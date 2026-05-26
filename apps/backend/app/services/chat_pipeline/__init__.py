import logging

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.api.wiring import AppContext, settings_store
from app.services.agent_actions import AutomationPolicy

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
        action_type=action.action_type,
        risk_tier=action.risk_tier,
        decision=action.decision,
        status=action.status,
        title=action.title,
        summary=action.summary,
        target_paths=action.target_paths,
        reversible=action.reversible,
        requires_confirmation=action.decision == "ask",
        metadata=action.metadata,
    )
