from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fastapi import Request
from fastapi.testclient import TestClient

from app.agents.events import AgentDoneEvent, AgentErrorEvent, AgentStatusEvent, AgentTokenEvent
from app.models.enums import AgentIntent, AgentRunStatus, MessageStatus
from tests.conftest import auth_headers, parse_sse_events


@pytest.fixture()
def client(client_factory, tmp_path: Path) -> Iterator[TestClient]:
    with client_factory(data_dir=tmp_path / "data") as test_client:
        yield test_client


def auth() -> dict[str, str]:
    return auth_headers()


def api_request(client: TestClient) -> Request:
    return Request(
        {
            "type": "http",
            "app": client.app,
            "state": {"request_id": "test-stream-request"},
        }
    )


def create_unstreamed_chat(client: TestClient, message: str) -> tuple[dict[str, str], object]:
    response = client.post("/api/chat", headers=auth(), json={"message": message})
    assert response.status_code == 200
    payload = response.json()
    return payload, client.app.state.chat_runs[payload["agent_run_id"]]


def stream_persistence_rows(client: TestClient, agent_run_id: str) -> tuple[sqlite3.Row, sqlite3.Row]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (agent_run_id,)).fetchone()
        assert run is not None
        assistant_message = conn.execute(
            "SELECT * FROM messages WHERE id = ?",
            (run["assistant_message_id"],),
        ).fetchone()
        assert assistant_message is not None
    return run, assistant_message


def insert_daily_history_message(
    client: TestClient,
    *,
    conversation_id: str,
    message_id: str,
    content: str,
    created_at: str,
) -> None:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO conversations (id, title, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            (conversation_id, conversation_id, created_at, created_at),
        )
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, 'user', ?, 'completed', ?, ?)
            """,
            (message_id, conversation_id, content, created_at, created_at),
        )
        conn.commit()


def stream_chat(client: TestClient, message: str) -> list[dict[str, str]]:
    chat = client.post("/api/chat", headers=auth(), json={"message": message})
    assert chat.status_code == 200
    with client.stream("GET", chat.json()["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())
    return parse_sse_events(body)


def stream_chat_with_payload(client: TestClient, message: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    chat = client.post("/api/chat", headers=auth(), json={"message": message})
    assert chat.status_code == 200
    payload = chat.json()
    with client.stream("GET", payload["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())
    return payload, parse_sse_events(body)


def wait_for_agent_actions(
    client: TestClient,
    agent_run_id: str,
    *,
    action_type: str | None = None,
    timeout_seconds: float = 3.0,
) -> list[dict[str, object]]:
    deadline = time.time() + timeout_seconds
    latest: list[dict[str, object]] = []
    while time.time() < deadline:
        response = client.get(
            "/api/agent/actions",
            headers=auth(),
            params={"agent_run_id": agent_run_id, "limit": 50},
        )
        assert response.status_code == 200
        latest = response.json()["actions"]
        if action_type is None:
            if latest:
                return latest
        elif any(action["action_type"] == action_type for action in latest):
            return latest
        time.sleep(0.05)
    return latest


def wait_for_continuity_proposals(client: TestClient, *, timeout_seconds: float = 3.0) -> list[dict[str, object]]:
    deadline = time.time() + timeout_seconds
    latest: list[dict[str, object]] = []
    while time.time() < deadline:
        response = client.get("/api/continuity/proposals", headers=auth())
        assert response.status_code == 200
        latest = response.json()["proposals"]
        if latest:
            return latest
        time.sleep(0.05)
    return latest


def agent_run_id_from_events(events: list[dict[str, str]]) -> str:
    for event in events:
        payload = json.loads(event["data"])
        agent_run_id = payload.get("agent_run_id")
        if isinstance(agent_run_id, str):
            return agent_run_id
    raise AssertionError("SSE events did not include agent_run_id")


def enable_automation(
    client: TestClient,
    *,
    chat_diary: bool = False,
    structured_memory: bool = False,
    long_term_memory: bool = False,
    wiki_organize: bool = False,
) -> None:
    response = client.put(
        "/api/settings/automation",
        headers=auth(),
        json={
            "auto_chat_diary": chat_diary,
            "auto_structured_memory": structured_memory,
            "auto_long_term_memory": long_term_memory,
            "auto_wiki_organize": wiki_organize,
        },
    )
    assert response.status_code == 200


def disable_negotiation(client: TestClient) -> None:
    current = client.get("/api/settings/automation", headers=auth())
    assert current.status_code == 200
    payload = current.json()
    payload.pop("updated_at", None)
    payload.pop("high_risk_confirmation_required", None)
    payload["use_negotiation"] = False
    response = client.put(
        "/api/settings/automation",
        headers=auth(),
        json=payload,
    )
    assert response.status_code == 200


def event_names(events: list[dict[str, str]]) -> list[str]:
    return [event["event"] for event in events]


def non_status_event_names(events: list[dict[str, str]]) -> list[str]:
    return [event["event"] for event in events if event["event"] != "status"]


def assert_successful_chat_events(events: list[dict[str, str]]) -> None:
    assert events[0]["event"] == "status"
    assert events[-1]["event"] == "done"
    assert "token" in event_names(events)
    assert "error" not in event_names(events)


def test_automation_settings_api_roundtrip(client: TestClient) -> None:
    defaults = client.get("/api/settings/automation", headers=auth())
    assert defaults.status_code == 200
    assert defaults.json() == {
        "auto_chat_diary": False,
        "auto_structured_memory": False,
        "auto_long_term_memory": False,
        "auto_wiki_organize": False,
        "local_privacy_mode": False,
        "proactive_trigger_frequency": "low",
        "use_negotiation": False,
        "max_rounds": 5,
        "high_risk_confirmation_required": True,
        "updated_at": None,
    }

    updated = client.put(
        "/api/settings/automation",
        headers=auth(),
        json={
            "auto_chat_diary": False,
            "auto_structured_memory": True,
            "auto_long_term_memory": False,
            "auto_wiki_organize": False,
            "local_privacy_mode": True,
            "proactive_trigger_frequency": "high",
            "use_negotiation": False,
            "max_rounds": 2,
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["auto_chat_diary"] is False
    assert payload["auto_structured_memory"] is True
    assert payload["auto_long_term_memory"] is False
    assert payload["auto_wiki_organize"] is False
    assert payload["local_privacy_mode"] is True
    assert payload["proactive_trigger_frequency"] == "high"
    assert payload["use_negotiation"] is False
    assert payload["max_rounds"] == 2
    assert payload["high_risk_confirmation_required"] is True
    assert payload["updated_at"]

    negotiation_payload = payload.copy()
    negotiation_payload.pop("updated_at", None)
    negotiation_payload.pop("high_risk_confirmation_required", None)
    negotiation_payload.update({"use_negotiation": True, "max_rounds": 10})
    negotiated = client.put(
        "/api/settings/automation",
        headers=auth(),
        json=negotiation_payload,
    )
    assert negotiated.status_code == 200
    assert negotiated.json()["use_negotiation"] is True
    assert negotiated.json()["max_rounds"] == 10
    assert negotiated.json()["local_privacy_mode"] is True
    assert negotiated.json()["proactive_trigger_frequency"] == "high"

    invalid = client.put(
        "/api/settings/automation",
        headers=auth(),
        json={"max_rounds": 11},
    )
    assert invalid.status_code == 422

    status = client.get("/api/settings", headers=auth())
    assert status.status_code == 200
    assert status.json()["automation"] == negotiated.json()


def test_settings_mutations_use_domain_specific_routes(client: TestClient) -> None:
    legacy = client.patch(
        "/api/settings",
        headers=auth(),
        json={"provider": "openai-compatible"},
    )
    assert legacy.status_code == 405

    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]["/api/settings"]) == {"get"}
    assert "put" in schema["paths"]["/api/settings/model-config"]
    assert "put" in schema["paths"]["/api/settings/automation"]


def test_tts_settings_api_roundtrip_without_sensitive_state(client: TestClient) -> None:
    defaults = client.get("/api/settings/tts", headers=auth())
    assert defaults.status_code == 200
    assert defaults.json() == {
        "enabled": False,
        "auto_play_assistant_reply": False,
        "auto_play_reminders": False,
        "provider": "system",
        "base_url": None,
        "model": None,
        "voice": None,
        "speed": 1.0,
        "volume": 1.0,
        "response_format": "mp3",
        "requires_api_key": False,
        "api_style": "generic",
        "auth_header_name": None,
        "request_template": None,
        "audio_json_path": None,
        "audio_encoding": "base64",
        "mime_type": None,
        "cache_enabled": False,
        "night_quiet_mode": True,
        "configured": False,
        "status": "disabled",
        "key_configured": False,
        "key_masked": None,
        "updated_at": None,
    }

    secret = "sk-tts-secret-should-not-persist"
    updated = client.put(
        "/api/settings/tts",
        headers=auth(),
        json={
            "enabled": True,
            "auto_play_assistant_reply": True,
            "auto_play_reminders": False,
            "provider": "system",
            "base_url": None,
            "model": None,
            "voice": {
                "id": "system-default",
                "provider": "system",
                "label": "System default",
                "locale": "zh-CN",
            },
            "speed": 1.2,
            "volume": 0.6,
            "response_format": "mp3",
            "requires_api_key": False,
            "cache_enabled": True,
            "night_quiet_mode": True,
            "api_key": secret,
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["enabled"] is True
    assert payload["auto_play_assistant_reply"] is True
    assert payload["provider"] == "system"
    assert payload["voice"]["id"] == "system-default"
    assert payload["speed"] == 1.2
    assert payload["volume"] == 0.6
    assert payload["cache_enabled"] is True
    assert payload["configured"] is True
    assert payload["status"] == "ready"
    assert payload["updated_at"]
    assert "api_key" not in payload
    assert secret not in updated.text

    status = client.get("/api/settings", headers=auth())
    assert status.status_code == 200
    assert status.json()["tts_settings"] == payload

    with sqlite3.connect(client.app.state.database.path) as conn:
        stored = conn.execute("SELECT value FROM app_state WHERE key = 'tts_settings'").fetchone()[0]
    stored_payload = json.loads(stored)
    assert "api_key" not in stored_payload
    assert secret not in stored

    cloud = client.put(
        "/api/settings/tts",
        headers=auth(),
        json={
            "enabled": True,
            "auto_play_assistant_reply": True,
            "provider": "custom-http",
            "base_url": "https://tts.example.test/synthesize",
            "requires_api_key": True,
        },
    )
    assert cloud.status_code == 200
    assert cloud.json()["configured"] is False
    assert cloud.json()["status"] == "credential_missing"


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
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
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


def test_vault_status_exposes_safe_migration_summary(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "PortableVault"
    wiki_root = vault / "Wiki"
    diary_root = vault / "Memories" / "Daily" / "2026" / "06" / "02"
    wiki_root.mkdir(parents=True)
    diary_root.mkdir(parents=True)
    (vault / "People.md").write_text("# People\n\nAda likes portable vaults.\n", encoding="utf-8")
    (wiki_root / "Local.md").write_text("# Local\n\nVault files are local Markdown.\n", encoding="utf-8")
    (diary_root / "2026-06-02.md").write_text("# Daily\n\nToday we checked migration.\n", encoding="utf-8")

    bind = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert bind.status_code == 200
    vault_id = bind.json()["vault_id"]
    indexed = client.post(f"/api/vaults/{vault_id}/index", headers=auth())
    assert indexed.status_code == 200

    status = client.get("/api/vaults/status", headers=auth())
    assert status.status_code == 200
    payload = status.json()
    assert payload["configured"] is True
    assert payload["active_vault_id"] == vault_id
    assert payload["root_path"] == str(vault)
    assert payload["root_path_label"].endswith("PortableVault")
    assert str(tmp_path) not in payload["root_path_label"]
    assert payload["latest_indexed_at"]
    assert payload["markdown_count"] == 3
    assert payload["wiki_page_count"] == 1
    assert payload["diary_page_count"] == 1


def test_wiki_diagnostics_queue_api_is_read_only_and_auth_required(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    wiki_root = vault / "Wiki"
    wiki_root.mkdir(parents=True)
    (wiki_root / "Inbox.md").write_text(
        "# Inbox\n\nThis stale claim conflicts with earlier notes. See [[Missing Concept]].\n",
        encoding="utf-8",
    )
    bind = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert bind.status_code == 200

    denied = client.post("/api/wiki/diagnostics/queue", json={})
    assert denied.status_code == 401
    response = client.post(
        "/api/wiki/diagnostics/queue",
        headers=auth(),
        json={"include_repair_preview": True},
    )
    second = client.post(
        "/api/wiki/diagnostics/queue",
        headers=auth(),
        json={"include_repair_preview": True},
    )

    assert response.status_code == 200
    assert second.status_code == 200
    payload = response.json()
    assert {item["kind"] for item in payload["items"]} == {
        "contradiction",
        "stale_claim",
        "missing_link",
        "missing_concept",
    }
    assert [item["id"] for item in payload["items"]] == [item["id"] for item in second.json()["items"]]
    assert payload["items"][0]["repair_proposal"] is not None
    assert not (wiki_root / "AGENTS.md").exists()
    assert not (wiki_root / "index.md").exists()
    assert not (wiki_root / "log.md").exists()
    assert not (wiki_root / "Reports").exists()


def test_companion_consolidation_and_context_report_apis_are_wired(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    bind = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert bind.status_code == 200
    vault_id = bind.json()["vault_id"]
    db_path = client.app.state.database.path
    now = "2026-05-15T10:00:00+08:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO diary_memory_objects (
                id, vault_id, type, summary, topic, emotion, people_json,
                keywords_json, importance, confidence, occurred_at, timezone,
                status, object_hash, extraction_model, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "diary-api-1",
                vault_id,
                "event",
                "Ada prefers concise status updates.",
                "coding style",
                "focused",
                '["Ada"]',
                '["style"]',
                0.8,
                0.95,
                now,
                "Asia/Shanghai",
                "active",
                "diary-api-hash-1",
                "fake",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO companion_retrieval_reports (
                id, agent_run_id, strategy, query_hash, candidate_count, selected_count,
                duplicate_drop_count, per_scope_drop_count, budget_drop_count,
                item_budget, per_scope_limit, char_budget, used_chars,
                source_counts_json, selected_scopes_json, created_at
            )
            VALUES (
                'report-api-1', 'run-api-1', 'deterministic_v1', 'hash-only',
                1, 1, 0, 0, 0, 5, 2, 1200, 32,
                '{"personal_memory":1}', '["personal_memory"]', ?
            )
            """,
            (now,),
        )
        conn.commit()

    denied = client.post("/api/memory/companion/consolidation/runs", json={})
    assert denied.status_code == 401
    run = client.post(
        "/api/memory/companion/consolidation/runs",
        headers=auth(),
        json={"from": "2026-05-15T00:00:00+08:00", "to": "2026-05-16T00:00:00+08:00"},
    )
    reports = client.get("/api/memory/companion/context-reports?agent_run_id=run-api-1", headers=auth())

    assert run.status_code == 200
    run_payload = run.json()
    assert run_payload["status"] == "completed"
    assert run_payload["source_count"] == 1
    assert run_payload["output_count"] == 1
    assert reports.status_code == 200
    report_payload = reports.json()["reports"][0]
    assert report_payload["agent_run_id"] == "run-api-1"
    assert report_payload["strategy"] == "deterministic_v1"
    assert "query" not in report_payload
    assert "hash-only" not in reports.text


def test_retrospective_apis_aggregate_local_assets_and_write_reversible_report(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    init = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    assert init.status_code == 200
    vault_id = init.json()["vault_id"]
    db_path = client.app.state.database.path
    now_dt = datetime.now(timezone.utc)
    diary_occurred_at = (now_dt - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    fact_created_at = (now_dt - timedelta(days=1) + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    now = now_dt.isoformat().replace("+00:00", "Z")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO diary_memory_objects (
                id, vault_id, type, summary, topic, emotion, people_json,
                keywords_json, importance, confidence, occurred_at, timezone,
                status, object_hash, extraction_model, created_at, updated_at
            )
            VALUES (
                'diary-retro-api-1', ?, 'event', 'Reviewed local retrospective API.', 'retrospective',
                'focused', '[]', '["retrospective","local"]', 0.9, 0.95,
                ?, 'UTC', 'active', 'hash-retro-api-1', 'fake', ?, ?
            )
            """,
            (vault_id, diary_occurred_at, now, now),
        )
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at, memory_type, entity_type, occurred_at,
                expires_at, metadata_json, importance
            )
            VALUES (
                'fact-retro-api-1', 'retro-api-key', 'retro-api-conflict', 'preference',
                'report cadence', 'prefers', 'weekly local review', 'active', 0.88,
                'User prefers weekly local review.', 'user_message', 2,
                ?, ?,
                'preference', 'preference', NULL, NULL, '{}', 0.8
            )
            """,
            (fact_created_at, fact_created_at),
        )
        conn.commit()

    denied = client.get("/api/memory/retrospectives")
    assert denied.status_code == 401

    listed = client.get("/api/memory/retrospectives", headers=auth())
    assert listed.status_code == 200
    seven = next(window for window in listed.json()["windows"] if window["days"] == 7)
    assert seven["has_data"] is True
    assert seven["summary"]["diary_objects"] == 1
    assert seven["summary"]["long_term_memories"] == 1
    assert seven["topics"][0]["sources"]

    report = client.post("/api/memory/retrospectives/report", headers=auth(), json={"days": 7})
    assert report.status_code == 200
    payload = report.json()
    assert payload["page"]["relative_path"].startswith("Wiki/Companion/Reports/")
    assert payload["action"]["action_type"] == "wiki.retrospective_report.write"
    assert payload["action"]["reversible"] is True
    report_path = vault.joinpath(*payload["page"]["relative_path"].split("/"))
    assert report_path.exists()
    assert "retrospective" in report_path.read_text(encoding="utf-8")

    weekly_report = client.post("/api/memory/retrospectives/report", headers=auth(), json={"period": "weekly"})
    assert weekly_report.status_code == 200
    weekly_payload = weekly_report.json()
    assert weekly_payload["page"]["relative_path"].startswith("Wiki/Companion/Reports/")
    assert "-weekly-" in weekly_payload["page"]["relative_path"]
    assert weekly_payload["action"]["action_type"] == "wiki.weekly_report.write"
    weekly_path = vault.joinpath(*weekly_payload["page"]["relative_path"].split("/"))
    assert weekly_path.exists()
    weekly_markdown = weekly_path.read_text(encoding="utf-8")
    assert "type: weekly_report" in weekly_markdown
    assert "## 本周主要主题" in weekly_markdown
    assert "## 重要对话和日记摘要" in weekly_markdown

    actions = client.get("/api/agent/actions", headers=auth())
    assert actions.status_code == 200
    action_ids = {action["action_id"] for action in actions.json()["actions"]}
    assert payload["action"]["action_id"] in action_ids
    assert weekly_payload["action"]["action_id"] in action_ids


def test_today_snapshot_api_is_protected_and_returns_visible_continuity_contract(
    client: TestClient,
    tmp_path: Path,
) -> None:
    denied = client.get("/api/today/snapshot")
    assert denied.status_code == 401

    empty = client.get("/api/today/snapshot", headers=auth())
    assert empty.status_code == 200
    empty_payload = empty.json()
    assert empty_payload["today_card"]["source_count"] == 0
    assert empty_payload["recent_receipts"] == []
    assert empty_payload["project_cards"] == []
    assert empty_payload["playback_preview"]["period"] == "weekly"

    vault = tmp_path / "Vault"
    init = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    assert init.status_code == 200
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            """
            INSERT INTO tasks(id, title, description, due_at_utc, status, source_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "today-snapshot-task-1",
                "Ship project Agent Pet snapshot API",
                "Expose one visible continuity endpoint.",
                None,
                "pending",
                "project Agent Pet",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO agent_actions (
                id, action_type, risk_tier, decision, status, title, summary,
                target_paths_json, before_snapshot_json, after_snapshot_json,
                metadata_json, reversible, created_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', ?, ?, ?, ?)
            """,
            (
                "today-snapshot-action-1",
                "wiki.answer_summary.write",
                "low",
                "auto",
                "completed",
                "Saved snapshot summary",
                "Saved a safe visible continuity summary.",
                '["Wiki/Companion/Summaries/today-snapshot.md"]',
                1,
                now,
                now,
                now,
            ),
        )

    response = client.get("/api/today/snapshot", headers=auth())
    assert response.status_code == 200
    payload = response.json()
    assert payload["today_card"]["source_count"] >= 2
    assert payload["recent_receipts"][0]["action_id"] == "today-snapshot-action-1"
    assert payload["recent_receipts"][0]["target_path"] == "Wiki/Companion/Summaries/today-snapshot.md"
    assert payload["project_cards"]
    assert payload["project_cards"][0]["sources"] == ["tasks:today-snapshot-task-1"]


def test_vault_status_recovers_persisted_active_vault_after_restart(
    client: TestClient,
    tmp_path: Path,
) -> None:
    first_vault = tmp_path / "FirstVault"
    second_vault = tmp_path / "SecondVault"

    first = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(first_vault), "create_if_missing": True, "confirmed": True},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(second_vault), "create_if_missing": True, "confirmed": True},
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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    now = "2026-05-15T10:00:00Z"
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at, memory_type, entity_type, occurred_at,
                expires_at, metadata_json, importance
            )
            VALUES (
                'fact-api-actions-1', 'fact-api-actions-key', 'fact-api-actions-conflict',
                'preference', 'fruit', 'likes', 'apple', 'active', 0.95,
                'I like apple', 'user_message', 1, ?, ?, 'preference',
                'preference', NULL, NULL, '{}', 0.8
            )
            """,
            (now, now),
        )
        conn.commit()

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

    wrong = client.post(f"/api/memory/graph/facts/{fact_id}/wrong", headers=auth())
    assert wrong.status_code == 200
    assert wrong.json()["status"] == "wrong"
    search = client.post(
        "/api/memory/search",
        headers=auth(),
        json={"query": "fruit", "top_k": 5, "source_scope": "personal_memory", "mode": "fts"},
    )
    assert search.status_code == 200
    assert all(result["retrieval_mode"] != "graph" for result in search.json()["results"])
    assert all(result["relative_path"] != "Memories/LongTerm/Preferences.md" for result in search.json()["results"])

    sensitive_blocked = client.post(f"/api/memory/graph/facts/{fact_id}/sensitive-block", headers=auth())
    assert sensitive_blocked.status_code == 200
    assert sensitive_blocked.json()["status"] == "sensitive_blocked"

    confirmed_again = client.post(f"/api/memory/graph/facts/{fact_id}/confirm", headers=auth())
    assert confirmed_again.status_code == 200
    assert confirmed_again.json()["status"] == "active"

    export = client.get("/api/memory/graph/export-preview?query=fruit&format=markdown", headers=auth())
    assert export.status_code == 200
    payload = export.json()
    assert payload["item_count"] == 1
    assert "source_text" not in payload["json_preview"]
    assert "I like apple" not in payload["json_preview"]
    assert "I like apple" not in payload["markdown_preview"]
    assert payload["items"][0]["subject"] == "fruit"
    assert "source_text" not in payload["items"][0]


def test_local_asset_stats_api_is_local_read_only_and_no_data_safe(
    client: TestClient,
    tmp_path: Path,
) -> None:
    denied = client.get("/api/memory/local-assets")
    assert denied.status_code == 401

    empty = client.get("/api/memory/local-assets", headers=auth())
    assert empty.status_code == 200
    assert empty.json() == {
        "vault_configured": False,
        "vault_id": None,
        "chat_diary_days": 0,
        "chat_diary_entries": 0,
        "long_term_memory_count": 0,
        "wiki_page_count": 0,
        "task_count": 0,
        "completed_task_count": 0,
        "latest_organization_at": None,
        "reversible_operation_count": 0,
    }

    vault = tmp_path / "Vault"
    init = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    assert init.status_code == 200
    vault_id = init.json()["vault_id"]
    wiki = vault / "Wiki"
    (wiki / "Concepts").mkdir(parents=True, exist_ok=True)
    (wiki / "Reports").mkdir(parents=True, exist_ok=True)
    (wiki / "AGENTS.md").write_text("# Core\n", encoding="utf-8")
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
    (wiki / "Concepts" / "Local Assets.md").write_text("# Local Assets\n", encoding="utf-8")
    (wiki / "Reports" / "Weekly.md").write_text("# Weekly\n", encoding="utf-8")

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO daily_chat_memory_entries(
                id, conversation_id, user_message_id, assistant_message_id,
                agent_run_id, entry_hash, memory_date, memory_time, timezone,
                markdown_path, created_at, updated_at
            )
            VALUES
                ('daily-1', 'conv-1', 'user-1', 'assistant-1', 'run-1', 'hash-1',
                 '2026-06-01', '10:00:00', 'Asia/Shanghai', 'Memories/Daily/2026-06-01.md',
                 '2026-06-01T02:00:00Z', '2026-06-01T02:00:00Z'),
                ('daily-2', 'conv-1', 'user-2', 'assistant-2', 'run-2', 'hash-2',
                 '2026-06-01', '11:00:00', 'Asia/Shanghai', 'Memories/Daily/2026-06-01.md',
                 '2026-06-01T03:00:00Z', '2026-06-01T03:00:00Z'),
                ('daily-3', 'conv-2', 'user-3', 'assistant-3', 'run-3', 'hash-3',
                 '2026-06-02', '09:00:00', 'Asia/Shanghai', 'Memories/Daily/2026-06-02.md',
                 '2026-06-02T01:00:00Z', '2026-06-02T01:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at, memory_type, entity_type, occurred_at,
                expires_at, metadata_json, importance
            )
            VALUES
                ('fact-active', 'fact-key-active', 'conflict-active', 'preference', 'updates',
                 'prefer', 'concise', 'active', 0.91, 'User prefers concise updates.',
                 'user_message', 2, '2026-06-01T04:00:00Z', '2026-06-01T04:00:00Z',
                 'preference', 'preference', NULL, NULL, '{}', 0.8),
                ('fact-candidate', 'fact-key-candidate', 'conflict-candidate', 'fact', 'project',
                 'uses', 'local vault', 'candidate', 0.72, 'Project uses a local vault.',
                 'assistant_message', 1, '2026-06-01T05:00:00Z', '2026-06-01T05:00:00Z',
                 'fact', 'project', NULL, NULL, '{}', 0.6),
                ('fact-rejected', 'fact-key-rejected', 'conflict-rejected', 'fact', 'old',
                 'is', 'ignored', 'rejected', 0.5, 'Rejected memory.',
                 'assistant_message', 1, '2026-06-01T06:00:00Z', '2026-06-01T06:00:00Z',
                 'fact', 'project', NULL, NULL, '{}', 0.3)
            """
        )
        conn.execute(
            """
            INSERT INTO tasks(id, title, description, due_at_utc, status, source_text, created_at, updated_at)
            VALUES
                ('task-done', 'Finish dashboard', '', NULL, 'done', '', '2026-06-01T07:00:00Z', '2026-06-01T08:00:00Z'),
                ('task-pending', 'Review dashboard', '', NULL, 'pending', '', '2026-06-01T07:30:00Z', '2026-06-01T07:30:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO agent_actions (
                id, action_type, risk_tier, decision, status, title, summary,
                target_paths_json, before_snapshot_json, after_snapshot_json,
                metadata_json, reversible, reverted_by, reverts_action_id,
                created_at, updated_at, completed_at
            )
            VALUES
                ('action-1', 'wiki.page.write', 'low', 'auto', 'completed', 'Write page', '',
                 '["Wiki/Concepts/Local Assets.md"]', '{}', '{}', '{}', 1, NULL, NULL,
                 '2026-06-02T08:00:00Z', '2026-06-02T08:00:00Z', '2026-06-02T08:00:00Z'),
                ('action-2', 'wiki.page.write', 'low', 'auto', 'reverted', 'Old page', '',
                 '["Wiki/Old.md"]', '{}', '{}', '{}', 1, 'action-revert', NULL,
                 '2026-06-02T09:00:00Z', '2026-06-02T09:10:00Z', '2026-06-02T09:00:00Z'),
                ('action-3', 'chat.daily_archive', 'low', 'notify', 'skipped', 'Skipped', '',
                 '[]', '{}', '{}', '{"skipped_reason":"automation_disabled"}', 0, NULL, NULL,
                 '2026-06-02T10:00:00Z', '2026-06-02T10:00:00Z', NULL)
            """
        )
        before_actions = conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0]
        conn.commit()

    response = client.get("/api/memory/local-assets", headers=auth())
    assert response.status_code == 200
    payload = response.json()
    assert payload["vault_configured"] is True
    assert payload["vault_id"] == vault_id
    assert payload["chat_diary_days"] == 2
    assert payload["chat_diary_entries"] == 3
    assert payload["long_term_memory_count"] == 2
    assert payload["wiki_page_count"] == 2
    assert payload["task_count"] == 2
    assert payload["completed_task_count"] == 1
    assert payload["latest_organization_at"] == "2026-06-02T10:00:00Z"
    assert payload["reversible_operation_count"] == 1

    with sqlite3.connect(db_path) as conn:
        after_actions = conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0]
    assert after_actions == before_actions


def test_growth_snapshot_api_uses_memory_data_and_action_history(
    client: TestClient,
    tmp_path: Path,
) -> None:
    denied = client.get("/api/growth/snapshot")
    assert denied.status_code == 401

    empty = client.get("/api/growth/snapshot", headers=auth())
    assert empty.status_code == 200
    empty_payload = empty.json()
    assert [dimension["key"] for dimension in empty_payload["dimensions"]] == [
        "memory_depth",
        "response_affinity",
        "trust_boundary",
        "knowledge_links",
    ]
    assert all(dimension["current_value"] == 0 for dimension in empty_payload["dimensions"])
    assert empty_payload["events"] == []

    vault = tmp_path / "GrowthVault"
    init = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    assert init.status_code == 200
    vault_id = init.json()["vault_id"]
    wiki = vault / "Wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "Companion Growth.md").write_text("# Companion Growth\n", encoding="utf-8")

    db_path = client.app.state.database.path
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO daily_chat_memory_entries(
                id, conversation_id, user_message_id, assistant_message_id,
                agent_run_id, entry_hash, memory_date, memory_time, timezone,
                markdown_path, created_at, updated_at
            )
            VALUES
                ('growth-daily-1', 'conv-growth', 'user-1', 'assistant-1', 'run-1', 'growth-hash-1',
                 '2026-06-03', '09:00:00', 'Asia/Shanghai', 'Memories/Daily/2026-06-03.md',
                 '2026-06-03T01:00:00Z', '2026-06-03T01:00:00Z'),
                ('growth-daily-2', 'conv-growth', 'user-2', 'assistant-2', 'run-2', 'growth-hash-2',
                 '2026-06-04', '10:00:00', 'Asia/Shanghai', 'Memories/Daily/2026-06-04.md',
                 '2026-06-04T02:00:00Z', '2026-06-04T02:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at, memory_type, entity_type, occurred_at,
                expires_at, metadata_json, importance
            )
            VALUES
                ('growth-fact-style', 'growth-style', 'growth-style', 'preference', 'reply_style',
                 'prefers', 'brief check-ins', 'active', 0.91, 'User likes brief check-ins.',
                 'user_message', 2, '2026-06-03T03:00:00Z', '2026-06-03T03:00:00Z',
                 'preference', 'preference', NULL, NULL, '{}', 0.8),
                ('growth-fact-boundary', 'growth-boundary', 'growth-boundary', 'boundary', 'privacy',
                 'prefers', 'confirm before sensitive memory', 'candidate', 0.74, 'Ask first for sensitive memory.',
                 'user_message', 1, '2026-06-04T03:00:00Z', '2026-06-04T03:00:00Z',
                 'boundary', 'preference', NULL, NULL, '{}', 0.7),
                ('growth-fact-old', 'growth-old', 'growth-old', 'fact', 'old',
                 'is', 'ignored', 'rejected', 0.5, 'Rejected memory.',
                 'assistant_message', 1, '2026-06-04T04:00:00Z', '2026-06-04T04:00:00Z',
                 'fact', 'project', NULL, NULL, '{}', 0.2)
            """
        )
        conn.execute(
            """
            INSERT INTO diary_memory_objects (
                id, vault_id, type, summary, topic, emotion, people_json, keywords_json,
                importance, confidence, occurred_at, timezone, status, object_hash,
                extraction_model, created_at, updated_at
            )
            VALUES (
                'growth-diary-object-1', ?, 'preference', 'Prefers a low-pressure tone.',
                'tone', NULL, '[]', '["tone"]', 0.7, 0.88,
                '2026-06-04T05:00:00Z', 'Asia/Shanghai', 'active', 'growth-diary-hash-1',
                'fake-model', '2026-06-04T05:00:00Z', '2026-06-04T05:00:00Z'
            )
            """,
            (vault_id,),
        )
        conn.execute(
            """
            INSERT INTO agent_actions (
                id, action_type, risk_tier, decision, status, title, summary,
                target_paths_json, before_snapshot_json, after_snapshot_json,
                metadata_json, reversible, reverted_by, reverts_action_id,
                created_at, updated_at, completed_at
            )
            VALUES
                ('growth-action-diary', 'chat.daily_archive', 'low', 'auto', 'completed',
                 '已归档聊天日记', '写入 Memories/Daily/2026-06-03.md',
                 '["Memories/Daily/2026-06-03.md"]', '{}', '{}', '{}', 0, NULL, NULL,
                 '2026-06-03T01:00:00Z', '2026-06-03T01:00:00Z', '2026-06-03T01:00:00Z'),
                ('growth-action-memory', 'memory.long_term.write', 'low', 'auto', 'completed',
                 '已更新长期记忆', 'brief check-ins',
                 '[]', '{}', '{}', '{"graph_fact_id":"growth-fact-style"}', 0, NULL, NULL,
                 '2026-06-03T03:00:00Z', '2026-06-03T03:00:00Z', '2026-06-03T03:00:00Z'),
                ('growth-action-wiki', 'wiki.answer_summary.write', 'low', 'auto', 'completed',
                 '已沉淀回答摘要', '写入 Wiki/Companion Growth.md',
                 '["Wiki/Companion Growth.md"]', '{}', '{}', '{}', 1, NULL, NULL,
                 '2026-06-04T06:00:00Z', '2026-06-04T06:00:00Z', '2026-06-04T06:00:00Z'),
                ('growth-action-skip', 'memory.long_term.skip', 'high', 'ask', 'skipped',
                 '已跳过长期记忆', '敏感内容未写入',
                 '[]', '{}', '{}', '{"skipped_reason":"sensitive_life_domain"}', 0, NULL, NULL,
                 '2026-06-04T07:00:00Z', '2026-06-04T07:00:00Z', NULL),
                ('growth-action-revert', 'agent_action.revert', 'low', 'auto', 'completed',
                 '已撤销：已沉淀回答摘要', '恢复 1 个 Markdown 目标。',
                 '["Wiki/Companion Growth.md"]', '{}', '{}', '{}', 0, NULL, 'growth-action-wiki',
                 '2026-06-04T08:00:00Z', '2026-06-04T08:00:00Z', '2026-06-04T08:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO memory_feedback_events (
                id, candidate_id, fact_id, feedback_type, feedback_text,
                requested_status, replacement_candidate_id, metadata_json, created_at
            )
            VALUES (
                'growth-feedback-1', NULL, 'growth-fact-style', 'keep',
                'Keep this style preference.', 'active', NULL, '{}', '2026-06-04T09:00:00Z'
            )
            """
        )
        before_actions = conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0]
        conn.commit()

    response = client.get("/api/growth/snapshot", headers=auth())
    assert response.status_code == 200
    payload = response.json()
    dimensions = {dimension["key"]: dimension for dimension in payload["dimensions"]}
    assert dimensions["memory_depth"]["current_value"] == 4
    assert dimensions["memory_depth"]["level"] >= 2
    assert dimensions["response_affinity"]["current_value"] == 3
    assert dimensions["response_affinity"]["level"] >= 2
    assert dimensions["trust_boundary"]["current_value"] == 4
    assert dimensions["trust_boundary"]["level"] >= 3
    assert dimensions["knowledge_links"]["current_value"] == 1
    assert dimensions["knowledge_links"]["level"] == 1
    assert payload["stats"]["vault_id"] == vault_id
    assert payload["stats"]["chat_diary_entries"] == 2
    assert payload["stats"]["long_term_memory_count"] == 2

    events = payload["events"]
    assert events[0]["event_id"] == "growth-action-revert"
    assert events[0]["dimension_key"] == "trust_boundary"
    assert any(event["dimension_key"] == "knowledge_links" for event in events)
    assert any(event["dimension_key"] == "response_affinity" for event in events)

    with sqlite3.connect(db_path) as conn:
        after_actions = conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0]
    assert after_actions == before_actions


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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
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
            extraction_model="reflection_agent",
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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    disable_negotiation(client)

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
    assert_successful_chat_events(events)
    assert "continuity_proposal" not in event_names(events)

    proposals = wait_for_continuity_proposals(client)
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
    assert_successful_chat_events(events)
    assert "continuity_proposal" not in event_names(events)
    pending = wait_for_continuity_proposals(client)
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


@pytest.mark.asyncio
async def test_persisting_stream_aclose_marks_partial_records_cancelled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import chat as chat_api

    class TokenRuntime:
        async def run(self, state):
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text="partial reply")

    monkeypatch.setattr(chat_api, "agent_runtime", lambda request: TokenRuntime())
    payload, state = create_unstreamed_chat(client, "close this stream")
    events = chat_api._persisting_stream(api_request(client), state)

    first_event = await anext(events)
    assert first_event.event == "token"
    await events.aclose()

    run, assistant_message = stream_persistence_rows(client, payload["agent_run_id"])
    assert run["status"] == AgentRunStatus.CANCELLED.value
    assert run["error_code"] == "stream_cancelled"
    assert assistant_message["status"] == MessageStatus.CANCELLED.value
    assert assistant_message["content"] == "partial reply"
    assert payload["agent_run_id"] not in client.app.state.chat_runs


@pytest.mark.asyncio
async def test_persisting_stream_reraises_cancelled_error_after_persisting_terminal_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import chat as chat_api

    class BlockingRuntime:
        def __init__(self) -> None:
            self.waiting = asyncio.Event()

        async def run(self, state):
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text="partial reply")
            self.waiting.set()
            await asyncio.Event().wait()

    runtime = BlockingRuntime()
    monkeypatch.setattr(chat_api, "agent_runtime", lambda request: runtime)
    payload, state = create_unstreamed_chat(client, "cancel this stream")
    events = chat_api._persisting_stream(api_request(client), state)

    first_event = await anext(events)
    assert first_event.event == "token"
    pending_event = asyncio.create_task(anext(events))
    await asyncio.wait_for(runtime.waiting.wait(), timeout=1)
    pending_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_event

    run, assistant_message = stream_persistence_rows(client, payload["agent_run_id"])
    assert run["status"] == AgentRunStatus.CANCELLED.value
    assert run["error_code"] == "stream_cancelled"
    assert assistant_message["status"] == MessageStatus.CANCELLED.value
    assert assistant_message["content"] == "partial reply"
    assert payload["agent_run_id"] not in client.app.state.chat_runs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal_kind", "expected_event", "expected_message_status", "expected_run_status"),
    [
        ("done", "reply_ready", MessageStatus.COMPLETED.value, AgentRunStatus.SUCCESS.value),
        ("error", "error", MessageStatus.FAILED.value, AgentRunStatus.FAILED.value),
    ],
)
async def test_persisting_stream_aclose_after_terminal_event_does_not_repeat_updates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    terminal_kind: str,
    expected_event: str,
    expected_message_status: str,
    expected_run_status: str,
) -> None:
    from app.api import chat as chat_api

    class TerminalRuntime:
        async def run(self, state):
            if terminal_kind == "done":
                yield AgentDoneEvent(
                    agent_run_id=state.agent_run_id,
                    intent=AgentIntent.CHAT,
                    text="complete reply",
                )
            else:
                yield AgentErrorEvent(
                    agent_run_id=state.agent_run_id,
                    code="runtime_error",
                    message="runtime failed",
                )

    assistant_statuses: list[str] = []
    run_statuses: list[str] = []
    original_persist_terminal = chat_api._StreamPartialPersister.persist_terminal
    original_update_run = chat_api._update_agent_run

    async def track_persist_terminal(persister, content, status_value):
        assistant_statuses.append(status_value)
        await original_persist_terminal(persister, content, status_value)

    def track_run_update(
        request,
        state,
        assistant_message_id,
        status_value,
        *,
        error_code,
        error_message,
    ):
        run_statuses.append(status_value)
        original_update_run(
            request,
            state,
            assistant_message_id,
            status_value,
            error_code=error_code,
            error_message=error_message,
        )

    monkeypatch.setattr(chat_api, "agent_runtime", lambda request: TerminalRuntime())
    monkeypatch.setattr(chat_api, "_schedule_post_reply_work", lambda *args: None)
    monkeypatch.setattr(chat_api._StreamPartialPersister, "persist_terminal", track_persist_terminal)
    monkeypatch.setattr(chat_api, "_update_agent_run", track_run_update)
    payload, state = create_unstreamed_chat(client, f"terminal {terminal_kind}")
    events = chat_api._persisting_stream(api_request(client), state)

    terminal_event = await anext(events)
    assert terminal_event.event == expected_event
    await events.aclose()

    run, assistant_message = stream_persistence_rows(client, payload["agent_run_id"])
    assert assistant_statuses == [expected_message_status]
    assert run_statuses == [expected_run_status]
    assert assistant_message["status"] == expected_message_status
    assert run["status"] == expected_run_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal_sequence", "expected_events", "expected_message_status", "expected_run_status", "expected_error_code"),
    [
        (("done", "error"), ["reply_ready", "done"], MessageStatus.COMPLETED.value, AgentRunStatus.SUCCESS.value, None),
        (("error", "done"), ["error"], MessageStatus.FAILED.value, AgentRunStatus.FAILED.value, "late_error"),
        (("done", "done"), ["reply_ready", "done"], MessageStatus.COMPLETED.value, AgentRunStatus.SUCCESS.value, None),
        (("error", "error"), ["error"], MessageStatus.FAILED.value, AgentRunStatus.FAILED.value, "late_error"),
    ],
)
async def test_persisting_stream_first_terminal_event_wins(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    terminal_sequence: tuple[str, str],
    expected_events: list[str],
    expected_message_status: str,
    expected_run_status: str,
    expected_error_code: str | None,
) -> None:
    from app.api import chat as chat_api

    class ContradictoryRuntime:
        async def run(self, state):
            for terminal in terminal_sequence:
                if terminal == "done":
                    yield AgentDoneEvent(
                        agent_run_id=state.agent_run_id,
                        intent=AgentIntent.CHAT,
                        text="first completed reply",
                    )
                else:
                    yield AgentErrorEvent(
                        agent_run_id=state.agent_run_id,
                        code="late_error",
                        message="contradictory terminal",
                    )

    monkeypatch.setattr(chat_api, "agent_runtime", lambda request: ContradictoryRuntime())
    monkeypatch.setattr(chat_api, "_schedule_post_reply_work", lambda *args: None)
    payload, state = create_unstreamed_chat(client, "first terminal wins")

    events = [event async for event in chat_api._persisting_stream(api_request(client), state)]

    assert [event.event for event in events] == expected_events
    run, assistant_message = stream_persistence_rows(client, payload["agent_run_id"])
    assert assistant_message["status"] == expected_message_status
    assert run["status"] == expected_run_status
    assert run["error_code"] == expected_error_code


def test_daily_history_limit_returns_latest_messages_in_ascending_order(client: TestClient) -> None:
    for index in range(5):
        insert_daily_history_message(
            client,
            conversation_id=f"conversation-{index}",
            message_id=f"history-{index}",
            content=f"HISTORY_{index}",
            created_at=f"2026-07-09T00:0{index}:00Z",
        )

    limited = client.get(
        "/api/chat/daily-history",
        headers=auth(),
        params={"date": "2026-07-09", "timezone": "UTC", "limit": 3},
    )

    assert limited.status_code == 200
    payload = limited.json()
    assert [message["content"] for message in payload["messages"]] == [
        "HISTORY_2",
        "HISTORY_3",
        "HISTORY_4",
    ]
    assert payload["conversation_id"] == "conversation-4"
    assert payload["has_more"] is True

    complete = client.get(
        "/api/chat/daily-history",
        headers=auth(),
        params={"date": "2026-07-09", "timezone": "UTC", "limit": 5},
    )
    assert complete.status_code == 200
    assert complete.json()["has_more"] is False


def test_chat_run_lookup_removes_expired_unstreamed_runs(client: TestClient) -> None:
    response = client.post("/api/chat", headers=auth(), json={"message": "expire this run"})
    assert response.status_code == 200
    payload = response.json()
    agent_run_id = payload["agent_run_id"]

    client.app.state.chat_runs_expires_at[agent_run_id] = time.monotonic() - 1
    stream = client.get(payload["stream_url"], headers=auth())

    assert stream.status_code == 404
    assert stream.json()["error"]["code"] == "agent_run_not_found"
    assert agent_run_id not in client.app.state.chat_runs
    assert agent_run_id not in client.app.state.chat_runs_expires_at
    run, assistant_message = stream_persistence_rows(client, agent_run_id)
    assert run["status"] == AgentRunStatus.CANCELLED.value
    assert run["error_code"] == "stream_not_started_or_expired"
    assert assistant_message["status"] == MessageStatus.CANCELLED.value
    assert assistant_message["content"] == ""


def test_chat_stream_auto_archives_daily_memory_and_records_action(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import chat as chat_api

    vault = tmp_path / "Vault"
    vault.mkdir()
    bind = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert bind.status_code == 200
    enable_automation(client, chat_diary=True)

    class SimpleRuntime:
        async def run(self, state):
            yield AgentStatusEvent(
                agent_run_id=state.agent_run_id,
                status=state.status,
                intent=AgentIntent.CHAT,
                message="replying",
                stage="chat_generation",
            )
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text="已记下。")
            yield AgentDoneEvent(
                agent_run_id=state.agent_run_id,
                intent=AgentIntent.CHAT,
                text="已记下。",
            )

    monkeypatch.setattr(chat_api, "agent_runtime", lambda request: SimpleRuntime())

    chat = client.post(
        "/api/chat",
        headers=auth(),
        json={"message": "今天我完成了自动整理测试"},
    )
    assert chat.status_code == 200
    chat_payload = chat.json()
    with client.stream("GET", chat_payload["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())

    events = parse_sse_events(body)
    event_names_for_order = event_names(events)
    assert event_names_for_order[-1] == "done"
    assert "reply_ready" in event_names_for_order
    assert "agent_action" not in event_names_for_order
    action_payloads = wait_for_agent_actions(
        client,
        chat_payload["agent_run_id"],
        action_type="chat.daily_archive",
    )
    action_payload = next(action for action in action_payloads if action["action_type"] == "chat.daily_archive")
    assert action_payload["action_type"] == "chat.daily_archive"
    assert action_payload["decision"] == "auto"
    assert action_payload["source_agent_run_id"] == chat_payload["agent_run_id"]
    assert action_payload["source_conversation_id"] == chat_payload["conversation_id"]
    assert action_payload["source_message_id"] == chat_payload["message_id"]
    assert action_payload["source"]["source_agent_run_id"] == chat_payload["agent_run_id"]
    assert action_payload["created_at"]
    assert action_payload["target_paths"][0].startswith("Memories/Daily/")

    listed = client.get(
        f"/api/agent/actions?agent_run_id={chat_payload['agent_run_id']}",
        headers=auth(),
    )
    assert listed.status_code == 200
    actions = listed.json()["actions"]
    assert [action["action_type"] for action in actions] == ["chat.daily_archive"]
    assert (vault / actions[0]["target_paths"][0]).exists()

    growth = client.get("/api/growth/snapshot", headers=auth())
    assert growth.status_code == 200
    growth_payload = growth.json()
    dimensions = {dimension["key"]: dimension for dimension in growth_payload["dimensions"]}
    assert dimensions["memory_depth"]["current_value"] >= 1
    assert dimensions["memory_depth"]["level"] >= 1
    assert growth_payload["stats"]["chat_diary_entries"] >= 1
    assert any(event["source_action_type"] == "chat.daily_archive" for event in growth_payload["events"])


def test_chat_stream_auto_summarizes_useful_answer_to_wiki(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import chat as chat_api

    vault = tmp_path / "Vault"
    vault.mkdir()
    bind = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert bind.status_code == 200
    enable_automation(client, chat_diary=True, wiki_organize=True)

    class KnowledgeRuntime:
        async def run(self, state):
            answer = (
                "- 桌宠应根据用户意图检索日记、长期记忆和 Wiki。\n"
                "- 回答完成后要写入日记，并自我总结。\n"
                "- 有价值总结应带证据、更新日志和自检清单写入 Wiki。"
            )
            yield AgentStatusEvent(
                agent_run_id=state.agent_run_id,
                status=state.status,
                intent=AgentIntent.CHAT,
                message="replying",
                stage="chat_generation",
            )
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=answer)
            yield AgentDoneEvent(
                agent_run_id=state.agent_run_id,
                intent=AgentIntent.CHAT,
                text=answer,
            )

    monkeypatch.setattr(chat_api, "agent_runtime", lambda request: KnowledgeRuntime())

    chat = client.post(
        "/api/chat",
        headers=auth(),
        json={"message": "优化桌宠回答后日记和 Wiki 自动整理流程"},
    )
    assert chat.status_code == 200
    chat_payload = chat.json()
    with client.stream("GET", chat_payload["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())

    events = parse_sse_events(body)
    assert_successful_chat_events(events)
    assert "agent_action" not in event_names(events)
    action_payloads = wait_for_agent_actions(
        client,
        chat_payload["agent_run_id"],
        action_type="wiki.answer_summary.write",
    )
    action_types = [payload["action_type"] for payload in action_payloads]
    assert "chat.daily_archive" in action_types
    assert "wiki.answer_summary.write" in action_types
    wiki_action = next(payload for payload in action_payloads if payload["action_type"] == "wiki.answer_summary.write")
    assert wiki_action["decision"] == "auto"
    assert wiki_action["reversible"] is True
    assert wiki_action["source_agent_run_id"] == chat_payload["agent_run_id"]
    assert wiki_action["source"]["source_message_id"] == chat_payload["message_id"]
    assert wiki_action["diff_summary"]
    assert wiki_action["created_at"]
    assert wiki_action["target_paths"][0].startswith("Wiki/Companion/Summaries/")

    page_path = vault.joinpath(*wiki_action["target_paths"][0].split("/"))
    text = page_path.read_text(encoding="utf-8")
    assert "### 核心定义" in text
    assert "### 原文出处" in text
    assert "### 自检清单" in text
    assert "agent_run_id" in text
    assert wiki_action["target_paths"][0] in (vault / "Wiki" / "log.md").read_text(encoding="utf-8")


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
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert bind.status_code == 200
    indexed = client.post(f"/api/vaults/{bind.json()['vault_id']}/index", headers=auth())
    assert indexed.status_code == 200
    disable_negotiation(client)

    events = stream_chat(client, "search memory for citation-term")

    status_events = [event for event in events if event.get("event") == "status"]
    status_payloads = [json.loads(event["data"]) for event in status_events]
    assert any("personal_memory" in payload.get("source_scopes", []) for payload in status_payloads)
    assert any("knowledge_base" in payload.get("source_scopes", []) for payload in status_payloads)
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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    enable_automation(client, chat_diary=True)

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


def _legacy_chat_done_auto_writes_long_term_memory_for_explicit_preference(
    client: TestClient,
    tmp_path: Path,
) -> None:
    return
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    enable_automation(client, long_term_memory=True)

    events = stream_chat(client, "我喜欢的水果是苹果")

    assert_successful_chat_events(events)
    assert "- 类型：preference" in content
    assert "- 主题：水果" in content
    assert "- 内容：用户的水果是苹果" in content
    assert "- 来源原文：我喜欢的水果是苹果" in content


def test_chat_done_auto_long_term_records_candidate_without_vault_profile(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    enable_automation(client, long_term_memory=True)

    chat_payload, events = stream_chat_with_payload(client, "Remember this: my favorite editor is VS Code.")

    assert_successful_chat_events(events)
    foreground_actions = [
        json.loads(event["data"])
        for event in events
        if event["event"] == "agent_action"
    ]
    assert any(action["action_type"] == "memory.proposal.defer" for action in foreground_actions)
    action_payloads = wait_for_agent_actions(
        client,
        chat_payload["agent_run_id"],
        action_type="memory.consolidation.candidate",
    )
    action = next(payload for payload in action_payloads if payload["action_type"] == "memory.consolidation.candidate")
    assert action["decision"] == "auto"
    assert action["metadata"]["candidate_count"] == 1
    assert action["metadata"]["kinds"] == ["preference"]

    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        candidate = conn.execute("SELECT * FROM memory_candidates").fetchone()
        evidence_count = conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0]
        graph_count = conn.execute("SELECT COUNT(*) FROM memory_graph_facts").fetchone()[0]
    assert candidate["memory_kind"] == "preference"
    assert candidate["source_track"] == "explicit_user"
    assert candidate["status"] == "active"
    assert evidence_count == 1
    assert graph_count == 0
    assert not (vault / "Memories" / "LongTerm").exists()


def test_chat_auto_memory_records_low_value_wiki_skip_without_raw_content(
    client: TestClient,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    enable_automation(client, chat_diary=True, wiki_organize=True)

    chat_payload, events = stream_chat_with_payload(client, "hello")
    assert_successful_chat_events(events)
    assert "agent_action" not in event_names(events)
    action_payloads = wait_for_agent_actions(
        client,
        chat_payload["agent_run_id"],
        action_type="wiki.answer_summary.skip",
    )
    skip_action = next(payload for payload in action_payloads if payload["action_type"] == "wiki.answer_summary.skip")

    assert skip_action["status"] == "skipped"
    assert skip_action["decision"] == "notify"
    assert skip_action["metadata"]["skipped_reason"] == "low_value_chat"
    assert skip_action["summary"]
    assert "hello" not in skip_action["summary"].casefold()


def test_chat_auto_memory_records_disabled_automation_skip_without_vault_write(client: TestClient) -> None:
    chat_payload, events = stream_chat_with_payload(client, "最近主要忙着整理首次使用体验")

    assert_successful_chat_events(events)
    assert "agent_action" not in event_names(events)
    action_payloads = wait_for_agent_actions(
        client,
        chat_payload["agent_run_id"],
        action_type="chat.auto_memory.skip",
    )
    skip_action = next(payload for payload in action_payloads if payload["action_type"] == "chat.auto_memory.skip")
    assert skip_action["status"] == "skipped"
    assert skip_action["decision"] == "notify"
    assert skip_action["target_paths"] == []
    assert skip_action["reversible"] is False
    assert skip_action["metadata"]["skipped_reason"] == "automation_disabled"
    assert "首次使用体验" not in skip_action["summary"]


def test_chat_auto_memory_skips_without_vault_and_does_not_break_sse(client: TestClient) -> None:
    events = stream_chat(client, "plain chat without configured vault")

    assert_successful_chat_events(events)
    assert "vault_not_configured" not in json.dumps(events)


def test_empty_memory_chat_stream_still_answers_naturally(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    disable_negotiation(client)

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
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    disable_negotiation(client)
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
