from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.api import HabitLoopCandidateResponse, HabitLoopTriggerResponse
from app.models.common import new_id
from app.models.config import ProactiveTriggerFrequency, normalize_proactive_trigger_frequency


@dataclass(frozen=True, slots=True)
class _FrequencyPolicy:
    daily_limit: int
    cooldown_minutes: int
    min_idle_minutes: int


@dataclass(frozen=True, slots=True)
class _Candidate:
    content_type: str
    title: str
    message: str
    suggested_prompt: str
    sources: tuple[str, ...]


FREQUENCY_POLICIES: dict[ProactiveTriggerFrequency, _FrequencyPolicy] = {
    "off": _FrequencyPolicy(daily_limit=0, cooldown_minutes=0, min_idle_minutes=0),
    "low": _FrequencyPolicy(daily_limit=1, cooldown_minutes=8 * 60, min_idle_minutes=3 * 60),
    "normal": _FrequencyPolicy(daily_limit=2, cooldown_minutes=4 * 60, min_idle_minutes=90),
    "high": _FrequencyPolicy(daily_limit=3, cooldown_minutes=2 * 60, min_idle_minutes=45),
}
QUIET_START = time(hour=22)
QUIET_END = time(hour=8)
TERMINAL_TASK_STATUSES = {"done", "completed", "cancelled", "canceled", "rejected", "archived"}
TRIGGER_ACTION_TYPE = "habit.proactive_trigger"
SECRET_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bAuthorization:\s*Bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghu|github_pat|xox[baprs]|AKIA)[A-Za-z0-9_\-]{8,}\b", re.IGNORECASE),
    re.compile(r"(?i)\b(?:password|passwd|pwd|secret|token|api[_ -]?key)\s*[:=]\s*\S+"),
)


class HabitLoopTriggerService:
    def __init__(self, conn: sqlite3.Connection, *, now_provider=None) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def trigger(self, *, timezone_name: str = "UTC", record_delivery: bool = True) -> HabitLoopTriggerResponse:
        now_utc = _as_utc(self.now_provider())
        timezone_info = _timezone(timezone_name)
        local_now = now_utc.astimezone(timezone_info)
        frequency = self._frequency()
        policy = FREQUENCY_POLICIES[frequency]
        if frequency == "off":
            return self._blocked("frequency_off", frequency, policy)

        if _is_quiet_time(local_now):
            next_eligible = _next_quiet_end(local_now).astimezone(timezone.utc)
            return self._blocked("quiet_hours", frequency, policy, next_eligible_at=_iso_utc(next_eligible))

        last_chat_at = self._latest_user_message_at()
        if last_chat_at is not None:
            idle_until = last_chat_at + timedelta(minutes=policy.min_idle_minutes)
            if idle_until > now_utc:
                return self._blocked("recent_chat_cooldown", frequency, policy, next_eligible_at=_iso_utc(idle_until))

        day_start, day_end = _local_day_window_utc(local_now)
        current_daily_count = self._delivered_count(day_start, day_end)
        if current_daily_count >= policy.daily_limit:
            next_eligible = day_end.astimezone(timezone.utc)
            return self._blocked(
                "daily_limit_reached",
                frequency,
                policy,
                daily_count=current_daily_count,
                next_eligible_at=_iso_utc(next_eligible),
            )

        last_trigger_at = self._last_trigger_at()
        if last_trigger_at is not None:
            cooldown_until = last_trigger_at + timedelta(minutes=policy.cooldown_minutes)
            if cooldown_until > now_utc:
                return self._blocked(
                    "cooldown_active",
                    frequency,
                    policy,
                    daily_count=current_daily_count,
                    next_eligible_at=_iso_utc(cooldown_until),
                )

        candidate = self._candidate(now_utc)
        if candidate is None:
            return self._blocked("no_value_candidate", frequency, policy, daily_count=current_daily_count)

        response_candidate = HabitLoopCandidateResponse(
            trigger_id=new_id(),
            content_type=candidate.content_type,
            title=candidate.title,
            message=candidate.message,
            suggested_prompt=candidate.suggested_prompt,
            source_count=len(candidate.sources),
            sources=list(candidate.sources),
        )
        action_id = self._record_delivery(response_candidate, frequency, now_utc) if record_delivery else None
        return HabitLoopTriggerResponse(
            should_trigger=True,
            reason="triggered",
            frequency=frequency,
            daily_limit=policy.daily_limit,
            daily_count=current_daily_count + (1 if action_id else 0),
            cooldown_minutes=policy.cooldown_minutes,
            next_eligible_at=_iso_utc(now_utc + timedelta(minutes=policy.cooldown_minutes)),
            candidate=response_candidate,
            action_id=action_id,
        )

    def _blocked(
        self,
        reason: str,
        frequency: ProactiveTriggerFrequency,
        policy: _FrequencyPolicy,
        *,
        daily_count: int | None = None,
        next_eligible_at: str | None = None,
    ) -> HabitLoopTriggerResponse:
        return HabitLoopTriggerResponse(
            should_trigger=False,
            reason=reason,
            frequency=frequency,
            daily_limit=policy.daily_limit,
            daily_count=self._current_daily_count() if daily_count is None else daily_count,
            cooldown_minutes=policy.cooldown_minutes,
            next_eligible_at=next_eligible_at,
        )

    def _frequency(self) -> ProactiveTriggerFrequency:
        row = self.conn.execute(
            "SELECT value FROM app_state WHERE key = 'proactive_trigger_frequency'",
        ).fetchone()
        if row is None:
            return normalize_proactive_trigger_frequency(None)
        try:
            value = json.loads(str(row["value"]))
        except (TypeError, ValueError):
            value = str(row["value"])
        return normalize_proactive_trigger_frequency(value)

    def _current_daily_count(self) -> int:
        now_utc = _as_utc(self.now_provider())
        start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self._delivered_count(start, end)

    def _delivered_count(self, start_utc: datetime, end_utc: datetime) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM agent_actions
            WHERE action_type = ?
              AND status = 'completed'
              AND created_at >= ?
              AND created_at < ?
            """,
            (TRIGGER_ACTION_TYPE, _iso_utc(start_utc), _iso_utc(end_utc)),
        ).fetchone()
        return int(row["count"] or 0)

    def _latest_user_message_at(self) -> datetime | None:
        row = self.conn.execute(
            "SELECT MAX(created_at) AS latest FROM messages WHERE role = 'user'",
        ).fetchone()
        return _parse_datetime(row["latest"]) if row and row["latest"] else None

    def _last_trigger_at(self) -> datetime | None:
        row = self.conn.execute(
            """
            SELECT MAX(created_at) AS latest
            FROM agent_actions
            WHERE action_type = ? AND status = 'completed'
            """,
            (TRIGGER_ACTION_TYPE,),
        ).fetchone()
        return _parse_datetime(row["latest"]) if row and row["latest"] else None

    def _candidate(self, now_utc: datetime) -> _Candidate | None:
        return (
            self._task_candidate(now_utc)
            or self._diary_candidate()
            or self._memory_candidate()
            or self._wiki_candidate()
        )

    def _task_candidate(self, now_utc: datetime) -> _Candidate | None:
        rows = self.conn.execute(
            """
            SELECT id, title, description, due_at_utc, status, updated_at
            FROM tasks
            WHERE status NOT IN (?, ?, ?, ?, ?, ?)
            ORDER BY
                CASE WHEN due_at_utc IS NULL THEN 1 ELSE 0 END,
                due_at_utc ASC,
                updated_at DESC
            LIMIT 1
            """,
            tuple(TERMINAL_TASK_STATUSES),
        ).fetchall()
        if not rows:
            return None
        row = rows[0]
        title = _safe_text(row["title"], fallback="这个待办", limit=80)
        due_at = _parse_datetime(row["due_at_utc"]) if row["due_at_utc"] else None
        if due_at and due_at <= now_utc:
            return _Candidate(
                content_type="task_due",
                title="有个待办到时间了",
                message=f"{title} 已经到时间。现在只接一个下一步也可以。",
                suggested_prompt=f"帮我继续处理这个任务：{title}",
                sources=(f"tasks:{row['id']}",),
            )
        return _Candidate(
            content_type="task_followup",
            title="要不要接一下未完待办",
            message=f"还留着：{title}。如果现在有两分钟，我可以陪你拆一个很小的下一步。",
            suggested_prompt=f"帮我把这个待办拆成下一步：{title}",
            sources=(f"tasks:{row['id']}",),
        )

    def _diary_candidate(self) -> _Candidate | None:
        row = self.conn.execute(
            """
            SELECT id, memory_date, markdown_path, updated_at
            FROM daily_chat_memory_entries
            ORDER BY updated_at DESC, rowid DESC
            LIMIT 1
            """,
        ).fetchone()
        if row is None:
            return None
        memory_date = _safe_text(row["memory_date"], fallback="最近一天", limit=24)
        return _Candidate(
            content_type="daily_reflection",
            title="要不要轻轻回看一下",
            message=f"我已经把 {memory_date} 的聊天整理进日记。可以花一分钟看看今天有什么值得继续。",
            suggested_prompt="帮我回看最近的聊天日记，找一个值得继续的小动作。",
            sources=(f"daily_chat_memory_entries:{row['id']}",),
        )

    def _memory_candidate(self) -> _Candidate | None:
        row = self.conn.execute(
            """
            SELECT id, category, subject, object, updated_at
            FROM memory_graph_facts
            WHERE status IN ('active', 'candidate')
            ORDER BY updated_at DESC, rowid DESC
            LIMIT 1
            """,
        ).fetchone()
        if row is None:
            return None
        subject = _safe_text(row["subject"], fallback="一条记忆", limit=60)
        object_text = _safe_text(row["object"], fallback="新的线索", limit=80)
        return _Candidate(
            content_type="memory_checkin",
            title="我记住了一点线索",
            message=f"关于 {subject}，我这里有一条线索：{object_text}。要不要把它接到今天的安排里？",
            suggested_prompt=f"结合这条记忆帮我想一个今天能做的小动作：{object_text}",
            sources=(f"memory_graph_facts:{row['id']}",),
        )

    def _wiki_candidate(self) -> _Candidate | None:
        row = self.conn.execute(
            """
            SELECT id, title, summary, target_paths_json, updated_at
            FROM agent_actions
            WHERE action_type LIKE 'wiki.%' AND status = 'completed'
            ORDER BY COALESCE(completed_at, updated_at, created_at) DESC, rowid DESC
            LIMIT 1
            """,
        ).fetchone()
        if row is None:
            return None
        title = _safe_text(row["title"], fallback="最近整理的知识页", limit=80)
        target_paths = _json_string_list(row["target_paths_json"])
        source = f"agent_actions:{row['id']}"
        if target_paths:
            source = f"vault:{target_paths[0]}"
        return _Candidate(
            content_type="knowledge_return",
            title="有一条资料线索可以接上",
            message=f"{title} 已经整理过。现在可以顺手问一句，把它变成可用的下一步。",
            suggested_prompt="帮我从最近整理的资料里找一个今天能继续的点。",
            sources=(source,),
        )

    def _record_delivery(
        self,
        candidate: HabitLoopCandidateResponse,
        frequency: ProactiveTriggerFrequency,
        now_utc: datetime,
    ) -> str:
        now = _iso_utc(now_utc)
        metadata = {
            "content_type": candidate.content_type,
            "frequency": frequency,
            "suggested_prompt": candidate.suggested_prompt,
            "sources": candidate.sources,
        }
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO agent_actions (
                    id, source_agent_run_id, source_conversation_id, source_message_id,
                    action_type, risk_tier, decision, status, title, summary,
                    target_paths_json, before_snapshot_json, after_snapshot_json,
                    metadata_json, reversible, error, created_at, updated_at, completed_at,
                    negotiation_rounds, total_tokens, total_latency_ms
                )
                VALUES (?, NULL, NULL, NULL, ?, 'low', 'notify', 'completed', ?, ?, '[]', '{}', '{}', ?, 0, NULL, ?, ?, ?, 0, 0, 0)
                """,
                (
                    candidate.trigger_id,
                    TRIGGER_ACTION_TYPE,
                    candidate.title,
                    candidate.message,
                    json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                    now,
                    now,
                    now,
                ),
            )
        return candidate.trigger_id


def _timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name.strip() or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _is_quiet_time(local_now: datetime) -> bool:
    current = local_now.time()
    return current >= QUIET_START or current < QUIET_END


def _next_quiet_end(local_now: datetime) -> datetime:
    end_today = local_now.replace(hour=QUIET_END.hour, minute=0, second=0, microsecond=0)
    if local_now.time() < QUIET_END:
        return end_today
    return end_today + timedelta(days=1)


def _local_day_window_utc(local_now: datetime) -> tuple[datetime, datetime]:
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(f"{text[:-1]}+00:00")
        else:
            parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _as_utc(parsed)


def _iso_utc(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _safe_text(value: object, *, fallback: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return fallback
    if any(pattern.search(text) for pattern in SECRET_TEXT_PATTERNS):
        return fallback
    return text[:limit].rstrip() or fallback


def _json_string_list(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]
