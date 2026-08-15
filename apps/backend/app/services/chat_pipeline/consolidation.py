from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.services.agent_actions import AutomationPolicy

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


def memory_consolidation_service(context: AppContext) -> Any:
    from app.api.wiring import memory_consolidation_service as factory

    return factory(context)


def action_lifecycle(context: AppContext) -> Any:
    from app.api.wiring import production_action_lifecycle

    return production_action_lifecycle(context)


def consolidate_slow_memory(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    daily_result: Any | None,
    diary_object_ids: tuple[str, ...],
    automation,
    policy: AutomationPolicy,
    raise_errors: bool = False,
) -> list[AgentActionEvent] | Any:
    from . import skipped_agent_action_event

    if not automation.auto_long_term_memory:
        return []
    diary_markdown_path = getattr(getattr(daily_result, "entry", None), "markdown_path", None)
    service = None
    try:
        service = memory_consolidation_service(context)
        preview = service.preview(
            user_message=state.user_message,
            assistant_answer=assistant_answer,
            diary_object_ids=diary_object_ids,
            diary_markdown_path=diary_markdown_path,
        )
        if preview.candidate_count == 0:
            return [
                skipped_agent_action_event(
                    context=context,
                    state=state,
                    action_type="memory.consolidation.skip",
                    title="Skipped slow memory consolidation",
                    summary="This exchange did not contain a safe durable memory signal.",
                    reason="no_signal",
                    risk_tier="low",
                )
            ]
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning(
            "Slow memory consolidation skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
        return []
    finally:
        if service is not None:
            service.close()

    return _consolidate_slow_memory_async(
        context=context,
        state=state,
        assistant_message_id=assistant_message_id,
        assistant_answer=assistant_answer,
        diary_object_ids=diary_object_ids,
        diary_markdown_path=diary_markdown_path,
        safety_event=preview.has_sensitive_signal,
        expected_candidate_count=preview.candidate_count,
        raise_errors=raise_errors,
    )


async def _consolidate_slow_memory_async(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    diary_object_ids: tuple[str, ...],
    diary_markdown_path: str | None,
    safety_event: bool,
    expected_candidate_count: int,
    raise_errors: bool,
) -> list[AgentActionEvent]:
    from app.api.services.adapters import _execute_registered_action

    from . import agent_action_event

    action_type = "memory.consolidation.safety_event" if safety_event else "memory.consolidation.candidate"
    parameters: dict[str, object] = {
        "conversation_id": state.conversation_id,
        "user_message_id": state.message_id,
        "assistant_message_id": assistant_message_id,
        "agent_run_id": state.agent_run_id,
        "diary_object_ids": list(diary_object_ids),
        "diary_markdown_path": diary_markdown_path,
        "expected_candidate_count": expected_candidate_count,
    }
    if not safety_event:
        parameters.update(
            {
                "user_message": state.user_message,
                "assistant_answer": assistant_answer,
            }
        )
    try:
        outcome = await _execute_registered_action(
            context,
            action_lifecycle=action_lifecycle(context),
            action_type=action_type,
            target_ref=f"intent:post-reply/consolidation/{state.agent_run_id}",
            parameters=parameters,
            expected_effect=(
                "Record one redacted non-recallable memory safety event."
                if safety_event
                else "Persist evidence-backed slow memory candidates for one completed chat exchange."
            ),
            source_message_id=state.message_id,
            source_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
            reversible=False,
        )
        if outcome.receipt.status != "verified":
            raise RuntimeError(outcome.receipt.safe_error_code or "memory_consolidation_not_verified")
        return [agent_action_event(state.agent_run_id, outcome.action)]
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning(
            "Slow memory consolidation skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
        return []
