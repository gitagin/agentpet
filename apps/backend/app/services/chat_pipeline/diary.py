import logging
from typing import Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.api.wiring import AppContext, chat_auto_memory_service, record_agent_action
from app.services.agent_actions import AgentActionCreate, AutomationPolicy

logger = logging.getLogger(__name__)


def archive_daily_diary(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    automation,
    policy: AutomationPolicy,
) -> tuple[Any | None, list[AgentActionEvent]]:
    from . import AutomationStepSkipped, agent_action_event

    service = None
    daily_result = None
    actions: list[AgentActionEvent] = []
    try:
        if not automation.auto_chat_diary:
            raise AutomationStepSkipped()
        service = chat_auto_memory_service(context)
        daily_result = service.append_chat_exchange(
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            assistant_message_id=assistant_message_id,
            agent_run_id=state.agent_run_id,
            user_question=state.user_message,
            assistant_answer=assistant_answer,
        )
        if daily_result.written:
            decision = policy.decide(
                "chat.daily_archive",
                target_paths=[daily_result.entry.markdown_path],
                reversible=False,
            )
            action = record_agent_action(
                context,
                AgentActionCreate(
                    action_type="chat.daily_archive",
                    title="已归档聊天日记",
                    summary=f"写入 {daily_result.entry.markdown_path}",
                    source_agent_run_id=state.agent_run_id,
                    source_conversation_id=state.conversation_id,
                    source_message_id=state.message_id,
                    risk_tier=decision.risk_tier,
                    decision=decision.decision,
                    status="completed",
                    target_paths=(daily_result.entry.markdown_path,),
                    metadata={"entry_id": daily_result.entry.id, "index_job_id": daily_result.index_job_id},
                    reversible=False,
                ),
            )
            actions.append(agent_action_event(state.agent_run_id, action))
    except AutomationStepSkipped:
        pass
    except Exception as exc:
        logger.warning(
            "Chat auto memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    finally:
        if service is not None:
            service.close()
    return daily_result, actions
