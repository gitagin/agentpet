from __future__ import annotations

import asyncio

import pytest

from app.agents.agent_runner import run_agent
from app.agents.registry import AgentCapability, AgentRegistry
from app.agents.state import NegotiationState
from app.models.enums import AgentId


def _state() -> NegotiationState:
    return NegotiationState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="帮我总结今天的状态",
        round=2,
    )


def _registry(handler) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(
        AgentCapability(
            agent_id=AgentId.MEMORY_RETRIEVAL_AGENT,
            description="检索用户记忆库。",
            input_schema="搜索关键词字符串。",
            output_schema="相关记忆列表。",
            typical_latency_ms=800,
            can_retry=True,
            max_retries=1,
        ),
        handler,
    )
    return registry


@pytest.mark.asyncio
async def test_run_agent_returns_invocation_result_from_handler_output() -> None:
    async def handler(input_query: str, state: NegotiationState) -> dict:
        await asyncio.sleep(0)
        return {
            "confidence": 0.84,
            "results": [{"title": "状态", "content": "稳定"}],
            "tool_calls": ["search_memory"],
            "input_query": input_query,
            "round": state.round,
        }

    result = await run_agent(AgentId.MEMORY_RETRIEVAL_AGENT, "今天的状态", _state(), _registry(handler))

    assert result.agent_id == AgentId.MEMORY_RETRIEVAL_AGENT
    assert result.round == 2
    assert result.input_query == "今天的状态"
    assert result.output["confidence"] == 0.84
    assert result.output["results"] == [{"title": "状态", "content": "稳定"}]
    assert result.confidence == 0.84
    assert result.latency_ms > 0
    assert result.tool_calls == ["search_memory"]


@pytest.mark.asyncio
async def test_run_agent_wraps_handler_exception() -> None:
    async def handler(input_query: str, state: NegotiationState) -> dict:
        raise RuntimeError("retrieval failed")

    result = await run_agent(AgentId.MEMORY_RETRIEVAL_AGENT, "今天的状态", _state(), _registry(handler))

    assert result.agent_id == AgentId.MEMORY_RETRIEVAL_AGENT
    assert result.round == 2
    assert result.output == {"error": "retrieval failed"}
    assert result.confidence == 0.0
    assert result.latency_ms > 0
    assert result.tool_calls == []
