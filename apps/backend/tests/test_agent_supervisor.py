from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from tests.agent_runtime_fakes import make_state

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.agents.contracts import (
    AgentResultEnvelope,
    ExecutionPlan,
    IndependentAgentRoleId,
    PrivacyClass,
    WorkItem,
)
from app.agents.execution_policy import ExecutionPolicyError, mark_terminal
from app.agents.nodes.supervisor import SupervisorNode
from app.agents.registry import default_agent_registry
from app.agents.state import MultiAgentGraphState


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _item(
    work_item_id: str,
    role_id: IndependentAgentRoleId,
    *,
    input_key: str,
    depends_on: tuple[str, ...] = (),
    requested_tools: tuple[str, ...] = (),
    context_characters: int = 100,
    retry_policy: str = "none",
) -> WorkItem:
    capability = default_agent_registry.get_role_capability(role_id)
    return WorkItem(
        work_item_id=work_item_id,
        role_id=role_id.value,
        input_ref=f"input:{input_key}",
        normalized_input_hash=_hash(input_key),
        expected_output_schema=capability.policy.output_schema,
        depends_on=depends_on,
        privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
        requested_tools=requested_tools,
        timeout_ms=int(capability.policy.budget.timeout_seconds * 1_000),
        context_characters=context_characters,
        retry_policy=retry_policy,
    )


def _plan(*items: WorkItem) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-1",
        planning_round=1,
        work_items=items,
    )


def _planning_result(plan: ExecutionPlan, *, known_usage: bool = True) -> dict:
    return {
        "plan": plan.model_dump(mode="json"),
        "input_tokens": 20 if known_usage else None,
        "output_tokens": 10 if known_usage else None,
        "estimated_cost_usd": 0.001 if known_usage else None,
    }


def _state() -> MultiAgentGraphState:
    return MultiAgentGraphState(
        run_id="run-1",
        source_message_id="message-1",
        input_ref="message:message-1",
    )


def _result(item: WorkItem, *, status: str = "success", error: str | None = None) -> AgentResultEnvelope:
    return AgentResultEnvelope(
        task_id=item.work_item_id,
        role_id=IndependentAgentRoleId(item.role_id),
        status=status,
        output_schema=item.expected_output_schema,
        output={"work_item_id": item.work_item_id},
        safe_error_code=error,
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=0.001,
    )


def test_supervisor_dispatches_two_distinct_registered_specialists_sequentially() -> None:
    first = _item(
        "work-retrieval",
        IndependentAgentRoleId.RETRIEVAL,
        input_key="project atlas",
        requested_tools=("search_vault_fts",),
        retry_policy="transient_read_once",
    )
    second = _item(
        "work-analysis",
        IndependentAgentRoleId.ANALYST_PLANNER,
        input_key="analyze atlas evidence",
        depends_on=(first.work_item_id,),
        retry_policy="transient_read_once",
    )
    calls = []

    async def handler(item, state):
        calls.append((item.role_id, tuple(state.completed_work_ids)))
        return _result(item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(first, second)),
            registry=default_agent_registry,
            role_handlers={first.role_id: handler, second.role_id: handler},
        )(_state())
    )

    assert outcome.fallback_reason is None
    assert outcome.dispatched_role_ids == (first.role_id, second.role_id)
    assert calls == [(first.role_id, ()), (second.role_id, (first.work_item_id,))]
    assert outcome.state.completed_work_ids == {first.work_item_id, second.work_item_id}
    assert outcome.state.budget_usage.planning_rounds == 1
    assert outcome.state.budget_usage.model_calls == 3
    assert outcome.state.budget_usage.specialist_dispatches == 2
    assert outcome.state.budget_usage.tool_calls == 1
    assert outcome.state.budget_usage.observed_input_tokens == 40
    assert outcome.state.terminal == "done"


@pytest.mark.parametrize(
    ("item", "reason"),
    (
        (
            WorkItem(
                work_item_id="unknown-role",
                role_id="user_supplied_agent",
                input_ref="input:1",
                normalized_input_hash=_hash("1"),
                expected_output_schema="UnknownOutput",
                privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
                timeout_ms=1_000,
            ),
            "unknown_role",
        ),
        (
            _item(
                "write-tool",
                IndependentAgentRoleId.RETRIEVAL,
                input_key="unsafe",
                requested_tools=("delete_vault",),
            ),
            "unknown_tool",
        ),
    ),
)
def test_invalid_or_escalated_plans_fail_closed_without_dispatch(item: WorkItem, reason: str) -> None:
    calls = []
    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(item)),
            registry=default_agent_registry,
            role_handlers={item.role_id: lambda work, state: calls.append(work)},
        )(_state())
    )

    assert outcome.fallback_reason == reason
    assert outcome.dispatched_role_ids == ()
    assert calls == []
    assert outcome.state.fallback_triggered is True
    assert outcome.state.terminal == "done"


def test_duplicate_role_plus_normalized_input_is_executed_once() -> None:
    first = _item("work-1", IndependentAgentRoleId.RETRIEVAL, input_key="same")
    duplicate = _item("work-2", IndependentAgentRoleId.RETRIEVAL, input_key="same")
    calls = []

    async def handler(item, state):
        calls.append(item.work_item_id)
        return _result(item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(first, duplicate)),
            registry=default_agent_registry,
            role_handlers={first.role_id: handler},
        )(_state())
    )

    assert calls == [first.work_item_id]
    assert outcome.state.skipped_duplicate_work_ids == {duplicate.work_item_id}
    assert outcome.state.completed_work_ids == {first.work_item_id, duplicate.work_item_id}
    assert outcome.state.budget_usage.specialist_dispatches == 1


def test_unknown_provider_usage_stops_before_specialist_dispatch() -> None:
    item = _item("work-1", IndependentAgentRoleId.RETRIEVAL, input_key="query")
    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(item), known_usage=False),
            registry=default_agent_registry,
            role_handlers={item.role_id: lambda work, state: _result(work)},
        )(_state())
    )

    assert outcome.fallback_reason == "provider_usage_unknown"
    assert outcome.dispatched_role_ids == ()
    assert outcome.state.budget_usage.observed_input_tokens is None
    assert outcome.state.budget_usage.observed_estimated_cost_usd is None


def test_global_context_budget_exhaustion_stops_later_work() -> None:
    first = _item(
        "work-1",
        IndependentAgentRoleId.ANALYST_PLANNER,
        input_key="one",
        context_characters=30_000,
    )
    second = _item(
        "work-2",
        IndependentAgentRoleId.ANALYST_PLANNER,
        input_key="two",
        context_characters=30_000,
    )
    calls = []

    async def handler(item, state):
        calls.append(item.work_item_id)
        return _result(item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(first, second)),
            registry=default_agent_registry,
            role_handlers={first.role_id: handler},
        )(_state())
    )

    assert outcome.fallback_reason == "context_budget_exceeded"
    assert calls == [first.work_item_id]
    assert outcome.state.terminal == "done"


def test_transient_read_retry_occurs_once_within_shared_repair_budget() -> None:
    item = _item(
        "work-1",
        IndependentAgentRoleId.RETRIEVAL,
        input_key="retry",
        retry_policy="transient_read_once",
    )
    attempts = 0

    async def handler(work, state):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _result(work, status="failed", error="provider_timeout")
        return _result(work)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(item)),
            registry=default_agent_registry,
            role_handlers={item.role_id: handler},
        )(_state())
    )

    assert attempts == 2
    assert outcome.dispatched_role_ids == (item.role_id, item.role_id)
    assert outcome.state.budget_usage.repairs == 1
    assert outcome.state.budget_usage.specialist_dispatches == 2
    assert outcome.state.terminal == "done"


def test_dependency_cycle_fails_closed_and_terminal_is_first_wins() -> None:
    first = _item(
        "work-1",
        IndependentAgentRoleId.RETRIEVAL,
        input_key="one",
        depends_on=("work-2",),
    )
    second = _item(
        "work-2",
        IndependentAgentRoleId.ANALYST_PLANNER,
        input_key="two",
        depends_on=("work-1",),
    )
    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(first, second)),
            registry=default_agent_registry,
            role_handlers={},
        )(_state())
    )

    assert outcome.fallback_reason == "dependency_cycle"
    assert outcome.state.terminal == "done"
    with pytest.raises(ExecutionPolicyError, match="terminal_already_committed"):
        mark_terminal(outcome.state, "error")


class _RuntimeSupervisorModel:
    def __init__(self, plan: ExecutionPlan) -> None:
        self.plan = plan
        self.calls = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if system_prompt == "supervisor-plan-v1":
            return json.dumps(_planning_result(self.plan))
        return "supervisor synthesis"


class _SupervisorRuntime(LangGraphAgentRuntime):
    def __init__(self, *, plan: ExecutionPlan, calls: list[str]) -> None:
        self._test_calls = calls
        super().__init__(
            AgentRuntimeServices(
                chat_model=_RuntimeSupervisorModel(plan),
                automation_settings=SimpleNamespace(use_negotiation=True, use_supervisor=True),
            )
        )

    def _supervisor_role_handlers(self):
        async def handler(item, state):
            self._test_calls.append(item.role_id)
            return _result(item)

        return {
            IndependentAgentRoleId.RETRIEVAL.value: handler,
            IndependentAgentRoleId.ANALYST_PLANNER.value: handler,
        }


def test_runtime_feature_path_dispatches_two_roles_and_keeps_one_public_terminal() -> None:
    first = _item("work-1", IndependentAgentRoleId.RETRIEVAL, input_key="runtime-one")
    second = _item(
        "work-2",
        IndependentAgentRoleId.ANALYST_PLANNER,
        input_key="runtime-two",
        depends_on=(first.work_item_id,),
    )
    calls = []

    async def run_case():
        runtime = _SupervisorRuntime(plan=_plan(first, second), calls=calls)
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())
    names = [event.event for event in events]

    assert calls == [first.role_id, second.role_id]
    assert "negotiation_step" in names
    assert "negotiation_done" in names
    assert names[-1] == "done"
    assert sum(name in {"done", "error"} for name in names) == 1


def test_simple_chat_does_not_enter_supervisor_graph() -> None:
    plan = _plan(_item("work-1", IndependentAgentRoleId.RETRIEVAL, input_key="unused"))
    calls = []

    async def run_case():
        runtime = _SupervisorRuntime(plan=plan, calls=calls)
        return [event async for event in runtime.run(make_state("你好"))]

    events = asyncio.run(run_case())

    assert calls == []
    assert [event.event for event in events if event.event in {"negotiation_step", "negotiation_done"}] == []
    assert [event.event for event in events][-1] == "done"
