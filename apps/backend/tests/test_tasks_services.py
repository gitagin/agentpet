from datetime import datetime, timedelta, timezone

from datetime import datetime, timedelta, timezone

from apps.backend.tests._schema import migrate_db, migrated_connection
from app.models.enums import ReminderStatus, TaskStatus
from app.scheduler import ReminderSchedulerError
from app.services.tasks import TaskService, TaskStore


class RecordingReminderScheduler:
    def __init__(self, *, fail_schedule: bool = False):
        self.fail_schedule = fail_schedule
        self.jobs = {}
        self.cancelled_job_ids = []

    def schedule(self, reminder_id: str, trigger_at_utc: datetime, title: str) -> str:
        if self.fail_schedule:
            raise ReminderSchedulerError("提醒调度器不可用")
        job_id = f"reminder:{reminder_id}"
        self.jobs[job_id] = {
            "reminder_id": reminder_id,
            "trigger_at_utc": trigger_at_utc,
            "title": title,
        }
        return job_id

    def cancel(self, job_id: str) -> None:
        self.cancelled_job_ids.append(job_id)
        self.jobs.pop(job_id, None)

    def trigger(self, job_id: str, service: TaskService) -> None:
        job = self.jobs.pop(job_id)
        service.mark_reminder_triggered(job["reminder_id"])


def fixed_now():
    return datetime(2026, 5, 1, 1, 0, tzinfo=timezone.utc)


def build_service(scheduler=None):
    return TaskService(TaskStore(migrated_connection()), scheduler=scheduler, now_provider=fixed_now)


def test_create_task_converts_local_times_to_utc_and_schedules_reminder():
    scheduler = RecordingReminderScheduler()
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
    assert scheduler.jobs[result.reminder.scheduler_job_id]["title"] == "Review plan"
    assert result.metadata["time_parse_status"] == "explicit"


def test_create_task_parses_chinese_absolute_reminder_time():
    scheduler = RecordingReminderScheduler()
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
    service = build_service(RecordingReminderScheduler())

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
    service = build_service(RecordingReminderScheduler())

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
    service = build_service(RecordingReminderScheduler())

    result = service.create(title="整理知识库", source_text="提醒我整理知识库", timezone="Asia/Shanghai")

    assert result.task.status == TaskStatus.PENDING
    assert result.reminder is None
    assert result.metadata["time_parse_status"] == "not_found"


def test_list_today_defaults_to_local_timezone_day(monkeypatch):
    import app.services.tasks as tasks_module

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc)
            return current.astimezone(tz) if tz is not None else current.replace(tzinfo=None)

    monkeypatch.setattr(tasks_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(tasks_module, "DEFAULT_NATURAL_TIMEZONE", "Asia/Shanghai")
    service = TaskService(TaskStore(migrated_connection()))
    created = service.create(
        title="Local midnight task",
        due_at="2026-01-02T00:30:00",
        timezone="Asia/Shanghai",
    )

    assert [task.id for task in service.list_today()] == [created.task.id]
    assert service.list_today("UTC") == []


def test_scheduler_failure_keeps_task_and_marks_reminder_unscheduled():
    scheduler = RecordingReminderScheduler(fail_schedule=True)
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
    failing = RecordingReminderScheduler(fail_schedule=True)
    store = TaskStore(migrated_connection())
    service = TaskService(store, scheduler=failing)
    created = service.create(title="Stand up", remind_at="2026-04-27T09:00:00", timezone="UTC")
    assert created.reminder is not None
    assert created.reminder.status == ReminderStatus.UNSCHEDULED

    working = RecordingReminderScheduler()
    retrying_service = TaskService(store, scheduler=working)
    reminders = retrying_service.retry_unscheduled()

    assert len(reminders) == 1
    assert reminders[0].status == ReminderStatus.SCHEDULED
    assert reminders[0].scheduler_job_id == f"reminder:{created.reminder.id}"


def test_recover_reminders_reschedules_existing_scheduled_rows(tmp_path):
    db_path = migrate_db(tmp_path / "tasks.sqlite3")
    first_store = TaskStore(db_path)
    first_service = TaskService(first_store, scheduler=RecordingReminderScheduler())
    created = first_service.create(
        title="Future reminder",
        remind_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        timezone="UTC",
    )
    assert created.reminder is not None
    first_store.close()

    scheduler = RecordingReminderScheduler()
    recovering = TaskService(TaskStore(db_path), scheduler=scheduler)
    reminders = recovering.recover_reminders()

    assert len(reminders) == 1
    assert reminders[0].status == ReminderStatus.SCHEDULED
    assert reminders[0].scheduler_job_id in scheduler.jobs


def test_scheduler_trigger_marks_reminder_triggered(tmp_path):
    db_path = migrate_db(tmp_path / "tasks.sqlite3")
    scheduler = RecordingReminderScheduler()
    service = TaskService(TaskStore(db_path), scheduler=scheduler)
    created = service.create(
        title="Soon",
        remind_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        timezone="UTC",
    )
    assert created.reminder is not None
    assert created.reminder.status == ReminderStatus.SCHEDULED
    assert created.reminder.scheduler_job_id is not None

    scheduler.trigger(created.reminder.scheduler_job_id, service)
    reminder = service.reminder_for_task(created.task.id)

    assert reminder is not None
    assert reminder.status == ReminderStatus.TRIGGERED
    assert reminder.scheduler_job_id is None
    assert reminder.triggered_at


def test_retry_unscheduled_cancels_reminders_for_completed_tasks():
    store = TaskStore(migrated_connection())
    service = TaskService(store)
    created = service.create(title="Already done", remind_at="2026-04-27T09:00:00", timezone="UTC")
    assert created.reminder is not None
    assert created.reminder.status == ReminderStatus.UNSCHEDULED
    store.complete_task(created.task.id)

    scheduler = RecordingReminderScheduler()
    retrying_service = TaskService(store, scheduler=scheduler)
    reminders = retrying_service.retry_unscheduled()

    assert len(reminders) == 1
    assert reminders[0].status == ReminderStatus.CANCELLED
    assert reminders[0].scheduler_job_id is None
    assert scheduler.jobs == {}


def test_complete_task_cancels_scheduled_reminder():
    scheduler = RecordingReminderScheduler()
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
    scheduler = RecordingReminderScheduler()
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


def test_current_prefers_pending_task():
    service = build_service()
    service.create(title="Completed first")
    completed = service.current()
    assert completed is not None
    service.complete(completed.id)
    pending = service.create(title="Pending second")

    current = service.current()

    assert current is not None
    assert current.id == pending.task.id


def test_current_returns_most_recent_task_when_no_pending_tasks():
    service = build_service()
    older = service.create(title="Older task")
    service.complete(older.task.id)
    newer = service.create(title="Newer task")
    service.cancel(newer.task.id)
    service.store.conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", ("2026-05-01T01:00:00Z", older.task.id))
    service.store.conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", ("2026-05-01T01:01:00Z", newer.task.id))
    service.store.conn.commit()

    current = service.current()

    assert current is not None
    assert current.id == newer.task.id


def test_current_returns_none_when_no_tasks():
    service = build_service()

    assert service.current() is None


def test_steps_and_logs_for_task_are_synthesized():
    service = build_service()
    created = service.create(title="Write workspace task")

    steps = service.steps_for_task(created.task.id)
    logs = service.logs_for_task(created.task.id)

    assert steps == [{"index": 1, "tool_name": "task", "status": "pending", "duration_ms": 0}]
    assert logs[0]["timestamp"] == created.task.created_at
    assert "任务已创建" in logs[0]["content"]
    assert logs[1]["timestamp"] == created.task.updated_at
    assert "pending" in logs[1]["content"]


def test_approve_keeps_task_status():
    service = build_service()
    created = service.create(title="Approve no-op")

    approved = service.approve(created.task.id)

    assert approved.id == created.task.id
    assert approved.status == TaskStatus.PENDING


def test_reject_cancels_task_and_reminder():
    scheduler = RecordingReminderScheduler()
    service = build_service(scheduler)
    created = service.create(title="Reject task", remind_at="2026-04-27T09:00:00", timezone="UTC")
    assert created.reminder is not None
    assert created.reminder.scheduler_job_id in scheduler.jobs

    rejected = service.reject(created.task.id)
    reminder = service.reminder_for_task(created.task.id)

    assert rejected.status == TaskStatus.CANCELLED
    assert reminder is not None
    assert reminder.status == ReminderStatus.CANCELLED
    assert scheduler.jobs == {}
