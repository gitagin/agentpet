from __future__ import annotations

import pytest

from app.agents.events import AgentDoneEvent, AgentStatusEvent
from app.agents.nodes.finish import _finish_node
from app.agents.state import AgentRoute, AgentState
from app.models.enums import AgentIntent, AgentRunStatus


def _graph_state(*, failed: bool = False) -> dict:
    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="你好",
        route=AgentRoute(intent=AgentIntent.CHAT, confidence=1.0, reason="test"),
        response_text="回复内容",
    )
    graph_state = {"agent_state": state, "events": []}
    if failed:
        graph_state["failed"] = True
    return graph_state


@pytest.mark.asyncio
async def test_finish_node_emits_done_on_happy_path() -> None:
    graph_state = _graph_state()

    result = await _finish_node(graph_state)

    assert result["agent_state"].status == AgentRunStatus.SUCCESS
    assert any(isinstance(event, AgentStatusEvent) for event in result["events"])
    assert any(isinstance(event, AgentDoneEvent) and event.text == "回复内容" for event in result["events"])


@pytest.mark.asyncio
async def test_finish_node_returns_empty_when_run_already_failed() -> None:
    graph_state = _graph_state(failed=True)

    result = await _finish_node(graph_state)

    assert result["agent_state"].status == AgentRunStatus.RUNNING
    assert result["events"] == []


@pytest.mark.asyncio
async def test_finish_node_handles_invalid_json_from_model() -> None:
    graph_state = _graph_state()
    graph_state["agent_state"].response_text = "{not-json"

    result = await _finish_node(graph_state)

    assert result["agent_state"].status == AgentRunStatus.SUCCESS
    assert any(isinstance(event, AgentDoneEvent) and event.text == "{not-json" for event in result["events"])


@pytest.mark.asyncio
async def test_finish_node_returns_empty_when_model_times_out() -> None:
    graph_state = _graph_state(failed=True)
    graph_state["agent_state"].error_code = "TimeoutError"

    result = await _finish_node(graph_state)

    assert result["agent_state"].error_code == "TimeoutError"
    assert result["events"] == []


@pytest.mark.asyncio
async def test_finish_node_raises_when_route_is_missing() -> None:
    graph_state = _graph_state()
    graph_state["agent_state"].route = None

    with pytest.raises(AttributeError):
        await _finish_node(graph_state)


@pytest.mark.asyncio
async def test_finish_node_raises_when_events_list_is_missing() -> None:
    graph_state = _graph_state()
    del graph_state["events"]

    with pytest.raises(KeyError):
        await _finish_node(graph_state)
