import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models.enums import ReminderStatus
from app.scheduler import APSchedulerReminderScheduler
from app.services.tasks import TaskService, TaskStore
from app.storage.database import Database, MigrationRunner


def prepare_db(db_path: Path) -> None:
    MigrationRunner(Database(db_path)).apply()
    TaskStore(db_path).close()


def reminder_status(db_path: Path, reminder_id: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()


async def wait_for_reminder_status(db_path: Path, reminder_id: str, status: ReminderStatus) -> sqlite3.Row:
    deadline = asyncio.get_running_loop().time() + 3.0
    row = reminder_status(db_path, reminder_id)
    while asyncio.get_running_loop().time() < deadline:
        row = reminder_status(db_path, reminder_id)
        if row["status"] == status.value:
            return row
        await asyncio.sleep(0.05)
    return row


@pytest.mark.asyncio
async def test_reminder_job_persists_across_scheduler_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    prepare_db(db_path)
    first_scheduler = APSchedulerReminderScheduler(db_path)
    first_scheduler.start(paused=True)
    store = TaskStore(db_path)
    try:
        created = TaskService(store, scheduler=first_scheduler).create(
            title="Persistent reminder",
            remind_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            timezone="UTC",
        )
        assert created.reminder is not None
        job_id = f"reminder:{created.reminder.id}"
        assert first_scheduler.get_job(job_id) is not None
    finally:
        store.close()
        first_scheduler.shutdown()

    second_scheduler = APSchedulerReminderScheduler(db_path)
    try:
        second_scheduler.start(paused=True)
        assert second_scheduler.get_job(job_id) is not None
    finally:
        second_scheduler.shutdown()


@pytest.mark.asyncio
async def test_due_reminder_job_marks_reminder_triggered(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    prepare_db(db_path)
    scheduler = APSchedulerReminderScheduler(db_path)
    scheduler.start(paused=True)
    store = TaskStore(db_path)
    try:
        created = TaskService(store, scheduler=scheduler).create(
            title="Soon",
            remind_at=(datetime.now(timezone.utc) + timedelta(milliseconds=120)).isoformat(),
            timezone="UTC",
        )
        assert created.reminder is not None
        scheduler.resume()
        row = await wait_for_reminder_status(db_path, created.reminder.id, ReminderStatus.TRIGGERED)
    finally:
        store.close()
        scheduler.shutdown()

    assert row["status"] == ReminderStatus.TRIGGERED.value
    assert row["scheduler_job_id"] is None
    assert row["triggered_at"]

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        audit = conn.execute(
            "SELECT * FROM audit_logs WHERE action = ? ORDER BY created_at DESC LIMIT 1",
            ("reminder.triggered",),
        ).fetchone()
    assert audit is not None
    assert audit["actor"] == "scheduler"
    assert audit["result"] == "success"
    assert f"reminder_id={created.reminder.id}" in audit["reason"]


@pytest.mark.asyncio
async def test_cancelled_reminder_job_is_not_restored_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    prepare_db(db_path)
    scheduler = APSchedulerReminderScheduler(db_path)
    scheduler.start(paused=True)
    store = TaskStore(db_path)
    try:
        service = TaskService(store, scheduler=scheduler)
        created = service.create(
            title="Cancel me",
            remind_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            timezone="UTC",
        )
        assert created.reminder is not None
        job_id = f"reminder:{created.reminder.id}"
        assert scheduler.get_job(job_id) is not None
        service.cancel(created.task.id)
        assert scheduler.get_job(job_id) is None
    finally:
        store.close()
        scheduler.shutdown()

    restarted = APSchedulerReminderScheduler(db_path)
    try:
        restarted.start(paused=True)
        assert restarted.get_job(job_id) is None
    finally:
        restarted.shutdown()
