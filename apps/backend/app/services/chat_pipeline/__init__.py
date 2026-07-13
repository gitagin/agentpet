from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.services.agent_actions import AgentActionCreate, AutomationPolicy

from .consolidation import consolidate_slow_memory
from .diary import archive_daily_diary
from .diary_memory import archive_structured_diary_memory
from .wiki_summary import archive_wiki_answer_summary

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


class AutomationStepSkipped(Exception):
    pass


async def archive_chat_memory(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
) -> list[AgentActionEvent]:
    from app.services.post_reply_memory_job_runner import PostReplyMemoryJobInput, PostReplyMemoryJobRunner

    run = await PostReplyMemoryJobRunner(
        automation_provider=automation_settings,
        daily_diary_stage=archive_daily_diary,
        structured_diary_stage=archive_structured_diary_memory,
        slow_consolidation_stage=consolidate_slow_memory,
        wiki_summary_stage=archive_wiki_answer_summary,
    ).run_with_actions(
        PostReplyMemoryJobInput(
            context=context,
            state=state,
            assistant_message_id=assistant_message_id,
            assistant_answer=assistant_answer,
            policy=AutomationPolicy(),
        )
    )
    if _job_all_stages_disabled(run.result):
        actions = [_disabled_automation_skip_event(context=context, state=state)]
    else:
        actions = list(run.action_events)
    _schedule_reflection_job(context=context, state=state, assistant_answer=assistant_answer)
    return actions


def _schedule_reflection_job(*, context: AppContext, state: AgentState, assistant_answer: str) -> None:
    if state.local_privacy_mode or state.local_privacy_sensitive_reason:
        return
    manager = getattr(getattr(context, "app", None), "state", None)
    manager = getattr(manager, "reflection_jobs", None)
    if manager is None:
        return
    try:
        from app.api.services.factory import chat_model_client

        model = chat_model_client(context)
    except Exception:
        logger.warning("Reflection model setup failed; foreground and post-reply stages remain complete", exc_info=True)
        return
    if model is None:
        return
    from app.agents.reflection_graph import ReflectionJobInput

    manager.start(
        ReflectionJobInput(
            state=state.model_copy(deep=True),
            assistant_answer=assistant_answer,
            model=model,
        )
    )


def _post_chat_automation_disabled(automation) -> bool:
    return not any(
        (
            getattr(automation, "auto_chat_diary", False),
            getattr(automation, "auto_structured_memory", False),
            getattr(automation, "auto_long_term_memory", False),
            getattr(automation, "auto_wiki_organize", False),
        )
    )


def _job_all_stages_disabled(result) -> bool:
    return bool(result.stages) and all(
        stage.status == "skipped" and stage.safe_summary == "Stage skipped: disabled."
        for stage in result.stages
    )


def _disabled_automation_skip_event(*, context: AppContext, state: AgentState) -> AgentActionEvent:
    return skipped_agent_action_event(
        context=context,
        state=state,
        action_type="chat.auto_memory.skip",
        title="Skipped automatic memory organization",
        summary="Automatic memory organization is disabled; no local assets were written.",
        reason="automation_disabled",
    )


def automation_settings(context: AppContext):
    from app.api.wiring import settings_store

    store = settings_store(context)
    try:
        return store.get_automation_settings()
    finally:
        store.close()


def agent_action_event(agent_run_id: str, action) -> AgentActionEvent:
    return AgentActionEvent(
        agent_run_id=agent_run_id,
        action_id=action.action_id,
        source_agent_run_id=action.source_agent_run_id,
        source_conversation_id=action.source_conversation_id,
        source_message_id=action.source_message_id,
        action_type=action.action_type,
        risk_tier=action.risk_tier,
        decision=action.decision,
        status=action.status,
        title=action.title,
        summary=action.summary,
        target_paths=action.target_paths,
        reversible=action.reversible,
        reverted_by=action.reverted_by,
        reverts_action_id=action.reverts_action_id,
        error=action.error,
        source=action.source,
        diff_summary=action.diff_summary,
        requires_confirmation=action.decision == "ask",
        metadata=action.metadata,
        created_at=action.created_at,
        updated_at=action.updated_at,
        completed_at=action.completed_at,
    )


def skipped_agent_action_event(
    *,
    context: AppContext,
    state: AgentState,
    action_type: str,
    title: str,
    summary: str,
    reason: str,
    risk_tier: str = "low",
) -> AgentActionEvent:
    from app.api.wiring import record_agent_action

    action = record_agent_action(
        context,
        AgentActionCreate(
            action_type=action_type,
            title=title,
            summary=summary,
            source_agent_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
            source_message_id=state.message_id,
            risk_tier=risk_tier,  # type: ignore[arg-type]
            decision="notify",
            status="skipped",
            metadata={"skipped_reason": reason, "safe_summary": True},
            reversible=False,
        ),
    )
    return agent_action_event(state.agent_run_id, action)
