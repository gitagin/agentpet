from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient


FORBIDDEN_HEALTH_KEYS = {
    "active_vault_id",
    "vault_id",
    "vault_path",
    "root_path",
    "model_provider",
    "model_config",
    "api_key",
    "token",
    "authorization",
}


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer hardening-token"}


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


def _iter_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _iter_keys(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_keys(item)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENT_PET_SESSION_TOKEN", "hardening-token")
    monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(tmp_path / "state.sqlite3"))

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    return TestClient(create_app())


def _bind_vault(client: TestClient, vault: Path) -> str:
    response = client.post(
        "/api/vaults/init",
        headers=_auth(),
        json={"path": str(vault), "create_if_missing": True},
    )
    assert response.status_code == 200
    return str(response.json()["vault_id"])


def test_model_key_endpoint_never_returns_plaintext_key(client: TestClient) -> None:
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
    assert "api_key" not in {key.lower() for key in _iter_keys(payload)}


def test_model_key_secret_uses_replaceable_credential_store(tmp_path: Path) -> None:
    from app.services.settings import InMemoryCredentialStore, SettingsStore

    db_path = tmp_path / "state.sqlite3"
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
    assert row["masked"] != secret
    assert secret.encode("utf-8") not in db_path.read_bytes()


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
) -> None:
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
    assert FORBIDDEN_HEALTH_KEYS.isdisjoint({key.lower() for key in _iter_keys(payload)})
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
        json={"path": str(not_a_directory), "create_if_missing": False},
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
    assert "input" not in {key.lower() for key in _iter_keys(payload)}


def test_internal_service_error_mappers_do_not_echo_exception_text() -> None:
    from app.api.wiring import map_memory_error, map_task_error

    secret = "sk-internal-exception-secret-1234567890"

    memory_error = map_memory_error(RuntimeError(secret))
    task_error = map_task_error(RuntimeError(secret))

    assert memory_error.status_code == 500
    assert task_error.status_code == 500
    assert secret not in memory_error.message
    assert secret not in task_error.message
