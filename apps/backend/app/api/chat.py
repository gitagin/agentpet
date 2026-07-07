from collections.abc import AsyncIterator
import asyncio
import logging
import re

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse

from ..agents.events import (
    AgentActionEvent,
    AgentContinuityProposalEvent,
    AgentDoneEvent,
    AgentErrorEvent,
    AgentEventBase,
    AgentReplyReadyEvent,
    AgentTokenEvent,
)
from ..errors import AppError
from ..agents.events import sse_stream
from ..agents.state import AgentState
from ..models.api import ChatAcceptedResponse, ChatRequest
from ..services.agent_actions import AgentActionCreate, AutomationPolicy
from ..services.chat_pipeline import agent_action_event, archive_chat_memory, automation_settings
from ..services.memory_policy import evaluate_memory_content
from ..services.prompt_context_types import PromptRecentTurn
from ..models.common import new_id
from ..models.enums import AgentId, AgentRunStatus, ConversationStatus, MessageRole, MessageStatus
from ..utils.time import utc_now_iso
from .wiring import (
    AppContext,
    add_chat_run,
    agent_runtime,
    record_agent_action,
    audit_reason,
    chat_model_client,
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
        with database(request).connect() as conn:
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
    with database(request).connect() as conn:
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


async def _persisting_stream(request: Request, state: AgentState) -> AsyncIterator[AgentEventBase]:
    assistant_message_id = new_id()
    _insert_assistant_message(request, state, assistant_message_id)
    token_chunks: list[str] = []
    final_status = AgentRunStatus.SUCCESS.value
    error_code = None
    error_message = None
    terminal_event_seen = False

    try:
        try:
            async for event in agent_runtime(request).run(state):
                if isinstance(event, AgentTokenEvent):
                    token_chunks.append(event.text)
                    _update_assistant_message(request, assistant_message_id, "".join(token_chunks), MessageStatus.PARTIAL.value)
                elif isinstance(event, AgentDoneEvent):
                    terminal_event_seen = True
                    final_text = "".join(token_chunks) or event.text
                    if not final_text.strip():
                        final_status = AgentRunStatus.FAILED.value
                        error_code = "empty_response"
                        error_message = "后端返回了完成事件，但没有生成可显示回复。"
                        yield _fail_message(request, state, assistant_message_id, "".join(token_chunks), error_code, error_message)
                        continue
                    _update_assistant_message(request, assistant_message_id, final_text, MessageStatus.COMPLETED.value)
                    yield AgentReplyReadyEvent(
                        agent_run_id=state.agent_run_id,
                        intent=event.intent,
                        text=final_text,
                    )
                    if not _post_reply_work_blocked_by_local_privacy(state):
                        _schedule_post_reply_work(request, state, assistant_message_id, final_text)
                    final_status = AgentRunStatus.SUCCESS.value
                elif isinstance(event, AgentErrorEvent):
                    terminal_event_seen = True
                    error_code = event.code
                    error_message = event.message
                    final_status = AgentRunStatus.FAILED.value
                    _update_assistant_message(request, assistant_message_id, "".join(token_chunks), MessageStatus.FAILED.value)
                yield event
        except Exception as exc:
            terminal_event_seen = True
            final_status = AgentRunStatus.FAILED.value
            error_code = getattr(exc, "code", exc.__class__.__name__)
            error_message = str(exc) or "智能体流式回复异常中断。"
            yield _fail_message(request, state, assistant_message_id, "".join(token_chunks), error_code, error_message)

        if not terminal_event_seen:
            final_status = AgentRunStatus.FAILED.value
            error_code = "stream_ended_without_terminal_event"
            error_message = "回复流结束时没有收到完成或错误事件。"
            yield _fail_message(request, state, assistant_message_id, "".join(token_chunks), error_code, error_message)

        _update_agent_run(request, state, assistant_message_id, final_status, error_code=error_code, error_message=error_message)
        record_audit(
            request,
            action="chat.complete" if final_status == AgentRunStatus.SUCCESS.value else "chat.failed",
            result="success" if final_status == AgentRunStatus.SUCCESS.value else "failed",
            reason=audit_reason(request, agent_run_id=state.agent_run_id, conversation_id=state.conversation_id, error_code=error_code),
        )
    finally:
        pop_chat_run(request, state.agent_run_id)


def _post_reply_work_blocked_by_local_privacy(state: AgentState) -> bool:
    return bool(state.local_privacy_mode and state.local_privacy_sensitive_reason)


def _schedule_post_reply_work(request: Request, state: AgentState, assistant_message_id: str, final_text: str) -> None:
    context = AppContext(
        app=request.app,
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    task = asyncio.create_task(
        _complete_assistant_message_background(
            context,
            state.model_copy(deep=True),
            assistant_message_id,
            final_text,
        )
    )
    task.add_done_callback(_log_post_reply_task_result)


async def _complete_assistant_message_background(
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    final_text: str,
) -> None:
    _update_assistant_message(context, assistant_message_id, final_text, MessageStatus.COMPLETED.value)
    await _archive_chat_memory_in_background(context, state, assistant_message_id, final_text)
    async for _ in _create_continuity_proposals(context, state, assistant_answer=final_text):
        pass


def _log_post_reply_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Post-reply chat memory task was cancelled")
    except Exception:
        logger.warning("Post-reply chat memory task failed", exc_info=True)


def _fail_message(request: Request, state: AgentState, assistant_message_id: str, content: str, code: str, message: str) -> AgentErrorEvent:
    _update_assistant_message(request, assistant_message_id, content, MessageStatus.FAILED.value)
    return AgentErrorEvent(agent_run_id=state.agent_run_id, code=code, message=message)


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
    except Exception as exc:
        logger.warning(
            "Continuity proposal generation skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
        return

    try:
        automation = automation_settings(request)
        policy = AutomationPolicy()
        for proposal in proposals:
            decision = policy.decide(
                f"continuity.{proposal.kind}",
                confidence=proposal.confidence,
                reversible=False,
            )
            if automation.auto_structured_memory and decision.decision != "ask":
                try:
                    confirmed = service.confirm_proposal(proposal.id)
                except Exception:
                    confirmed = proposal
                else:
                    action = record_agent_action(
                        request,
                        AgentActionCreate(
                            action_type=f"continuity.{confirmed.kind}",
                            title="已自动更新桌宠连续性",
                            summary=confirmed.summary,
                            source_agent_run_id=confirmed.agent_run_id,
                            source_conversation_id=confirmed.source_conversation_id,
                            source_message_id=confirmed.source_message_id,
                            risk_tier=decision.risk_tier,
                            decision=decision.decision,
                            status="completed",
                            metadata={
                                "proposal_id": confirmed.id,
                                "kind": confirmed.kind,
                                "confidence": confirmed.confidence,
                                "policy_reason": decision.reason,
                            },
                            reversible=False,
                        ),
                    )
                    yield agent_action_event(state.agent_run_id, action)
                    continue
                proposal = confirmed
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
    with database(request).connect() as conn:
        with conn:
            conn.execute(
                """INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (assistant_message_id, state.conversation_id, MessageRole.ASSISTANT.value, "", MessageStatus.PARTIAL.value, now, now),
            )
            conn.execute("UPDATE agent_runs SET assistant_message_id = ?, updated_at = ? WHERE id = ?", (assistant_message_id, now, state.agent_run_id))


def _update_assistant_message(request: Request, message_id: str, content: str, status: str) -> None:
    with database(request).connect() as conn:
        conn.execute(
            "UPDATE messages SET content = ?, status = ?, updated_at = ? WHERE id = ?",
            (content, status, utc_now_iso(), message_id),
        )
        conn.commit()


def _update_agent_run(
    request: Request, state: AgentState, assistant_message_id: str, status_value: str, *, error_code: str | None, error_message: str | None
) -> None:
    now = utc_now_iso()
    with database(request).connect() as conn:
        with conn:
            conn.execute(
                """UPDATE agent_runs SET assistant_message_id = ?, status = ?, intent = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE id = ?""",
                (assistant_message_id, status_value, state.intent.value if state.intent else None, error_code, error_message, now, state.agent_run_id),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, state.conversation_id))
