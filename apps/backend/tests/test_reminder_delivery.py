from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.reminder_delivery import (
    ReminderDeliveryService,
    ReminderDeliveryValidationError,
)
from app.api.services import adapters
from app.services.tasks import TaskService, TaskStore
from app.storage.database import Database, MigrationRunner
from tests.conftest import auth_headers


def _create_reminder(db_path: Path, *, reminder_id: str = "reminder-delivery-1") -> str:
    store = TaskStore(db_path)
    try:
        result = TaskService(store).create(
            title="Review graph evidence",
            remind_at="2026-08-08T12:00:00Z",
            reminder_id=reminder_id,
        )
        assert result.reminder is not None
        return result.reminder.id
    finally:
        store.close()


def test_delivery_ledger_dedupes_automatic_and_allows_new_manual_attempts(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    MigrationRunner(Database(db_path)).apply()
    reminder_id = _create_reminder(db_path)
    service = ReminderDeliveryService(db_path)
    try:
        first, duplicate = service.reserve(
            reminder_id,
            "2026-08-08T12:00:00Z",
            idempotency_key="a" * 64,
        )
        assert duplicate is False
        replay, duplicate = service.reserve(
            reminder_id,
            "2026-08-08T12:00:00Z",
            idempotency_key="b" * 64,
        )
        assert duplicate is True
        assert replay.attempt_id == first.attempt_id

        manual_one, duplicate = service.reserve(
            reminder_id,
            "2026-08-08T12:00:00Z",
            idempotency_key="c" * 64,
            dispatch_kind="manual",
        )
        assert duplicate is False
        manual_two, duplicate = service.reserve(
            reminder_id,
            "2026-08-08T12:00:00Z",
            idempotency_key="d" * 64,
            dispatch_kind="manual",
        )
        assert duplicate is False
        assert manual_two.attempt_id != manual_one.attempt_id

        with pytest.raises(ReminderDeliveryValidationError, match="payload conflict"):
            service.reserve(
                reminder_id,
                "2026-08-09T12:00:00Z",
                idempotency_key="c" * 64,
                dispatch_kind="manual",
            )
    finally:
        service.close()


def test_delivery_ledger_records_display_attempt_and_unknown_crash_window(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    MigrationRunner(Database(db_path)).apply()
    reminder_id = _create_reminder(db_path)
    service = ReminderDeliveryService(db_path)
    try:
        shown, _ = service.reserve(
            reminder_id,
            "2026-08-08T12:00:00Z",
            idempotency_key="a" * 64,
        )
        invoked = service.mark_display_invoked(shown.attempt_id, result_code="shown")
        assert invoked.status == "display_invoked"
        assert invoked.display_invoked_at is not None

        pending, _ = service.reserve(
            reminder_id,
            "2026-08-08T12:00:00Z",
            idempotency_key="b" * 64,
            dispatch_kind="manual",
        )
        assert service.recover_reserved(reason="injected_crash") == 1
        recovered = service.get(pending.attempt_id)
        assert recovered.status == "unknown_after_crash"
        assert recovered.display_invoked_at is None
    finally:
        service.close()


def _assert_delivery_api_requires_durable_reservation_before_display_receipt(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/tasks",
        headers=auth_headers(),
        json={
            "title": "Review graph evidence",
            "remind_at": "2026-08-08T12:00:00Z",
        },
    )
    assert created.status_code == 200
    reminder_id = created.json()["reminder_id"]
    payload = {
        "reminder_id": reminder_id,
        "trigger_at": "2026-08-08T12:00:00Z",
        "dispatch_kind": "automatic",
    }

    missing_key = client.post(
        "/api/tasks/reminder-delivery/reservations",
        headers=auth_headers(),
        json=payload,
    )
    assert missing_key.status_code == 422

    reserved = client.post(
        "/api/tasks/reminder-delivery/reservations",
        headers={**auth_headers(), "Idempotency-Key": "a" * 64},
        json=payload,
    )
    assert reserved.status_code == 200
    assert reserved.json()["status"] == "reserved"
    assert reserved.json()["duplicate"] is False

    duplicate = client.post(
        "/api/tasks/reminder-delivery/reservations",
        headers={**auth_headers(), "Idempotency-Key": "b" * 64},
        json=payload,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["attempt_id"] == reserved.json()["attempt_id"]
    assert duplicate.json()["duplicate"] is True

    displayed = client.post(
        f"/api/tasks/reminder-delivery/attempts/{reserved.json()['attempt_id']}/display",
        headers=auth_headers(),
        json={"result_code": "shown"},
    )
    assert displayed.status_code == 200
    assert displayed.json()["status"] == "display_invoked"
    assert displayed.json()["display_invoked_at"] is not None


def test_delivery_api_requires_durable_reservation_before_display_receipt(
    client_factory,
) -> None:
    with client_factory() as client:
        _assert_delivery_api_requires_durable_reservation_before_display_receipt(client)


def _action_rows(client: TestClient, action_type: str) -> list[sqlite3.Row]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM agent_actions WHERE action_type = ? ORDER BY created_at",
            (action_type,),
        ).fetchall()


def _create_api_reminder(client: TestClient) -> str:
    response = client.post(
        "/api/tasks",
        headers=auth_headers(),
        json={"title": "Lifecycle reminder", "remind_at": "2099-01-01T00:00:00Z", "timezone": "UTC"},
    )
    assert response.status_code == 200
    return str(response.json()["reminder_id"])


def test_delivery_reserve_recovers_effect_after_adapter_interrupt(
    client_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = adapters._reminder_delivery_reserve_adapter
    calls = 0

    def interrupted_factory(request):
        inner = original_factory(request)

        async def execute(proposal, policy, claim):
            nonlocal calls
            await inner(proposal, policy, claim)
            calls += 1
            raise RuntimeError("receipt interrupted after reservation commit")

        return execute

    monkeypatch.setattr(adapters, "_reminder_delivery_reserve_adapter", interrupted_factory)
    with client_factory() as client:
        reminder_id = _create_api_reminder(client)
        payload = {
            "reminder_id": reminder_id,
            "trigger_at": "2099-01-01T00:00:00Z",
            "dispatch_kind": "automatic",
        }
        headers = {**auth_headers(), "Idempotency-Key": "e" * 64}
        first = client.post(
            "/api/tasks/reminder-delivery/reservations",
            headers=headers,
            json=payload,
        )
        second = client.post(
            "/api/tasks/reminder-delivery/reservations",
            headers=headers,
            json=payload,
        )

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert first.json()["status"] == "reserved"
        assert calls == 1
        rows = _action_rows(client, "reminder.delivery.reserve")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert rows[0]["status"] == "completed"
        assert metadata["execution_receipt"]["status"] == "verified"
        assert metadata["execution_receipt"]["result"]["recovered_from_authoritative_state"] is True
        with sqlite3.connect(client.app.state.database.path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM reminder_delivery_attempts WHERE reminder_id = ?",
                (reminder_id,),
            ).fetchone()[0] == 1


def test_delivery_display_is_claimed_and_receipted(
    client_factory,
) -> None:
    with client_factory() as client:
        reminder_id = _create_api_reminder(client)
        reserved = client.post(
            "/api/tasks/reminder-delivery/reservations",
            headers={**auth_headers(), "Idempotency-Key": "f" * 64},
            json={
                "reminder_id": reminder_id,
                "trigger_at": "2099-01-01T00:00:00Z",
                "dispatch_kind": "automatic",
            },
        )
        assert reserved.status_code == 200
        attempt_id = reserved.json()["attempt_id"]
        displayed = client.post(
            f"/api/tasks/reminder-delivery/attempts/{attempt_id}/display",
            headers=auth_headers(),
            json={"result_code": "shown"},
        )
        replay = client.post(
            f"/api/tasks/reminder-delivery/attempts/{attempt_id}/display",
            headers=auth_headers(),
            json={"result_code": "shown"},
        )

        assert displayed.status_code == replay.status_code == 200
        assert displayed.json() == replay.json()
        assert displayed.json()["status"] == "display_invoked"
        rows = _action_rows(client, "reminder.delivery.display")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert rows[0]["status"] == "completed"
        assert metadata["execution_receipt"]["status"] == "verified"
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.row_factory = sqlite3.Row
            metric_rows = conn.execute(
                """
                SELECT event_type, subject_hash, dimensions_json
                FROM product_metric_events
                WHERE event_type IN ('reminder_triggered', 'reminder_display_attempted')
                ORDER BY event_type
                """
            ).fetchall()
        assert [row["event_type"] for row in metric_rows] == [
            "reminder_display_attempted",
            "reminder_triggered",
        ]
        assert len({row["subject_hash"] for row in metric_rows}) == 1
        assert all(attempt_id not in row["dimensions_json"] for row in metric_rows)


def test_delivery_recovery_returns_original_receipt_after_effect_interrupt(
    client_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = adapters._reminder_delivery_recover_adapter
    calls = 0

    def interrupted_factory(request):
        inner = original_factory(request)

        async def execute(proposal, policy, claim):
            nonlocal calls
            await inner(proposal, policy, claim)
            calls += 1
            raise RuntimeError("receipt interrupted after recovery commit")

        return execute

    monkeypatch.setattr(adapters, "_reminder_delivery_recover_adapter", interrupted_factory)
    with client_factory() as client:
        calls = 0
        reminder_id = _create_api_reminder(client)
        reserved = client.post(
            "/api/tasks/reminder-delivery/reservations",
            headers={**auth_headers(), "Idempotency-Key": "d" * 64},
            json={
                "reminder_id": reminder_id,
                "trigger_at": "2099-01-01T00:00:00Z",
                "dispatch_kind": "automatic",
            },
        )
        assert reserved.status_code == 200
        attempt_id = reserved.json()["attempt_id"]

        headers = {**auth_headers(), "X-Request-ID": "recovery-run-fixed"}
        first = client.post("/api/tasks/reminder-delivery/recover", headers=headers, json={})
        second = client.post("/api/tasks/reminder-delivery/recover", headers=headers, json={})

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert first.json()["unknown_attempts"] == 1
        assert calls == 1
        recovered = ReminderDeliveryService(client.app.state.database.path)
        try:
            assert recovered.get(attempt_id).status == "unknown_after_crash"
        finally:
            recovered.close()
        rows = [
            row
            for row in _action_rows(client, "reminder.delivery.recover")
            if row["source_agent_run_id"] == "recovery-run-fixed"
        ]
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert rows[0]["status"] == "completed"
        assert metadata["execution_receipt"]["status"] == "verified"
        assert metadata["execution_receipt"]["result"]["recovered_from_authoritative_state"] is True
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.row_factory = sqlite3.Row
            metric_rows = conn.execute(
                """
                SELECT event_type, subject_hash, dimensions_json
                FROM product_metric_events
                WHERE event_type IN ('reminder_triggered', 'reminder_display_unknown')
                ORDER BY event_type
                """
            ).fetchall()
        assert [row["event_type"] for row in metric_rows] == [
            "reminder_display_unknown",
            "reminder_triggered",
        ]
        assert len({row["subject_hash"] for row in metric_rows}) == 1
        assert all(attempt_id not in row["dimensions_json"] for row in metric_rows)

        impact = client.get("/api/metrics/local-impact", headers=auth_headers())
        assert impact.status_code == 200
        report = impact.json()
        assert report["metrics"]["reminder_display_attempt_rate"]["numerator"] == 0
        assert report["metrics"]["reminder_display_attempt_rate"]["denominator"] == 1
        assert report["failure_counts"]["reminder_display_unknown"] == 1
