from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import logging
import os
import sqlite3
import sys
import threading
from contextlib import AbstractContextManager
from pathlib import Path

from app.storage.database import Database, configure_connection
from app.utils.hash import sha256_hex

from .settings_models import SettingsModelsMixin
from .settings_preferences import SettingsPreferencesMixin
from .settings_types import (
    AGENT_CREDENTIAL_SLOT,
    AGENT_MODEL_IDS,
    EMBEDDING_CREDENTIAL_SLOT,
    MODEL_CREDENTIAL_SLOT,
    TTS_CREDENTIAL_SLOT,
    TTS_KEY_STATE_PREFIX,
    AgentModelSettings,
    ConfigurationError,
    CredentialSlot,
    CredentialStore,
    CredentialStoreError,
    EmbeddingConfig,
    ModelConfig,
    ModelKeyStatus,
    is_supported_model_provider,
    mask_secret,
    normalize_agent_id,
    normalize_model_provider,
    normalize_tts_provider,
    tts_key_state_key,
)


__all__ = [
    "AGENT_CREDENTIAL_SLOT",
    "AGENT_MODEL_IDS",
    "EMBEDDING_CREDENTIAL_SLOT",
    "MODEL_CREDENTIAL_SLOT",
    "TTS_CREDENTIAL_SLOT",
    "AgentModelSettings",
    "ConfigurationError",
    "CredentialSlot",
    "CredentialStoreError",
    "EmbeddingConfig",
    "InMemoryCredentialStore",
    "LocalCredentialStore",
    "ModelConfig",
    "ModelKeyStatus",
    "SettingsStore",
    "initialize_settings_store",
    "is_supported_model_provider",
    "mask_secret",
    "normalize_agent_id",
    "normalize_model_provider",
    "normalize_tts_provider",
    "tts_key_state_key",
]


logger = logging.getLogger(__name__)


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def put(self, ref: str, secret: str) -> None:
        self._secrets[ref] = secret

    def get(self, ref: str) -> str | None:
        return self._secrets.get(ref)

    def exists(self, ref: str) -> bool:
        return ref in self._secrets


class LocalCredentialStore:
    """File credential vault with a self-describing protection scheme."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @classmethod
    def for_database(cls, db_path: str | Path) -> LocalCredentialStore:
        path = Path(db_path)
        return cls(path.with_suffix(f"{path.suffix}.credentials"))

    def put(self, ref: str, secret: str) -> None:
        if not _dpapi_available() and not _allow_insecure_file_credentials():
            raise CredentialStoreError(
                "当前平台不支持安全凭据存储（仅支持 Windows DPAPI）。"
                "API Key 未被保存。如需在非 Windows 平台运行，"
                "请通过环境变量 AGENT_PET_API_KEY 传入凭据。"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        scheme = "dpapi" if _dpapi_available() else "plain"
        path = self._path_for(ref, scheme=scheme)
        data = secret.encode("utf-8")
        protected = _dpapi_protect(data) if scheme == "dpapi" else data
        document = {
            "version": 1,
            "scheme": scheme,
            "payload": base64.b64encode(protected).decode("ascii"),
        }
        path.write_text(json.dumps(document, separators=(",", ":")), encoding="ascii")
        try:
            os.chmod(path, 0o600)
        except OSError as exc:
            logger.warning(
                "凭据文件权限收紧失败，文件可能处于宽权限状态",
                extra={"path": str(path), "error": str(exc)},
            )
            path.unlink(missing_ok=True)
            raise CredentialStoreError("凭据文件权限设置失败，API Key 未被保存。") from exc
        for stale_path in self._candidate_paths(ref):
            if stale_path != path:
                stale_path.unlink(missing_ok=True)

    def get(self, ref: str) -> str | None:
        path = next((candidate for candidate in self._candidate_paths(ref) if candidate.exists()), None)
        if path is None:
            return None
        raw_bytes = path.read_bytes()
        try:
            document = json.loads(raw_bytes.decode("ascii"))
            scheme = str(document["scheme"])
            protected = base64.b64decode(str(document["payload"]), validate=True)
        except (UnicodeDecodeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            # Read-only compatibility for files created before the v1 envelope.
            scheme = "dpapi" if path.suffix == ".dpapi" else "plain"
            protected = base64.b64decode(raw_bytes, validate=True)
        if scheme == "dpapi":
            if not _dpapi_available():
                raise CredentialStoreError(
                    "该凭据使用 Windows DPAPI 加密，当前平台不支持解密；"
                    "凭据仍存在但不可读取。"
                )
            data = _dpapi_unprotect(protected)
        elif scheme == "plain":
            data = protected
        else:
            raise CredentialStoreError(f"不支持的凭据文件方案：{scheme}")
        return data.decode("utf-8")

    def exists(self, ref: str) -> bool:
        return any(path.exists() for path in self._candidate_paths(ref))

    def _path_for(self, ref: str, *, scheme: str) -> Path:
        suffix = ".dpapi" if scheme == "dpapi" else ".plaintext"
        return self.root / f"{sha256_hex(ref)}{suffix}"

    def _candidate_paths(self, ref: str) -> tuple[Path, ...]:
        digest = sha256_hex(ref)
        return (
            self.root / f"{digest}.dpapi",
            self.root / f"{digest}.plaintext",
            self.root / f"{digest}.secret",
        )


_DATA_MIGRATIONS_DONE: set[str] = set()
_DATA_MIGRATIONS_LOCK = threading.Lock()


class SettingsStore(SettingsPreferencesMixin, SettingsModelsMixin):
    """Facade composing focused settings domains over one request-scoped session."""

    def __init__(
        self,
        db: str | Path | sqlite3.Connection | Database,
        credential_store: CredentialStore | None = None,
    ):
        self._database: Database | None
        self._session_context: AbstractContextManager[sqlite3.Connection] | None = None
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        if isinstance(db, sqlite3.Connection):
            self._database = None
            self.conn = db
            configure_connection(self.conn)
            database_path: str | Path | None = None
        else:
            self._database = db if isinstance(db, Database) else Database(db)
            self._session_context = self._database.session()
            self.conn = self._session_context.__enter__()
            database_path = self._database.path
        if credential_store is not None:
            self.credentials = credential_store
        elif database_path is None:
            self.credentials = InMemoryCredentialStore()
        else:
            self.credentials = LocalCredentialStore.for_database(database_path)
        self._run_data_migrations_once(database_path)

    def close(self) -> None:
        session = self._session_context
        self._session_context = None
        if self._owns_connection and session is not None:
            session.__exit__(None, None, None)

    def _run_data_migrations_once(self, database_path: str | Path | None) -> None:
        if database_path is None:
            self._run_data_migrations()
            return
        key = str(Path(database_path).resolve())
        with _DATA_MIGRATIONS_LOCK:
            if key in _DATA_MIGRATIONS_DONE:
                return
            self._run_data_migrations()
            _DATA_MIGRATIONS_DONE.add(key)

    def _run_data_migrations(self) -> None:
        if self._table_exists("agent_model_configs"):
            self._migrate_legacy_retrieval_agent_configs()
        self._remove_persisted_masked_values()
        self.conn.commit()

    def _remove_persisted_masked_values(self) -> None:
        for table in ("model_keys", "embedding_keys", "agent_model_configs"):
            if self._table_exists(table):
                self.conn.execute(f"UPDATE {table} SET masked = NULL WHERE masked IS NOT NULL")
        if not self._table_exists("app_state"):
            return
        rows = self.conn.execute(
            "SELECT key, value FROM app_state WHERE key LIKE ?",
            (f"{TTS_KEY_STATE_PREFIX}%",),
        ).fetchall()
        for row in rows:
            try:
                value = json.loads(str(row["value"]))
            except (TypeError, ValueError):
                continue
            if not isinstance(value, dict) or "masked" not in value:
                continue
            value.pop("masked", None)
            self.conn.execute(
                "UPDATE app_state SET value = ? WHERE key = ?",
                (json.dumps(value, ensure_ascii=False), row["key"]),
            )

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None


def initialize_settings_store(database: Database) -> None:
    """Run idempotent legacy data cleanup once during application startup."""
    store = SettingsStore(database)
    store.close()


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _allow_insecure_file_credentials() -> bool:
    return os.environ.get("AGENT_PET_ALLOW_INSECURE_FILE_CREDENTIALS") == "1"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob._buffer = buffer  # type: ignore[attr-defined]
    return blob


def _bytes_from_blob(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _dpapi_protect(data: bytes) -> bytes:
    in_blob = _blob_from_bytes(data)
    out_blob = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("系统凭据加密失败")
    return _bytes_from_blob(out_blob)


def _dpapi_unprotect(data: bytes) -> bytes:
    in_blob = _blob_from_bytes(data)
    out_blob = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("系统凭据解密失败")
    return _bytes_from_blob(out_blob)
