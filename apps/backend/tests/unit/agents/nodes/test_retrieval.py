from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.events import AgentCitationEvent, AgentErrorEvent, AgentStatusEvent
from app.agents.nodes.retrieval import (
    _fallback_daily_chat_context,
    _fallback_scoped_retrieval,
    _knowledge_retrieval_node,
    _memory_retrieval_node,
)
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState, SemanticAnalysisResult
from app.agents.tools import AgentToolResult
from app.models.api import MemorySearchResponse, MemorySearchResult


def _citation(scope: str = "personal_memory") -> MemorySearchResult:
    return MemorySearchResult(
        note_id="note-1",
        chunk_id="chunk-1",
        relative_path="Memories/Test.md",
        title="Test",
        snippet="用户喜欢苹果。",
        score=0.9,
        source_scope=scope,
    )


def _search_response(results: list[MemorySearchResult] | None = None) -> MemorySearchResponse:
    return MemorySearchResponse(results=results if results is not None else [_citation()])


def _state() -> AgentState:
    return AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="查一下我喜欢什么",
        semantic_analysis=SemanticAnalysisResult(needs_context=True, source_scope="personal_memory", query="喜欢"),
    )


def _graph_state() -> dict:
    return {"agent_state": _state(), "events": []}


class Retrieval:
    def __init__(self, response: MemorySearchResponse | None = None) -> None:
        self.search = AsyncMock(return_value=response or _search_response())


class Registry:
    def __init__(self, model: object = object()) -> None:
        self.model = model

    def get(self, _agent_id):
        return self.model


def _has_tool_result(results, name: str) -> bool:
    return any(result.name == name for result in results)


def _has_empty_search_result(results) -> bool:
    return any(result.name == "search_memory" and not result.value.results for result in results)


@pytest.mark.asyncio
async def test_memory_retrieval_node_returns_happy_path_citation() -> None:
    graph_state = _graph_state()
    services = AgentRuntimeServices(retrieval=Retrieval())

    result = await _memory_retrieval_node(
        graph_state,
        services,
        AsyncMock(),
        _has_tool_result,
        _has_empty_search_result,
    )

    assert result["agent_state"].citations[0].snippet == "用户喜欢苹果。"
    assert any(isinstance(event, AgentCitationEvent) for event in result["events"])
    assert any(isinstance(event, AgentStatusEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_memory_retrieval_node_returns_empty_when_model_returns_empty_result() -> None:
    graph_state = _graph_state()
    services = AgentRuntimeServices(retrieval=Retrieval(_search_response([])))

    result = await _memory_retrieval_node(
        graph_state,
        services,
        AsyncMock(),
        _has_tool_result,
        _has_empty_search_result,
    )

    assert result["agent_state"].citations == []
    assert result["agent_state"].response_text == ""


@pytest.mark.asyncio
async def test_knowledge_retrieval_node_handles_invalid_json_from_model() -> None:
    graph_state = _graph_state()
    graph_state["agent_state"].semantic_analysis = SemanticAnalysisResult(
        needs_context=True,
        source_scope="knowledge_base",
        query="项目文档",
    )
    run_model_agent_with_tools = AsyncMock(return_value=("{not-json", []))

    result = await _knowledge_retrieval_node(
        graph_state,
        AgentRuntimeServices(model_registry=Registry()),
        run_model_agent_with_tools,
        _has_tool_result,
        _has_empty_search_result,
    )

    assert result["agent_state"].response_text == ""
    assert not result["agent_state"].citations
    run_model_agent_with_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_retrieval_node_returns_empty_when_model_times_out() -> None:
    graph_state = _graph_state()
    retrieval = Retrieval()
    retrieval.search.side_effect = TimeoutError("retrieval timed out")

    result = await _memory_retrieval_node(
        graph_state,
        AgentRuntimeServices(retrieval=retrieval),
        AsyncMock(),
        _has_tool_result,
        _has_empty_search_result,
    )

    assert result["agent_state"].citations == []
    assert result["agent_state"].response_text == ""


@pytest.mark.asyncio
async def test_fallback_scoped_retrieval_handles_search_exception() -> None:
    retrieval = Retrieval()
    retrieval.search.side_effect = RuntimeError("database unavailable")

    response, tool_results = await _fallback_scoped_retrieval(
        AgentRuntimeServices(retrieval=retrieval),
        _state(),
        SemanticAnalysisResult(needs_context=True, source_scope="personal_memory", query="喜欢"),
    )

    assert response == ""
    assert tool_results == []


@pytest.mark.asyncio
async def test_fallback_daily_chat_context_records_error_as_empty_result() -> None:
    retrieval = Retrieval()
    retrieval.search.side_effect = RuntimeError("database unavailable")
    state = _state()

    results = await _fallback_daily_chat_context(
        AgentRuntimeServices(retrieval=retrieval),
        state,
        SemanticAnalysisResult(needs_context=True, source_scope="personal_memory", query="喜欢"),
    )

    assert results == []
    assert state.semantic_analysis.source_scope == "personal_memory"


@pytest.mark.asyncio
async def test_knowledge_retrieval_node_records_exception_when_model_fails() -> None:
    graph_state = _graph_state()
    run_model_agent_with_tools = AsyncMock(side_effect=ValueError("bad model output"))

    result = await _knowledge_retrieval_node(
        graph_state,
        AgentRuntimeServices(model_registry=Registry()),
        run_model_agent_with_tools,
        _has_tool_result,
        _has_empty_search_result,
    )

    assert result["failed"] is True
    assert result["agent_state"].error_code == "ValueError"
    assert any(isinstance(event, AgentErrorEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_knowledge_retrieval_node_emits_model_tool_result() -> None:
    graph_state = _graph_state()
    response = _search_response([_citation("knowledge_base")])
    run_model_agent_with_tools = AsyncMock(
        return_value=("", [AgentToolResult(name="search_memory", value=response)])
    )

    result = await _knowledge_retrieval_node(
        graph_state,
        AgentRuntimeServices(model_registry=Registry()),
        run_model_agent_with_tools,
        _has_tool_result,
        _has_empty_search_result,
    )

    assert result["agent_state"].citations[0].source_scope == "knowledge_base"
    assert result["agent_state"].response_text == ""
