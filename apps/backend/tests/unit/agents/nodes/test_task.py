from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from app.agents.events import AgentErrorEvent, AgentTaskEvent, AgentTokenEvent
from app.agents.nodes.task import _fallback_create_task, _optional_task_reply, _task_node
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState
from app.models.api import TaskCreateResponse


@dataclass
class ModelResult:
    text: str


def _state(message: str = "提醒我明天测试") -> AgentState:
    return AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message=message,
    )


def _graph_state(message: str = "提醒我明天测试") -> dict:
    return {"agent_state": _state(message), "events": []}


class TaskService:
    def __init__(self) -> None:
        self.create = AsyncMock(
            return_value=TaskCreateResponse(
                task_id="task-1",
                reminder_id="reminder-1",
                status="scheduled",
                metadata={"title": "提醒我明天测试", "reminder_status": "scheduled"},
            )
        )


class TaskModel:
    def __init__(self, text: str = "任务已创建") -> None:
        self.complete_with_tools = AsyncMock(return_value=ModelResult(text=text))


class Registry:
    def __init__(self, model: object = object()) -> None:
        self.model = model

    def get(self, _agent_id):
        return self.model


@pytest.mark.asyncio
async def test_task_node_creates_task_on_happy_path() -> None:
    graph_state = _graph_state()

    result = await _task_node(graph_state, AgentRuntimeServices(tasks=TaskService()))

    assert result["agent_state"].task_id == "task-1"
    assert result["agent_state"].reminder_id == "reminder-1"
    assert result["agent_state"].response_text == "我已创建任务。"
    assert any(isinstance(event, AgentTaskEvent) for event in result["events"])
    assert any(isinstance(event, AgentTokenEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_task_node_returns_empty_when_model_returns_empty_result() -> None:
    graph_state = _graph_state()

    result = await _task_node(
        graph_state,
        AgentRuntimeServices(tasks=TaskService(), model_registry=Registry(TaskModel(""))),
    )

    assert result["agent_state"].response_text == ""
    assert result["agent_state"].task_id == "task-1"


@pytest.mark.asyncio
async def test_task_node_handles_invalid_json_from_model() -> None:
    graph_state = _graph_state()

    result = await _task_node(
        graph_state,
        AgentRuntimeServices(tasks=TaskService(), model_registry=Registry(TaskModel("{not-json"))),
    )

    assert result["agent_state"].response_text == "{not-json"
    assert result["agent_state"].task_id == "task-1"


@pytest.mark.asyncio
async def test_task_node_returns_fallback_when_model_times_out() -> None:
    graph_state = _graph_state()
    model = TaskModel()
    model.complete_with_tools.side_effect = TimeoutError("model timed out")

    result = await _task_node(
        graph_state,
        AgentRuntimeServices(tasks=TaskService(), model_registry=Registry(model)),
    )

    assert result["agent_state"].response_text == "我已创建任务。"
    assert result["agent_state"].task_id == "task-1"


@pytest.mark.asyncio
async def test_task_node_records_exception_when_task_service_fails() -> None:
    graph_state = _graph_state()
    tasks = TaskService()
    tasks.create.side_effect = RuntimeError("task store unavailable")

    result = await _task_node(graph_state, AgentRuntimeServices(tasks=tasks))

    assert result["failed"] is True
    assert result["agent_state"].error_code == "RuntimeError"
    assert any(isinstance(event, AgentErrorEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_fallback_create_task_raises_when_tool_unavailable() -> None:
    with pytest.raises(Exception) as exc_info:
        await _fallback_create_task(AgentRuntimeServices(), _state())

    assert getattr(exc_info.value, "code", "") == "agent_tool_unavailable"


@pytest.mark.asyncio
async def test_optional_task_reply_returns_fallback_when_model_exception() -> None:
    model = TaskModel()
    model.complete_with_tools.side_effect = ValueError("bad model output")

    response = await _optional_task_reply(
        AgentRuntimeServices(model_registry=Registry(model)),
        _state(),
        "我已创建任务。",
    )

    assert response == "我已创建任务。"
