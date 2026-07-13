from __future__ import annotations

import asyncio
import hashlib

import pytest

from app.agents.contracts import ExecutionPlan, IndependentAgentRoleId, PrivacyClass, WorkItem
from app.agents.execution_policy import ExecutionPolicyError, mark_terminal, reserve_planning_call
from app.agents.nodes.supervisor import SupervisorNode
from app.agents.registry import default_agent_registry
from app.agents.state import MultiAgentGraphState


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state() -> MultiAgentGraphState:
    return MultiAgentGraphState(run_id="task-1215-failure", source_message_id="message-1", input_ref="message:message-1")


def _item() -> WorkItem:
    policy = default_agent_registry.get_role_capability(IndependentAgentRoleId.RETRIEVAL).policy
    return WorkItem(
        work_item_id="failure-read",
        role_id=IndependentAgentRoleId.RETRIEVAL.value,
        input_ref="input:failure",
        normalized_input_hash=_hash("failure"),
        expected_output_schema=policy.output_schema,
        privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
        timeout_ms=int(policy.budget.timeout_seconds * 1_000),
    )


def test_provider_usage_unknown_stops_dispatch_without_claiming_zero_tokens() -> None:
    item = _item()
    plan = ExecutionPlan(plan_id="failure-plan", planning_round=1, work_items=(item,))
    calls = []
    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: {
                "plan": plan.model_dump(mode="json"),
                "input_tokens": None,
                "output_tokens": None,
                "estimated_cost_usd": None,
            },
            registry=default_agent_registry,
            role_handlers={item.role_id: lambda work, state: calls.append(work)},
        )(_state())
    )
    assert outcome.fallback_reason == "provider_usage_unknown"
    assert calls == []
    assert outcome.state.budget_usage.observed_input_tokens is None
    assert outcome.state.budget_usage.observed_output_tokens is None
    assert outcome.state.budget_usage.observed_estimated_cost_usd is None


def test_budget_exhaustion_and_duplicate_terminal_are_fail_closed() -> None:
    state = _state()
    exhausted = state.model_copy(update={"budget_limit": state.budget_limit.model_copy(update={"max_planning_rounds": 0})})
    with pytest.raises(ExecutionPolicyError, match="planning_rounds_exceeded"):
        reserve_planning_call(exhausted)

    terminal = mark_terminal(state, "done")
    with pytest.raises(ExecutionPolicyError, match="terminal_already_committed"):
        mark_terminal(terminal, "error")
