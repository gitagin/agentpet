from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.events import AgentErrorEvent, AgentMemoryProposalEvent, AgentTokenEvent
from app.agents.nodes.memory import _fallback_memory_proposal, _memory_node
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState
from app.agents.tools import AgentToolResult, AgentToolSet
from app.models.api import MemoryProposalActionResponse


def _state(message: str = "记住我喜欢苹果") -> AgentState:
    return AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message=message,
    )


def _graph_state(message: str = "记住我喜欢苹果") -> dict:
    return {"agent_state": _state(message), "events": []}


class MemoryService:
    def __init__(self) -> None:
        self.create_proposal = AsyncMock(
            return_value=MemoryProposalActionResponse(proposal_id="proposal-1", status="pending")
        )


class Registry:
    def __init__(self, model: object = object()) -> None:
        self.model = model

    def get(self, _agent_id):
        return self.model


def _manual_memory_automation():
    return type("Automation", (), {"auto_long_term_memory": False})()


def _has_tool_result(results, name: str) -> bool:
    return any(result.name == name for result in results)


@pytest.mark.asyncio
async def test_memory_node_creates_proposal_on_happy_path() -> None:
    graph_state = _graph_state()
    memory = MemoryService()

    result = await _memory_node(
        graph_state,
        AgentRuntimeServices(memory=memory, automation_settings=_manual_memory_automation()),
        AgentToolSet(memory=memory),
        AsyncMock(),
        _has_tool_result,
    )

    assert result["agent_state"].proposal_id == "proposal-1"
    assert result["agent_state"].response_text == "我已创建一条待确认的记忆提案，请审核后再写入。"
    assert any(isinstance(event, AgentMemoryProposalEvent) for event in result["events"])
    assert any(isinstance(event, AgentTokenEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_memory_node_returns_empty_when_model_returns_empty_result() -> None:
    graph_state = _graph_state()
    run_model_agent_with_tools = AsyncMock(return_value=("", []))
    memory = MemoryService()

    result = await _memory_node(
        graph_state,
        AgentRuntimeServices(memory=memory, model_registry=Registry(), automation_settings=_manual_memory_automation()),
        AgentToolSet(memory=memory),
        run_model_agent_with_tools,
        _has_tool_result,
    )

    assert result["agent_state"].response_text == "我已创建一条待确认的记忆提案，请审核后再写入。"
    assert result["agent_state"].proposal_id == "proposal-1"


@pytest.mark.asyncio
async def test_memory_node_handles_invalid_json_from_model() -> None:
    graph_state = _graph_state()
    response = MemoryProposalActionResponse(proposal_id="proposal-2", status="pending")
    run_model_agent_with_tools = AsyncMock(
        return_value=("{not-json", [AgentToolResult(name="propose_memory", value=response)])
    )

    result = await _memory_node(
        graph_state,
        AgentRuntimeServices(model_registry=Registry(), automation_settings=_manual_memory_automation()),
        AgentToolSet(),
        run_model_agent_with_tools,
        _has_tool_result,
    )

    assert result["agent_state"].response_text == "{not-json"
    assert result["agent_state"].proposal_id == "proposal-2"


@pytest.mark.asyncio
async def test_memory_node_returns_empty_when_model_times_out() -> None:
    graph_state = _graph_state()
    run_model_agent_with_tools = AsyncMock(side_effect=TimeoutError("model timed out"))

    result = await _memory_node(
        graph_state,
        AgentRuntimeServices(model_registry=Registry(), automation_settings=_manual_memory_automation()),
        AgentToolSet(),
        run_model_agent_with_tools,
        _has_tool_result,
    )

    assert result["failed"] is True
    assert result["agent_state"].error_code == "TimeoutError"
    assert any(isinstance(event, AgentErrorEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_memory_node_rejects_sensitive_content() -> None:
    graph_state = _graph_state("记住我的密码是 correct-horse-battery-staple")

    result = await _memory_node(
        graph_state,
        AgentRuntimeServices(),
        AgentToolSet(memory=MemoryService()),
        AsyncMock(),
        _has_tool_result,
    )

    assert result["failed"] is True
    assert result["agent_state"].error_code == "sensitive_memory_rejected"
    assert any(isinstance(event, AgentErrorEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_fallback_memory_proposal_records_service_exception() -> None:
    memory = MemoryService()
    memory.create_proposal.side_effect = RuntimeError("proposal store unavailable")

    with pytest.raises(RuntimeError):
        await _fallback_memory_proposal(AgentRuntimeServices(memory=memory, automation_settings=_manual_memory_automation()), _state())
