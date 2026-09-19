from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from app.agents.contracts import ActionProposal
from app.agents.events import AgentActionEvent
from app.agents.nodes.policy_guard import evaluate_action_proposal
from app.agents.state import AgentState
from app.services.chat_answer_wiki_summary import ChatAnswerWikiSummaryService

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


def action_lifecycle(context: AppContext) -> Any:
    from app.api.services.adapters import production_action_lifecycle

    return production_action_lifecycle(context)


async def archive_wiki_answer_summary(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    daily_result: Any | None,
    diary_object_ids: tuple[str, ...],
    automation,
    raise_errors: bool = False,
) -> list[AgentActionEvent]:
    if daily_result is None or not automation.auto_wiki_organize:
        return []
    from . import agent_action_event, skipped_agent_action_event

    actions: list[AgentActionEvent] = []
    daily_entry = getattr(daily_result, "entry", None)
    if daily_entry is None:
        return actions
    try:
        summary_service = ChatAnswerWikiSummaryService()
        from app.api.services.factory import chat_model_client

        plan = await summary_service.plan_with_model(
            model=chat_model_client(context),
            conversation_id=state.conversation_id,
            user_message_id=state.message_id,
            assistant_message_id=assistant_message_id,
            agent_run_id=state.agent_run_id,
            user_question=state.user_message,
            assistant_answer=assistant_answer,
            diary_markdown_path=getattr(daily_entry, "markdown_path", None),
            memory_date=getattr(daily_entry, "memory_date", None),
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
        proposal = _wiki_summary_proposal(
            plan=plan,
            state=state,
            assistant_message_id=assistant_message_id,
        )
        decision = evaluate_action_proposal(proposal)
        outcome = await action_lifecycle(context).execute(
            proposal,
            decision,
            source_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
        )
        actions.append(agent_action_event(state.agent_run_id, outcome.action))
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning(
            "Post-answer Wiki summary skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
    return actions


def _wiki_summary_proposal(
    *,
    plan,
    state: AgentState,
    assistant_message_id: str,
) -> ActionProposal:
    intent_ref = f"post-reply:{assistant_message_id}:wiki-summary"
    proposal_hash = hashlib.sha256(f"{intent_ref}:{plan.target_path}".encode("utf-8")).hexdigest()[:24]
    log_details = "\n".join(
        [
            f"- 页面：`{plan.target_path}`",
            f"- 触发消息：`{state.message_id}`",
            f"- 置信度：{plan.confidence:.2f}",
            f"- 来源路径：{len(plan.source_paths)}",
        ]
    )
    return ActionProposal(
        proposal_id=f"proposal-wiki-summary-{proposal_hash}",
        explicit_intent_ref=intent_ref,
        action_type="wiki.answer_summary.write",
        target_ref=plan.target_path,
        parameters={
            "title": plan.title,
            "target_path": plan.target_path,
            "content": plan.content,
            "operation": "replace_section",
            "section": "来源摘要",
            "tags": list(plan.tags),
            "links": list(plan.links),
            "page_type": "report",
            "confidence": "unverified",
            "authors": ["chat_answer_wiki_summary_agent"],
            "sources": list(plan.source_paths),
            "refresh_wiki_index": True,
            "append_wiki_log": True,
            "log_operation": "auto-summary",
            "log_title": plan.title,
            "log_details": log_details,
            "proposal_confidence": plan.confidence,
        },
        expected_effect=plan.summary,
        reversible=True,
        source_message_id=state.message_id,
    )


def _wiki_skip_summary(reason: str) -> str:
    if reason == "sensitive_content":
        return "本轮内容包含敏感信息，因此没有写入 Wiki 摘要。"
    if reason == "low_value_chat":
        return "本轮内容较短或临时性较强，不适合沉淀为长期 Wiki 摘要。"
    if reason == "low_knowledge_score":
        return "本轮回答没有提炼出足够可复用的 Wiki 知识。"
    return "本轮没有生成可保存的 Wiki 摘要内容。"
