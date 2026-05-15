from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.models.common import new_id
from app.models.enums import MemoryFactStatus
from app.services.memory import utc_now_iso


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


@dataclass(frozen=True)
class MemoryGraphWriteResult:
    fact: MemoryGraphFact
    inserted: bool
    reason: str | None = None


class MemoryGraphStore:
    def __init__(self, db: str | Path | sqlite3.Connection, *, graph_root: str | Path | None = None):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.graph_root = Path(graph_root) if graph_root else None
        self._ensure_schema()
        self._kuzu = _KuzuMirror(self.graph_root) if self.graph_root is not None else None

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_graph_facts (
                id TEXT PRIMARY KEY,
                fact_key TEXT NOT NULL UNIQUE,
                conflict_key TEXT NOT NULL,
                category TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_text TEXT NOT NULL,
                source_type TEXT NOT NULL,
                conversation_id TEXT,
                user_message_id TEXT,
                agent_run_id TEXT,
                memory_type TEXT,
                entity_type TEXT,
                occurred_at TEXT,
                expires_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                importance REAL NOT NULL DEFAULT 0.5,
                support_count INTEGER NOT NULL DEFAULT 1,
                conflicts_with TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._ensure_fact_columns(
            {
                "memory_type": "TEXT",
                "entity_type": "TEXT",
                "occurred_at": "TEXT",
                "expires_at": "TEXT",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                "importance": "REAL NOT NULL DEFAULT 0.5",
            }
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_graph_facts_status
            ON memory_graph_facts(status, updated_at)
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_graph_facts_conflict
            ON memory_graph_facts(conflict_key, status)
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_graph_events (
                id TEXT PRIMARY KEY,
                fact_id TEXT NOT NULL REFERENCES memory_graph_facts(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def upsert_candidate(self, candidate: MemoryFactCandidate) -> MemoryGraphWriteResult:
        fact_key = _fact_key(candidate.subject, candidate.predicate, candidate.object)
        conflict_key = _conflict_key(candidate.subject, candidate.predicate)
        existing = self._get_by_fact_key(fact_key)
        if existing is not None:
            updated = self._increment_support(existing.id)
            return MemoryGraphWriteResult(fact=updated, inserted=False, reason="already_recorded")

        conflict = self._find_active_conflict(conflict_key, candidate.object)
        status = MemoryFactStatus.ACTIVE if conflict is None and candidate.confidence >= 0.65 else MemoryFactStatus.QUARANTINED
        reason = None
        conflicts_with = None
        if conflict is not None:
            status = MemoryFactStatus.QUARANTINED
            reason = "conflict_detected"
            conflicts_with = conflict.id
        elif candidate.confidence < 0.65:
            reason = "low_confidence"

        now = utc_now_iso()
        fact_id = new_id()
        metadata_json = _normalize_metadata_json(candidate.metadata_json)
        importance = _normalize_importance(candidate.importance)
        with self.conn:
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
                    conflicts_with,
                    now,
                    now,
                ),
            )
            self._record_event(fact_id, "create", reason)
        fact = self.get(fact_id)
        self._mirror_fact(fact)
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
                    WHEN 'quarantined' THEN 2
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

    def update_status(self, fact_id: str, status: MemoryFactStatus | str, *, reason: str | None = None) -> MemoryGraphFact:
        normalized = MemoryFactStatus(status)
        with self.conn:
            self.conn.execute(
                "UPDATE memory_graph_facts SET status = ?, updated_at = ? WHERE id = ?",
                (normalized.value, utc_now_iso(), fact_id),
            )
            self._record_event(fact_id, normalized.value, reason)
        fact = self.get(fact_id)
        self._mirror_fact(fact)
        return fact

    def _get_by_fact_key(self, fact_key: str) -> MemoryGraphFact | None:
        row = self.conn.execute("SELECT * FROM memory_graph_facts WHERE fact_key = ?", (fact_key,)).fetchone()
        return self._map(row) if row else None

    def _ensure_fact_columns(self, columns: dict[str, str]) -> None:
        existing = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(memory_graph_facts)").fetchall()
        }
        for column, definition in columns.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE memory_graph_facts ADD COLUMN {column} {definition}")

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

    def _increment_support(self, fact_id: str) -> MemoryGraphFact:
        with self.conn:
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

    def _mirror_fact(self, fact: MemoryGraphFact) -> None:
        if self._kuzu is not None:
            self._kuzu.upsert_fact(fact)

    def _map(self, row: sqlite3.Row) -> MemoryGraphFact:
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
            conflicts_with=row["conflicts_with"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            memory_type=row["memory_type"],
            entity_type=row["entity_type"],
            occurred_at=row["occurred_at"],
            expires_at=row["expires_at"],
            metadata_json=row["metadata_json"] or "{}",
            importance=float(row["importance"]),
        )


class _KuzuMirror:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._ready = False
        try:
            import kuzu
        except ImportError:
            self._kuzu = None
            return
        self._kuzu = kuzu
        database_path = self._database_path(root)
        try:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = kuzu.Database(str(database_path))
            self.conn = kuzu.Connection(self.db)
            self._ensure_schema()
            self._ready = True
        except Exception:
            self._ready = False

    def _database_path(self, root: Path) -> Path:
        if root.exists() and root.is_dir():
            return root / "memory_graph.kuzu"
        return root

    def _ensure_schema(self) -> None:
        self._execute("CREATE NODE TABLE IF NOT EXISTS Entity(name STRING, PRIMARY KEY(name))")
        self._execute(
            """
            CREATE NODE TABLE IF NOT EXISTS MemoryFact(
                id STRING,
                category STRING,
                predicate STRING,
                object STRING,
                status STRING,
                confidence DOUBLE,
                source_text STRING,
                support_count INT64,
                updated_at STRING,
                PRIMARY KEY(id)
            )
            """
        )
        self._execute(
            """
            CREATE NODE TABLE IF NOT EXISTS Source(id STRING, source_type STRING, text STRING, PRIMARY KEY(id))
            """
        )
        self._execute("CREATE REL TABLE IF NOT EXISTS SUBJECT_OF(FROM Entity TO MemoryFact)")
        self._execute("CREATE REL TABLE IF NOT EXISTS DERIVED_FROM(FROM MemoryFact TO Source)")

    def upsert_fact(self, fact: MemoryGraphFact) -> None:
        if not self._ready:
            return
        try:
            self._execute("MERGE (e:Entity {name: $name})", {"name": fact.subject})
            self._execute(
                """
                MERGE (f:MemoryFact {id: $id})
                SET f.category = $category,
                    f.predicate = $predicate,
                    f.object = $object,
                    f.status = $status,
                    f.confidence = $confidence,
                    f.source_text = $source_text,
                    f.support_count = $support_count,
                    f.updated_at = $updated_at
                """,
                {
                    "id": fact.id,
                    "category": fact.category,
                    "predicate": fact.predicate,
                    "object": fact.object,
                    "status": fact.status.value,
                    "confidence": fact.confidence,
                    "source_text": fact.source_text,
                    "support_count": fact.support_count,
                    "updated_at": fact.updated_at,
                },
            )
            self._execute(
                "MERGE (s:Source {id: $id}) SET s.source_type = $source_type, s.text = $text",
                {"id": fact.agent_run_id or fact.id, "source_type": fact.source_type, "text": fact.source_text},
            )
            self._execute(
                """
                MATCH (e:Entity {name: $subject}), (f:MemoryFact {id: $id})
                MERGE (e)-[:SUBJECT_OF]->(f)
                """,
                {"subject": fact.subject, "id": fact.id},
            )
            self._execute(
                """
                MATCH (f:MemoryFact {id: $id}), (s:Source {id: $source_id})
                MERGE (f)-[:DERIVED_FROM]->(s)
                """,
                {"id": fact.id, "source_id": fact.agent_run_id or fact.id},
            )
        except Exception:
            self._ready = False

    def _execute(self, query: str, params: dict[str, object] | None = None) -> None:
        if params is None:
            self.conn.execute(query)
        else:
            self.conn.execute(query, params)


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


def _hash_key(*parts: str) -> str:
    normalized = "\n".join(part.casefold().strip() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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


def _normalize_importance(value: float | None) -> float:
    if value is None:
        return 0.5
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, normalized))
