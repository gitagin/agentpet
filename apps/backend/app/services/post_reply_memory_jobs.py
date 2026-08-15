from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.storage.database import open_database_connection
from app.utils.time import utc_now_iso


@dataclass(frozen=True, slots=True)
class PostReplyMemoryJobRecord:
    id: str
    agent_run_id: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    status: str
    stage_states: dict[str, object]
    attempts: int
    lease_owner: str | None
    lease_expires_at: str | None
    last_error_code: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


class PostReplyMemoryJobStore:
    """Durable queue for post-reply work; message bodies remain in messages."""

    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def enqueue(
        self,
        *,
        job_id: str,
        agent_run_id: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        stage_states: dict[str, object] | None = None,
    ) -> PostReplyMemoryJobRecord:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO post_reply_memory_jobs (
                    id, agent_run_id, conversation_id, user_message_id,
                    assistant_message_id, status, stage_states_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                ON CONFLICT(agent_run_id) DO UPDATE SET
                    assistant_message_id = excluded.assistant_message_id,
                    updated_at = excluded.updated_at
                """,
                (
                    job_id,
                    agent_run_id,
                    conversation_id,
                    user_message_id,
                    assistant_message_id,
                    _json(stage_states or {}),
                    now,
                    now,
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM post_reply_memory_jobs WHERE agent_run_id = ?",
            (agent_run_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("post_reply_job_enqueue_failed")
        return _map(row)

    def get(self, job_id: str) -> PostReplyMemoryJobRecord | None:
        row = self.conn.execute(
            "SELECT * FROM post_reply_memory_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return _map(row) if row is not None else None

    def claim(
        self,
        job_id: str,
        *,
        owner: str,
        lease_seconds: int = 300,
        max_attempts: int | None = None,
    ) -> tuple[PostReplyMemoryJobRecord | None, bool]:
        now = utc_now_iso()
        lease_expires = _future_iso(lease_seconds)
        attempt_clause = ""
        attempt_params: tuple[object, ...] = ()
        if max_attempts is not None:
            attempt_clause = " AND attempts < ?"
            attempt_params = (max(1, int(max_attempts)),)
        with self.conn:
            cursor = self.conn.execute(
                f"""
                UPDATE post_reply_memory_jobs
                SET status = 'running', attempts = attempts + 1,
                    lease_owner = ?, lease_expires_at = ?, updated_at = ?,
                    last_error_code = NULL
                WHERE id = ?
                  AND (
                    status = 'pending'
                    OR (status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at < ?))
                  ){attempt_clause}
                """,
                (owner, lease_expires, now, job_id, now, *attempt_params),
            )
        row = self.conn.execute("SELECT * FROM post_reply_memory_jobs WHERE id = ?", (job_id,)).fetchone()
        return (_map(row) if row is not None else None, bool(cursor.rowcount))

    def requeue_failed(self, job_id: str, *, max_attempts: int | None = None) -> bool:
        """Make a failed job eligible for another leased attempt.

        A failed row is intentionally kept visible until an explicit recovery
        pass requeues it. This prevents a process restart from creating an
        unbounded in-memory retry loop while retaining the failure evidence.
        """
        now = utc_now_iso()
        attempt_clause = ""
        params: tuple[object, ...] = ()
        if max_attempts is not None:
            attempt_clause = " AND attempts < ?"
            params = (max(1, int(max_attempts)),)
        with self.conn:
            result = self.conn.execute(
                f"""
                UPDATE post_reply_memory_jobs
                SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'failed'{attempt_clause}
                """,
                (now, job_id, *params),
            )
        return bool(result.rowcount)

    def release(self, job_id: str, *, owner: str, error_code: str | None = None) -> bool:
        """Release a leased job without consuming a retry on shutdown."""
        now = utc_now_iso()
        with self.conn:
            result = self.conn.execute(
                """
                UPDATE post_reply_memory_jobs
                SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?, last_error_code = COALESCE(?, last_error_code)
                WHERE id = ? AND status = 'running' AND lease_owner = ?
                """,
                (now, error_code, job_id, owner),
            )
        return bool(result.rowcount)

    def update_stage_states(self, job_id: str, *, owner: str, stage_states: dict[str, object]) -> bool:
        """Persist bounded, non-sensitive progress while a lease is held."""
        now = utc_now_iso()
        with self.conn:
            result = self.conn.execute(
                """
                UPDATE post_reply_memory_jobs
                SET stage_states_json = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ?
                """,
                (_json(stage_states), now, job_id, owner),
            )
        return bool(result.rowcount)

    def mark_exhausted(self, job_id: str, *, error_code: str = "post_reply_retry_exhausted") -> bool:
        """Terminally retain a job that exceeded the retry budget."""
        now = utc_now_iso()
        with self.conn:
            result = self.conn.execute(
                """
                UPDATE post_reply_memory_jobs
                SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?, last_error_code = ?
                WHERE id = ? AND status IN ('pending', 'failed')
                """,
                (now, str(error_code)[:128], job_id),
            )
        return bool(result.rowcount)

    def complete(self, job_id: str, *, owner: str, stage_states: dict[str, object]) -> None:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                UPDATE post_reply_memory_jobs
                SET status = 'completed', stage_states_json = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?, completed_at = ?, last_error_code = NULL
                WHERE id = ? AND status = 'running' AND lease_owner = ?
                """,
                (_json(stage_states), now, now, job_id, owner),
            )

    def fail(self, job_id: str, *, owner: str, stage_states: dict[str, object], error_code: str) -> None:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                UPDATE post_reply_memory_jobs
                SET status = 'failed', stage_states_json = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?, last_error_code = ?
                WHERE id = ? AND status = 'running' AND lease_owner = ?
                """,
                (_json(stage_states), now, str(error_code)[:128], job_id, owner),
            )

    def requeue_expired(self, *, max_attempts: int | None = None) -> int:
        now = utc_now_iso()
        where = "status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at < ?)"
        params: tuple[object, ...] = (now,)
        with self.conn:
            if max_attempts is not None:
                # A lease that has already consumed the retry budget is a
                # terminal, inspectable failure. Leaving it as ``running``
                # would make startup recovery skip it forever.
                self.conn.execute(
                    f"""
                    UPDATE post_reply_memory_jobs
                    SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
                        updated_at = ?, last_error_code = 'post_reply_retry_exhausted'
                    WHERE {where} AND attempts >= ?
                    """,
                    (now, *params, max(1, int(max_attempts))),
                )
            requeue_where = where
            requeue_params = params
            if max_attempts is not None:
                requeue_where += " AND attempts < ?"
                requeue_params = (*params, max(1, int(max_attempts)))
            result = self.conn.execute(
                f"""
                UPDATE post_reply_memory_jobs
                SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE {requeue_where}
                """,
                (now, *requeue_params),
            )
        return int(result.rowcount)

    def list_pending(self, *, limit: int = 20) -> list[PostReplyMemoryJobRecord]:
        rows = self.conn.execute(
            """
            SELECT * FROM post_reply_memory_jobs
            WHERE status IN ('pending', 'failed')
            ORDER BY updated_at, id
            LIMIT ?
            """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()
        return [_map(row) for row in rows]


def _map(row: sqlite3.Row) -> PostReplyMemoryJobRecord:
    try:
        states = json.loads(str(row["stage_states_json"] or "{}"))
    except json.JSONDecodeError:
        states = {}
    return PostReplyMemoryJobRecord(
        id=str(row["id"]),
        agent_run_id=str(row["agent_run_id"]),
        conversation_id=str(row["conversation_id"]),
        user_message_id=str(row["user_message_id"]),
        assistant_message_id=str(row["assistant_message_id"]),
        status=str(row["status"]),
        stage_states=states if isinstance(states, dict) else {},
        attempts=int(row["attempts"] or 0),
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        last_error_code=row["last_error_code"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        completed_at=row["completed_at"],
    )


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _future_iso(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, seconds))).isoformat()
