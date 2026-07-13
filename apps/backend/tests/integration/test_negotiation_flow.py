from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.agents.events import AgentDoneEvent, AgentErrorEvent, AgentTokenEvent
from app.models.enums import AgentIntent
from app.services.agent_actions import AgentActionCreate
from tests.conftest import auth_headers, parse_sse_events


class LegacyNegotiationChatModel:
    def __init__(
        self,
        response: str = "v2 foreground reply",
        *,
        reasoning: str = "已完成一次有界检索。",
    ) -> None:
        self.response = response
        self.reasoning = reasoning
        self.calls: list[tuple[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if system_prompt == "orchestrator-json-only":
            return json.dumps(
                {
                    "action": "synthesize",
                    "agent": None,
                    "agent_input": None,
                    "reasoning": self.reasoning,
                    "confidence": 0.95,
                    "expected_outcome": "合成本地证据回复。",
                },
                ensure_ascii=False,
            )
        return self.response

    @property
    def orchestrator_calls(self) -> list[tuple[str, str | None]]:
        return [call for call in self.calls if call[1] == "orchestrator-json-only"]


class RecordingRuntime(LangGraphAgentRuntime):
    def __init__(
        self,
        *,
        chat_model: LegacyNegotiationChatModel,
        recorded_actions: list[AgentActionCreate],
        invoked_agents: list[str],
    ) -> None:
        self.invoked_agents = invoked_agents
        super().__init__(
            AgentRuntimeServices(
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=True, max_rounds=2),
                agent_action_recorder=recorded_actions.append,
            )
        )

    def _agent_handler_for(self, agent_id):
        async def handler(input_query: str, state) -> dict[str, Any]:
            agent_name = agent_id.value if hasattr(agent_id, "value") else str(agent_id)
            self.invoked_agents.append(agent_name)
            return {"result": f"{agent_name}: {input_query}", "confidence": 0.3}

        return handler


@pytest.fixture()
def runtime_harness(monkeypatch: pytest.MonkeyPatch):
    recorded_actions: list[AgentActionCreate] = []
    invoked_agents: list[str] = []
    chat_models: list[LegacyNegotiationChatModel] = []

    def install(response: str = "v2 foreground reply") -> LegacyNegotiationChatModel:
        chat_model = LegacyNegotiationChatModel(response)
        chat_models.append(chat_model)

        def fake_agent_runtime(request: Request) -> RecordingRuntime:
            return RecordingRuntime(
                chat_model=chat_model,
                recorded_actions=recorded_actions,
                invoked_agents=invoked_agents,
            )

        monkeypatch.setattr("app.api.chat.agent_runtime", fake_agent_runtime)
        return chat_model

    return SimpleNamespace(
        install=install,
        recorded_actions=recorded_actions,
        invoked_agents=invoked_agents,
        chat_models=chat_models,
    )


def _stream_chat(client: TestClient, message: str) -> list[dict[str, str]]:
    accepted = client.post("/api/chat", headers=auth_headers(), json={"message": message})
    assert accepted.status_code == 200
    stream = client.get(accepted.json()["stream_url"], headers=auth_headers())
    assert stream.status_code == 200
    return parse_sse_events(stream.text)


def _event_names(events: list[dict[str, str]]) -> list[str]:
    return [event["event"] for event in events]


def test_negotiation_switch_streams_bounded_steps_and_records_stats(client_factory, runtime_harness) -> None:
    credential = "s" + "k-" + "integration-secret"
    unsafe_reasoning = " | ".join(
        [
            "private-integration-sentinel",
            "Authorization: " + "Bearer " + credential,
            r"C:\Users\Alice\Vault\Secret.md",
            "/home/alice/vault/Secret.md",
            "raw_prompt=hidden",
            "tool_arguments={'query': 'hidden'}",
            "Traceback (most recent call last):",
        ]
    )
    chat_model = runtime_harness.install()
    chat_model.reasoning = unsafe_reasoning

    with client_factory() as client:
        events = _stream_chat(client, "search memory for Ada project")

    names = _event_names(events)
    assert "token" in names
    assert names[-1] == "done"
    assert "negotiation_step" in names
    assert "negotiation_done" in names
    assert names.index("negotiation_done") < names.index("done")
    assert names.index("negotiation_done") < names.index("reply_ready") < names.index("done")
    assert sum(name in {"done", "error"} for name in names) == 1
    trace_payloads = [
        json.loads(event["data"])
        for event in events
        if event["event"] in {"negotiation_step", "negotiation_done"}
    ]
    assert [payload["sequence"] for payload in trace_payloads] == list(range(1, len(trace_payloads) + 1))
    assert all(payload["contract_version"] == "agent-trace.v1" for payload in trace_payloads)
    serialized_trace = json.dumps(trace_payloads, ensure_ascii=False)
    for forbidden in (
        "private-integration-sentinel",
        credential,
        r"C:\Users\Alice",
        "/home/alice",
        "raw_prompt",
        "tool_arguments",
        "Traceback",
    ):
        assert forbidden not in serialized_trace
    assert len(chat_model.orchestrator_calls) == 1
    assert runtime_harness.invoked_agents == ["retrieval_agent"]
    assert len(runtime_harness.recorded_actions) == 1
    action = runtime_harness.recorded_actions[0]
    assert action.action_type == "agent.negotiation"
    assert action.negotiation_rounds == 1


class ContradictoryTerminalRuntime:
    async def run(self, state):
        yield AgentTokenEvent(agent_run_id=state.agent_run_id, text="first terminal wins")
        yield AgentDoneEvent(
            agent_run_id=state.agent_run_id,
            intent=AgentIntent.CHAT,
            text="first terminal wins",
        )
        yield AgentErrorEvent(
            agent_run_id=state.agent_run_id,
            code="internal_error",
            message="late error",
        )
        yield AgentDoneEvent(
            agent_run_id=state.agent_run_id,
            intent=AgentIntent.CHAT,
            text="late done",
        )


def test_api_stream_keeps_exactly_one_first_terminal_event(client_factory, monkeypatch) -> None:
    monkeypatch.setattr("app.api.chat.agent_runtime", lambda request: ContradictoryTerminalRuntime())

    with client_factory() as client:
        events = _stream_chat(client, "hello")

    names = _event_names(events)
    assert names[-2:] == ["reply_ready", "done"]
    assert sum(name in {"done", "error"} for name in names) == 1
    assert "error" not in names


class UnsafeErrorRuntime:
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message

    async def run(self, state):
        yield AgentErrorEvent(
            agent_run_id=state.agent_run_id,
            code=self.code,
            message=self.message,
        )


def test_api_redacts_unknown_error_from_sse_and_persisted_run(client_factory, monkeypatch) -> None:
    credential = "s" + "k-" + "persisted-error-secret"
    unsafe_error = " | ".join(
        [
            "Authorization: " + "Bearer " + credential,
            r"C:\Users\Alice\Vault\Secret.md",
            "raw_prompt tool_arguments Traceback",
        ]
    )
    monkeypatch.setattr(
        "app.api.chat.agent_runtime",
        lambda request: UnsafeErrorRuntime(code=unsafe_error, message=unsafe_error),
    )

    with client_factory() as client:
        accepted = client.post("/api/chat", headers=auth_headers(), json={"message": "hello"})
        assert accepted.status_code == 200
        accepted_payload = accepted.json()
        stream = client.get(accepted_payload["stream_url"], headers=auth_headers())
        assert stream.status_code == 200
        events = parse_sse_events(stream.text)
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.row_factory = sqlite3.Row
            run = conn.execute(
                "SELECT error_code, error_message FROM agent_runs WHERE id = ?",
                (accepted_payload["agent_run_id"],),
            ).fetchone()

    error_payload = json.loads(events[-1]["data"])
    assert events[-1]["event"] == "error"
    assert error_payload == {"agent_run_id": accepted_payload["agent_run_id"], "code": "internal_error", "message": "回复处理失败，请稍后重试。"}
    assert run is not None
    assert run["error_code"] == "internal_error"
    assert run["error_message"] == "回复处理失败，请稍后重试。"
    assert credential not in stream.text
    assert unsafe_error not in stream.text
