from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from app.models.common import new_id
from app.models.enums import MemoryFactStatus
from app.services.memory_taxonomy import LOW_CONFIDENCE_THRESHOLD, LifecycleStatus
from app.storage.database import open_database_connection
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


@contextmanager
def _sqlite_write_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        # 见 memory_entity_graph.atomic:WAL 下 deferred 事务先读后写会被并发提交
        # 变成立即失败的快照冲突,写事务要一开始就拿写锁。
        conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if owns_transaction:
            conn.rollback()
        raise
    else:
        if owns_transaction:
            conn.commit()


@dataclass(frozen=True)
class MemoryFactCandidate:
    category: str
    subject: str
    predicate: str
    object: str
    source_text: str
    source_type: str = "user_message"
    confidence: float = 0.75
    conversation_id: str | None = None
    user_message_id: str | None = None
    agent_run_id: str | None = None
    memory_type: str | None = None
    entity_type: str | None = None
    occurred_at: str | None = None
    expires_at: str | None = None
    metadata_json: str | None = None
    importance: float = 0.5
    subject_identity_key: str | None = None
    object_identity_key: str | None = None


@dataclass(frozen=True)
class MemoryGraphFact:
    id: str
    fact_key: str
    conflict_key: str
    category: str
    subject: str
    predicate: str
    object: str
    status: MemoryFactStatus
    confidence: float
    source_text: str
    source_type: str
    conversation_id: str | None
    user_message_id: str | None
    agent_run_id: str | None
    support_count: int
    conflicts_with: str | None
    created_at: str
    updated_at: str
    memory_type: str | None = None
    entity_type: str | None = None
    occurred_at: str | None = None
    expires_at: str | None = None
    metadata_json: str = "{}"
    importance: float = 0.5
    superseded_by: str | None = None
    statement_kind: str | None = None
    subject_entity_id: str | None = None
    subject_fact_id: str | None = None
    object_entity_id: str | None = None
    object_fact_id: str | None = None
    relation_type: str | None = None


@dataclass(frozen=True)
class MemoryGraphWriteResult:
    fact: MemoryGraphFact
    inserted: bool
    reason: str | None = None


class MemoryGraphStore:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
    ):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def upsert_candidate(
        self,
        candidate: MemoryFactCandidate,
        *,
        detect_conflict: bool = True,
    ) -> MemoryGraphWriteResult:
        fact_key = _candidate_fact_key(candidate)
        conflict_key = _candidate_conflict_key(candidate)
        existing = self._get_by_fact_key(fact_key)
        if existing is not None:
            updated = self.record_support(existing.id)
            return MemoryGraphWriteResult(fact=updated, inserted=False, reason="already_recorded")

        conflict = self._find_active_conflict(conflict_key, candidate.object) if detect_conflict else None
        status = MemoryFactStatus.ACTIVE if conflict is None and candidate.confidence >= LOW_CONFIDENCE_THRESHOLD else MemoryFactStatus.QUARANTINED
        reason = None
        if conflict is not None:
            status = MemoryFactStatus.QUARANTINED
            reason = "conflict_detected"
        elif candidate.confidence < LOW_CONFIDENCE_THRESHOLD:
            reason = "low_confidence"

        now = utc_now_iso()
        fact_id = new_id()
        metadata_json = _normalize_metadata_json(candidate.metadata_json)
        importance = _normalize_importance(candidate.importance)
        with _sqlite_write_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO memory_graph_facts (
                    id, fact_key, conflict_key, category, subject, predicate, object,
                    status, confidence, source_text, source_type, conversation_id,
                    user_message_id, agent_run_id, memory_type, entity_type,
                    occurred_at, expires_at, metadata_json, importance, support_count,
                    conflicts_with, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    fact_id,
                    fact_key,
                    conflict_key,
                    candidate.category,
                    candidate.subject,
                    candidate.predicate,
                    candidate.object,
                    status.value,
                    candidate.confidence,
                    candidate.source_text,
                    candidate.source_type,
                    candidate.conversation_id,
                    candidate.user_message_id,
                    candidate.agent_run_id,
                    candidate.memory_type,
                    candidate.entity_type,
                    candidate.occurred_at,
                    candidate.expires_at,
                    metadata_json,
                    importance,
                    None,
                    now,
                    now,
                ),
            )
            self._record_event(fact_id, "create", reason)
        fact = self.get(fact_id)
        return MemoryGraphWriteResult(fact=fact, inserted=True, reason=reason)

    def insert_candidate(self, candidate: MemoryFactCandidate, *, reason: str = "candidate_review_required") -> MemoryGraphWriteResult:
        fact_key = _candidate_fact_key(candidate)
        existing = self._get_by_fact_key(fact_key)
        if existing is not None:
            return MemoryGraphWriteResult(fact=existing, inserted=False, reason="already_recorded")

        now = utc_now_iso()
        fact_id = new_id()
        metadata_json = _normalize_metadata_json(candidate.metadata_json)
        importance = _normalize_importance(candidate.importance)
        with _sqlite_write_transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO memory_graph_facts (
                    id, fact_key, conflict_key, category, subject, predicate, object,
                    status, confidence, source_text, source_type, conversation_id,
                    user_message_id, agent_run_id, memory_type, entity_type,
                    occurred_at, expires_at, metadata_json, importance, support_count,
                    conflicts_with, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    fact_id,
                    fact_key,
                    _candidate_conflict_key(candidate),
                    candidate.category,
                    candidate.subject,
                    candidate.predicate,
                    candidate.object,
                    MemoryFactStatus.CANDIDATE.value,
                    candidate.confidence,
                    candidate.source_text,
                    candidate.source_type,
                    candidate.conversation_id,
                    candidate.user_message_id,
                    candidate.agent_run_id,
                    candidate.memory_type,
                    candidate.entity_type,
                    candidate.occurred_at,
                    candidate.expires_at,
                    metadata_json,
                    importance,
                    None,
                    now,
                    now,
                ),
            )
            self._record_event(fact_id, "create", reason)
        fact = self.get(fact_id)
        return MemoryGraphWriteResult(fact=fact, inserted=True, reason=reason)

    def list_facts(
        self,
        *,
        status: MemoryFactStatus | str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> list[MemoryGraphFact]:
        clauses = []
        params: list[object] = []
        if status is not None:
            normalized = MemoryFactStatus(status)
            clauses.append("status = ?")
            params.append(normalized.value)
        if query:
            clauses.append(
                """
                (
                    subject LIKE ? ESCAPE '~'
                    OR predicate LIKE ? ESCAPE '~'
                    OR object LIKE ? ESCAPE '~'
                    OR source_text LIKE ? ESCAPE '~'
                    OR memory_type LIKE ? ESCAPE '~'
                    OR entity_type LIKE ? ESCAPE '~'
                    OR occurred_at LIKE ? ESCAPE '~'
                    OR expires_at LIKE ? ESCAPE '~'
                    OR metadata_json LIKE ? ESCAPE '~'
                )
                """
            )
            pattern = _like_pattern(query)
            params.extend([pattern] * 9)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM memory_graph_facts
            {where}
            ORDER BY
                CASE status
                    WHEN 'active' THEN 0
                    WHEN 'candidate' THEN 1
                    WHEN 'stale' THEN 2
                    WHEN 'quarantined' THEN 3
                    ELSE 3
                END,
                importance DESC,
                updated_at DESC
            LIMIT ?
            """,
            (*params, max(1, min(limit, 200))),
        ).fetchall()
        return [self._map(row) for row in rows]

    def search_active(self, query: str, *, limit: int = 5) -> list[MemoryGraphFact]:
        return self.list_facts(status=MemoryFactStatus.ACTIVE, query=query, limit=limit)

    def get(self, fact_id: str) -> MemoryGraphFact:
        row = self.conn.execute("SELECT * FROM memory_graph_facts WHERE id = ?", (fact_id,)).fetchone()
        if row is None:
            raise KeyError(fact_id)
        return self._map(row)

    def update_status(
        self,
        fact_id: str,
        status: MemoryFactStatus | str,
        *,
        reason: str | None = None,
        lifecycle_metadata: Mapping[str, object] | None = None,
        superseded_by: str | None = None,
    ) -> MemoryGraphFact:
        normalized = MemoryFactStatus(status)
        existing = self.get(fact_id)
        with _sqlite_write_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE memory_graph_facts
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized.value, utc_now_iso(), fact_id),
            )
            self._record_event(fact_id, normalized.value, reason)
            self._record_lifecycle_event(
                fact_id=fact_id,
                from_status=_fact_status_to_lifecycle(existing.status),
                to_status=_fact_status_to_lifecycle(normalized),
                reason=reason,
                metadata=dict(lifecycle_metadata or {}),
            )
            if superseded_by:
                self._record_supersedes_relation(
                    replaced=existing,
                    replacement_id=superseded_by,
                    reason=reason,
                )
        fact = self.get(fact_id)
        return fact

    def _record_supersedes_relation(
        self,
        *,
        replaced: MemoryGraphFact,
        replacement_id: str,
        reason: str | None,
    ) -> None:
        """Persist a typed replacement edge for legacy graph-store callers.

        The entity graph service is the normal relation writer.  This small
        compatibility path keeps the lower-level store's lifecycle API
        authoritative when older callers provide ``superseded_by`` directly.
        """
        if not _has_authority_relations(self.conn):
            return
        replacement = self.get(replacement_id)
        now = utc_now_iso()
        self.conn.execute(
            """
            UPDATE memory_graph_facts
            SET status = 'archived', updated_at = ?
            WHERE statement_kind = 'relation'
              AND relation_type = 'supersedes'
              AND object_fact_id = ?
              AND status = 'active'
              AND subject_fact_id <> ?
            """,
            (now, replaced.id, replacement.id),
        )
        relation_id = new_id()
        source_text = reason or f"{replacement.subject} supersedes {replaced.subject}"
        relation_key = _hash_key("relation-v1", "supersedes", replacement.id, replaced.id)
        self.conn.execute(
            """
            INSERT OR IGNORE INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, conversation_id,
                user_message_id, agent_run_id, memory_type, entity_type,
                occurred_at, expires_at, metadata_json, importance, support_count,
                conflicts_with, created_at, updated_at, statement_kind,
                subject_fact_id, object_fact_id, relation_type
            )
            VALUES (?, ?, ?, 'relation', ?, 'supersedes', ?, 'active', 1.0, ?,
                    'lifecycle', NULL, NULL, NULL, 'relation', NULL, NULL, NULL,
                    '{}', 0.5, 1, NULL, ?, ?, 'relation', ?, ?, 'supersedes')
            """,
            (
                relation_id,
                relation_key,
                _hash_key("relation-conflict", "supersedes", replaced.id),
                replacement.subject,
                replaced.subject,
                source_text,
                now,
                now,
                replacement.id,
                replaced.id,
            ),
        )
        relation_row = self.conn.execute(
            "SELECT id FROM memory_graph_facts WHERE fact_key = ?",
            (relation_key,),
        ).fetchone()
        if relation_row is None:
            return
        evidence_id = "evidence-lifecycle-supersedes-" + sha256_hex(relation_key)[:32]
        self.conn.execute(
            """
            INSERT OR IGNORE INTO memory_evidence (
                id, fact_id, source_type, source_text_hash, source_excerpt,
                confidence, metadata_json, created_at
            ) VALUES (?, ?, 'lifecycle', ?, ?, 1.0, '{}', ?)
            """,
            (
                evidence_id,
                str(relation_row[0]),
                sha256_hex(source_text),
                source_text[:1000],
                now,
            ),
        )

    def _get_by_fact_key(self, fact_key: str) -> MemoryGraphFact | None:
        row = self.conn.execute("SELECT * FROM memory_graph_facts WHERE fact_key = ?", (fact_key,)).fetchone()
        return self._map(row) if row else None

    def _find_active_conflict(self, conflict_key: str, object_value: str) -> MemoryGraphFact | None:
        row = self.conn.execute(
            """
            SELECT *
            FROM memory_graph_facts
            WHERE conflict_key = ?
              AND status = ?
              AND lower(object) != lower(?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (conflict_key, MemoryFactStatus.ACTIVE.value, object_value),
        ).fetchone()
        return self._map(row) if row else None

    def record_support(self, fact_id: str) -> MemoryGraphFact:
        with _sqlite_write_transaction(self.conn):
            self.conn.execute(
                """
                UPDATE memory_graph_facts
                SET support_count = support_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (utc_now_iso(), fact_id),
            )
            self._record_event(fact_id, "support", "duplicate_fact")
        return self.get(fact_id)

    def _record_event(self, fact_id: str, action: str, reason: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO memory_graph_events (id, fact_id, action, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_id(), fact_id, action, reason, utc_now_iso()),
        )

    def _record_lifecycle_event(
        self,
        *,
        fact_id: str,
        from_status: LifecycleStatus | None,
        to_status: LifecycleStatus | None,
        reason: str | None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if to_status is None:
            return
        self.conn.execute(
            """
            INSERT INTO memory_lifecycle_events (
                id, fact_id, from_status, to_status, reason, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                fact_id,
                from_status.value if from_status is not None else None,
                to_status.value,
                reason or "",
                json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                utc_now_iso(),
            ),
        )

    def _map(self, row: sqlite3.Row) -> MemoryGraphFact:
        conflicts_with = self._contradiction_for(str(row["id"]))
        superseded_by = self._replacement_for(str(row["id"]))
        return MemoryGraphFact(
            id=row["id"],
            fact_key=row["fact_key"],
            conflict_key=row["conflict_key"],
            category=row["category"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            status=MemoryFactStatus(row["status"]),
            confidence=float(row["confidence"]),
            source_text=row["source_text"],
            source_type=row["source_type"],
            conversation_id=row["conversation_id"],
            user_message_id=row["user_message_id"],
            agent_run_id=row["agent_run_id"],
            support_count=int(row["support_count"]),
            conflicts_with=conflicts_with,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            memory_type=row["memory_type"],
            entity_type=row["entity_type"],
            occurred_at=row["occurred_at"],
            expires_at=row["expires_at"],
            metadata_json=row["metadata_json"] or "{}",
            importance=float(row["importance"]),
            superseded_by=superseded_by,
            statement_kind=row["statement_kind"] if "statement_kind" in row.keys() else None,
            subject_entity_id=row["subject_entity_id"] if "subject_entity_id" in row.keys() else None,
            subject_fact_id=row["subject_fact_id"] if "subject_fact_id" in row.keys() else None,
            object_entity_id=row["object_entity_id"] if "object_entity_id" in row.keys() else None,
            object_fact_id=row["object_fact_id"] if "object_fact_id" in row.keys() else None,
            relation_type=row["relation_type"] if "relation_type" in row.keys() else None,
        )

    def _replacement_for(self, fact_id: str) -> str | None:
        return authority_superseded_by(self.conn, fact_id)

    def _contradiction_for(self, fact_id: str) -> str | None:
        return authority_contradicted_by(self.conn, fact_id)


def facts_to_context_lines(facts: Iterable[MemoryGraphFact]) -> list[str]:
    return [
        f"{fact.subject} {fact.predicate} {fact.object} (confidence={fact.confidence:.2f}, support={fact.support_count})"
        for fact in facts
        if fact.status == MemoryFactStatus.ACTIVE
    ]


def _fact_key(subject: str, predicate: str, object_value: str) -> str:
    return _hash_key(subject, predicate, object_value)


def _conflict_key(subject: str, predicate: str) -> str:
    return _hash_key(subject, predicate)


def _candidate_fact_key(candidate: MemoryFactCandidate) -> str:
    if candidate.subject_identity_key is None and candidate.object_identity_key is None:
        return _fact_key(candidate.subject, candidate.predicate, candidate.object)
    subject = _typed_key_part("subject", candidate.subject_identity_key, candidate.subject)
    object_value = _typed_key_part("object", candidate.object_identity_key, candidate.object)
    return _hash_key("typed-v1", subject, candidate.predicate, object_value)


def _candidate_conflict_key(candidate: MemoryFactCandidate) -> str:
    if candidate.subject_identity_key is None:
        return _conflict_key(candidate.subject, candidate.predicate)
    subject = _typed_key_part("subject", candidate.subject_identity_key, candidate.subject)
    return _hash_key("typed-v1", subject, candidate.predicate)


def _typed_key_part(kind: str, identity: str | None, value: str) -> str:
    return f"{kind}:identity:{identity}" if identity is not None else f"{kind}:literal:{value}"


def _hash_key(*parts: str) -> str:
    normalized = "\n".join(part.casefold().strip() for part in parts)
    return sha256_hex(normalized)


def _like_pattern(query: str) -> str:
    escaped = query.replace("~", "~~").replace("%", "~%").replace("_", "~_")
    return f"%{escaped}%"


def _normalize_metadata_json(value: str | None) -> str:
    if not value:
        return "{}"
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return "{}"
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _has_authority_relations(conn: sqlite3.Connection) -> bool:
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(memory_graph_facts)").fetchall()
    }
    return {
        "statement_kind",
        "relation_type",
        "subject_fact_id",
        "object_fact_id",
    }.issubset(columns)


def authority_superseded_by(conn: sqlite3.Connection, fact_id: str) -> str | None:
    """Read the current replacement only from the typed authority relation."""
    if not _has_authority_relations(conn):
        return None
    row = conn.execute(
        """
        SELECT subject_fact_id
        FROM memory_graph_facts
        WHERE statement_kind = 'relation'
          AND relation_type = 'supersedes'
          AND object_fact_id = ?
          AND status = 'active'
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (fact_id,),
    ).fetchone()
    return str(row[0]) if row is not None and row[0] else None


def authority_contradicted_by(conn: sqlite3.Connection, fact_id: str) -> str | None:
    """Read the current contradiction only from the typed authority relation."""
    if not _has_authority_relations(conn):
        return None
    row = conn.execute(
        """
        SELECT CASE WHEN subject_fact_id = ? THEN object_fact_id ELSE subject_fact_id END
        FROM memory_graph_facts
        WHERE statement_kind = 'relation'
          AND relation_type = 'contradicts'
          AND status = 'active'
          AND (subject_fact_id = ? OR object_fact_id = ?)
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (fact_id, fact_id, fact_id),
    ).fetchone()
    return str(row[0]) if row is not None and row[0] else None


def _fact_status_to_lifecycle(status: MemoryFactStatus) -> LifecycleStatus | None:
    if status is MemoryFactStatus.QUARANTINED:
        return LifecycleStatus.CANDIDATE
    if status in {MemoryFactStatus.WRONG, MemoryFactStatus.SENSITIVE_BLOCKED}:
        return LifecycleStatus.REJECTED
    try:
        return LifecycleStatus(status.value)
    except ValueError:
        return None


def _normalize_importance(value: float | None) -> float:
    if value is None:
        return 0.5
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, normalized))
