from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.services.agent_actions import AgentActionCreate
from tests.agent_runtime_fakes import FakeChatModel, assert_langgraph_events, make_state

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime


class NegotiationChatModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if "action" in user_message:
            return json.dumps(
                {
                    "action": "synthesize",
                    "agent": None,
                    "agent_input": None,
                    "reasoning": "已有信息足够。",
                    "confidence": 0.95,
                    "expected_outcome": "直接回复用户。",
                },
                ensure_ascii=False,
            )
        return "协商回复"


class LoopingNegotiationChatModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if "action" in user_message:
            return json.dumps(
                {
                    "action": "invoke_agent",
                    "agent": "memory_retrieval_agent",
                    "agent_input": "Ada",
                    "reasoning": "需要更多记忆上下文。",
                    "confidence": 0.1,
                    "expected_outcome": "找到相关记忆。",
                },
                ensure_ascii=False,
            )
        return "达到轮次上限后的回复"


def test_langgraph_runtime_uses_legacy_graph_when_negotiation_disabled() -> None:
    async def run_case():
        chat_model = FakeChatModel("旧图回复")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=chat_model, automation_settings=SimpleNamespace(use_negotiation=False))
        )

        events = [event async for event in runtime.run(make_state("你好"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert len(chat_model.calls) == 1
    assert "action" not in chat_model.calls[0][0]
    assert_langgraph_events(events, ["token", "done"])


def test_negotiation_fast_path_bypasses_orchestrator_for_confident_chat() -> None:
    async def run_case():
        chat_model = FakeChatModel("fast path 回复")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=chat_model, automation_settings=SimpleNamespace(use_negotiation=True))
        )

        events = [event async for event in runtime.run(make_state("你好"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert len(chat_model.calls) == 1
    assert "action" not in chat_model.calls[0][0]
    assert_langgraph_events(events, ["token", "done"])


def test_negotiation_calls_orchestrator_for_non_fast_path() -> None:
    recorded_actions: list[AgentActionCreate] = []

    async def run_case():
        chat_model = NegotiationChatModel()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=True),
                agent_action_recorder=recorded_actions.append,
            )
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert any(call[1] == "orchestrator-json-only" for call in chat_model.calls)
    assert_langgraph_events(events, ["negotiation_step", "token", "negotiation_done", "done"])
    step = next(event for event in events if event.event == "negotiation_step")
    done = next(event for event in events if event.event == "negotiation_done")
    assert step.action == "synthesizing"
    assert step.confidence == 0.95
    assert done.total_rounds == 0
    assert done.final_confidence == 0.95
    assert recorded_actions[0].action_type == "agent.negotiation"
    assert recorded_actions[0].negotiation_rounds == 0
    assert recorded_actions[0].total_latency_ms == 0
    assert recorded_actions[0].metadata["fallback"] is False


def test_negotiation_orchestrator_stops_at_max_rounds() -> None:
    recorded_actions: list[AgentActionCreate] = []

    async def run_case():
        chat_model = LoopingNegotiationChatModel()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=True, max_rounds=2),
                agent_action_recorder=recorded_actions.append,
            )
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    orchestrator_calls = [call for call in chat_model.calls if call[1] == "orchestrator-json-only"]
    assert len(orchestrator_calls) == 2
    assert_langgraph_events(
        events,
        ["negotiation_step", "negotiation_step", "negotiation_step", "token", "negotiation_done", "done"],
    )
    done = next(event for event in events if event.event == "negotiation_done")
    assert done.total_rounds == 2
    assert done.agents_invoked == ["memory_retrieval_agent", "memory_retrieval_agent"]
    assert done.fallback is True
    assert recorded_actions[0].negotiation_rounds == 2
    assert recorded_actions[0].metadata["agents_invoked"] == ["memory_retrieval_agent", "memory_retrieval_agent"]
    assert recorded_actions[0].metadata["fallback"] is True
