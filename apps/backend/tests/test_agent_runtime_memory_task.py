from __future__ import annotations

import asyncio
import json

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
            AgentRuntimeServices(memory=memory, tasks=tasks)
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
    assert "后台自动整理流程" in first_event(memory_events, "token").text
    assert_langgraph_events(task_events, ["task", "token", "done"])


def test_langgraph_memory_agent_defers_to_auto_background_archive_by_default() -> None:
    async def run_case():
        memory = FakeMemory()
        memory_model = FakeToolCallingChatModel("propose_memory", "已创建待确认记忆。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                model_registry=AgentModelRegistry(
                    {AgentId.MEMORY_PROPOSAL_AGENT: memory_model}
                ),
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
    assert "后台自动整理流程" in first_event(events, "token").text


def test_langgraph_chat_agent_maps_model_memory_tool_call_to_proposal_event_when_auto_disabled() -> None:
    async def run_case():
        memory = FakeMemory()
        memory_model = FakeToolCallingChatModel("propose_memory", "已创建待确认记忆。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                model_registry=AgentModelRegistry(
                    {AgentId.MEMORY_PROPOSAL_AGENT: memory_model}
                ),
                automation_settings=AutomationSettingsResponse(auto_long_term_memory=False),
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

    assert memory.requests[0].content == "Ada likes tests"
    assert_langgraph_events(events, ["memory_proposal", "token", "done"])
    assert first_event(events, "memory_proposal").proposal_id == "proposal-1"
    assert first_event(events, "token").text == "已创建待确认记忆。"


def test_langgraph_task_agent_uses_model_for_confirmation_after_local_task_create() -> None:
    async def run_case():
        tasks = FakeTasks()
        task_model = FakeRegistryChatModel(None, "已创建任务。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                tasks=tasks,
                model_registry=AgentModelRegistry({AgentId.TASK_AGENT: task_model}),
            )
        )

        events = [event async for event in runtime.run(make_state("安排一次测试事项"))]

        return tasks, task_model, events

    tasks, task_model, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "安排一次测试事项"
    assert task_model.calls[0][2] == []
    assert_langgraph_events(events, ["task", "token", "done"])
    assert first_event(events, "task").task_id == "task-1"
    assert first_event(events, "task").title == "安排一次测试事项"
    assert first_event(events, "task").reminder_status == "scheduled"
    assert first_event(events, "task").timezone_label == "北京时间"
    assert first_event(events, "token").text == "已创建任务。"


def test_langgraph_task_agent_creates_task_when_provider_rejects_model_params() -> None:
    async def run_case():
        tasks = FakeTasks()
        task_model = FakeBadRequestTaskModel()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                tasks=tasks,
                model_registry=AgentModelRegistry({AgentId.TASK_AGENT: task_model}),
            )
        )

        events = [event async for event in runtime.run(make_state("5秒钟后提醒我写笔记"))]

        return tasks, task_model, events

    tasks, task_model, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "写笔记"
    assert tasks.requests[0].source_text == "5秒钟后提醒我写笔记"
    assert task_model.calls[0][2] == []
    assert_langgraph_events(events, ["task", "token", "done"])
    assert first_event(events, "task").task_id == "task-1"
    assert first_event(events, "task").reminder_id == "reminder-1"
    assert first_event(events, "token").text == "我已创建任务。"


def test_langgraph_chat_agent_returns_error_when_model_tool_call_fails() -> None:
    async def run_case():
        memory = FakeMemory()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                model_registry=AgentModelRegistry(
                    {AgentId.MEMORY_PROPOSAL_AGENT: FakeFailingToolCallingChatModel()}
                ),
                automation_settings=AutomationSettingsResponse(auto_long_term_memory=False),
            )
        )

        events = [event async for event in runtime.run(make_state("请把这个密钥保存到长期偏好里"))]

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
