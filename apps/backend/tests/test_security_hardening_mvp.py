from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.backend.tests._schema import migrate_db
from tests.conftest import FORBIDDEN_HEALTH_KEYS, auth_headers, iter_keys


def _auth() -> dict[str, str]:
    return auth_headers("hardening-token")


def _iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _iter_strings(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, str):
        yield value


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory(session_token="hardening-token") as test_client:
        yield test_client


def _bind_vault(client: TestClient, vault: Path) -> str:
    response = client.post(
        "/api/vaults/init",
        headers=_auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    assert response.status_code == 200
    return str(response.json()["vault_id"])


def test_model_key_endpoint_never_returns_plaintext_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import settings

    monkeypatch.setattr(settings, "_dpapi_available", lambda: True)
    monkeypatch.setattr(settings, "_dpapi_protect", lambda data: b"protected-" + data)
    secret = "sk-live-super-secret-model-key-1234567890"

    response = client.put(
        "/api/settings/model-key",
        headers=_auth(),
        json={"provider": "openai-compatible", "api_key": secret},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "configured"
    assert payload["masked"] != secret
    serialized = response.text
    assert secret not in serialized
    assert "super-secret-model-key" not in serialized
    assert "api_key" not in {key.lower() for key in iter_keys(payload)}


def test_model_key_secret_uses_replaceable_credential_store(tmp_path: Path) -> None:
    from app.services.settings import InMemoryCredentialStore, SettingsStore

    db_path = migrate_db(tmp_path / "state.sqlite3")
    credentials = InMemoryCredentialStore()
    store = SettingsStore(db_path, credential_store=credentials)
    secret = "sk-direct-store-secret-1234567890"

    status = store.set_model_key("openai-compatible", secret)

    assert status.configured is True
    assert store.get_model_key("openai-compatible") == secret
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_keys)").fetchall()}
        row = conn.execute("SELECT * FROM model_keys").fetchone()

    assert "api_key" not in columns
    assert set(columns) == {"provider", "masked", "credential_ref", "created_at", "updated_at"}
    assert row["masked"] is None
    assert secret.encode("utf-8") not in db_path.read_bytes()


def test_credential_slots_preserve_historical_reference_formats() -> None:
    from app.services.settings import (
        AGENT_CREDENTIAL_SLOT,
        EMBEDDING_CREDENTIAL_SLOT,
        MODEL_CREDENTIAL_SLOT,
        TTS_CREDENTIAL_SLOT,
    )
    from app.utils.hash import sha256_hex

    provider = "openai-compatible"
    assert MODEL_CREDENTIAL_SLOT.ref(provider) == f"model-key:{sha256_hex(provider)}"
    assert EMBEDDING_CREDENTIAL_SLOT.ref(provider) == f"embedding-key:{sha256_hex(provider)}"
    assert TTS_CREDENTIAL_SLOT.ref(provider) == f"tts-key:{sha256_hex(provider)}"
    assert AGENT_CREDENTIAL_SLOT.ref("chat_agent") == "model-key:agent:chat_agent"


def test_settings_domains_are_split_and_all_credential_slots_roundtrip(tmp_path: Path) -> None:
    from app.services.settings import InMemoryCredentialStore, SettingsStore

    services_dir = Path(__file__).parents[1] / "app" / "services"
    implementation_modules = (
        "settings_store.py",
        "settings_types.py",
        "settings_preferences.py",
        "settings_models.py",
    )
    assert all(
        len((services_dir / module).read_text(encoding="utf-8").splitlines()) <= 700
        for module in implementation_modules
    )

    db_path = migrate_db(tmp_path / "state.sqlite3")
    credentials = InMemoryCredentialStore()
    store = SettingsStore(db_path, credential_store=credentials)
    try:
        store.set_model_key("openai-compatible", "sk-model-credential")
        store.set_embedding_key("openai-compatible", "sk-embedding-credential")
        store.set_tts_key("xiaomi-mimo", "sk-tts-credential")
        store.set_agent_model_config(
            agent_id="chat_agent",
            provider="openai-compatible",
            base_url="https://example.test/v1",
            model="chat-model",
        )
        store.set_agent_model_key(
            agent_id="chat_agent",
            provider="openai-compatible",
            api_key="sk-agent-credential",
        )

        assert store.get_model_key("openai-compatible") == "sk-model-credential"
        assert store.get_embedding_key("openai-compatible") == "sk-embedding-credential"
        assert store.get_tts_key("xiaomi-mimo") == "sk-tts-credential"
        assert store.get_agent_model_key(
            agent_id="chat_agent",
            provider="openai-compatible",
        ) == "sk-agent-credential"
    finally:
        store.close()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT masked FROM model_keys").fetchone()[0] is None
        assert conn.execute("SELECT masked FROM embedding_keys").fetchone()[0] is None
        assert conn.execute("SELECT masked FROM agent_model_configs").fetchone()[0] is None
        tts_metadata = conn.execute(
            "SELECT value FROM app_state WHERE key LIKE 'tts_key:%'"
        ).fetchone()[0]
    assert "masked" not in json.loads(tts_metadata)


def test_dpapi_vault_moved_to_unsupported_platform_is_not_reported_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import settings
    from app.services.settings import CredentialStoreError, SettingsStore

    db_path = migrate_db(tmp_path / "state.sqlite3")
    monkeypatch.setattr(settings, "_dpapi_available", lambda: True)
    monkeypatch.setattr(settings, "_dpapi_protect", lambda data: b"protected-" + data)
    windows_store = SettingsStore(db_path)
    try:
        windows_store.set_model_key("openai-compatible", "sk-cross-platform")
    finally:
        windows_store.close()

    credential_file = next(db_path.with_suffix(".sqlite3.credentials").glob("*.dpapi"))
    assert json.loads(credential_file.read_text(encoding="ascii"))["scheme"] == "dpapi"

    monkeypatch.setattr(settings, "_dpapi_available", lambda: False)
    migrated_store = SettingsStore(db_path)
    try:
        with pytest.raises(CredentialStoreError, match="当前平台不支持解密"):
            migrated_store.get_model_key_status()
    finally:
        migrated_store.close()


def test_settings_api_reports_unsupported_dpapi_platform(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import settings

    monkeypatch.setattr(settings, "_dpapi_available", lambda: True)
    monkeypatch.setattr(settings, "_dpapi_protect", lambda data: b"protected-" + data)
    configured = client.put(
        "/api/settings/model-key",
        headers=_auth(),
        json={"provider": "openai-compatible", "api_key": "sk-cross-platform-api"},
    )
    assert configured.status_code == 200

    monkeypatch.setattr(settings, "_dpapi_available", lambda: False)
    status_response = client.get("/api/settings", headers=_auth())

    assert status_response.status_code == 503
    assert "当前平台不支持解密" in status_response.json()["error"]["message"]
    assert "未配置" not in status_response.text


def test_local_credential_store_rejects_unprotected_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import settings
    from app.services.settings import CredentialStoreError, LocalCredentialStore

    monkeypatch.setattr(settings, "_dpapi_available", lambda: False)
    store = LocalCredentialStore(tmp_path / "credentials")

    with pytest.raises(CredentialStoreError, match="仅支持 Windows DPAPI"):
        store.put("model-key:test", "sk-unprotected-secret")

    assert not any((tmp_path / "credentials").glob("*"))


def test_mask_secret_only_reveals_last_four_characters() -> None:
    from app.services.settings import mask_secret

    assert mask_secret("sk-abcdefghijklmnopqrstuvwxyz123456") == "****3456"
    assert not mask_secret("sk-abcdefghijklmnopqrstuvwxyz123456").startswith("sk")


def test_local_credential_store_removes_file_when_chmod_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import settings
    from app.services.settings import CredentialStoreError, LocalCredentialStore

    monkeypatch.setattr(settings, "_dpapi_available", lambda: True)
    monkeypatch.setattr(settings, "_dpapi_protect", lambda data: b"protected-" + data)

    def raise_chmod(_path: Path, _mode: int) -> None:
        raise OSError("chmod failed")

    monkeypatch.setattr(settings.os, "chmod", raise_chmod)
    store = LocalCredentialStore(tmp_path / "credentials")

    with pytest.raises(CredentialStoreError, match="权限设置失败"):
        store.put("model-key:test", "sk-permission-secret")

    assert not any((tmp_path / "credentials").glob("*"))


def test_local_credential_store_uses_dpapi_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import settings
    from app.services.settings import LocalCredentialStore

    monkeypatch.setattr(settings, "_dpapi_available", lambda: True)
    monkeypatch.setattr(settings, "_dpapi_protect", lambda data: b"protected-" + data)
    monkeypatch.setattr(settings, "_dpapi_unprotect", lambda data: data.removeprefix(b"protected-"))
    store = LocalCredentialStore(tmp_path / "credentials")

    store.put("model-key:test", "sk-dpapi-secret")

    assert store.get("model-key:test") == "sk-dpapi-secret"
    files = list((tmp_path / "credentials").glob("*"))
    assert len(files) == 1
    assert files[0].suffix == ".dpapi"
    assert files[0].read_bytes() != b"sk-dpapi-secret"


def test_legacy_plaintext_model_key_migration_purges_sqlite_bytes(tmp_path: Path) -> None:
    from app.services.settings import SettingsStore
    from app.storage.database import Database, MigrationRunner

    db_path = tmp_path / "legacy.sqlite3"
    secret = "sk-legacy-plaintext-secret-1234567890"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE model_keys (
                provider TEXT PRIMARY KEY,
                api_key TEXT NOT NULL,
                masked TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO model_keys VALUES (?, ?, ?, ?, ?)",
            ("openai-compatible", secret, "sk...90", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        conn.commit()

    MigrationRunner(Database(db_path)).apply()
    status = SettingsStore(db_path).get_model_key_status()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_keys)").fetchall()}
        row = conn.execute("SELECT * FROM model_keys").fetchone()

    assert columns == {"provider", "masked", "credential_ref", "created_at", "updated_at"}
    assert row["credential_ref"].startswith("migrated-unavailable:")
    assert status.configured is False
    assert secret.encode("utf-8") not in db_path.read_bytes()


def test_health_remains_unauthenticated_and_does_not_leak_runtime_state(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import settings

    monkeypatch.setattr(settings, "_dpapi_available", lambda: True)
    monkeypatch.setattr(settings, "_dpapi_protect", lambda data: b"protected-" + data)
    vault = tmp_path / "Vault"
    _bind_vault(client, vault)
    secret = "sk-health-leak-check-1234567890"
    client.put(
        "/api/settings/model-key",
        headers=_auth(),
        json={"provider": "openai-compatible", "api_key": secret},
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    payload = response.json()
    assert payload["status"] == "ok"
    assert FORBIDDEN_HEALTH_KEYS.isdisjoint({key.lower() for key in iter_keys(payload)})
    body_values = set(_iter_strings(payload))
    assert str(vault) not in body_values
    assert secret not in response.text


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/vaults/status"),
        ("POST", "/api/vaults/init"),
        ("POST", "/api/vaults/example-vault/index"),
        ("GET", "/api/settings"),
        ("PUT", "/api/settings/model-key"),
        ("PUT", "/api/settings/model-config"),
        ("POST", "/api/settings/model-test"),
        ("POST", "/api/memory/search"),
        ("POST", "/api/memory/proposals"),
        ("GET", "/api/memory/proposals"),
        ("POST", "/api/memory/proposals/example-proposal/confirm"),
        ("POST", "/api/memory/proposals/example-proposal/reject"),
        ("POST", "/api/tasks"),
        ("GET", "/api/tasks"),
        ("POST", "/api/chat"),
        ("GET", "/api/chat/runs/example-run/events"),
        ("GET", "/api/chat/runs/example-run/stream"),
        ("GET", "/api/chat/stream/example-run"),
    ],
)
def test_protected_api_surface_requires_authentication(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.request(method, path, json={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_authorization"


def test_stream_endpoint_requires_auth_before_sse_is_started(client: TestClient) -> None:
    accepted = client.post(
        "/api/chat",
        headers=_auth(),
        json={"message": "hello"},
    )
    assert accepted.status_code == 200
    stream_url = accepted.json()["stream_url"]

    response = client.get(stream_url)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_authorization"
    assert not response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.parametrize(
    "target_path",
    [
        "../outside.md",
        "Inbox/../../outside.md",
        ".obsidian/config.md",
        "Inbox/.hidden.md",
        "Inbox/not-markdown.txt",
    ],
)
def test_memory_proposal_rejects_unsafe_target_paths(
    client: TestClient,
    tmp_path: Path,
    target_path: str,
) -> None:
    vault = tmp_path / "Vault"
    _bind_vault(client, vault)

    response = client.post(
        "/api/memory/proposals",
        headers=_auth(),
        json={
            "type": "fact",
            "content": "- safe content",
            "target_path": target_path,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "markdown_write_failed"
    assert not (tmp_path / "outside.md").exists()
    pending = client.get("/api/memory/proposals", headers=_auth())
    assert pending.status_code == 200
    assert pending.json()["proposals"] == []


def test_memory_proposal_rejects_absolute_target_path(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    _bind_vault(client, vault)
    outside = tmp_path / "outside.md"

    response = client.post(
        "/api/memory/proposals",
        headers=_auth(),
        json={
            "type": "fact",
            "content": "- safe content",
            "target_path": str(outside),
        },
    )

    assert response.status_code == 400
    assert "知识库根目录内的相对路径" in response.json()["error"]["message"]
    assert not outside.exists()


def test_vault_init_rejects_file_path_target(client: TestClient, tmp_path: Path) -> None:
    not_a_directory = tmp_path / "not-a-vault.md"
    not_a_directory.write_text("# Not a vault\n", encoding="utf-8")

    response = client.post(
        "/api/vaults/init",
        headers=_auth(),
        json={"path": str(not_a_directory), "create_if_missing": False, "confirmed": True},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_vault_path"


def test_sensitive_api_key_memory_proposal_is_rejected_before_pending_state(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    _bind_vault(client, vault)
    secret = "sk-sensitive-memory-proposal-1234567890"

    response = client.post(
        "/api/memory/proposals",
        headers=_auth(),
        json={
            "type": "fact",
            "content": f"- Remember this API key for me: {secret}",
            "target_path": "Inbox/Pending Memories.md",
        },
    )

    assert response.status_code in {400, 403, 422}
    assert secret not in response.text
    pending = client.get("/api/memory/proposals", headers=_auth())
    assert pending.status_code == 200
    assert pending.json()["proposals"] == []


def test_memory_graph_projection_omits_sensitive_raw_evidence(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    _bind_vault(client, vault)
    secret = "sk-memory-export-source-1234567890"
    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at, memory_type, entity_type, occurred_at,
                expires_at, metadata_json, importance
            )
            VALUES (
                'fact-export-sensitive', 'fact-export-key', 'fact-export-conflict',
                'preference', 'fruit', 'is', 'apple', 'active', 0.9,
                ?, 'user_message', 1, '2026-06-01T00:00:00Z',
                '2026-06-01T00:00:00Z', 'preference', 'preference',
                NULL, NULL, '{"raw_note":"password=hidden"}', 0.8
            )
            """,
            (f"My API key is {secret}",),
        )
        conn.execute(
            """
            INSERT INTO memory_evidence (
                id, fact_id, source_type, source_text_hash, source_excerpt,
                confidence, metadata_json, created_at
            ) VALUES (
                'evidence-export-sensitive', 'fact-export-sensitive',
                'user_message', 'redacted-hash', ?, 0.9, '{}',
                '2026-06-01T00:00:00Z'
            )
            """,
            (f"My API key is {secret}",),
        )
        conn.commit()

    response = client.get("/api/memory/graph?query=fruit", headers=_auth())

    assert response.status_code == 200
    assert secret not in response.text
    assert "source_text" not in response.text
    assert "password=hidden" not in response.text
    assert "memory_graph_facts" not in response.text
    assert "memory_evidence" not in response.text


def test_model_key_endpoint_reports_credential_store_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import settings

    monkeypatch.setattr(settings, "_dpapi_available", lambda: False)

    response = client.put(
        "/api/settings/model-key",
        headers=_auth(),
        json={"provider": "openai-compatible", "api_key": "sk-unavailable-dpapi"},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "http_error"
    assert "仅支持 Windows DPAPI" in payload["error"]["message"]
    assert "未被保存" in payload["error"]["message"]


def test_validation_errors_do_not_echo_sensitive_request_input(client: TestClient) -> None:
    secret = "sk-validation-secret-1234567890"

    response = client.put(
        "/api/settings/model-key",
        headers=_auth(),
        json={
            "provider": "openai-compatible",
            "api_key": {"nested": secret},
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert secret not in response.text
    assert "input" not in {key.lower() for key in iter_keys(payload)}


def test_internal_service_error_mappers_do_not_echo_exception_text() -> None:
    from app.api.wiring import map_memory_error, map_task_error

    secret = "sk-internal-exception-secret-1234567890"

    memory_error = map_memory_error(RuntimeError(secret))
    task_error = map_task_error(RuntimeError(secret))

    assert memory_error.status_code == 500
    assert task_error.status_code == 500
    assert secret not in memory_error.message
    assert secret not in task_error.message
