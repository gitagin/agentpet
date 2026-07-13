from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal

from app.agents.contracts import ActionProposal, ReflectionProposalBatch
from app.agents.nodes.policy_guard import evaluate_action_proposal
from app.agents.roles.reflection_agent import build_role_agent
from app.agents.state import AgentState
from app.models.enums import AgentRunStatus
from app.services.memory_policy import evaluate_memory_content

logger = logging.getLogger(__name__)

REFLECTION_POLICY_VERSION = "reflection-policy.v1"
REFLECTION_MAX_PROPOSALS = 4
REFLECTION_MAX_MODEL_CALLS = 2
REFLECTION_STAGE_TIMEOUT_SECONDS = 15.0
REFLECTION_JOB_DEADLINE_SECONDS = 60.0

ReflectionStatus = Literal[
    "queued",
    "running",
    "completed",
    "done_with_pending",
    "partial",
    "failed",
    "cancelled",
    "skipped",
]


@dataclass(frozen=True, slots=True)
class ReflectionProposalResult:
    proposal_id: str
    status: Literal["approved", "pending_confirmation", "denied", "executed", "failed"]
    reason_code: str


@dataclass(frozen=True, slots=True)
class ReflectionJobState:
    job_id: str
    source_message_id: str
    source_agent_run_id: str
    policy_version: str
    status: ReflectionStatus
    started_at: str | None = None
    completed_at: str | None = None
    model_calls: int = 0
    proposal_results: tuple[ReflectionProposalResult, ...] = ()
    safe_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ReflectionJobInput:
    state: AgentState
    assistant_answer: str
    model: Any | None = None
    reflector: Callable[[dict[str, Any]], Any | Awaitable[Any]] | None = None
    executor: Callable[[ActionProposal], Any | Awaitable[Any]] | None = None
    job_id: str | None = None
    policy_version: str = REFLECTION_POLICY_VERSION
    stage_timeout_seconds: float = REFLECTION_STAGE_TIMEOUT_SECONDS
    deadline_seconds: float = REFLECTION_JOB_DEADLINE_SECONDS


@dataclass(frozen=True, slots=True)
class ReflectionJobRun:
    state: ReflectionJobState
    proposals: ReflectionProposalBatch = field(default_factory=ReflectionProposalBatch)


class ReflectionJobRunner:
    async def run(self, payload: ReflectionJobInput) -> ReflectionJobRun:
        state = payload.state
        job_id = payload.job_id or deterministic_reflection_job_id(state.message_id, payload.policy_version)
        base = ReflectionJobState(
            job_id=job_id,
            source_message_id=state.message_id,
            source_agent_run_id=state.agent_run_id,
            policy_version=payload.policy_version,
            status="running",
            started_at=_now(),
        )
        if state.status is not AgentRunStatus.SUCCESS:
            return ReflectionJobRun(
                state=replace(
                    base,
                    status="skipped",
                    completed_at=_now(),
                    safe_error_code="foreground_not_done",
                ),
            )
        if _reflection_blocked(state, payload.assistant_answer):
            return ReflectionJobRun(
                state=replace(
                    base,
                    status="skipped",
                    completed_at=_now(),
                    safe_error_code="sensitive_or_private_input",
                ),
            )
        if payload.model is None and payload.reflector is None:
            return ReflectionJobRun(
                state=replace(
                    base,
                    status="skipped",
                    completed_at=_now(),
                    safe_error_code="reflection_model_unavailable",
                ),
            )

        started = time.perf_counter()
        try:
            projection = _bounded_projection(state, payload.assistant_answer)
            if payload.reflector is not None:
                raw = payload.reflector(projection)
            else:
                role = build_role_agent(model=payload.model)
                raw = role.ainvoke(projection)
            result = await asyncio.wait_for(
                raw,
                timeout=min(payload.stage_timeout_seconds, payload.deadline_seconds),
            )
            batch = ReflectionProposalBatch.model_validate(result)
            if len(batch.proposals) > REFLECTION_MAX_PROPOSALS:
                raise ValueError("reflection_proposal_budget_exceeded")
            proposal_results = await self._route_proposals(
                batch,
                state=state,
                executor=payload.executor,
                deadline=started + min(payload.deadline_seconds, REFLECTION_JOB_DEADLINE_SECONDS),
            )
            statuses = {item.status for item in proposal_results}
            final_status: ReflectionStatus = (
                "done_with_pending"
                if "pending_confirmation" in statuses
                else "partial"
                if "failed" in statuses or "denied" in statuses
                else "completed"
            )
            return ReflectionJobRun(
                state=replace(
                    base,
                    status=final_status,
                    completed_at=_now(),
                    model_calls=1,
                    proposal_results=tuple(proposal_results),
                ),
                proposals=batch,
            )
        except asyncio.CancelledError:
            raise
        except (asyncio.TimeoutError, TimeoutError):
            return ReflectionJobRun(
                state=replace(
                    base,
                    status="failed",
                    completed_at=_now(),
                    model_calls=1,
                    safe_error_code="reflection_timeout",
                )
            )
        except Exception:
            logger.warning("Reflection job failed safely for source_message_id=%s", state.message_id, exc_info=True)
            return ReflectionJobRun(
                state=replace(
                    base,
                    status="failed",
                    completed_at=_now(),
                    model_calls=1,
                    safe_error_code="reflection_failed",
                )
            )

    async def _route_proposals(
        self,
        batch: ReflectionProposalBatch,
        *,
        state: AgentState,
        executor: Callable[[ActionProposal], Any | Awaitable[Any]] | None,
        deadline: float,
    ) -> list[ReflectionProposalResult]:
        routed: list[ReflectionProposalResult] = []
        for reflection in batch.proposals:
            if time.perf_counter() >= deadline:
                routed.append(ReflectionProposalResult(reflection.proposal_id, "failed", "reflection_deadline_exceeded"))
                continue
            proposal = _action_proposal(reflection, state)
            policy = evaluate_action_proposal(proposal)
            if policy.decision == "denied":
                routed.append(ReflectionProposalResult(reflection.proposal_id, "denied", policy.reason_code))
                continue
            if policy.decision == "pending_confirmation":
                routed.append(ReflectionProposalResult(reflection.proposal_id, "pending_confirmation", policy.reason_code))
                continue
            if executor is None:
                routed.append(ReflectionProposalResult(reflection.proposal_id, "failed", "reflection_executor_unavailable"))
                continue
            try:
                executed = executor(proposal)
                if inspect.isawaitable(executed):
                    remaining = max(0.001, deadline - time.perf_counter())
                    executed = await asyncio.wait_for(executed, timeout=remaining)
                routed.append(ReflectionProposalResult(reflection.proposal_id, "executed", "allowlisted_low_risk"))
            except Exception:
                routed.append(ReflectionProposalResult(reflection.proposal_id, "failed", "reflection_execution_failed"))
        return routed


class ReflectionJobManager:
    def __init__(self, runner: ReflectionJobRunner | None = None) -> None:
        self.runner = runner or ReflectionJobRunner()
        self._tasks: dict[str, asyncio.Task[ReflectionJobRun]] = {}
        self._results: dict[str, ReflectionJobRun] = {}

    def start(self, payload: ReflectionJobInput) -> asyncio.Task[ReflectionJobRun] | None:
        job_id = payload.job_id or deterministic_reflection_job_id(payload.state.message_id, payload.policy_version)
        existing = self._tasks.get(job_id)
        if existing is not None and not existing.done():
            return existing
        if job_id in self._results:
            return None
        task = asyncio.create_task(self.runner.run(payload), name=f"reflection-job:{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda done, key=job_id: self._capture(key, done))
        return task

    def get(self, job_id: str) -> ReflectionJobRun | None:
        return self._results.get(job_id)

    async def shutdown(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def recover_orphans(self) -> tuple[str, ...]:
        orphaned = tuple(job_id for job_id, task in self._tasks.items() if not task.done())
        for job_id in orphaned:
            self._tasks[job_id].cancel()
        return orphaned

    def _capture(self, job_id: str, task: asyncio.Task[ReflectionJobRun]) -> None:
        if task.cancelled():
            return
        try:
            self._results[job_id] = task.result()
        except Exception:
            logger.warning("Reflection manager lost job result for %s", job_id, exc_info=True)


def deterministic_reflection_job_id(source_message_id: str, policy_version: str = REFLECTION_POLICY_VERSION) -> str:
    digest = hashlib.sha256(f"{source_message_id}:{policy_version}".encode("utf-8")).hexdigest()[:32]
    return f"reflection:{digest}"


def _reflection_blocked(state: AgentState, assistant_answer: str) -> bool:
    if state.local_privacy_mode or state.local_privacy_sensitive_reason:
        return True
    return not evaluate_memory_content(f"{state.user_message}\n{assistant_answer}").allowed


def _bounded_projection(state: AgentState, assistant_answer: str) -> dict[str, Any]:
    return {
        "schema_version": "reflection-input.v1",
        "source_message_id": state.message_id,
        "source_agent_run_id": state.agent_run_id,
        "user_message": state.user_message[:2_000],
        "assistant_answer": assistant_answer[:4_000],
        "approved_action_refs": tuple(
            receipt.receipt_ref for receipt in state.execution_receipts[:4]
        ),
    }


def _action_proposal(reflection: Any, state: AgentState) -> ActionProposal:
    return ActionProposal(
        proposal_id=reflection.proposal_id,
        explicit_intent_ref=f"reflection:{state.message_id}:{reflection.proposal_kind}",
        action_type=reflection.action_type,
        target_ref=reflection.target_ref,
        parameters={"content": reflection.content, "proposal_kind": reflection.proposal_kind},
        expected_effect=f"Reflection proposal: {reflection.proposal_kind}",
        reversible=reflection.reversible,
        source_message_id=state.message_id,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
