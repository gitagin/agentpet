from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.agents.events import sse_encode
from app.models.event_payloads import AgentTraceReasonCode
from app.models.enums import AgentId
from app.services.agent_actions import AgentActionCreate
from app.services.chat_model import AgentModelRegistry, ChatModelError
from tests.agent_runtime_fakes import (
    FakeChatModel,
    FakeMemory,
    FakeRegistryChatModel,
    FakeRetrieval,
    FakeTasks,
    assert_langgraph_events,
    make_state,
)


class NegotiationChatModel:
    def __init__(
        self,
        *,
        orchestrator_mode: str = "synthesize",
        orchestrator_reasoning: str = "根据当前证据决定下一步。",
    ) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.orchestrator_mode = orchestrator_mode
        self.orchestrator_reasoning = orchestrator_reasoning
        self.orchestrator_call_count = 0

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if system_prompt == "orchestrator-json-only":
            self.orchestrator_call_count += 1
            if self.orchestrator_mode == "malformed":
                return "not-json"
            if self.orchestrator_mode == "duplicate":
                return _decision(
                    agent_input="Ada",
                    confidence=0.1,
                    reasoning=self.orchestrator_reasoning,
                )
            if self.orchestrator_mode == "loop":
                return _decision(
                    agent_input=f"Ada followup {self.orchestrator_call_count}",
                    confidence=0.1,
                    reasoning=self.orchestrator_reasoning,
                )
            return _decision(
                action="synthesize",
                agent=None,
                agent_input=None,
                confidence=0.95,
                reasoning=self.orchestrator_reasoning,
            )
        return "协商后的本地证据回复"


class SlowOrchestratorChatModel(NegotiationChatModel):
    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if system_prompt == "orchestrator-json-only":
            await asyncio.sleep(1)
        return "协调超时后的稳定回复"


class FailingSynthesisChatModel(NegotiationChatModel):
    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if system_prompt == "orchestrator-json-only":
            return _decision(action="synthesize", agent=None, agent_input=None, confidence=0.95)
        raise RuntimeError("synthesis failed")


class ProviderFailingOrchestratorChatModel(NegotiationChatModel):
    def __init__(self, code: str) -> None:
        super().__init__()
        self.code = code

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if system_prompt == "orchestrator-json-only":
            raise ChatModelError(
                "Traceback: raw_prompt tool_arguments C:\\Users\\Alice\\Vault\\Secret.md",
                code=self.code,
            )
        return "不应生成的回复"


class SlowRetrievalRuntime(LangGraphAgentRuntime):
    def _agent_handler_for(self, agent_id):
        if agent_id == AgentId.RETRIEVAL_AGENT:
            async def slow_handler(input_query, state):
                await asyncio.sleep(1)
                return {"result": input_query, "confidence": 0.0}

            return slow_handler
        return super()._agent_handler_for(agent_id)


class CountingSemanticModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        return json.dumps(
            {
                "intent": "need_retrieval",
                "retrieval_scope": "personal_memory",
                "retrieval_query": "上午 下午 开会 偏好",
                "action_type": None,
                "action_params": {},
                "confidence": 0.94,
                "reason": "用户在询问过去表达过的会议时间偏好。",
            },
            ensure_ascii=False,
        )


def _decision(
    *,
    action: str = "invoke_agent",
    agent: str | None = AgentId.RETRIEVAL_AGENT.value,
    agent_input: str | None = "Ada",
    confidence: float = 0.1,
    reasoning: str = "根据当前证据决定下一步。",
) -> str:
    return json.dumps(
        {
            "action": action,
            "agent": agent,
            "agent_input": agent_input,
            "reasoning": reasoning,
            "confidence": confidence,
            "expected_outcome": "获得足够证据后回复。",
        },
        ensure_ascii=False,
    )


def _event_names(events) -> list[str]:
    return [event.event for event in events]


def _assert_successful_negotiation(events) -> None:
    names = _event_names(events)
    assert names[-1] == "done"
    assert "negotiation_done" in names
    assert names.index("negotiation_done") < len(names) - 1
    assert sum(name in {"done", "error"} for name in names) == 1


def _trace_payload(event) -> dict[str, object]:
    encoded = sse_encode(event)
    return json.loads(encoded.split("data: ", 1)[1])


def test_langgraph_runtime_uses_stable_graph_when_negotiation_disabled() -> None:
    async def run_case():
        chat_model = FakeChatModel("普通图回复")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=chat_model, automation_settings=SimpleNamespace(use_negotiation=False))
        )
        return chat_model, [event async for event in runtime.run(make_state("你好"))]

    chat_model, events = asyncio.run(run_case())

    assert len(chat_model.calls) == 1
    assert "action" not in chat_model.calls[0][0]
    assert_langgraph_events(events, ["token", "done"])


def test_negotiation_switch_keeps_confident_plain_chat_on_fast_path() -> None:
    async def run_case():
        chat_model = FakeChatModel("fast path 回复")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=chat_model, automation_settings=SimpleNamespace(use_negotiation=True))
        )
        return chat_model, [event async for event in runtime.run(make_state("你好"))]

    chat_model, events = asyncio.run(run_case())

    assert len(chat_model.calls) == 1
    assert not any(call[1] == "orchestrator-json-only" for call in chat_model.calls)
    assert_langgraph_events(events, ["token", "done"])


def test_negotiation_switch_keeps_compound_action_on_deterministic_graph() -> None:
    prompt = "明天下午三点提醒我给张老师回邮件，并记住我更喜欢下午开会。"

    async def run_case():
        chat_model = NegotiationChatModel()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=FakeMemory(),
                tasks=FakeTasks(),
                chat_model=chat_model,
                automation_settings=SimpleNamespace(
                    use_negotiation=True,
                    auto_long_term_memory=False,
                ),
            )
        )
        return chat_model, [event async for event in runtime.run(make_state(prompt))]

    chat_model, events = asyncio.run(run_case())
    names = _event_names(events)

    assert "negotiation_step" not in names
    assert "negotiation_done" not in names
    assert "task" in names
    assert "memory_proposal" in names
    assert chat_model.calls == []
    assert "同时处理两件事" in next(event.text for event in events if event.event == "token")


def test_negotiation_memory_path_emits_citation_steps_done_and_stats() -> None:
    recorded_actions: list[AgentActionCreate] = []

    async def run_case():
        chat_model = NegotiationChatModel()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=True, max_rounds=10),
                agent_action_recorder=recorded_actions.append,
            )
        )
        return chat_model, [event async for event in runtime.run(make_state("search memory for Ada"))]

    chat_model, events = asyncio.run(run_case())
    names = _event_names(events)

    assert chat_model.orchestrator_call_count == 1
    assert "citation" in names
    assert names.count("negotiation_step") >= 2
    _assert_successful_negotiation(events)
    negotiation_done = next(event for event in events if event.event == "negotiation_done")
    assert negotiation_done.counts.rounds == 1
    assert negotiation_done.counts.agents_invoked == 1
    assert negotiation_done.reason_code == AgentTraceReasonCode.NEGOTIATION_COMPLETED
    assert recorded_actions[-1].action_type == "agent.negotiation"
    assert recorded_actions[-1].negotiation_rounds == 1


def test_public_trace_is_versioned_allowlisted_and_drops_model_reasoning() -> None:
    credential = "s" + "k-" + "trace-secret"
    unsafe_reasoning = " | ".join(
        [
            "private-user-sentinel",
            "Authorization: " + "Bearer " + credential,
            r"C:\Users\Alice\Vault\Secret.md",
            "/home/alice/vault/Secret.md",
            "raw_prompt=hidden",
            "tool_arguments={'query': 'hidden'}",
            "Traceback (most recent call last):",
        ]
    )

    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                chat_model=NegotiationChatModel(orchestrator_reasoning=unsafe_reasoning),
                automation_settings=SimpleNamespace(use_negotiation=True),
            )
        )
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())
    trace_events = [event for event in events if event.event in {"negotiation_step", "negotiation_done"}]
    payloads = [_trace_payload(event) for event in trace_events]
    encoded_trace = json.dumps(payloads, ensure_ascii=False)
    allowed_fields = {
        "contract_version",
        "run_id",
        "branch_id",
        "stage_id",
        "agent_id",
        "phase",
        "status",
        "round",
        "sequence",
        "duration_ms",
        "reason_code",
        "safe_summary",
        "counts",
        "source_scope",
    }

    assert trace_events
    assert all(set(payload) == allowed_fields for payload in payloads)
    assert all(payload["contract_version"] == "agent-trace.v1" for payload in payloads)
    assert [payload["sequence"] for payload in payloads] == list(range(1, len(payloads) + 1))
    assert unsafe_reasoning not in encoded_trace
    for forbidden in (
        "private-user-sentinel",
        credential,
        r"C:\Users\Alice",
        "/home/alice",
        "raw_prompt",
        "tool_arguments",
        "Traceback",
    ):
        assert forbidden not in encoded_trace


def test_golden_memory_question_runs_one_semantic_pass_and_one_event_sequence() -> None:
    prompt = "我之前提过更喜欢上午还是下午开会？顺便告诉我这个结论来自哪条记录。"

    async def run_case():
        semantic_model = CountingSemanticModel()
        retrieval_model = FakeRegistryChatModel("search_memory", "retrieval complete")
        chat_model = NegotiationChatModel()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                model_registry=AgentModelRegistry(
                    {
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.RETRIEVAL_AGENT: retrieval_model,
                        AgentId.CHAT_AGENT: chat_model,
                    }
                ),
                automation_settings=SimpleNamespace(use_negotiation=True),
            )
        )
        events = [event async for event in runtime.run(make_state(prompt))]
        return semantic_model, events

    semantic_model, events = asyncio.run(run_case())
    semantic_statuses = [
        event
        for event in events
        if event.event == "status" and event.stage == "semantic_analysis"
    ]

    assert len(semantic_model.calls) == 1
    assert len(semantic_statuses) == 1
    assert sum(event.event == "citation" for event in events) == 1
    _assert_successful_negotiation(events)


def test_negotiation_hard_stops_after_two_agent_invocations() -> None:
    async def run_case():
        chat_model = NegotiationChatModel(orchestrator_mode="loop")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=True, max_rounds=10),
            )
        )
        return chat_model, [event async for event in runtime.run(make_state("search memory for Ada"))]

    chat_model, events = asyncio.run(run_case())
    done = next(event for event in events if event.event == "negotiation_done")

    assert chat_model.orchestrator_call_count == 1
    assert done.counts.rounds == 2
    assert done.counts.agents_invoked == 2
    assert done.reason_code == AgentTraceReasonCode.NEGOTIATION_COMPLETED_WITH_FALLBACK
    _assert_successful_negotiation(events)


def test_negotiation_blocks_duplicate_agent_query() -> None:
    async def run_case():
        chat_model = NegotiationChatModel(orchestrator_mode="duplicate")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=True),
            )
        )
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())
    done = next(event for event in events if event.event == "negotiation_done")

    assert done.counts.rounds == 1
    assert done.reason_code == AgentTraceReasonCode.NEGOTIATION_COMPLETED_WITH_FALLBACK
    assert any(
        event.event == "negotiation_step"
        and event.reason_code == AgentTraceReasonCode.DUPLICATE_AGENT_QUERY
        for event in events
    )


def test_malformed_orchestrator_response_falls_back_to_stable_synthesis() -> None:
    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                chat_model=NegotiationChatModel(orchestrator_mode="malformed"),
                automation_settings=SimpleNamespace(use_negotiation=True),
            )
        )
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())
    names = _event_names(events)

    assert "error" not in names
    _assert_successful_negotiation(events)
    assert (
        next(event for event in events if event.event == "negotiation_done").reason_code
        == AgentTraceReasonCode.NEGOTIATION_COMPLETED_WITH_FALLBACK
    )
    assert any(
        event.event == "negotiation_step"
        and event.reason_code == AgentTraceReasonCode.ORCHESTRATOR_INVALID_RESPONSE
        for event in events
    )


def test_orchestrator_timeout_falls_back_to_stable_synthesis(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.graph_runtime._NEGOTIATION_AGENT_TIMEOUT_SECONDS", 0.01)

    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                chat_model=SlowOrchestratorChatModel(),
                automation_settings=SimpleNamespace(use_negotiation=True),
            )
        )
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())

    _assert_successful_negotiation(events)
    assert (
        next(event for event in events if event.event == "negotiation_done").reason_code
        == AgentTraceReasonCode.NEGOTIATION_COMPLETED_WITH_FALLBACK
    )
    assert any(
        event.event == "negotiation_step"
        and event.reason_code == AgentTraceReasonCode.ORCHESTRATOR_TIMEOUT
        for event in events
    )


@pytest.mark.parametrize("error_code", ["authentication_failed", "provider_timeout"])
def test_provider_failure_is_terminal_error_without_negotiation_done(error_code: str) -> None:
    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                chat_model=ProviderFailingOrchestratorChatModel(error_code),
                automation_settings=SimpleNamespace(use_negotiation=True),
            )
        )
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())
    names = _event_names(events)

    assert names[-1] == "error"
    assert next(event for event in events if event.event == "error").code == error_code
    assert "Traceback" not in next(event for event in events if event.event == "error").message
    assert "negotiation_done" not in names
    assert "done" not in names
    assert sum(name in {"done", "error"} for name in names) == 1


def test_subagent_timeout_falls_back_without_terminal_error(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.graph_runtime._NEGOTIATION_AGENT_TIMEOUT_SECONDS", 0.01)

    async def run_case():
        runtime = SlowRetrievalRuntime(
            AgentRuntimeServices(
                chat_model=NegotiationChatModel(),
                automation_settings=SimpleNamespace(use_negotiation=True),
            )
        )
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())
    names = _event_names(events)

    assert "error" not in names
    _assert_successful_negotiation(events)
    done = next(event for event in events if event.event == "negotiation_done")
    assert done.counts.rounds == 1
    assert done.reason_code == AgentTraceReasonCode.NEGOTIATION_COMPLETED_WITH_FALLBACK
    assert any(
        event.event == "negotiation_step"
        and event.reason_code == AgentTraceReasonCode.AGENT_TIMEOUT
        for event in events
    )


def test_failed_synthesis_does_not_emit_negotiation_done_or_done() -> None:
    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=FakeRetrieval(),
                chat_model=FailingSynthesisChatModel(),
                automation_settings=SimpleNamespace(use_negotiation=True),
            )
        )
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())
    names = _event_names(events)

    assert names[-1] == "error"
    assert "negotiation_done" not in names
    assert "done" not in names
    error = next(event for event in events if event.event == "error")
    assert error.code == "model_invocation_failed"
    assert error.message == "模型调用失败，请检查模型服务地址、模型名称和 API 密钥。"
    assert sum(name in {"done", "error"} for name in names) == 1
