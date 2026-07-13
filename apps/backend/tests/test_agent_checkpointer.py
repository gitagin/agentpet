from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.checkpointer import (
    CheckpointConflictError,
    CheckpointError,
    CheckpointExpiredError,
    CheckpointVersionMismatchError,
    SQLiteCheckpointStore,
)
from app.storage.database import Database, MigrationRunner


def make_store(tmp_path):
    database = Database(tmp_path / "checkpoint.sqlite3")
    MigrationRunner(database).apply()
    return database, SQLiteCheckpointStore(database)


def test_checkpoint_round_trip_and_restart_isolation(tmp_path) -> None:
    database, store = make_store(tmp_path)
    expiry = datetime.now(timezone.utc) + timedelta(hours=24)

    created = store.save_pending(
        checkpoint_id="cp-1",
        thread_id="thread-1",
        run_id="run-1",
        graph_version="graph-v1",
        state_version="state-v1",
        node_name="action_agent",
        state={"risk": "high", "target_class": "wiki"},
        expires_at=expiry,
        action_proposal_id="proposal-1",
        idempotency_key="effect-1",
        public_event_cursor=4,
    )

    restarted = SQLiteCheckpointStore(Database(database.path))
    loaded = restarted.load_for_resume("cp-1", graph_version="graph-v1", state_version="state-v1")
    assert loaded == created
    assert restarted.list_pending(thread_id="thread-1")[0].checkpoint_id == "cp-1"


def test_checkpoint_rejects_sensitive_or_unbounded_state(tmp_path) -> None:
    _, store = make_store(tmp_path)
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    with pytest.raises(CheckpointError, match="forbidden checkpoint field"):
        store.save_pending(
            checkpoint_id="cp-sensitive",
            thread_id="thread-1",
            run_id="run-1",
            graph_version="graph-v1",
            state_version="state-v1",
            node_name="action_agent",
            state={"authorization": "Bearer redacted"},
            expires_at=expiry,
        )

    with pytest.raises(CheckpointError, match="bounded size"):
        store.save_pending(
            checkpoint_id="cp-large",
            thread_id="thread-1",
            run_id="run-1",
            graph_version="graph-v1",
            state_version="state-v1",
            node_name="action_agent",
            state={"safe": "x" * 70_000},
            expires_at=expiry,
        )


def test_decision_claim_is_single_use_and_replay_returns_original(tmp_path) -> None:
    _, store = make_store(tmp_path)
    store.save_pending(
        checkpoint_id="cp-decision",
        thread_id="thread-1",
        run_id="run-1",
        graph_version="graph-v1",
        state_version="state-v1",
        node_name="action_agent",
        state={"safe": True},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    first = store.claim_decision(
        checkpoint_id="cp-decision",
        decision_id="decision-1",
        decision="approved",
        policy_version="policy-v1",
    )
    replay = store.claim_decision(
        checkpoint_id="cp-decision",
        decision_id="decision-2",
        decision="rejected",
        policy_version="policy-v1",
    )
    assert first == replay
    assert store.get("cp-decision").status == "approved"


def test_expiry_and_version_mismatch_fail_closed(tmp_path) -> None:
    _, store = make_store(tmp_path)
    store.save_pending(
        checkpoint_id="cp-expired",
        thread_id="thread-1",
        run_id="run-1",
        graph_version="graph-v1",
        state_version="state-v1",
        node_name="action_agent",
        state={"safe": True},
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    assert store.expire_due(now=datetime.now(timezone.utc)) == 1
    with pytest.raises(CheckpointExpiredError):
        store.load_for_resume("cp-expired", graph_version="graph-v1", state_version="state-v1")

    store.save_pending(
        checkpoint_id="cp-version",
        thread_id="thread-1",
        run_id="run-2",
        graph_version="graph-v1",
        state_version="state-v1",
        node_name="action_agent",
        state={"safe": True},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    with pytest.raises(CheckpointVersionMismatchError):
        store.load_for_resume("cp-version", graph_version="graph-v2", state_version="state-v1")


def test_checkpoint_delete_cascades_only_checkpoint_decision_rows(tmp_path) -> None:
    database, store = make_store(tmp_path)
    store.save_pending(
        checkpoint_id="cp-delete",
        thread_id="thread-1",
        run_id="run-1",
        graph_version="graph-v1",
        state_version="state-v1",
        node_name="action_agent",
        state={"safe": True},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    store.claim_decision(
        checkpoint_id="cp-delete",
        decision_id="decision-delete",
        decision="rejected",
        policy_version="policy-v1",
    )
    store.delete_checkpoint("cp-delete")

    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_checkpoints").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_checkpoint_decisions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 18


def test_duplicate_checkpoint_is_rejected(tmp_path) -> None:
    _, store = make_store(tmp_path)
    kwargs = dict(
        checkpoint_id="cp-duplicate",
        thread_id="thread-1",
        run_id="run-1",
        graph_version="graph-v1",
        state_version="state-v1",
        node_name="action_agent",
        state={"safe": True},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    store.save_pending(**kwargs)
    with pytest.raises(CheckpointConflictError):
        store.save_pending(**kwargs)
