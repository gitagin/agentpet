from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from app.agents.events import AgentStatusEvent


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENT_PET_SESSION_TOKEN", "test-token")
    monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("AGENT_PET_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    return TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def parse_sse_events(body: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                events.append(current)
                current = {}
            continue
        field, _, value = line.partition(":")
        current[field] = value.lstrip()
    if current:
        events.append(current)
    return events


def stream_chat(client: TestClient, message: str) -> list[dict[str, str]]:
    chat = client.post("/api/chat", headers=auth(), json={"message": message})
    assert chat.status_code == 200
    with client.stream("GET", chat.json()["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())
    return parse_sse_events(body)


def event_names(events: list[dict[str, str]]) -> list[str]:
    return [event["event"] for event in events]


def non_status_event_names(events: list[dict[str, str]]) -> list[str]:
    return [event["event"] for event in events if event["event"] != "status"]


def assert_successful_chat_events(events: list[dict[str, str]]) -> None:
    assert events[0]["event"] == "status"
    assert events[-1]["event"] == "done"
    assert "token" in event_names(events)
    assert "error" not in event_names(events)


def wait_for_file(path: Path, timeout_seconds: float = 2.0) -> Path:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return path
        time.sleep(0.05)
    assert path.exists()
    return path


def test_vault_bind_index_and_search_are_wired(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "People.md").write_text("# People\n\nAda likes deterministic backend wiring.\n", encoding="utf-8")

    bind = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False},
    )
    assert bind.status_code == 200
    vault_id = bind.json()["vault_id"]

    indexed = client.post(f"/api/vaults/{vault_id}/index", headers=auth())
    assert indexed.status_code == 200
    assert indexed.json()["files_indexed"] == 1

    search = client.post(
        "/api/memory/search",
        headers=auth(),
        json={"query": "deterministic", "top_k": 5},
    )
    assert search.status_code == 200
    assert search.json()["results"][0]["relative_path"] == "People.md"


def test_vault_status_recovers_persisted_active_vault_after_restart(
    client: TestClient,
    tmp_path: Path,
) -> None:
    first_vault = tmp_path / "FirstVault"
    second_vault = tmp_path / "SecondVault"

    first = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(first_vault), "create_if_missing": True},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(second_vault), "create_if_missing": True},
    )
    assert second.status_code == 200
    second_payload = second.json()

    client.app.state.active_vault_id = None
    status = client.get("/api/vaults/status", headers=auth())

    assert status.status_code == 200
    payload = status.json()
    assert payload["configured"] is True
    assert payload["active_vault_id"] == second_payload["vault_id"]
    assert payload["root_path"] == str(second_vault.resolve(strict=False))
    assert payload["name"] == second_vault.name


def test_memory_proposal_create_confirm_and_reject_are_wired(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    response = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )
    assert response.status_code == 200

    created = client.post(
        "/api/memory/proposals",
        headers=auth(),
        json={
            "type": "fact",
            "content": "- The MVP uses explicit memory confirmation.",
            "target_path": "Inbox/Pending Memories.md",
        },
    )
    assert created.status_code == 200
    proposal_id = created.json()["proposal_id"]

    pending = client.get("/api/memory/proposals", headers=auth())
    assert pending.status_code == 200
    assert pending.json()["proposals"][0]["proposal_id"] == proposal_id

    confirmed = client.post(f"/api/memory/proposals/{proposal_id}/confirm", headers=auth())
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert (vault / "Inbox" / "Pending Memories.md").exists()

    rejected_source = client.post(
        "/api/memory/proposals",
        headers=auth(),
        json={
            "type": "fact",
            "content": "- Reject this.",
            "target_path": "Inbox/Pending Memories.md",
        },
    )
    rejected = client.post(
        f"/api/memory/proposals/{rejected_source.json()['proposal_id']}/reject",
        headers=auth(),
        json={"reason": "not needed"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_wiki_page_api_writes_under_wiki_and_lists_pages(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    response = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )
    assert response.status_code == 200

    written = client.post(
        "/api/wiki/pages",
        headers=auth(),
        json={
            "title": "Runtime Architecture",
            "content": "The wiki manager writes durable knowledge pages.",
            "tags": ["architecture"],
        },
    )

    assert written.status_code == 200
    payload = written.json()
    assert payload["relative_path"] == "Wiki/Runtime-Architecture.md"
    assert payload["status"] == "created"
    assert payload["index_job_id"] == f"scheduled:{response.json()['vault_id']}"
    assert (vault / "Wiki" / "Runtime-Architecture.md").exists()

    listed = client.get("/api/wiki/pages", headers=auth())
    assert listed.status_code == 200
    assert listed.json()["pages"][0]["relative_path"] == "Wiki/Runtime-Architecture.md"


def test_memory_graph_fact_api_actions_are_wired(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )

    stream_chat(client, "my favorite fruit is apple")
    wait_for_file(vault / "Memories" / "LongTerm" / "Preferences.md")

    listed = client.get("/api/memory/graph/facts?query=fruit", headers=auth())
    assert listed.status_code == 200
    facts = listed.json()["facts"]
    assert facts
    assert facts[0]["status"] == "active"
    fact_id = facts[0]["fact_id"]

    archived = client.post(f"/api/memory/graph/facts/{fact_id}/archive", headers=auth())
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    confirmed = client.post(f"/api/memory/graph/facts/{fact_id}/confirm", headers=auth())
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "active"


def test_structured_diary_memory_api_search_detail_and_source_scope_are_wired(
    client: TestClient,
    tmp_path: Path,
) -> None:
    from app.services.diary_memory import DiaryMemoryObjectSource, DiaryMemoryStore
    from app.services.diary_memory_extractor import DiaryMemoryObject
    from app.models.enums import MemoryFactStatus

    vault = tmp_path / "Vault"
    init = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )
    assert init.status_code == 200
    vault_id = init.json()["vault_id"]
    store = DiaryMemoryStore(client.app.state.database.path)
    try:
        record = store.insert_object(
            vault_id=vault_id,
            extracted=DiaryMemoryObject(
                summary="User considered resigning after work pressure.",
                topic="work pressure",
                emotion="negative",
                people=("manager",),
                keywords=("resign", "pressure"),
                source_text="I want to resign after the manager conflict.",
                importance=0.82,
                confidence=0.9,
                status=MemoryFactStatus.ACTIVE,
            ),
            occurred_at="2026-05-13T10:30:00+08:00",
            timezone="Asia/Shanghai",
            source=DiaryMemoryObjectSource(
                object_id="",
                source_type="chat_exchange",
                source_id="run-1",
                conversation_id="conversation-1",
                user_message_id="user-1",
                assistant_message_id="assistant-1",
                agent_run_id="run-1",
                markdown_path="Memories/Daily/2026/05/week/2026-05-13.md",
            ),
            extraction_model="diary_memory_extractor_agent",
        )
    finally:
        store.close()
    assert record is not None

    diary_search = client.post(
        "/api/memory/diary/search",
        headers=auth(),
        json={"query": "resign", "people": ["manager"], "min_importance": 0.7, "top_k": 5},
    )
    assert diary_search.status_code == 200
    objects = diary_search.json()["objects"]
    assert len(objects) == 1
    assert objects[0]["id"] == record.id
    assert objects[0]["people"] == ["manager"]

    detail = client.get(f"/api/memory/diary/{record.id}", headers=auth())
    assert detail.status_code == 200
    assert detail.json()["sources"][0]["agent_run_id"] == "run-1"

    scoped_search = client.post(
        "/api/memory/search",
        headers=auth(),
        json={"query": "resign", "top_k": 5, "source_scope": "diary_objects"},
    )
    assert scoped_search.status_code == 200
    result = scoped_search.json()["results"][0]
    assert result["relative_path"] == f"DiaryMemory/{record.id}"
    assert result["source_scope"] == "diary_objects"
    assert result["retrieval_mode"] == "diary_object"


def test_tasks_and_chat_sse_are_wired(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )

    task = client.post(
        "/api/tasks",
        headers=auth(),
        json={"title": "write wiring tests", "timezone": "UTC"},
    )
    assert task.status_code == 200
    assert task.json()["status"] == "pending"

    chat = client.post(
        "/api/chat",
        headers=auth(),
        json={"message": "remember this: Ada prefers direct updates"},
    )
    assert chat.status_code == 200
    stream_url = chat.json()["stream_url"]
    assert stream_url.endswith("/events")

    with client.stream("GET", stream_url, headers=auth()) as stream:
        body = "".join(stream.iter_text())
    assert "event: memory_proposal" in body
    assert "event: done" in body


def test_continuity_routes_are_protected_and_update_runtime_state(client: TestClient) -> None:
    unauthenticated = client.get("/api/continuity/state")
    assert unauthenticated.status_code == 401

    events = stream_chat(client, "I feel tired today, can we continue this tomorrow?")
    assert "continuity_proposal" in event_names(events)

    pending = client.get("/api/continuity/proposals", headers=auth())
    assert pending.status_code == 200
    proposals = pending.json()["proposals"]
    assert proposals
    proposal_id = proposals[0]["proposal_id"]

    confirmed = client.post(f"/api/continuity/proposals/{proposal_id}/confirm", headers=auth())
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    state = client.get("/api/continuity/state", headers=auth())
    assert state.status_code == 200
    payload = state.json()
    assert payload["items"]
    assert payload["updated_at"]

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        audit_actions = {
            row[0]
            for row in conn.execute(
                "SELECT action FROM audit_logs WHERE action LIKE 'continuity.%'"
            ).fetchall()
        }
    assert {
        "continuity.proposal.list",
        "continuity.proposal.confirm",
        "continuity.state.read",
    }.issubset(audit_actions)

    followup_events = stream_chat(client, "hello again")
    assert "continuity_signal" in event_names(followup_events)
    signal_payload = next(
        json.loads(event["data"])
        for event in followup_events
        if event["event"] == "continuity_signal"
    )
    assert signal_payload["intensity"] == "high"
    assert signal_payload["source_state_keys"]


def test_rejected_continuity_proposal_remains_out_of_runtime_state(client: TestClient) -> None:
    events = stream_chat(client, "I feel lonely tonight and want to continue this later.")
    assert "continuity_proposal" in event_names(events)
    pending = client.get("/api/continuity/proposals", headers=auth()).json()["proposals"]
    proposal_id = pending[0]["proposal_id"]

    rejected = client.post(
        f"/api/continuity/proposals/{proposal_id}/reject",
        headers=auth(),
        json={"reason": "not stable enough"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    state = client.get("/api/continuity/state", headers=auth())
    assert state.status_code == 200
    assert state.json()["items"] == []
    followup_events = stream_chat(client, "hello again")
    assert "continuity_signal" not in event_names(followup_events)
    with sqlite3.connect(client.app.state.database.path) as conn:
        row = conn.execute(
            "SELECT status, rejected_reason FROM continuity_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    assert row == ("rejected", "not stable enough")


def test_chat_stream_fails_when_runtime_ends_without_terminal_event(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import chat as chat_api

    class MissingTerminalRuntime:
        async def run(self, state):
            yield AgentStatusEvent(
                agent_run_id=state.agent_run_id,
                status=state.status,
                intent=None,
                message="still working",
                stage="chat_generation",
            )

    monkeypatch.setattr(chat_api, "agent_runtime", lambda request: MissingTerminalRuntime())

    chat = client.post(
        "/api/chat",
        headers=auth(),
        json={"message": "hello without terminal event"},
    )
    assert chat.status_code == 200
    payload = chat.json()

    with client.stream("GET", payload["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())

    events = parse_sse_events(body)
    assert events[0]["event"] == "status"
    assert events[-1]["event"] == "error"
    error_payload = json.loads(events[-1]["data"])
    assert error_payload["code"] == "stream_ended_without_terminal_event"

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "SELECT * FROM agent_runs WHERE id = ?",
            (payload["agent_run_id"],),
        ).fetchone()
        assistant_message = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? AND role = ? ORDER BY created_at DESC LIMIT 1",
            (payload["conversation_id"], "assistant"),
        ).fetchone()

    assert run is not None
    assert run["status"] == "failed"
    assert run["error_code"] == "stream_ended_without_terminal_event"
    assert assistant_message is not None
    assert assistant_message["status"] == "failed"
    assert payload["agent_run_id"] not in client.app.state.chat_runs


def test_retrieval_chat_stream_emits_citation_event(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    (vault / "People.md").write_text(
        "# People\n\nAda uses the contract sentinel citation-term.",
        encoding="utf-8",
    )
    bind = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False},
    )
    assert bind.status_code == 200
    indexed = client.post(f"/api/vaults/{bind.json()['vault_id']}/index", headers=auth())
    assert indexed.status_code == 200

    events = stream_chat(client, "search memory for citation-term")

    citation_events = [event for event in events if event.get("event") == "citation"]
    assert citation_events
    citation_payload = json.loads(citation_events[0]["data"])
    assert citation_payload["citation"]["relative_path"] == "People.md"
    assert events[-1]["event"] == "done"


def test_plain_chat_stream_answers_without_citation(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )

    events = stream_chat(client, "我喜欢什么")

    assert_successful_chat_events(events)
    token_text = "".join(
        json.loads(event["data"]).get("text", "")
        for event in events
        if event.get("event") == "token"
    )
    assert token_text
    assert "搜索" not in token_text
    assert "Markdown" not in token_text


def test_chat_done_auto_writes_daily_memory_file(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )

    events = stream_chat(client, "auto daily memory question")

    assert events[-1]["event"] == "done"
    deadline = time.monotonic() + 2.0
    daily_files = []
    while time.monotonic() < deadline:
        daily_files = list(vault.glob("Memories/Daily/[0-9][0-9][0-9][0-9]/*/*/*/*.md"))
        if daily_files:
            break
        time.sleep(0.05)
    assert len(daily_files) == 1
    assert not list(vault.glob("[0-9][0-9][0-9][0-9]/*/第*周_*/*/*.md"))
    content = daily_files[0].read_text(encoding="utf-8")
    assert "聊天记忆" in content
    assert "auto daily memory question" in content
    assert "- 桌宠回答：" in content
    assert "- conversation_id：`" in content
    assert "- user_message_id：`" in content
    assert "- assistant_message_id：`" in content
    assert "- agent_run_id：`" in content


def test_chat_done_auto_writes_long_term_memory_for_explicit_preference(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )

    events = stream_chat(client, "我喜欢的水果是苹果")

    assert_successful_chat_events(events)
    preferences = wait_for_file(vault / "Memories" / "LongTerm" / "Preferences.md")
    content = preferences.read_text(encoding="utf-8")
    assert "- 类型：preference" in content
    assert "- 主题：水果" in content
    assert "- 内容：用户的水果是苹果" in content
    assert "- 来源原文：我喜欢的水果是苹果" in content


def test_chat_auto_memory_skips_without_vault_and_does_not_break_sse(client: TestClient) -> None:
    events = stream_chat(client, "plain chat without configured vault")

    assert_successful_chat_events(events)
    assert "vault_not_configured" not in json.dumps(events)


def test_empty_memory_chat_stream_still_answers_naturally(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )

    events = stream_chat(client, "你记得我喜欢什么吗")

    assert_successful_chat_events(events)
    token_text = "".join(
        json.loads(event["data"]).get("text", "")
        for event in events
        if event.get("event") == "token"
    )
    assert "翻了下记忆本" in token_text
    assert "Markdown" not in token_text


def test_task_chat_stream_emits_task_event(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )

    events = stream_chat(client, "remind me to review agent contracts tomorrow")

    task_events = [event for event in events if event.get("event") == "task"]
    assert task_events
    task_payload = json.loads(task_events[0]["data"])
    assert task_payload["task_id"]
    assert task_payload["status"] == "pending"
    assert events[-1]["event"] == "done"


def test_sensitive_memory_chat_stream_rejects_without_proposal(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True},
    )
    secret = "sk-chat-memory-secret-1234567890"

    events = stream_chat(client, f"remember this: my api key is {secret}")

    assert non_status_event_names(events) == ["error"]
    error_event = next(event for event in events if event.get("event") == "error")
    error_payload = json.loads(error_event["data"])
    assert error_payload["code"] == "sensitive_memory_rejected"
    assert secret not in error_event["data"]
    pending = client.get("/api/memory/proposals", headers=auth())
    assert pending.status_code == 200
    assert pending.json()["proposals"] == []
