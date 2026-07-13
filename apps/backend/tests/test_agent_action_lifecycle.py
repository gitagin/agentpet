from __future__ import annotations

import asyncio
from pathlib import Path

from apps.backend.tests._schema import migrate_db

from app.agents.contracts import ActionProposal
from app.agents.nodes.executor import ActionLifecycleCoordinator, AdapterExecutionResult
from app.agents.nodes.policy_guard import evaluate_action_proposal
from app.services.agent_actions import AgentActionService, AgentActionStore, markdown_snapshot
from app.services.memory import SafeMarkdownWriter


def _proposal(
    action_type: str,
    *,
    target: str,
    parameters: dict | None = None,
    reversible: bool = False,
    requested_confirmation: bool = False,
) -> ActionProposal:
    return ActionProposal(
        proposal_id="proposal-action-1",
        explicit_intent_ref="intent:message-1:0",
        action_type=action_type,
        target_ref=target,
        parameters=parameters or {},
        expected_effect="Apply the requested isolated test effect.",
        reversible=reversible,
        source_message_id="message-1",
        requested_confirmation=requested_confirmation,
    )


def _ledger(tmp_path: Path, *, writer: SafeMarkdownWriter | None = None) -> AgentActionService:
    return AgentActionService(
        AgentActionStore(migrate_db(tmp_path / "action-state.sqlite3")),
        writer=writer,
    )


def test_low_risk_allowlisted_action_executes_once_and_duplicate_returns_original_receipt(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    state: dict[str, object] = {}
    adapter_calls = 0

    async def adapter(proposal, policy, claim):
        nonlocal adapter_calls
        adapter_calls += 1
        state.update({"title": policy.canonical_parameters["title"], "state_ref": "task:1"})
        return AdapterExecutionResult(
            result={"expected_state": {"title": "Pay invoice"}},
            after_snapshot={"title": "Pay invoice"},
        )

    async def reader(receipt):
        return dict(state)

    proposal = _proposal(
        "task.create",
        target="task:pay-invoice",
        parameters={"title": "Pay invoice"},
    )
    policy = evaluate_action_proposal(proposal)
    coordinator = ActionLifecycleCoordinator(
        ledger=ledger,
        adapters={"task.create": adapter},
        readers={"task.create": reader},
    )

    first = asyncio.run(coordinator.execute(proposal, policy, source_run_id="run-1"))
    duplicate = asyncio.run(coordinator.execute(proposal, policy, source_run_id="run-2"))

    assert policy.decision == "approved"
    assert first.receipt.status == "verified"
    assert first.verification is not None and first.verification.status == "verified"
    assert duplicate.duplicate is True
    assert duplicate.receipt == first.receipt
    assert adapter_calls == 1
    assert ledger.find_execution(policy.idempotency_key).status == "completed"


def test_high_risk_action_is_zero_write_and_target_is_byte_identical_before_confirmation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "protected.md"
    target.write_bytes(b"original bytes\r\n")
    before = target.read_bytes()
    adapter_calls = 0

    async def adapter(proposal, policy, claim):
        nonlocal adapter_calls
        adapter_calls += 1
        target.unlink()
        return AdapterExecutionResult(result={})

    proposal = _proposal(
        "markdown.delete",
        target="Wiki/Protected.md",
        parameters={"target_path": "Wiki/Protected.md"},
    )
    policy = evaluate_action_proposal(proposal)
    coordinator = ActionLifecycleCoordinator(
        ledger=_ledger(tmp_path),
        adapters={"markdown.delete": adapter},
        readers={},
    )

    outcome = asyncio.run(coordinator.execute(proposal, policy, source_run_id="run-1"))

    assert policy.decision == "pending_confirmation"
    assert policy.risk_tier == "high"
    assert outcome.receipt.status == "pending_confirmation"
    assert target.read_bytes() == before
    assert adapter_calls == 0


def test_unknown_and_unsafe_actions_are_denied_without_adapter_dispatch(tmp_path: Path) -> None:
    adapter_calls = 0

    async def adapter(proposal, policy, claim):
        nonlocal adapter_calls
        adapter_calls += 1
        return AdapterExecutionResult(result={})

    proposals = (
        _proposal("unknown.effect", target="unknown:target"),
        _proposal(
            "wiki.page.write",
            target="../Secret.md",
            parameters={"content": "safe text"},
            reversible=True,
        ),
    )
    coordinator = ActionLifecycleCoordinator(
        ledger=_ledger(tmp_path),
        adapters={"unknown.effect": adapter, "wiki.page.write": adapter},
        readers={},
    )

    outcomes = [
        asyncio.run(
            coordinator.execute(proposal, evaluate_action_proposal(proposal), source_run_id=f"run-{index}")
        )
        for index, proposal in enumerate(proposals)
    ]

    assert [evaluate_action_proposal(proposal).decision for proposal in proposals] == ["denied", "denied"]
    assert [outcome.receipt.status for outcome in outcomes] == ["denied", "denied"]
    assert adapter_calls == 0


def test_write_timeout_is_not_retried_and_enters_failed_recovery(tmp_path: Path) -> None:
    adapter_calls = 0

    async def adapter(proposal, policy, claim):
        nonlocal adapter_calls
        adapter_calls += 1
        await asyncio.sleep(0.05)
        return AdapterExecutionResult(result={})

    proposal = _proposal("task.create", target="task:slow", parameters={"title": "Slow"})
    policy = evaluate_action_proposal(proposal)
    coordinator = ActionLifecycleCoordinator(
        ledger=_ledger(tmp_path),
        adapters={"task.create": adapter},
        readers={},
        timeout_seconds=0.005,
    )

    outcome = asyncio.run(coordinator.execute(proposal, policy, source_run_id="run-1"))

    assert outcome.receipt.status == "failed_recovery"
    assert outcome.receipt.safe_error_code == "action_timeout"
    assert adapter_calls == 1


def test_partial_success_never_runs_compensation_or_verifier(tmp_path: Path) -> None:
    state = {"writes": 0, "reads": 0, "compensations": 0}

    async def adapter(proposal, policy, claim):
        state["writes"] += 1
        return AdapterExecutionResult(
            result={"expected_state": {"value": "complete"}},
            after_snapshot={"value": "partial"},
            fully_applied=False,
            safe_error_code="partial_write",
        )

    async def reader(receipt):
        state["reads"] += 1
        return {"value": "partial"}

    proposal = _proposal("task.create", target="task:partial", parameters={"title": "Partial"})
    coordinator = ActionLifecycleCoordinator(
        ledger=_ledger(tmp_path),
        adapters={"task.create": adapter},
        readers={"task.create": reader},
    )

    outcome = asyncio.run(
        coordinator.execute(proposal, evaluate_action_proposal(proposal), source_run_id="run-1")
    )

    assert outcome.receipt.status == "failed_recovery"
    assert outcome.receipt.safe_error_code == "partial_write"
    assert state == {"writes": 1, "reads": 0, "compensations": 0}


def test_verifier_reads_actual_state_and_mismatch_fails_closed(tmp_path: Path) -> None:
    async def adapter(proposal, policy, claim):
        return AdapterExecutionResult(
            result={"expected_state": {"title": "Expected"}},
            after_snapshot={"title": "Expected"},
        )

    async def reader(receipt):
        return {"title": "Different", "state_ref": "task:actual"}

    proposal = _proposal("task.create", target="task:verify", parameters={"title": "Expected"})
    coordinator = ActionLifecycleCoordinator(
        ledger=_ledger(tmp_path),
        adapters={"task.create": adapter},
        readers={"task.create": reader},
    )

    outcome = asyncio.run(
        coordinator.execute(proposal, evaluate_action_proposal(proposal), source_run_id="run-1")
    )

    assert outcome.verification is not None
    assert outcome.verification.status == "mismatch"
    assert outcome.verification.failed_checks == ("title",)
    assert outcome.receipt.status == "failed_recovery"


def test_verified_reversible_markdown_action_keeps_snapshot_for_auditable_rollback(
    tmp_path: Path,
) -> None:
    writer = SafeMarkdownWriter(tmp_path / "Vault")
    target_path = "Wiki/Runtime.md"
    old_text = "# Runtime\n\nOld.\n"
    new_text = "# Runtime\n\nNew.\n"
    writer.write(target_path, old_text)
    ledger = _ledger(tmp_path, writer=writer)

    async def adapter(proposal, policy, claim):
        before = markdown_snapshot(writer, [target_path])
        writer.write(target_path, new_text)
        after = markdown_snapshot(writer, [target_path])
        return AdapterExecutionResult(
            result={"expected_state": {"content": new_text}},
            before_snapshot=before,
            after_snapshot=after,
            target_paths=(target_path,),
        )

    async def reader(receipt):
        return {
            "content": writer.resolve_markdown_path(target_path).read_text(encoding="utf-8"),
            "state_ref": target_path,
        }

    proposal = _proposal(
        "wiki.page.write",
        target=target_path,
        parameters={"target_path": target_path, "content": new_text},
        reversible=True,
    )
    policy = evaluate_action_proposal(proposal)
    coordinator = ActionLifecycleCoordinator(
        ledger=ledger,
        adapters={"wiki.page.write": adapter},
        readers={"wiki.page.write": reader},
    )

    outcome = asyncio.run(coordinator.execute(proposal, policy, source_run_id="run-1"))
    original_action_id = outcome.receipt.claim_id
    updated, reverted = ledger.revert(original_action_id)

    assert outcome.receipt.status == "verified"
    assert writer.resolve_markdown_path(target_path).read_text(encoding="utf-8") == old_text
    assert updated.status == "reverted"
    assert reverted.metadata["reverted_action_id"] == original_action_id
