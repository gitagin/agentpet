from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.checkpointer import CheckpointConflictError, SQLiteCheckpointStore
from app.agents.contracts import ActionProposal, PolicyDecision
from app.agents.graph_runtime import LangGraphAgentRuntime
from app.agents.nodes.action import _action_planner_node
from app.agents.nodes.policy_guard import evaluate_action_proposal
from app.agents.services import AgentRuntimeServices
from app.agents.state import ActionPlan, AgentRoute, AgentState
from app.models.enums import AgentIntent
from app.storage.database import Database, MigrationRunner


def make_store(tmp_path):
    database = Database(tmp_path / "interrupt.sqlite3")
    MigrationRunner(database).apply()
    return SQLiteCheckpointStore(database)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def pending_payload() -> tuple[ActionPlan, ActionProposal, PolicyDecision]:
    key = "a" * 64
    plan = ActionPlan(
        action_type="wiki",
        payload={
            "kind": "ingest",
            "title": "Safe page",
            "content": "Safe content",
            "auto_organize": True,
        },
        risk_score="high",
        decision="ask",
        status="pending_confirm",
        reversible=False,
        proposal_id="proposal-interrupt",
        policy_version="action-policy.v1",
        idempotency_key=key,
        control_state="pending_confirmation",
    )
    proposal = ActionProposal(
        proposal_id="proposal-interrupt",
        explicit_intent_ref="intent:interrupt",
        action_type="wiki.ingest.apply",
        target_ref="Wiki/Safe.md",
        normalized_target="Wiki/Safe.md",
        parameters={
            "kind": "ingest",
            "title": "Safe page",
            "content": "Safe content",
            "auto_organize": True,
        },
        expected_effect="Write one bounded Wiki page.",
        reversible=False,
        requested_confirmation=True,
    )
    policy = evaluate_action_proposal(proposal)
    key = policy.idempotency_key
    proposal = proposal.model_copy(update={"idempotency_key": key})
    plan.idempotency_key = key
    return plan, proposal, policy


def save_pending(
    store: SQLiteCheckpointStore,
    *,
    checkpoint_id: str = "checkpoint-interrupt",
    decision_id: str = "decision-interrupt-1",
) -> None:
    plan, proposal, policy = pending_payload()
    store.save_pending(
        checkpoint_id=checkpoint_id,
        thread_id="thread-interrupt",
        run_id="run-interrupt",
        graph_version="agent-graph-v1",
        state_version="agent-state-v1",
        node_name="action_agent",
        state={
            "conversation_id": "conversation-interrupt",
            "message_id": "message-interrupt",
            "agent_run_id": "run-interrupt",
            "action_plan": plan.model_dump(mode="json"),
            "action_proposal": proposal.model_dump(mode="json"),
            "policy_decision": policy.model_dump(mode="json"),
            "decision_id": decision_id,
            "decision_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            "action_label": policy.action_type,
            "safe_target_summary": policy.normalized_target,
            "risk_tier": policy.risk_tier,
            "reversible": plan.reversible,
        },
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        action_proposal_id=proposal.proposal_id,
        idempotency_key=policy.idempotency_key,
    )


def test_action_planner_persists_pending_checkpoint_before_finish(tmp_path) -> None:
    store = make_store(tmp_path)
    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="批量改写文件",
        route=AgentRoute(intent=AgentIntent.MANAGE_WIKI, confidence=1.0, reason="test"),
    )
    services = AgentRuntimeServices(checkpoint_store=store)
    graph_state = {"agent_state": state, "events": [], "failed": False}

    asyncio.run(_action_planner_node(graph_state, services))

    assert state.checkpoint_id is not None
    checkpoint = store.get(state.checkpoint_id)
    assert checkpoint.status == "pending_confirmation"
    assert checkpoint.state["action_proposal"]["action_type"] == "local.destructive_request"


def test_approved_resume_calls_executor_once_and_replay_is_terminal(tmp_path, monkeypatch) -> None:
    store = make_store(tmp_path)
    save_pending(store)
    calls: list[str] = []

    async def fake_execute(graph_state, services):
        plan = graph_state["agent_state"].action_plans[0]
        calls.append(plan.proposal_id or "")
        plan.executed = True
        plan.status = "executed"
        plan.control_state = "completed"

    monkeypatch.setattr("app.agents.graph_runtime._execute_action_plan", fake_execute)
    runtime = LangGraphAgentRuntime(AgentRuntimeServices(checkpoint_store=store))

    with pytest.raises(CheckpointConflictError, match="decision_id_mismatch"):
        asyncio.run(
            runtime.resume_checkpoint(
                "checkpoint-interrupt",
                decision_id="forged-decision-id-1",
                decision="approved",
                policy_version="action-policy.v1",
            )
        )
    assert store.get("checkpoint-interrupt").status == "pending_confirmation"
    assert calls == []

    first = asyncio.run(
        runtime.resume_checkpoint(
            "checkpoint-interrupt",
            decision_id="decision-interrupt-1",
            decision="approved",
            policy_version="action-policy.v1",
        )
    )
    replay = asyncio.run(
        runtime.resume_checkpoint(
            "checkpoint-interrupt",
            decision_id="decision-interrupt-2",
            decision="approved",
            policy_version="action-policy.v1",
        )
    )

    assert first == {"checkpoint_id": "checkpoint-interrupt", "status": "completed", "effect_applied": True}
    assert replay == {"checkpoint_id": "checkpoint-interrupt", "status": "completed", "effect_applied": False}
    assert calls == ["proposal-interrupt"]


def test_rejection_is_zero_effect_and_cannot_be_reversed(tmp_path, monkeypatch) -> None:
    store = make_store(tmp_path)
    save_pending(store, checkpoint_id="checkpoint-reject", decision_id="decision-reject-1")
    calls: list[str] = []

    async def fake_execute(graph_state, services):
        calls.append("unexpected")

    monkeypatch.setattr("app.agents.graph_runtime._execute_action_plan", fake_execute)
    runtime = LangGraphAgentRuntime(AgentRuntimeServices(checkpoint_store=store))

    rejected = asyncio.run(
        runtime.resume_checkpoint(
            "checkpoint-reject",
            decision_id="decision-reject-1",
            decision="rejected",
            policy_version="action-policy.v1",
        )
    )
    replay_approval = asyncio.run(
        runtime.resume_checkpoint(
            "checkpoint-reject",
            decision_id="decision-reject-2",
            decision="approved",
            policy_version="action-policy.v1",
        )
    )

    assert rejected["status"] == "rejected"
    assert rejected["effect_applied"] is False
    assert replay_approval["status"] == "rejected"
    assert calls == []


def test_checkpoint_api_exposes_safe_projection_and_rejection(client_factory, tmp_path) -> None:
    with client_factory() as client:
        store = SQLiteCheckpointStore(Database(client.app.state.database.path))
        save_pending(store, checkpoint_id="checkpoint-api", decision_id="decision-api-reject-1")

    with client_factory() as client:
        unauthorized = client.get("/api/checkpoints/pending")
        assert unauthorized.status_code == 401
        listed = client.get("/api/checkpoints/pending", headers=auth_headers())
        assert listed.status_code == 200
        payload = listed.json()
        assert payload[0]["checkpoint_id"] == "checkpoint-api"
        assert "state" not in payload[0]

        rejected = client.post(
            "/api/checkpoints/checkpoint-api/decision",
            headers=auth_headers(),
            json={
                "decision_id": "decision-api-reject-1",
                "decision": "rejected",
                "policy_version": "action-policy.v1",
            },
        )
        assert rejected.status_code == 200
        assert rejected.json() == {
            "checkpoint_id": "checkpoint-api",
            "status": "rejected",
            "effect_applied": False,
        }
