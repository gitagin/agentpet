from __future__ import annotations

import asyncio

from tests.agent_runtime_fakes import make_state

from app.agents.contracts import ReflectionProposal, ReflectionProposalBatch
from app.agents.reflection_graph import (
    ReflectionJobInput,
    ReflectionJobManager,
    ReflectionJobRunner,
    deterministic_reflection_job_id,
)
from app.models.enums import AgentRunStatus


def _done_state(message: str):
    state = make_state(message)
    state.status = AgentRunStatus.SUCCESS
    return state


def _batch(*, action_type: str = "task.create", proposal_id: str = "proposal:reflection:1") -> ReflectionProposalBatch:
    return ReflectionProposalBatch(
        proposals=(
            ReflectionProposal(
                proposal_id=proposal_id,
                source_message_id="message-1",
                proposal_kind="daily_diary",
                action_type=action_type,
                target_ref="task:reflection",
                content="A bounded reflection proposal.",
                confidence=0.95,
                reversible=True,
            ),
        )
    )


def test_reflection_starts_only_from_bounded_projection_and_routes_low_risk_proposal() -> None:
    calls: list[dict] = []
    executions: list[str] = []

    async def reflector(projection):
        calls.append(projection)
        return _batch()

    async def executor(proposal):
        executions.append(proposal.proposal_id)

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=_done_state("please remember this safe preference"),
                assistant_answer="A concise answer.",
                reflector=reflector,
                executor=executor,
            )
        )
    )

    assert run.state.status == "completed"
    assert run.state.model_calls == 1
    assert run.state.proposal_results[0].status == "executed"
    assert executions == ["proposal:reflection:1"]
    assert calls[0]["schema_version"] == "reflection-input.v1"
    assert set(calls[0]) == {
        "schema_version",
        "source_message_id",
        "source_agent_run_id",
        "user_message",
        "assistant_answer",
        "approved_action_refs",
    }


def test_high_risk_reflection_proposal_becomes_pending_without_executor_call() -> None:
    executions: list[str] = []

    async def executor(proposal):
        executions.append(proposal.proposal_id)

    async def reflector(_projection):
        return _batch(action_type="markdown.delete")

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=_done_state("review the local note"),
                assistant_answer="The note was reviewed.",
                reflector=reflector,
                executor=executor,
            )
        )
    )

    assert run.state.status == "done_with_pending"
    assert run.state.proposal_results[0].status == "pending_confirmation"
    assert executions == []


def test_local_privacy_or_sensitive_input_makes_zero_reflection_model_calls() -> None:
    calls = 0

    async def reflector(_projection):
        nonlocal calls
        calls += 1
        return _batch()

    private_state = _done_state("api_key=private-value-123456")
    private_state.local_privacy_mode = True
    private_state.local_privacy_sensitive_reason = "credential"
    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=private_state,
                assistant_answer="I will not retain this.",
                reflector=reflector,
            )
        )
    )

    assert run.state.status == "skipped"
    assert run.state.safe_error_code == "sensitive_or_private_input"
    assert calls == 0


def test_reflection_before_foreground_done_is_skipped_without_model_call() -> None:
    calls = 0

    async def reflector(_projection):
        nonlocal calls
        calls += 1
        return _batch()

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=make_state("not done yet"),
                assistant_answer="Partial.",
                reflector=reflector,
            )
        )
    )

    assert run.state.status == "skipped"
    assert run.state.safe_error_code == "foreground_not_done"
    assert calls == 0


def test_reflection_provider_failure_is_background_only_and_safe() -> None:
    async def reflector(_projection):
        raise RuntimeError("provider failure with private path C:\\Users\\Ada\\Vault\\Secret.md")

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=_done_state("summarize this"),
                assistant_answer="Done.",
                reflector=reflector,
            )
        )
    )

    assert run.state.status == "failed"
    assert run.state.safe_error_code == "reflection_failed"
    assert run.state.proposal_results == ()


def test_reflection_manager_deduplicates_source_message_and_cancels_owned_jobs() -> None:
    gate = asyncio.Event()

    async def reflector(_projection):
        await gate.wait()
        return _batch()

    async def run_case():
        manager = ReflectionJobManager()
        payload = ReflectionJobInput(
            state=_done_state("deduplicate this"),
            assistant_answer="Done.",
            reflector=reflector,
        )
        first = manager.start(payload)
        second = manager.start(payload)
        await asyncio.sleep(0)
        await manager.shutdown()
        return first, second, manager

    first, second, manager = asyncio.run(run_case())

    assert first is second
    assert first is not None and first.cancelled()
    assert manager.get(deterministic_reflection_job_id("message-1")) is None


def test_reflection_job_id_changes_with_policy_version() -> None:
    assert deterministic_reflection_job_id("message-1") != deterministic_reflection_job_id(
        "message-1", "reflection-policy.v2"
    )
