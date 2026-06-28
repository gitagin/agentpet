from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from apps.backend.tests._schema import migrate_db
from app.models.api import AutomationSettingsRequest
from app.services.habit_loop import HabitLoopTriggerService
from app.services.settings import SettingsStore


def test_habit_loop_trigger_records_task_candidate_and_frequency_cooldown(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "habit.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        SettingsStore(conn).set_automation_settings(
            AutomationSettingsRequest(
                proactive_trigger_frequency="normal",
                use_negotiation=False,
                max_rounds=2,
            )
        )
        conn.execute(
            """
            INSERT INTO tasks(id, title, description, due_at_utc, status, source_text, created_at, updated_at)
            VALUES (
                'habit-task-1', 'Review acceptance notes', '', NULL, 'pending', '',
                '2026-06-21T08:00:00Z', '2026-06-21T08:00:00Z'
            )
            """
        )
        conn.commit()

        now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        service = HabitLoopTriggerService(conn, now_provider=lambda: now)

        first = service.trigger(timezone_name="Asia/Shanghai")
        second = service.trigger(timezone_name="Asia/Shanghai")

        assert first.should_trigger is True
        assert first.reason == "triggered"
        assert first.frequency == "normal"
        assert first.daily_limit == 2
        assert first.cooldown_minutes == 240
        assert first.candidate is not None
        assert first.candidate.content_type == "task_followup"
        assert first.candidate.sources == ["tasks:habit-task-1"]
        assert first.action_id == first.candidate.trigger_id

        row = conn.execute("SELECT * FROM agent_actions WHERE id = ?", (first.action_id,)).fetchone()
        assert row["action_type"] == "habit.proactive_trigger"
        assert row["decision"] == "notify"
        assert row["risk_tier"] == "low"

        assert second.should_trigger is False
        assert second.reason == "cooldown_active"
    finally:
        conn.close()


def test_habit_loop_trigger_respects_quiet_hours(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "habit.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        SettingsStore(conn).set_automation_settings(
            AutomationSettingsRequest(
                proactive_trigger_frequency="high",
                use_negotiation=False,
                max_rounds=2,
            )
        )
        service = HabitLoopTriggerService(
            conn,
            now_provider=lambda: datetime(2026, 6, 21, 15, 0, tzinfo=timezone.utc),
        )

        response = service.trigger(timezone_name="Asia/Shanghai")

        assert response.should_trigger is False
        assert response.reason == "quiet_hours"
        assert response.daily_limit == 3
        assert response.next_eligible_at == "2026-06-22T00:00:00Z"
    finally:
        conn.close()

