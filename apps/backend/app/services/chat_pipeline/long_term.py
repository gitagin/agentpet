import logging

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.api.wiring import AppContext, long_term_memory_service, record_agent_action
from app.services.agent_actions import AgentActionCreate, AutomationPolicy

logger = logging.getLogger(__name__)


def archive_long_term_memory(
    *,
    context: AppContext,
    state: AgentState,
    automation,
    policy: AutomationPolicy,
) -> list[AgentActionEvent]:
    from . import AutomationStepSkipped, agent_action_event

    long_term_service = None
    actions: list[AgentActionEvent] = []
    try:
        if not automation.auto_long_term_memory:
            raise AutomationStepSkipped()
        long_term_service = long_term_memory_service(context)
        long_term_result = long_term_service.remember_from_user_message(
            state.user_message,
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            agent_run_id=state.agent_run_id,
        )
        if long_term_result.written or long_term_result.graph_fact_id:
            decision = policy.decide(
                "memory.long_term.write",
                target_paths=[long_term_result.target_path] if long_term_result.target_path else [],
                reversible=False,
            )
            action = record_agent_action(
                context,
                AgentActionCreate(
                    action_type="memory.long_term.write",
                    title="已更新长期记忆",
                    summary=long_term_result.target_path or long_term_result.reason or "已整理为结构化长期记忆。",
                    source_agent_run_id=state.agent_run_id,
                    source_conversation_id=state.conversation_id,
                    source_message_id=state.message_id,
                    risk_tier=decision.risk_tier,
                    decision=decision.decision,
                    status="completed",
                    target_paths=tuple([long_term_result.target_path] if long_term_result.target_path else []),
                    metadata={
                        "graph_fact_id": long_term_result.graph_fact_id,
                        "graph_status": long_term_result.graph_status,
                        "reason": long_term_result.reason,
                    },
                    reversible=False,
                ),
            )
            actions.append(agent_action_event(state.agent_run_id, action))
    except AutomationStepSkipped:
        pass
    except Exception as exc:
        logger.warning(
            "Long-term memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    finally:
        if long_term_service is not None and hasattr(long_term_service, "close"):
            long_term_service.close()
    return actions
