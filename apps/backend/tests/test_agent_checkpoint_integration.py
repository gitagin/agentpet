from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.checkpointer import (
    CheckpointConflictError,
    CheckpointExpiredError,
    SQLiteCheckpointStore,
)
from app.agents.contracts import ActionProposal
from app.agents.graph_runtime import LangGraphAgentRuntime
from app.agents.nodes.policy_guard import evaluate_action_proposal
from app.agents.services import AgentRuntimeServices
from app.agents.state import ActionPlan
from app.storage.database import Database, MigrationRunner


def make_runtime(tmp_path):
    database = Database(tmp_path / "integration.sqlite3")
    MigrationRunner(database).apply()
    store = SQLiteCheckpointStore(database)
    return store, LangGraphAgentRuntime(AgentRuntimeServices(checkpoint_store=store))


def save_checkpoint(
    store: SQLiteCheckpointStore,
    *,
    checkpoint_id: str,
    run_id: str,
    decision_id: str,
    decision_expires_at: datetime | None = None,
    graph_version: str = "agent-graph-v1",
) -> None:
    proposal = ActionProposal(
        proposal_id=f"proposal-{run_id}",
        explicit_intent_ref=f"intent:{run_id}",
        action_type="wiki.ingest.apply",
        target_ref="Wiki/Safe.md",
        normalized_target="Wiki/Safe.md",
        parameters={"kind": "ingest", "title": "Safe", "content": "Safe", "auto_organize": True},
        expected_effect="Write one bounded Wiki page.",
        requested_confirmation=True,
    )
    policy = evaluate_action_proposal(proposal)
    proposal = proposal.model_copy(update={"idempotency_key": policy.idempotency_key})
    plan = ActionPlan(
        action_type="wiki",
        payload={"kind": "ingest", "title": "Safe", "content": "Safe", "auto_organize": True},
        risk_score=policy.risk_tier,
        decision="ask",
        status="pending_confirm",
        proposal_id=proposal.proposal_id,
        policy_version=policy.policy_version,
        idempotency_key=policy.idempotency_key,
        control_state="pending_confirmation",
    )
    store.save_pending(
        checkpoint_id=checkpoint_id,
        thread_id="thread-integration",
        run_id=run_id,
        graph_version=graph_version,
        state_version="agent-state-v1",
        node_name="action_agent",
        state={
            "conversation_id": "conversation-integration",
            "message_id": f"message-{run_id}",
            "agent_run_id": run_id,
            "action_plan": plan.model_dump(mode="json"),
            "action_proposal": proposal.model_dump(mode="json"),
            "policy_decision": policy.model_dump(mode="json"),
            "decision_id": decision_id,
            "decision_expires_at": (
                decision_expires_at or datetime.now(timezone.utc) + timedelta(minutes=15)
            ).isoformat(),
            "action_label": policy.action_type,
            "safe_target_summary": policy.normalized_target,
            "risk_tier": policy.risk_tier,
            "reversible": plan.reversible,
        },
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        action_proposal_id=proposal.proposal_id,
        idempotency_key=policy.idempotency_key,
    )


def test_cross_checkpoint_decision_is_rejected_before_claim(tmp_path) -> None:
    store, runtime = make_runtime(tmp_path)
    save_checkpoint(store, checkpoint_id="checkpoint-a", run_id="run-a", decision_id="decision-a-secure")
    save_checkpoint(store, checkpoint_id="checkpoint-b", run_id="run-b", decision_id="decision-b-secure")

    with pytest.raises(CheckpointConflictError, match="decision_id_mismatch"):
        asyncio.run(
            runtime.resume_checkpoint(
                "checkpoint-a",
                decision_id="decision-b-secure",
                decision="approved",
                policy_version="action-policy.v1",
            )
        )

    assert store.get("checkpoint-a").status == "pending_confirmation"
    assert store.get("checkpoint-b").status == "pending_confirmation"


def test_expired_decision_is_zero_effect(tmp_path, monkeypatch) -> None:
    store, runtime = make_runtime(tmp_path)
    save_checkpoint(
        store,
        checkpoint_id="checkpoint-expired-decision",
        run_id="run-expired",
        decision_id="decision-expired-secure",
        decision_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    calls: list[str] = []

    async def fake_execute(graph_state, services):
        calls.append("unexpected")

    monkeypatch.setattr("app.agents.graph_runtime._execute_action_plan", fake_execute)
    with pytest.raises(CheckpointExpiredError):
        asyncio.run(
            runtime.resume_checkpoint(
                "checkpoint-expired-decision",
                decision_id="decision-expired-secure",
                decision="approved",
                policy_version="action-policy.v1",
            )
        )

    assert store.get("checkpoint-expired-decision").status == "expired"
    assert calls == []


def test_graph_version_mismatch_is_rejected_before_claim(tmp_path) -> None:
    store, runtime = make_runtime(tmp_path)
    save_checkpoint(
        store,
        checkpoint_id="checkpoint-old-graph",
        run_id="run-old",
        decision_id="decision-old-secure",
        graph_version="agent-graph-v0",
    )

    with pytest.raises(CheckpointConflictError, match="checkpoint_version_mismatch"):
        asyncio.run(
            runtime.resume_checkpoint(
                "checkpoint-old-graph",
                decision_id="decision-old-secure",
                decision="approved",
                policy_version="action-policy.v1",
            )
        )
    assert store.get("checkpoint-old-graph").status == "pending_confirmation"


def test_executor_failure_has_one_stable_failed_recovery_terminal(tmp_path, monkeypatch) -> None:
    store, runtime = make_runtime(tmp_path)
    save_checkpoint(
        store,
        checkpoint_id="checkpoint-failure",
        run_id="run-failure",
        decision_id="decision-failure-secure",
    )
    calls: list[str] = []

    async def fake_execute(graph_state, services):
        calls.append("execute")
        plan = graph_state["agent_state"].action_plans[0]
        plan.executed = True
        plan.status = "failed"
        plan.control_state = "failed_recovery"

    monkeypatch.setattr("app.agents.graph_runtime._execute_action_plan", fake_execute)
    first = asyncio.run(
        runtime.resume_checkpoint(
            "checkpoint-failure",
            decision_id="decision-failure-secure",
            decision="approved",
            policy_version="action-policy.v1",
        )
    )
    replay = asyncio.run(
        runtime.resume_checkpoint(
            "checkpoint-failure",
            decision_id="decision-replay-secure",
            decision="approved",
            policy_version="action-policy.v1",
        )
    )

    assert first["status"] == "failed_recovery"
    assert replay["status"] == "failed_recovery"
    assert calls == ["execute"]


def test_pending_checkpoint_short_circuits_chat_tool_path(tmp_path) -> None:
    store, runtime = make_runtime(tmp_path)
    save_checkpoint(store, checkpoint_id="checkpoint-short-circuit", run_id="run-short", decision_id="decision-short-secure")
    record = store.get("checkpoint-short-circuit")
    from app.agents.state import AgentState

    state = AgentState(
        conversation_id="conversation-integration",
        message_id="message-run-short",
        agent_run_id="run-short",
        user_message="[pending checkpoint]",
        response_text="等待确认",
        checkpoint_id="checkpoint-short-circuit",
        checkpoint_status="pending_confirmation",
    )
    graph_state = {"agent_state": state, "events": [], "failed": False}
    result = asyncio.run(runtime._chat_node_adapter(graph_state))

    assert result["agent_state"].response_text == "等待确认"
    assert any(getattr(event, "stage", None) == "pending_confirmation" for event in result["events"])
    assert record.status == "pending_confirmation"
