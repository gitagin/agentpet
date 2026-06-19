from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.agents.nodes.orchestrator import OrchestratorNode
from app.agents.registry import default_agent_registry
from app.agents.state import AgentInvocationResult, NegotiationState
from app.models.enums import AgentId


@dataclass
class ModelResult:
    text: str


class JsonModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> ModelResult:
        self.prompts.append(prompt)
        return ModelResult(text=json.dumps(self.payload))


def _state(**kwargs) -> NegotiationState:
    defaults = {
        "conversation_id": "conversation-1",
        "message_id": "message-1",
        "agent_run_id": "run-1",
        "user_message": "帮我总结今天的状态",
    }
    defaults.update(kwargs)
    return NegotiationState(**defaults)


@pytest.mark.asyncio
async def test_orchestrator_synthesizes_when_confidence_is_high() -> None:
    model = JsonModel(
        {
            "action": "synthesize",
            "agent": None,
            "agent_input": None,
            "reasoning": "已有信息足够回复用户。",
            "confidence": 0.9,
            "expected_outcome": "生成最终回复。",
        }
    )
    node = OrchestratorNode(model, default_agent_registry)

    result = await node(_state(collected_context="用户今天状态稳定。"))

    assert result["next"] == "synthesize"
    assert result["orchestrator_decisions"][0]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_orchestrator_invokes_agent_when_confidence_is_low() -> None:
    model = JsonModel(
        {
            "action": "invoke_agent",
            "agent": AgentId.RETRIEVAL_AGENT.value,
            "agent_input": "今天的状态",
            "reasoning": "需要检索长期记忆补充上下文。",
            "confidence": 0.4,
            "expected_outcome": "获得与今天状态相关的记忆。",
        }
    )
    node = OrchestratorNode(model, default_agent_registry)

    result = await node(_state())

    assert result["next"] == "invoke_agent"
    assert result["next_agent"] == AgentId.RETRIEVAL_AGENT
    assert result["agent_input"] == "今天的状态"
    assert result["orchestrator_decisions"][0]["agent"] == AgentId.RETRIEVAL_AGENT.value


@pytest.mark.asyncio
async def test_orchestrator_falls_back_when_max_rounds_reached() -> None:
    model = JsonModel(
        {
            "action": "invoke_agent",
            "agent": AgentId.RETRIEVAL_AGENT.value,
            "agent_input": "今天的状态",
            "reasoning": "需要更多信息。",
            "confidence": 0.2,
            "expected_outcome": "补充上下文。",
        }
    )
    node = OrchestratorNode(model, default_agent_registry, max_rounds=5)

    result = await node(_state(round=5))

    assert result == {"next": "synthesize", "fallback_triggered": True}
    assert model.prompts == []


def test_build_prompt_contains_agent_names_and_context() -> None:
    model = JsonModel({})
    node = OrchestratorNode(model, default_agent_registry)
    state = _state(
        collected_context="已检索到近期状态记录。",
        invocation_history=[
            AgentInvocationResult(
                agent_id=AgentId.RETRIEVAL_AGENT.value,
                round=1,
                input_query="今天的状态",
                output={"summary": "状态稳定"},
                confidence=0.72,
                latency_ms=120,
                tool_calls=["search_memory"],
            )
        ],
    )

    prompt = node._build_prompt(state)

    assert "帮我总结今天的状态" in prompt
    assert "已检索到近期状态记录。" in prompt
    assert AgentId.RETRIEVAL_AGENT.value in prompt
    for agent_id in {
        AgentId.CHAT_AGENT,
        AgentId.SEMANTIC_ANALYSIS_AGENT,
        AgentId.RETRIEVAL_AGENT,
        AgentId.ACTION_AGENT,
        AgentId.REFLECTION_AGENT,
    }:
        assert f"## {agent_id.value}" in prompt
