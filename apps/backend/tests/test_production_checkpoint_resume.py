from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from apps.backend.tests._schema import migrate_db

from app.agents.checkpointer import SQLiteCheckpointStore
from app.agents.graph_runtime import LangGraphAgentRuntime
from app.agents.nodes.action import _action_planner_node
from app.agents.nodes.executor import ActionLedgerProtocol, ActionLifecycleCoordinator
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentRoute, AgentState, ClassifierResult
from app.api.services import adapters
from app.models.enums import AgentIntent
from app.services.agent_actions import AgentActionService, AgentActionStore
from app.services.memory import SafeMarkdownWriter
from app.services.wiki import WikiService
from app.storage.database import Database


class _ProcessCrash(BaseException):
    """Stand in for a process exit after the local effect has committed."""


def _build_wiki_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = migrate_db(tmp_path / "state.sqlite3")
    vault = tmp_path / "Vault"
    writer = SafeMarkdownWriter(vault)
    request: Any = object()
    monkeypatch.setattr(adapters, "wiki_service", lambda _request: WikiService(writer))

    ledger = cast(ActionLedgerProtocol, AgentActionService(AgentActionStore(db_path)))
    checkpoint_store = SQLiteCheckpointStore(Database(db_path))
    base_adapter = adapters._wiki_action_adapter(request)
    reader = adapters._wiki_action_reader(request)
    calls = {"count": 0}

    async def adapter(proposal, policy, claim):
        calls["count"] += 1
        return await base_adapter(proposal, policy, claim)

    coordinator = ActionLifecycleCoordinator(
        ledger=ledger,
        adapters={"wiki.page.write": adapter},
        readers={"wiki.page.write": reader},
    )
    services = AgentRuntimeServices(
        checkpoint_store=checkpoint_store,
        action_lifecycle=coordinator,
        allow_ephemeral_lifecycle=False,
    )
    return db_path, vault, writer, calls, checkpoint_store, coordinator, services, ledger


def _plan_page_write(services: AgentRuntimeServices) -> AgentState:
    state = AgentState(
        conversation_id="conversation-approval",
        message_id="message-approval",
        agent_run_id="run-approval",
        user_message="覆盖 Wiki 文件 Wiki/Approval.md",
        route=AgentRoute(intent=AgentIntent.MANAGE_WIKI, confidence=1.0, reason="test"),
        classifier=ClassifierResult(
            intent="action",
            action_type="wiki",
            action_params={
                "kind": "page",
                "title": "Approval",
                "target_path": "Wiki/Approval.md",
                "content": "Approval evidence",
                "auto_organize": True,
            },
            confidence=1.0,
            reason="test",
        ),
    )
    graph_state = {"agent_state": state, "events": [], "failed": False}
    asyncio.run(_action_planner_node(graph_state, services))
    assert state.checkpoint_id is not None
    assert state.action_proposals[0].action_type == "wiki.page.write"
    assert state.policy_decisions[0].decision == "pending_confirmation"
    return state


def _decision_values(checkpoint_store: SQLiteCheckpointStore, checkpoint_id: str) -> tuple[str, str]:
    record = checkpoint_store.get(checkpoint_id)
    return str(record.state["decision_id"]), str(record.state["policy_decision"]["policy_version"])


def test_approved_checkpoint_runs_real_wiki_adapter_once_and_replay_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, vault, _, calls, checkpoint_store, coordinator, services, _ = _build_wiki_runtime(tmp_path, monkeypatch)
    state = _plan_page_write(services)
    record = checkpoint_store.get(state.checkpoint_id or "")
    proposal_parameters = record.state["action_proposal"]["parameters"]
    assert proposal_parameters["target_path"] == "Wiki/Approval.md"
    assert proposal_parameters["content"] == "Approval evidence"
    assert record.state["action_plan"]["idempotency_key"] == record.state["policy_decision"]["idempotency_key"]
    stored_canonical_parameters = record.state["policy_decision"]["canonical_parameters"]
    observed: list[tuple[dict[str, Any], dict[str, Any], str | None]] = []
    original_adapter = coordinator.adapters["wiki.page.write"]

    async def capture_resume_inputs(proposal, policy, claim):
        observed.append(
            (
                dict(proposal.parameters),
                dict(policy.canonical_parameters),
                proposal.source_message_id,
            )
        )
        return await original_adapter(proposal, policy, claim)

    coordinator.adapters["wiki.page.write"] = capture_resume_inputs

    decision_id, policy_version = _decision_values(checkpoint_store, state.checkpoint_id or "")
    runtime = LangGraphAgentRuntime(services)
    first = asyncio.run(
        runtime.resume_checkpoint(
            state.checkpoint_id or "",
            decision_id=decision_id,
            decision="approved",
            policy_version=policy_version,
        )
    )
    replay = asyncio.run(
        runtime.resume_checkpoint(
            state.checkpoint_id or "",
            decision_id=decision_id,
            decision="approved",
            policy_version=policy_version,
        )
    )

    assert first["status"] == "completed"
    assert first["effect_applied"] is True
    assert replay == {
        "checkpoint_id": state.checkpoint_id,
        "status": "completed",
        "effect_applied": False,
    }
    assert calls["count"] == 1
    assert observed == [
        (
            dict(proposal_parameters),
            dict(stored_canonical_parameters),
            "message-approval",
        )
    ]
    page = vault / "Wiki" / "Approval.md"
    marker = f"<!-- llmwiki-action:{record.state['policy_decision']['idempotency_key']} -->"
    assert page.exists()
    assert page.read_text(encoding="utf-8").count(marker) == 1


def test_rejected_checkpoint_has_zero_wiki_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, vault, _, calls, checkpoint_store, coordinator, services, ledger = _build_wiki_runtime(
        tmp_path,
        monkeypatch,
    )
    state = _plan_page_write(services)
    checkpoint_id = state.checkpoint_id or ""
    proposal = state.action_proposals[0]
    policy = state.policy_decisions[0]
    pending = asyncio.run(
        coordinator.execute(
            proposal,
            policy,
            source_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
        )
    )
    assert pending.action.status == "pending_confirmation"
    decision_id, policy_version = _decision_values(checkpoint_store, checkpoint_id)
    result = asyncio.run(
        LangGraphAgentRuntime(services).resume_checkpoint(
            checkpoint_id,
            decision_id=decision_id,
            decision="rejected",
            policy_version=policy_version,
        )
    )

    assert result == {"checkpoint_id": checkpoint_id, "status": "rejected", "effect_applied": False}
    assert calls["count"] == 0
    assert not (vault / "Wiki" / "Approval.md").exists()
    assert checkpoint_store.get(checkpoint_id).status == "rejected"
    denied = ledger.find_execution(policy.idempotency_key)
    assert denied is not None
    assert denied.action_id == pending.action.action_id
    assert denied.status == "denied"
    assert denied.metadata["execution_receipt"]["status"] == "denied"
    assert denied.metadata["execution_receipt"]["safe_error_code"] == "policy_denied"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, status FROM agent_actions WHERE idempotency_key = ?",
            (policy.idempotency_key,),
        ).fetchall()
    assert rows == [(pending.action.action_id, "denied")]


def test_rejected_checkpoint_replay_repairs_pending_action_after_decision_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, vault, _, calls, checkpoint_store, coordinator, services, ledger = _build_wiki_runtime(
        tmp_path,
        monkeypatch,
    )
    state = _plan_page_write(services)
    checkpoint_id = state.checkpoint_id or ""
    proposal = state.action_proposals[0]
    policy = state.policy_decisions[0]
    pending = asyncio.run(
        coordinator.execute(
            proposal,
            policy,
            source_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
        )
    )
    decision_id, policy_version = _decision_values(checkpoint_store, checkpoint_id)
    checkpoint_store.claim_decision(
        checkpoint_id=checkpoint_id,
        decision_id=decision_id,
        decision="rejected",
        policy_version=policy_version,
    )

    still_pending = ledger.find_execution(policy.idempotency_key)
    assert still_pending is not None
    assert still_pending.action_id == pending.action.action_id
    assert still_pending.status == "pending_confirmation"

    result = asyncio.run(
        LangGraphAgentRuntime(services).resume_checkpoint(
            checkpoint_id,
            decision_id=decision_id,
            decision="rejected",
            policy_version=policy_version,
        )
    )

    assert result == {"checkpoint_id": checkpoint_id, "status": "rejected", "effect_applied": False}
    assert calls["count"] == 0
    assert not (vault / "Wiki" / "Approval.md").exists()
    denied = ledger.find_execution(policy.idempotency_key)
    assert denied is not None
    assert denied.action_id == pending.action.action_id
    assert denied.status == "denied"
    receipt = denied.metadata["execution_receipt"]
    assert receipt["status"] == "denied"
    assert receipt["safe_error_code"] == "policy_denied"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, status FROM agent_actions WHERE idempotency_key = ?",
            (policy.idempotency_key,),
        ).fetchall()
    assert rows == [(pending.action.action_id, "denied")]


def test_effect_before_receipt_crash_is_recovered_without_repeating_wiki_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, vault, _, calls, checkpoint_store, coordinator, services, ledger = _build_wiki_runtime(tmp_path, monkeypatch)
    state = _plan_page_write(services)
    checkpoint_id = state.checkpoint_id or ""
    decision_id, policy_version = _decision_values(checkpoint_store, checkpoint_id)
    original_adapter = coordinator.adapters["wiki.page.write"]

    async def crash_after_effect(proposal, policy, claim):
        await original_adapter(proposal, policy, claim)
        raise _ProcessCrash("process exited after Wiki commit")

    coordinator.adapters["wiki.page.write"] = crash_after_effect
    runtime = LangGraphAgentRuntime(services)
    with pytest.raises(_ProcessCrash, match="Wiki commit"):
        awaitable = runtime.resume_checkpoint(
            checkpoint_id,
            decision_id=decision_id,
            decision="approved",
            policy_version=policy_version,
        )
        asyncio.run(awaitable)

    assert checkpoint_store.get(checkpoint_id).status == "approved"
    action = ledger.find_execution(str(checkpoint_store.get(checkpoint_id).idempotency_key))
    assert action is not None and action.status == "executing"

    coordinator.adapters["wiki.page.write"] = original_adapter
    recovered = asyncio.run(
        runtime.resume_checkpoint(
            checkpoint_id,
            decision_id=decision_id,
            decision="approved",
            policy_version=policy_version,
        )
    )

    assert recovered == {"checkpoint_id": checkpoint_id, "status": "completed", "effect_applied": False}
    assert calls["count"] == 1
    marker = f"<!-- llmwiki-action:{checkpoint_store.get(checkpoint_id).idempotency_key} -->"
    assert (vault / "Wiki" / "Approval.md").read_text(encoding="utf-8").count(marker) == 1
    assert checkpoint_store.get(checkpoint_id).terminal_receipt_ref


def test_unsupported_confirmation_preserves_target_and_fails_closed_after_approval(
    tmp_path: Path,
) -> None:
    db_path = migrate_db(tmp_path / "unsupported.sqlite3")
    checkpoint_store = SQLiteCheckpointStore(Database(db_path))
    services = AgentRuntimeServices(checkpoint_store=checkpoint_store, allow_ephemeral_lifecycle=False)
    state = AgentState(
        conversation_id="conversation-unsupported",
        message_id="message-unsupported",
        agent_run_id="run-unsupported",
        user_message="删除所有本地记忆文件",
        route=AgentRoute(intent=AgentIntent.MANAGE_WIKI, confidence=1.0, reason="test"),
    )
    graph_state = {"agent_state": state, "events": [], "failed": False}
    asyncio.run(_action_planner_node(graph_state, services))

    checkpoint_id = state.checkpoint_id or ""
    record = checkpoint_store.get(checkpoint_id)
    proposal = record.state["action_proposal"]
    assert record.status == "pending_confirmation"
    assert proposal["action_type"] == "local.destructive_request"
    assert proposal["parameters"]["request_text"] == state.user_message
    assert proposal["parameters"]["requested_target"] == state.user_message
    assert str(proposal["target_ref"]).startswith("intent:unsupported-mutation:")

    decision_id, policy_version = _decision_values(checkpoint_store, checkpoint_id)
    result = asyncio.run(
        LangGraphAgentRuntime(services).resume_checkpoint(
            checkpoint_id,
            decision_id=decision_id,
            decision="approved",
            policy_version=policy_version,
        )
    )
    assert result == {"checkpoint_id": checkpoint_id, "status": "failed_recovery", "effect_applied": False}
    assert checkpoint_store.get(checkpoint_id).status == "failed_recovery"
