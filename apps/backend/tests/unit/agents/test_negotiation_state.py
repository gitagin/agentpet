from __future__ import annotations

from app.agents.state import AgentInvocationResult, AgentState, NegotiationState


def _state() -> NegotiationState:
    return NegotiationState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="帮我总结今天的状态",
    )


def test_negotiation_state_defaults() -> None:
    state = _state()

    assert state.round == 0
    assert state.max_rounds == 5
    assert state.confidence_threshold == 0.8
    assert state.invocation_history == []
    assert state.orchestrator_decisions == []
    assert state.collected_context == ""
    assert state.pending_proposals == []
    assert state.fallback_triggered is False


def test_negotiation_state_invocation_history_accepts_results() -> None:
    state = _state()
    result = AgentInvocationResult(
        agent_id="memory_retrieval_agent",
        round=1,
        input_query="今天的状态",
        output={"summary": "状态稳定"},
        confidence=0.72,
        latency_ms=120,
        tool_calls=["search_memory"],
    )

    state.invocation_history.append(result)

    assert state.invocation_history == [result]
    assert state.invocation_history[0].agent_id == "memory_retrieval_agent"
    assert state.invocation_history[0].tool_calls == ["search_memory"]


def test_negotiation_state_extends_agent_state() -> None:
    state = _state()

    assert isinstance(state, AgentState)
    assert state.conversation_id == "conversation-1"
    assert state.user_message == "帮我总结今天的状态"
