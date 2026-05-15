from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENT_PET_SESSION_TOKEN", "audit-token")
    monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(tmp_path / "state.sqlite3"))

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    return TestClient(create_app())


def auth(request_id: str = "audit-request") -> dict[str, str]:
    return {
        "Authorization": "Bearer audit-token",
        "X-Request-ID": request_id,
    }


def audit_rows(client: TestClient) -> list[sqlite3.Row]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM audit_logs ORDER BY created_at, id"
        ).fetchall()


def test_chat_audit_logs_include_request_and_agent_run_ids(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    client.post(
        "/api/vaults/init",
        headers=auth("audit-chat-vault"),
        json={"path": str(vault), "create_if_missing": True},
    )
    accepted = client.post(
        "/api/chat",
        headers=auth("audit-chat"),
        json={"message": "plain audit chat"},
    )
    assert accepted.status_code == 200
    payload = accepted.json()

    with client.stream("GET", payload["stream_url"], headers=auth("audit-chat-stream")) as stream:
        body = "".join(stream.iter_text())

    assert "event: done" in body
    rows = audit_rows(client)
    actions = [row["action"] for row in rows]
    assert "chat.create" in actions
    assert "chat.complete" in actions
    chat_rows = [row for row in rows if row["action"].startswith("chat.")]
    assert any("request_id=audit-chat" in row["reason"] for row in chat_rows)
    assert any(f"agent_run_id={payload['agent_run_id']}" in row["reason"] for row in chat_rows)


def test_memory_and_denied_vault_paths_are_audited(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    bind = client.post(
        "/api/vaults/init",
        headers=auth("audit-vault-ok"),
        json={"path": str(vault), "create_if_missing": True},
    )
    assert bind.status_code == 200
    invalid_vault_path = tmp_path / "not-a-vault.md"
    invalid_vault_path.write_text("not a directory", encoding="utf-8")
    denied = client.post(
        "/api/vaults/init",
        headers=auth("audit-vault-denied"),
        json={"path": str(invalid_vault_path), "create_if_missing": True},
    )
    assert denied.status_code == 400

    created = client.post(
        "/api/memory/proposals",
        headers=auth("audit-memory-create"),
        json={
            "type": "fact",
            "content": "- audit fact",
            "target_path": "Inbox/Pending Memories.md",
        },
    )
    assert created.status_code == 200
    proposal_id = created.json()["proposal_id"]
    confirmed = client.post(
        f"/api/memory/proposals/{proposal_id}/confirm",
        headers=auth("audit-memory-confirm"),
    )
    assert confirmed.status_code == 200
    reject_source = client.post(
        "/api/memory/proposals",
        headers=auth("audit-memory-reject-source"),
        json={
            "type": "fact",
            "content": "- audit reject",
            "target_path": "Inbox/Pending Memories.md",
        },
    )
    rejected = client.post(
        f"/api/memory/proposals/{reject_source.json()['proposal_id']}/reject",
        headers=auth("audit-memory-reject"),
        json={"reason": "not needed"},
    )
    assert rejected.status_code == 200

    rows = audit_rows(client)
    action_results = {(row["action"], row["result"]) for row in rows}
    assert ("vault.bind", "success") in action_results
    assert ("vault.bind", "denied") in action_results
    assert ("memory.proposal.create", "success") in action_results
    assert ("memory.proposal.confirm", "success") in action_results
    assert ("memory.proposal.reject", "success") in action_results


def test_due_reminder_trigger_writes_scheduler_audit_log(client: TestClient) -> None:
    remind_at = (datetime.now(timezone.utc) + timedelta(milliseconds=120)).isoformat()
    created = client.post(
        "/api/tasks",
        headers=auth("audit-reminder-create"),
        json={
            "title": "audit reminder",
            "remind_at": remind_at,
            "timezone": "UTC",
        },
    )
    assert created.status_code == 200
    reminder_id = created.json()["reminder_id"]

    deadline = time.monotonic() + 2.0
    rows = []
    while time.monotonic() < deadline:
        rows = audit_rows(client)
        if any(row["action"] == "reminder.triggered" for row in rows):
            break
        time.sleep(0.05)

    trigger_rows = [row for row in rows if row["action"] == "reminder.triggered"]
    assert trigger_rows
    assert trigger_rows[-1]["actor"] == "scheduler"
    assert trigger_rows[-1]["result"] == "success"
    assert f"reminder_id={reminder_id}" in trigger_rows[-1]["reason"]


def test_diagnostics_export_exposes_redacted_runtime_audit_logs(client: TestClient, tmp_path: Path) -> None:
    secret_path = tmp_path / "Vault" / "Secrets.md"
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            """
            INSERT INTO audit_logs(id, actor, action, target_path, result, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "audit-runtime-redaction",
                "Authorization: Bearer audit-secret-token",
                "memory.proposal.confirm",
                str(secret_path),
                "success",
                "request_id=req-1;agent_run_id=run-1;token=sk-audit-secret-1234567890",
            ),
        )
        conn.commit()

    response = client.get("/api/diagnostics/export", headers=auth("audit-diagnostics"))

    assert response.status_code == 200
    body = response.text
    payload = response.json()
    assert payload["recent_audit_logs"][0]["id"] == "audit-runtime-redaction"
    assert payload["recent_audit_logs"][0]["action"] == "memory.proposal.confirm"
    assert payload["recent_audit_logs"][0]["target_path_present"] is True
    assert "audit-secret-token" not in body
    assert "sk-audit-secret" not in body
    assert str(secret_path) not in body
