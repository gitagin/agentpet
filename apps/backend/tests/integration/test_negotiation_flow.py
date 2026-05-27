from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.services.agent_actions import AgentActionCreate
from tests.conftest import auth_headers, parse_sse_events


class SequencedNegotiationChatModel:
    def __init__(self, *, decisions: list[dict[str, Any]], response: str) -> None:
        self.decisions = decisions
        self.response = response
        self.calls: list[tuple[str, str | None]] = []
        self.final_user_message = ""

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if system_prompt == "orchestrator-json-only":
            index = min(len(self.orchestrator_calls) - 1, len(self.decisions) - 1)
            return json.dumps(self.decisions[index], ensure_ascii=False)
        self.final_user_message = user_message
        return self.response

    @property
    def orchestrator_calls(self) -> list[tuple[str, str | None]]:
        return [call for call in self.calls if call[1] == "orchestrator-json-only"]


class RecordingRuntime(LangGraphAgentRuntime):
    def __init__(
        self,
        *,
        chat_model: SequencedNegotiationChatModel,
        automation_settings: SimpleNamespace,
        outputs: dict[str, list[dict[str, Any]]],
        recorded_actions: list[AgentActionCreate],
        invoked_agents: list[str],
    ) -> None:
        self.outputs = outputs
        self.invoked_agents = invoked_agents
        super().__init__(
            AgentRuntimeServices(
                chat_model=chat_model,
                automation_settings=automation_settings,
                agent_action_recorder=recorded_actions.append,
            )
        )

    def _agent_handler_for(self, agent_id):
        async def handler(input_query: str, state) -> dict[str, Any]:
            agent_name = agent_id.value if hasattr(agent_id, "value") else str(agent_id)
            self.invoked_agents.append(agent_name)
            queue = self.outputs.setdefault(agent_name, [])
            if not queue:
                return {"result": f"{agent_name} 没有更多结果", "confidence": 0.3}
            return queue.pop(0)

        return handler


def _decision(agent: str, confidence: float, reasoning: str, agent_input: str | None = None) -> dict[str, Any]:
    return {
        "action": "invoke_agent",
        "agent": agent,
        "agent_input": agent_input or agent,
        "reasoning": reasoning,
        "confidence": confidence,
        "expected_outcome": "补充上下文。",
    }


def _synthesize(confidence: float, reasoning: str = "已有信息足够。") -> dict[str, Any]:
    return {
        "action": "synthesize",
        "agent": None,
        "agent_input": None,
        "reasoning": reasoning,
        "confidence": confidence,
        "expected_outcome": "合成最终回复。",
    }


@pytest.fixture()
def runtime_harness(monkeypatch: pytest.MonkeyPatch):
    recorded_actions: list[AgentActionCreate] = []
    invoked_agents: list[str] = []
    chat_models: list[SequencedNegotiationChatModel] = []

    def install(
        *,
        decisions: list[dict[str, Any]],
        outputs: dict[str, list[dict[str, Any]]] | None = None,
        response: str = "协商后的最终回复",
        max_rounds: int = 5,
    ) -> SequencedNegotiationChatModel:
        chat_model = SequencedNegotiationChatModel(decisions=decisions, response=response)
        chat_models.append(chat_model)

        def fake_agent_runtime(request: Request) -> RecordingRuntime:
            return RecordingRuntime(
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=True, max_rounds=max_rounds),
                outputs={key: [*value] for key, value in (outputs or {}).items()},
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


def _event_payload(events: list[dict[str, str]], name: str) -> dict[str, Any]:
    matching = [item for item in events if item["event"] == name]
    assert matching, _event_names(events)
    return json.loads(matching[0]["data"])


def _event_names(events: list[dict[str, str]]) -> list[str]:
    return [event["event"] for event in events]


def test_multi_round_retrieval(client_factory, runtime_harness) -> None:
    chat_model = runtime_harness.install(
        decisions=[
            _decision("memory_retrieval_agent", 0.5, "先检索个人记忆。", "Ada"),
            _decision("knowledge_retrieval_agent", 0.4, "还需要知识库补充。", "Ada project"),
            _synthesize(0.85, "两次检索后信息足够。"),
        ],
        outputs={
            "memory_retrieval_agent": [{"result": "个人记忆：Ada 喜欢图数据库。", "confidence": 0.5}],
            "knowledge_retrieval_agent": [{"result": "知识库：Ada 项目使用 FTS5。", "confidence": 0.85}],
        },
        response="聚合回复：Ada 喜欢图数据库，项目使用 FTS5。",
    )

    with client_factory() as client:
        events = _stream_chat(client, "search memory for Ada project")

    done = _event_payload(events, "negotiation_done")
    assert done["total_rounds"] == 2
    assert done["agents_invoked"] == ["memory_retrieval_agent", "knowledge_retrieval_agent"]
    assert "个人记忆：Ada 喜欢图数据库。" in chat_model.final_user_message
    assert "知识库：Ada 项目使用 FTS5。" in chat_model.final_user_message
    assert runtime_harness.recorded_actions[0].negotiation_rounds == 2


def test_memory_proposal_self_review(client_factory, runtime_harness) -> None:
    chat_model = runtime_harness.install(
        decisions=[
            _decision("memory_proposal_agent", 0.6, "先生成记忆草案。", "record Ada preference"),
            _decision("memory_proposal_agent", 0.6, "草案需要自审修订。", "review draft"),
            _synthesize(0.9, "修订草案可提交。"),
        ],
        outputs={
            "memory_proposal_agent": [
                {"result": "草案：Ada 喜欢数据库。", "confidence": 0.6},
                {
                    "result": "approved=False; revised_draft=修订草案：Ada 偏好图数据库和可追溯记忆。",
                    "confidence": 0.9,
                },
            ],
        },
        response="最终 proposal：修订草案：Ada 偏好图数据库和可追溯记忆。",
    )

    with client_factory() as client:
        events = _stream_chat(client, "帮我记住 Ada 的偏好，需要审查")

    done = _event_payload(events, "negotiation_done")
    assert done["total_rounds"] == 2
    assert done["agents_invoked"] == ["memory_proposal_agent", "memory_proposal_agent"]
    assert "修订草案：Ada 偏好图数据库和可追溯记忆。" in chat_model.final_user_message
    assert "草案：Ada 喜欢数据库。" in chat_model.final_user_message


def test_wiki_edit_quality_loop(client_factory, runtime_harness) -> None:
    chat_model = runtime_harness.install(
        decisions=[
            _decision("wiki_manager_agent", 0.55, "先规划 Vault 页面。", "plan wiki edit"),
            _decision("wiki_manager_agent", 0.6, "执行初稿整理。", "execute draft"),
            _decision("wiki_manager_agent", 0.6, "审查发现问题。", "review draft"),
            _decision("wiki_manager_agent", 0.6, "根据审查修正。", "fix draft"),
            _synthesize(0.9, "修正后内容可交付。"),
        ],
        outputs={
            "wiki_manager_agent": [
                {"result": "计划：整理到 Projects/Ada.md。", "confidence": 0.55},
                {"result": "初稿：Ada 页面缺少来源。", "confidence": 0.6},
                {"result": "issues=['缺少来源']; 需要修正。", "confidence": 0.6},
                {"result": "修正后内容：Ada 页面补充来源与结构。", "confidence": 0.9},
            ],
        },
        response="最终提交：修正后内容：Ada 页面补充来源与结构。",
    )

    with client_factory() as client:
        events = _stream_chat(client, "请整理到知识库 Ada 的 Vault 页面并自检")

    done = _event_payload(events, "negotiation_done")
    assert done["total_rounds"] == 4
    assert done["agents_invoked"] == [
        "wiki_manager_agent",
        "wiki_manager_agent",
        "wiki_manager_agent",
        "wiki_manager_agent",
    ]
    assert "修正后内容：Ada 页面补充来源与结构。" in chat_model.final_user_message
    assert runtime_harness.invoked_agents[-1] == "wiki_manager_agent"


def test_max_rounds_fallback(client_factory, runtime_harness) -> None:
    runtime_harness.install(
        decisions=[_decision("memory_retrieval_agent", 0.3, "置信度仍不足。", "Ada")],
        outputs={
            "memory_retrieval_agent": [
                {"result": "低置信度结果 1", "confidence": 0.3},
                {"result": "低置信度结果 2", "confidence": 0.3},
            ],
        },
        response="达到轮次上限后的兜底回复",
        max_rounds=2,
    )

    with client_factory() as client:
        events = _stream_chat(client, "search memory for Ada until confident")

    done = _event_payload(events, "negotiation_done")
    assert done["total_rounds"] == 2
    assert done["fallback"] is True
    assert runtime_harness.recorded_actions[0].negotiation_rounds == 2
    assert runtime_harness.recorded_actions[0].metadata["fallback"] is True


def test_fast_path_bypasses_orchestrator(client_factory, runtime_harness) -> None:
    chat_model = runtime_harness.install(
        decisions=[_decision("memory_retrieval_agent", 0.1, "不应调用。")],
        response="你好呀",
    )

    with client_factory() as client:
        events = _stream_chat(client, "你好")

    assert "token" in _event_names(events)
    assert _event_names(events)[-1] == "done"
    assert chat_model.orchestrator_calls == []
    assert runtime_harness.invoked_agents == []
    assert runtime_harness.recorded_actions == []
