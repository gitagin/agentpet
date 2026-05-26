from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from app.agents.events import AgentErrorEvent, AgentStatusEvent, AgentTokenEvent
from app.agents.nodes.chat import _chat_node
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState, SemanticAnalysisResult


@dataclass
class ModelResult:
    text: str


class ChatModel:
    def __init__(self, text: str = "模型回复") -> None:
        self.complete_with_tools = AsyncMock(return_value=ModelResult(text=text))


def _graph_state(message: str = "你好") -> dict:
    return {
        "agent_state": AgentState(
            conversation_id="conversation-1",
            message_id="message-1",
            agent_run_id="run-1",
            user_message=message,
        ),
        "events": [],
    }


def _has_empty_search_result(_tool_results) -> bool:
    return False


@pytest.mark.asyncio
async def test_chat_node_returns_model_reply_on_happy_path() -> None:
    graph_state = _graph_state()
    model = ChatModel("你好呀")

    result = await _chat_node(graph_state, AgentRuntimeServices(chat_model=model), _has_empty_search_result)

    state = result["agent_state"]
    assert state.response_text == "你好呀"
    assert any(isinstance(event, AgentStatusEvent) for event in result["events"])
    assert any(isinstance(event, AgentTokenEvent) and event.text == "你好呀" for event in result["events"])
    model.complete_with_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_node_returns_empty_when_model_returns_empty_result() -> None:
    graph_state = _graph_state()

    result = await _chat_node(graph_state, AgentRuntimeServices(chat_model=ChatModel("")), _has_empty_search_result)

    assert result["agent_state"].response_text == ""
    assert any(isinstance(event, AgentTokenEvent) and event.text == "" for event in result["events"])


@pytest.mark.asyncio
async def test_chat_node_handles_invalid_json_from_model() -> None:
    graph_state = _graph_state()

    result = await _chat_node(graph_state, AgentRuntimeServices(chat_model=ChatModel("{not-json")), _has_empty_search_result)

    assert result["agent_state"].response_text == "{not-json"
    assert any(isinstance(event, AgentTokenEvent) and event.text == "{not-json" for event in result["events"])


@pytest.mark.asyncio
async def test_chat_node_returns_empty_when_model_times_out() -> None:
    graph_state = _graph_state()
    model = ChatModel()
    model.complete_with_tools.side_effect = TimeoutError("model timed out")

    result = await _chat_node(graph_state, AgentRuntimeServices(chat_model=model), _has_empty_search_result)

    assert result["failed"] is True
    assert result["agent_state"].error_code == "model_invocation_failed"
    assert any(isinstance(event, AgentErrorEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_chat_node_uses_local_fallback_when_primary_fails_without_model() -> None:
    graph_state = _graph_state()
    graph_state["agent_state"].semantic_analysis = SemanticAnalysisResult(needs_context=True, source_scope="knowledge_base")

    result = await _chat_node(graph_state, AgentRuntimeServices(), _has_empty_search_result)

    assert "暂时没有找到" in result["agent_state"].response_text
    assert any(isinstance(event, AgentTokenEvent) for event in result["events"])
