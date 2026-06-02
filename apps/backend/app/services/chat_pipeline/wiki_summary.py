import logging
from typing import Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.api.wiring import AppContext, record_agent_action, wiki_service
from app.services.agent_actions import AgentActionCreate, AutomationPolicy
from app.services.chat_answer_wiki_summary import ChatAnswerWikiSummaryService

logger = logging.getLogger(__name__)


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
                    title="Skipped Wiki summary",
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
        logger.warning(
            "Post-answer Wiki summary skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    return actions


def _wiki_skip_summary(reason: str) -> str:
    if reason == "sensitive_content":
        return "Skipped because this turn contained sensitive content; no Wiki summary was written."
    if reason == "low_value_chat":
        return "Skipped because this turn was too short or low-value for a durable Wiki summary."
    if reason == "low_knowledge_score":
        return "Skipped because this answer did not contain enough reusable knowledge for Wiki."
    return "Skipped because this turn did not produce saveable Wiki summary content."
