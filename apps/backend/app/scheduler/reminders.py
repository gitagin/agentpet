from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import SchedulerAlreadyRunningError, SchedulerNotRunningError
from apscheduler.util import undefined


class ReminderSchedulerError(Exception):
    pass


@runtime_checkable
class ReminderSchedulerProtocol(Protocol):
    def start(self, *, paused: bool = False) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def shutdown(self) -> None: ...
    def schedule(self, reminder_id: str, trigger_at_utc: datetime, title: str) -> str: ...
    def cancel(self, job_id: str) -> None: ...
    def clear(self) -> None: ...


ReminderScheduler = ReminderSchedulerProtocol


class APSchedulerReminderScheduler:
    def __init__(self, db_path: str | Path, *, fail_schedule: bool = False):
        self.db_path = Path(db_path)
        self.fail_schedule = fail_schedule
        self.scheduler = AsyncIOScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(
                    url=f"sqlite:///{self.db_path.resolve().as_posix()}",
                    engine_options={"connect_args": {"timeout": 30}},
                )
            },
            timezone=timezone.utc,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": None,
            },
        )

    def start(self, *, paused: bool = False) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.scheduler.running:
            return
        try:
            self.scheduler.start(paused=paused)
        except SchedulerAlreadyRunningError:
            pass

    def pause(self) -> None:
        if not self.scheduler.running:
            return
        self.scheduler.pause()

    def resume(self) -> None:
        if not self.scheduler.running:
            return
        self.scheduler.resume()

    def schedule(self, reminder_id: str, trigger_at_utc: datetime, title: str) -> str:
        if self.fail_schedule:
            raise ReminderSchedulerError("提醒调度器不可用")
        self.start(paused=False)
        job_id = f"reminder:{reminder_id}"
        run_at = _as_utc(trigger_at_utc)
        if run_at <= datetime.now(timezone.utc):
            run_at = datetime.now(timezone.utc) + timedelta(milliseconds=50)
        self.scheduler.add_job(
            fire_reminder_job,
            trigger="date",
            run_date=run_at,
            id=job_id,
            args=[reminder_id, str(self.db_path)],
            replace_existing=True,
            name=title,
            misfire_grace_time=undefined,
        )
        return job_id

    def cancel(self, job_id: str) -> None:
        if not self.scheduler.running:
            self.start(paused=True)
        job = self.scheduler.get_job(job_id)
        if job is not None:
            job.remove()

    def clear(self) -> None:
        if not self.scheduler.running:
            self.start(paused=True)
        self.scheduler.remove_all_jobs()

    def get_job(self, job_id: str) -> Any:
        if not self.scheduler.running:
            self.start(paused=True)
        return self.scheduler.get_job(job_id)

    def shutdown(self) -> None:
        if not self.scheduler.running:
            return
        try:
            self.scheduler.shutdown(wait=True)
        except SchedulerNotRunningError:
            pass


def fire_reminder_job(reminder_id: str, db_path: str) -> None:
    from app.services.tasks import TaskService, TaskStore

    store = TaskStore(db_path)
    try:
        TaskService(store).mark_reminder_triggered(reminder_id)
        _record_scheduler_audit(db_path, "reminder.triggered", "success", reminder_id)
    except Exception as exc:
        try:
            TaskService(store).mark_reminder_failed(reminder_id, str(exc) or "提醒触发失败")
        finally:
            _record_scheduler_audit(
                db_path,
                "reminder.failed",
                "failed",
                reminder_id,
                code=exc.__class__.__name__,
            )
    finally:
        store.close()


def _record_scheduler_audit(
    db_path: str | Path,
    action: str,
    result: str,
    reminder_id: str,
    *,
    code: str | None = None,
) -> None:
    from app.services.audit import AuditLogService

    audit = AuditLogService(db_path)
    try:
        reason = f"reminder_id={reminder_id}"
        if code:
            reason = f"{reason};code={code}"
        audit.record(actor="scheduler", action=action, result=result, reason=reason)
    finally:
        audit.close()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
