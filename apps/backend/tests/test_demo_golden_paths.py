from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

from tests.conftest import auth_headers, parse_sse_events


def _stream_chat(client: TestClient, message: str) -> list[dict[str, str]]:
    accepted = client.post("/api/chat", headers=auth_headers(), json={"message": message})
    assert accepted.status_code == 200
    streamed = client.get(accepted.json()["stream_url"], headers=auth_headers())
    assert streamed.status_code == 200
    return parse_sse_events(streamed.text)


def _payloads(events: list[dict[str, str]], event_name: str) -> list[dict[str, object]]:
    return [json.loads(event["data"]) for event in events if event.get("event") == event_name]


def _wait_for_demo_memory_candidate(database_path: str, timeout_seconds: float = 3.0) -> sqlite3.Row | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with sqlite3.connect(database_path) as conn:
            conn.row_factory = sqlite3.Row
            candidate = conn.execute(
                """
                SELECT memory_kind, source_track, status, summary, normalized_value
                FROM memory_candidates
                WHERE normalized_value LIKE ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                ("%下午开会%",),
            ).fetchone()
        if candidate is not None:
            return candidate
        time.sleep(0.05)
    return None


def test_compound_demo_chat_persists_task_and_memory_activity(client_factory) -> None:
    with client_factory() as client:
        configured = client.put(
            "/api/settings/automation",
            headers=auth_headers(),
            json={
                "auto_chat_diary": False,
                "auto_structured_memory": False,
                "auto_long_term_memory": True,
                "auto_wiki_organize": False,
                "local_privacy_mode": False,
                "proactive_trigger_frequency": "off",
                "use_negotiation": False,
                "max_rounds": 2,
            },
        )
        assert configured.status_code == 200

        events = _stream_chat(
            client,
            "明天下午三点提醒我给张老师回邮件，并记住我更喜欢下午开会。",
        )

        names = [event["event"] for event in events]
        assert names[-1] == "done"
        task_payloads = _payloads(events, "task")
        assert len(task_payloads) == 1
        assert task_payloads[0]["title"] == "给张老师回邮件"
        assert task_payloads[0]["reminder_id"]
        action_types = {payload["action_type"] for payload in _payloads(events, "agent_action")}
        assert {"task.create", "memory.proposal.defer"}.issubset(action_types)

        with sqlite3.connect(client.app.state.database.path) as conn:
            task = conn.execute(
                "SELECT title, source_text FROM tasks WHERE id = ?",
                (task_payloads[0]["task_id"],),
            ).fetchone()
            stored_action_types = {
                row[0]
                for row in conn.execute(
                    "SELECT action_type FROM agent_actions WHERE action_type IN ('task.create', 'memory.proposal.defer')"
                ).fetchall()
            }
        assert task == ("给张老师回邮件", "明天下午三点提醒我给张老师回邮件")
        assert stored_action_types == {"task.create", "memory.proposal.defer"}

        candidate = _wait_for_demo_memory_candidate(str(client.app.state.database.path))
        assert candidate is not None
        assert candidate["memory_kind"] == "preference"
        assert candidate["source_track"] == "explicit_user"
        assert candidate["status"] == "active"
        assert "下午开会" in candidate["summary"]


def test_destructive_demo_chat_requires_confirmation_and_keeps_target_bytes(client_factory, tmp_path) -> None:
    vault_root = tmp_path / "DemoVault"
    vault_root.mkdir()
    protected_file = vault_root / "must-stay.md"
    protected_file.write_bytes(b"keep-this-content")

    with client_factory() as client:
        bound = client.post(
            "/api/vaults/init",
            headers=auth_headers(),
            json={"path": str(vault_root), "create_if_missing": False, "confirmed": True},
        )
        assert bound.status_code == 200
        configured = client.put(
            "/api/settings/automation",
            headers=auth_headers(),
            json={
                "auto_chat_diary": True,
                "auto_structured_memory": True,
                "auto_long_term_memory": True,
                "auto_wiki_organize": False,
                "local_privacy_mode": False,
                "proactive_trigger_frequency": "off",
                "use_negotiation": False,
                "max_rounds": 2,
            },
        )
        assert configured.status_code == 200
        markdown_before = {
            path.relative_to(vault_root).as_posix(): path.read_bytes()
            for path in vault_root.rglob("*.md")
        }
        events = _stream_chat(client, "删除所有本地记忆文件")

        names = [event["event"] for event in events]
        assert names[-1] == "done"
        actions = _payloads(events, "agent_action")
        assert len(actions) == 1
        assert actions[0]["action_type"] == "local.destructive_request"
        assert actions[0]["risk_tier"] == "high"
        assert actions[0]["decision"] == "ask"
        assert actions[0]["requires_confirmation"] is True
        assert actions[0]["target_paths"] == []
        agent_run_id = str(actions[0]["agent_run_id"])

        time.sleep(0.2)

        with sqlite3.connect(client.app.state.database.path) as conn:
            stored = conn.execute(
                "SELECT risk_tier, decision, status FROM agent_actions WHERE action_type = 'local.destructive_request'"
            ).fetchone()
            action_types = {
                row[0]
                for row in conn.execute(
                    "SELECT action_type FROM agent_actions WHERE source_agent_run_id = ?",
                    (agent_run_id,),
                ).fetchall()
            }
        assert stored == ("high", "ask", "pending_confirmation")
        assert action_types == {"local.destructive_request"}

    assert protected_file.read_bytes() == b"keep-this-content"
    markdown_after = {
        path.relative_to(vault_root).as_posix(): path.read_bytes()
        for path in vault_root.rglob("*.md")
    }
    assert markdown_after == markdown_before
