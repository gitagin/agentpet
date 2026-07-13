from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..contracts import (
    AgentResultEnvelope,
    BranchExecutionRecord,
    DraftClaim,
    ExecutionPlan,
    IndependentAgentRoleId,
    ReviewDecision,
    ReviewInput,
    WorkItem,
)
from ..execution_policy import (
    ExecutionPolicyError,
    accept_execution_plan,
    complete_work_item,
    mark_fallback,
    mark_terminal,
    ready_work_items,
    record_provider_usage,
    reserve_planning_call,
    reserve_work_item,
    should_retry,
    validate_execution_plan,
    work_call_key,
)
from ..registry import AgentRegistry
from ..state import (
    MultiAgentGraphState,
    reduce_branch_records,
    reduce_merged_evidence,
    reduce_review_gate,
)
from .evidence_merge import merge_parallel_evidence
from ..roles.reviewer_agent import build_review_input


RoleHandler = Callable[[WorkItem, MultiAgentGraphState], Awaitable[AgentResultEnvelope] | AgentResultEnvelope]

_PARALLEL_READ_ONLY_ROLES = frozenset(
    {
        IndependentAgentRoleId.RETRIEVAL.value,
        IndependentAgentRoleId.MEMORY.value,
    }
)
_PARALLEL_READ_ONLY_TOOLS = frozenset(
    {
        "search_vault_fts",
        "search_vault_vector",
        "search_active_memory",
        "search_diary_objects",
        "search_daily_chat",
        "search_sqlite_graph",
    }
)
_DEFAULT_APPROVED_SCOPES = (
    "personal_memory",
    "diary",
    "daily_chat",
    "wiki",
    "vault_note",
    "graph",
)


class SupervisorPlanningResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: ExecutionPlan
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class SupervisorRunOutcome:
    state: MultiAgentGraphState
    dispatched_role_ids: tuple[str, ...]
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _BranchAttempt:
    item: WorkItem
    result: AgentResultEnvelope
    record: BranchExecutionRecord


class SupervisorNode:
    def __init__(
        self,
        *,
        planner: Any,
        registry: AgentRegistry,
        role_handlers: Mapping[str, RoleHandler],
        reviewer: Any | None = None,
        planning_timeout_seconds: float = 10.0,
        parallel_dispatch: bool = False,
        approved_scopes: Sequence[str] = _DEFAULT_APPROVED_SCOPES,
        cancellation_grace_seconds: float = 0.1,
    ) -> None:
        self.planner = planner
        self.registry = registry
        self.role_handlers = dict(role_handlers)
        self.reviewer = reviewer
        self.planning_timeout_seconds = max(0.001, min(float(planning_timeout_seconds), 10.0))
        self.parallel_dispatch = bool(parallel_dispatch)
        self.approved_scopes = tuple(dict.fromkeys(str(scope).strip() for scope in approved_scopes if str(scope).strip()))
        self.cancellation_grace_seconds = max(
            0.001,
            min(float(cancellation_grace_seconds), 0.5),
        )

    async def __call__(self, state: MultiAgentGraphState) -> SupervisorRunOutcome:
        started_ns = perf_counter_ns()
        dispatched_roles: list[str] = []
        try:
            state = reserve_planning_call(state)
            planning = await self._plan(state)
            state = record_provider_usage(
                state,
                input_tokens=planning.input_tokens,
                output_tokens=planning.output_tokens,
                estimated_cost_usd=planning.estimated_cost_usd,
            )
            if not state.budget_usage.provider_usage_complete:
                raise ExecutionPolicyError("provider_usage_unknown")
            validate_execution_plan(planning.plan, state=state, registry=self.registry)
            state = accept_execution_plan(state, planning.plan)
            state = await self._dispatch(
                state,
                dispatched_roles=dispatched_roles,
                started_ns=started_ns,
            )
            if self.reviewer is not None:
                state = await self._review_and_repair(
                    state,
                    started_ns=started_ns,
                    dispatched_roles=dispatched_roles,
                )
            else:
                merge = merge_parallel_evidence(
                    state.results,
                    approved_scopes=self.approved_scopes,
                )
                state = reduce_merged_evidence(state, merge.accepted)
            if state.fallback_triggered:
                state = mark_terminal(state, "done")
                return SupervisorRunOutcome(
                    state=state,
                    dispatched_role_ids=tuple(dispatched_roles),
                    fallback_reason=state.fallback_reason,
                )
            state = mark_terminal(state, "done")
            return SupervisorRunOutcome(state=state, dispatched_role_ids=tuple(dispatched_roles))
        except (ExecutionPolicyError, asyncio.TimeoutError, TimeoutError, ValueError, TypeError) as exc:
            reason = _safe_fallback_reason(exc)
            state = mark_fallback(state, reason)
            if state.terminal is None:
                state = mark_terminal(state, "done")
            return SupervisorRunOutcome(
                state=state,
                dispatched_role_ids=tuple(dispatched_roles),
                fallback_reason=reason,
            )
        except Exception:
            state = mark_fallback(state, "supervisor_failed")
            if state.terminal is None:
                state = mark_terminal(state, "done")
            return SupervisorRunOutcome(
                state=state,
                dispatched_role_ids=tuple(dispatched_roles),
                fallback_reason="supervisor_failed",
            )

    async def _plan(
        self,
        state: MultiAgentGraphState,
        *,
        review_feedback: Mapping[str, Any] | None = None,
    ) -> SupervisorPlanningResult:
        payload = {
            "schema_version": "supervisor-input.v1",
            "run_id": state.run_id,
            "source_message_id": state.source_message_id,
            "input_ref": state.input_ref,
            "registry_version": state.registry_version,
            "budget": state.budget_limit.model_dump(mode="json"),
            "capabilities": self.registry.describe_roles_for_supervisor(),
        }
        if review_feedback:
            payload["review_feedback"] = dict(review_feedback)
        raw = await asyncio.wait_for(
            _invoke(self.planner, payload),
            timeout=self.planning_timeout_seconds,
        )
        if isinstance(raw, SupervisorPlanningResult):
            return raw
        if isinstance(raw, str):
            raw = json.loads(raw)
        return SupervisorPlanningResult.model_validate(raw)

    async def _dispatch(
        self,
        state: MultiAgentGraphState,
        *,
        dispatched_roles: list[str],
        started_ns: int,
    ) -> MultiAgentGraphState:
        while state.execution_plan is not None and any(
            item.work_item_id not in state.completed_work_ids
            for item in state.execution_plan.work_items
        ):
            ready = ready_work_items(state)
            if not ready:
                raise ExecutionPolicyError("no_ready_work")
            parallel_items = self._parallel_items(ready)
            if len(parallel_items) >= 2:
                state = await self._dispatch_parallel_batch(
                    state,
                    items=parallel_items,
                    dispatched_roles=dispatched_roles,
                    started_ns=started_ns,
                )
                if state.fallback_triggered:
                    return state
                continue
            state = await self._dispatch_ready_sequential(
                state,
                ready=ready,
                dispatched_roles=dispatched_roles,
                started_ns=started_ns,
            )
        return state

    async def _review_and_repair(
        self,
        state: MultiAgentGraphState,
        *,
        started_ns: int,
        dispatched_roles: list[str],
    ) -> MultiAgentGraphState:
        """Run one independent review, with at most one targeted repair/replan."""

        state = self._merge_evidence(state)
        state = await self._run_review(state, repair_already_used=False)
        decision = state.review_decision
        if decision is None or decision.decision in {"pass", "reject", "escalate"}:
            return state
        if state.budget_usage.repairs >= state.budget_limit.max_repairs:
            return mark_fallback(state, "review_repair_budget_exceeded")

        state = self._reserve_review_repair(state)
        if decision.decision == "retry":
            state = await self._dispatch_review_retry(
                state,
                decision,
                started_ns=started_ns,
                dispatched_roles=dispatched_roles,
            )
        elif decision.decision == "replan":
            state = await self._dispatch_review_replan(
                state,
                decision,
                started_ns=started_ns,
                dispatched_roles=dispatched_roles,
            )
        else:
            return mark_fallback(state, "review_invalid_decision")
        if state.fallback_triggered:
            return state
        state = self._merge_evidence(state)
        state = await self._run_review(state, repair_already_used=True)
        if state.review_decision is not None and state.review_decision.decision in {"retry", "replan"}:
            return mark_fallback(state, "review_repair_exhausted")
        return state

    def _merge_evidence(self, state: MultiAgentGraphState) -> MultiAgentGraphState:
        merge = merge_parallel_evidence(
            state.results,
            approved_scopes=self.approved_scopes,
        )
        return reduce_merged_evidence(state, merge.accepted)

    async def _run_review(
        self,
        state: MultiAgentGraphState,
        *,
        repair_already_used: bool,
    ) -> MultiAgentGraphState:
        claims = _draft_claims_from_results(state.results)
        review_input = build_review_input(
            input_ref=state.input_ref,
            review_attempt=state.review_attempts + 1,
            repair_already_used=repair_already_used,
            draft_claims=claims,
            accepted_evidence=state.merged_evidence,
        )
        try:
            state = _reserve_reviewer_call(state)
            raw = await asyncio.wait_for(
                _invoke(self.reviewer, review_input),
                timeout=min(
                    10.0,
                    max(0.001, (state.budget_limit.max_elapsed_ms - state.budget_usage.active_elapsed_ms) / 1_000),
                ),
            )
            decision = _coerce_review_decision(raw)
            _validate_review_decision(decision, review_input)
        except (asyncio.TimeoutError, TimeoutError):
            return mark_fallback(state, "reviewer_timeout")
        except Exception:
            return mark_fallback(state, "reviewer_invalid_response")

        accepted_claims = tuple(
            claim for claim in claims if claim.claim_id in set(decision.supported_claim_ids)
        )
        accepted_citation_ids = set(decision.usable_citation_ids)
        accepted_evidence = tuple(
            evidence
            for evidence in state.merged_evidence
            if evidence.citation_id in accepted_citation_ids
        )
        if decision.decision != "pass":
            accepted_claims = ()
            accepted_evidence = ()
        return reduce_review_gate(
            state,
            decision=decision,
            draft_claims=claims,
            approved_claims=accepted_claims,
            approved_evidence=accepted_evidence,
        )

    async def _dispatch_review_retry(
        self,
        state: MultiAgentGraphState,
        decision: ReviewDecision,
        *,
        started_ns: int,
        dispatched_roles: list[str],
    ) -> MultiAgentGraphState:
        role_id = decision.retry_role_id
        if role_id is None or not decision.immutable_input_ref:
            return mark_fallback(state, "review_retry_missing_target")
        capability = self.registry.get_role_capability(role_id)
        query = _bounded_review_query(decision.missing_evidence_needs)
        item = WorkItem(
            work_item_id=f"review-repair-{state.review_attempts + 1}",
            role_id=role_id.value,
            input_ref=decision.immutable_input_ref,
            normalized_input_hash=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            expected_output_schema=capability.policy.output_schema,
            privacy_class=capability.policy.privacy_class,
            timeout_ms=int(capability.policy.budget.timeout_seconds * 1_000),
            context_characters=min(8_000, len(query)),
            retry_policy="none",
        )
        handler = self.role_handlers.get(item.role_id)
        if handler is None:
            return mark_fallback(state, "review_retry_role_unavailable")
        state = state.model_copy(update={"active_branch_id": item.work_item_id})
        state = self._reserve_repair_work_item(state, item)
        result = await self._invoke_role(handler, item, state)
        dispatched_roles.append(item.role_id)
        return complete_work_item(
            state,
            item,
            result,
            active_elapsed_ms=_elapsed_ms(started_ns),
        )

    async def _dispatch_review_replan(
        self,
        state: MultiAgentGraphState,
        decision: ReviewDecision,
        *,
        started_ns: int,
        dispatched_roles: list[str],
    ) -> MultiAgentGraphState:
        if not decision.immutable_input_ref:
            return mark_fallback(state, "review_replan_missing_target")
        state = reserve_planning_call(state)
        planning = await self._plan(
            state,
            review_feedback={
                "missing_evidence_needs": list(decision.missing_evidence_needs),
                "required_scopes": list(decision.required_scopes),
                "safe_summary_code": decision.safe_summary_code,
            },
        )
        state = record_provider_usage(
            state,
            input_tokens=planning.input_tokens,
            output_tokens=planning.output_tokens,
            estimated_cost_usd=planning.estimated_cost_usd,
        )
        if not state.budget_usage.provider_usage_complete:
            return mark_fallback(state, "provider_usage_unknown")
        if planning.plan.planning_round != 2:
            return mark_fallback(state, "review_replan_round_invalid")
        validate_execution_plan(planning.plan, state=state, registry=self.registry)
        if any(item.work_item_id in state.completed_work_ids for item in planning.plan.work_items):
            return mark_fallback(state, "review_replan_duplicate_work")
        state = accept_execution_plan(state, planning.plan)
        return await self._dispatch(
            state,
            dispatched_roles=dispatched_roles,
            started_ns=started_ns,
        )

    def _reserve_repair_work_item(self, state: MultiAgentGraphState, item: WorkItem) -> MultiAgentGraphState:
        from ..execution_policy import reserve_work_item

        return reserve_work_item(state, item, registry=self.registry)

    def _reserve_review_repair(self, state: MultiAgentGraphState) -> MultiAgentGraphState:
        usage = state.budget_usage.model_copy(update={"repairs": state.budget_usage.repairs + 1})
        if usage.repairs > state.budget_limit.max_repairs:
            raise ExecutionPolicyError("repair_budget_exceeded")
        return state.model_copy(update={"budget_usage": usage, "transition_sequence": state.transition_sequence + 1})

    def _parallel_items(self, ready: tuple[WorkItem, ...]) -> tuple[WorkItem, ...]:
        if not self.parallel_dispatch:
            return ()
        candidates = tuple(
            item
            for item in ready
            if item.branch_id is not None
            and item.role_id in _PARALLEL_READ_ONLY_ROLES
            and set(item.requested_tools).issubset(_PARALLEL_READ_ONLY_TOOLS)
            and inspect.iscoroutinefunction(self.role_handlers.get(item.role_id))
        )
        if len(candidates) < 2:
            return ()
        if len({item.branch_id for item in candidates}) != len(candidates):
            return ()
        if len({work_call_key(item) for item in candidates}) != len(candidates):
            return ()
        return tuple(sorted(candidates, key=lambda item: item.work_item_id))

    async def _dispatch_ready_sequential(
        self,
        state: MultiAgentGraphState,
        *,
        ready: tuple[WorkItem, ...],
        dispatched_roles: list[str],
        started_ns: int,
    ) -> MultiAgentGraphState:
        for item in ready:
            previous_completed = state.completed_work_ids
            state = reserve_work_item(state, item, registry=self.registry)
            if item.work_item_id in state.skipped_duplicate_work_ids:
                continue
            if state.completed_work_ids != previous_completed:
                continue
            handler = self.role_handlers.get(item.role_id)
            if handler is None:
                raise ExecutionPolicyError("role_handler_unavailable")
            result = await self._invoke_role(handler, item, state)
            dispatched_roles.append(item.role_id)
            state = complete_work_item(
                state,
                item,
                result,
                active_elapsed_ms=_elapsed_ms(started_ns),
            )
            if should_retry(item, result, registry=self.registry):
                state = reserve_work_item(state, item, registry=self.registry, retry=True)
                retry_result = await self._invoke_role(handler, item, state)
                dispatched_roles.append(item.role_id)
                state = complete_work_item(
                    state,
                    item,
                    retry_result,
                    active_elapsed_ms=_elapsed_ms(started_ns),
                )
        return state

    async def _dispatch_parallel_batch(
        self,
        state: MultiAgentGraphState,
        *,
        items: tuple[WorkItem, ...],
        dispatched_roles: list[str],
        started_ns: int,
    ) -> MultiAgentGraphState:
        for item in items:
            state = reserve_work_item(state, item, registry=self.registry)

        remaining_ms = state.budget_limit.max_elapsed_ms - max(
            state.budget_usage.active_elapsed_ms,
            _elapsed_ms(started_ns),
        )
        if remaining_ms <= 0:
            raise ExecutionPolicyError("elapsed_budget_exceeded")
        fair_share_seconds = max(0.001, remaining_ms / len(items) / 1_000)
        tasks: dict[asyncio.Task[_BranchAttempt], WorkItem] = {}
        for item in items:
            handler = self.role_handlers.get(item.role_id)
            if handler is None:
                raise ExecutionPolicyError("role_handler_unavailable")
            branch_state = state.model_copy(
                deep=True,
                update={"active_branch_id": item.branch_id},
            )
            timeout_seconds = min(item.timeout_ms / 1_000, fair_share_seconds)
            task = asyncio.create_task(
                self._run_branch(
                    handler,
                    item,
                    branch_state,
                    started_ns=started_ns,
                    timeout_seconds=timeout_seconds,
                ),
                name=f"agent-read-branch:{item.branch_id}",
            )
            tasks[task] = item
            dispatched_roles.append(item.role_id)

        attempts = await self._collect_parallel_attempts(
            tasks,
            batch_timeout_seconds=fair_share_seconds,
            started_ns=started_ns,
        )
        ordered_attempts = tuple(sorted(attempts, key=lambda attempt: attempt.item.work_item_id))
        state = reduce_branch_records(
            state,
            tuple(attempt.record for attempt in ordered_attempts),
        )
        active_compute_ms = state.budget_usage.active_elapsed_ms + math.ceil(
            sum(attempt.record.duration_ms for attempt in ordered_attempts)
        )
        final_results: dict[str, AgentResultEnvelope] = {}
        for attempt in ordered_attempts:
            state = complete_work_item(
                state,
                attempt.item,
                attempt.result,
                active_elapsed_ms=active_compute_ms,
            )
            final_results[attempt.item.work_item_id] = attempt.result

        for attempt in ordered_attempts:
            if not should_retry(attempt.item, attempt.result, registry=self.registry):
                continue
            try:
                state = reserve_work_item(state, attempt.item, registry=self.registry, retry=True)
            except ExecutionPolicyError as exc:
                if exc.code == "repair_budget_exceeded":
                    continue
                raise
            handler = self.role_handlers[attempt.item.role_id]
            retry_state = state.model_copy(
                deep=True,
                update={"active_branch_id": attempt.item.branch_id},
            )
            retry_attempt = await self._run_branch(
                handler,
                attempt.item,
                retry_state,
                started_ns=started_ns,
                timeout_seconds=attempt.item.timeout_ms / 1_000,
                attempt_number=2,
            )
            state = reduce_branch_records(state, (retry_attempt.record,))
            retry_result = retry_attempt.result
            dispatched_roles.append(attempt.item.role_id)
            active_compute_ms += math.ceil(retry_attempt.record.duration_ms)
            state = complete_work_item(
                state,
                attempt.item,
                retry_result,
                active_elapsed_ms=max(active_compute_ms, _elapsed_ms(started_ns)),
            )
            final_results[attempt.item.work_item_id] = retry_result

        completion_failure = self._parallel_completion_failure(
            items,
            final_results,
            state.execution_plan,
        )
        if completion_failure is not None:
            return mark_fallback(state, completion_failure)
        return state

    async def _collect_parallel_attempts(
        self,
        tasks: Mapping[asyncio.Task[_BranchAttempt], WorkItem],
        *,
        batch_timeout_seconds: float,
        started_ns: int,
    ) -> tuple[_BranchAttempt, ...]:
        pending = set(tasks)
        attempts: list[_BranchAttempt] = []
        deadline = asyncio.get_running_loop().time() + batch_timeout_seconds
        terminal_candidate_id = min(
            (
                item.work_item_id
                for item in tasks.values()
                if item.terminal_condition == "first_supported"
            ),
            default=None,
        )
        cancellation_reason = "branch_budget_cancelled"

        while pending:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            done, pending = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                break
            completed = [task.result() for task in done]
            attempts.extend(completed)
            if terminal_candidate_id is not None and any(
                attempt.item.work_item_id == terminal_candidate_id
                and attempt.result.status == "success"
                for attempt in completed
            ):
                cancellation_reason = "terminal_condition_reached"
                break

        if pending:
            for task in pending:
                task.cancel(cancellation_reason)
            done_after_cancel, still_pending = await asyncio.wait(
                pending,
                timeout=self.cancellation_grace_seconds,
            )
            attempts.extend(task.result() for task in done_after_cancel)
            for task in still_pending:
                task.add_done_callback(_consume_late_task)
                item = tasks[task]
                attempts.append(
                    _cancelled_attempt(
                        item,
                        started_ns=started_ns,
                        safe_error_code="branch_cancellation_timeout",
                    )
                )

        return tuple(attempts)

    async def _run_branch(
        self,
        handler: RoleHandler,
        item: WorkItem,
        state: MultiAgentGraphState,
        *,
        started_ns: int,
        timeout_seconds: float,
        attempt_number: int = 1,
    ) -> _BranchAttempt:
        branch_started_ns = perf_counter_ns()
        try:
            result = await self._invoke_role(
                handler,
                item,
                state,
                timeout_seconds=timeout_seconds,
            )
            status = result.status
            safe_error_code = result.safe_error_code
        except asyncio.CancelledError:
            status = "cancelled"
            safe_error_code = "branch_cancelled"
            result = _failed_result(item, safe_error_code=safe_error_code)
        except (asyncio.TimeoutError, TimeoutError):
            status = "timed_out"
            safe_error_code = "provider_timeout"
            result = _failed_result(item, safe_error_code=safe_error_code)
        except ExecutionPolicyError as exc:
            status = "failed"
            safe_error_code = exc.code
            result = _failed_result(item, safe_error_code=safe_error_code)
        except Exception:
            status = "failed"
            safe_error_code = "branch_failed"
            result = _failed_result(item, safe_error_code=safe_error_code)
        branch_finished_ns = perf_counter_ns()
        return _BranchAttempt(
            item=item,
            result=result,
            record=BranchExecutionRecord(
                branch_id=item.branch_id or item.work_item_id,
                work_item_id=item.work_item_id,
                attempt=attempt_number,
                role_id=IndependentAgentRoleId(item.role_id),
                status=status,
                started_offset_ms=_elapsed_ms_float(started_ns, branch_started_ns),
                finished_offset_ms=_elapsed_ms_float(started_ns, branch_finished_ns),
                duration_ms=_elapsed_ms_float(branch_started_ns, branch_finished_ns),
                safe_error_code=safe_error_code,
            ),
        )

    def _parallel_completion_failure(
        self,
        items: tuple[WorkItem, ...],
        final_results: Mapping[str, AgentResultEnvelope],
        plan: ExecutionPlan | None,
    ) -> str | None:
        successful_ids = {
            work_id for work_id, result in final_results.items() if result.status == "success"
        }
        failed_required = {
            item.work_item_id
            for item in items
            if item.terminal_condition == "required" and item.work_item_id not in successful_ids
        }
        if plan is None:
            return "execution_plan_missing"
        if plan.completion_rule == "all_required" and failed_required:
            return "parallel_required_branch_failed"
        if plan.completion_rule == "approved_partial_read" and not successful_ids:
            return "parallel_no_approved_result"
        return None

    async def _invoke_role(
        self,
        handler: RoleHandler,
        item: WorkItem,
        state: MultiAgentGraphState,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentResultEnvelope:
        raw = handler(item, state)
        if inspect.isawaitable(raw):
            raw = await asyncio.wait_for(
                raw,
                timeout=timeout_seconds or item.timeout_ms / 1_000,
            )
        capability = self.registry.get_role_capability(item.role_id)
        result = AgentResultEnvelope.model_validate(raw)
        if result.output_schema != capability.policy.output_schema:
            raise ExecutionPolicyError("output_schema_mismatch")
        if capability.output_model is not AgentResultEnvelope:
            capability.output_model.model_validate(result.output)
        return result


async def _invoke(target: Any, payload: Any) -> Any:
    if hasattr(target, "ainvoke"):
        result = target.ainvoke(payload)
    elif hasattr(target, "invoke"):
        result = target.invoke(payload)
    elif callable(target):
        result = target(payload)
    else:
        raise TypeError("Supervisor planner must be callable or expose invoke/ainvoke")
    if inspect.isawaitable(result):
        return await result
    return result


def _draft_claims_from_results(results: Sequence[AgentResultEnvelope]) -> tuple[DraftClaim, ...]:
    by_id: dict[str, DraftClaim] = {}
    for result in results:
        raw_claims = result.output.get("draft_claims", ())
        if not isinstance(raw_claims, list | tuple):
            continue
        for raw_claim in raw_claims:
            claim = DraftClaim.model_validate(raw_claim)
            by_id[claim.claim_id] = claim
    return tuple(by_id[claim_id] for claim_id in sorted(by_id))


def _coerce_review_decision(raw: Any) -> ReviewDecision:
    if isinstance(raw, ReviewDecision):
        return raw
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, Mapping) and "decision" in raw and isinstance(raw["decision"], Mapping):
        raw = raw["decision"]
    return ReviewDecision.model_validate(raw)


def _validate_review_decision(decision: ReviewDecision, review_input: ReviewInput) -> None:
    claim_by_id = {claim.claim_id: claim for claim in review_input.draft_claims}
    accepted_citation_ids = {
        evidence.citation_id for evidence in review_input.accepted_evidence
    }
    supported_claim_ids = set(decision.supported_claim_ids)
    unsupported_claim_ids = {claim.claim_id for claim in decision.unsupported_claims}
    if not supported_claim_ids.issubset(claim_by_id):
        raise ValueError("review supported an unknown claim")
    if not unsupported_claim_ids.issubset(claim_by_id):
        raise ValueError("review rejected an unknown claim")
    if not set(decision.usable_citation_ids).issubset(accepted_citation_ids):
        raise ValueError("review approved a fabricated citation")
    if decision.decision == "pass":
        if supported_claim_ids | unsupported_claim_ids != set(claim_by_id):
            raise ValueError("review pass left a claim unclassified")
        usable = set(decision.usable_citation_ids)
        for claim_id in supported_claim_ids:
            claim_citations = set(claim_by_id[claim_id].citation_ids)
            if not claim_citations or not claim_citations.issubset(usable):
                raise ValueError("review pass approved an unsupported claim")
    if decision.decision in {"retry", "replan"}:
        if review_input.repair_already_used:
            raise ValueError("review repair already used")
        if not decision.missing_evidence_needs:
            raise ValueError("review repair requires a bounded evidence need")


def _bounded_review_query(needs: Sequence[str]) -> str:
    normalized = tuple(
        " ".join(str(need).split())[:256]
        for need in needs[:3]
        if " ".join(str(need).split())
    )
    if not normalized:
        raise ValueError("review repair query is empty")
    return " | ".join(normalized)[:512]


def _reserve_reviewer_call(state: MultiAgentGraphState) -> MultiAgentGraphState:
    if state.review_attempts >= 2:
        raise ExecutionPolicyError("reviewer_calls_exceeded")
    usage = state.budget_usage
    updated = usage.model_copy(
        update={
            "model_calls": usage.model_calls + 1,
            "specialist_dispatches": usage.specialist_dispatches + 1,
            "reserved_input_tokens": usage.reserved_input_tokens + 8_000,
            "reserved_output_tokens": usage.reserved_output_tokens + 1_500,
            "reserved_estimated_cost_usd": usage.reserved_estimated_cost_usd + 0.01,
        }
    )
    limit = state.budget_limit
    checks = (
        (updated.model_calls, limit.max_model_calls, "model_calls_exceeded"),
        (
            updated.specialist_dispatches,
            limit.max_specialist_dispatches,
            "specialist_dispatches_exceeded",
        ),
        (updated.reserved_input_tokens, limit.max_input_tokens, "input_token_budget_exceeded"),
        (updated.reserved_output_tokens, limit.max_output_tokens, "output_token_budget_exceeded"),
    )
    for actual, maximum, code in checks:
        if actual > maximum:
            raise ExecutionPolicyError(code)
    if updated.reserved_estimated_cost_usd > limit.max_estimated_cost_usd + 1e-12:
        raise ExecutionPolicyError("cost_budget_exceeded")
    return state.model_copy(
        update={
            "budget_usage": updated,
            "transition_sequence": state.transition_sequence + 1,
        }
    )


def _failed_result(item: WorkItem, *, safe_error_code: str) -> AgentResultEnvelope:
    return AgentResultEnvelope(
        task_id=item.work_item_id,
        role_id=IndependentAgentRoleId(item.role_id),
        status="fallback",
        output_schema=item.expected_output_schema,
        output={},
        safe_error_code=safe_error_code,
        input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=None,
    )


def _cancelled_attempt(
    item: WorkItem,
    *,
    started_ns: int,
    safe_error_code: str,
) -> _BranchAttempt:
    offset_ms = float(_elapsed_ms(started_ns))
    return _BranchAttempt(
        item=item,
        result=_failed_result(item, safe_error_code=safe_error_code),
        record=BranchExecutionRecord(
            branch_id=item.branch_id or item.work_item_id,
            work_item_id=item.work_item_id,
            role_id=IndependentAgentRoleId(item.role_id),
            status="cancelled",
            started_offset_ms=offset_ms,
            finished_offset_ms=offset_ms,
            duration_ms=0.0,
            safe_error_code=safe_error_code,
        ),
    )


def _consume_late_task(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except (asyncio.CancelledError, Exception):
        return


def _elapsed_ms(started_ns: int) -> int:
    return max(0, int((perf_counter_ns() - started_ns) / 1_000_000))


def _elapsed_ms_float(started_ns: int, finished_ns: int) -> float:
    return max(0.0, (finished_ns - started_ns) / 1_000_000)


def _safe_fallback_reason(exc: Exception) -> str:
    if isinstance(exc, ExecutionPolicyError):
        return exc.code
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "supervisor_timeout"
    if isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)):
        return "supervisor_invalid_plan"
    return "supervisor_failed"
