from __future__ import annotations

from ..runtime_helpers import _chat_system_prompt, _task_title
from ..state import AgentState, SemanticAnalysisResult

# 从 graph_runtime.py 迁移，原函数名：_semantic_system_prompt, _memory_retrieval_system_prompt, _knowledge_retrieval_system_prompt, _memory_system_prompt, _wiki_system_prompt, _task_system_prompt, _task_confirmation_system_prompt, _task_confirmation_prompt, _knowledge_not_found_chat_prompt


def _semantic_system_prompt() -> str:
    return (
        "你是 semantic_analysis_agent，只输出 JSON。"
        "字段：needs_context(boolean), source_scope(one of none,personal_memory,daily_chat,knowledge_base,all), "
        "query(string), answer_style(one of casual,concise,grounded,clarifying), confidence(number), reason(string)。"
        "判断用户是否在询问个人记忆、每日聊天记录或知识库资料；普通闲聊 needs_context=false。"
    )


def _memory_retrieval_system_prompt(semantic: SemanticAnalysisResult) -> str:
    return (
        "You are memory_retrieval_agent. Use only the search_memory tool. "
        f"You must call search_memory with query={semantic.query!r}, "
        f"source_scope={semantic.source_scope!r}. Do not answer the user. "
        "Do not create memories, wiki pages, tasks, or reminders."
    )


def _knowledge_retrieval_system_prompt(semantic: SemanticAnalysisResult) -> str:
    return (
        "You are knowledge_retrieval_agent. Use only the search_memory tool. "
        f"You must call search_memory with query={semantic.query!r}, "
        "source_scope='knowledge_base'. Do not answer the user. "
        "Do not create memories, wiki pages, tasks, or reminders."
    )


def _memory_system_prompt() -> str:
    return (
        "你是 memory_proposal_agent，只能使用 propose_memory 工具创建待确认记忆提案。"
        "不要直接声称已经写入长期记忆。"
    )


def _wiki_system_prompt(*, auto_organize: bool = True) -> str:
    if not auto_organize:
        return (
            "You are wiki_manager_agent. Use plan_wiki_ingest, plan_wiki_query_archive, "
            "plan_wiki_synthesis, or plan_wiki_lint to prepare a confirmation-first review plan. "
            "Do not write Markdown unless a later confirmed apply step is explicitly requested."
        )
    return (
        "You are wiki_manager_agent. Use manage_wiki_page for ordinary Wiki整理, report writes, "
        "or concise page updates. Only ask for confirmation when the action is destructive, "
        "overwrites important content, or the user explicitly asks for a review flow. "
        "Do not claim that the Vault changed unless a tool event confirms it."
    )


def _task_system_prompt() -> str:
    return (
        "你是 task_agent，只能使用 create_task 工具创建本地任务或提醒。"
        "不要暴露其他工具，也不要声称执行了未发生的操作。"
    )


def _task_confirmation_system_prompt() -> str:
    return (
        "你是桌面助手。任务或提醒已经由本地服务创建完成。"
        "只用一句简短中文确认，不要调用工具，不要重新解析时间。"
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


def _knowledge_not_found_chat_prompt() -> str:
    return (
        _chat_system_prompt()
        + "当前检索上下文为空。请用桌宠口吻说明没有翻到相关记忆，不要编造用户记忆；"
        "然后给出一个自然追问或提供按一般经验继续分析的选项。"
    )
