from __future__ import annotations

import asyncio
from pathlib import Path

from apps.backend.tests._schema import migrate_db

from app.agents.contracts import ActionProposal, ExecutionReceipt
from app.agents.nodes.executor import ActionLifecycleCoordinator
from app.agents.nodes.policy_guard import evaluate_action_proposal
from app.api.services import adapters
from app.services.agent_actions import AgentActionService, AgentActionStore
from app.services.memory import MemoryProposalStore, MemoryService, SafeMarkdownWriter
from app.services.tasks import TaskService, TaskStore
from app.services.wiki import WikiService


def _request() -> object:
    return object()


def _ledger(db_path: Path) -> AgentActionService:
    return AgentActionService(AgentActionStore(migrate_db(db_path)))


def _proposal(action_type: str, *, target: str, parameters: dict[str, object]) -> ActionProposal:
    return ActionProposal(
        proposal_id=f"proposal-recovery-{action_type.replace('.', '-')}",
        explicit_intent_ref=f"intent:recovery:{action_type}",
        action_type=action_type,
        target_ref=target,
        parameters=parameters,
        expected_effect=f"Apply {action_type} once.",
        source_message_id="message-recovery",
    )


def _crashing_after_commit(adapter):
    async def execute(proposal, policy, claim):
        await adapter(proposal, policy, claim)
        raise RuntimeError("receipt write interrupted after effect commit")

    return execute


def test_task_reader_recovers_after_effect_before_receipt_and_projects_title_and_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "task.sqlite3"
    request = _request()
    monkeypatch.setattr(
        adapters,
        "task_service",
        lambda _request: TaskService(TaskStore(db_path)),
    )
    proposal = _proposal(
        "task.create",
        target="task:recover-task",
        parameters={
            "title": "Recover task",
            "source_text": "Recover task",
            "timezone": "Asia/Shanghai",
            "due_at": "2030-01-01T00:00:00",
            "remind_at": "2030-01-01T01:00:00",
        },
    )
    policy = evaluate_action_proposal(proposal)
    adapter = adapters._task_action_adapter(request)
    coordinator = ActionLifecycleCoordinator(
        ledger=_ledger(db_path),
        adapters={"task.create": _crashing_after_commit(adapter)},
        readers={"task.create": adapters._task_action_reader(request)},
    )

    outcome = asyncio.run(coordinator.execute(proposal, policy, source_run_id="run-recovery-task"))

    assert outcome.receipt.status == "verified"
    assert outcome.receipt.result["title"] == "Recover task"
    assert outcome.receipt.result["target_ref"] == f"task:task-{policy.idempotency_key}"
    assert "canonical_parameters" not in outcome.receipt.result
    assert outcome.action.title == "Recover task"
    assert outcome.action.metadata["target_ref"] == policy.normalized_target
    probe = ExecutionReceipt(
        receipt_ref="receipt:probe",
        claim_id="claim-probe",
        proposal_id=proposal.proposal_id,
        idempotency_key=policy.idempotency_key,
        action_type=policy.action_type,
        normalized_target=policy.normalized_target,
        status="applied",
        result={"canonical_parameters": policy.canonical_parameters},
    )
    assert adapters._task_action_reader(request)(probe)["task_id"] == f"task-{policy.idempotency_key}"
    store = TaskStore(db_path)
    try:
        assert store.get_task(f"task-{policy.idempotency_key}").title == "Recover task"
    finally:
        store.close()


def test_memory_reader_recovers_by_stable_proposal_id_without_expected_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "memory.sqlite3"
    vault = tmp_path / "Vault"
    writer = SafeMarkdownWriter(vault)
    request = _request()
    monkeypatch.setattr(
        adapters,
        "database",
        lambda _request: type("DatabaseRef", (), {"path": db_path})(),
    )
    monkeypatch.setattr(
        adapters,
        "memory_service",
        lambda _request: MemoryService(MemoryProposalStore(db_path), writer),
    )
    proposal = _proposal(
        "memory.proposal",
        target="Inbox/Pending Memories.md",
        parameters={"content": "I prefer short meetings.", "target_path": "Inbox/Pending Memories.md"},
    )
    policy = evaluate_action_proposal(proposal)
    adapter = adapters._memory_action_adapter(request)
    coordinator = ActionLifecycleCoordinator(
        ledger=_ledger(db_path),
        adapters={"memory.proposal": _crashing_after_commit(adapter)},
        readers={"memory.proposal": adapters._memory_action_reader(request)},
    )

    outcome = asyncio.run(coordinator.execute(proposal, policy, source_run_id="run-recovery-memory"))

    assert outcome.receipt.status == "verified"
    assert outcome.receipt.result["proposal_id"] == f"memory-proposal-{policy.idempotency_key}"
    assert outcome.receipt.result["target_ref"] == f"memory-proposal:memory-proposal-{policy.idempotency_key}"
    assert "expected_state" not in outcome.receipt.result


def test_wiki_reader_recovers_marker_and_target_from_canonical_parameters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "wiki.sqlite3"
    vault = tmp_path / "Vault"
    writer = SafeMarkdownWriter(vault)
    request = _request()
    monkeypatch.setattr(adapters, "wiki_service", lambda _request: WikiService(writer))
    proposal = _proposal(
        "wiki.page.write",
        target="Wiki/Recovery.md",
        parameters={
            "title": "Recovery",
            "target_path": "Wiki/Recovery.md",
            "content": "Durable evidence.",
        },
    )
    policy = evaluate_action_proposal(proposal)
    adapter = adapters._wiki_action_adapter(request)
    coordinator = ActionLifecycleCoordinator(
        ledger=_ledger(db_path),
        adapters={"wiki.page.write": _crashing_after_commit(adapter)},
        readers={"wiki.page.write": adapters._wiki_action_reader(request)},
    )

    outcome = asyncio.run(coordinator.execute(proposal, policy, source_run_id="run-recovery-wiki"))

    assert outcome.receipt.status == "verified"
    assert outcome.receipt.result["target_path"] == "Wiki/Recovery.md"
    assert outcome.receipt.result["title"] == "Recovery"
    assert outcome.receipt.result["target_ref"] == "Wiki/Recovery.md"
    marker = f"<!-- llmwiki-action:{policy.idempotency_key} -->"
    assert marker in (vault / "Wiki" / "Recovery.md").read_text(encoding="utf-8")
