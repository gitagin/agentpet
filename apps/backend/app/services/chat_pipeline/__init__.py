import logging

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.api.wiring import AppContext, record_agent_action, settings_store
from app.services.agent_actions import AgentActionCreate, AutomationPolicy

from .diary import archive_daily_diary
from .diary_memory import archive_structured_diary_memory
from .long_term import archive_long_term_memory
from .wiki_summary import archive_wiki_answer_summary

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
    actions: list[AgentActionEvent] = []
    automation = automation_settings(context)
    policy = AutomationPolicy()

    if _post_chat_automation_disabled(automation):
        actions.append(
            skipped_agent_action_event(
                context=context,
                state=state,
                action_type="chat.auto_memory.skip",
                title="Skipped automatic organization",
                summary=(
                    "Skipped because automatic diary, structured memory, long-term memory, "
                    "and Wiki organization are disabled; no local asset was written."
                ),
                reason="automation_disabled",
            )
        )
        return actions

    actions.extend(
        archive_long_term_memory(
            context=context,
            state=state,
            automation=automation,
            policy=policy,
        )
    )
    daily_result, daily_actions = archive_daily_diary(
        context=context,
        state=state,
        assistant_message_id=assistant_message_id,
        assistant_answer=assistant_answer,
        automation=automation,
        policy=policy,
    )
    actions.extend(daily_actions)
    diary_object_ids, diary_actions = await archive_structured_diary_memory(
        context=context,
        state=state,
        assistant_message_id=assistant_message_id,
        assistant_answer=assistant_answer,
        daily_result=daily_result,
        automation=automation,
        policy=policy,
    )
    actions.extend(diary_actions)
    actions.extend(
        archive_wiki_answer_summary(
            context=context,
            state=state,
            assistant_message_id=assistant_message_id,
            assistant_answer=assistant_answer,
            daily_result=daily_result,
            diary_object_ids=diary_object_ids,
            automation=automation,
            policy=policy,
        )
    )
    return actions


def _post_chat_automation_disabled(automation) -> bool:
    return not any(
        (
            getattr(automation, "auto_chat_diary", False),
            getattr(automation, "auto_structured_memory", False),
            getattr(automation, "auto_long_term_memory", False),
            getattr(automation, "auto_wiki_organize", False),
        )
    )


def automation_settings(context: AppContext):
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
