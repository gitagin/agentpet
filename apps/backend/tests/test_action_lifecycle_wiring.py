from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from app.agents.contracts import ActionProposal
from app.agents.nodes.action import _execute_action_plan
from app.agents.nodes.executor import ActionLifecycleCoordinator
from app.agents.nodes.policy_guard import evaluate_action_proposal
from app.agents.services import AgentRuntimeServices
from app.agents.state import ActionPlan, AgentRoute, AgentState
from app.api.services.adapters import _execute_registered_action, agent_runtime
from app.api.services.factory import AppContext
from app.models.api import MemoryProposalCreateRequest, TaskCreateRequest, WikiPageWriteRequest
from app.models.enums import AgentIntent, MemoryProposalType
from apps.backend.tests.conftest import auth_headers


def _bind_vault(client, root: Path) -> None:
    response = client.post(
        "/api/vaults/init",
        headers=auth_headers(),
        json={"path": str(root / "Vault"), "create_if_missing": True, "confirmed": True},
    )
    assert response.status_code == 200


def test_runtime_without_durable_lifecycle_fails_closed_before_write() -> None:
    class WriteService:
        calls = 0

        async def create(self, request):
            self.calls += 1
            raise AssertionError("the write service must not run without a coordinator")

    writer = WriteService()
    proposal = ActionProposal(
        proposal_id="proposal-fail-closed",
        explicit_intent_ref="intent:fail-closed",
        action_type="task.create",
        target_ref="task:no-write",
        parameters={"title": "Must not write"},
        expected_effect="Create one local task.",
        source_message_id="message-fail-closed",
    )
    policy = evaluate_action_proposal(proposal)
    proposal = proposal.model_copy(
        update={
            "normalized_target": policy.normalized_target,
            "idempotency_key": policy.idempotency_key,
        }
    )
    plan = ActionPlan(
        action_type="task",
        payload={"title": "Must not write"},
        proposal_id=proposal.proposal_id,
        policy_version=policy.policy_version,
        idempotency_key=policy.idempotency_key,
        control_state="approved",
    )
    state = AgentState(
        conversation_id="conversation-fail-closed",
        message_id="message-fail-closed",
        agent_run_id="run-fail-closed",
        user_message="create a task",
        route=AgentRoute(intent=AgentIntent.CREATE_TASK, confidence=1.0, reason="test"),
        action_plan=plan,
        action_plans=[plan],
        action_proposals=[proposal],
        policy_decisions=[policy],
    )
    graph_state = {"agent_state": state, "events": [], "failed": False}

    asyncio.run(
        _execute_action_plan(
            graph_state,
            AgentRuntimeServices(tasks=writer, allow_ephemeral_lifecycle=False),
        )
    )

    assert writer.calls == 0
    assert graph_state["failed"] is True
    assert state.status.value == "failed"
    assert state.error_code == "action_lifecycle_unavailable"
    assert graph_state["events"][-1].event == "error"
    assert graph_state["events"][-1].code == "action_lifecycle_unavailable"


def test_production_runtime_shares_one_lifecycle_registry_across_write_adapters(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, tmp_path)
        runtime = agent_runtime(AppContext(app=client.app, request_id="wiring-runtime"))  # type: ignore[arg-type]
        lifecycle = runtime.services.action_lifecycle

        assert isinstance(lifecycle, ActionLifecycleCoordinator)
        assert runtime.services.allow_ephemeral_lifecycle is False
        assert runtime.services.tasks.action_lifecycle is lifecycle
        assert runtime.services.memory.action_lifecycle is lifecycle
        assert runtime.services.continuity.action_lifecycle is lifecycle
        assert runtime.services.wiki.action_lifecycle is lifecycle
        assert runtime.services.wiki_workflow.action_lifecycle is lifecycle
        assert set(lifecycle.adapters) == {
            "task.create",
            "reminder.delivery.reserve",
            "reminder.delivery.display",
            "reminder.delivery.recover",
            "task.complete",
            "task.approve",
            "task.reject",
            "task.cancel",
            "task.patch",
            "memory.proposal",
            "memory.proposal.confirm",
            "memory.proposal.reject",
            "memory.proposal.defer",
            "memory.feedback.apply",
            "memory.hygiene.apply",
            "memory.graph.entity",
            "memory.graph.statement",
            "memory.graph.relation",
            "memory.graph.rebuild",
            "chat.daily_archive",
            "diary.structured_memory",
            "memory.consolidation.candidate",
            "memory.consolidation.safety_event",
            "metrics.feedback",
            "continuity.proposal.confirm",
            "continuity.proposal.activate",
            "continuity.proposal.reject",
            "wiki.ingest.confirm",
            "wiki.ingest.review",
            "wiki.ingest.apply",
            "wiki.page.write",
            "wiki.answer_summary.write",
            "wiki.ingest.write",
            "wiki.query_archive.write",
            "wiki.synthesize.write",
            "wiki.lint.write",
            "wiki.lint.report",
            "wiki.retrospective_report.write",
            "wiki.weekly_report.write",
            "wiki.monthly_report.write",
            "wiki.ingest.plan",
            "wiki.query_archive.plan",
            "wiki.synthesize.plan",
            "wiki.lint.plan",
        }
        assert set(lifecycle.readers) == set(lifecycle.adapters)


def test_wiki_summary_executor_and_reader_require_the_declared_effects(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, tmp_path)
        runtime = agent_runtime(AppContext(app=client.app, request_id="wiki-summary-contract"))  # type: ignore[arg-type]
        target_path = "Wiki/Companion/Summaries/2026-09-14-answer.md"
        proposal = ActionProposal(
            proposal_id="proposal-wiki-summary-contract",
            explicit_intent_ref="intent:wiki-summary-contract",
            action_type="wiki.answer_summary.write",
            target_ref=target_path,
            parameters={
                "title": "Answer summary",
                "target_path": target_path,
                "content": "Use the local evidence before making a claim.",
            },
            expected_effect="写入 Wiki 摘要页面。",
            source_message_id="message-wiki-summary-contract",
        )
        policy = evaluate_action_proposal(proposal)
        assert policy.decision == "approved"

        outcome = asyncio.run(
            runtime.services.action_lifecycle.execute(
                proposal,
                policy,
                source_run_id="run-wiki-summary-contract",
            )
        )
        actual_path = tmp_path / "Vault" / target_path
        assert actual_path.exists(), {
            "actual_path": str(actual_path),
            "result": outcome.receipt.result,
        }
        assert outcome.receipt.result["action_marker"] in actual_path.read_text(encoding="utf-8")
        index_text = (tmp_path / "Vault" / "Wiki" / "index.md").read_text(encoding="utf-8")
        log_text = (tmp_path / "Vault" / "Wiki" / "log.md").read_text(encoding="utf-8")
        assert target_path in index_text, index_text
        assert outcome.receipt.result["action_marker"] in log_text, log_text
        assert outcome.receipt.result["expected_state"]["target_path"] == target_path
        from app.api.services.adapters import _wiki_summary_section_content
        assert _wiki_summary_section_content(
            actual_path.read_text(encoding="utf-8"),
            outcome.receipt.result["action_marker"],
        ) == "Use the local evidence before making a claim."
        reader = runtime.services.action_lifecycle.readers["wiki.answer_summary.write"]
        assert reader(outcome.receipt) is not None
        assert outcome.receipt.status == "verified"
        assert reader(outcome.receipt) is not None

        vault_root = tmp_path / "Vault"
        (vault_root / "Wiki" / "index.md").unlink()
        assert reader(outcome.receipt) is None


def test_wiki_summary_policy_rejects_non_summary_targets() -> None:
    proposal = ActionProposal(
        proposal_id="proposal-wiki-summary-invalid-target",
        explicit_intent_ref="intent:wiki-summary-invalid-target",
        action_type="wiki.answer_summary.write",
        target_ref="Wiki/Notes/not-a-summary.md",
        parameters={
            "target_path": "Wiki/Notes/not-a-summary.md",
            "content": "Do not write this outside the summary area.",
        },
        expected_effect="写入 Wiki 摘要页面。",
    )

    policy = evaluate_action_proposal(proposal)

    assert policy.decision == "denied"
    assert policy.reason_code == "wiki_summary_target_invalid"


def test_runtime_write_adapters_persist_verified_receipts_before_returning(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, tmp_path)
        runtime = agent_runtime(AppContext(app=client.app, request_id="wiring-effects"))  # type: ignore[arg-type]

        task = asyncio.run(
            runtime.services.tasks.create(
                TaskCreateRequest(title="Verify lifecycle wiring", source_text="Verify lifecycle wiring")
            )
        )
        memory = asyncio.run(
            runtime.services.memory.create_proposal(
                MemoryProposalCreateRequest(
                    type=MemoryProposalType.FACT,
                    content="I prefer evidence-first project reviews.",
                    target_path="Inbox/Pending Memories.md",
                    source_message_id="message-wiring",
                )
            )
        )
        wiki = asyncio.run(
            runtime.services.wiki.manage_page(
                WikiPageWriteRequest(
                    title="Lifecycle Wiring",
                    target_path="Wiki/Lifecycle-Wiring.md",
                    operation="create",
                    content="The production write path is claim and receipt backed.",
                    source_message_id="message-wiring",
                )
            )
        )

        assert task.task_id.startswith("task-")
        assert memory.proposal_id.startswith("memory-proposal-")
        assert wiki.relative_path == "Wiki/Lifecycle-Wiring.md"
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT action_type, status, idempotency_key, metadata_json
                FROM agent_actions
                WHERE action_type IN ('task.create', 'memory.proposal', 'wiki.page.write')
                ORDER BY action_type
                """
            ).fetchall()
        assert [str(row["action_type"]) for row in rows] == [
            "memory.proposal",
            "task.create",
            "wiki.page.write",
        ]
        for row in rows:
            metadata = json.loads(str(row["metadata_json"]))
            assert row["status"] == "completed"
            assert len(str(row["idempotency_key"])) == 64
            assert metadata["control_state"] == "completed"
            assert metadata["execution_receipt"]["status"] == "verified"
            assert metadata["verification_result"]["status"] == "verified"


def test_a_failed_apply_reruns_only_under_a_new_attempt_identity(
    client_factory,
    tmp_path: Path,
) -> None:
    # 失败回执在账本里是终局的:同键重跑只会把它原样回放(适配器不再执行),所以
    # "重试"必须换尝试身份,否则用户点的是一个什么都不做的按钮。
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, tmp_path)
        context = AppContext(app=client.app, request_id="retry-identity")
        lifecycle = agent_runtime(context).services.action_lifecycle
        attempted_keys: list[str] = []
        original = lifecycle.adapters["task.create"]

        async def flaky_task_adapter(proposal, policy, claim):
            attempted_keys.append(claim.idempotency_key)
            if len(attempted_keys) == 1:
                raise RuntimeError("transient_provider_failure")
            return await original(proposal, policy, claim)

        lifecycle.adapters["task.create"] = flaky_task_adapter

        def run(*, attempt: int):
            return asyncio.run(
                _execute_registered_action(
                    context,
                    action_lifecycle=lifecycle,
                    action_type="task.create",
                    target_ref="task:retry-identity",
                    parameters={"title": "Retry identity probe"},
                    expected_effect="Create one local task.",
                    source_message_id="message-retry-identity",
                    reversible=True,
                    attempt=attempt,
                )
            )

        first = run(attempt=1)
        assert first.receipt.status != "verified"

        replayed = run(attempt=1)
        assert replayed.duplicate is True
        assert replayed.receipt.status != "verified"
        assert len(attempted_keys) == 1

        retried = run(attempt=2)
        assert retried.receipt.status == "verified"
        assert len(attempted_keys) == 2
        assert attempted_keys[0] != attempted_keys[1]


def test_unknown_adapter_failures_are_classified_for_diagnosis() -> None:
    # 存储故障、参数校验失败和未知 bug 曾经一律报 action_failed:线上遇到的间歇
    # 失败因此无法归因。领域异常自带的安全码保持不变。
    from pydantic import ValidationError

    from app.agents.nodes.executor import _safe_exception_code

    class DomainFailure(Exception):
        code = "wiki_workflow_failed"

    assert _safe_exception_code(DomainFailure()) == "wiki_workflow_failed"
    assert _safe_exception_code(sqlite3.OperationalError("database is locked")) == "storage_unavailable"
    assert (
        _safe_exception_code(
            ValidationError.from_exception_data("X", [{"type": "missing", "loc": ("a",), "input": None}])
        )
        == "invalid_action_parameters"
    )
    assert _safe_exception_code(RuntimeError("mystery")) is None
