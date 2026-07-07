from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.services.agent_actions import AgentActionCreate, AutomationPolicy
from app.services.memory_consolidation import MemoryConsolidationResult

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


def memory_consolidation_service(context: AppContext) -> Any:
    from app.api.wiring import memory_consolidation_service as factory

    return factory(context)


def record_agent_action(context: AppContext, payload: AgentActionCreate) -> Any:
    from app.api.wiring import record_agent_action as recorder

    return recorder(context, payload)


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
                    title="已跳过慢记忆整理",
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
                title="已记录慢记忆整理候选",
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
        if raise_errors:
            raise
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
        return "已记录一条不可召回的安全事件，没有写入普通长期记忆或 Vault 文件。"
    return (
        f"已记录 {result.candidate_count} 条慢记忆候选和 "
        f"{result.evidence_count} 条证据记录；没有写入 Vault 长期画像。"
    )


def _skip_summary(reason: str | None) -> str:
    if reason == "no_signal":
        return "本轮没有包含可安全沉淀的慢记忆信号。"
    return "已跳过慢记忆整理，没有写入本地资产。"
