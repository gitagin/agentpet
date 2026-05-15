from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock, Timer
from collections.abc import Callable
from typing import Protocol


class ReminderSchedulerError(Exception):
    pass


class ReminderScheduler(Protocol):
    def schedule(self, reminder_id: str, trigger_at_utc: datetime, title: str) -> str:
        ...

    def cancel(self, job_id: str) -> None:
        ...


@dataclass
class ScheduledJob:
    reminder_id: str
    trigger_at_utc: datetime
    title: str
    job_id: str
    timer: Timer | None = None


class InMemoryReminderScheduler:
    def __init__(
        self,
        *,
        fail_schedule: bool = False,
        on_trigger: Callable[[str], None] | None = None,
        on_error: Callable[[str, Exception], None] | None = None,
    ):
        self.fail_schedule = fail_schedule
        self.on_trigger = on_trigger
        self.on_error = on_error
        self.jobs: dict[str, ScheduledJob] = {}
        self._lock = Lock()

    def schedule(self, reminder_id: str, trigger_at_utc: datetime, title: str) -> str:
        if self.fail_schedule:
            raise ReminderSchedulerError("提醒调度器不可用")
        job_id = f"reminder:{reminder_id}"
        self.cancel(job_id)
        normalized_trigger = _as_utc(trigger_at_utc)
        job = ScheduledJob(
            reminder_id=reminder_id,
            trigger_at_utc=normalized_trigger,
            title=title,
            job_id=job_id,
        )
        if self.on_trigger is not None:
            delay = max(0.0, (normalized_trigger - datetime.now(timezone.utc)).total_seconds())
            if delay == 0.0:
                delay = 0.05
            job.timer = Timer(delay, self._fire, args=(job_id,))
            job.timer.daemon = True
        with self._lock:
            self.jobs[job_id] = job
        if job.timer is not None:
            job.timer.start()
        return job_id

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self.jobs.pop(job_id, None)
        if job is not None and job.timer is not None:
            job.timer.cancel()

    def run_due(self, now_utc: datetime | None = None) -> list[str]:
        now = _as_utc(now_utc or datetime.now(timezone.utc))
        with self._lock:
            due_job_ids = [
                job_id
                for job_id, job in self.jobs.items()
                if job.trigger_at_utc <= now
            ]
        for job_id in due_job_ids:
            self._fire(job_id)
        return due_job_ids

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self.jobs.values())
            self.jobs.clear()
        for job in jobs:
            if job.timer is not None:
                job.timer.cancel()

    def _fire(self, job_id: str) -> None:
        with self._lock:
            job = self.jobs.pop(job_id, None)
        if job is None or self.on_trigger is None:
            return
        try:
            self.on_trigger(job.reminder_id)
        except Exception as exc:
            if self.on_error is not None:
                try:
                    self.on_error(job.reminder_id, exc)
                except Exception:
                    pass


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
