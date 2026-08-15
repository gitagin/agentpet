from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.models.common import new_id
from app.services.memory_taxonomy import (
    LifecycleStatus,
    MemoryKind,
    MemoryScope,
    RecallPermissions,
    RiskTier,
    SourceTrack,
)
from app.storage.database import open_database_connection
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


CANDIDATE_SOURCE_TYPE_PREFIX = "candidate_source:"


@dataclass(frozen=True, slots=True)
class MemoryCandidateCreate:
    memory_kind: MemoryKind | str
    memory_scope: MemoryScope | str
    summary: str
    normalized_value: str = ""
    source_text: str = ""
    source_track: SourceTrack | str = SourceTrack.SLOW_CONSOLIDATION
    risk_tier: RiskTier | str = RiskTier.LOW
    confidence: float = 0.5
    importance: float = 0.5
    status: LifecycleStatus | str = LifecycleStatus.CANDIDATE
    expires_at: str | None = None
    last_confirmed_at: str | None = None
    superseded_by: str | None = None
    fact_id: str | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class MemoryCandidateRecord:
    id: str
    candidate_hash: str
    memory_kind: MemoryKind
    memory_scope: MemoryScope
    summary: str
    normalized_value: str
    source_text_hash: str
    source_track: SourceTrack
    risk_tier: RiskTier
    confidence: float
    importance: float
    evidence_count: int
    status: LifecycleStatus
    expires_at: str | None
    last_confirmed_at: str | None
    superseded_by: str | None
    fact_id: str | None
    metadata: dict[str, object]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class MemoryEvidenceCreate:
    candidate_id: str | None = None
    fact_id: str | None = None
    source_type: str = "chat_message"
    source_text: str = ""
    source_excerpt: str = ""
    conversation_id: str | None = None
    message_id: str | None = None
    agent_run_id: str | None = None
    diary_object_id: str | None = None
    confidence: float = 0.5
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class MemoryEvidenceRecord:
    id: str
    evidence_key: str
    candidate_id: str | None
    fact_id: str | None
    source_type: str
    source_text_hash: str
    source_excerpt: str
    conversation_id: str | None
    message_id: str | None
    agent_run_id: str | None
    diary_object_id: str | None
    confidence: float
    metadata: dict[str, object]
    created_at: str


@dataclass(frozen=True, slots=True)
class MemoryLifecycleEventRecord:
    id: str
    candidate_id: str | None
    fact_id: str | None
    from_status: LifecycleStatus | None
    to_status: LifecycleStatus
    reason: str
    source_agent_run_id: str | None
    source_message_id: str | None
    agent_action_id: str | None
    metadata: dict[str, object]
    created_at: str


@dataclass(frozen=True, slots=True)
class MemoryActivationEventCreate:
    candidate_id: str | None = None
    fact_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    agent_run_id: str | None = None
    activation_score: float = 0.0
    permissions: RecallPermissions | Mapping[str, object] | None = None
    score_breakdown: Mapping[str, object] | None = None
    used_for_style: bool = False
    used_for_answer_context: bool = False
    used_for_proactive_mention: bool = False
    used_for_action_suggestion: bool = False
    filtered_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryFeedbackEventCreate:
    candidate_id: str | None = None
    fact_id: str | None = None
    feedback_type: str = "correction"
    feedback_text: str = ""
    requested_status: LifecycleStatus | str | None = None
    replacement_candidate_id: str | None = None
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    source_agent_run_id: str | None = None
    agent_action_id: str | None = None
    metadata: Mapping[str, object] | None = None


class MemoryCandidateStore:
    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def create_candidate(self, request: MemoryCandidateCreate) -> MemoryCandidateRecord:
        kind = MemoryKind(request.memory_kind)
        scope = MemoryScope(request.memory_scope)
        track = SourceTrack(request.source_track)
        risk = RiskTier(request.risk_tier)
        status = LifecycleStatus(request.status)
        source_text_hash = sha256_hex(request.source_text)
        candidate_hash = _candidate_hash(
            kind=kind,
            scope=scope,
            summary=request.summary,
            normalized_value=request.normalized_value,
            source_track=track,
            source_text_hash=source_text_hash,
        )
        now = utc_now_iso()
        candidate_id = new_id()
        metadata_json = _json_object(request.metadata)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO memory_candidates (
                    id, candidate_hash, memory_kind, memory_scope, summary,
                    normalized_value, source_text, source_text_hash, source_track,
                    risk_tier, confidence, importance, evidence_count, status,
                    expires_at, last_confirmed_at, superseded_by, fact_id,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_hash) DO UPDATE SET
                    confidence = MAX(confidence, excluded.confidence),
                    importance = MAX(importance, excluded.importance),
                    updated_at = excluded.updated_at
                """,
                (
                    candidate_id,
                    candidate_hash,
                    kind.value,
                    scope.value,
                    _compact(request.summary, 1000),
                    _compact(request.normalized_value, 1000),
                    _compact(request.source_text, 2000),
                    source_text_hash,
                    track.value,
                    risk.value,
                    _clamp(request.confidence),
                    _clamp(request.importance),
                    status.value,
                    request.expires_at,
                    request.last_confirmed_at,
                    request.superseded_by,
                    request.fact_id,
                    metadata_json,
                    now,
                    now,
                ),
            )
            row = self.conn.execute(
                "SELECT id FROM memory_candidates WHERE candidate_hash = ?",
                (candidate_hash,),
            ).fetchone()
            if row is None:
                raise RuntimeError("candidate_insert_missing")
            stored_candidate_id = str(row["id"])
            if request.source_text.strip():
                self._insert_evidence(
                    MemoryEvidenceCreate(
                        candidate_id=stored_candidate_id,
                        source_type=f"{CANDIDATE_SOURCE_TYPE_PREFIX}{track.value}",
                        source_text=request.source_text,
                        source_excerpt=request.source_text,
                        confidence=request.confidence,
                        metadata={"source_track": track.value},
                    ),
                    created_at=now,
                )
            self._recount_candidate(stored_candidate_id, updated_at=now)
        return self.get_candidate_by_hash(candidate_hash)

    def get_candidate(self, candidate_id: str) -> MemoryCandidateRecord:
        row = self.conn.execute(
            "SELECT * FROM memory_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return _candidate_record(row)

    def get_candidate_by_hash(self, candidate_hash: str) -> MemoryCandidateRecord:
        row = self.conn.execute(
            "SELECT * FROM memory_candidates WHERE candidate_hash = ?",
            (candidate_hash,),
        ).fetchone()
        if row is None:
            raise KeyError(candidate_hash)
        return _candidate_record(row)

    def attach_fact(self, candidate_id: str, fact_id: str) -> MemoryCandidateRecord:
        """Bind a candidate and its existing evidence to the authoritative fact."""
        self.get_candidate(candidate_id)
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                UPDATE memory_candidates
                SET fact_id = COALESCE(fact_id, ?), updated_at = ?
                WHERE id = ?
                """,
                (fact_id, now, candidate_id),
            )
            self.conn.execute(
                """
                UPDATE memory_evidence
                SET fact_id = COALESCE(fact_id, ?)
                WHERE candidate_id = ? AND fact_id IS NULL
                """,
                (fact_id, candidate_id),
            )
        return self.get_candidate(candidate_id)

    def list_candidates(
        self,
        *,
        status: LifecycleStatus | str | None = None,
        memory_kind: MemoryKind | str | None = None,
        limit: int = 50,
    ) -> list[MemoryCandidateRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(LifecycleStatus(status).value)
        if memory_kind is not None:
            clauses.append("memory_kind = ?")
            params.append(MemoryKind(memory_kind).value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM memory_candidates
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (*params, max(1, min(limit, 200))),
        ).fetchall()
        return [_candidate_record(row) for row in rows]

    def add_evidence(self, request: MemoryEvidenceCreate) -> MemoryEvidenceRecord:
        if request.candidate_id is None and request.fact_id is None:
            raise ValueError("candidate_id_or_fact_id_required")
        created_at = utc_now_iso()
        with self.conn:
            evidence_key = self._insert_evidence(request, created_at=created_at)
            if request.candidate_id is not None:
                self._recount_candidate(request.candidate_id, updated_at=created_at)
        return self.get_evidence_by_key(evidence_key)

    def _insert_evidence(self, request: MemoryEvidenceCreate, *, created_at: str) -> str:
        source_text_hash = sha256_hex(request.source_text)
        evidence_key = _evidence_key(request, source_text_hash=source_text_hash)
        self.conn.execute(
            """
            INSERT OR IGNORE INTO memory_evidence (
                id, evidence_key, candidate_id, fact_id, source_type, source_text_hash,
                source_excerpt, conversation_id, message_id, agent_run_id,
                diary_object_id, confidence, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"evidence-{evidence_key}",
                evidence_key,
                request.candidate_id,
                request.fact_id,
                _compact(request.source_type, 80),
                source_text_hash,
                _compact(request.source_excerpt or request.source_text, 500),
                request.conversation_id,
                request.message_id,
                request.agent_run_id,
                request.diary_object_id,
                _clamp(request.confidence),
                _json_object(request.metadata),
                created_at,
            ),
        )
        return evidence_key

    def _recount_candidate(self, candidate_id: str, *, updated_at: str) -> None:
        self.conn.execute(
            """
            UPDATE memory_candidates
            SET evidence_count = (
                    SELECT COUNT(*)
                    FROM memory_evidence
                    WHERE candidate_id = ?
                ),
                updated_at = ?
            WHERE id = ?
            """,
            (candidate_id, updated_at, candidate_id),
        )

    def get_evidence(self, evidence_id: str) -> MemoryEvidenceRecord:
        row = self.conn.execute(
            "SELECT * FROM memory_evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        if row is None:
            raise KeyError(evidence_id)
        return _evidence_record(row)

    def get_evidence_by_key(self, evidence_key: str) -> MemoryEvidenceRecord:
        row = self.conn.execute(
            "SELECT * FROM memory_evidence WHERE evidence_key = ?",
            (evidence_key,),
        ).fetchone()
        if row is None:
            raise KeyError(evidence_key)
        return _evidence_record(row)

    def transition(
        self,
        *,
        candidate_id: str | None = None,
        fact_id: str | None = None,
        to_status: LifecycleStatus | str,
        reason: str = "",
        source_agent_run_id: str | None = None,
        source_message_id: str | None = None,
        agent_action_id: str | None = None,
        superseded_by: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryLifecycleEventRecord:
        if candidate_id is None and fact_id is None:
            raise ValueError("candidate_id_or_fact_id_required")
        target_status = LifecycleStatus(to_status)
        from_status: str | None = None
        now = utc_now_iso()
        if candidate_id is not None:
            candidate = self.get_candidate(candidate_id)
            from_status = candidate.status.value
        event_id = new_id()
        with self.conn:
            if candidate_id is not None:
                self.conn.execute(
                    """
                    UPDATE memory_candidates
                    SET status = ?,
                        superseded_by = COALESCE(?, superseded_by),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (target_status.value, superseded_by, now, candidate_id),
                )
            self.conn.execute(
                """
                INSERT INTO memory_lifecycle_events (
                    id, candidate_id, fact_id, from_status, to_status, reason,
                    source_agent_run_id, source_message_id, agent_action_id,
                    metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    candidate_id,
                    fact_id,
                    from_status,
                    target_status.value,
                    _compact(reason, 500),
                    source_agent_run_id,
                    source_message_id,
                    agent_action_id,
                    _json_object(metadata),
                    now,
                ),
            )
        return self.get_lifecycle_event(event_id)

    def get_lifecycle_event(self, event_id: str) -> MemoryLifecycleEventRecord:
        row = self.conn.execute(
            "SELECT * FROM memory_lifecycle_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return _lifecycle_event_record(row)

    def record_activation(self, request: MemoryActivationEventCreate) -> str:
        event_id = new_id()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO memory_activation_events (
                    id, candidate_id, fact_id, conversation_id, message_id,
                    agent_run_id, activation_score, permissions_json,
                    score_breakdown_json, used_for_style, used_for_answer_context,
                    used_for_proactive_mention, used_for_action_suggestion,
                    filtered_reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    request.candidate_id,
                    request.fact_id,
                    request.conversation_id,
                    request.message_id,
                    request.agent_run_id,
                    _clamp(request.activation_score),
                    _permissions_json(request.permissions),
                    _json_object(request.score_breakdown),
                    int(request.used_for_style),
                    int(request.used_for_answer_context),
                    int(request.used_for_proactive_mention),
                    int(request.used_for_action_suggestion),
                    request.filtered_reason,
                    utc_now_iso(),
                ),
            )
        return event_id

    def record_feedback(self, request: MemoryFeedbackEventCreate) -> str:
        if request.candidate_id is None and request.fact_id is None:
            raise ValueError("candidate_id_or_fact_id_required")
        requested_status = LifecycleStatus(request.requested_status).value if request.requested_status else None
        event_id = new_id()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO memory_feedback_events (
                    id, candidate_id, fact_id, feedback_type, feedback_text,
                    requested_status, replacement_candidate_id,
                    source_conversation_id, source_message_id, source_agent_run_id,
                    agent_action_id, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    request.candidate_id,
                    request.fact_id,
                    request.feedback_type,
                    _compact(request.feedback_text, 1000),
                    requested_status,
                    request.replacement_candidate_id,
                    request.source_conversation_id,
                    request.source_message_id,
                    request.source_agent_run_id,
                    request.agent_action_id,
                    _json_object(request.metadata),
                    utc_now_iso(),
                ),
            )
        return event_id


def _candidate_record(row: sqlite3.Row) -> MemoryCandidateRecord:
    return MemoryCandidateRecord(
        id=str(row["id"]),
        candidate_hash=str(row["candidate_hash"]),
        memory_kind=MemoryKind(row["memory_kind"]),
        memory_scope=MemoryScope(row["memory_scope"]),
        summary=str(row["summary"]),
        normalized_value=str(row["normalized_value"]),
        source_text_hash=str(row["source_text_hash"]),
        source_track=SourceTrack(row["source_track"]),
        risk_tier=RiskTier(row["risk_tier"]),
        confidence=float(row["confidence"]),
        importance=float(row["importance"]),
        evidence_count=int(row["evidence_count"]),
        status=LifecycleStatus(row["status"]),
        expires_at=row["expires_at"],
        last_confirmed_at=row["last_confirmed_at"],
        superseded_by=row["superseded_by"],
        fact_id=row["fact_id"],
        metadata=_json_load(row["metadata_json"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _evidence_record(row: sqlite3.Row) -> MemoryEvidenceRecord:
    return MemoryEvidenceRecord(
        id=str(row["id"]),
        evidence_key=str(row["evidence_key"]),
        candidate_id=row["candidate_id"],
        fact_id=row["fact_id"],
        source_type=str(row["source_type"]),
        source_text_hash=str(row["source_text_hash"]),
        source_excerpt=str(row["source_excerpt"]),
        conversation_id=row["conversation_id"],
        message_id=row["message_id"],
        agent_run_id=row["agent_run_id"],
        diary_object_id=row["diary_object_id"],
        confidence=float(row["confidence"]),
        metadata=_json_load(row["metadata_json"]),
        created_at=str(row["created_at"]),
    )


def _lifecycle_event_record(row: sqlite3.Row) -> MemoryLifecycleEventRecord:
    return MemoryLifecycleEventRecord(
        id=str(row["id"]),
        candidate_id=row["candidate_id"],
        fact_id=row["fact_id"],
        from_status=LifecycleStatus(row["from_status"]) if row["from_status"] else None,
        to_status=LifecycleStatus(row["to_status"]),
        reason=str(row["reason"]),
        source_agent_run_id=row["source_agent_run_id"],
        source_message_id=row["source_message_id"],
        agent_action_id=row["agent_action_id"],
        metadata=_json_load(row["metadata_json"]),
        created_at=str(row["created_at"]),
    )


def _candidate_hash(
    *,
    kind: MemoryKind,
    scope: MemoryScope,
    summary: str,
    normalized_value: str,
    source_track: SourceTrack,
    source_text_hash: str,
) -> str:
    return sha256_hex(
        "\n".join(
            [
                kind.value,
                scope.value,
                _compact(summary.casefold(), 1000),
                _compact(normalized_value.casefold(), 1000),
                source_track.value,
                source_text_hash,
            ]
        )
    )


def _evidence_key(request: MemoryEvidenceCreate, *, source_text_hash: str) -> str:
    return sha256_hex(
        json.dumps(
            {
                "candidate_id": request.candidate_id,
                "fact_id": request.fact_id,
                "source_type": _compact(request.source_type, 80),
                "source_text_hash": source_text_hash,
                "conversation_id": request.conversation_id,
                "message_id": request.message_id,
                "agent_run_id": request.agent_run_id,
                "diary_object_id": request.diary_object_id,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _permissions_json(value: RecallPermissions | Mapping[str, object] | None) -> str:
    if isinstance(value, RecallPermissions):
        return _json_object(
            {
                "can_style_response": value.can_style_response,
                "can_answer_context": value.can_answer_context,
                "can_proactively_mention": value.can_proactively_mention,
                "can_suggest_action": value.can_suggest_action,
                "can_persist": value.can_persist,
            }
        )
    return _json_object(value)


def _json_object(value: Mapping[str, object] | None) -> str:
    return json.dumps(dict(value or {}), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_load(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _compact(value: str, limit: int) -> str:
    compacted = " ".join(str(value).split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(0, limit - 3)].rstrip() + "..."
