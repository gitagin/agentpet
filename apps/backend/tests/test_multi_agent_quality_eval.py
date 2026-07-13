from __future__ import annotations

import asyncio
import hashlib

from app.agents.contracts import ExecutionPlan, IndependentAgentRoleId, PrivacyClass, WorkItem
from app.agents.nodes.supervisor import SupervisorNode
from app.agents.registry import default_agent_registry
from app.agents.state import MultiAgentGraphState


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _state() -> MultiAgentGraphState:
    return MultiAgentGraphState(run_id="task-1215-quality", source_message_id="message-1", input_ref="message:message-1")


def _item(work_item_id: str, role_id: IndependentAgentRoleId, *, tool: str | None = None) -> WorkItem:
    policy = default_agent_registry.get_role_capability(role_id).policy
    return WorkItem(
        work_item_id=work_item_id,
        role_id=role_id.value,
        input_ref=f"input:{work_item_id}",
        normalized_input_hash=_hash(work_item_id),
        expected_output_schema=policy.output_schema,
        privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
        requested_tools=(tool,) if tool else (),
        timeout_ms=int(policy.budget.timeout_seconds * 1_000),
    )


def _plan(item: WorkItem) -> dict:
    plan = ExecutionPlan(plan_id="task-1215-plan", planning_round=1, work_items=(item,))
    return {"plan": plan.model_dump(mode="json"), "input_tokens": 20, "output_tokens": 10, "estimated_cost_usd": 0.001}


def test_deterministic_quality_contract_has_valid_plan_and_successful_role_dispatch() -> None:
    item = _item("read-vault", IndependentAgentRoleId.RETRIEVAL, tool="search_vault_fts")

    async def handler(work_item, state):
        from app.agents.contracts import AgentResultEnvelope

        return AgentResultEnvelope(
            task_id=work_item.work_item_id,
            role_id=IndependentAgentRoleId(work_item.role_id),
            status="success",
            output_schema=work_item.expected_output_schema,
            output={"evidence_candidates": []},
            input_tokens=10,
            output_tokens=5,
            estimated_cost_usd=0.001,
        )

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _plan(item),
            registry=default_agent_registry,
            role_handlers={item.role_id: handler},
        )(_state())
    )
    assert outcome.fallback_reason is None
    assert outcome.state.terminal == "done"
    assert outcome.state.completed_work_ids == {item.work_item_id}
    assert outcome.state.budget_usage.specialist_dispatches == 1
    assert outcome.state.budget_usage.tool_calls == 1


def test_quality_contract_rejects_unknown_role_and_write_tool_before_dispatch() -> None:
    unknown = WorkItem(
        work_item_id="invalid-role",
        role_id="user_supplied_role",
        input_ref="input:invalid",
        normalized_input_hash=_hash("invalid"),
        expected_output_schema="UnknownOutput",
        privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
        timeout_ms=1_000,
    )
    calls = []
    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _plan(unknown),
            registry=default_agent_registry,
            role_handlers={unknown.role_id: lambda work, state: calls.append(work)},
        )(_state())
    )
    assert outcome.fallback_reason == "unknown_role"
    assert calls == []
    assert outcome.state.terminal == "done"

    unsafe = _item("unsafe-tool", IndependentAgentRoleId.RETRIEVAL, tool="delete_vault")
    unsafe_outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _plan(unsafe),
            registry=default_agent_registry,
            role_handlers={unsafe.role_id: lambda work, state: calls.append(work)},
        )(_state())
    )
    assert unsafe_outcome.fallback_reason == "unknown_tool"
    assert calls == []
