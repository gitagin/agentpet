import sqlite3
import time
from datetime import datetime, timedelta, timezone

from app.models.enums import ReminderStatus, TaskStatus
from app.scheduler import InMemoryReminderScheduler
from app.services.tasks import TaskService, TaskStore


def fixed_now():
    return datetime(2026, 5, 1, 1, 0, tzinfo=timezone.utc)


def build_service(scheduler=None):
    return TaskService(TaskStore(sqlite3.connect(":memory:")), scheduler=scheduler, now_provider=fixed_now)


def test_create_task_converts_local_times_to_utc_and_schedules_reminder():
    scheduler = InMemoryReminderScheduler()
    service = build_service(scheduler)

    result = service.create(
        title="Review plan",
        due_at="2026-04-27T15:00:00",
        remind_at="2026-04-27T14:30:00",
        timezone="Asia/Shanghai",
        source_text="tomorrow afternoon",
    )

    assert result.task.status == TaskStatus.PENDING
    assert result.task.due_at_utc == "2026-04-27T07:00:00Z"
    assert result.reminder is not None
    assert result.reminder.remind_at_utc == "2026-04-27T06:30:00Z"
    assert result.reminder.time_parse_timezone == "Asia/Shanghai"
    assert result.reminder.status == ReminderStatus.SCHEDULED
    assert result.reminder.scheduler_job_id == f"reminder:{result.reminder.id}"
    assert result.reminder.scheduler_job_id in scheduler.jobs
    assert result.metadata["time_parse_status"] == "explicit"


def test_create_task_parses_chinese_absolute_reminder_time():
    scheduler = InMemoryReminderScheduler()
    service = build_service(scheduler)

    result = service.create(
        title="测试桌面记忆助手",
        source_text="提醒我明天下午三点测试桌面记忆助手",
        timezone="Asia/Shanghai",
    )

    assert result.reminder is not None
    assert result.reminder.remind_at_utc == "2026-05-02T07:00:00Z"
    assert result.reminder.time_parse_timezone == "Asia/Shanghai"
    assert result.reminder.status == ReminderStatus.SCHEDULED
    assert result.metadata["time_parse_status"] == "parsed"
    assert result.metadata["time_parse_source"] == "absolute"
    assert result.metadata["timezone_label"] == "北京时间"


def test_beijing_timezone_aliases_are_stored_as_canonical_china_timezone():
    service = build_service(InMemoryReminderScheduler())

    for timezone_name in ["北京时间", "北京", "Asia/Beijing", "Beijing"]:
        result = service.create(
            title=f"alias {timezone_name}",
            remind_at="2026-04-27T14:30:00",
            timezone=timezone_name,
        )

        assert result.reminder is not None
        assert result.reminder.remind_at_utc == "2026-04-27T06:30:00Z"
        assert result.reminder.time_parse_timezone == "Asia/Shanghai"
        assert result.metadata["timezone"] == "Asia/Shanghai"
        assert result.metadata["timezone_label"] == "北京时间"


def test_create_task_parses_relative_seconds_minutes_and_hours():
    service = build_service(InMemoryReminderScheduler())

    seconds = service.create(title="写笔记", source_text="5秒钟后提醒我写笔记", timezone="Asia/Shanghai")
    minutes = service.create(title="喝水", source_text="30分钟后提醒我喝水", timezone="Asia/Shanghai")
    hours = service.create(title="休息", source_text="2小时后提醒我休息", timezone="Asia/Shanghai")

    assert seconds.reminder is not None
    assert seconds.reminder.remind_at_utc == "2026-05-01T01:00:05Z"
    assert minutes.reminder is not None
    assert minutes.reminder.remind_at_utc == "2026-05-01T01:30:00Z"
    assert hours.reminder is not None
    assert hours.reminder.remind_at_utc == "2026-05-01T03:00:00Z"
    assert seconds.metadata["time_parse_source"] == "relative"


def test_create_task_without_time_expression_remains_plain_task():
    service = build_service(InMemoryReminderScheduler())

    result = service.create(title="整理知识库", source_text="提醒我整理知识库", timezone="Asia/Shanghai")

    assert result.task.status == TaskStatus.PENDING
    assert result.reminder is None
    assert result.metadata["time_parse_status"] == "not_found"


def test_scheduler_failure_keeps_task_and_marks_reminder_unscheduled():
    scheduler = InMemoryReminderScheduler(fail_schedule=True)
    service = build_service(scheduler)

    result = service.create(
        title="Take a break",
        remind_at="2026-04-27T09:00:00",
        timezone="America/New_York",
    )

    assert result.task.status == TaskStatus.PENDING
    assert result.reminder is not None
    assert result.reminder.status == ReminderStatus.UNSCHEDULED
    assert result.reminder.scheduler_job_id is None
    assert "提醒调度器不可用" in result.reminder.error


def test_retry_unscheduled_schedules_existing_reminders():
    failing = InMemoryReminderScheduler(fail_schedule=True)
    store = TaskStore(sqlite3.connect(":memory:"))
    service = TaskService(store, scheduler=failing)
    created = service.create(title="Stand up", remind_at="2026-04-27T09:00:00", timezone="UTC")
    assert created.reminder is not None
    assert created.reminder.status == ReminderStatus.UNSCHEDULED

    working = InMemoryReminderScheduler()
    retrying_service = TaskService(store, scheduler=working)
    reminders = retrying_service.retry_unscheduled()

    assert len(reminders) == 1
    assert reminders[0].status == ReminderStatus.SCHEDULED
    assert reminders[0].scheduler_job_id == f"reminder:{created.reminder.id}"


def test_recover_reminders_reschedules_existing_scheduled_rows(tmp_path):
    db_path = tmp_path / "tasks.sqlite3"
    first_store = TaskStore(db_path)
    first_service = TaskService(first_store, scheduler=InMemoryReminderScheduler())
    created = first_service.create(
        title="Future reminder",
        remind_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        timezone="UTC",
    )
    assert created.reminder is not None
    first_store.close()

    scheduler = InMemoryReminderScheduler()
    recovering = TaskService(TaskStore(db_path), scheduler=scheduler)
    reminders = recovering.recover_reminders()

    assert len(reminders) == 1
    assert reminders[0].status == ReminderStatus.SCHEDULED
    assert reminders[0].scheduler_job_id in scheduler.jobs


def test_scheduler_trigger_marks_reminder_triggered(tmp_path):
    db_path = tmp_path / "tasks.sqlite3"

    def mark_triggered(reminder_id: str) -> None:
        service = TaskService(TaskStore(db_path))
        try:
            service.mark_reminder_triggered(reminder_id)
        finally:
            service.close()

    scheduler = InMemoryReminderScheduler(on_trigger=mark_triggered)
    service = TaskService(TaskStore(db_path), scheduler=scheduler)
    created = service.create(
        title="Soon",
        remind_at=(datetime.now(timezone.utc) + timedelta(milliseconds=120)).isoformat(),
        timezone="UTC",
    )
    assert created.reminder is not None
    assert created.reminder.status == ReminderStatus.SCHEDULED

    time.sleep(0.35)
    reminder = service.reminder_for_task(created.task.id)

    assert reminder is not None
    assert reminder.status == ReminderStatus.TRIGGERED
    assert reminder.scheduler_job_id is None
    assert reminder.triggered_at


def test_retry_unscheduled_cancels_reminders_for_completed_tasks():
    store = TaskStore(sqlite3.connect(":memory:"))
    service = TaskService(store)
    created = service.create(title="Already done", remind_at="2026-04-27T09:00:00", timezone="UTC")
    assert created.reminder is not None
    assert created.reminder.status == ReminderStatus.UNSCHEDULED
    store.complete_task(created.task.id)

    scheduler = InMemoryReminderScheduler()
    retrying_service = TaskService(store, scheduler=scheduler)
    reminders = retrying_service.retry_unscheduled()

    assert len(reminders) == 1
    assert reminders[0].status == ReminderStatus.CANCELLED
    assert reminders[0].scheduler_job_id is None
    assert scheduler.jobs == {}


def test_complete_task_cancels_scheduled_reminder():
    scheduler = InMemoryReminderScheduler()
    service = build_service(scheduler)
    created = service.create(title="Submit report", remind_at="2026-04-27T09:00:00", timezone="UTC")
    assert created.reminder is not None
    assert created.reminder.scheduler_job_id in scheduler.jobs

    task = service.complete(created.task.id)
    reminder = service.reminder_for_task(created.task.id)

    assert task.status == TaskStatus.DONE
    assert reminder is not None
    assert reminder.status == ReminderStatus.CANCELLED
    assert reminder.scheduler_job_id is None
    assert scheduler.jobs == {}


def test_cancel_task_cancels_scheduled_reminder():
    scheduler = InMemoryReminderScheduler()
    service = build_service(scheduler)
    created = service.create(title="Call partner", remind_at="2026-04-27T09:00:00", timezone="UTC")
    assert created.reminder is not None
    assert created.reminder.scheduler_job_id in scheduler.jobs

    task = service.cancel(created.task.id)
    reminder = service.reminder_for_task(created.task.id)

    assert task.status == TaskStatus.CANCELLED
    assert reminder is not None
    assert reminder.status == ReminderStatus.CANCELLED
    assert reminder.scheduler_job_id is None
    assert scheduler.jobs == {}
