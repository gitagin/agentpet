from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from app.storage.database import Database


CheckpointStatus = Literal[
    "pending_confirmation",
    "approved",
    "rejected",
    "expired",
    "cancelled",
    "completed",
    "failed_recovery",
]
Decision = Literal["approved", "rejected", "expired"]

_MAX_STATE_BYTES = 65_536
_FORBIDDEN_KEY = re.compile(
    r"authorization|bearer|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"private[_-]?key|secret|password|raw[_-]?(prompt|output|tool|evidence)|"
    r"chain[_-]?of[_-]?thought|source[_-]?(text|excerpt)",
    re.IGNORECASE,
)


class CheckpointError(ValueError):
    """Base error for safe, deterministic checkpoint failures."""


class CheckpointConflictError(CheckpointError):
    pass


class CheckpointNotFoundError(CheckpointError):
    pass


class CheckpointExpiredError(CheckpointError):
    pass


class CheckpointVersionMismatchError(CheckpointError):
    pass


class CheckpointCorruptError(CheckpointError):
    pass


@dataclass(frozen=True)
class CheckpointRecord:
    checkpoint_id: str
    thread_id: str
    run_id: str
    graph_version: str
    state_version: str
    node_name: str
    state: dict[str, Any]
    action_proposal_id: str | None
    idempotency_key: str | None
    status: CheckpointStatus
    public_event_cursor: int | None
    terminal_receipt_ref: str | None
    created_at: str
    updated_at: str
    expires_at: str


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    checkpoint_id: str
    decision: Decision
    policy_version: str
    decided_at: str
    expires_at: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(timezone.utc).isoformat()


def _walk_forbidden(value: Any, path: str = "state") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if _FORBIDDEN_KEY.search(key_text):
                raise CheckpointError(f"forbidden checkpoint field: {path}.{key_text}")
            _walk_forbidden(child, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _walk_forbidden(child, f"{path}[{index}]")


def _encode_state(state: Mapping[str, Any]) -> str:
    _walk_forbidden(state)
    try:
        encoded = json.dumps(state, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise CheckpointError("checkpoint state must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_STATE_BYTES:
        raise CheckpointError("checkpoint state exceeds the bounded size limit")
    return encoded


class SQLiteCheckpointStore:
    """Minimal SQLite persistence boundary for future graph checkpoint injection."""

    def __init__(self, database: Database | str | Path) -> None:
        self.database = database if isinstance(database, Database) else Database(database)

    def save_pending(
        self,
        *,
        checkpoint_id: str,
        thread_id: str,
        run_id: str,
        graph_version: str,
        state_version: str,
        node_name: str,
        state: Mapping[str, Any],
        expires_at: datetime,
        action_proposal_id: str | None = None,
        idempotency_key: str | None = None,
        public_event_cursor: int | None = None,
    ) -> CheckpointRecord:
        encoded_state = _encode_state(state)
        now = _timestamp()
        expiry = _timestamp(expires_at)
        try:
            with self.database.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_checkpoints (
                        checkpoint_id, thread_id, run_id, graph_version,
                        state_version, node_name, state_json, action_proposal_id,
                        idempotency_key, status, public_event_cursor,
                        created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_confirmation', ?, ?, ?, ?)
                    """,
                    (
                        checkpoint_id,
                        thread_id,
                        run_id,
                        graph_version,
                        state_version,
                        node_name,
                        encoded_state,
                        action_proposal_id,
                        idempotency_key,
                        public_event_cursor,
                        now,
                        now,
                        expiry,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise CheckpointConflictError(f"checkpoint already exists: {checkpoint_id}") from exc
        return self.get(checkpoint_id)

    def get(self, checkpoint_id: str) -> CheckpointRecord:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            raise CheckpointNotFoundError(checkpoint_id)
        return self._map_checkpoint(row)

    def list_pending(self, *, thread_id: str | None = None) -> list[CheckpointRecord]:
        query = "SELECT * FROM agent_checkpoints WHERE status = 'pending_confirmation'"
        params: tuple[str, ...] = ()
        if thread_id is not None:
            query += " AND thread_id = ?"
            params = (thread_id,)
        query += " ORDER BY created_at DESC"
        with self.database.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._map_checkpoint(row) for row in rows]

    def claim_decision(
        self,
        *,
        checkpoint_id: str,
        decision_id: str,
        decision: Literal["approved", "rejected"],
        policy_version: str,
        now: datetime | None = None,
    ) -> DecisionRecord:
        decided_at = _timestamp(now)
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM agent_checkpoint_decisions WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return self._map_decision(existing)

            row = conn.execute(
                "SELECT status, expires_at FROM agent_checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise CheckpointNotFoundError(checkpoint_id)
            if row["status"] != "pending_confirmation":
                conn.rollback()
                raise CheckpointConflictError(f"checkpoint is not pending: {checkpoint_id}")
            if row["expires_at"] <= decided_at:
                self._expire_locked(conn, checkpoint_id, decided_at)
                conn.commit()
                raise CheckpointExpiredError(checkpoint_id)

            conn.execute(
                """
                INSERT INTO agent_checkpoint_decisions (
                    decision_id, checkpoint_id, decision, policy_version,
                    decided_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (decision_id, checkpoint_id, decision, policy_version, decided_at, row["expires_at"]),
            )
            conn.execute(
                "UPDATE agent_checkpoints SET status = ?, updated_at = ? WHERE checkpoint_id = ?",
                (decision, decided_at, checkpoint_id),
            )
            conn.commit()
            result = conn.execute(
                "SELECT * FROM agent_checkpoint_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        assert result is not None
        return self._map_decision(result)

    def expire_due(self, *, now: datetime | None = None) -> int:
        timestamp = _timestamp(now)
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT checkpoint_id, expires_at FROM agent_checkpoints "
                "WHERE status = 'pending_confirmation' AND expires_at <= ?",
                (timestamp,),
            ).fetchall()
            for row in rows:
                self._expire_locked(conn, row["checkpoint_id"], timestamp)
            conn.commit()
        return len(rows)

    def expire_checkpoint(self, checkpoint_id: str, *, now: datetime | None = None) -> None:
        timestamp = _timestamp(now)
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM agent_checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise CheckpointNotFoundError(checkpoint_id)
            if row["status"] != "pending_confirmation":
                conn.rollback()
                raise CheckpointConflictError(f"checkpoint is not pending: {checkpoint_id}")
            self._expire_locked(conn, checkpoint_id, timestamp)
            conn.commit()

    def delete_checkpoint(self, checkpoint_id: str) -> None:
        with self.database.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            )
            if cursor.rowcount == 0:
                raise CheckpointNotFoundError(checkpoint_id)

    def mark_status(
        self,
        checkpoint_id: str,
        status: CheckpointStatus,
        *,
        terminal_receipt_ref: str | None = None,
    ) -> None:
        with self.database.connect() as conn:
            cursor = conn.execute(
                "UPDATE agent_checkpoints SET status = ?, terminal_receipt_ref = ?, "
                "updated_at = ? WHERE checkpoint_id = ?",
                (status, terminal_receipt_ref, _timestamp(), checkpoint_id),
            )
            if cursor.rowcount == 0:
                raise CheckpointNotFoundError(checkpoint_id)

    def load_for_resume(
        self,
        checkpoint_id: str,
        *,
        graph_version: str,
        state_version: str,
    ) -> CheckpointRecord:
        record = self.get(checkpoint_id)
        if record.graph_version != graph_version or record.state_version != state_version:
            raise CheckpointVersionMismatchError(checkpoint_id)
        if record.status == "expired":
            raise CheckpointExpiredError(checkpoint_id)
        return record

    @staticmethod
    def _expire_locked(conn: sqlite3.Connection, checkpoint_id: str, timestamp: str) -> None:
        row = conn.execute(
            "SELECT expires_at FROM agent_checkpoints WHERE checkpoint_id = ?",
            (checkpoint_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute(
            "INSERT OR IGNORE INTO agent_checkpoint_decisions "
            "(decision_id, checkpoint_id, decision, policy_version, decided_at, expires_at) "
            "VALUES (?, ?, 'expired', 'system-expiry-v1', ?, ?)",
            (f"expiry:{checkpoint_id}", checkpoint_id, timestamp, row["expires_at"]),
        )
        conn.execute(
            "UPDATE agent_checkpoints SET status = 'expired', updated_at = ? "
            "WHERE checkpoint_id = ? AND status = 'pending_confirmation'",
            (timestamp, checkpoint_id),
        )

    @staticmethod
    def _map_checkpoint(row: sqlite3.Row) -> CheckpointRecord:
        try:
            state = json.loads(row["state_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CheckpointCorruptError(row["checkpoint_id"]) from exc
        if not isinstance(state, dict):
            raise CheckpointCorruptError(row["checkpoint_id"])
        return CheckpointRecord(
            checkpoint_id=row["checkpoint_id"],
            thread_id=row["thread_id"],
            run_id=row["run_id"],
            graph_version=row["graph_version"],
            state_version=row["state_version"],
            node_name=row["node_name"],
            state=state,
            action_proposal_id=row["action_proposal_id"],
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            public_event_cursor=row["public_event_cursor"],
            terminal_receipt_ref=row["terminal_receipt_ref"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
        )

    @staticmethod
    def _map_decision(row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            decision_id=row["decision_id"],
            checkpoint_id=row["checkpoint_id"],
            decision=row["decision"],
            policy_version=row["policy_version"],
            decided_at=row["decided_at"],
            expires_at=row["expires_at"],
        )
