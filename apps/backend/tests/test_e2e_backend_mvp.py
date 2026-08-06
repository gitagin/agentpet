from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FORBIDDEN_HEALTH_KEYS, assert_error_shape, auth_headers, iter_keys, parse_sse_events


SESSION_TOKEN = "integration-test-session-token"
AUTH_HEADERS = auth_headers(SESSION_TOKEN)


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory(session_token=SESSION_TOKEN, sqlite_name="agent_pet.sqlite3") as test_client:
        yield test_client


def skip_if_unwired(response, capability: str) -> None:
    if response.status_code != 501:
        return
    payload = response.json()
    if payload.get("error", {}).get("code") == "not_implemented":
        pytest.fail(
            f"{capability} API returned 501, but this endpoint is marked Covered in the MVP acceptance matrix. "
            "Implement the endpoint or change the acceptance matrix status to Partial."
        )


def test_health_has_no_auth_requirement_and_no_sensitive_state(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert FORBIDDEN_HEALTH_KEYS.isdisjoint({key.lower() for key in iter_keys(payload)})


def test_health_degrades_when_database_is_unreachable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenDatabase:
        def connect(self):
            raise sqlite3.OperationalError("database is unavailable")

    monkeypatch.setattr(client.app.state, "database", BrokenDatabase())

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "error"


def test_health_reports_vector_index_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_PET_SESSION_TOKEN", SESSION_TOKEN)
    monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(tmp_path / "agent_pet.sqlite3"))

    from app.config import get_settings
    from app.main import create_app
    from app.services.settings import InMemoryCredentialStore, SettingsStore

    class BrokenEmbeddingClient:
        def __init__(self, **kwargs):
            pass

        def create_embeddings(self):
            raise RuntimeError("embedding unavailable")

    get_settings.cache_clear()
    app = create_app()
    credential_store = InMemoryCredentialStore()
    monkeypatch.setattr(
        "app.services.settings.LocalCredentialStore.for_database",
        classmethod(lambda cls, db_path: credential_store),
    )
    monkeypatch.setattr("app.services.retrieval_factory.LangChainEmbeddingClient", BrokenEmbeddingClient)
    store = SettingsStore(app.state.database.path, credential_store=credential_store)
    try:
        store.set_embedding_key("openai-compatible", "test-embedding-key")
    finally:
        store.close()

    with TestClient(app) as test_client:
        response = test_client.get("/api/health")

    get_settings.cache_clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "ok"
    assert payload["components"]["vector_index"]["status"] == "unavailable"
    assert "RuntimeError" in payload["components"]["vector_index"]["reason"]
    assert FORBIDDEN_HEALTH_KEYS.isdisjoint({key.lower() for key in iter_keys(payload)})


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/vaults/status"),
        ("POST", "/api/vaults/init"),
        ("POST", "/api/memory/search"),
        ("POST", "/api/memory/proposals"),
        ("POST", "/api/memory/proposals/example-proposal/confirm"),
        ("POST", "/api/memory/proposals/example-proposal/reject"),
        ("POST", "/api/tasks"),
        ("POST", "/api/chat"),
        ("GET", "/api/chat/runs/example-run/stream"),
    ],
)
def test_protected_mvp_apis_require_authorization(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.request(method, path, json={})

    assert response.status_code == 401
    assert_error_shape(response.json())


def test_vault_init_creates_and_binds_temp_vault(client: TestClient, tmp_path: Path) -> None:
    vault_root = tmp_path / "PetMemoryVault"
    response = client.post(
        "/api/vaults/init",
        headers=AUTH_HEADERS,
        json={"path": str(vault_root), "create_if_missing": True, "confirmed": True},
    )
    skip_if_unwired(response, "vault init")

    assert response.status_code in {200, 201}
    payload = response.json()
    assert payload["vault_id"]
    assert payload["status"] in {"created", "bound", "ok"}
    assert vault_root.exists()
    assert any(vault_root.iterdir()), "vault initialization should create default folders or templates"

    status_response = client.get("/api/vaults/status", headers=AUTH_HEADERS)
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["configured"] is True
    assert status_payload["active_vault_id"] == payload["vault_id"]
    assert status_payload["root_path"] == str(vault_root.resolve(strict=False))
    assert status_payload["name"] == vault_root.name


def test_markdown_index_then_memory_search_returns_citation(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "PetMemoryVault"
    vault_root.mkdir()
    (vault_root / "Project.md").write_text(
        "# Project Memory\n\nThe integration sentinel keyword is citrine-falcon.",
        encoding="utf-8",
    )
    init_response = client.post(
        "/api/vaults/init",
        headers=AUTH_HEADERS,
        json={"path": str(vault_root), "create_if_missing": False, "confirmed": True},
    )
    skip_if_unwired(init_response, "vault init")
    assert init_response.status_code in {200, 201}
    vault_id = init_response.json()["vault_id"]

    index_response = client.post(f"/api/vaults/{vault_id}/index", headers=AUTH_HEADERS)
    skip_if_unwired(index_response, "vault indexing")
    assert index_response.status_code in {200, 202}

    search_response = client.post(
        "/api/memory/search",
        headers=AUTH_HEADERS,
        json={"query": "citrine-falcon", "top_k": 5, "mode": "fts"},
    )
    skip_if_unwired(search_response, "memory search")
    assert search_response.status_code == 200
    results = search_response.json()["results"]
    assert results
    first = results[0]
    assert first["relative_path"] == "Project.md"
    assert "citrine-falcon" in first["snippet"]
    assert first["note_id"]
    assert first["chunk_id"]


def test_task_create_stores_utc_time_and_timezone(client: TestClient) -> None:
    response = client.post(
        "/api/tasks",
        headers=AUTH_HEADERS,
        json={
            "title": "Integration reminder",
            "description": "Verify UTC persistence",
            "due_at": "2026-04-27T15:00:00",
            "remind_at": "2026-04-27T14:30:00",
            "timezone": "Asia/Shanghai",
            "source_text": "remind me tomorrow afternoon",
        },
    )
    skip_if_unwired(response, "task create")

    assert response.status_code in {200, 201}
    payload = response.json()
    assert payload["task_id"]
    assert payload["reminder_id"]
    assert payload["status"] in {"pending", "scheduled", "unscheduled"}
    metadata = payload["metadata"]
    assert metadata.get("time_parse_timezone", metadata.get("timezone")) == "Asia/Shanghai"
    assert metadata.get("timezone_label") == "北京时间"

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (payload["task_id"],)).fetchone()
        reminder = conn.execute(
            "SELECT * FROM reminders WHERE id = ?",
            (payload["reminder_id"],),
        ).fetchone()

    assert task is not None
    assert reminder is not None
    assert task["due_at_utc"].endswith("Z")
    assert reminder["remind_at_utc"].endswith("Z")
    assert datetime.fromisoformat(reminder["remind_at_utc"].replace("Z", "+00:00")).tzinfo == timezone.utc
    assert task["due_at_utc"].startswith("2026-04-27T07:00:00")
    assert reminder["remind_at_utc"].startswith("2026-04-27T06:30:00")
    assert reminder["time_parse_timezone"] == "Asia/Shanghai"


def test_chat_task_command_creates_natural_language_reminder(client: TestClient) -> None:
    settings_response = client.put(
        "/api/settings/automation",
        headers=AUTH_HEADERS,
        json={"use_negotiation": False},
    )
    assert settings_response.status_code == 200

    chat_response = client.post(
        "/api/chat",
        headers=AUTH_HEADERS,
        json={"message": "提醒我30分钟后测试桌面记忆助手"},
    )
    assert chat_response.status_code in {200, 202}

    stream_response = client.get(chat_response.json()["stream_url"], headers=AUTH_HEADERS)
    skip_if_unwired(stream_response, "chat stream")
    events = parse_sse_events(stream_response.text)
    task_events = [event for event in events if event.get("event") == "task"]
    assert task_events
    task_payload = json.loads(task_events[0]["data"])
    assert task_payload["task_id"]
    assert task_payload["reminder_id"]
    assert task_payload["reminder_status"] in {"scheduled", "unscheduled"}
    assert task_payload["remind_at"].endswith("Z")
    assert task_payload["timezone"] == "Asia/Shanghai"
    assert task_payload["timezone_label"] == "北京时间"

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        reminder = conn.execute(
            "SELECT * FROM reminders WHERE id = ?",
            (task_payload["reminder_id"],),
        ).fetchone()

    assert reminder is not None
    assert reminder["time_parse_timezone"] == "Asia/Shanghai"


def test_chat_returns_stream_url_and_stream_emits_sse_events(client: TestClient) -> None:
    chat_response = client.post(
        "/api/chat",
        headers=AUTH_HEADERS,
        json={"message": "Search memory for the integration sentinel keyword."},
    )

    assert chat_response.status_code in {200, 202}
    payload = chat_response.json()
    assert payload["conversation_id"]
    assert payload["message_id"]
    assert payload["agent_run_id"]
    assert payload["stream_url"].startswith("/api/chat/runs/")
    assert payload["agent_run_id"] in payload["stream_url"]

    stream_response = client.get(payload["stream_url"], headers=AUTH_HEADERS)
    skip_if_unwired(stream_response, "chat stream")
    assert stream_response.status_code == 200
    content_type = stream_response.headers.get("content-type", "")
    assert "text/event-stream" in content_type
    events = parse_sse_events(stream_response.text)
    assert events
    assert any("event" in event for event in events)
    assert any(event.get("event") in {"token", "citation", "done", "error"} for event in events)
    assert events[-1].get("event") in {"done", "error"}


def test_memory_proposal_create_confirm_and_reject_behavior(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "PetMemoryVault"
    vault_root.mkdir()
    (vault_root / "Preferences.md").write_text("# Preferences\n", encoding="utf-8")
    init_response = client.post(
        "/api/vaults/init",
        headers=AUTH_HEADERS,
        json={"path": str(vault_root), "create_if_missing": False, "confirmed": True},
    )
    skip_if_unwired(init_response, "vault init")
    assert init_response.status_code in {200, 201}

    create_response = client.post(
        "/api/memory/proposals",
        headers=AUTH_HEADERS,
        json={
            "type": "preference",
            "content": "User prefers terse integration notes.",
            "target_path": "Preferences.md",
            "source_message_id": "message-integration-1",
        },
    )
    skip_if_unwired(create_response, "memory proposals")
    assert create_response.status_code in {200, 201}
    proposal = create_response.json()
    assert proposal["proposal_id"]
    assert proposal["status"] == "pending"
    assert "terse integration notes" in proposal["preview_markdown"]
    assert (vault_root / "Preferences.md").read_text(encoding="utf-8") == "# Preferences\n"

    confirm_response = client.post(
        f"/api/memory/proposals/{proposal['proposal_id']}/confirm",
        headers=AUTH_HEADERS,
    )
    skip_if_unwired(confirm_response, "memory proposal confirmation")
    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["proposal_id"] == proposal["proposal_id"]
    assert confirmed["status"] == "confirmed"
    assert confirmed["written_path"]
    assert "terse integration notes" in (vault_root / "Preferences.md").read_text(encoding="utf-8")

    reject_create_response = client.post(
        "/api/memory/proposals",
        headers=AUTH_HEADERS,
        json={
            "type": "fact",
            "content": "Rejected memory must not be written.",
            "target_path": "Preferences.md",
        },
    )
    assert reject_create_response.status_code in {200, 201}
    reject_proposal = reject_create_response.json()
    reject_response = client.post(
        f"/api/memory/proposals/{reject_proposal['proposal_id']}/reject",
        headers=AUTH_HEADERS,
        json={"reason": "integration rejection path"},
    )
    skip_if_unwired(reject_response, "memory proposal rejection")
    assert reject_response.status_code == 200
    rejected = reject_response.json()
    assert rejected["proposal_id"] == reject_proposal["proposal_id"]
    assert rejected["status"] == "rejected"
    assert "Rejected memory must not be written." not in (vault_root / "Preferences.md").read_text(
        encoding="utf-8"
    )
