from __future__ import annotations

from ..immediate_understanding import ImmediateUnderstanding, immediate_understanding_context_block
from ..runtime_helpers import _chat_system_prompt, _task_title
from ..state import AgentState, SemanticAnalysisResult

# 从 graph_runtime.py 迁移，原函数名：_semantic_system_prompt, _memory_retrieval_system_prompt, _knowledge_retrieval_system_prompt, _memory_system_prompt, _wiki_system_prompt, _task_system_prompt, _task_confirmation_system_prompt, _task_confirmation_prompt, _knowledge_not_found_chat_prompt


def _immediate_understanding_context_prompt(understanding: ImmediateUnderstanding | None) -> str:
    return immediate_understanding_context_block(understanding)


def _semantic_system_prompt() -> str:
    return (
        "你是 semantic_analysis_agent，只输出 JSON。"
        "字段：needs_context(boolean), source_scope(one of none,personal_memory,daily_chat,knowledge_base,all), "
        "query(string), answer_style(one of casual,concise,grounded,clarifying), confidence(number), reason(string)。"
        "判断用户是否在询问个人记忆、每日聊天记录或知识库资料；普通闲聊 needs_context=false。"
    )


def _memory_retrieval_system_prompt(semantic: SemanticAnalysisResult) -> str:
    return (
        "你是 memory_retrieval_agent，只能使用 search_memory 工具。"
        f"必须调用 search_memory，query={semantic.query!r}，"
        f"source_scope={semantic.source_scope!r}。不要直接回答用户。"
        "不要创建记忆、Wiki 页面、任务或提醒。"
    )


def _knowledge_retrieval_system_prompt(semantic: SemanticAnalysisResult) -> str:
    return (
        "你是 knowledge_retrieval_agent，只能使用 search_memory 工具。"
        f"必须调用 search_memory，query={semantic.query!r}，"
        "source_scope='knowledge_base'。不要直接回答用户。"
        "不要创建记忆、Wiki 页面、任务或提醒。"
    )


def _memory_system_prompt(revision_notes: str | None = None) -> str:
    prompt = (
        "你是 memory_proposal_agent，只能使用 propose_memory 工具创建待确认记忆提案。"
        "不要直接声称已经写入长期记忆。"
    )
    if revision_notes:
        prompt += f"请根据以下审查意见修正草案后再创建提案：{revision_notes}"
    return prompt


def _wiki_system_prompt(*, auto_organize: bool = True, revision_issues: list[str] | None = None) -> str:
    if not auto_organize:
        prompt = (
            "你是 wiki_manager_agent。使用 plan_wiki_ingest、plan_wiki_query_archive、"
            "plan_wiki_synthesis 或 plan_wiki_lint 准备确认优先的审查计划。"
            "除非后续明确请求已确认的应用步骤，否则不要写入 Markdown。"
        )
    else:
        prompt = (
            "你是 wiki_manager_agent。普通 Wiki 整理、报告写入或简洁页面更新使用 manage_wiki_page。"
            "只有操作具有破坏性、会覆盖重要内容，或用户明确要求审查流程时，才请求确认。"
            "除非工具事件确认 Vault 已变更，否则不要声称 Vault 已改变。"
        )
    if revision_issues:
        prompt += " Continue addressing these review issues: "
        prompt += " 请逐条处理以下审查问题并修正草案：" + "; ".join(revision_issues)
    return prompt


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
