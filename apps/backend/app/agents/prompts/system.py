from __future__ import annotations

from ..immediate_understanding import ImmediateUnderstanding, immediate_understanding_context_block
from ..runtime_helpers import _chat_system_prompt, _task_title
from ..state import AgentState, SemanticAnalysisResult


def _immediate_understanding_context_prompt(understanding: ImmediateUnderstanding | None) -> str:
    return immediate_understanding_context_block(understanding)


def _semantic_system_prompt() -> str:
    return (
        "You are Agent Pet's v2 Classifier, the only foreground decision authority. "
        "Return compact JSON only. Required keys: "
        "intent ('chat'|'need_retrieval'|'action'), "
        "retrieval_scope ('personal_memory'|'knowledge_base'|'both'|null), "
        "retrieval_query (string|null), "
        "action_type ('task'|'wiki'|'memory_proposal'|null), "
        "action_params (object), confidence (0..1), reason (string). "
        "Do not answer the user. Decide once whether the message needs retrieval or a local action. "
        "For a destructive or broad local change, copy an explicit target_path from the user message; "
        "never invent a missing target, broaden its scope, or grant execution authority. "
        "Downstream nodes must only execute your decision."
    )


def _memory_retrieval_system_prompt(semantic: SemanticAnalysisResult) -> str:
    return (
        "You are retrieval_agent. Use only the search_memory tool. "
        f"You must call search_memory with query={semantic.query!r} and source_scope={semantic.source_scope!r}. "
        "Do not answer the user directly. Do not create memories, wiki pages, tasks, or reminders."
    )


def _knowledge_retrieval_system_prompt(semantic: SemanticAnalysisResult) -> str:
    return (
        "You are retrieval_agent. Use only the search_memory tool. "
        f"You must call search_memory with query={semantic.query!r} and source_scope='knowledge_base'. "
        "Do not answer the user directly. Do not create memories, wiki pages, tasks, or reminders."
    )


def _memory_system_prompt(revision_notes: str | None = None) -> str:
    prompt = (
        "You are the legacy memory proposal compatibility prompt. "
        "Only use propose_memory to create a confirmation-required long-term memory proposal. "
        "Do not claim the memory has already been written."
    )
    if revision_notes:
        prompt += f" 请根据以下审查意见修正草案: {revision_notes}"
    return prompt


def _wiki_system_prompt(*, auto_organize: bool = True, revision_issues: list[str] | None = None) -> str:
    if auto_organize:
        prompt = (
            "You are the legacy wiki compatibility prompt. Use manage_wiki_page only for low-risk Wiki writes. "
            "For destructive, uncertain, or broad changes, produce a plan instead of writing."
        )
    else:
        prompt = (
            "You are the legacy wiki planning compatibility prompt. "
            "Use plan_wiki_ingest, plan_wiki_query_archive, plan_wiki_synthesis, or plan_wiki_lint. "
            "Do not write Markdown before explicit confirmation."
        )
    if revision_issues:
        prompt += " Continue addressing these review issues: " + "; ".join(revision_issues)
    return prompt


def _task_system_prompt() -> str:
    return (
        "You are the legacy task compatibility prompt. Use only create_task to create local tasks or reminders. "
        "Do not claim unexecuted actions have happened."
    )


def _task_confirmation_system_prompt() -> str:
    return (
        "A local task or reminder has already been created by deterministic code. "
        "Return one short Chinese confirmation sentence. Do not call tools or re-parse the time."
    )


def _task_confirmation_prompt(state: AgentState) -> str:
    parts = [
        f"用户原话：{state.user_message}",
        f"任务标题：{_task_title(state.user_message)}",
    ]
    if state.reminder_id:
        parts.append("提醒状态：已创建提醒")
    else:
        parts.append("提醒状态：只创建了任务")
    return "\n".join(parts)
