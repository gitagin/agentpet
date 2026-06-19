from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Iterator
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from apps.backend.tests._schema import migrate_db
from app.scheduler import ReminderSchedulerError
from app.services.chat_model import ChatModelError
from app.services.tasks import TaskService, TaskStore
from tests.conftest import auth_headers


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory() as test_client:
        yield test_client


def auth() -> dict[str, str]:
    return auth_headers()


class FailingReminderScheduler:
    def schedule(self, reminder_id: str, trigger_at_utc: datetime, title: str) -> str:
        raise ReminderSchedulerError("提醒调度器不可用")

    def cancel(self, job_id: str) -> None:
        pass


def test_model_key_is_persisted_and_never_returned_plaintext(client: TestClient) -> None:
    secret = "sk-secret-value"
    config_response = client.put(
        "/api/settings/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://example.test/v1/",
            "model": "demo-model",
        },
    )
    assert config_response.status_code == 200
    assert config_response.json() == {
        "provider": "openai-compatible",
        "base_url": "https://example.test/v1",
        "model": "demo-model",
        "status": "configured",
    }

    response = client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": secret},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "provider": "openai-compatible",
        "status": "configured",
        "masked": "****alue",
    }
    assert secret not in response.text

    status = client.get("/api/settings", headers=auth())
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["model_provider"] == "openai-compatible"
    assert status_payload["model_base_url"] == "https://example.test/v1"
    assert status_payload["chat_model"] == "demo-model"
    assert status_payload["model_configured"] is True
    assert secret not in status.text

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_keys)").fetchall()}
        row = conn.execute("SELECT * FROM model_keys WHERE provider = ?", ("openai-compatible",)).fetchone()
        config_row = conn.execute("SELECT * FROM model_config WHERE id = 1").fetchone()

    assert columns == {"provider", "masked", "credential_ref", "created_at", "updated_at"}
    assert row["masked"] == "****alue"
    assert row["credential_ref"]
    assert config_row["base_url"] == "https://example.test/v1"
    assert config_row["model"] == "demo-model"
    assert secret.encode("utf-8") not in db_path.read_bytes()


def test_model_test_reports_missing_key_without_plaintext(client: TestClient) -> None:
    response = client.post("/api/settings/model-test", headers=auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error_code"] == "not_configured"
    assert "API 密钥" in payload["message"]
    assert "api_key" not in response.text.lower()


def test_model_test_success_uses_saved_config(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class FakeModelClient:
        def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["model"] = model
            captured["timeout_seconds"] = timeout_seconds

        async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            captured["user_message"] = user_message
            captured["system_prompt"] = system_prompt
            return "OK"

    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "LangChainGraphChatClient", FakeModelClient)
    client.put(
        "/api/settings/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://example.test/v1/",
            "model": "demo-model",
        },
    )
    client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-test-secret"},
    )

    response = client.post("/api/settings/model-test", headers=auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["provider"] == "openai-compatible"
    assert payload["base_url"] == "https://example.test/v1"
    assert payload["model"] == "demo-model"
    assert isinstance(payload["latency_ms"], int)
    assert payload["error_code"] is None
    assert "sk-test-secret" not in response.text
    assert captured["api_key"] == "sk-test-secret"
    assert captured["base_url"] == "https://example.test/v1"
    assert captured["model"] == "demo-model"


def test_agent_model_settings_are_persisted_per_agent(client: TestClient) -> None:
    config_response = client.put(
        "/api/settings/agent-models/chat_agent/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://chat.example.test/v1/",
            "model": "chat-model",
        },
    )
    key_response = client.put(
        "/api/settings/agent-models/chat_agent/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-chat-secret"},
    )
    second_config = client.put(
        "/api/settings/agent-models/task_agent/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://task.example.test/v1",
            "model": "task-model",
        },
    )

    assert config_response.status_code == 200
    assert config_response.json()["agent_id"] == "chat_agent"
    assert config_response.json()["base_url"] == "https://chat.example.test/v1"
    assert key_response.status_code == 200
    assert key_response.json()["configured"] is True
    assert key_response.json()["masked"] == "****cret"
    assert second_config.status_code == 200

    listed = client.get("/api/settings/agent-models", headers=auth())
    assert listed.status_code == 200
    agents = {item["agent_id"]: item for item in listed.json()["agents"]}
    assert set(agents) == {
        "chat_agent",
        "semantic_analysis_agent",
        "retrieval_agent",
        "action_agent",
        "reflection_agent",
    }
    assert agents["chat_agent"]["model"] == "chat-model"
    assert agents["chat_agent"]["configured"] is True
    assert agents["action_agent"]["model"] == "task-model"
    assert agents["action_agent"]["configured"] is False
    assert "sk-chat-secret" not in listed.text

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        config_rows = conn.execute(
            "SELECT agent_id, base_url, model FROM agent_model_config ORDER BY agent_id"
        ).fetchall()
        key_row = conn.execute(
            "SELECT agent_id, provider, masked, credential_ref FROM agent_model_keys"
        ).fetchone()

    assert [row["agent_id"] for row in config_rows] == ["action_agent", "chat_agent"]
    assert key_row["agent_id"] == "chat_agent"
    assert key_row["masked"] == "****cret"
    assert key_row["credential_ref"]
    assert b"sk-chat-secret" not in db_path.read_bytes()


def test_agent_model_bulk_put_updates_current_configs_and_global_defaults(
    client: TestClient,
) -> None:
    global_config = client.put(
        "/api/settings/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://global.example.test/v1",
            "model": "global-model",
        },
    )
    bulk_response = client.put(
        "/api/settings/agent-models",
        headers=auth(),
        json={
            "agents": [
                {
                    "agent_id": "knowledge_retrieval_agent",
                    "provider": "openai-compatible",
                    "base_url": "https://knowledge.example.test/v1/",
                    "model": "knowledge-model",
                },
                {
                    "agent_id": "memory_proposal_agent",
                    "provider": "openai-compatible",
                    "base_url": "https://memory.example.test/v1",
                    "model": "memory-model",
                },
            ]
        },
    )

    assert global_config.status_code == 200
    assert bulk_response.status_code == 200
    agents = {item["agent_id"]: item for item in bulk_response.json()["agents"]}
    assert "knowledge_agent" not in agents
    assert "context_retrieval_agent" not in agents
    assert agents["retrieval_agent"]["base_url"] == "https://knowledge.example.test/v1"
    assert agents["retrieval_agent"]["model"] == "knowledge-model"
    assert agents["action_agent"]["model"] == "memory-model"

    status_response = client.get("/api/settings", headers=auth())
    assert status_response.status_code == 200
    assert status_response.json()["model_base_url"] == "https://global.example.test/v1"
    assert status_response.json()["chat_model"] == "global-model"


def test_legacy_continuity_agent_model_config_maps_to_reflection_agent(client: TestClient) -> None:
    response = client.put(
        "/api/settings/agent-models/continuity_agent/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://continuity.example.test/v1/",
            "model": "continuity-model",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == "reflection_agent"
    assert payload["base_url"] == "https://continuity.example.test/v1"
    assert payload["model"] == "continuity-model"


def test_agent_model_endpoints_map_legacy_agent_ids(client: TestClient) -> None:
    bulk_response = client.put(
        "/api/settings/agent-models",
        headers=auth(),
        json={
            "agents": [
                {
                    "agent_id": "memory_retrieval_agent",
                    "provider": "openai-compatible",
                    "base_url": "https://knowledge.example.test/v1",
                    "model": "knowledge-model",
                }
            ]
        },
    )
    config_response = client.put(
        "/api/settings/agent-models/context_retrieval_agent/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://context.example.test/v1",
            "model": "context-model",
        },
    )

    assert bulk_response.status_code == 200
    assert config_response.status_code == 200
    bulk_agents = {item["agent_id"]: item for item in bulk_response.json()["agents"]}
    assert bulk_agents["retrieval_agent"]["model"] == "knowledge-model"
    assert config_response.json()["agent_id"] == "retrieval_agent"
    assert config_response.json()["model"] == "context-model"


def test_legacy_agent_model_configs_are_migrated_and_removed(tmp_path: Path) -> None:
    from app.services.settings import InMemoryCredentialStore, SettingsStore

    db_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE agent_model_configs (
                agent_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                masked TEXT,
                credential_ref TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO agent_model_configs
                (agent_id, provider, base_url, model, masked, credential_ref, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "context_retrieval_agent",
                    "openai-compatible",
                    "https://context.example.test/v1",
                    "context-model",
                    "sk...ct",
                    "legacy-context-ref",
                    1,
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
                (
                    "knowledge_agent",
                    "openai-compatible",
                    "https://knowledge.example.test/v1",
                    "knowledge-model",
                    "sk...ge",
                    "legacy-knowledge-ref",
                    1,
                    "2026-01-02T00:00:00Z",
                    "2026-01-02T00:00:00Z",
                ),
                (
                    "memory_retrieval_agent",
                    "openai-compatible",
                    "https://existing-memory.example.test/v1",
                    "existing-memory-model",
                    "sk...em",
                    "existing-memory-ref",
                    1,
                    "2026-01-03T00:00:00Z",
                    "2026-01-03T00:00:00Z",
                ),
            ],
        )
        conn.commit()

    store = SettingsStore(db_path, credential_store=InMemoryCredentialStore())
    try:
        retrieval_config = store.get_agent_model_config(
            "retrieval_agent",
            default_provider="openai-compatible",
            default_base_url="",
            default_model="",
        )
        legacy_memory_alias_config = store.get_agent_model_config(
            "memory_retrieval_agent",
            default_provider="openai-compatible",
            default_base_url="",
            default_model="",
        )
    finally:
        store.close()

    with sqlite3.connect(db_path) as conn:
        remaining_ids = {
            row[0]
            for row in conn.execute("SELECT agent_id FROM agent_model_configs").fetchall()
        }

    assert retrieval_config is not None
    assert legacy_memory_alias_config is not None
    assert retrieval_config.model == "existing-memory-model"
    assert legacy_memory_alias_config.model == "existing-memory-model"
    assert "retrieval_agent" in remaining_ids
    assert "memory_retrieval_agent" not in remaining_ids
    assert "knowledge_retrieval_agent" not in remaining_ids
    assert "context_retrieval_agent" not in remaining_ids
    assert "knowledge_agent" not in remaining_ids


def test_agent_model_key_requires_base_url_before_saving(tmp_path: Path) -> None:
    from app.services.settings import ConfigurationError, InMemoryCredentialStore, SettingsStore

    db_path = migrate_db(tmp_path / "state.sqlite3")
    store = SettingsStore(db_path, credential_store=InMemoryCredentialStore())
    try:
        with pytest.raises(ConfigurationError, match="未配置 Base URL"):
            store.set_agent_model_key(
                agent_id="chat_agent",
                provider="openai-compatible",
                api_key="sk-agent-key-without-base-url",
            )
    finally:
        store.close()


def test_sql_migration_removes_legacy_agent_model_ids(tmp_path: Path) -> None:
    from app.storage.database import Database, MigrationRunner

    db_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE agent_model_configs (
                agent_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                masked TEXT,
                credential_ref TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO agent_model_configs
                (agent_id, provider, base_url, model, masked, credential_ref, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "context_retrieval_agent",
                    "openai-compatible",
                    "https://context.example.test/v1",
                    "context-model",
                    None,
                    "legacy-context-ref",
                    1,
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
                (
                    "knowledge_agent",
                    "openai-compatible",
                    "https://knowledge.example.test/v1",
                    "knowledge-model",
                    None,
                    "legacy-knowledge-ref",
                    1,
                    "2026-01-02T00:00:00Z",
                    "2026-01-02T00:00:00Z",
                ),
            ],
        )
        conn.commit()

    MigrationRunner(Database(db_path)).apply()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = {
            row["agent_id"]: row
            for row in conn.execute(
                "SELECT agent_id, base_url, model FROM agent_model_configs"
            ).fetchall()
        }

    assert set(rows) == {"memory_retrieval_agent", "knowledge_retrieval_agent"}
    assert rows["memory_retrieval_agent"]["model"] == "context-model"
    assert rows["knowledge_retrieval_agent"]["model"] == "knowledge-model"


def test_model_test_accepts_agent_id_and_uses_agent_credentials(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class FakeModelClient:
        def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["model"] = model

        async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            return "OK"

    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "LangChainGraphChatClient", FakeModelClient)
    client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-global-secret"},
    )
    client.put(
        "/api/settings/agent-models/task_agent/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://task.example.test/v1/",
            "model": "task-model",
        },
    )
    client.put(
        "/api/settings/agent-models/task_agent/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-task-secret"},
    )

    response = client.post(
        "/api/settings/model-test",
        headers=auth(),
        json={"agent_id": "task_agent"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["agent_id"] == "action_agent"
    assert payload["base_url"] == "https://task.example.test/v1"
    assert payload["model"] == "task-model"
    assert captured["api_key"] == "sk-task-secret"
    assert captured["base_url"] == "https://task.example.test/v1"
    assert captured["model"] == "task-model"
    assert "sk-task-secret" not in response.text


def test_model_test_recovers_after_agent_provider_is_corrected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class FakeModelClient:
        def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["model"] = model

        async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            return "OK"

    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "LangChainGraphChatClient", FakeModelClient)
    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO agent_model_configs
                (agent_id, provider, base_url, model, masked, credential_ref, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "chat_agent",
                "mimo",
                "https://wrong.example.test/v1",
                "wrong-model",
                "****cret",
                "model-key:agent:chat_agent",
                1,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
    failed = client.post(
        "/api/settings/model-test",
        headers=auth(),
        json={"agent_id": "chat_agent"},
    )

    corrected_config = client.put(
        "/api/settings/agent-models/chat_agent/model-config",
        headers=auth(),
        json={
            "provider": "OpenAI Compatible",
            "base_url": "https://token-plan-sgp.xiaomimimo.com/v1",
            "model": "MiMo-v2.5-pro",
        },
    )
    corrected_key = client.put(
        "/api/settings/agent-models/chat_agent/model-key",
        headers=auth(),
        json={"provider": "OpenAI Compatible", "api_key": "sk-correct-secret"},
    )
    recovered = client.post(
        "/api/settings/model-test",
        headers=auth(),
        json={"agent_id": "chat_agent"},
    )

    assert failed.status_code == 200
    assert failed.json()["error_code"] == "unsupported_provider"
    assert corrected_config.status_code == 200
    assert corrected_config.json()["provider"] == "openai-compatible"
    assert corrected_key.status_code == 200
    assert corrected_key.json()["provider"] == "openai-compatible"
    payload = recovered.json()
    assert payload["status"] == "ok"
    assert payload["provider"] == "openai-compatible"
    assert payload["base_url"] == "https://token-plan-sgp.xiaomimimo.com/v1"
    assert payload["model"] == "MiMo-v2.5-pro"
    assert captured["api_key"] == "sk-correct-secret"
    assert "sk-correct-secret" not in recovered.text


def test_agent_model_config_rejects_unsupported_provider(client: TestClient) -> None:
    config_response = client.put(
        "/api/settings/agent-models/chat_agent/model-config",
        headers=auth(),
        json={
            "provider": "mimo-v2.5",
            "base_url": "https://token-plan-sgp.xiaomimimo.com/v1",
            "model": "MiMo-v2.5-pro",
        },
    )
    key_response = client.put(
        "/api/settings/agent-models/chat_agent/model-key",
        headers=auth(),
        json={"provider": "mimo-v2.5", "api_key": "sk-test-secret"},
    )

    assert config_response.status_code == 422
    assert key_response.status_code == 422


def test_model_test_maps_provider_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeModelClient:
        def __init__(self, **_kwargs):
            pass

        async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            raise ChatModelError(
                "模型名称不被当前服务支持，请检查模型名称。",
                code="unsupported_model",
                detail="Not supported model demo-model",
            )

    from app.api import settings as settings_api

    monkeypatch.setattr(settings_api, "LangChainGraphChatClient", FakeModelClient)
    client.put(
        "/api/settings/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://example.test/v1",
            "model": "demo-model",
        },
    )
    client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-test-secret"},
    )

    response = client.post("/api/settings/model-test", headers=auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error_code"] == "unsupported_model"
    assert "模型名称" in payload["message"]
    assert "sk-test-secret" not in response.text


def test_task_list_today_complete_and_cancel_are_persisted(client: TestClient) -> None:
    today_due_at = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    later_due_at = today_due_at + timedelta(days=1)
    today = client.post(
        "/api/tasks",
        headers=auth(),
        json={
            "title": "Today task",
            "due_at": today_due_at.isoformat().replace("+00:00", "Z"),
            "timezone": "UTC",
        },
    )
    later = client.post(
        "/api/tasks",
        headers=auth(),
        json={
            "title": "Later task",
            "due_at": later_due_at.isoformat().replace("+00:00", "Z"),
            "timezone": "UTC",
        },
    )
    assert today.status_code == 200
    assert later.status_code == 200

    listed = client.get("/api/tasks", headers=auth())
    assert listed.status_code == 200
    assert {task["title"] for task in listed.json()["tasks"]} == {"Today task", "Later task"}

    today_response = client.get("/api/tasks/today?timezone=UTC", headers=auth())
    assert today_response.status_code == 200
    assert [task["title"] for task in today_response.json()["tasks"]] == ["Today task"]

    task_id = today.json()["task_id"]
    complete = client.post(f"/api/tasks/{task_id}/complete", headers=auth())
    assert complete.status_code == 200
    assert complete.json()["status"] == "done"

    cancel = client.post(f"/api/tasks/{later.json()['task_id']}/cancel", headers=auth())
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


def test_task_workspace_endpoints_are_persisted(client: TestClient) -> None:
    created = client.post(
        "/api/tasks",
        headers=auth(),
        json={"title": "Workspace task", "description": "Show in Agent workspace"},
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    current = client.get("/api/tasks/current", headers=auth())
    assert current.status_code == 200
    assert current.json()["task"]["task_id"] == task_id
    assert current.json()["task"]["needs_approval"] is False

    steps = client.get(f"/api/tasks/{task_id}/steps", headers=auth())
    assert steps.status_code == 200
    assert steps.json()["steps"] == [{"index": 1, "tool_name": "task", "status": "pending", "duration_ms": 0}]

    logs = client.get(f"/api/tasks/{task_id}/logs", headers=auth())
    assert logs.status_code == 200
    assert len(logs.json()["logs"]) == 2
    assert "Workspace task" in logs.json()["logs"][0]["content"]

    approve = client.post(f"/api/tasks/{task_id}/approve", headers=auth())
    assert approve.status_code == 200
    assert approve.json() == {"task_id": task_id, "status": "pending", "approved": True, "rejected": False}

    reject = client.post(f"/api/tasks/{task_id}/reject", headers=auth())
    assert reject.status_code == 200
    assert reject.json() == {"task_id": task_id, "status": "cancelled", "approved": False, "rejected": True}


def test_task_workspace_endpoints_return_not_found_for_missing_task(client: TestClient) -> None:
    for method, path in [
        (client.get, "/api/tasks/missing-task/steps"),
        (client.get, "/api/tasks/missing-task/logs"),
        (client.post, "/api/tasks/missing-task/approve"),
        (client.post, "/api/tasks/missing-task/reject"),
    ]:
        response = method(path, headers=auth())
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "task_not_found"


def test_startup_restores_unscheduled_reminders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    failing_scheduler = FailingReminderScheduler()
    store = TaskStore(db_path)
    created = TaskService(store, scheduler=failing_scheduler).create(
        title="Retry on startup",
        remind_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        timezone="UTC",
    )
    store.close()
    assert created.reminder is not None

    monkeypatch.setenv("AGENT_PET_SESSION_TOKEN", "test-token")
    monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(db_path))

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as startup_client:
        scheduler = startup_client.app.state.reminder_scheduler
        assert scheduler.get_job(f"reminder:{created.reminder.id}") is not None

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        reminder = conn.execute(
            "SELECT * FROM reminders WHERE id = ?",
            (created.reminder.id,),
        ).fetchone()

    assert reminder["status"] == "scheduled"
    assert reminder["scheduler_job_id"] == f"reminder:{created.reminder.id}"


def test_chat_conversation_messages_and_agent_run_are_persisted(client: TestClient) -> None:
    chat = client.post(
        "/api/chat",
        headers=auth(),
        json={"message": "hello persistence"},
    )
    assert chat.status_code == 200
    payload = chat.json()

    with client.stream("GET", payload["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())
    assert "event: done" in body

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conversation = conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (payload["conversation_id"],),
        ).fetchone()
        messages = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (payload["conversation_id"],),
        ).fetchall()
        run = conn.execute(
            "SELECT * FROM agent_runs WHERE id = ?",
            (payload["agent_run_id"],),
        ).fetchone()

    assert conversation is not None
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hello persistence"
    assert messages[0]["status"] == "completed"
    assert messages[1]["content"]
    assert messages[1]["status"] == "completed"
    assert run["status"] == "success"
    assert run["user_message_id"] == payload["message_id"]
    assert run["assistant_message_id"] == messages[1]["id"]
    assert payload["agent_run_id"] not in client.app.state.chat_runs


def test_reset_local_state_requires_confirmation(client: TestClient) -> None:
    response = client.post(
        "/api/diagnostics/reset-local-state",
        headers=auth(),
        json={"confirmation": "wrong"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "reset_confirmation_required"


def test_reset_local_state_clears_user_state_and_credentials(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    (vault / "Notes").mkdir(parents=True)
    (vault / "Notes" / "Seed.md").write_text("# Seed\n\nDevelopment memory.\n", encoding="utf-8")
    init = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert init.status_code == 200
    vault_id = init.json()["vault_id"]
    assert client.post(f"/api/vaults/{vault_id}/index", headers=auth()).status_code == 200
    assert client.put(
        "/api/settings/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://example.test/v1",
            "model": "demo-model",
        },
    ).status_code == 200
    assert client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-reset-secret"},
    ).status_code == 200
    assert client.put(
        "/api/settings/agent-models/chat_agent/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://chat.example.test/v1",
            "model": "chat-model",
        },
    ).status_code == 200
    assert client.put(
        "/api/settings/agent-models/chat_agent/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-chat-reset-secret"},
    ).status_code == 200
    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, title, status, created_at, updated_at)
            VALUES ('conversation-reset', 'reset', 'active', datetime('now'), datetime('now'))
            """
        )
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES ('message-user-reset', 'conversation-reset', 'user', 'hello reset', 'completed', datetime('now'), datetime('now'))
            """
        )
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES ('message-assistant-reset', 'conversation-reset', 'assistant', 'test memory', 'completed', datetime('now'), datetime('now'))
            """
        )
        conn.execute(
            """
            INSERT INTO agent_runs (
                id, conversation_id, user_message_id, assistant_message_id, status, intent, created_at, updated_at
            )
            VALUES (
                'run-reset', 'conversation-reset', 'message-user-reset', 'message-assistant-reset',
                'success', 'chat', datetime('now'), datetime('now')
            )
            """
        )
        conn.commit()
    credentials_dir = db_path.with_suffix(f"{db_path.suffix}.credentials")
    assert credentials_dir.exists()
    data_dir = db_path.parent
    vector_index_dir = data_dir / "vector-index"
    graph_dir = data_dir / "memory-graph"
    graph_file = data_dir / "memory_graph.kuzu"
    vector_index_dir.mkdir()
    graph_dir.mkdir()
    graph_file.write_text("development graph mirror", encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT COUNT(*) FROM vaults").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM model_keys").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_model_configs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM agent_model_keys").fetchone()[0] == 1

    response = client.post(
        "/api/diagnostics/reset-local-state",
        headers=auth(),
        json={"confirmation": "RESET_AGENT_PET"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "reset"
    assert payload["cleared_tables"]["vaults"] == 1
    assert payload["cleared_tables"]["messages"] == 2
    assert payload["cleared_tables"]["model_keys"] == 1
    assert payload["cleared_tables"]["agent_model_configs"] == 1
    assert "state.sqlite3.credentials" in payload["removed_paths"]
    assert "vector-index" in payload["removed_paths"]
    assert "memory-graph" in payload["removed_paths"]
    assert "memory_graph.kuzu" in payload["removed_paths"]
    assert not credentials_dir.exists()
    assert not vector_index_dir.exists()
    assert not graph_dir.exists()
    assert not graph_file.exists()
    assert client.app.state.active_vault_id is None
    assert client.app.state.chat_runs == {}

    status_response = client.get("/api/settings", headers=auth())
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["vault_configured"] is False
    assert status_payload["model_configured"] is False
    assert all(agent["configured"] is False for agent in status_payload["agent_models"])

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing_tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        for table in (
            "vaults",
            "notes",
            "note_chunks",
            "note_fts",
            "conversations",
            "messages",
            "agent_runs",
            "daily_chat_memory_entries",
            "memory_proposals",
            "model_keys",
            "model_config",
            "agent_model_configs",
            "agent_model_keys",
        ):
            if table not in existing_tables:
                continue
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        migrations = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert migrations > 0
