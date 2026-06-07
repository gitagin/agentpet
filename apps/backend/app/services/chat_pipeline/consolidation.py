import logging
from typing import Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.api.wiring import AppContext, memory_consolidation_service, record_agent_action
from app.services.agent_actions import AgentActionCreate, AutomationPolicy
from app.services.memory_consolidation import MemoryConsolidationResult

logger = logging.getLogger(__name__)


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
) -> list[AgentActionEvent]:
    from . import AutomationStepSkipped, agent_action_event, skipped_agent_action_event

    service = None
    actions: list[AgentActionEvent] = []
    try:
        if not automation.auto_long_term_memory:
            raise AutomationStepSkipped()
        service = memory_consolidation_service(context)
        result = service.consolidate(
            user_message=state.user_message,
            assistant_answer=assistant_answer,
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            assistant_message_id=assistant_message_id,
            agent_run_id=state.agent_run_id,
            diary_object_ids=diary_object_ids,
            diary_markdown_path=getattr(getattr(daily_result, "entry", None), "markdown_path", None),
        )
        if result.candidate_count == 0:
            actions.append(
                skipped_agent_action_event(
                    context=context,
                    state=state,
                    action_type="memory.consolidation.skip",
                    title="Skipped slow memory consolidation",
                    summary=_skip_summary(result.skipped_reason),
                    reason=result.skipped_reason or "no_signal",
                    risk_tier="low",
                )
            )
            return actions

        action_type = "memory.consolidation.safety_event" if result.rejected_count else "memory.consolidation.candidate"
        decision = policy.decide(action_type, reversible=False)
        risk_tier = "high" if result.rejected_count else decision.risk_tier
        decision_value = "notify" if result.rejected_count else decision.decision
        action = record_agent_action(
            context,
            AgentActionCreate(
                action_type=action_type,
                title="Recorded slow memory consolidation candidates",
                summary=_result_summary(result),
                source_agent_run_id=state.agent_run_id,
                source_conversation_id=state.conversation_id,
                source_message_id=state.message_id,
                risk_tier=risk_tier,  # type: ignore[arg-type]
                decision=decision_value,  # type: ignore[arg-type]
                status="completed",
                metadata={
                    "candidate_ids": [item.candidate.id for item in result.items],
                    "candidate_count": result.candidate_count,
                    "evidence_count": result.evidence_count,
                    "rejected_count": result.rejected_count,
                    "highest_risk_tier": result.highest_risk_tier.value,
                    "kinds": sorted({item.candidate.memory_kind.value for item in result.items}),
                    "statuses": sorted({item.candidate.status.value for item in result.items}),
                },
                reversible=False,
            ),
        )
        actions.append(agent_action_event(state.agent_run_id, action))
    except AutomationStepSkipped:
        pass
    except Exception as exc:
        logger.warning(
            "Slow memory consolidation skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    finally:
        if service is not None:
            service.close()
    return actions


def _result_summary(result: MemoryConsolidationResult) -> str:
    if result.rejected_count:
        return "Recorded a non-recallable safety event; no ordinary long-term memory or Vault file was written."
    return (
        f"Recorded {result.candidate_count} slow-memory candidate(s) with "
        f"{result.evidence_count} evidence record(s); no Vault long-term profile was written."
    )


def _skip_summary(reason: str | None) -> str:
    if reason == "no_signal":
        return "Skipped because this turn did not contain a safe slow-memory signal."
    return "Skipped slow memory consolidation; no local asset was written."
