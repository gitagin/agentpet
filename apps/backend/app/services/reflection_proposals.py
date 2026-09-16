"""Review-queue storage for background reflection proposals.

The reflection agent looks back at a finished exchange and suggests memory or
organisation work.  Those suggestions are proposals, not effects: this module
only stores them and moves them through a review state machine.  Actually
turning a confirmed proposal into memory is the executor's job.

Identity is content-derived.  A suggestion that keeps coming back with the same
meaning must map to the same row, otherwise dismissing it does nothing and the
queue fills with per-turn duplicates -- the failure mode the continuity
subsystem already paid for.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from app.models.common import new_id
from app.storage.database import open_database_connection
from app.utils.hash import sha256_hex
from app.utils.time import coerce_datetime, utc_now_iso

PENDING = "pending"
REJECTED = "rejected"
APPLIED = "applied"
DENIED = "denied"
FAILED = "failed"
APPLYING = "applying"

REFLECTION_STATUSES = (PENDING, APPLYING, REJECTED, APPLIED, DENIED, FAILED)

# 队列语义:用户还需要处理的建议。failed 不是用户的决定,而是系统这一轮没做成,
# 因此留在队列里等用户重试或忽略;只有用户自己的决定(rejected/applied/denied)
# 才离开队列。
ATTENTION_STATUSES = (PENDING, FAILED)

# 落地重试预算。限次重试而不是无限复跑:永久性失败(例如没有配置 Wiki)再点也
# 不会成功,预算用完就只剩"忽略"这个出口。
MAX_APPLY_ATTEMPTS = 3

# 已经写过效果的落地不值得换身份重试:Wiki 摘要的效果是按尝试身份追加的日志行
# (markers 里带着幂等键),重试会再追加一条。记忆登记那两步各自按行身份幂等,
# 所以只有它还值得重试。
NON_RETRYABLE_APPLY_KINDS = frozenset({"wiki_summary"})


class ReflectionProposalNotFoundError(Exception):
    pass


class ReflectionProposalStateError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ReflectionProposalRecord:
    id: str
    proposal_kind: str
    action_type: str
    target_ref: str | None
    content: str
    confidence: float
    reversible: bool
    status: str
    rejected_reason: str | None
    error: str | None
    applied_ref: str | None
    apply_attempts: int
    source_conversation_id: str | None
    source_message_id: str | None
    agent_run_id: str | None
    created_at: str
    updated_at: str


def reflection_proposal_hash(*, proposal_kind: str, action_type: str, content: str) -> str:
    """Content-derived identity, deliberately free of per-turn identifiers."""
    raw = "\n".join(
        [
            proposal_kind.casefold().strip(),
            action_type.casefold().strip(),
            " ".join(content.split()).casefold(),
        ]
    )
    return sha256_hex(raw)


class ReflectionProposalService:
    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def record(
        self,
        *,
        proposal_kind: str,
        action_type: str,
        content: str,
        confidence: float,
        status: str,
        target_ref: str | None = None,
        reversible: bool = True,
        source_conversation_id: str | None = None,
        source_message_id: str | None = None,
        agent_run_id: str | None = None,
        error: str | None = None,
    ) -> ReflectionProposalRecord:
        """Insert one proposal, or return the existing row with the same meaning.

        Re-recording never resurrects a decision the user already made: the row
        keeps its status, and only ``updated_at`` moves.
        """
        if status not in REFLECTION_STATUSES:
            raise ValueError(f"unknown reflection proposal status: {status}")
        proposal_hash = reflection_proposal_hash(
            proposal_kind=proposal_kind,
            action_type=action_type,
            content=content,
        )
        existing = self._row_by_hash(proposal_hash)
        now = utc_now_iso()
        if existing is not None:
            self.conn.execute(
                "UPDATE reflection_proposals SET updated_at = ? WHERE id = ?",
                (now, str(existing["id"])),
            )
            self.conn.commit()
            return self._map(self._row(str(existing["id"])))
        proposal_id = new_id()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO reflection_proposals (
                    id, proposal_hash, proposal_kind, action_type, target_ref,
                    content, confidence, reversible, status, rejected_reason,
                    error, applied_ref, source_conversation_id, source_message_id,
                    agent_run_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_hash) DO NOTHING
                """,
                (
                    proposal_id,
                    proposal_hash,
                    proposal_kind,
                    action_type,
                    target_ref,
                    content,
                    confidence,
                    1 if reversible else 0,
                    status,
                    error,
                    source_conversation_id,
                    source_message_id,
                    agent_run_id,
                    now,
                    now,
                ),
            )
        return self._map(self._row_by_hash(proposal_hash))

    def list_proposals(
        self,
        *,
        statuses: Sequence[str] | None = None,
        limit: int = 50,
    ) -> list[ReflectionProposalRecord]:
        clause = ""
        params: list[object] = []
        if statuses is not None:
            placeholders = ", ".join("?" for _ in statuses)
            clause = f"WHERE status IN ({placeholders})"
            params.extend(statuses)
        rows = self.conn.execute(
            f"""
            SELECT * FROM reflection_proposals
            {clause}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (*params, max(1, min(limit, 200))),
        ).fetchall()
        return [self._map(row) for row in rows]

    def get(self, proposal_id: str) -> ReflectionProposalRecord:
        row = self._row(proposal_id)
        if row is None:
            raise ReflectionProposalNotFoundError(proposal_id)
        return self._map(row)

    def reject(self, proposal_id: str, reason: str) -> ReflectionProposalRecord:
        return self._transition(
            proposal_id,
            from_statuses=(PENDING,),
            status=REJECTED,
            rejected_reason=" ".join(reason.split())[:500] or "user_rejected",
        )

    def mark_applied(self, proposal_id: str, *, applied_ref: str) -> ReflectionProposalRecord:
        return self._transition(
            proposal_id,
            from_statuses=(PENDING, APPLYING),
            status=APPLIED,
            applied_ref=applied_ref,
        )

    def mark_failed(self, proposal_id: str, *, error: str) -> ReflectionProposalRecord:
        return self._transition(
            proposal_id,
            from_statuses=(PENDING, APPLYING),
            status=FAILED,
            error=" ".join(error.split())[:500],
        )

    def claim_for_apply(self, proposal_id: str, *, lease_seconds: int = 900) -> ReflectionProposalRecord:
        """Atomically reserve a pending proposal before any external effect.

        The reservation closes the confirm/reject race: exactly one caller can
        move ``pending`` to ``applying``.  A process crash can leave that state
        behind, so old leases are returned to ``pending`` before claiming.  The
        actual action is idempotent in the action ledger and can therefore be
        safely retried after recovery.

        A proposal whose apply attempt failed can be claimed again while it has
        budget left; the claim also bumps ``apply_attempts``, which is the
        attempt identity the caller must carry into the action ledger — the
        ledger replays a stored failure under its original key, so a retry that
        kept the key would be a button that does nothing.
        """
        self.recover_stale_applying(lease_seconds=lease_seconds)
        current = self.get(proposal_id)
        attempt = _claimable_attempt(current)
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE reflection_proposals
                SET status = ?, apply_attempts = ?, updated_at = ?
                WHERE id = ? AND status = ? AND apply_attempts = ?
                """,
                (
                    APPLYING,
                    attempt,
                    utc_now_iso(),
                    proposal_id,
                    current.status,
                    current.apply_attempts,
                ),
            )
            if cursor.rowcount != 1:
                observed = self._row(proposal_id)
                if observed is None:
                    raise ReflectionProposalNotFoundError(proposal_id)
                raise ReflectionProposalStateError(f"proposal {proposal_id} is {observed['status']}")
        return self.get(proposal_id)

    def recover_stale_applying(self, *, lease_seconds: int = 900) -> int:
        """Return abandoned ``applying`` rows to ``pending`` for retry."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, lease_seconds))
        recovered = 0
        rows = self.conn.execute(
            "SELECT id, updated_at FROM reflection_proposals WHERE status = ?",
            (APPLYING,),
        ).fetchall()
        for row in rows:
            try:
                updated_at = coerce_datetime(str(row["updated_at"]))
            except (TypeError, ValueError, OverflowError):
                updated_at = cutoff - timedelta(seconds=1)
            if updated_at >= cutoff:
                continue
            with self.conn:
                cursor = self.conn.execute(
                    """
                    UPDATE reflection_proposals
                    SET status = ?, error = NULL, updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (PENDING, utc_now_iso(), str(row["id"]), APPLYING),
                )
            recovered += int(cursor.rowcount == 1)
        return recovered

    def _transition(
        self,
        proposal_id: str,
        *,
        from_statuses: tuple[str, ...],
        status: str,
        rejected_reason: str | None = None,
        applied_ref: str | None = None,
        error: str | None = None,
    ) -> ReflectionProposalRecord:
        current = self.get(proposal_id)
        if current.status == status:
            # Idempotent repeat: the caller asked for a state the row is in.
            return current
        if current.status not in from_statuses:
            raise ReflectionProposalStateError(f"proposal {proposal_id} is {current.status}")
        with self.conn:
            placeholders = ", ".join("?" for _ in from_statuses)
            cursor = self.conn.execute(
                """
                UPDATE reflection_proposals
                SET status = ?,
                    rejected_reason = COALESCE(?, rejected_reason),
                    applied_ref = COALESCE(?, applied_ref),
                    error = COALESCE(?, error),
                    updated_at = ?
                WHERE id = ? AND status IN (""" + placeholders + ")",
                (status, rejected_reason, applied_ref, error, utc_now_iso(), proposal_id, *from_statuses),
            )
            if cursor.rowcount != 1:
                current = self._row(proposal_id)
                if current is None:
                    raise ReflectionProposalNotFoundError(proposal_id)
                if current["status"] == status:
                    return self._map(current)
                raise ReflectionProposalStateError(f"proposal {proposal_id} is {current['status']}")
        return self.get(proposal_id)

    def _row(self, proposal_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM reflection_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()

    def _row_by_hash(self, proposal_hash: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM reflection_proposals WHERE proposal_hash = ?",
            (proposal_hash,),
        ).fetchone()

    @staticmethod
    def _map(row: sqlite3.Row) -> ReflectionProposalRecord:
        return ReflectionProposalRecord(
            id=str(row["id"]),
            proposal_kind=str(row["proposal_kind"]),
            action_type=str(row["action_type"]),
            target_ref=str(row["target_ref"]) if row["target_ref"] is not None else None,
            content=str(row["content"]),
            confidence=float(row["confidence"]),
            reversible=bool(row["reversible"]),
            status=str(row["status"]),
            rejected_reason=str(row["rejected_reason"]) if row["rejected_reason"] is not None else None,
            error=str(row["error"]) if row["error"] is not None else None,
            applied_ref=str(row["applied_ref"]) if row["applied_ref"] is not None else None,
            apply_attempts=int(row["apply_attempts"]),
            source_conversation_id=(
                str(row["source_conversation_id"]) if row["source_conversation_id"] is not None else None
            ),
            source_message_id=str(row["source_message_id"]) if row["source_message_id"] is not None else None,
            agent_run_id=str(row["agent_run_id"]) if row["agent_run_id"] is not None else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _claimable_attempt(record: ReflectionProposalRecord) -> int:
    """Return the attempt number this claim should record, or refuse to claim."""
    if record.status == FAILED:
        if record.proposal_kind in NON_RETRYABLE_APPLY_KINDS:
            raise ReflectionProposalStateError(
                f"proposal {record.id} has no retryable apply for {record.proposal_kind}"
            )
        if record.apply_attempts >= MAX_APPLY_ATTEMPTS:
            raise ReflectionProposalStateError(
                f"proposal {record.id} exhausted {record.apply_attempts} apply attempts"
            )
        return record.apply_attempts + 1
    if record.status != PENDING:
        raise ReflectionProposalStateError(f"proposal {record.id} is {record.status}")
    return record.apply_attempts + 1
