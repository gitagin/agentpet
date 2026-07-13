from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from app.agents.events import AgentErrorEvent, AgentStatusEvent, AgentTokenEvent
from app.agents.nodes.chat import _chat_node, _grounded_response_from_citations, _message_with_citation_context
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState, SemanticAnalysisResult
from app.models.api import MemoryRecallPermissions, MemorySearchResult


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


def _memory_result(
    *,
    snippet: str = "Ada prefers concise status updates.",
    source_scope: str = "personal_memory",
) -> MemorySearchResult:
    return MemorySearchResult(
        note_id="note-1",
        chunk_id="chunk-1",
        relative_path="People/Ada.md",
        title="Ada",
        heading="Preferences",
        snippet=snippet,
        score=0.9,
        source_scope=source_scope,
        recall_permissions=MemoryRecallPermissions(can_answer_context=True),
    )


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


@pytest.mark.asyncio
async def test_chat_node_does_not_call_model_when_required_evidence_is_empty() -> None:
    graph_state = _graph_state("你记得我的偏好吗？")
    graph_state["agent_state"].semantic_analysis = SemanticAnalysisResult(
        needs_context=True,
        source_scope="personal_memory",
    )
    model = ChatModel("不应使用的模型回复")

    result = await _chat_node(graph_state, AgentRuntimeServices(chat_model=model), _has_empty_search_result)

    assert "没有找到能引用的记录" in result["agent_state"].response_text
    model.complete_with_tools.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_node_preserves_deterministic_action_response_without_model_call() -> None:
    graph_state = _graph_state("明天下午提醒我回邮件，并记住我喜欢下午开会。")
    graph_state["deterministic_action_response"] = True
    graph_state["agent_state"].response_text = "已创建提醒；记忆已进入本地整理流程。"
    model = ChatModel("不应覆盖安全回执")

    result = await _chat_node(graph_state, AgentRuntimeServices(chat_model=model), _has_empty_search_result)

    assert result["agent_state"].response_text == "已创建提醒；记忆已进入本地整理流程。"
    model.complete_with_tools.assert_not_awaited()


def test_grounded_fallback_does_not_echo_raw_memory_snippets() -> None:
    response = _grounded_response_from_citations(
        [
            _memory_result(
                snippet="Ada prefers concise status updates. conversation_id=conversation-1"
            )
        ]
    )

    assert "相关线索" in response
    assert "原始记录" in response
    assert "Ada prefers concise status updates." not in response
    assert "conversation_id" not in response


def test_message_with_citation_context_instructs_natural_recall_not_raw_echo() -> None:
    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="What do you remember about Ada?",
        citations=[_memory_result()],
    )

    prompt = _message_with_citation_context(state)

    assert "只在记忆能直接帮助当前问题时自然带入" in prompt
    assert "不要为了证明检索到了而提及路径、状态、分数或原文" in prompt
    assert "避免逐字复述" in prompt
    assert "Ada prefers concise status updates." in prompt
