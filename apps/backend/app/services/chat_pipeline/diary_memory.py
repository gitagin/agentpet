from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.services.agent_actions import AutomationPolicy

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


def diary_memory_service(context: AppContext) -> Any:
    from app.api.wiring import diary_memory_service as factory

    return factory(context)


def action_lifecycle(context: AppContext) -> Any:
    from app.api.wiring import production_action_lifecycle

    return production_action_lifecycle(context)


async def archive_structured_diary_memory(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    daily_result: Any | None,
    automation,
    policy: AutomationPolicy,
    raise_errors: bool = False,
) -> tuple[tuple[str, ...], list[AgentActionEvent]]:
    from app.api.services.adapters import _execute_registered_action

    from . import agent_action_event

    if not automation.auto_structured_memory:
        return (), []
    if not state.user_message.strip() or not assistant_answer.strip():
        return (), []

    daily_entry = getattr(daily_result, "entry", None)
    occurred_at = getattr(daily_entry, "created_at", None) or _message_created_at(
        context,
        assistant_message_id,
    )
    markdown_path = getattr(daily_entry, "markdown_path", None)

    try:
        expected_object_count = await _has_structured_signal(
            context=context,
            user_question=state.user_message,
            assistant_answer=assistant_answer,
            occurred_at=occurred_at,
            markdown_path=markdown_path,
        )
        if expected_object_count <= 0:
            return (), []
        outcome = await _execute_registered_action(
            context,
            action_lifecycle=action_lifecycle(context),
            action_type="diary.structured_memory",
            target_ref=f"intent:post-reply/structured-diary/{state.agent_run_id}",
            parameters={
                "conversation_id": state.conversation_id,
                "user_message_id": state.message_id,
                "assistant_message_id": assistant_message_id,
                "agent_run_id": state.agent_run_id,
                "user_question": state.user_message,
                "assistant_answer": assistant_answer,
                "occurred_at": occurred_at,
                "markdown_path": markdown_path,
                "expected_object_count": expected_object_count,
            },
            expected_effect="Persist evidence-backed structured diary objects for one completed chat exchange.",
            source_message_id=state.message_id,
            source_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
            reversible=False,
        )
        if outcome.receipt.status != "verified":
            raise RuntimeError(outcome.receipt.safe_error_code or "structured_diary_not_verified")
        object_ids = tuple(str(item) for item in outcome.receipt.result.get("object_ids") or ())
        if not object_ids:
            raise RuntimeError("structured_diary_authoritative_objects_missing")
        return object_ids, [agent_action_event(state.agent_run_id, outcome.action)]
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning(
            "Structured diary memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
        return (), []


async def _has_structured_signal(
    *,
    context: AppContext,
    user_question: str,
    assistant_answer: str,
    occurred_at: str,
    markdown_path: str | None,
) -> int:
    service = diary_memory_service(context)
    try:
        diary_text = "\n".join(
            [
                f"User question: {user_question}",
                f"Assistant answer: {assistant_answer}",
            ]
        )
        memory_date = occurred_at[:10] if len(occurred_at) >= 10 else None
        extracted = await service.extractor.extract(
            diary_text,
            memory_date=memory_date,
            source_path=markdown_path,
        )
        return len(extracted)
    finally:
        service.close()


def _message_created_at(context: AppContext, assistant_message_id: str) -> str:
    from app.api.wiring import database

    try:
        with database(context).session() as conn:
            row = conn.execute(
                "SELECT created_at FROM messages WHERE id = ?",
                (assistant_message_id,),
            ).fetchone()
        if row is not None and row[0]:
            return str(row[0])
    except Exception:
        logger.debug("Assistant message timestamp lookup failed", exc_info=True)
    # Test doubles may not expose a message table.  A fixed fallback keeps
    # the lifecycle key stable across retries instead of using wall-clock time.
    return "1970-01-01T00:00:00Z"
