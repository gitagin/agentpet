from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone as dt_timezone
from pathlib import Path
import re
from collections.abc import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.common import new_id
from app.models.enums import ReminderStatus, TaskStatus
from app.scheduler import ReminderScheduler
from app.utils.time import utc_now_iso


class TaskServiceError(Exception):
    pass


class TaskNotFoundError(TaskServiceError):
    pass


class ReminderNotFoundError(TaskServiceError):
    pass


class TimezoneParseError(TaskServiceError):
    pass


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    description: str
    due_at_utc: str | None
    status: TaskStatus
    source_text: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Reminder:
    id: str
    task_id: str
    remind_at_utc: str
    time_parse_timezone: str
    status: ReminderStatus
    scheduler_job_id: str | None
    error: str | None
    triggered_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TaskCreateResult:
    task: Task
    reminder: Reminder | None
    metadata: dict[str, str]


@dataclass(frozen=True)
class NaturalReminderParseResult:
    status: str
    remind_at: str | None
    timezone: str | None
    source: str = ""
    error: str = ""


DEFAULT_NATURAL_TIMEZONE = "Asia/Shanghai"
DEFAULT_NATURAL_TIMEZONE_LABEL = "北京时间"
TIMEZONE_ALIASES = {
    "Asia/Beijing": DEFAULT_NATURAL_TIMEZONE,
    "Beijing": DEFAULT_NATURAL_TIMEZONE,
    "北京": DEFAULT_NATURAL_TIMEZONE,
    "北京时间": DEFAULT_NATURAL_TIMEZONE,
    "China/Beijing": DEFAULT_NATURAL_TIMEZONE,
}
CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
NUMBER_TOKEN = r"\d{1,2}|[零〇一二两三四五六七八九十]{1,4}"
RELATIVE_TIME_RE = re.compile(rf"(?P<num>{NUMBER_TOKEN})\s*(?P<unit>秒钟|秒|分钟|小时)\s*后")
COLON_TIME_RE = re.compile(
    rf"(?P<period>凌晨|早上|上午|中午|下午|晚上|夜里)?\s*(?P<hour>{NUMBER_TOKEN})\s*[:：]\s*(?P<minute>\d{{1,2}})"
)
POINT_TIME_RE = re.compile(
    rf"(?P<period>凌晨|早上|上午|中午|下午|晚上|夜里)?\s*(?P<hour>{NUMBER_TOKEN})\s*(?:点|时)(?P<half>半)?(?:(?P<minute>{NUMBER_TOKEN})\s*分?)?"
)


def parse_datetime_to_utc(value: str | None, timezone: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, normalize_timezone_name(timezone) if timezone else timezone
    tz_name = normalize_timezone_name(timezone, "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise TimezoneParseError(f"未知时区：{tz_name}") from exc
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z"), tz_name


def parse_natural_reminder(
    source_text: str | None,
    timezone: str | None,
    now_utc: datetime | None = None,
) -> NaturalReminderParseResult:
    text = (source_text or "").strip()
    if not text:
        return NaturalReminderParseResult(status="not_found", remind_at=None, timezone=timezone)

    tz_name = normalize_timezone_name(timezone, DEFAULT_NATURAL_TIMEZONE)
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        return NaturalReminderParseResult(
            status="failed",
            remind_at=None,
            timezone=tz_name,
            error=f"未知时区：{tz_name}",
        )

    now = (now_utc or datetime.now(dt_timezone.utc)).astimezone(tz)
    relative = _parse_relative_time(text, now)
    if relative is not None:
        return NaturalReminderParseResult(
            status="parsed",
            remind_at=relative.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
            timezone=tz_name,
            source="relative",
        )

    absolute = _parse_absolute_time(text, now, tz)
    if absolute is not None:
        return NaturalReminderParseResult(
            status="parsed",
            remind_at=absolute.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z"),
            timezone=tz_name,
            source="absolute",
        )

    return NaturalReminderParseResult(status="not_found", remind_at=None, timezone=tz_name)


def normalize_timezone_name(timezone: str | None, default: str | None = None) -> str | None:
    raw = (timezone or default or "").strip()
    if not raw:
        return default
    return TIMEZONE_ALIASES.get(raw, raw)


def display_timezone_name(timezone: str | None) -> str:
    normalized = normalize_timezone_name(timezone)
    if normalized == DEFAULT_NATURAL_TIMEZONE:
        return DEFAULT_NATURAL_TIMEZONE_LABEL
    return normalized or ""


def parse_iso_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt_timezone.utc)


def _parse_relative_time(text: str, now: datetime) -> datetime | None:
    match = RELATIVE_TIME_RE.search(text)
    if match is None:
        return None
    amount = _parse_number(match.group("num"))
    if amount is None or amount <= 0:
        return None
    if match.group("unit") in {"秒", "秒钟"}:
        return now + timedelta(seconds=amount)
    if match.group("unit") == "分钟":
        return now + timedelta(minutes=amount)
    return now + timedelta(hours=amount)


def _parse_absolute_time(text: str, now: datetime, tz: ZoneInfo) -> datetime | None:
    match = POINT_TIME_RE.search(text) or COLON_TIME_RE.search(text)
    if match is None:
        return None

    hour = _parse_number(match.group("hour"))
    if hour is None:
        return None

    minute = 0
    if "half" in match.groupdict() and match.group("half"):
        minute = 30
    elif match.groupdict().get("minute"):
        parsed_minute = _parse_number(str(match.group("minute")))
        if parsed_minute is None:
            return None
        minute = parsed_minute

    if hour > 23 or minute > 59:
        return None

    period = match.groupdict().get("period") or ""
    hour = _apply_period(hour, period)
    if hour > 23:
        return None

    target_date = now.date() + timedelta(days=_date_offset(text))
    target = datetime.combine(target_date, time(hour=hour, minute=minute), tzinfo=tz)
    if _date_offset(text) == 0 and target <= now:
        target += timedelta(days=1)
    return target


def _date_offset(text: str) -> int:
    if "后天" in text:
        return 2
    if "明天" in text:
        return 1
    return 0


def _apply_period(hour: int, period: str) -> int:
    if period in {"下午", "晚上", "夜里"} and 1 <= hour < 12:
        return hour + 12
    if period == "中午" and 1 <= hour < 11:
        return hour + 12
    if period in {"凌晨", "早上", "上午"} and hour == 12:
        return 0
    return hour


def _parse_number(value: str) -> int | None:
    text = value.strip()
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = CHINESE_DIGITS.get(left, 1) if left else 1
        ones = CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    result = 0
    for char in text:
        digit = CHINESE_DIGITS.get(char)
        if digit is None:
            return None
        result = result * 10 + digit
    return result


class TaskStore:
    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def insert_task_with_reminder(self, task: Task, reminder: Reminder | None) -> TaskCreateResult:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO tasks (
                    id, title, description, due_at_utc, status, source_text, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.title,
                    task.description,
                    task.due_at_utc,
                    task.status.value,
                    task.source_text,
                    task.created_at,
                    task.updated_at,
                ),
            )
            if reminder is not None:
                self.conn.execute(
                    """
                    INSERT INTO reminders (
                        id, task_id, remind_at_utc, time_parse_timezone, status,
                        scheduler_job_id, error, triggered_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reminder.id,
                        reminder.task_id,
                        reminder.remind_at_utc,
                        reminder.time_parse_timezone,
                        reminder.status.value,
                        reminder.scheduler_job_id,
                        reminder.error,
                        reminder.triggered_at,
                        reminder.created_at,
                        reminder.updated_at,
                    ),
                )
        return TaskCreateResult(task=task, reminder=reminder, metadata={})

    def get_task(self, task_id: str) -> Task:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        return self._map_task(row)

    def get_reminder(self, reminder_id: str) -> Reminder:
        row = self.conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if row is None:
            raise ReminderNotFoundError(reminder_id)
        return self._map_reminder(row)

    def update_reminder_schedule(
        self,
        reminder_id: str,
        *,
        status: ReminderStatus,
        scheduler_job_id: str | None,
        error: str | None,
    ) -> Reminder:
        self.conn.execute(
            """
            UPDATE reminders
            SET status = ?, scheduler_job_id = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (status.value, scheduler_job_id, error, utc_now_iso(), reminder_id),
        )
        self.conn.commit()
        return self.get_reminder(reminder_id)

    def mark_reminder_triggered(self, reminder_id: str) -> Reminder:
        now = utc_now_iso()
        self.conn.execute(
            """
            UPDATE reminders
            SET status = ?, scheduler_job_id = NULL, error = NULL, triggered_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (ReminderStatus.TRIGGERED.value, now, now, reminder_id),
        )
        self.conn.commit()
        return self.get_reminder(reminder_id)

    def mark_reminder_failed(self, reminder_id: str, error: str) -> Reminder:
        self.conn.execute(
            """
            UPDATE reminders
            SET status = ?, scheduler_job_id = NULL, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (ReminderStatus.FAILED.value, error, utc_now_iso(), reminder_id),
        )
        self.conn.commit()
        return self.get_reminder(reminder_id)

    def list_unscheduled(self) -> list[Reminder]:
        rows = self.conn.execute(
            "SELECT * FROM reminders WHERE status = ? ORDER BY remind_at_utc",
            (ReminderStatus.UNSCHEDULED.value,),
        ).fetchall()
        return [self._map_reminder(row) for row in rows]

    def list_recoverable_reminders(self) -> list[Reminder]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM reminders
            WHERE status IN (?, ?)
            ORDER BY remind_at_utc
            """,
            (ReminderStatus.SCHEDULED.value, ReminderStatus.UNSCHEDULED.value),
        ).fetchall()
        return [self._map_reminder(row) for row in rows]

    def list_tasks(self) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks ORDER BY COALESCE(due_at_utc, created_at), created_at"
        ).fetchall()
        return [self._map_task(row) for row in rows]

    def get_current_task(self) -> Task | None:
        row = self.conn.execute(
            """
            SELECT *
            FROM tasks
            ORDER BY CASE WHEN status = ? THEN 0 ELSE 1 END,
                     CASE WHEN status = ? THEN COALESCE(due_at_utc, created_at) END,
                     CASE WHEN status = ? THEN created_at END,
                     CASE WHEN status != ? THEN updated_at END DESC,
                     CASE WHEN status != ? THEN created_at END DESC,
                     CASE WHEN status != ? THEN id END DESC
            LIMIT 1
            """,
            (
                TaskStatus.PENDING.value,
                TaskStatus.PENDING.value,
                TaskStatus.PENDING.value,
                TaskStatus.PENDING.value,
                TaskStatus.PENDING.value,
                TaskStatus.PENDING.value,
            ),
        ).fetchone()
        return self._map_task(row) if row is not None else None

    def list_tasks_between(self, start_utc: str, end_utc: str) -> list[Task]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM tasks
            WHERE due_at_utc >= ? AND due_at_utc < ?
            ORDER BY due_at_utc, created_at
            """,
            (start_utc, end_utc),
        ).fetchall()
        return [self._map_task(row) for row in rows]

    def get_reminder_for_task(self, task_id: str) -> Reminder | None:
        row = self.conn.execute(
            "SELECT * FROM reminders WHERE task_id = ? ORDER BY remind_at_utc LIMIT 1",
            (task_id,),
        ).fetchone()
        return self._map_reminder(row) if row is not None else None

    def list_reminders_for_task(self, task_id: str) -> list[Reminder]:
        rows = self.conn.execute(
            "SELECT * FROM reminders WHERE task_id = ? ORDER BY remind_at_utc",
            (task_id,),
        ).fetchall()
        return [self._map_reminder(row) for row in rows]

    def cancel_reminders_for_task(self, task_id: str) -> list[Reminder]:
        with self.conn:
            self.conn.execute(
                """
                UPDATE reminders
                SET status = ?, scheduler_job_id = NULL, error = NULL, updated_at = ?
                WHERE task_id = ? AND status NOT IN (?, ?)
                """,
                (
                    ReminderStatus.CANCELLED.value,
                    utc_now_iso(),
                    task_id,
                    ReminderStatus.TRIGGERED.value,
                    ReminderStatus.CANCELLED.value,
                ),
            )
        return self.list_reminders_for_task(task_id)

    def complete_task(self, task_id: str) -> Task:
        self.conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.DONE.value, utc_now_iso(), task_id),
        )
        self.conn.commit()
        return self.get_task(task_id)

    def cancel_task(self, task_id: str) -> Task:
        self.conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.CANCELLED.value, utc_now_iso(), task_id),
        )
        self.conn.commit()
        return self.get_task(task_id)

    def _map_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            due_at_utc=row["due_at_utc"],
            status=TaskStatus(row["status"]),
            source_text=row["source_text"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _map_reminder(self, row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            task_id=row["task_id"],
            remind_at_utc=row["remind_at_utc"],
            time_parse_timezone=row["time_parse_timezone"],
            status=ReminderStatus(row["status"]),
            scheduler_job_id=row["scheduler_job_id"],
            error=row["error"],
            triggered_at=row["triggered_at"] if "triggered_at" in row.keys() else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class TaskService:
    def __init__(
        self,
        store: TaskStore,
        scheduler: ReminderScheduler | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.scheduler = scheduler
        self.now_provider = now_provider or (lambda: datetime.now(dt_timezone.utc))

    def close(self) -> None:
        self.store.close()

    def create(
        self,
        *,
        title: str,
        description: str = "",
        due_at: str | None = None,
        remind_at: str | None = None,
        timezone: str | None = None,
        source_text: str | None = None,
    ) -> TaskCreateResult:
        due_at_utc, due_timezone = parse_datetime_to_utc(due_at, timezone)
        remind_at_utc, remind_timezone = parse_datetime_to_utc(remind_at, timezone)
        metadata: dict[str, str] = {
            "time_parse_status": "explicit" if remind_at_utc is not None else "not_found",
        }
        if remind_at_utc is None and source_text:
            parsed_reminder = parse_natural_reminder(source_text, timezone, self.now_provider())
            metadata["time_parse_status"] = parsed_reminder.status
            if parsed_reminder.source:
                metadata["time_parse_source"] = parsed_reminder.source
            if parsed_reminder.error:
                metadata["time_parse_error"] = parsed_reminder.error
            if parsed_reminder.remind_at is not None:
                remind_at_utc = parsed_reminder.remind_at
                remind_timezone = parsed_reminder.timezone

        if remind_timezone:
            metadata["timezone"] = remind_timezone
        elif due_timezone:
            metadata["timezone"] = due_timezone
        if metadata.get("timezone"):
            metadata["timezone_label"] = display_timezone_name(metadata["timezone"])

        now = utc_now_iso()
        task = Task(
            id=new_id(),
            title=title,
            description=description,
            due_at_utc=due_at_utc,
            status=TaskStatus.PENDING,
            source_text=source_text,
            created_at=now,
            updated_at=now,
        )
        reminder = None
        if remind_at_utc is not None:
            reminder = Reminder(
                id=new_id(),
                task_id=task.id,
                remind_at_utc=remind_at_utc,
                time_parse_timezone=remind_timezone or due_timezone or "UTC",
                status=ReminderStatus.UNSCHEDULED,
                scheduler_job_id=None,
                error=None,
                triggered_at=None,
                created_at=now,
                updated_at=now,
        )
        result = self.store.insert_task_with_reminder(task, reminder)
        if result.reminder is None:
            return TaskCreateResult(task=result.task, reminder=None, metadata=metadata)
        scheduled = self._schedule_or_mark_unscheduled(result.reminder, title)
        return TaskCreateResult(task=result.task, reminder=scheduled, metadata=metadata)

    def retry_unscheduled(self) -> list[Reminder]:
        reminders = []
        for reminder in self.store.list_unscheduled():
            task = self.store.get_task(reminder.task_id)
            if task.status != TaskStatus.PENDING:
                reminders.extend(self.store.cancel_reminders_for_task(task.id))
                continue
            reminders.append(self._schedule_or_mark_unscheduled(reminder, task.title))
        return reminders

    def recover_reminders(self) -> list[Reminder]:
        reminders = []
        for reminder in self.store.list_recoverable_reminders():
            task = self.store.get_task(reminder.task_id)
            if task.status != TaskStatus.PENDING:
                reminders.extend(self.store.cancel_reminders_for_task(task.id))
                continue
            reminders.append(self._schedule_or_mark_unscheduled(reminder, task.title))
        return reminders

    def mark_reminder_triggered(self, reminder_id: str) -> Reminder:
        return self.store.mark_reminder_triggered(reminder_id)

    def mark_reminder_failed(self, reminder_id: str, error: str) -> Reminder:
        return self.store.mark_reminder_failed(reminder_id, error)

    def complete(self, task_id: str) -> Task:
        task = self.store.complete_task(task_id)
        self._cancel_reminders_for_task(task_id)
        return task

    def cancel(self, task_id: str) -> Task:
        task = self.store.cancel_task(task_id)
        self._cancel_reminders_for_task(task_id)
        return task

    def current(self) -> Task | None:
        return self.store.get_current_task()

    def steps_for_task(self, task_id: str) -> list[dict[str, int | str]]:
        task = self.store.get_task(task_id)
        return [
            {
                "index": 1,
                "tool_name": "task",
                "status": task.status.value,
                "duration_ms": 0,
            }
        ]

    def logs_for_task(self, task_id: str) -> list[dict[str, str]]:
        task = self.store.get_task(task_id)
        return [
            {"timestamp": task.created_at, "content": f"任务已创建：{task.title}"},
            {"timestamp": task.updated_at, "content": f"当前状态：{task.status.value}"},
        ]

    def approve(self, task_id: str) -> Task:
        return self.store.get_task(task_id)

    def reject(self, task_id: str) -> Task:
        return self.cancel(task_id)

    def list(self) -> list[Task]:
        return self.store.list_tasks()

    def list_today(self, timezone: str | None = None) -> list[Task]:
        tz_name = normalize_timezone_name(timezone, "UTC") or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError as exc:
            raise TimezoneParseError(f"未知时区：{tz_name}") from exc
        today = datetime.now(tz).date()
        start = datetime.combine(today, time.min, tzinfo=tz)
        end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
        start_utc = start.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
        end_utc = end.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
        return self.store.list_tasks_between(start_utc, end_utc)

    def reminder_for_task(self, task_id: str) -> Reminder | None:
        return self.store.get_reminder_for_task(task_id)

    def _schedule_or_mark_unscheduled(self, reminder: Reminder, title: str) -> Reminder:
        if self.scheduler is None:
            return reminder
        try:
            job_id = self.scheduler.schedule(reminder.id, parse_iso_utc(reminder.remind_at_utc), title)
        except Exception as exc:
            return self.store.update_reminder_schedule(
                reminder.id,
                status=ReminderStatus.UNSCHEDULED,
                scheduler_job_id=None,
                error=_localized_scheduler_error(exc),
            )
        return self.store.update_reminder_schedule(
            reminder.id,
            status=ReminderStatus.SCHEDULED,
            scheduler_job_id=job_id,
            error=None,
        )

    def _cancel_reminders_for_task(self, task_id: str) -> list[Reminder]:
        reminders = self.store.list_reminders_for_task(task_id)
        if self.scheduler is not None:
            for reminder in reminders:
                if reminder.scheduler_job_id is not None and reminder.status == ReminderStatus.SCHEDULED:
                    try:
                        self.scheduler.cancel(reminder.scheduler_job_id)
                    except Exception:
                        pass
        return self.store.cancel_reminders_for_task(task_id)


def _localized_scheduler_error(exc: Exception) -> str:
    message = str(exc)
    if message in {"scheduler unavailable", "提醒调度器不可用"}:
        return "提醒调度器不可用"
    if message and not message.isascii():
        return message
    return "提醒调度失败"
