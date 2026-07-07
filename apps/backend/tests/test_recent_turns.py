from __future__ import annotations

from collections.abc import Iterator
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.agents.events import AgentDoneEvent, AgentTokenEvent
from app.models.enums import AgentIntent


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory() as test_client:
        yield test_client


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_chat_state_loads_same_conversation_completed_user_and_assistant_turns(client: TestClient) -> None:
    _insert_conversation(client, "conversation-main")
    _insert_message(client, "conversation-main", "m1", "user", "OLDER_SAFE_USER", "completed", "2026-07-01T00:00:00Z")
    _insert_message(client, "conversation-main", "m2", "assistant", "OLDER_SAFE_ASSISTANT", "completed", "2026-07-01T00:01:00Z")
    _insert_message(client, "conversation-other", "other-1", "user", "OTHER_CONVERSATION_SENTINEL", "completed", "2026-07-01T00:02:00Z")

    response = client.post(
        "/api/chat",
        headers=auth(),
        json={"conversation_id": "conversation-main", "message": "CURRENT_USER_SENTINEL"},
    )

    assert response.status_code == 200
    state = client.app.state.chat_runs[response.json()["agent_run_id"]]
    assert [(turn.role, turn.content) for turn in state.recent_turns] == [
        ("user", "OLDER_SAFE_USER"),
        ("assistant", "OLDER_SAFE_ASSISTANT"),
    ]
    assert all(turn.content != "CURRENT_USER_SENTINEL" for turn in state.recent_turns)
    assert all(turn.content != "OTHER_CONVERSATION_SENTINEL" for turn in state.recent_turns)


def test_chat_state_excludes_non_completed_and_non_visible_message_roles(client: TestClient) -> None:
    _insert_conversation(client, "conversation-filter")
    _insert_message(client, "conversation-filter", "safe-1", "user", "SAFE_VISIBLE_TURN", "completed", "2026-07-01T00:00:00Z")
    _insert_message(client, "conversation-filter", "partial-1", "user", "PARTIAL_SENTINEL", "partial", "2026-07-01T00:01:00Z")
    _insert_message(client, "conversation-filter", "failed-1", "assistant", "FAILED_SENTINEL", "failed", "2026-07-01T00:02:00Z")
    _insert_message(client, "conversation-filter", "cancelled-1", "assistant", "CANCELLED_SENTINEL", "cancelled", "2026-07-01T00:03:00Z")
    _insert_message(client, "conversation-filter", "tool-1", "tool", "TOOL_SENTINEL", "completed", "2026-07-01T00:04:00Z")
    _insert_message(client, "conversation-filter", "system-1", "system", "SYSTEM_SENTINEL", "completed", "2026-07-01T00:05:00Z")
    _insert_message(client, "conversation-filter", "developer-1", "developer", "DEVELOPER_SENTINEL", "completed", "2026-07-01T00:06:00Z")

    response = client.post(
        "/api/chat",
        headers=auth(),
        json={"conversation_id": "conversation-filter", "message": "continue"},
    )

    assert response.status_code == 200
    state = client.app.state.chat_runs[response.json()["agent_run_id"]]
    assert [turn.content for turn in state.recent_turns] == ["SAFE_VISIBLE_TURN"]


def test_chat_state_excludes_recent_turns_with_internal_or_sensitive_content(client: TestClient) -> None:
    _insert_conversation(client, "conversation-safe")
    unsafe_contents = [
        "source_text: raw hidden content",
        "source_excerpt: raw hidden content",
        "raw evidence should not enter",
        "agent_run_id=run-raw",
        "message_id=message-raw",
        "conversation_id=conversation-raw",
        "source_message_id=message-source",
        "source_conversation_id=conversation-source",
        "raw_evidence should not enter",
        "evidence_id=evidence-raw",
        "evidence: raw detail",
        "source_message: raw detail",
        "source_conversation: raw detail",
        "Authorization: Bearer secret-token-value",
        "token should not enter",
        r"C:\Users\Alice\Vault\Secret.md",
        "Traceback (most recent call last):\n  File \"app.py\", line 1",
        "vault write preview raw markdown",
        "<tool_call>{\"name\":\"search\"}</tool_call>",
    ]
    for index, content in enumerate(unsafe_contents):
        _insert_message(
            client,
            "conversation-safe",
            f"unsafe-{index}",
            "user" if index % 2 == 0 else "assistant",
            content,
            "completed",
            f"2026-07-01T00:{index:02d}:00Z",
        )
    _insert_message(client, "conversation-safe", "safe-1", "assistant", "SAFE_RECENT_TURN", "completed", "2026-07-01T00:20:00Z")

    response = client.post(
        "/api/chat",
        headers=auth(),
        json={"conversation_id": "conversation-safe", "message": "continue"},
    )

    assert response.status_code == 200
    state = client.app.state.chat_runs[response.json()["agent_run_id"]]
    assert [turn.content for turn in state.recent_turns] == ["SAFE_RECENT_TURN"]


def test_chat_state_keeps_only_four_most_recent_safe_turns(client: TestClient) -> None:
    _insert_conversation(client, "conversation-limit")
    for index in range(6):
        _insert_message(
            client,
            "conversation-limit",
            f"m{index}",
            "user" if index % 2 == 0 else "assistant",
            f"SAFE_TURN_{index}",
            "completed",
            f"2026-07-01T00:0{index}:00Z",
        )

    response = client.post(
        "/api/chat",
        headers=auth(),
        json={"conversation_id": "conversation-limit", "message": "continue"},
    )

    assert response.status_code == 200
    state = client.app.state.chat_runs[response.json()["agent_run_id"]]
    assert [turn.content for turn in state.recent_turns] == [
        "SAFE_TURN_2",
        "SAFE_TURN_3",
        "SAFE_TURN_4",
        "SAFE_TURN_5",
    ]


def test_stream_runtime_receives_recent_turns_from_common_chat_state(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import chat as chat_api

    captured: dict[str, list[str]] = {}

    class CapturingRuntime:
        async def run(self, state):
            captured["recent_turns"] = [turn.content for turn in state.recent_turns]
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text="ok")
            yield AgentDoneEvent(agent_run_id=state.agent_run_id, intent=AgentIntent.CHAT, text="ok")

    monkeypatch.setattr(chat_api, "agent_runtime", lambda request: CapturingRuntime())

    _insert_conversation(client, "conversation-stream")
    _insert_message(client, "conversation-stream", "m1", "user", "STREAM_RECENT_TURN", "completed", "2026-07-01T00:00:00Z")
    response = client.post(
        "/api/chat",
        headers=auth(),
        json={"conversation_id": "conversation-stream", "message": "continue"},
    )
    assert response.status_code == 200

    with client.stream("GET", response.json()["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())

    assert "event: done" in body
    assert captured["recent_turns"] == ["STREAM_RECENT_TURN"]


def _insert_conversation(client: TestClient, conversation_id: str) -> None:
    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO conversations (id, title, status, created_at, updated_at)
            VALUES (?, ?, 'active', '2026-07-01T00:00:00Z', '2026-07-01T00:00:00Z')
            """,
            (conversation_id, conversation_id),
        )
        conn.commit()


def _insert_message(
    client: TestClient,
    conversation_id: str,
    message_id: str,
    role: str,
    content: str,
    status: str,
    created_at: str,
) -> None:
    _insert_conversation(client, conversation_id)
    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, conversation_id, role, content, status, created_at, created_at),
        )
        conn.commit()
