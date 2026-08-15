from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from tests.agent_runtime_fakes import (
    FakeBadRequestTaskModel,
    FakeFailingToolCallingChatModel,
    FakeMemory,
    FakeRegistryChatModel,
    FakeTasks,
    FakeToolCallingChatModel,
    assert_langgraph_events,
    first_event,
    make_state,
)

from app.agents import AgentRuntimeServices, AgentTaskEvent, LangGraphAgentRuntime, sse_encode
from app.models.api import AutomationSettingsResponse
from app.services.chat_model import AgentId, AgentModelRegistry


def test_langgraph_runtime_preserves_core_tool_agents() -> None:
    async def run_case():
        memory = FakeMemory()
        tasks = FakeTasks()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                tasks=tasks,
                automation_settings=SimpleNamespace(use_negotiation=False),
                allow_ephemeral_lifecycle=True,
            )
        )

        memory_events = [
            event async for event in runtime.run(make_state("remember this: Ada likes tests"))
        ]
        task_events = [
            event async for event in runtime.run(make_state("remind me to review tests"))
        ]

        return memory, tasks, memory_events, task_events

    memory, tasks, memory_events, task_events = asyncio.run(run_case())

    assert memory.requests == []
    assert tasks.requests[0].title == "review tests"
    assert_langgraph_events(memory_events, ["token", "done"])
    assert "后台长期记忆整理流程" in first_event(memory_events, "token").text
    assert_langgraph_events(task_events, ["token", "task", "done"])


def test_langgraph_action_agent_defers_memory_to_auto_background_archive_by_default() -> None:
    async def run_case():
        memory = FakeMemory()
        memory_model = FakeToolCallingChatModel("propose_memory", "已创建待确认记忆。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                model_registry=AgentModelRegistry(
                    {AgentId.ACTION_AGENT: memory_model}
                ),
                automation_settings=SimpleNamespace(use_negotiation=False),
                allow_ephemeral_lifecycle=True,
            )
        )

        events = [
            event
            async for event in runtime.run(
                make_state("请把 Ada likes tests 作为长期偏好保存下来")
            )
        ]

        return memory, memory_model, events

    memory, memory_model, events = asyncio.run(run_case())

    assert memory.requests == []
    assert memory_model.calls == []
    assert_langgraph_events(events, ["token", "done"])
    assert "后台长期记忆整理流程" in first_event(events, "token").text


def test_langgraph_chat_agent_maps_model_memory_tool_call_to_proposal_event_when_auto_disabled() -> None:
    async def run_case():
        memory = FakeMemory()
        memory_model = FakeToolCallingChatModel("propose_memory", "已创建待确认记忆。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                model_registry=AgentModelRegistry(
                    {AgentId.ACTION_AGENT: memory_model}
                ),
                automation_settings=AutomationSettingsResponse(auto_long_term_memory=False, use_negotiation=False),
                allow_ephemeral_lifecycle=True,
            )
        )

        events = [
            event
            async for event in runtime.run(
                make_state("请把 Ada likes tests 作为长期偏好保存下来")
            )
        ]

        return memory, events

    memory, events = asyncio.run(run_case())

    assert memory.requests[0].content == "请把 Ada likes tests 作为长期偏好保存下来"
    assert_langgraph_events(events, ["token", "memory_proposal", "done"])
    assert first_event(events, "memory_proposal").proposal_id == "proposal-1"
    assert first_event(events, "token").text == "我会先创建一条待确认的长期记忆提案。"


def test_langgraph_action_agent_creates_task_without_legacy_task_model_call() -> None:
    async def run_case():
        tasks = FakeTasks()
        task_model = FakeRegistryChatModel(None, "已创建任务。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                tasks=tasks,
                model_registry=AgentModelRegistry({AgentId.ACTION_AGENT: task_model}),
                automation_settings=SimpleNamespace(use_negotiation=False),
                allow_ephemeral_lifecycle=True,
            )
        )

        events = [event async for event in runtime.run(make_state("安排一次测试事项"))]

        return tasks, task_model, events

    tasks, task_model, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "安排一次测试事项"
    assert task_model.calls == []
    assert_langgraph_events(events, ["token", "task", "done"])
    assert first_event(events, "task").task_id == "task-1"
    assert first_event(events, "task").title == "安排一次测试事项"
    assert first_event(events, "task").reminder_status == "scheduled"
    assert first_event(events, "task").timezone_label == "北京时间"
    assert first_event(events, "token").text == "好，我先把它整理成一个本地提醒：安排一次测试事项"


def test_langgraph_action_agent_creates_task_when_provider_rejects_model_params() -> None:
    async def run_case():
        tasks = FakeTasks()
        task_model = FakeBadRequestTaskModel()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                tasks=tasks,
                model_registry=AgentModelRegistry({AgentId.ACTION_AGENT: task_model}),
                automation_settings=SimpleNamespace(use_negotiation=False),
                allow_ephemeral_lifecycle=True,
            )
        )

        events = [event async for event in runtime.run(make_state("5秒钟后提醒我写笔记"))]

        return tasks, task_model, events

    tasks, task_model, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "写笔记"
    assert tasks.requests[0].source_text == "5秒钟后提醒我写笔记"
    assert task_model.calls == []
    assert_langgraph_events(events, ["token", "task", "done"])
    assert first_event(events, "task").task_id == "task-1"
    assert first_event(events, "task").reminder_id == "reminder-1"
    assert first_event(events, "token").text == "好，我先把它整理成一个本地提醒：写笔记"


def test_demo_compound_request_creates_task_and_memory_receipts() -> None:
    async def run_case():
        memory = FakeMemory()
        tasks = FakeTasks()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                tasks=tasks,
                automation_settings=AutomationSettingsResponse(
                    auto_long_term_memory=False,
                    use_negotiation=False,
                ),
                allow_ephemeral_lifecycle=True,
            )
        )

        events = [
            event
            async for event in runtime.run(
                make_state("明天下午三点提醒我给张老师回邮件，并记住我更喜欢下午开会。")
            )
        ]
        return memory, tasks, events

    memory, tasks, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "给张老师回邮件"
    assert tasks.requests[0].source_text == "明天下午三点提醒我给张老师回邮件"
    assert memory.requests[0].content == "我更喜欢下午开会"
    assert_langgraph_events(events, ["token", "task", "memory_proposal", "done"])
    assert "同时处理两件事" in first_event(events, "token").text


def test_demo_compound_request_ignores_unsplit_classifier_title() -> None:
    async def run_case():
        memory = FakeMemory()
        tasks = FakeTasks()
        semantic_model = FakeRegistryChatModel(
            None,
            json.dumps(
                {
                    "intent": "action",
                    "retrieval_scope": None,
                    "retrieval_query": None,
                    "action_type": "task",
                    "action_params": {
                        "title": "给张老师回邮件，并记住我更喜欢下午开会",
                    },
                    "confidence": 0.99,
                    "reason": "compound reminder",
                },
                ensure_ascii=False,
            ),
        )
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                tasks=tasks,
                model_registry=AgentModelRegistry(
                    {AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model}
                ),
                automation_settings=AutomationSettingsResponse(
                    auto_long_term_memory=False,
                    use_negotiation=False,
                ),
                allow_ephemeral_lifecycle=True,
            )
        )

        events = [
            event
            async for event in runtime.run(
                make_state("明天下午三点提醒我给张老师回邮件，并记住我更喜欢下午开会。")
            )
        ]
        return memory, tasks, events

    memory, tasks, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "给张老师回邮件"
    assert tasks.requests[0].source_text == "明天下午三点提醒我给张老师回邮件"
    assert memory.requests[0].content == "我更喜欢下午开会"
    assert_langgraph_events(events, ["token", "task", "memory_proposal", "done"])


def test_high_risk_chat_request_only_records_confirmation() -> None:
    recorded_actions = []

    def record_action(action):
        recorded_actions.append(action)
        return SimpleNamespace(
            action_id="action-confirm-1",
            source_agent_run_id=action.source_agent_run_id,
            source_conversation_id=action.source_conversation_id,
            source_message_id=action.source_message_id,
            action_type=action.action_type,
            risk_tier=action.risk_tier,
            decision=action.decision,
            status=action.status,
            title=action.title,
            summary=action.summary,
            target_paths=list(action.target_paths),
            reversible=action.reversible,
            reverted_by=None,
            reverts_action_id=None,
            error=None,
            source={},
            diff_summary="",
            metadata=action.metadata,
            created_at=None,
            updated_at=None,
            completed_at=None,
        )

    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                automation_settings=SimpleNamespace(use_negotiation=False),
                agent_action_recorder=record_action,
                allow_ephemeral_lifecycle=True,
            )
        )
        return [event async for event in runtime.run(make_state("删除所有本地记忆文件"))]

    events = asyncio.run(run_case())

    assert recorded_actions[0].action_type == "local.destructive_request"
    assert recorded_actions[0].risk_tier == "high"
    assert recorded_actions[0].decision == "ask"
    action_event = first_event(events, "agent_action")
    assert action_event.requires_confirmation is True
    assert action_event.target_paths == []
    assert_langgraph_events(events, ["token", "agent_action", "done"])


def test_langgraph_chat_agent_returns_error_when_model_tool_call_fails() -> None:
    async def run_case():
        memory = FakeMemory()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                model_registry=AgentModelRegistry(
                    {AgentId.ACTION_AGENT: FakeFailingToolCallingChatModel()}
                ),
                automation_settings=AutomationSettingsResponse(auto_long_term_memory=False, use_negotiation=False),
                allow_ephemeral_lifecycle=True,
            )
        )

        events = [event async for event in runtime.run(make_state("remember this: sk-agent-memory-secret-1234567890"))]

        return memory, events

    memory, events = asyncio.run(run_case())

    assert memory.requests == []
    assert_langgraph_events(events, ["error"])
    assert first_event(events, "error").code == "sensitive_memory_rejected"
    assert "敏感内容" in first_event(events, "error").message


def test_sse_encode_uses_event_name_and_json_data() -> None:
    encoded = sse_encode(
        AgentTaskEvent(
            agent_run_id="run-1",
            task_id="task-1",
            reminder_id=None,
            status="pending",
        )
    )

    event_line, data_line, blank = encoded.splitlines()
    assert event_line == "event: task"
    assert blank == ""
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload == {
        "agent_run_id": "run-1",
        "task_id": "task-1",
        "reminder_id": None,
        "status": "pending",
        "title": None,
        "reminder_status": None,
        "remind_at": None,
        "timezone": None,
        "timezone_label": None,
    }
