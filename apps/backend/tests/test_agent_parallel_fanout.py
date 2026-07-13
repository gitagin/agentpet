from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from tests.agent_runtime_fakes import make_state

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.agents.contracts import (
    AgentResultEnvelope,
    EvidenceEnvelope,
    ExecutionPlan,
    IndependentAgentRoleId,
    ParallelEvidenceCandidate,
    PrivacyClass,
    RetrievalProvenance,
    WorkItem,
)
from app.agents.nodes.evidence_merge import merge_parallel_evidence
from app.agents.nodes.supervisor import SupervisorNode
from app.agents.registry import default_agent_registry
from app.agents.state import MultiAgentGraphState


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _item(
    work_item_id: str,
    role_id: IndependentAgentRoleId,
    *,
    branch_id: str,
    input_key: str | None = None,
    timeout_ms: int = 1_000,
    terminal_condition: str = "required",
    retry_policy: str = "none",
    requested_tools: tuple[str, ...] = (),
) -> WorkItem:
    capability = default_agent_registry.get_role_capability(role_id)
    input_key = input_key or work_item_id
    return WorkItem(
        work_item_id=work_item_id,
        role_id=role_id.value,
        input_ref=f"input:{input_key}",
        normalized_input_hash=_hash(input_key),
        expected_output_schema=capability.policy.output_schema,
        branch_id=branch_id,
        privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
        requested_tools=requested_tools,
        timeout_ms=timeout_ms,
        retry_policy=retry_policy,
        terminal_condition=terminal_condition,
    )


def _plan(
    *items: WorkItem,
    completion_rule: str = "all_required",
) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="parallel-plan",
        planning_round=1,
        work_items=items,
        completion_rule=completion_rule,
    )


def _planning_result(plan: ExecutionPlan) -> dict:
    return {
        "plan": plan.model_dump(mode="json"),
        "input_tokens": 20,
        "output_tokens": 10,
        "estimated_cost_usd": 0.001,
    }


def _state() -> MultiAgentGraphState:
    return MultiAgentGraphState(
        run_id="parallel-run",
        source_message_id="parallel-message",
        input_ref="message:parallel-message",
    )


def _result(
    item: WorkItem,
    *,
    output: dict | None = None,
    status: str = "success",
    safe_error_code: str | None = None,
) -> AgentResultEnvelope:
    return AgentResultEnvelope(
        task_id=item.work_item_id,
        role_id=IndependentAgentRoleId(item.role_id),
        status=status,
        output_schema=item.expected_output_schema,
        output=output or {},
        safe_error_code=safe_error_code,
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=0.001,
    )


def _candidate(
    citation_id: str,
    *,
    scope: str,
    channel: str,
    rank: int,
    content_key: str,
    permission_allowed: bool = True,
) -> dict:
    evidence = EvidenceEnvelope(
        citation_id=citation_id,
        source=f"{scope}/{citation_id}.md",
        chunk_id=f"chunk:{citation_id}",
        permitted_excerpt=f"accepted excerpt for {citation_id}",
        lifecycle_status="active",
        confidence=0.9,
        retrieval_provenance=(
            RetrievalProvenance(
                channel=channel,
                rank=rank,
                score_component=1.0 / (60 + rank),
            ),
        ),
    )
    return ParallelEvidenceCandidate(
        stable_id=citation_id,
        content_hash=_hash(content_key),
        source_scope=scope,
        permission_allowed=permission_allowed,
        evidence=evidence,
    ).model_dump(mode="json")


async def _run_overlap_once() -> tuple[object, float]:
    retrieval = _item(
        "read-vault",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-vault",
        requested_tools=("search_vault_fts",),
    )
    memory = _item(
        "read-memory",
        IndependentAgentRoleId.MEMORY,
        branch_id="branch-memory",
        requested_tools=("search_active_memory",),
    )

    async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
        assert state.active_branch_id == item.branch_id
        await asyncio.sleep(0.09 if item.role_id == retrieval.role_id else 0.12)
        return _result(item)

    started = perf_counter()
    outcome = await SupervisorNode(
        planner=lambda payload: _planning_result(_plan(retrieval, memory)),
        registry=default_agent_registry,
        role_handlers={retrieval.role_id: handler, memory.role_id: handler},
        parallel_dispatch=True,
    )(_state())
    return outcome, (perf_counter() - started) * 1_000


def test_parallel_fanout_measures_real_temporal_overlap() -> None:
    run_count = max(1, min(int(os.getenv("TASK1210_RUNS", "1")), 10))
    measurements: list[dict[str, object]] = []

    for run_number in range(1, run_count + 1):
        outcome, wall_ms = asyncio.run(_run_overlap_once())
        records = outcome.state.branch_records
        overlap_ms = min(record.finished_offset_ms for record in records) - max(
            record.started_offset_ms for record in records
        )
        sequential_sum_ms = sum(record.duration_ms for record in records)

        assert outcome.fallback_reason is None
        assert outcome.state.parallel_dispatch_used is True
        assert outcome.state.terminal == "done"
        assert len(records) == 2
        assert outcome.state.budget_usage.model_calls == 3
        assert outcome.state.budget_usage.tool_calls == 2
        assert outcome.state.budget_usage.reserved_input_tokens == 12_000
        assert outcome.state.budget_usage.reserved_output_tokens == 3_000
        assert outcome.state.budget_usage.reserved_estimated_cost_usd == 0.02
        assert outcome.state.budget_usage.observed_input_tokens == 40
        assert outcome.state.budget_usage.observed_output_tokens == 20
        assert outcome.state.budget_usage.observed_estimated_cost_usd == 0.003
        assert overlap_ms >= 50
        assert wall_ms < sequential_sum_ms * 0.8
        measurements.append(
            {
                "run": run_number,
                "wall_ms": round(wall_ms, 3),
                "sequential_sum_ms": round(sequential_sum_ms, 3),
                "overlap_ms": round(overlap_ms, 3),
                "terminal_count": 1,
                "work_item_ids": [record.work_item_id for record in records],
            }
        )

    output_path = os.getenv("TASK1210_OVERLAP_OUTPUT")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(measurements, indent=2), encoding="utf-8")


def test_reversed_completion_order_yields_identical_results_and_evidence() -> None:
    retrieval = _item(
        "a-vault",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-vault",
    )
    memory = _item(
        "b-memory",
        IndependentAgentRoleId.MEMORY,
        branch_id="branch-memory",
    )
    outputs = {
        retrieval.work_item_id: {
            "evidence_candidates": [
                _candidate(
                    "citation:shared",
                    scope="wiki",
                    channel="fts",
                    rank=1,
                    content_key="shared",
                ),
                _candidate(
                    "citation:vault-only",
                    scope="wiki",
                    channel="fts",
                    rank=2,
                    content_key="vault-only",
                ),
            ]
        },
        memory.work_item_id: {
            "evidence_candidates": [
                _candidate(
                    "citation:shared",
                    scope="personal_memory",
                    channel="active_memory",
                    rank=2,
                    content_key="shared",
                )
            ]
        },
    }

    async def run(delays: dict[str, float]):
        async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
            await asyncio.sleep(delays[item.work_item_id])
            return _result(item, output=outputs[item.work_item_id])

        return await SupervisorNode(
            planner=lambda payload: _planning_result(_plan(retrieval, memory)),
            registry=default_agent_registry,
            role_handlers={retrieval.role_id: handler, memory.role_id: handler},
            parallel_dispatch=True,
            approved_scopes=("personal_memory", "wiki"),
        )(_state())

    first = asyncio.run(run({retrieval.work_item_id: 0.02, memory.work_item_id: 0.06}))
    reversed_run = asyncio.run(run({retrieval.work_item_id: 0.06, memory.work_item_id: 0.02}))

    assert [result.task_id for result in first.state.results] == ["a-vault", "b-memory"]
    assert first.state.results == reversed_run.state.results
    assert first.state.merged_evidence == reversed_run.state.merged_evidence
    assert [item.citation_id for item in first.state.merged_evidence] == [
        "citation:shared",
        "citation:vault-only",
    ]


def test_evidence_merge_filters_permission_scope_and_conflicting_identity() -> None:
    item = _item(
        "read-vault",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-vault",
    )
    result = _result(
        item,
        output={
            "evidence_candidates": [
                _candidate(
                    "citation:allowed",
                    scope="wiki",
                    channel="fts",
                    rank=1,
                    content_key="allowed",
                ),
                _candidate(
                    "citation:denied",
                    scope="wiki",
                    channel="fts",
                    rank=2,
                    content_key="denied",
                    permission_allowed=False,
                ),
                _candidate(
                    "citation:wrong-scope",
                    scope="graph",
                    channel="graph",
                    rank=1,
                    content_key="wrong-scope",
                ),
                _candidate(
                    "citation:conflict",
                    scope="wiki",
                    channel="fts",
                    rank=3,
                    content_key="conflict-a",
                ),
                _candidate(
                    "citation:conflict",
                    scope="wiki",
                    channel="vector",
                    rank=1,
                    content_key="conflict-b",
                ),
            ]
        },
    )

    merged = merge_parallel_evidence((result,), approved_scopes=("wiki",))

    assert [item.citation_id for item in merged.accepted] == ["citation:allowed"]
    assert merged.input_count == 5
    assert merged.filtered_count == 4
    assert merged.conflicting_identity_count == 1


def test_branch_timeout_is_bounded_and_approved_partial_read_completes() -> None:
    fast = _item(
        "a-fast",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-fast",
        timeout_ms=100,
    )
    slow = _item(
        "b-slow",
        IndependentAgentRoleId.MEMORY,
        branch_id="branch-slow",
        timeout_ms=40,
    )

    async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
        await asyncio.sleep(0.01 if item.work_item_id == fast.work_item_id else 1.0)
        return _result(item)

    started = perf_counter()
    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(
                _plan(fast, slow, completion_rule="approved_partial_read")
            ),
            registry=default_agent_registry,
            role_handlers={fast.role_id: handler, slow.role_id: handler},
            parallel_dispatch=True,
        )(_state())
    )
    wall_ms = (perf_counter() - started) * 1_000

    assert outcome.fallback_reason is None
    assert wall_ms < 300
    assert {record.status for record in outcome.state.branch_records} == {"success", "timed_out"}
    assert outcome.state.budget_usage.provider_usage_complete is False
    assert outcome.state.terminal == "done"


def test_first_supported_terminal_condition_cancels_remaining_branch() -> None:
    terminal = _item(
        "a-terminal",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-terminal",
        terminal_condition="first_supported",
    )
    pending = _item(
        "b-pending",
        IndependentAgentRoleId.MEMORY,
        branch_id="branch-pending",
    )

    async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
        await asyncio.sleep(0.02 if item.work_item_id == terminal.work_item_id else 1.0)
        return _result(item)

    started = perf_counter()
    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(
                _plan(terminal, pending, completion_rule="approved_partial_read")
            ),
            registry=default_agent_registry,
            role_handlers={terminal.role_id: handler, pending.role_id: handler},
            parallel_dispatch=True,
        )(_state())
    )

    assert outcome.fallback_reason is None
    assert (perf_counter() - started) < 0.3
    assert {record.status for record in outcome.state.branch_records} == {"success", "cancelled"}


def test_one_branch_error_uses_approved_partial_read_without_blocking() -> None:
    failed = _item(
        "a-failed",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-failed",
    )
    successful = _item(
        "b-successful",
        IndependentAgentRoleId.MEMORY,
        branch_id="branch-successful",
    )

    async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
        if item.work_item_id == failed.work_item_id:
            raise RuntimeError("private provider detail")
        return _result(item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(
                _plan(failed, successful, completion_rule="approved_partial_read")
            ),
            registry=default_agent_registry,
            role_handlers={failed.role_id: handler, successful.role_id: handler},
            parallel_dispatch=True,
        )(_state())
    )

    assert outcome.fallback_reason is None
    assert {record.status for record in outcome.state.branch_records} == {"failed", "success"}
    assert "private provider detail" not in outcome.state.model_dump_json()


def test_parallel_read_retry_is_shared_bounded_and_audited_per_attempt() -> None:
    retrying = _item(
        "a-retrying",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-retrying",
        retry_policy="transient_read_once",
        requested_tools=("search_vault_fts",),
    )
    memory = _item(
        "b-memory",
        IndependentAgentRoleId.MEMORY,
        branch_id="branch-memory",
        requested_tools=("search_active_memory",),
    )
    attempts = 0

    async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
        nonlocal attempts
        if item.work_item_id == retrying.work_item_id:
            attempts += 1
            if attempts == 1:
                return _result(
                    item,
                    status="failed",
                    safe_error_code="provider_unavailable",
                )
        return _result(item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(retrying, memory)),
            registry=default_agent_registry,
            role_handlers={retrying.role_id: handler, memory.role_id: handler},
            parallel_dispatch=True,
        )(_state())
    )

    assert outcome.fallback_reason is None
    assert attempts == 2
    assert [(record.work_item_id, record.attempt, record.status) for record in outcome.state.branch_records] == [
        ("a-retrying", 1, "failed"),
        ("b-memory", 1, "success"),
        ("a-retrying", 2, "success"),
    ]
    assert outcome.state.budget_usage.repairs == 1
    assert outcome.state.budget_usage.model_calls == 4
    assert outcome.state.budget_usage.tool_calls == 3
    assert outcome.state.budget_usage.reserved_estimated_cost_usd == 0.025


def test_parallel_budget_is_reserved_before_any_branch_starts() -> None:
    items = tuple(
        _item(
            f"work-{index}",
            IndependentAgentRoleId.RETRIEVAL if index % 2 else IndependentAgentRoleId.MEMORY,
            branch_id=f"branch-{index}",
        )
        for index in range(1, 9)
    )
    calls: list[str] = []

    async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
        calls.append(item.work_item_id)
        return _result(item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(*items)),
            registry=default_agent_registry,
            role_handlers={
                IndependentAgentRoleId.RETRIEVAL.value: handler,
                IndependentAgentRoleId.MEMORY.value: handler,
            },
            parallel_dispatch=True,
        )(_state())
    )

    assert outcome.fallback_reason == "input_token_budget_exceeded"
    assert calls == []
    assert outcome.state.branch_records == ()


class _ParallelRuntimeModel:
    def __init__(self, plan: ExecutionPlan) -> None:
        self.plan = plan

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        if system_prompt == "supervisor-plan-v1":
            return json.dumps(_planning_result(self.plan))
        return "safe sequential fallback reply"


class _ParallelRuntime(LangGraphAgentRuntime):
    def __init__(self, *, plan: ExecutionPlan) -> None:
        self._parallel_plan = plan
        super().__init__(
            AgentRuntimeServices(
                chat_model=_ParallelRuntimeModel(plan),
                automation_settings=SimpleNamespace(
                    use_negotiation=True,
                    use_supervisor=True,
                    use_parallel_supervisor=True,
                ),
            )
        )

    def _supervisor_role_handlers(self):
        async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
            if item.role_id == IndependentAgentRoleId.RETRIEVAL.value:
                raise RuntimeError("unpublished branch exception")
            await asyncio.sleep(0.01)
            return _result(item)

        return {
            IndependentAgentRoleId.RETRIEVAL.value: handler,
            IndependentAgentRoleId.MEMORY.value: handler,
        }


def test_required_branch_failure_emits_safe_events_and_runtime_uses_sequential_fallback() -> None:
    retrieval = _item(
        "read-vault",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-vault",
    )
    memory = _item(
        "read-memory",
        IndependentAgentRoleId.MEMORY,
        branch_id="branch-memory",
    )

    async def run_case():
        runtime = _ParallelRuntime(plan=_plan(retrieval, memory))
        return [event async for event in runtime.run(make_state("search memory for Ada"))]

    events = asyncio.run(run_case())
    names = [event.event for event in events]
    branch_events = [event for event in events if event.event == "agent_branch"]

    assert len(branch_events) == 4
    assert [event.sequence for event in branch_events] == [1, 2, 3, 4]
    assert all(event.contract_version == "agent-branch.v1" for event in branch_events)
    assert "unpublished branch exception" not in json.dumps(
        [event.model_dump(mode="json") for event in branch_events]
    )
    assert "negotiation_done" in names
    assert names[-1] == "done"
    assert sum(name in {"done", "error"} for name in names) == 1


def test_parallel_flag_is_off_by_default_and_keeps_sequential_dispatch() -> None:
    retrieval = _item(
        "read-vault",
        IndependentAgentRoleId.RETRIEVAL,
        branch_id="branch-vault",
    )
    memory = _item(
        "read-memory",
        IndependentAgentRoleId.MEMORY,
        branch_id="branch-memory",
    )
    calls: list[str] = []

    async def handler(item: WorkItem, state: MultiAgentGraphState) -> AgentResultEnvelope:
        calls.append(item.work_item_id)
        return _result(item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _planning_result(_plan(retrieval, memory)),
            registry=default_agent_registry,
            role_handlers={retrieval.role_id: handler, memory.role_id: handler},
        )(_state())
    )

    assert calls == [retrieval.work_item_id, memory.work_item_id]
    assert outcome.state.parallel_dispatch_used is False
    assert outcome.state.branch_records == ()
