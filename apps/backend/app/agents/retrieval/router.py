from __future__ import annotations

from ..services import AgentRuntimeServices
from ..state import AgentState
from ..tools import AgentToolName

# 从 graph_runtime.py 迁移，原函数名：_select_after_memory_retrieval, _should_require_grounding, _chat_agent_tool_names, _automation_enabled, _should_offer_wiki_management


def _select_after_memory_retrieval(graph_state: dict[str, object]) -> str:
    plan = graph_state.get("retrieval_plan")
    if isinstance(plan, dict) and plan.get("knowledge"):
        return "knowledge_retrieval_agent"
    return "chat_agent"


def _should_require_grounding(message: str) -> bool:
    normalized = message.casefold()
    markers = (
        "search memory",
        "search memories",
        "find in memory",
        "lookup memory",
        "search notes",
        "search docs",
        "what do you remember",
        "recall",
        "查一下记忆",
        "查一下知识库",
        "搜索记忆",
        "查找记忆",
        "检索记忆",
        "你记得",
        "知识库里",
        "记忆里",
        "记忆中",
        "笔记里",
        "文档里",
        "之前记录",
        "回忆一下",
    )
    return any(marker in normalized for marker in markers)


def _chat_agent_tool_names(state: AgentState, services: AgentRuntimeServices) -> tuple[AgentToolName, ...]:
    names: list[AgentToolName] = []
    if _should_require_grounding(state.user_message) and not state.response_text:
        names.append(AgentToolName.SEARCH_MEMORY)
    if _should_offer_wiki_management(state.user_message) and _automation_enabled(services, "auto_wiki_organize"):
        names.append(AgentToolName.MANAGE_WIKI)
    return tuple(names)


def _automation_enabled(services: AgentRuntimeServices, field: str) -> bool:
    settings = getattr(services, "automation_settings", None)
    if settings is None:
        return True
    return bool(getattr(settings, field, True))


def _should_offer_wiki_management(message: str) -> bool:
    normalized = message.casefold()
    markers = (
        "obsidian note",
        "obsidian page",
        "vault note",
        "vault page",
        "knowledge-base note",
        "knowledge base note",
        "wiki note",
        "wiki page",
        "query archive",
        "archive query",
        "synthesis",
        "synthesize",
        "wiki lint",
        "lint report",
        "turn this into a note",
        "make this a note",
        "整理成笔记",
        "整理成知识库",
        "查询归档",
        "归档回答",
        "综合整理",
        "wiki 检查",
        "检查 wiki",
        "整理到笔记",
        "整理到 vault",
        "整理到vault",
        "转成笔记",
        "变成笔记",
        "obsidian 笔记",
        "vault 笔记",
    )
    return any(marker in normalized for marker in markers)
