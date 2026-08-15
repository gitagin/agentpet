from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.services.agent_actions import AutomationPolicy
from app.services.chat_auto_memory import ChatAutoMemoryEntry, ChatAutoMemoryWriteResult

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


def chat_auto_memory_service(context: AppContext) -> Any:
    from app.api.wiring import chat_auto_memory_service as factory

    return factory(context)


def action_lifecycle(context: AppContext) -> Any:
    from app.api.wiring import production_action_lifecycle

    return production_action_lifecycle(context)


def archive_daily_diary(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    automation,
    policy: AutomationPolicy,
    raise_errors: bool = False,
) -> tuple[Any | None, list[AgentActionEvent]] | Any:
    """Run the daily archive through the production action lifecycle.

    The synchronous wrapper preserves the historical direct-call failure
    contract.  Successful production work is awaitable and is consumed by
    ``PostReplyMemoryJobRunner``.
    """
    if not automation.auto_chat_diary:
        return None, []
    try:
        service = chat_auto_memory_service(context)
        service.close()
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning(
            "Chat auto memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
        return None, []
    return _archive_daily_diary_async(
        context=context,
        state=state,
        assistant_message_id=assistant_message_id,
        assistant_answer=assistant_answer,
        raise_errors=raise_errors,
    )


async def _archive_daily_diary_async(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    raise_errors: bool,
) -> tuple[ChatAutoMemoryWriteResult | None, list[AgentActionEvent]]:
    from app.api.services.adapters import _execute_registered_action

    from . import agent_action_event

    try:
        outcome = await _execute_registered_action(
            context,
            action_lifecycle=action_lifecycle(context),
            action_type="chat.daily_archive",
            target_ref=f"intent:post-reply/daily/{state.agent_run_id}",
            parameters={
                "conversation_id": state.conversation_id,
                "user_message_id": state.message_id,
                "assistant_message_id": assistant_message_id,
                "agent_run_id": state.agent_run_id,
                "user_question": state.user_message,
                "assistant_answer": assistant_answer,
            },
            expected_effect="Archive one completed chat exchange to the local daily memory log.",
            source_message_id=state.message_id,
            source_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
            reversible=False,
        )
        if outcome.receipt.status != "verified":
            raise RuntimeError(outcome.receipt.safe_error_code or "daily_archive_not_verified")
        result = _daily_result(outcome.receipt.result)
        return result, [agent_action_event(state.agent_run_id, outcome.action)]
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning(
            "Chat auto memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
        return None, []


def _daily_result(payload: dict[str, Any]) -> ChatAutoMemoryWriteResult:
    entry = ChatAutoMemoryEntry(
        id=str(payload["entry_id"]),
        conversation_id=str(payload["conversation_id"]),
        user_message_id=str(payload["user_message_id"]),
        assistant_message_id=str(payload["assistant_message_id"]),
        agent_run_id=str(payload["agent_run_id"]),
        entry_hash=str(payload["entry_hash"]),
        memory_date=str(payload["memory_date"]),
        memory_time=str(payload["memory_time"]),
        timezone=str(payload["timezone"]),
        markdown_path=str(payload["markdown_path"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
    )
    raw_job_id = payload.get("index_job_id")
    return ChatAutoMemoryWriteResult(
        entry=entry,
        written=bool(payload.get("written")),
        index_job_id=str(raw_job_id) if raw_job_id else None,
    )
