from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.services.agent_actions import AgentActionCreate
from tests.conftest import auth_headers, parse_sse_events


class LegacyNegotiationChatModel:
    def __init__(self, response: str = "v2 foreground reply") -> None:
        self.response = response
        self.calls: list[tuple[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
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


def test_legacy_negotiation_switch_no_longer_runs_foreground_orchestrator(client_factory, runtime_harness) -> None:
    chat_model = runtime_harness.install()

    with client_factory() as client:
        events = _stream_chat(client, "search memory for Ada project")

    names = _event_names(events)
    assert "token" in names
    assert names[-1] == "done"
    assert "negotiation_step" not in names
    assert "negotiation_done" not in names
    assert chat_model.orchestrator_calls == []
    assert runtime_harness.invoked_agents == []
    assert runtime_harness.recorded_actions == []
