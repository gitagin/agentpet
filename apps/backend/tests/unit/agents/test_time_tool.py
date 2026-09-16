from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agents.retrieval.router import _chat_agent_tool_names, _mentions_time_topic
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState
from app.agents.tools import (
    AgentToolName,
    AgentToolSet,
    _system_local_time_payload,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _state(message: str) -> AgentState:
    return AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message=message,
    )


def test_system_local_time_payload_formats_weekday_and_seconds() -> None:
    payload = _system_local_time_payload(datetime(2026, 9, 6, 8, 5, 9, tzinfo=SHANGHAI))

    assert payload.local_time == "2026年9月6日（星期日）08:05:09"
    assert payload.iso == "2026-09-06T08:05:09+08:00"
    assert payload.timezone  # 平台相关（Windows 为「中国标准时间」，POSIX 为 Asia/Shanghai）


def test_get_current_time_tool_returns_payload_without_service_dependencies() -> None:
    tool = AgentToolSet().get_current_time_tool()

    result = tool.invoke({})

    assert result.local_time
    assert result.iso
    assert result.timezone


def test_allowed_tools_includes_time_tool_when_named() -> None:
    tools = AgentToolSet().allowed_tools((AgentToolName.GET_CURRENT_TIME,))

    assert [tool.name for tool in tools] == ["get_current_time"]


@pytest.mark.parametrize(
    "message",
    [
        "现在几点",
        "今天几号",
        "今天星期几",
        "当前时间",
        "现在是什么时间",
        "现在的时间是多久？",
        "几点了",
        "晚上几点下班",
        "What time is it now",
        "today's date",
    ],
)
def test_time_topic_word_covers_common_phrasings(message: str) -> None:
    assert _mentions_time_topic(message)


def test_time_topic_guard_misses_are_harmless_because_tool_is_always_available() -> None:
    # 守卫漏报（如「现在是多久」）没有代价：聊天 agent 恒持有时间工具，
    # 是否调用由模型动态决定；守卫只负责阻断记忆反刍这一条路径。
    assert not _mentions_time_topic("现在是多久")
    names = _chat_agent_tool_names(_state("现在是多久"), AgentRuntimeServices())
    assert AgentToolName.GET_CURRENT_TIME in names


def test_time_topic_guard_does_not_fire_on_plain_chat() -> None:
    assert not _mentions_time_topic("今天心情不错")
    assert not _mentions_time_topic("我喜欢吃苹果")


def test_chat_agent_always_receives_time_tool_regardless_of_phrasing() -> None:
    # 动态方法：不按问法门控，聊天 agent 恒持有时间工具，
    # 是否调用由模型根据对话语义决定。
    for message in ("现在几点", "现在是多久？", "你好", "今天心情不错"):
        names = _chat_agent_tool_names(_state(message), AgentRuntimeServices())
        assert AgentToolName.GET_CURRENT_TIME in names, message


def test_grounding_and_wiki_tools_still_coexist_with_time_tool() -> None:
    names = _chat_agent_tool_names(_state("你记得我的偏好吗"), AgentRuntimeServices())

    assert AgentToolName.SEARCH_MEMORY in names
    assert AgentToolName.GET_CURRENT_TIME in names
