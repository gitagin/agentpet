from __future__ import annotations

from collections.abc import Iterable

from .contracts import (
    AgentResultEnvelope,
    AgentTask,
    BudgetUsage,
    ExecutionBudget,
    ExecutionPlan,
    IndependentAgentRoleId,
    WorkItem,
)
from .registry import AgentRegistry, AgentRegistryError
from .state import MultiAgentGraphState


READ_ONLY_RETRYABLE_ROLES = frozenset(
    {
        IndependentAgentRoleId.RETRIEVAL,
        IndependentAgentRoleId.MEMORY,
        IndependentAgentRoleId.ANALYST_PLANNER,
        IndependentAgentRoleId.REVIEWER,
    }
)
RETRYABLE_ERROR_CODES = frozenset({"provider_timeout", "provider_unavailable"})


class ExecutionPolicyError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_execution_plan(
    plan: ExecutionPlan,
    *,
    state: MultiAgentGraphState,
    registry: AgentRegistry,
) -> None:
    if plan.registry_version != state.registry_version:
        raise ExecutionPolicyError("registry_version_mismatch")
    if plan.planning_round > state.budget_limit.max_planning_rounds:
        raise ExecutionPolicyError("planning_rounds_exceeded")
    work_ids = {item.work_item_id for item in plan.work_items}
    for item in plan.work_items:
        if any(dependency not in work_ids for dependency in item.depends_on):
            raise ExecutionPolicyError("unknown_dependency")
        try:
            capability = registry.get_role_capability(item.role_id)
        except AgentRegistryError as exc:
            raise ExecutionPolicyError(exc.code) from exc
        policy = capability.policy
        if item.timeout_ms > int(policy.budget.timeout_seconds * 1_000):
            raise ExecutionPolicyError("role_timeout_exceeded")
        if item.retry_policy == "transient_read_once":
            if policy.role_id not in READ_ONLY_RETRYABLE_ROLES or policy.retry_policy.max_retries < 1:
                raise ExecutionPolicyError("retry_not_permitted")
        task = AgentTask(
            task_id=item.work_item_id,
            role_id=item.role_id,
            input_ref=item.input_ref,
            expected_output_schema=item.expected_output_schema,
            requested_tools=item.requested_tools,
            privacy_class=item.privacy_class,
            budget=ExecutionBudget(
                max_calls=1,
                timeout_seconds=item.timeout_ms / 1_000,
                max_input_tokens=policy.budget.max_input_tokens,
                max_output_tokens=policy.budget.max_output_tokens,
                max_tool_calls=len(item.requested_tools),
                max_cost_usd=policy.budget.max_cost_usd,
            ),
            requested_by="supervisor",
        )
        try:
            registry.validate_task(task)
        except AgentRegistryError as exc:
            raise ExecutionPolicyError(exc.code) from exc
    _validate_acyclic(plan.work_items)


def reserve_planning_call(state: MultiAgentGraphState) -> MultiAgentGraphState:
    usage = state.budget_usage
    limit = state.budget_limit
    updated = usage.model_copy(
        update={
            "planning_rounds": usage.planning_rounds + 1,
            "supervisor_calls": usage.supervisor_calls + 1,
            "model_calls": usage.model_calls + 1,
            "reserved_input_tokens": usage.reserved_input_tokens + 4_000,
            "reserved_output_tokens": usage.reserved_output_tokens + 1_000,
            "reserved_estimated_cost_usd": usage.reserved_estimated_cost_usd + 0.01,
        }
    )
    if updated.planning_rounds > limit.max_planning_rounds:
        raise ExecutionPolicyError("planning_rounds_exceeded")
    if updated.supervisor_calls > limit.max_supervisor_calls:
        raise ExecutionPolicyError("supervisor_calls_exceeded")
    if updated.model_calls > limit.max_model_calls:
        raise ExecutionPolicyError("model_calls_exceeded")
    _assert_usage_within_limit(updated, state)
    return _transition(state, budget_usage=updated)


def record_provider_usage(
    state: MultiAgentGraphState,
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    estimated_cost_usd: float | None,
) -> MultiAgentGraphState:
    usage = state.budget_usage
    usage_complete = usage.provider_usage_complete and all(
        value is not None for value in (input_tokens, output_tokens, estimated_cost_usd)
    )
    updated = usage.model_copy(
        update={
            "observed_input_tokens": (
                (usage.observed_input_tokens or 0) + int(input_tokens or 0)
                if usage_complete
                else None
            ),
            "observed_output_tokens": (
                (usage.observed_output_tokens or 0) + int(output_tokens or 0)
                if usage_complete
                else None
            ),
            "observed_estimated_cost_usd": (
                (usage.observed_estimated_cost_usd or 0.0) + float(estimated_cost_usd or 0.0)
                if usage_complete
                else None
            ),
            "provider_usage_complete": usage_complete,
        }
    )
    _assert_usage_within_limit(updated, state)
    return _transition(state, budget_usage=updated)


def accept_execution_plan(
    state: MultiAgentGraphState,
    plan: ExecutionPlan,
) -> MultiAgentGraphState:
    return _transition(state, execution_plan=plan)


def reserve_work_item(
    state: MultiAgentGraphState,
    item: WorkItem,
    *,
    registry: AgentRegistry,
    retry: bool = False,
) -> MultiAgentGraphState:
    call_key = work_call_key(item)
    if call_key in state.executed_call_keys and not retry:
        return _transition(
            state,
            completed_work_ids=state.completed_work_ids | {item.work_item_id},
            skipped_duplicate_work_ids=state.skipped_duplicate_work_ids | {item.work_item_id},
        )
    usage = state.budget_usage
    if usage.specialist_dispatches > 0 and not usage.provider_usage_complete:
        raise ExecutionPolicyError("provider_usage_unknown")
    capability = registry.get_role_capability(item.role_id)
    policy = capability.policy
    role_tools = dict(usage.tool_calls_by_role)
    role_tools[item.role_id] = role_tools.get(item.role_id, 0) + len(item.requested_tools)
    updated = usage.model_copy(
        update={
            "model_calls": usage.model_calls + 1,
            "specialist_dispatches": usage.specialist_dispatches + 1,
            "tool_calls": usage.tool_calls + len(item.requested_tools),
            "repairs": usage.repairs + int(retry),
            "context_characters": usage.context_characters + item.context_characters,
            "reserved_input_tokens": usage.reserved_input_tokens + policy.budget.max_input_tokens,
            "reserved_output_tokens": usage.reserved_output_tokens + policy.budget.max_output_tokens,
            "reserved_estimated_cost_usd": (
                usage.reserved_estimated_cost_usd + policy.budget.max_cost_usd
            ),
            "tool_calls_by_role": role_tools,
        }
    )
    _assert_usage_within_limit(updated, state)
    return _transition(
        state,
        budget_usage=updated,
        executed_call_keys=state.executed_call_keys | {call_key},
    )


def complete_work_item(
    state: MultiAgentGraphState,
    item: WorkItem,
    result: AgentResultEnvelope,
    *,
    active_elapsed_ms: int,
) -> MultiAgentGraphState:
    if result.task_id != item.work_item_id or result.role_id.value != item.role_id:
        raise ExecutionPolicyError("result_identity_mismatch")
    usage = state.budget_usage
    usage_complete = usage.provider_usage_complete and all(
        value is not None
        for value in (result.input_tokens, result.output_tokens, result.estimated_cost_usd)
    )
    observed_input = (
        (usage.observed_input_tokens or 0) + int(result.input_tokens or 0)
        if usage_complete
        else None
    )
    observed_output = (
        (usage.observed_output_tokens or 0) + int(result.output_tokens or 0)
        if usage_complete
        else None
    )
    observed_cost = (
        (usage.observed_estimated_cost_usd or 0.0) + float(result.estimated_cost_usd or 0.0)
        if usage_complete
        else None
    )
    updated = usage.model_copy(
        update={
            "observed_input_tokens": observed_input,
            "observed_output_tokens": observed_output,
            "observed_estimated_cost_usd": observed_cost,
            "provider_usage_complete": usage_complete,
            "active_elapsed_ms": max(usage.active_elapsed_ms, active_elapsed_ms),
        }
    )
    _assert_usage_within_limit(updated, state)
    return _transition(
        state,
        budget_usage=updated,
        completed_work_ids=state.completed_work_ids | {item.work_item_id},
        results=(*state.results, result),
    )


def ready_work_items(state: MultiAgentGraphState) -> tuple[WorkItem, ...]:
    plan = state.execution_plan
    if plan is None:
        return ()
    return tuple(
        item
        for item in plan.work_items
        if item.work_item_id not in state.completed_work_ids
        and set(item.depends_on).issubset(state.completed_work_ids)
    )


def should_retry(item: WorkItem, result: AgentResultEnvelope, *, registry: AgentRegistry) -> bool:
    if item.retry_policy != "transient_read_once" or result.safe_error_code not in RETRYABLE_ERROR_CODES:
        return False
    capability = registry.get_role_capability(item.role_id)
    return (
        capability.policy.role_id in READ_ONLY_RETRYABLE_ROLES
        and capability.policy.retry_policy.max_retries == 1
    )


def mark_fallback(state: MultiAgentGraphState, reason: str) -> MultiAgentGraphState:
    return _transition(state, fallback_triggered=True, fallback_reason=reason)


def mark_terminal(state: MultiAgentGraphState, terminal: str) -> MultiAgentGraphState:
    if state.terminal is not None:
        raise ExecutionPolicyError("terminal_already_committed")
    if terminal not in {"done", "error", "cancelled"}:
        raise ExecutionPolicyError("invalid_terminal")
    return _transition(state, terminal=terminal)


def work_call_key(item: WorkItem) -> str:
    return f"{item.role_id}:{item.normalized_input_hash}"


def _assert_usage_within_limit(usage: BudgetUsage, state: MultiAgentGraphState) -> None:
    limit = state.budget_limit
    checks = (
        (usage.model_calls, limit.max_model_calls, "model_calls_exceeded"),
        (usage.specialist_dispatches, limit.max_specialist_dispatches, "specialist_dispatches_exceeded"),
        (usage.tool_calls, limit.max_tool_calls, "tool_calls_exceeded"),
        (usage.repairs, limit.max_repairs, "repair_budget_exceeded"),
        (usage.context_characters, limit.max_context_characters, "context_budget_exceeded"),
        (usage.reserved_input_tokens, limit.max_input_tokens, "input_token_budget_exceeded"),
        (usage.reserved_output_tokens, limit.max_output_tokens, "output_token_budget_exceeded"),
        (usage.active_elapsed_ms, limit.max_elapsed_ms, "elapsed_budget_exceeded"),
    )
    for actual, maximum, code in checks:
        if actual > maximum:
            raise ExecutionPolicyError(code)
    if usage.reserved_estimated_cost_usd > limit.max_estimated_cost_usd:
        raise ExecutionPolicyError("cost_budget_exceeded")
    if any(count > limit.max_tool_calls_per_role for count in usage.tool_calls_by_role.values()):
        raise ExecutionPolicyError("role_tool_calls_exceeded")
    if usage.observed_input_tokens is not None and usage.observed_input_tokens > limit.max_input_tokens:
        raise ExecutionPolicyError("input_token_budget_exceeded")
    if usage.observed_output_tokens is not None and usage.observed_output_tokens > limit.max_output_tokens:
        raise ExecutionPolicyError("output_token_budget_exceeded")
    if (
        usage.observed_estimated_cost_usd is not None
        and usage.observed_estimated_cost_usd > limit.max_estimated_cost_usd
    ):
        raise ExecutionPolicyError("cost_budget_exceeded")


def _validate_acyclic(items: Iterable[WorkItem]) -> None:
    dependencies = {item.work_item_id: set(item.depends_on) for item in items}
    remaining = dict(dependencies)
    while remaining:
        ready = {work_id for work_id, deps in remaining.items() if not deps.intersection(remaining)}
        if not ready:
            raise ExecutionPolicyError("dependency_cycle")
        for work_id in ready:
            remaining.pop(work_id)


def _transition(state: MultiAgentGraphState, **updates) -> MultiAgentGraphState:
    return state.model_copy(
        update={
            **updates,
            "transition_sequence": state.transition_sequence + 1,
        }
    )
