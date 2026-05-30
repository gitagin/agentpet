from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import logging
import os
import sys
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import DEFAULT_CHAT_MODEL, get_settings
from app.models.api import (
    AgentModelHealth,
    AutomationSettingsRequest,
    AutomationSettingsResponse,
    ModelHealthResponse,
)
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


AGENT_MODEL_IDS = (
    "chat_agent",
    "semantic_analysis_agent",
    "diary_memory_extractor_agent",
    "memory_retrieval_agent",
    "knowledge_retrieval_agent",
    "wiki_manager_agent",
    "memory_proposal_agent",
    "continuity_agent",
    "task_agent",
)
_LEGACY_RETRIEVAL_AGENT_MIGRATIONS = (
    ("knowledge_agent", ("knowledge_retrieval_agent",)),
    ("context_retrieval_agent", ("memory_retrieval_agent", "knowledge_retrieval_agent")),
)
_LEGACY_RETRIEVAL_AGENT_IDS = tuple(
    legacy_agent_id for legacy_agent_id, _target_agent_ids in _LEGACY_RETRIEVAL_AGENT_MIGRATIONS
)
_OPENAI_COMPATIBLE_PROVIDER_ALIASES = {
    "openai compatible",
    "openai-compatible",
    "openai_compatible",
    "openai兼容",
    "openai 兼容",
    "openai兼容接口",
    "openai 兼容接口",
    "openai兼容协议",
    "openai 兼容协议",
}
SUPPORTED_MODEL_PROVIDERS = {"openai", "openai-compatible"}
logger = logging.getLogger(__name__)


class CredentialStoreError(RuntimeError):
    pass


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelKeyStatus:
    provider: str | None
    configured: bool
    masked: str | None = None


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    base_url: str
    model: str


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    base_url: str
    model: str
    dimensions: int | None = None


@dataclass(frozen=True)
class AgentModelSettings:
    agent_id: str
    provider: str | None
    base_url: str | None
    model: str | None
    enabled: bool
    configured: bool
    masked: str | None = None


def normalize_model_provider(provider: str) -> str:
    value = provider.strip()
    normalized = value.lower().replace("－", "-").replace("—", "-").replace("–", "-")
    normalized = " ".join(normalized.split())
    if normalized in _OPENAI_COMPATIBLE_PROVIDER_ALIASES:
        return "openai-compatible"
    return value


def is_supported_model_provider(provider: str) -> bool:
    return normalize_model_provider(provider).strip().lower() in SUPPORTED_MODEL_PROVIDERS


class CredentialStore(Protocol):
    def put(self, ref: str, secret: str) -> None:
        pass

    def get(self, ref: str) -> str | None:
        pass

    def exists(self, ref: str) -> bool:
        pass


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
    """Small local credential store. On Windows, file contents are DPAPI-protected."""

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
        path = self._path_for(ref)
        data = secret.encode("utf-8")
        protected = _dpapi_protect(data) if _dpapi_available() else data
        path.write_bytes(base64.b64encode(protected))
        try:
            os.chmod(path, 0o600)
        except OSError as exc:
            logger.warning(
                "凭据文件权限收紧失败，文件可能处于宽权限状态",
                extra={"path": str(path), "error": str(exc)},
            )
            path.unlink(missing_ok=True)
            raise CredentialStoreError("凭据文件权限设置失败，API Key 未被保存。") from exc

    def get(self, ref: str) -> str | None:
        path = self._path_for(ref)
        if not path.exists():
            return None
        protected = base64.b64decode(path.read_bytes())
        data = _dpapi_unprotect(protected) if _dpapi_available() else protected
        return data.decode("utf-8")

    def exists(self, ref: str) -> bool:
        return self._path_for(ref).exists()

    def _path_for(self, ref: str) -> Path:
        digest = sha256_hex(ref)
        suffix = ".dpapi" if _dpapi_available() else ".secret"
        return self.root / f"{digest}{suffix}"


class SettingsStore:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        credential_store: CredentialStore | None = None,
    ):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        if credential_store is not None:
            self.credentials = credential_store
        elif isinstance(db, sqlite3.Connection):
            self.credentials = InMemoryCredentialStore()
        else:
            self.credentials = LocalCredentialStore.for_database(db)
        self._run_data_migrations()

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def _run_data_migrations(self) -> None:
        if self._table_exists("agent_model_configs"):
            self._migrate_legacy_retrieval_agent_configs()
            self.conn.commit()

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def get_automation_settings(self) -> AutomationSettingsResponse:
        row = self.conn.execute("SELECT * FROM automation_settings WHERE id = 1").fetchone()
        if row is None:
            return AutomationSettingsResponse()
        return AutomationSettingsResponse(
            auto_chat_diary=bool(row["auto_chat_diary"]),
            auto_structured_memory=bool(row["auto_structured_memory"]),
            auto_long_term_memory=bool(row["auto_long_term_memory"]),
            auto_wiki_organize=bool(row["auto_wiki_organize"]),
            use_negotiation=bool(row["use_negotiation"]),
            max_rounds=int(row["max_rounds"]),
            high_risk_confirmation_required=bool(row["high_risk_confirmation_required"]),
            updated_at=str(row["updated_at"]),
        )

    def set_automation_settings(self, settings: AutomationSettingsRequest) -> AutomationSettingsResponse:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO automation_settings (
                    id, auto_chat_diary, auto_structured_memory, auto_long_term_memory,
                    auto_wiki_organize, use_negotiation, max_rounds,
                    high_risk_confirmation_required, created_at, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    auto_chat_diary = excluded.auto_chat_diary,
                    auto_structured_memory = excluded.auto_structured_memory,
                    auto_long_term_memory = excluded.auto_long_term_memory,
                    auto_wiki_organize = excluded.auto_wiki_organize,
                    use_negotiation = excluded.use_negotiation,
                    max_rounds = excluded.max_rounds,
                    high_risk_confirmation_required = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    1 if settings.auto_chat_diary else 0,
                    1 if settings.auto_structured_memory else 0,
                    1 if settings.auto_long_term_memory else 0,
                    1 if settings.auto_wiki_organize else 0,
                    1 if settings.use_negotiation else 0,
                    settings.max_rounds,
                    now,
                    now,
                ),
            )
        return self.get_automation_settings()

    def _migrate_legacy_retrieval_agent_configs(self) -> None:
        for legacy_agent_id, target_agent_ids in _LEGACY_RETRIEVAL_AGENT_MIGRATIONS:
            self._copy_legacy_agent_config(legacy_agent_id, target_agent_ids)
        self.conn.execute(
            f"""
            DELETE FROM agent_model_configs
            WHERE agent_id IN ({",".join("?" for _agent_id in _LEGACY_RETRIEVAL_AGENT_IDS)})
            """,
            _LEGACY_RETRIEVAL_AGENT_IDS,
        )

    def _copy_legacy_agent_config(
        self,
        legacy_agent_id: str,
        target_agent_ids: tuple[str, ...],
    ) -> None:
        legacy = self.conn.execute(
            """
            SELECT provider, base_url, model, masked, credential_ref, enabled, created_at, updated_at
            FROM agent_model_configs
            WHERE agent_id = ?
            """,
            (legacy_agent_id,),
        ).fetchone()
        if legacy is None:
            return
        for target_agent_id in target_agent_ids:
            existing = self.conn.execute(
                "SELECT agent_id FROM agent_model_configs WHERE agent_id = ?",
                (target_agent_id,),
            ).fetchone()
            if existing is not None:
                continue
            self.conn.execute(
                """
                INSERT INTO agent_model_configs
                    (agent_id, provider, base_url, model, masked, credential_ref, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_agent_id,
                    legacy["provider"],
                    legacy["base_url"],
                    legacy["model"],
                    legacy["masked"],
                    legacy["credential_ref"],
                    legacy["enabled"],
                    legacy["created_at"],
                    legacy["updated_at"],
                ),
            )

    def set_model_key(self, provider: str, api_key: str) -> ModelKeyStatus:
        normalized_provider = normalize_model_provider(provider)
        now = utc_now_iso()
        masked = mask_secret(api_key)
        credential_ref = credential_ref_for_provider(normalized_provider)
        self.credentials.put(credential_ref, api_key)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO model_keys (provider, masked, credential_ref, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    masked = excluded.masked,
                    credential_ref = excluded.credential_ref,
                    updated_at = excluded.updated_at
                """,
                (normalized_provider, masked, credential_ref, now, now),
            )
        return ModelKeyStatus(provider=normalized_provider, configured=True, masked=masked)

    def get_model_key_status(self) -> ModelKeyStatus:
        row = self.conn.execute(
            """
            SELECT provider, masked, credential_ref
            FROM model_keys
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return ModelKeyStatus(provider=None, configured=False)
        return ModelKeyStatus(
            provider=row["provider"],
            configured=self.credentials.exists(row["credential_ref"]),
            masked=row["masked"],
        )

    def get_model_key(self, provider: str) -> str | None:
        row = self.conn.execute(
            "SELECT credential_ref FROM model_keys WHERE provider = ?",
            (provider.strip(),),
        ).fetchone()
        if row is None:
            return None
        return self.credentials.get(row["credential_ref"])

    def set_embedding_key(self, provider: str, api_key: str) -> ModelKeyStatus:
        normalized_provider = normalize_model_provider(provider)
        now = utc_now_iso()
        masked = mask_secret(api_key)
        credential_ref = credential_ref_for_embedding_provider(normalized_provider)
        self.credentials.put(credential_ref, api_key)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO embedding_keys (provider, masked, credential_ref, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    masked = excluded.masked,
                    credential_ref = excluded.credential_ref,
                    updated_at = excluded.updated_at
                """,
                (normalized_provider, masked, credential_ref, now, now),
            )
        return ModelKeyStatus(provider=normalized_provider, configured=True, masked=masked)

    def get_embedding_key_status(self) -> ModelKeyStatus:
        row = self.conn.execute(
            """
            SELECT provider, masked, credential_ref
            FROM embedding_keys
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return ModelKeyStatus(provider=None, configured=False)
        return ModelKeyStatus(
            provider=row["provider"],
            configured=self.credentials.exists(row["credential_ref"]),
            masked=row["masked"],
        )

    def get_embedding_key(self, provider: str) -> str | None:
        row = self.conn.execute(
            "SELECT credential_ref FROM embedding_keys WHERE provider = ?",
            (provider.strip(),),
        ).fetchone()
        if row is None:
            return None
        return self.credentials.get(row["credential_ref"])

    def set_embedding_config(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        dimensions: int | None = None,
    ) -> EmbeddingConfig:
        normalized = EmbeddingConfig(
            provider=normalize_model_provider(provider),
            base_url=base_url.strip().rstrip("/"),
            model=model.strip(),
            dimensions=dimensions,
        )
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO embedding_config (id, provider, base_url, model, dimensions, created_at, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    provider = excluded.provider,
                    base_url = excluded.base_url,
                    model = excluded.model,
                    dimensions = excluded.dimensions,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized.provider,
                    normalized.base_url,
                    normalized.model,
                    normalized.dimensions,
                    now,
                    now,
                ),
            )
        return normalized

    def get_embedding_config(
        self,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
        default_dimensions: int | None = None,
    ) -> EmbeddingConfig:
        row = self.conn.execute(
            "SELECT provider, base_url, model, dimensions FROM embedding_config WHERE id = 1"
        ).fetchone()
        if row is None:
            return EmbeddingConfig(
                provider=default_provider,
                base_url=default_base_url.rstrip("/"),
                model=default_model,
                dimensions=default_dimensions,
            )
        return EmbeddingConfig(
            provider=row["provider"],
            base_url=row["base_url"],
            model=row["model"],
            dimensions=row["dimensions"],
        )

    def set_model_config(self, *, provider: str, base_url: str, model: str) -> ModelConfig:
        normalized = ModelConfig(
            provider=normalize_model_provider(provider),
            base_url=base_url.strip().rstrip("/"),
            model=model.strip(),
        )
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO model_config (id, provider, base_url, model, created_at, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    provider = excluded.provider,
                    base_url = excluded.base_url,
                    model = excluded.model,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized.provider,
                    normalized.base_url,
                    normalized.model,
                    now,
                    now,
                ),
            )
        return normalized

    def get_model_config(
        self,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
    ) -> ModelConfig:
        row = self.conn.execute(
            "SELECT provider, base_url, model FROM model_config WHERE id = 1"
        ).fetchone()
        if row is None:
            return ModelConfig(
                provider=default_provider,
                base_url=default_base_url.rstrip("/"),
                model=default_model,
            )
        return ModelConfig(
            provider=row["provider"],
            base_url=row["base_url"],
            model=row["model"],
        )

    def set_agent_model_key(
        self,
        *,
        agent_id: str,
        provider: str,
        api_key: str,
    ) -> ModelKeyStatus:
        normalized_agent_id = normalize_agent_id(agent_id)
        normalized_provider = normalize_model_provider(provider)
        now = utc_now_iso()
        masked = mask_secret(api_key)
        credential_ref = credential_ref_for_agent(normalized_agent_id)
        current = self.conn.execute(
            "SELECT base_url, model, enabled FROM agent_model_configs WHERE agent_id = ?",
            (normalized_agent_id,),
        ).fetchone()
        global_config = self.conn.execute(
            "SELECT base_url, model FROM model_config WHERE id = 1"
        ).fetchone()
        base_url = (
            str(current["base_url"])
            if current is not None
            else str(global_config["base_url"]) if global_config is not None else ""
        )
        if api_key and not base_url.strip():
            raise ConfigurationError(
                "已配置 API Key 但未配置 Base URL，无法安全路由请求。"
                "请在设置中填写对应的 Base URL。"
            )
        model = (
            str(current["model"])
            if current is not None
            else str(global_config["model"]) if global_config is not None else DEFAULT_CHAT_MODEL
        )
        enabled = int(current["enabled"]) if current is not None else 1
        self.credentials.put(credential_ref, api_key)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO agent_model_configs
                    (agent_id, provider, base_url, model, masked, credential_ref, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    provider = excluded.provider,
                    masked = excluded.masked,
                    credential_ref = excluded.credential_ref,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_agent_id,
                    normalized_provider,
                    base_url,
                    model,
                    masked,
                    credential_ref,
                    enabled,
                    now,
                    now,
                ),
            )
        return ModelKeyStatus(provider=normalized_provider, configured=True, masked=masked)

    def get_agent_model_key_status(
        self,
        agent_id: str,
        *,
        provider: str | None = None,
    ) -> ModelKeyStatus:
        normalized_agent_id = normalize_agent_id(agent_id)
        if provider is not None:
            row = self.conn.execute(
                """
                SELECT provider, masked, credential_ref
                FROM agent_model_configs
                WHERE agent_id = ? AND provider = ?
                """,
                (normalized_agent_id, provider.strip()),
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT provider, masked, credential_ref
                FROM agent_model_configs
                WHERE agent_id = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (normalized_agent_id,),
            ).fetchone()
        if row is None:
            return ModelKeyStatus(provider=None, configured=False)
        return ModelKeyStatus(
            provider=row["provider"],
            configured=self.credentials.exists(row["credential_ref"]),
            masked=row["masked"],
        )

    def get_agent_model_key(self, *, agent_id: str, provider: str) -> str | None:
        normalized_agent_id = normalize_agent_id(agent_id)
        row = self.conn.execute(
            """
            SELECT credential_ref
            FROM agent_model_configs
            WHERE agent_id = ? AND provider = ?
            """,
            (normalized_agent_id, provider.strip()),
        ).fetchone()
        if row is None:
            return None
        return self.credentials.get(row["credential_ref"])

    def set_agent_model_config(
        self,
        *,
        agent_id: str,
        provider: str,
        base_url: str,
        model: str,
        enabled: bool = True,
    ) -> ModelConfig:
        normalized_agent_id = normalize_agent_id(agent_id)
        normalized = ModelConfig(
            provider=normalize_model_provider(provider),
            base_url=base_url.strip().rstrip("/"),
            model=model.strip(),
        )
        now = utc_now_iso()
        current = self.conn.execute(
            "SELECT masked, credential_ref FROM agent_model_configs WHERE agent_id = ?",
            (normalized_agent_id,),
        ).fetchone()
        masked = current["masked"] if current is not None else None
        credential_ref = (
            current["credential_ref"]
            if current is not None
            else credential_ref_for_agent(normalized_agent_id)
        )
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO agent_model_configs
                    (agent_id, provider, base_url, model, masked, credential_ref, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    provider = excluded.provider,
                    base_url = excluded.base_url,
                    model = excluded.model,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_agent_id,
                    normalized.provider,
                    normalized.base_url,
                    normalized.model,
                    masked,
                    credential_ref,
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return normalized

    def get_agent_model_config(
        self,
        agent_id: str,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
    ) -> ModelConfig | None:
        normalized_agent_id = normalize_agent_id(agent_id)
        row = self.conn.execute(
            """
            SELECT provider, base_url, model
            FROM agent_model_configs
            WHERE agent_id = ?
            """,
            (normalized_agent_id,),
        ).fetchone()
        if row is None:
            return None
        return ModelConfig(
            provider=row["provider"],
            base_url=row["base_url"],
            model=row["model"],
        )

    def is_agent_model_enabled(self, agent_id: str) -> bool:
        normalized_agent_id = normalize_agent_id(agent_id)
        row = self.conn.execute(
            "SELECT enabled FROM agent_model_configs WHERE agent_id = ?",
            (normalized_agent_id,),
        ).fetchone()
        return bool(row["enabled"]) if row is not None else False

    def list_agent_model_settings(
        self,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
    ) -> list[AgentModelSettings]:
        agents = []
        for agent_id in AGENT_MODEL_IDS:
            key_status = self.get_agent_model_key_status(agent_id)
            config = self.get_agent_model_config(
                agent_id,
                default_provider=key_status.provider or default_provider,
                default_base_url=default_base_url,
                default_model=default_model,
            )
            config_row = self.conn.execute(
                "SELECT enabled FROM agent_model_configs WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            enabled = bool(config_row["enabled"]) if config_row is not None else False
            provider_status = ModelKeyStatus(provider=None, configured=False)
            if config is not None:
                provider_status = self.get_agent_model_key_status(
                    agent_id,
                    provider=config.provider,
                )
                if not provider_status.configured and key_status.configured:
                    provider_status = key_status
            agents.append(
                AgentModelSettings(
                    agent_id=agent_id,
                    provider=config.provider if config is not None else None,
                    base_url=config.base_url if config is not None else None,
                    model=config.model if config is not None else None,
                    enabled=enabled,
                    configured=bool(config is not None and enabled and provider_status.configured),
                    masked=provider_status.masked,
                )
            )
        return agents

    def get_model_health_status(self) -> ModelHealthResponse:
        defaults = get_settings()
        default_config = ModelConfig(
            provider="openai-compatible",
            base_url=defaults.model_base_url.rstrip("/"),
            model=defaults.chat_model,
        )
        global_status = self.get_model_key_status()
        global_config_row = self.conn.execute(
            "SELECT provider, base_url, model FROM model_config WHERE id = 1"
        ).fetchone()
        global_configured = global_config_row is not None and global_status.configured
        global_config = (
            ModelConfig(
                provider=global_config_row["provider"],
                base_url=global_config_row["base_url"],
                model=global_config_row["model"],
            )
            if global_config_row is not None
            else default_config
        )
        agents_configured = 0
        agents_fallback_to_global = 0
        agents_fallback_to_default = 0
        agent_details: list[AgentModelHealth] = []
        for agent_id in AGENT_MODEL_IDS:
            row = self.conn.execute(
                """
                SELECT provider, base_url, model, enabled
                FROM agent_model_configs
                WHERE agent_id = ?
                """,
                (agent_id,),
            ).fetchone()
            agent_config = (
                ModelConfig(
                    provider=row["provider"],
                    base_url=row["base_url"],
                    model=row["model"],
                )
                if row is not None
                else None
            )
            has_agent_override = bool(
                row is not None
                and row["enabled"]
                and agent_config is not None
                and not _model_config_matches(agent_config, global_config if global_configured else default_config)
            )
            if has_agent_override:
                source = "agent_specific"
                model = agent_config.model
                agents_configured += 1
            elif global_configured:
                source = "global_fallback"
                model = global_config.model
                agents_fallback_to_global += 1
            else:
                source = "hardcoded_default"
                model = default_config.model
                agents_fallback_to_default += 1
            agent_details.append(
                AgentModelHealth(
                    agent_id=agent_id,
                    source=source,
                    model=model,
                )
            )
        return ModelHealthResponse(
            global_configured=global_configured,
            agents_configured=agents_configured,
            agents_fallback_to_global=agents_fallback_to_global,
            agents_fallback_to_default=agents_fallback_to_default,
            agent_details=agent_details,
        )


def _model_config_matches(left: ModelConfig, right: ModelConfig) -> bool:
    return (
        normalize_model_provider(left.provider).strip().lower()
        == normalize_model_provider(right.provider).strip().lower()
        and left.base_url.strip().rstrip("/") == right.base_url.strip().rstrip("/")
        and left.model.strip() == right.model.strip()
    )


def credential_ref_for_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    digest = sha256_hex(normalized)
    return f"model-key:{digest}"


def credential_ref_for_embedding_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    digest = sha256_hex(normalized)
    return f"embedding-key:{digest}"


def credential_ref_for_agent(agent_id: str) -> str:
    return f"model-key:agent:{normalize_agent_id(agent_id)}"


def normalize_agent_id(agent_id: str) -> str:
    normalized = getattr(agent_id, "value", str(agent_id)).strip()
    if normalized not in AGENT_MODEL_IDS:
        raise ValueError(f"unsupported agent_id: {agent_id}")
    return normalized


def mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"****{secret[-4:]}"


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
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise OSError("系统凭据加密失败")
    return _bytes_from_blob(out_blob)


def _dpapi_unprotect(data: bytes) -> bytes:
    in_blob = _blob_from_bytes(data)
    out_blob = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise OSError("系统凭据解密失败")
    return _bytes_from_blob(out_blob)
