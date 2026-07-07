from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.services.agent_actions import AgentActionCreate, AutomationPolicy
from app.services.chat_answer_wiki_summary import ChatAnswerWikiSummaryService

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


def wiki_service(context: AppContext) -> Any:
    from app.api.wiring import wiki_service as factory

    return factory(context)


def record_agent_action(context: AppContext, payload: AgentActionCreate) -> Any:
    from app.api.wiring import record_agent_action as recorder

    return recorder(context, payload)


def archive_wiki_answer_summary(
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
    from . import agent_action_event, skipped_agent_action_event

    actions: list[AgentActionEvent] = []
    if daily_result is None or not automation.auto_wiki_organize:
        return actions

    try:
        summary_service = ChatAnswerWikiSummaryService(wiki_service(context))
        plan = summary_service.plan(
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            assistant_message_id=assistant_message_id,
            agent_run_id=state.agent_run_id,
            user_question=state.user_message,
            assistant_answer=assistant_answer,
            diary_markdown_path=daily_result.entry.markdown_path,
            memory_date=daily_result.entry.memory_date,
            diary_object_ids=diary_object_ids,
        )
        if plan is None:
            reason = summary_service.skip_reason(
                user_question=state.user_message,
                assistant_answer=assistant_answer,
            )
            actions.append(
                skipped_agent_action_event(
                    context=context,
                    state=state,
                    action_type="wiki.answer_summary.skip",
                    title="已跳过 Wiki 摘要",
                    summary=_wiki_skip_summary(reason),
                    reason=reason,
                    risk_tier="low" if reason in {"low_value_chat", "low_knowledge_score", "no_saveable_content"} else "high",
                )
            )
            return actions
        if plan is not None:
            decision = policy.decide(
                "wiki.answer_summary.write",
                target_paths=[plan.target_path],
                confidence=plan.confidence,
                reversible=True,
            )
            if decision.decision == "ask":
                action = record_agent_action(
                    context,
                    AgentActionCreate(
                        action_type="wiki.answer_summary.write",
                        title="需要确认 Wiki 自动总结",
                        summary=plan.summary,
                        source_agent_run_id=state.agent_run_id,
                        source_conversation_id=state.conversation_id,
                        source_message_id=state.message_id,
                        risk_tier=decision.risk_tier,
                        decision=decision.decision,
                        status="pending_confirmation",
                        target_paths=(plan.target_path,),
                        metadata={"policy_reason": decision.reason, "confidence": plan.confidence},
                        reversible=False,
                    ),
                )
                actions.append(agent_action_event(state.agent_run_id, action))
                return actions
            written = summary_service.write(plan, source_message_id=state.message_id)
            action = record_agent_action(
                context,
                AgentActionCreate(
                    action_type="wiki.answer_summary.write",
                    title="已自动总结到 Wiki",
                    summary=plan.summary,
                    source_agent_run_id=state.agent_run_id,
                    source_conversation_id=state.conversation_id,
                    source_message_id=state.message_id,
                    risk_tier=decision.risk_tier,
                    decision=decision.decision,
                    status="completed",
                    target_paths=(written.page.relative_path,),
                    before_snapshot=written.before_snapshot,
                    after_snapshot=written.after_snapshot,
                    metadata={
                        "confidence": plan.confidence,
                        "index_updated": True,
                        "log_appended": True,
                        "source_paths": list(plan.source_paths),
                    },
                    reversible=True,
                ),
            )
            actions.append(agent_action_event(state.agent_run_id, action))
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning(
            "Post-answer Wiki summary skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    return actions


def _wiki_skip_summary(reason: str) -> str:
    if reason == "sensitive_content":
        return "本轮内容包含敏感信息，因此没有写入 Wiki 摘要。"
    if reason == "low_value_chat":
        return "本轮内容较短或临时性较强，不适合沉淀为长期 Wiki 摘要。"
    if reason == "low_knowledge_score":
        return "本轮回答没有提炼出足够可复用的 Wiki 知识。"
    return "本轮没有生成可保存的 Wiki 摘要内容。"
