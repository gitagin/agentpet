from collections.abc import AsyncIterator
import logging
import threading

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse

from ..agents.events import (
    AgentContinuityProposalEvent,
    AgentDoneEvent,
    AgentErrorEvent,
    AgentEventBase,
    AgentTokenEvent,
)
from ..errors import AppError
from ..agents.events import sse_stream
from ..agents.state import AgentState
from ..models.api import ChatAcceptedResponse, ChatRequest
from ..models.common import new_id
from ..models.enums import AgentRunStatus, ConversationStatus, MessageRole, MessageStatus
from ..services.tasks import utc_now_iso
from .wiring import (
    agent_runtime,
    audit_reason,
    chat_auto_memory_service,
    chat_model_client,
    continuity_service,
    database,
    diary_memory_service,
    long_term_memory_service,
    record_audit,
)

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ChatAcceptedResponse)
async def create_chat(chat_request: ChatRequest, request: Request) -> ChatAcceptedResponse:
    conversation_id = chat_request.conversation_id or new_id()
    message_id = new_id()
    agent_run_id = new_id()
    _create_chat_records(
        request,
        conversation_id=conversation_id,
        message_id=message_id,
        agent_run_id=agent_run_id,
        user_message=chat_request.message,
    )
    record_audit(
        request,
        action="chat.create",
        result="success",
        reason=audit_reason(request, agent_run_id=agent_run_id, conversation_id=conversation_id),
    )
    request.app.state.chat_runs[agent_run_id] = AgentState(
        conversation_id=conversation_id,
        message_id=message_id,
        agent_run_id=agent_run_id,
        user_message=chat_request.message,
    )
    return ChatAcceptedResponse(
        conversation_id=conversation_id,
        message_id=message_id,
        agent_run_id=agent_run_id,
        stream_url=f"/api/chat/runs/{agent_run_id}/events",
    )


@router.get("/runs/{agent_run_id}/events")
async def stream_chat(agent_run_id: str, request: Request) -> StreamingResponse:
    state = request.app.state.chat_runs.get(agent_run_id)
    if state is None:
        raise AppError(
            code="agent_run_not_found",
            message="未找到智能体运行记录。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"agent_run_id": agent_run_id},
        )
    return StreamingResponse(
        sse_stream(_persisting_stream(request, state)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{agent_run_id}/stream")
async def stream_chat_alias(agent_run_id: str, request: Request) -> StreamingResponse:
    return await stream_chat(agent_run_id, request)


@router.get("/stream/{agent_run_id}")
async def stream_chat_legacy(agent_run_id: str, request: Request) -> StreamingResponse:
    return await stream_chat(agent_run_id, request)


def _ensure_chat_schema(request: Request) -> None:
    with database(request).connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_message_id TEXT NOT NULL,
                assistant_message_id TEXT,
                status TEXT NOT NULL,
                intent TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY(user_message_id) REFERENCES messages(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


def _create_chat_records(
    request: Request,
    *,
    conversation_id: str,
    message_id: str,
    agent_run_id: str,
    user_message: str,
) -> None:
    _ensure_chat_schema(request)
    now = utc_now_iso()
    title = user_message.strip()[:80]
    with database(request).connect() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO conversations (id, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (conversation_id, title, ConversationStatus.ACTIVE.value, now, now),
            )
            conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    MessageRole.USER.value,
                    user_message,
                    MessageStatus.COMPLETED.value,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO agent_runs (
                    id, conversation_id, user_message_id, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_run_id,
                    conversation_id,
                    message_id,
                    AgentRunStatus.RUNNING.value,
                    now,
                    now,
                ),
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
                    _update_assistant_message(
                        request,
                        assistant_message_id,
                        "".join(token_chunks),
                        MessageStatus.PARTIAL.value,
                    )
                elif isinstance(event, AgentDoneEvent):
                    terminal_event_seen = True
                    final_text = "".join(token_chunks) or event.text
                    if not final_text.strip():
                        final_status = AgentRunStatus.FAILED.value
                        error_code = "empty_response"
                        error_message = "后端返回了完成事件，但没有生成可显示回复。"
                        _update_assistant_message(
                            request,
                            assistant_message_id,
                            "".join(token_chunks),
                            MessageStatus.FAILED.value,
                        )
                        yield AgentErrorEvent(
                            agent_run_id=state.agent_run_id,
                            code=error_code,
                            message=error_message,
                        )
                        continue
                    _update_assistant_message(
                        request,
                        assistant_message_id,
                        final_text,
                        MessageStatus.COMPLETED.value,
                    )
                    async for continuity_event in _create_continuity_proposals(
                        request,
                        state,
                        assistant_answer=final_text,
                    ):
                        yield continuity_event
                    _archive_chat_memory_in_background(request, state, assistant_message_id, final_text)
                    final_status = AgentRunStatus.SUCCESS.value
                elif isinstance(event, AgentErrorEvent):
                    terminal_event_seen = True
                    error_code = event.code
                    error_message = event.message
                    _update_assistant_message(
                        request,
                        assistant_message_id,
                        "".join(token_chunks),
                        MessageStatus.FAILED.value,
                    )
                    final_status = AgentRunStatus.FAILED.value
                yield event
        except Exception as exc:
            terminal_event_seen = True
            final_status = AgentRunStatus.FAILED.value
            error_code = getattr(exc, "code", exc.__class__.__name__)
            error_message = str(exc) or "智能体流式回复异常中断。"
            _update_assistant_message(
                request,
                assistant_message_id,
                "".join(token_chunks),
                MessageStatus.FAILED.value,
            )
            yield AgentErrorEvent(
                agent_run_id=state.agent_run_id,
                code=error_code,
                message=error_message,
            )

        if not terminal_event_seen:
            terminal_event_seen = True
            final_status = AgentRunStatus.FAILED.value
            error_code = "stream_ended_without_terminal_event"
            error_message = "回复流结束时没有收到完成或错误事件。"
            _update_assistant_message(
                request,
                assistant_message_id,
                "".join(token_chunks),
                MessageStatus.FAILED.value,
            )
            yield AgentErrorEvent(
                agent_run_id=state.agent_run_id,
                code=error_code,
                message=error_message,
            )

        _update_agent_run(
            request,
            state,
            assistant_message_id,
            final_status,
            error_code=error_code,
            error_message=error_message,
        )
        record_audit(
            request,
            action="chat.complete" if final_status == AgentRunStatus.SUCCESS.value else "chat.failed",
            result="success" if final_status == AgentRunStatus.SUCCESS.value else "failed",
            reason=audit_reason(
                request,
                agent_run_id=state.agent_run_id,
                conversation_id=state.conversation_id,
                error_code=error_code,
            ),
        )
    finally:
        request.app.state.chat_runs.pop(state.agent_run_id, None)


def _archive_chat_memory_in_background(
    request: Request,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
) -> None:
    if not assistant_answer.strip():
        return
    app = request.app
    worker = threading.Thread(
        target=_archive_chat_memory,
        kwargs={
            "app": app,
            "state": state.model_copy(deep=True),
            "assistant_message_id": assistant_message_id,
            "assistant_answer": assistant_answer,
        },
        name=f"chat-memory-{state.agent_run_id[:8]}",
        daemon=True,
    )
    worker.start()


async def _create_continuity_proposals(
    request: Request,
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
            model_client=chat_model_client(request, "continuity_agent"),
        )
    except Exception as exc:
        logger.warning(
            "Continuity proposal generation skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
        return
    finally:
        service.close()

    for proposal in proposals:
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


def _archive_chat_memory(
    *,
    app,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
) -> None:
    service = None
    long_term_service = None
    daily_result = None
    try:
        request = _AppRequest(app)
        long_term_service = long_term_memory_service(request)
        long_term_service.remember_from_user_message(
            state.user_message,
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            agent_run_id=state.agent_run_id,
        )
    except Exception as exc:
        logger.warning(
            "Long-term memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    finally:
        if long_term_service is not None and hasattr(long_term_service, "close"):
            long_term_service.close()

    try:
        request = _AppRequest(app)
        service = chat_auto_memory_service(request)
        daily_result = service.append_chat_exchange(
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            assistant_message_id=assistant_message_id,
            agent_run_id=state.agent_run_id,
            user_question=state.user_message,
            assistant_answer=assistant_answer,
        )
    except Exception as exc:
        logger.warning(
            "Chat auto memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    finally:
        if service is not None:
            service.close()

    if daily_result is None:
        return

    diary_service = None
    try:
        import asyncio

        request = _AppRequest(app)
        diary_service = diary_memory_service(request)
        asyncio.run(
            diary_service.archive_chat_exchange(
                conversation_id=state.conversation_id,
                user_message_id=state.message_id,
                assistant_message_id=assistant_message_id,
                agent_run_id=state.agent_run_id,
                user_question=state.user_message,
                assistant_answer=assistant_answer,
                occurred_at=daily_result.entry.created_at,
                markdown_path=daily_result.entry.markdown_path,
            )
        )
    except Exception as exc:
        logger.warning(
            "Structured diary memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    finally:
        if diary_service is not None:
            diary_service.close()


class _AppRequest:
    def __init__(self, app) -> None:
        self.app = app


def _insert_assistant_message(request: Request, state: AgentState, assistant_message_id: str) -> None:
    now = utc_now_iso()
    with database(request).connect() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assistant_message_id,
                    state.conversation_id,
                    MessageRole.ASSISTANT.value,
                    "",
                    MessageStatus.PARTIAL.value,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE agent_runs SET assistant_message_id = ?, updated_at = ? WHERE id = ?",
                (assistant_message_id, now, state.agent_run_id),
            )


def _update_assistant_message(request: Request, message_id: str, content: str, status: str) -> None:
    with database(request).connect() as conn:
        conn.execute(
            "UPDATE messages SET content = ?, status = ?, updated_at = ? WHERE id = ?",
            (content, status, utc_now_iso(), message_id),
        )
        conn.commit()


def _update_agent_run(
    request: Request,
    state: AgentState,
    assistant_message_id: str,
    status_value: str,
    *,
    error_code: str | None,
    error_message: str | None,
) -> None:
    with database(request).connect() as conn:
        with conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET assistant_message_id = ?,
                    status = ?,
                    intent = ?,
                    error_code = ?,
                    error_message = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    assistant_message_id,
                    status_value,
                    state.intent.value if state.intent else None,
                    error_code,
                    error_message,
                    utc_now_iso(),
                    state.agent_run_id,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (utc_now_iso(), state.conversation_id),
            )
