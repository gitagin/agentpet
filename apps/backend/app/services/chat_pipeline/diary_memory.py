import logging
from typing import Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.api.wiring import AppContext, diary_memory_service, record_agent_action
from app.services.agent_actions import AgentActionCreate, AutomationPolicy

logger = logging.getLogger(__name__)


async def archive_structured_diary_memory(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    daily_result: Any | None,
    automation,
    policy: AutomationPolicy,
) -> tuple[tuple[str, ...], list[AgentActionEvent]]:
    from . import agent_action_event

    actions: list[AgentActionEvent] = []
    diary_object_ids: tuple[str, ...] = ()
    if daily_result is None or not automation.auto_structured_memory:
        return diary_object_ids, actions

    diary_service = None
    try:
        diary_service = diary_memory_service(context)
        diary_result = await diary_service.archive_chat_exchange(
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            assistant_message_id=assistant_message_id,
            agent_run_id=state.agent_run_id,
            user_question=state.user_message,
            assistant_answer=assistant_answer,
            occurred_at=daily_result.entry.created_at,
            markdown_path=daily_result.entry.markdown_path,
        )
        diary_object_ids = tuple(diary_result.object_ids)
        if diary_result.objects_seen > 0:
            decision = policy.decide(
                "diary.structured_memory",
                reversible=False,
                confidence=0.9,
            )
            action = record_agent_action(
                context,
                AgentActionCreate(
                    action_type="diary.structured_memory",
                    title="已提取结构化日记记忆",
                    summary=f"识别 {diary_result.objects_seen} 条，写入 {diary_result.objects_written} 条。",
                    source_agent_run_id=state.agent_run_id,
                    source_conversation_id=state.conversation_id,
                    source_message_id=state.message_id,
                    risk_tier=decision.risk_tier,
                    decision=decision.decision,
                    status="completed",
                    target_paths=(),
                    metadata={"object_ids": list(diary_result.object_ids)},
                    reversible=False,
                ),
            )
            actions.append(agent_action_event(state.agent_run_id, action))
    except Exception as exc:
        logger.warning(
            "Structured diary memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    finally:
        if diary_service is not None:
            diary_service.close()
    return diary_object_ids, actions
