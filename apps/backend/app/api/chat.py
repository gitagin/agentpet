from collections.abc import AsyncIterator
import asyncio
from datetime import date as date_cls
from datetime import datetime, time, timedelta, timezone
import inspect
import logging
import re
import sqlite3
from threading import Lock as ThreadLock
from time import monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from ..agents.events import (
    AgentActionEvent,
    AgentContinuityProposalEvent,
    AgentDoneEvent,
    AgentErrorEvent,
    AgentReplyReadyEvent,
    AgentSseEventBase,
    AgentTokenEvent,
    public_agent_error,
)
from ..errors import AppError
from ..agents.events import sse_stream
from ..agents.state import AgentState
from ..agents.intent import route_intent
from ..models.api import ChatAcceptedResponse, ChatDailyHistoryMessage, ChatDailyHistoryResponse, ChatRequest
from ..models.answer_basis import normalize_answer_basis
from ..services.agent_actions import AutomationPolicy
from ..services.chat_pipeline import agent_action_event, archive_chat_memory, automation_settings
from ..services.memory_policy import evaluate_memory_content
from ..services.post_reply_memory_jobs import PostReplyMemoryJobRecord, PostReplyMemoryJobStore
from ..services.product_metrics import ProductMetricsService
from ..services.prompt_context_types import PromptRecentTurn
from ..models.common import new_id
from ..models.enums import AgentId, AgentIntent, AgentRunStatus, ConversationStatus, MessageRole, MessageStatus
from ..storage.database import Database
from ..utils.time import local_timezone_name, utc_now_iso
from ..agents.retrieval.compression import gate_evidence
from .wiring import (
    AppContext,
    add_chat_run,
    agent_runtime,
    audit_reason,
    chat_model_client,
    claim_chat_run,
    continuity_service,
    database,
    get_chat_run,
    pop_chat_run,
    record_audit,
    settings_store,
)

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)
LOCAL_PRIVACY_REDACTED_USER_MESSAGE = "[local privacy mode redacted sensitive user message]"
_RECENT_TURNS_FETCH_LIMIT = 12
_RECENT_TURNS_MAX_SELECTED = 4
_RECENT_TURN_INTERNAL_PATTERN = re.compile(
    r"source_text|source_excerpt|raw\s+evidence|agent_run_id|authorization|bearer\s+|"
    r"message_id|conversation_id|source_message_id|source_conversation_id|"
    r"raw_evidence|evidence_id|evidence:|source_message|source_conversation|"
    r"\btoken\b|tool_call|<tool_call|</tool_call>|memory_candidates|target_id|"
    r"vault\s+write\s+preview|markdown_preview",
    re.IGNORECASE,
)
_RECENT_TURN_WINDOWS_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)")
_RECENT_TURN_POSIX_PATH_PATTERN = re.compile(r"(?<!\w)/(?:Users|home|var|etc|tmp|mnt|opt|root)/", re.IGNORECASE)
_RECENT_TURN_STACK_TRACE_PATTERN = re.compile(
    r"Traceback \(most recent call last\)|\bFile \"[^\"]+\", line \d+",
    re.IGNORECASE,
)
# 每日聊天历史按本机时区解释（东八区机器解析结果与原来一致）。
_DEFAULT_DAILY_HISTORY_TIMEZONE = local_timezone_name()
_DAILY_HISTORY_DEFAULT_LIMIT = 160
# Streaming PARTIAL persistence throttle: flush after this many tokens or
# this many seconds since the last flush, whichever comes first. Terminal
# states (completed/failed/cancelled) always persist immediately.
_STREAM_PARTIAL_FLUSH_TOKEN_COUNT = 50
_STREAM_PARTIAL_FLUSH_INTERVAL_SECONDS = 0.2
# Keep room for the initial INSERT and one terminal UPDATE when the caller
# produces a slow 800-token response (the backlog's write-count bound).
_STREAM_MAX_PARTIAL_FLUSHES = 18
# Strong references to fire-and-forget post-reply tasks. asyncio only keeps
# a weak reference to tasks, so without this set a scheduled archive job can
# be garbage collected mid-flight and silently never complete.
_POST_REPLY_TASKS: set["asyncio.Task[None]"] = set()
# Durable post-reply work is deliberately bounded. A permanently failing
# local provider remains visible as a failed row for manual retry instead of
# creating an unbounded restart loop.
# 队列重试/租约/恢复上限收敛到 settings（env 可覆盖）。刻意用函数在每次
# 使用时读取：模块导入期求值会与 conftest 的 cache_clear 失配，测试也无法覆盖。
from ..config import get_settings as _get_settings

_POST_REPLY_RECOVERY_LIMIT = 100


def _post_reply_max_attempts() -> int:
    return max(1, _get_settings().tuning_post_reply_max_attempts)


def _post_reply_lease_seconds() -> int:
    return max(1, _get_settings().tuning_post_reply_lease_seconds)
_POST_REPLY_WORKER_ID = f"post-reply-worker-{new_id()}"


@router.post("", response_model=ChatAcceptedResponse)
async def create_chat(chat_request: ChatRequest, request: Request) -> ChatAcceptedResponse:
    conversation_id = chat_request.conversation_id or new_id()
    message_id = new_id()
    agent_run_id = new_id()
    local_privacy_reason = _local_privacy_sensitive_reason(request, chat_request.message)
    stored_user_message = _stored_user_message(chat_request.message, local_privacy_reason)
    _create_chat_records(request, conversation_id=conversation_id, message_id=message_id, agent_run_id=agent_run_id, user_message=stored_user_message)
    recent_turns = _load_recent_turns(request, conversation_id=conversation_id, current_message_id=message_id)
    record_audit(request, action="chat.create", result="success", reason=audit_reason(request, agent_run_id=agent_run_id, conversation_id=conversation_id))
    add_chat_run(
        request,
        AgentState(
            conversation_id=conversation_id,
            message_id=message_id,
            agent_run_id=agent_run_id,
            user_message=chat_request.message,
            recent_turns=list(recent_turns),
            local_privacy_mode=local_privacy_reason is not None,
            local_privacy_sensitive_reason=local_privacy_reason,
        ),
    )
    return ChatAcceptedResponse(conversation_id=conversation_id, message_id=message_id, agent_run_id=agent_run_id, stream_url=f"/api/chat/runs/{agent_run_id}/events")


@router.get("/daily-history", response_model=ChatDailyHistoryResponse)
async def get_daily_chat_history(
    request: Request,
    date: str | None = Query(default=None, min_length=10, max_length=10),
    timezone_name: str = Query(default=_DEFAULT_DAILY_HISTORY_TIMEZONE, alias="timezone", min_length=1, max_length=64),
    limit: int = Query(default=_DAILY_HISTORY_DEFAULT_LIMIT, ge=1, le=300),
) -> ChatDailyHistoryResponse:
    tz = _daily_history_timezone(timezone_name)
    target_date = _daily_history_date(date, tz)
    start_utc, end_utc = _daily_history_utc_window(target_date, tz)
    start_iso = _datetime_to_utc_iso(start_utc)
    end_iso = _datetime_to_utc_iso(end_utc)

    with database(request).session() as conn:
        rows = conn.execute(
            """
            SELECT
                messages.id,
                messages.conversation_id,
                messages.role,
                messages.content,
                messages.status,
                messages.answer_basis,
                messages.created_at,
                messages.updated_at,
                agent_runs.id AS agent_run_id
            FROM messages
            LEFT JOIN agent_runs ON agent_runs.assistant_message_id = messages.id
            WHERE messages.created_at >= ?
              AND messages.created_at < ?
              AND messages.role IN (?, ?)
              AND messages.status IN (?, ?, ?)
              AND TRIM(messages.content) != ''
            ORDER BY messages.created_at DESC, messages.id DESC
            LIMIT ?
            """,
            (
                start_iso,
                end_iso,
                MessageRole.USER.value,
                MessageRole.ASSISTANT.value,
                MessageStatus.COMPLETED.value,
                MessageStatus.FAILED.value,
                MessageStatus.CANCELLED.value,
                limit + 1,
            ),
        ).fetchall()
    limited_rows = list(reversed(rows[:limit]))
    latest_row = limited_rows[-1] if limited_rows else None
    return ChatDailyHistoryResponse(
        date=target_date.isoformat(),
        timezone=tz.key,
        conversation_id=str(latest_row["conversation_id"]) if latest_row is not None else None,
        messages=[
            ChatDailyHistoryMessage(
                id=str(row["id"]),
                conversation_id=str(row["conversation_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                status=str(row["status"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                agent_run_id=str(row["agent_run_id"]) if row["agent_run_id"] is not None else None,
                answer_basis=(
                    normalize_answer_basis(row["answer_basis"])
                    if row["role"] == "assistant" and row["status"] == "completed"
                    else "not_assessed"
                ),
            )
            for row in limited_rows
        ],
        has_more=len(rows) > limit,
    )


def _daily_history_timezone(timezone_name: str) -> ZoneInfo:
    normalized = (timezone_name or _DEFAULT_DAILY_HISTORY_TIMEZONE).strip() or _DEFAULT_DAILY_HISTORY_TIMEZONE
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise AppError(
            code="invalid_timezone",
            message=f"未知时区：{normalized}",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"timezone": normalized},
        ) from exc


def _daily_history_date(raw_date: str | None, tz: ZoneInfo) -> date_cls:
    if raw_date is None:
        return datetime.now(tz).date()
    try:
        return date_cls.fromisoformat(raw_date)
    except ValueError as exc:
        raise AppError(
            code="invalid_date",
            message="日期格式需要是 YYYY-MM-DD。",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"date": raw_date},
        ) from exc


def _daily_history_utc_window(target_date: date_cls, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=tz)
    end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _datetime_to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _local_privacy_sensitive_reason(request: Request, user_message: str) -> str | None:
    store = settings_store(request)
    try:
        automation = store.get_automation_settings()
    finally:
        store.close()
    if not automation.local_privacy_mode:
        return None
    decision = evaluate_memory_content(user_message)
    return decision.reason if not decision.allowed else None


def _stored_user_message(user_message: str, local_privacy_reason: str | None) -> str:
    if local_privacy_reason is None:
        return user_message
    return f"{LOCAL_PRIVACY_REDACTED_USER_MESSAGE}: {local_privacy_reason}"


def _load_recent_turns(
    request: Request,
    *,
    conversation_id: str,
    current_message_id: str,
) -> tuple[PromptRecentTurn, ...]:
    try:
        with database(request).session() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, created_at
                FROM messages
                WHERE conversation_id = ?
                  AND id != ?
                  AND role IN (?, ?)
                  AND status = ?
                  AND TRIM(content) != ''
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (
                    conversation_id,
                    current_message_id,
                    MessageRole.USER.value,
                    MessageRole.ASSISTANT.value,
                    MessageStatus.COMPLETED.value,
                    _RECENT_TURNS_FETCH_LIMIT,
                ),
            ).fetchall()
    except Exception:
        logger.warning("Recent turns loading failed; continuing without recent conversation context.", exc_info=True)
        return ()

    selected_newest: list[PromptRecentTurn] = []
    for row in rows:
        turn = _safe_recent_turn(row["role"], row["content"], row["created_at"])
        if turn is None:
            continue
        selected_newest.append(turn)
        if len(selected_newest) >= _RECENT_TURNS_MAX_SELECTED:
            break
    return tuple(reversed(selected_newest))


def _safe_recent_turn(role: str, content: str, created_at: str | None) -> PromptRecentTurn | None:
    role_value = str(role).casefold()
    if role_value not in {MessageRole.USER.value, MessageRole.ASSISTANT.value}:
        return None
    text = str(content or "").strip()
    if not text or _recent_turn_should_exclude(text):
        return None
    return PromptRecentTurn(role=role_value, content=text, created_at=created_at)


def _recent_turn_should_exclude(content: str) -> bool:
    if not evaluate_memory_content(content).allowed:
        return True
    return any(
        pattern.search(content)
        for pattern in (
            _RECENT_TURN_INTERNAL_PATTERN,
            _RECENT_TURN_WINDOWS_PATH_PATTERN,
            _RECENT_TURN_POSIX_PATH_PATTERN,
            _RECENT_TURN_STACK_TRACE_PATTERN,
        )
    )


@router.get("/runs/{agent_run_id}/events")
async def stream_chat(agent_run_id: str, request: Request) -> StreamingResponse:
    state = get_chat_run(request, agent_run_id)
    if state is None:
        raise AppError(code="agent_run_not_found", message="未找到智能体运行记录。", status_code=status.HTTP_404_NOT_FOUND, details={"agent_run_id": agent_run_id})
    return StreamingResponse(sse_stream(_persisting_stream(request, state)), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/runs/{agent_run_id}/stream")
async def stream_chat_alias(agent_run_id: str, request: Request) -> StreamingResponse:
    return await stream_chat(agent_run_id, request)


@router.get("/stream/{agent_run_id}")
async def stream_chat_legacy(agent_run_id: str, request: Request) -> StreamingResponse:
    return await stream_chat(agent_run_id, request)


def _create_chat_records(
    request: Request, *, conversation_id: str, message_id: str, agent_run_id: str, user_message: str
) -> None:
    now = utc_now_iso()
    with database(request).session() as conn:
        with conn:
            conn.execute(
                """INSERT INTO conversations (id, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at""",
                (conversation_id, user_message.strip()[:80], ConversationStatus.ACTIVE.value, now, now),
            )
            conn.execute(
                """INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (message_id, conversation_id, MessageRole.USER.value, user_message, MessageStatus.COMPLETED.value, now, now),
            )
            conn.execute(
                """INSERT INTO agent_runs (id, conversation_id, user_message_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (agent_run_id, conversation_id, message_id, AgentRunStatus.RUNNING.value, now, now),
            )


def recover_interrupted_chat_runs(database_instance: Database) -> int:
    """Close chat runs/messages left open when the previous process stopped.

    The in-memory run registry is intentionally not persisted. On startup,
    every persisted RUNNING run and assistant PARTIAL message therefore needs
    an explicit terminal state so the next client cannot observe a ghost
    stream forever.
    """
    now = utc_now_iso()
    recovered_runs = 0
    recovered_messages = 0
    with database_instance.session() as conn:
        running_runs = conn.execute(
            """
            SELECT id, conversation_id, assistant_message_id
            FROM agent_runs
            WHERE status = ?
            """,
            (AgentRunStatus.RUNNING.value,),
        ).fetchall()
        for row in running_runs:
            assistant_message_id = row["assistant_message_id"] or new_id()
            message_exists = conn.execute(
                "SELECT 1 FROM messages WHERE id = ?",
                (assistant_message_id,),
            ).fetchone()
            if message_exists is None:
                conn.execute(
                    """
                    INSERT INTO messages (
                        id, conversation_id, role, content, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assistant_message_id,
                        row["conversation_id"],
                        MessageRole.ASSISTANT.value,
                        "",
                        MessageStatus.CANCELLED.value,
                        now,
                        now,
                    ),
                )
            else:
                recovered_messages += conn.execute(
                    """
                    UPDATE messages
                    SET status = ?, updated_at = ?
                    WHERE id = ? AND role = ? AND status = ?
                    """,
                    (
                        MessageStatus.CANCELLED.value,
                        now,
                        assistant_message_id,
                        MessageRole.ASSISTANT.value,
                        MessageStatus.PARTIAL.value,
                    ),
                ).rowcount
            recovered_runs += conn.execute(
                """
                UPDATE agent_runs
                SET assistant_message_id = ?, status = ?, error_code = ?,
                    error_message = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    assistant_message_id,
                    AgentRunStatus.CANCELLED.value,
                    "process_interrupted",
                    "应用重启时，未完成的回复流已安全取消。",
                    now,
                    row["id"],
                    AgentRunStatus.RUNNING.value,
                ),
            ).rowcount
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, row["conversation_id"]),
            )

        # A process can stop after the run row was finalized but before the
        # assistant message update. Close any remaining assistant partials as
        # well, including rows from an older application version.
        recovered_messages += conn.execute(
            """
            UPDATE messages
            SET status = ?, updated_at = ?
            WHERE role = ? AND status = ?
            """,
            (
                MessageStatus.CANCELLED.value,
                now,
                MessageRole.ASSISTANT.value,
                MessageStatus.PARTIAL.value,
            ),
        ).rowcount
    recovered = recovered_runs + recovered_messages
    if recovered:
        logger.warning(
            "Recovered interrupted chat persistence: runs=%s messages=%s",
            recovered_runs,
            recovered_messages,
        )
    return recovered


class _StreamPartialPersister:
    """Throttled PARTIAL-state writer for the streaming assistant message.

    The previous implementation opened a new SQLite connection, rewrote the
    full message body and committed once PER TOKEN on the event loop thread —
    O(n²) character copies and one fsync per token for long replies, blocking
    every concurrent SSE stream. This reuses a single connection for the
    stream's lifetime and flushes at most every
     _STREAM_PARTIAL_FLUSH_TOKEN_COUNT tokens /
     _STREAM_PARTIAL_FLUSH_INTERVAL_SECONDS seconds. Terminal states use the
     same connection and are flushed immediately.
    """

    def __init__(self, request: Request, message_id: str) -> None:
        self._database = database(request)
        self._message_id = message_id
        self._conn: sqlite3.Connection | None = None
        self._session = None
        self._thread_lock = ThreadLock()
        self._pending_tokens = 0
        self._partial_flushes = 0
        self._last_flush = monotonic()

    async def note_token(self, chunks: list[str]) -> None:
        self._pending_tokens += 1
        if (
            self._partial_flushes >= _STREAM_MAX_PARTIAL_FLUSHES
            or (
                self._pending_tokens < _STREAM_PARTIAL_FLUSH_TOKEN_COUNT
                and monotonic() - self._last_flush < _STREAM_PARTIAL_FLUSH_INTERVAL_SECONDS
            )
        ):
            return
        await self._flush(chunks)

    async def persist_terminal(self, content: str, status_value: str, answer_basis: str = "not_assessed") -> None:
        await asyncio.to_thread(self._write_sync, content, status_value, answer_basis)
        self._pending_tokens = 0

    async def _flush(self, chunks: list[str]) -> None:
        await self.persist_terminal("".join(chunks), MessageStatus.PARTIAL.value)
        self._pending_tokens = 0
        self._last_flush = monotonic()

    def _write_sync(self, content: str, status_value: str, answer_basis: str = "not_assessed") -> None:
        # The connection is deliberately shared for one stream. All accesses
        # happen under a lock because to_thread may use different workers.
        with self._thread_lock:
            if self._session is None:
                self._session = self._database.session(check_same_thread=False)
                self._conn = self._session.__enter__()
            assert self._conn is not None
            try:
                self._conn.execute(
                    "UPDATE messages SET content = ?, status = ?, answer_basis = ?, updated_at = ? WHERE id = ?",
                    (content, status_value,
                     normalize_answer_basis(answer_basis) if status_value == "completed" else "not_assessed",
                     utc_now_iso(), self._message_id),
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            if status_value == MessageStatus.PARTIAL.value:
                self._partial_flushes += 1

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._thread_lock:
            session = self._session
            self._session = None
            self._conn = None
            if session is not None:
                try:
                    session.__exit__(None, None, None)
                except Exception:  # pragma: no cover - best-effort cleanup
                    logger.debug("Closing stream partial persister connection failed", exc_info=True)


async def _persisting_stream(request: Request, state: AgentState) -> AsyncIterator[AgentSseEventBase]:
    if not claim_chat_run(request, state):
        yield AgentErrorEvent(
            agent_run_id=state.agent_run_id,
            code="agent_run_not_found",
            message="回复流已过期、已启动或已被取消。",
        )
        return
    assistant_message_id = new_id()
    _insert_assistant_message(request, state, assistant_message_id)
    partial_persister = _StreamPartialPersister(request, assistant_message_id)
    token_chunks: list[str] = []
    final_status = AgentRunStatus.SUCCESS.value
    error_code = None
    error_message = None
    terminal_event_seen = False
    final_state_persisted = False
    shadow = getattr(request.app.state, "wiki_shadow", None)
    shadow_scope = shadow.foreground_started() if shadow is not None else None
    shadow_candidate = None
    shadow_ready = False

    try:
        try:
            runtime = agent_runtime(request)
            async for event in runtime.run(state):
                if isinstance(event, AgentTokenEvent):
                    token_chunks.append(event.text)
                    await partial_persister.note_token(token_chunks)
                    yield event
                elif isinstance(event, AgentDoneEvent):
                    terminal_event_seen = True
                    final_text = "".join(token_chunks) or event.text
                    if not final_text.strip():
                        final_status = AgentRunStatus.FAILED.value
                        error_code = "empty_response"
                        error_message = "后端返回了完成事件，但没有生成可显示回复。"
                        yield await _fail_message(
                            request,
                            state,
                            assistant_message_id,
                            error_code,
                            error_message,
                            persister=partial_persister,
                        )
                        break
                    final_status = AgentRunStatus.SUCCESS.value
                    error_code = None
                    error_message = None
                    await partial_persister.persist_terminal(
                        final_text, MessageStatus.COMPLETED.value, event.answer_basis,
                    )
                    shadow_candidate = getattr(runtime, "completed_state", None)
                    if not _post_reply_work_blocked(state):
                        _schedule_post_reply_work(request, state, assistant_message_id, final_text)
                    yield AgentReplyReadyEvent(
                        agent_run_id=state.agent_run_id,
                        intent=event.intent,
                        text=final_text,
                        answer_basis=event.answer_basis,
                    )
                    yield event
                    break
                elif isinstance(event, AgentErrorEvent):
                    terminal_event_seen = True
                    error_code, error_message = public_agent_error(event.code)
                    final_status = AgentRunStatus.FAILED.value
                    await partial_persister.persist_terminal(
                        "",
                        MessageStatus.FAILED.value,
                    )
                    yield AgentErrorEvent(
                        agent_run_id=state.agent_run_id,
                        code=error_code,
                        message=error_message,
                    )
                    break
                else:
                    yield event
        except Exception as exc:
            terminal_event_seen = True
            final_status = AgentRunStatus.FAILED.value
            error_code, error_message = public_agent_error(getattr(exc, "code", None))
            yield await _fail_message(
                request,
                state,
                assistant_message_id,
                error_code,
                error_message,
                persister=partial_persister,
            )

        if not terminal_event_seen:
            final_status = AgentRunStatus.FAILED.value
            error_code = "stream_ended_without_terminal_event"
            error_message = "回复流结束时没有收到完成或错误事件。"
            yield await _fail_message(
                request,
                state,
                assistant_message_id,
                error_code,
                error_message,
                persister=partial_persister,
            )

        _persist_stream_terminal_state(
            request,
            state,
            assistant_message_id,
            final_status,
            error_code=error_code,
            error_message=error_message,
        )
        final_state_persisted = True
        shadow_ready = True
    except (asyncio.CancelledError, GeneratorExit):
        if not terminal_event_seen:
            final_status = AgentRunStatus.CANCELLED.value
            error_code = "stream_cancelled"
            error_message = "客户端中断了回复流。"
            await partial_persister.persist_terminal(
                "",
                MessageStatus.CANCELLED.value,
            )
        if not final_state_persisted:
            _persist_stream_terminal_state(
                request,
                state,
                assistant_message_id,
                final_status,
                error_code=error_code,
                error_message=error_message,
            )
            final_state_persisted = True
        raise
    finally:
        try:
            await partial_persister.close()
            pop_chat_run(request, state.agent_run_id)
        finally:
            if shadow is not None:
                shadow.foreground_finished(
                    shadow_candidate if shadow_ready and final_status == AgentRunStatus.SUCCESS.value else None,
                    shadow_scope,
                )


def _persist_stream_terminal_state(
    request: Request,
    state: AgentState,
    assistant_message_id: str,
    final_status: str,
    *,
    error_code: str | None,
    error_message: str | None,
) -> None:
    _update_agent_run(
        request,
        state,
        assistant_message_id,
        final_status,
        error_code=error_code,
        error_message=error_message,
    )
    if final_status == AgentRunStatus.SUCCESS.value:
        action = "chat.complete"
        result = "success"
    elif final_status == AgentRunStatus.CANCELLED.value:
        action = "chat.cancelled"
        result = "failed"
    else:
        action = "chat.failed"
        result = "failed"
    record_audit(
        request,
        action=action,
        result=result,
        reason=audit_reason(
            request,
            agent_run_id=state.agent_run_id,
            conversation_id=state.conversation_id,
            error_code=error_code,
        ),
    )
    if final_status == AgentRunStatus.SUCCESS.value:
        _record_grounded_answer_metric(request, state, assistant_message_id)


def _record_grounded_answer_metric(
    request: Request,
    state: AgentState,
    assistant_message_id: str,
) -> None:
    if state.grounding_validation != "passed":
        return
    try:
        with database(request).session() as conn:
            run = conn.execute(
                "SELECT status FROM agent_runs WHERE id = ?",
                (state.agent_run_id,),
            ).fetchone()
        if run is None or str(run["status"]) != AgentRunStatus.SUCCESS.value:
            return
    except Exception:
        return
    accepted = tuple(
        envelope.result
        for envelope in gate_evidence(state.citations).accepted
        if envelope.result.recall_permissions.can_answer_context
    )
    if not accepted:
        return
    source_scopes = {citation.source_scope for citation in accepted}
    source_scope = next(iter(source_scopes)) if len(source_scopes) == 1 else "all"
    try:
        metrics = ProductMetricsService(database(request).path)
        try:
            metrics.record(
                event_type="grounded_answer",
                idempotency_key=f"grounded-answer:{assistant_message_id}",
                subject_id=assistant_message_id,
                dimensions={
                    "citation_valid": True,
                    "source_scope": source_scope,
                    "route": state.intent.value if state.intent is not None else "unknown",
                },
            )
        finally:
            metrics.close()
    except Exception:
        return


def _post_reply_work_blocked(state: AgentState) -> bool:
    return bool(
        state.suppress_post_reply_automation
        or (state.local_privacy_mode and state.local_privacy_sensitive_reason)
    )


def _schedule_post_reply_work(request: Request, state: AgentState, assistant_message_id: str, final_text: str) -> None:
    """Persist a post-reply job before starting any memory side effect.

    A few unit tests exercise this helper with a deliberately tiny fake app
    that has no database. Those tests retain the old in-process worker path;
    a real FastAPI app always has ``app.state.database`` and therefore never
    executes effects before the durable enqueue succeeds.
    """
    context = AppContext(
        app=request.app,
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    database_instance = _post_reply_database(context)
    if database_instance is None:
        _spawn_post_reply_task(
            context,
            state.model_copy(deep=True),
            assistant_message_id,
            final_text,
            job_id=None,
        )
        return

    job_id = new_id()
    store: PostReplyMemoryJobStore | None = None
    try:
        store = PostReplyMemoryJobStore(database_instance.path)
        record = store.enqueue(
            job_id=job_id,
            agent_run_id=state.agent_run_id,
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            assistant_message_id=assistant_message_id,
            stage_states={
                "schema_version": 1,
                "suppress_post_reply_automation": bool(state.suppress_post_reply_automation),
                "local_privacy_mode": bool(state.local_privacy_mode),
            },
        )
    except Exception:
        # The foreground answer is already durable, but running memory effects
        # without a claim would make a retry after restart non-idempotent.
        logger.error(
            "Post-reply job enqueue failed; memory effects were not scheduled for agent_run_id=%s",
            state.agent_run_id,
            exc_info=True,
        )
        return
    finally:
        if store is not None:
            store.close()

    _spawn_post_reply_task(
        context,
        state.model_copy(deep=True),
        assistant_message_id,
        final_text,
        job_id=record.id,
    )


def _spawn_post_reply_task(
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    final_text: str,
    *,
    job_id: str | None,
) -> None:
    if job_id is None:
        coroutine = _complete_assistant_message_background(
            context,
            state,
            assistant_message_id,
            final_text,
        )
    else:
        coroutine = _run_persisted_post_reply_job(
            context,
            state,
            assistant_message_id,
            final_text,
            job_id,
        )
    try:
        task = asyncio.create_task(coroutine)
    except RuntimeError:
        # Avoid leaking an un-awaited coroutine if a caller invokes the helper
        # outside an active event loop. The durable row remains recoverable.
        coroutine.close()
        logger.warning("Post-reply task could not be scheduled because no event loop is running")
        return
    _POST_REPLY_TASKS.add(task)
    task.add_done_callback(_finalize_post_reply_task)


def _finalize_post_reply_task(task: "asyncio.Task[None]") -> None:
    _POST_REPLY_TASKS.discard(task)
    _log_post_reply_task_result(task)


async def _complete_assistant_message_background(
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    final_text: str,
    job_id: str | None = None,
) -> None:
    """Run post-reply effects, optionally under a durable job lease.

    ``job_id`` is optional so existing callers and test doubles with the
    historical four-argument worker signature remain valid. Production
    scheduling always supplies it through ``_run_persisted_post_reply_job``.
    """
    if job_id is None:
        await _run_post_reply_effects(context, state, assistant_message_id, final_text)
        return

    database_instance = _post_reply_database(context)
    if database_instance is None:
        await _run_post_reply_effects(context, state, assistant_message_id, final_text)
        return

    owner = _post_reply_owner(job_id)
    store = PostReplyMemoryJobStore(database_instance.path)
    try:
        record, claimed = store.claim(
            job_id,
            owner=owner,
            lease_seconds=_post_reply_lease_seconds(),
            max_attempts=_post_reply_max_attempts(),
        )
        if not claimed or record is None:
            if record is not None and record.attempts >= _post_reply_max_attempts():
                store.mark_exhausted(job_id)
                logger.warning("Post-reply job retry budget exhausted for job_id=%s", job_id)
            return

        stage_states = {
            "schema_version": 1,
            "status": "running",
            "attempt": record.attempts,
        }
        store.update_stage_states(job_id, owner=owner, stage_states=stage_states)
        try:
            effect_states = await _run_post_reply_effects(
                context,
                state,
                assistant_message_id,
                final_text,
            )
            stage_states.update(effect_states)
            stage_states["status"] = "completed"
            store.complete(job_id, owner=owner, stage_states=stage_states)
        except asyncio.CancelledError:
            # Shutdown should leave the job eligible for the next process,
            # without consuming an attempt merely because the loop stopped.
            store.release(job_id, owner=owner, error_code="post_reply_shutdown")
            raise
        except Exception:
            stage_states["status"] = "failed"
            store.fail(
                job_id,
                owner=owner,
                stage_states=stage_states,
                error_code="post_reply_effect_failed",
            )
            raise
    finally:
        store.close()


async def _run_persisted_post_reply_job(
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    final_text: str,
    job_id: str,
) -> None:
    """Bridge durable scheduling to legacy monkeypatchable worker callables."""
    worker = _complete_assistant_message_background
    if _worker_accepts_job_id(worker):
        await worker(context, state, assistant_message_id, final_text, job_id=job_id)
        return

    # Older extensions replace the worker with a four-argument function.
    # Claim and finalize around that function so even the compatibility path
    # preserves the same at-most-one active executor guarantee.
    database_instance = _post_reply_database(context)
    if database_instance is None:
        await worker(context, state, assistant_message_id, final_text)
        return
    owner = _post_reply_owner(job_id)
    store = PostReplyMemoryJobStore(database_instance.path)
    try:
        record, claimed = store.claim(
            job_id,
            owner=owner,
            lease_seconds=_post_reply_lease_seconds(),
            max_attempts=_post_reply_max_attempts(),
        )
        if not claimed or record is None:
            return
        try:
            await worker(context, state, assistant_message_id, final_text)
            store.complete(
                job_id,
                owner=owner,
                stage_states={"schema_version": 1, "status": "completed", "attempt": record.attempts},
            )
        except asyncio.CancelledError:
            store.release(job_id, owner=owner, error_code="post_reply_shutdown")
            raise
        except Exception:
            store.fail(
                job_id,
                owner=owner,
                stage_states={"schema_version": 1, "status": "failed", "attempt": record.attempts},
                error_code="post_reply_effect_failed",
            )
            raise
    finally:
        store.close()


async def _run_post_reply_effects(
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    final_text: str,
) -> dict[str, object]:
    actions = await _archive_chat_memory_in_background(context, state, assistant_message_id, final_text)
    continuity_events = 0
    async for _ in _create_continuity_proposals(context, state, assistant_answer=final_text):
        continuity_events += 1
    return {
        "archive_action_count": len(actions),
        "continuity_event_count": continuity_events,
    }


def _worker_accepts_job_id(worker: object) -> bool:
    try:
        signature = inspect.signature(worker)
    except (TypeError, ValueError):
        return False
    return "job_id" in signature.parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _post_reply_database(context: AppContext):
    state = getattr(context.app, "state", None)
    return getattr(state, "database", None)


def _post_reply_owner(job_id: str) -> str:
    return f"{_POST_REPLY_WORKER_ID}:{job_id}"


def recover_post_reply_memory_jobs(app: object, *, limit: int = _POST_REPLY_RECOVERY_LIMIT) -> int:
    """Recover pending post-reply work during application startup.

    Only rows whose assistant message is already terminal and readable are
    scheduled. The queue stores message ids rather than prompt text, so a
    restart reconstructs an ``AgentState`` from the authoritative SQLite
    rows and never trusts an in-memory snapshot from the previous process.
    """
    context = AppContext(app=app)  # type: ignore[arg-type]
    database_instance = _post_reply_database(context)
    if database_instance is None:
        return 0
    store: PostReplyMemoryJobStore | None = None
    scheduled = 0
    try:
        store = PostReplyMemoryJobStore(database_instance.path)
        store.requeue_expired(max_attempts=_post_reply_max_attempts())
        for record in store.list_pending(limit=limit):
            if record.attempts >= _post_reply_max_attempts():
                store.mark_exhausted(record.id)
                continue
            if record.status == "failed":
                if not store.requeue_failed(record.id, max_attempts=_post_reply_max_attempts()):
                    continue
                refreshed = store.get(record.id)
                if refreshed is None:
                    continue
                record = refreshed
            payload = _rebuild_post_reply_payload(context, record)
            if payload is None:
                store.mark_exhausted(record.id, error_code="post_reply_messages_unavailable")
                continue
            state, answer = payload
            _spawn_post_reply_task(
                context,
                state,
                record.assistant_message_id,
                answer,
                job_id=record.id,
            )
            scheduled += 1
    except Exception:
        logger.error("Post-reply job recovery failed; rows remain durable for a later startup", exc_info=True)
    finally:
        if store is not None:
            store.close()
    return scheduled


def _rebuild_post_reply_payload(
    context: AppContext,
    record: PostReplyMemoryJobRecord,
) -> tuple[AgentState, str] | None:
    database_instance = _post_reply_database(context)
    if database_instance is None:
        return None
    with database_instance.session() as conn:
        row = conn.execute(
            """
            SELECT
                runs.status AS run_status,
                user_messages.content AS user_content,
                assistant_messages.content AS assistant_content,
                assistant_messages.status AS assistant_status
            FROM agent_runs AS runs
            JOIN messages AS user_messages
              ON user_messages.id = runs.user_message_id
             AND user_messages.id = ?
            JOIN messages AS assistant_messages
              ON assistant_messages.id = runs.assistant_message_id
             AND assistant_messages.id = ?
            WHERE runs.id = ?
              AND runs.conversation_id = ?
            """,
            (
                record.user_message_id,
                record.assistant_message_id,
                record.agent_run_id,
                record.conversation_id,
            ),
        ).fetchone()
    if row is None or str(row["assistant_status"]) != MessageStatus.COMPLETED.value:
        return None
    answer = str(row["assistant_content"] or "")
    user_message = str(row["user_content"] or "")
    if not answer.strip() or not user_message.strip():
        return None
    states = record.stage_states
    state = AgentState(
        conversation_id=record.conversation_id,
        message_id=record.user_message_id,
        agent_run_id=record.agent_run_id,
        user_message=user_message,
        status=AgentRunStatus.SUCCESS,
        suppress_post_reply_automation=bool(states.get("suppress_post_reply_automation", False)),
        local_privacy_mode=bool(states.get("local_privacy_mode", False)),
    )
    return state, answer


def _log_post_reply_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Post-reply chat memory task was cancelled")
    except Exception:
        logger.warning("Post-reply chat memory task failed", exc_info=True)


async def shutdown_post_reply_tasks() -> None:
    """Cancel and await post-reply jobs before the application shuts down."""
    tasks = tuple(_POST_REPLY_TASKS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _fail_message(
    request: Request,
    state: AgentState,
    assistant_message_id: str,
    code: str,
    _message: str,
    *,
    persister: _StreamPartialPersister | None = None,
) -> AgentErrorEvent:
    if persister is None:
        _update_assistant_message(request, assistant_message_id, "", MessageStatus.FAILED.value)
    else:
        await persister.persist_terminal("", MessageStatus.FAILED.value)
    safe_code, safe_message = public_agent_error(code)
    return AgentErrorEvent(agent_run_id=state.agent_run_id, code=safe_code, message=safe_message)


async def _archive_chat_memory_in_background(
    request: Request | AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
) -> list[AgentActionEvent]:
    if not assistant_answer.strip():
        return []
    return await archive_chat_memory(
        context=AppContext(
            app=request.app,
            request_id=getattr(getattr(request, "state", None), "request_id", None),
        ),
        state=state.model_copy(deep=True),
        assistant_message_id=assistant_message_id,
        assistant_answer=assistant_answer,
    )


async def _create_continuity_proposals(
    request: Request | AppContext,
    state: AgentState,
    *,
    assistant_answer: str,
) -> AsyncIterator[AgentContinuityProposalEvent]:
    if not assistant_answer.strip():
        return
    service = continuity_service(request)
    try:
        proposals = await service.create_proposals_from_exchange(
            user_message=state.user_message,
            assistant_answer=assistant_answer,
            conversation_id=state.conversation_id,
            source_message_id=state.message_id,
            agent_run_id=state.agent_run_id,
            model_client=chat_model_client(request, AgentId.REFLECTION_AGENT.value),
        )
    except Exception:
        logger.warning(
            "Continuity proposal generation skipped for agent_run_id=%s",
            state.agent_run_id,
            exc_info=True,
        )
        return

    # 用户明确在查询记忆/近期对话时，不要生成"下次接着聊"提案——
    # 那会让"我刚刚说了什么"这类查询得到"我不知道"+ 建议保存话题的割裂体验。
    if route_intent(state.user_message).intent == AgentIntent.SEARCH_MEMORY:
        proposals = [proposal for proposal in proposals if proposal.kind != "open_thread"]

    try:
        automation = automation_settings(request)
        policy = AutomationPolicy()
        for proposal in proposals:
            # 「下次接着聊」是纯陪伴增强：只记住一个未完话题供下次自然接上，
            # 没有任何写入风险。要求用户打开记忆页手动决定既不现实也无必要，
            # 因此直接自动确认；确认失败才降级为待确认兜底。
            if proposal.kind == "open_thread":
                try:
                    from .services.adapters import execute_continuity_activation

                    outcome = await execute_continuity_activation(
                        request,
                        proposal_id=proposal.id,
                        kind=proposal.kind,
                        source_message_id=proposal.source_message_id,
                        source_run_id=state.agent_run_id,
                        source_conversation_id=state.conversation_id,
                    )
                    if outcome.receipt.status == "verified":
                        yield agent_action_event(state.agent_run_id, outcome.action)
                        continue
                except Exception:
                    logger.warning(
                        "Open-thread continuity auto-confirm failed for proposal_id=%s; leaving it pending.",
                        proposal.id,
                        exc_info=True,
                    )
            decision = policy.decide(
                f"continuity.{proposal.kind}",
                confidence=proposal.confidence,
                reversible=False,
            )
            if automation.auto_structured_memory and decision.decision != "ask":
                try:
                    from .services.adapters import execute_continuity_activation

                    outcome = await execute_continuity_activation(
                        request,
                        proposal_id=proposal.id,
                        kind=proposal.kind,
                        source_message_id=proposal.source_message_id,
                        source_run_id=state.agent_run_id,
                        source_conversation_id=state.conversation_id,
                    )
                except Exception:
                    # Explicit failure branch: auto-confirm failed, so fall
                    # through and surface the proposal for manual confirmation
                    # instead of silently pretending nothing happened.
                    logger.warning(
                        "Continuity proposal auto-confirm failed for proposal_id=%s; leaving it pending manual confirmation.",
                        proposal.id,
                        exc_info=True,
                    )
                else:
                    if outcome.receipt.status == "verified":
                        yield agent_action_event(state.agent_run_id, outcome.action)
                        continue
                    logger.warning(
                        "Continuity auto-confirm lifecycle was not verified for proposal_id=%s: %s",
                        proposal.id,
                        outcome.receipt.safe_error_code or outcome.receipt.status,
                    )
            yield AgentContinuityProposalEvent(
                agent_run_id=state.agent_run_id,
                proposal_id=proposal.id,
                kind=proposal.kind,
                summary=proposal.summary,
                evidence=proposal.evidence,
                confidence=proposal.confidence,
                source_conversation_id=proposal.source_conversation_id,
                source_message_id=proposal.source_message_id,
                status=proposal.status,
            )
    finally:
        service.close()


def _insert_assistant_message(request: Request, state: AgentState, assistant_message_id: str) -> None:
    now = utc_now_iso()
    with database(request).session() as conn:
        with conn:
            conn.execute(
                """INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (assistant_message_id, state.conversation_id, MessageRole.ASSISTANT.value, "", MessageStatus.PARTIAL.value, now, now),
            )
            conn.execute("UPDATE agent_runs SET assistant_message_id = ?, updated_at = ? WHERE id = ?", (assistant_message_id, now, state.agent_run_id))


def _update_assistant_message(request: Request, message_id: str, content: str, status: str) -> None:
    with database(request).session() as conn:
        conn.execute(
            "UPDATE messages SET content = ?, status = ?, updated_at = ? WHERE id = ?",
            (content, status, utc_now_iso(), message_id),
        )
        conn.commit()


def _update_agent_run(
    request: Request, state: AgentState, assistant_message_id: str, status_value: str, *, error_code: str | None, error_message: str | None
) -> None:
    now = utc_now_iso()
    with database(request).session() as conn:
        with conn:
            conn.execute(
                """UPDATE agent_runs SET assistant_message_id = ?, status = ?, intent = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE id = ?""",
                (assistant_message_id, status_value, state.intent.value if state.intent else None, error_code, error_message, now, state.agent_run_id),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, state.conversation_id))
