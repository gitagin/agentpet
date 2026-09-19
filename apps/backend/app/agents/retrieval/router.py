from __future__ import annotations

import re

from ..services import AgentRuntimeServices
from ..state import AgentState
from ..tools import AgentToolName

# 从 graph_runtime.py 迁移，原函数名：_select_after_memory_retrieval, _chat_agent_tool_names, _automation_enabled


def _chat_agent_tool_names(state: AgentState, services: AgentRuntimeServices) -> tuple[AgentToolName, ...]:
    """Reading never grants write tools; mutations use the action lifecycle."""
    if state.action_plan is not None:
        return ()
    return (AgentToolName.SEARCH_MEMORY, AgentToolName.GET_CURRENT_TIME)


# 时间核心词仅用于「防检索反刍」守卫：命中时不让时间问题流入记忆检索，
# 避免模型引用旧聊天记录里自己编过的错误日期。这个守卫漏报没有代价——
# 真正兜底的是恒可用的 get_current_time 工具和每次刷新的提示词时间锚，
# 所以词表只需要覆盖大多数情况，不需要（也不可能）穷举问法。
_TIME_TOPIC_WORDS = (
    "时间",
    "几点",
    "几号",
    "日期",
    "星期",
    "周几",
    "礼拜",
    "时刻",
    "钟头",
    "点钟",
)


def _mentions_time_topic(message: str) -> bool:
    normalized = message.casefold()
    if any(word in normalized for word in _TIME_TOPIC_WORDS):
        return True
    return bool(
        re.search(
            r"\b(?:what(?:'s)? ?time|what (?:day|date)|current (?:time|date|day)|"
            r"today'?s date|time is it)\b",
            normalized,
        )
    )


def _automation_enabled(services: AgentRuntimeServices, field: str) -> bool:
    settings = getattr(services, "automation_settings", None)
    if settings is None:
        return True
    return bool(getattr(settings, field, True))
