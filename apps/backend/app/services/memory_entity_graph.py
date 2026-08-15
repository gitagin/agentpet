from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

from app.models.common import new_id
from app.models.enums import MemoryFactStatus
from app.services.memory_graph import (
    MemoryFactCandidate,
    MemoryGraphFact,
    MemoryGraphWriteResult,
    MemoryGraphStore,
    authority_superseded_by,
    _sqlite_write_transaction,
)
from app.services.memory_policy import evaluate_memory_content
from app.storage.database import open_database_connection
from app.utils.hash import sha256_hex
from app.utils.public_references import safe_relative_source_reference
from app.utils.time import utc_now_iso


ENTITY_TYPES = frozenset(
    {
        "self",
        "person",
        "project",
        "preference",
        "boundary",
        "goal",
        "event",
        "concept",
        "source",
        "wiki_page",
        "decision",
    }
)
GRAPH_CONTEXT_MAX_FACTS = 12
GRAPH_CONTEXT_MAX_PATHS = 4
GRAPH_CONTEXT_MAX_CHARS = 4000
_GRAPH_QUERY_STOP_WORDS = frozenset(
    {
        "about",
        "does",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "do",
        "the",
        "and",
        "or",
    }
)
ENTITY_STATUSES = frozenset(
    {"candidate", "active", "stale", "archived", "forgotten", "rejected"}
)
RELATION_TYPES = frozenset(
    {
        "prefers",
        "avoids",
        "works_on",
        "knows",
        "related_to",
        "occurred_in",
        "supports",
        "contradicts",
        "supersedes",
        "derived_from",
        "documented_in",
    }
)
_FACT_REFERENCE_INACTIVE_STATUSES = frozenset(
    {
        MemoryFactStatus.ARCHIVED,
        MemoryFactStatus.FORGOTTEN,
        MemoryFactStatus.REJECTED,
        MemoryFactStatus.SUPERSEDED,
        MemoryFactStatus.WRONG,
        MemoryFactStatus.SENSITIVE_BLOCKED,
    }
)
ENTITY_RELATION_TYPES = frozenset(
    {"prefers", "avoids", "works_on", "knows", "related_to", "occurred_in"}
)
FACT_RELATION_TYPES = frozenset(
    {"supports", "contradicts", "supersedes", "derived_from", "documented_in"}
)
EVIDENCE_ROLES = frozenset({"names", "describes", "supports", "contradicts"})


class EntityGraphError(ValueError):
    pass


class EntityAmbiguityError(EntityGraphError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryEntity:
    id: str
    entity_key: str
    lookup_fingerprint: str
    entity_type: str
    canonical_name: str
    normalized_name: str
    status: str
    risk_tier: str
    confidence: float
    metadata: dict[str, object]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class EntityAlias:
    id: str
    entity_id: str
    alias: str
    normalized_alias: str
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EntityRelation:
    fact: MemoryGraphFact
    relation_type: str
    subject_entity_id: str | None
    subject_fact_id: str | None
    object_entity_id: str | None
    object_fact_id: str | None


@dataclass(frozen=True, slots=True)
class RecallReferences:
    entity_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectionGeneration:
    id: str
    backend: str
    schema_version: str
    source_revision: int
    status: str
    built_at: str | None
    error_code: str | None


class MemoryEntityGraphStore:
    """SQLite authority for normalized memory entities and typed relations."""

    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.graph = MemoryGraphStore(self.conn)
        self._transaction_depth = 0
        self._dirty = False
        self.backfill_explicit_legacy_candidates()

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    @contextmanager
    def atomic(self) -> Iterator["MemoryEntityGraphStore"]:
        outer = self._transaction_depth == 0
        self._transaction_depth += 1
        if outer:
            self.conn.execute("BEGIN")
        try:
            yield self
        except BaseException:
            self._transaction_depth -= 1
            if outer:
                self.conn.rollback()
                self._dirty = False
            raise
        else:
            self._transaction_depth -= 1
            if outer:
                if self._dirty:
                    self._increment_revision_in_transaction()
                self.conn.commit()
                self._dirty = False

    def source_revision(self) -> int:
        row = self.conn.execute("SELECT revision FROM graph_source_state WHERE id = 1").fetchone()
        return int(row["revision"]) if row is not None else 0

    def backfill_explicit_legacy_candidates(self) -> tuple[str, ...]:
        """Conservatively type legacy facts with a durable explicit origin.

        A name, category, or active status alone is not enough evidence.  The
        legacy row must be linked by `memory_candidates.fact_id` to a low-risk
        explicit-user candidate.  Every other legacy row stays untyped and is
        therefore audit-only.
        """
        required_tables = {"memory_entities", "memory_graph_facts", "memory_candidates", "memory_evidence"}
        present = {
            str(row["name"])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if not required_tables.issubset(present):
            return ()
        fact_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(memory_graph_facts)").fetchall()
        }
        if not {"statement_kind", "subject_entity_id"}.issubset(fact_columns):
            return ()
        rows = self.conn.execute(
            """
            SELECT
                f.id AS fact_id,
                f.category,
                f.subject,
                f.status AS fact_status,
                f.confidence AS fact_confidence,
                f.source_text AS fact_source_text,
                f.source_type AS fact_source_type,
                c.id AS candidate_id,
                c.status AS candidate_status,
                c.risk_tier,
                c.source_text AS candidate_source_text,
                c.source_text_hash,
                c.confidence AS candidate_confidence
            FROM memory_graph_facts f
            JOIN memory_candidates c ON c.fact_id = f.id
            WHERE f.statement_kind IS NULL
              AND c.source_track = 'explicit_user'
              AND c.risk_tier = 'low'
              AND c.status IN ('candidate', 'active')
              AND f.status IN ('candidate', 'active', 'quarantined')
            ORDER BY f.created_at, f.id, c.created_at, c.id
            """
        ).fetchall()
        if not rows:
            return ()

        backfilled: list[str] = []
        with self.atomic():
            for row in rows:
                source_text = str(row["candidate_source_text"] or row["fact_source_text"] or "").strip()
                if not source_text or not evaluate_memory_content(source_text).allowed:
                    continue
                entity = self._legacy_entity_for_explicit_candidate(row)
                fact_id = str(row["fact_id"])
                fact_status = str(row["fact_status"] or "")
                candidate_status = str(row["candidate_status"] or "")
                typed_status = "candidate"
                if fact_status == "quarantined":
                    typed_status = "quarantined"
                elif fact_status == "active" and candidate_status == "active":
                    typed_status = "active"
                with self._write_scope():
                    self.conn.execute(
                        """
                        UPDATE memory_graph_facts
                        SET statement_kind = 'claim', subject_entity_id = ?,
                            subject_fact_id = NULL, object_entity_id = NULL,
                            object_fact_id = NULL, relation_type = NULL, status = ?
                        WHERE id = ? AND statement_kind IS NULL
                        """,
                        (entity.id, typed_status, fact_id),
                    )
                    evidence_id = f"legacy-explicit-evidence-{sha256_hex(str(row['candidate_id']))[:32]}"
                    self._ensure_fact_evidence(
                        fact_id=fact_id,
                        evidence_id=evidence_id,
                        source_type=str(row["fact_source_type"] or "explicit_user"),
                        source_text=source_text,
                        confidence=max(
                            float(row["fact_confidence"] or 0.0),
                            float(row["candidate_confidence"] or 0.0),
                        ),
                    )
                self.bind_entity_evidence(
                    entity_id=entity.id,
                    evidence_id=evidence_id,
                    role="describes",
                )
                backfilled.append(fact_id)
        return tuple(backfilled)

    def _legacy_entity_for_explicit_candidate(self, row: sqlite3.Row) -> MemoryEntity:
        entity_type = _legacy_entity_type(str(row["category"] or ""), str(row["subject"] or ""))
        canonical_name = _clean_name(str(row["subject"] or "")) or "Legacy memory subject"
        entity_status = (
            "active"
            if str(row["fact_status"] or "") == "active" and str(row["candidate_status"] or "") == "active"
            else "candidate"
        )
        if entity_type == "self":
            existing = self.conn.execute(
                "SELECT id FROM memory_entities WHERE entity_type = 'self' LIMIT 1"
            ).fetchone()
            if existing is not None:
                return self.get_entity(str(existing["id"]))
            return self.create_entity(
                entity_type="self",
                canonical_name=canonical_name,
                entity_key="entity:self",
                status=entity_status,
                risk_tier="low",
                confidence=max(
                    float(row["fact_confidence"] or 0.0),
                    float(row["candidate_confidence"] or 0.0),
                ),
                metadata={
                    "backfill": "explicit_user_candidate_v1",
                    "origin_fact_id": str(row["fact_id"]),
                    "origin_candidate_id": str(row["candidate_id"]),
                },
            )
        entity_key = f"legacy-origin:fact:{sha256_hex(str(row['fact_id']))[:32]}"
        existing = self.conn.execute(
            "SELECT id FROM memory_entities WHERE entity_key = ?",
            (entity_key,),
        ).fetchone()
        if existing is not None:
            return self.get_entity(str(existing["id"]))
        return self.create_entity(
            entity_type=entity_type,
            canonical_name=canonical_name,
            entity_key=entity_key,
            status=entity_status,
            risk_tier="low",
            confidence=max(
                float(row["fact_confidence"] or 0.0),
                float(row["candidate_confidence"] or 0.0),
            ),
            metadata={
                "backfill": "explicit_user_candidate_v1",
                "origin_fact_id": str(row["fact_id"]),
                "origin_candidate_id": str(row["candidate_id"]),
            },
        )

    def create_entity(
        self,
        *,
        entity_type: str,
        canonical_name: str,
        entity_key: str | None = None,
        status: str = "active",
        risk_tier: str = "low",
        confidence: float = 0.8,
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryEntity:
        normalized_type = _validated_entity_type(entity_type)
        normalized_status = _validated_entity_status(status)
        normalized_risk = _validated_risk_tier(risk_tier)
        canonical = _clean_name(canonical_name)
        if not canonical:
            raise EntityGraphError("entity_name_required")
        if normalized_type == "self":
            entity_key = "entity:self"
        key = entity_key or f"entity:{new_id()}"
        now = utc_now_iso()
        row_id = new_id()
        fingerprint = lookup_fingerprint(normalized_type, canonical)
        payload = json.dumps(dict(metadata or {}), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        try:
            with self._write_scope():
                self.conn.execute(
                    """
                    INSERT INTO memory_entities (
                        id, entity_key, lookup_fingerprint, entity_type, canonical_name,
                        normalized_name, status, risk_tier, confidence, metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        key,
                        fingerprint,
                        normalized_type,
                        canonical,
                        normalize_entity_name(canonical),
                        normalized_status,
                        normalized_risk,
                        max(0.0, min(1.0, float(confidence))),
                        payload,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise EntityGraphError("entity_identity_conflict") from exc
        return self.get_entity(row_id)

    def ensure_self(self, *, canonical_name: str = "自己") -> MemoryEntity:
        row = self.conn.execute(
            "SELECT id FROM memory_entities WHERE entity_type = 'self' LIMIT 1"
        ).fetchone()
        if row is not None:
            return self.get_entity(str(row["id"]))
        return self.create_entity(entity_type="self", canonical_name=canonical_name, entity_key="entity:self")

    def get_entity(self, entity_id: str) -> MemoryEntity:
        row = self.conn.execute("SELECT * FROM memory_entities WHERE id = ?", (entity_id,)).fetchone()
        if row is None:
            raise EntityGraphError("entity_not_found")
        return _map_entity(row)

    def update_entity(
        self,
        entity_id: str,
        *,
        canonical_name: str | None = None,
        entity_type: str | None = None,
        aliases: tuple[str, ...] | list[str] | None = None,
    ) -> MemoryEntity:
        """Apply an explicit, typed entity correction in one transaction."""
        current = self.get_entity(entity_id)
        next_type = _validated_entity_type(entity_type or current.entity_type)
        next_name = _clean_name(canonical_name if canonical_name is not None else current.canonical_name)
        if not next_name:
            raise EntityGraphError("entity_name_required")
        fingerprint = lookup_fingerprint(next_type, next_name)
        now = utc_now_iso()
        with self.atomic():
            with self._write_scope():
                conflict = self.conn.execute(
                    """
                    SELECT id FROM memory_entities
                    WHERE id != ? AND entity_type = ? AND lookup_fingerprint = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (entity_id, next_type, fingerprint),
                ).fetchone()
                if conflict is not None:
                    raise EntityAmbiguityError("entity_identity_conflict")
                self.conn.execute(
                    """
                    UPDATE memory_entities
                    SET entity_type = ?, canonical_name = ?, normalized_name = ?,
                        lookup_fingerprint = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (next_type, next_name, normalize_entity_name(next_name), fingerprint, now, entity_id),
                )
                if aliases is not None:
                    self.conn.execute(
                        "DELETE FROM memory_entity_aliases WHERE entity_id = ? AND status != 'rejected'",
                        (entity_id,),
                    )
                    for alias in aliases:
                        cleaned = _clean_name(alias)
                        if not cleaned or normalize_entity_name(cleaned) == normalize_entity_name(next_name):
                            continue
                        self.add_alias(entity_id, cleaned, status="active")
        return self.get_entity(entity_id)

    def update_entity_status(
        self,
        entity_id: str,
        status: str,
        *,
        reason: str = "user_lifecycle_changed",
    ) -> MemoryEntity:
        """Change an entity lifecycle and revoke all derived recall rights atomically."""
        normalized_status = _validated_entity_status(status)
        self.get_entity(entity_id)
        with self.atomic():
            with self._write_scope():
                self.conn.execute(
                    "UPDATE memory_entities SET status = ?, updated_at = ? WHERE id = ?",
                    (normalized_status, utc_now_iso(), entity_id),
                )
                self.conn.execute(
                    "UPDATE memory_entity_aliases SET status = CASE "
                    "WHEN ? = 'active' AND status = 'candidate' THEN 'active' "
                    "WHEN ? = 'candidate' AND status = 'active' THEN 'candidate' "
                    "WHEN ? IN ('forgotten', 'rejected') THEN 'rejected' "
                    "ELSE status END "
                    "WHERE entity_id = ?",
                    (normalized_status, normalized_status, normalized_status, entity_id),
                )
            # A candidate entity is an extraction result, not an instruction
            # to activate or revoke any fact.  Only an explicit lifecycle
            # transition to/from an answerable entity changes attached facts.
            if normalized_status == "candidate":
                return self.get_entity(entity_id)
            fact_rows = self.conn.execute(
                """
                SELECT id FROM memory_graph_facts
                WHERE (subject_entity_id = ? OR object_entity_id = ?
                   OR (statement_kind = 'relation' AND
                       (subject_fact_id IN (SELECT id FROM memory_graph_facts WHERE subject_entity_id = ?)
                        OR object_fact_id IN (SELECT id FROM memory_graph_facts WHERE subject_entity_id = ?))))
                  AND status IN ('active', 'candidate', 'quarantined', 'stale')
                """,
                (entity_id, entity_id, entity_id, entity_id),
            ).fetchall()
            target_status = {
                "active": MemoryFactStatus.ACTIVE,
                "forgotten": MemoryFactStatus.FORGOTTEN,
                "rejected": MemoryFactStatus.REJECTED,
                "archived": MemoryFactStatus.ARCHIVED,
                "stale": MemoryFactStatus.STALE,
            }[normalized_status]
            for row in fact_rows:
                fact_id = str(row["id"])
                self.graph.update_status(fact_id, target_status, reason=reason)
                if target_status is not MemoryFactStatus.ACTIVE:
                    self.revoke_fact_artifacts(fact_id, reason=reason)
        return self.get_entity(entity_id)

    def activate_entity_candidate(self, entity_id: str, *, reason: str = "user_confirmed_entity") -> MemoryEntity:
        """Activate one candidate entity without reviving attached facts.

        Fact activation is a separate decision because a user may confirm an
        identity while leaving one or more extracted claims in review.
        """
        entity = self.get_entity(entity_id)
        if entity.status == "active":
            return entity
        if entity.status != "candidate":
            raise EntityGraphError("entity_not_activatable")
        with self.atomic():
            with self._write_scope():
                self.conn.execute(
                    "UPDATE memory_entities SET status = 'active', updated_at = ? WHERE id = ?",
                    (utc_now_iso(), entity_id),
                )
            aliases = self.conn.execute(
                "SELECT alias FROM memory_entity_aliases "
                "WHERE entity_id = ? AND status = 'candidate' ORDER BY id",
                (entity_id,),
            ).fetchall()
            for row in aliases:
                # add_alias performs deterministic collision validation.
                self.add_alias(entity_id, str(row["alias"]), status="active")
        return self.get_entity(entity_id)

    def correct_claim(
        self,
        fact_id: str,
        *,
        literal_value: str,
        predicate: str | None = None,
        source_text: str = "用户纠正图谱事实",
        source_type: str = "user_correction",
    ) -> tuple[MemoryGraphFact, MemoryGraphFact]:
        """Create one replacement claim and its authoritative supersedes edge."""
        current = self.get(fact_id)
        if current.statement_kind != "claim" or not current.subject_entity_id:
            raise EntityGraphError("claim_subject_untyped")
        replacement = " ".join(str(literal_value).split())
        if not replacement:
            raise EntityGraphError("claim_value_required")
        with self.atomic():
            evidence_id = f"evidence-correction-{hashlib.sha256(f'{fact_id}:{replacement}'.encode()).hexdigest()[:32]}"
            next_fact = self._create_claim_impl(
                subject_entity_id=current.subject_entity_id,
                predicate=predicate or current.predicate,
                literal_value=replacement,
                category=current.category,
                source_text=source_text,
                source_type=source_type,
                confidence=1.0,
                evidence_id=evidence_id,
            )
            if next_fact.id == current.id:
                raise EntityGraphError("correction_matches_existing_claim")
            self.graph.update_status(current.id, MemoryFactStatus.SUPERSEDED, reason="user_corrected")
            self.graph.update_status(next_fact.id, MemoryFactStatus.ACTIVE, reason="user_correction_activated")
            self._create_relation_impl(
                relation_type="supersedes",
                subject_fact_id=next_fact.id,
                object_fact_id=current.id,
                source_text=source_text,
                source_type=source_type,
                confidence=1.0,
                evidence_id=f"evidence-supersedes-{hashlib.sha256(f'{next_fact.id}:{current.id}'.encode()).hexdigest()[:32]}",
            )
            self.archive_resolved_contradictions(
                current.id,
                reason="resolved_by_user_correction",
            )
        return self.get(current.id), self.get(next_fact.id)

    def correct_relation(
        self,
        fact_id: str,
        *,
        relation_type: str,
        subject_entity_id: str | None = None,
        subject_fact_id: str | None = None,
        object_entity_id: str | None = None,
        object_fact_id: str | None = None,
        source_text: str = "用户纠正图谱关系",
    ) -> tuple[MemoryGraphFact, MemoryGraphFact]:
        current = self.get(fact_id)
        if current.statement_kind != "relation":
            raise EntityGraphError("relation_required")
        with self.atomic():
            evidence_id = f"evidence-relation-correction-{hashlib.sha256(f'{fact_id}:{relation_type}:{subject_entity_id}:{subject_fact_id}:{object_entity_id}:{object_fact_id}'.encode()).hexdigest()[:32]}"
            replacement = self._create_relation_impl(
                relation_type=relation_type,
                subject_entity_id=subject_entity_id,
                subject_fact_id=subject_fact_id,
                object_entity_id=object_entity_id,
                object_fact_id=object_fact_id,
                source_text=source_text,
                source_type="user_correction",
                confidence=1.0,
                evidence_id=evidence_id,
            )
            if replacement.id == current.id:
                raise EntityGraphError("correction_matches_existing_relation")
            self.graph.update_status(current.id, MemoryFactStatus.SUPERSEDED, reason="user_corrected_relation")
            self._create_relation_impl(
                relation_type="supersedes",
                subject_fact_id=replacement.id,
                object_fact_id=current.id,
                source_text=source_text,
                source_type="user_correction",
                confidence=1.0,
                evidence_id=f"evidence-relation-supersedes-{hashlib.sha256(f'{replacement.id}:{current.id}'.encode()).hexdigest()[:32]}",
            )
        return self.get(current.id), self.get(replacement.id)

    def upsert_candidate(
        self,
        candidate: MemoryFactCandidate,
        *,
        entity_status: str = "active",
    ) -> MemoryGraphWriteResult:
        """Persist a new fact through the typed entity and evidence boundary."""
        with self.atomic():
            subject = self._ensure_candidate_subject(candidate, entity_status=entity_status)
            existing_id = self._find_typed_claim(
                subject_id=subject.id,
                predicate=candidate.predicate,
                object_value=candidate.object,
            )
            evidence_id = (
                _candidate_evidence_id(existing_id, candidate)
                if existing_id is not None
                else None
            )
            result = self._upsert_typed_claim(
                candidate,
                subject_id=subject.id,
                evidence_id=evidence_id,
            )
            fact = result.fact
            fact_evidence_id = evidence_id or _candidate_evidence_id(fact.id, candidate)
            if evidence_id is None:
                with self._write_scope():
                    self._ensure_fact_evidence(
                        fact_id=fact.id,
                        evidence_id=fact_evidence_id,
                        source_type=candidate.source_type,
                        source_text=candidate.source_text,
                        confidence=candidate.confidence,
                    )
            self.bind_entity_evidence(
                entity_id=subject.id,
                evidence_id=fact_evidence_id,
                role="describes",
            )
            conflict = self._active_conflict_for_claim(fact.id)
            if conflict is not None:
                self._create_relation_impl(
                    relation_type="contradicts",
                    subject_fact_id=fact.id,
                    object_fact_id=conflict.id,
                    source_text=candidate.source_text,
                    source_type=candidate.source_type,
                    confidence=candidate.confidence,
                    evidence_id=f"evidence-conflict-{hashlib.sha256(f'{fact.id}:{conflict.id}'.encode()).hexdigest()[:32]}",
                )
            return MemoryGraphWriteResult(
                fact=self.graph.get(fact.id),
                inserted=result.inserted,
                reason=result.reason,
            )

    def _upsert_typed_claim(
        self,
        candidate: MemoryFactCandidate,
        *,
        subject_id: str,
        evidence_id: str | None,
    ) -> MemoryGraphWriteResult:
        existing_id = self._find_typed_claim(
            subject_id=subject_id,
            predicate=candidate.predicate,
            object_value=candidate.object,
        )
        typed_candidate = replace(
            candidate,
            subject_identity_key=_endpoint_label(subject_id, None),
            object_identity_key=None,
        )
        with self._write_scope():
            if existing_id is None:
                result = self.graph.upsert_candidate(typed_candidate)
            elif evidence_id is not None and self._evidence_is_bound(existing_id, evidence_id):
                result = MemoryGraphWriteResult(
                    fact=self.graph.get(existing_id),
                    inserted=False,
                    reason="evidence_replayed",
                )
            else:
                result = MemoryGraphWriteResult(
                    fact=self.graph.record_support(existing_id),
                    inserted=False,
                    reason="already_recorded",
                )
        fact = result.fact
        if fact.statement_kind is not None and (
            fact.statement_kind != "claim" or fact.subject_entity_id != subject_id
        ):
            raise EntityGraphError("typed_claim_identity_conflict")
        with self._write_scope():
            if fact.statement_kind is None:
                self.conn.execute(
                    """
                    UPDATE memory_graph_facts
                    SET statement_kind = 'claim', subject_entity_id = ?,
                        subject_fact_id = NULL, object_entity_id = NULL,
                        object_fact_id = NULL, relation_type = NULL
                    WHERE id = ?
                    """,
                    (subject_id, fact.id),
                )
            if evidence_id is not None:
                self._ensure_fact_evidence(
                    fact_id=fact.id,
                    evidence_id=evidence_id,
                    source_type=candidate.source_type,
                    source_text=candidate.source_text,
                    confidence=candidate.confidence,
                )
        return MemoryGraphWriteResult(
            fact=self.graph.get(fact.id),
            inserted=result.inserted,
            reason=result.reason,
        )

    def _find_typed_claim(self, *, subject_id: str, predicate: str, object_value: str) -> str | None:
        rows = self.conn.execute(
            """
            SELECT id, predicate, object
            FROM memory_graph_facts
            WHERE statement_kind = 'claim' AND subject_entity_id = ?
            ORDER BY created_at, id
            """,
            (subject_id,),
        ).fetchall()
        matches = [
            str(row["id"])
            for row in rows
            if _key_part(row["predicate"]) == _key_part(predicate)
            and _key_part(row["object"]) == _key_part(object_value)
        ]
        if len(matches) > 1:
            raise EntityGraphError("typed_claim_identity_ambiguous")
        return matches[0] if matches else None

    def _active_conflict_for_claim(self, fact_id: str) -> MemoryGraphFact | None:
        row = self.conn.execute(
            "SELECT conflict_key, object FROM memory_graph_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
        if row is None:
            return None
        conflict = self.conn.execute(
            """
            SELECT id
            FROM memory_graph_facts
            WHERE id != ?
              AND statement_kind = 'claim'
              AND conflict_key = ?
              AND status = 'active'
              AND lower(object) != lower(?)
            ORDER BY updated_at DESC, id
            LIMIT 1
            """,
            (fact_id, row["conflict_key"], row["object"]),
        ).fetchone()
        return self.graph.get(str(conflict["id"])) if conflict is not None else None

    def insert_candidate(
        self,
        candidate: MemoryFactCandidate,
        *,
        reason: str = "candidate_review_required",
    ) -> MemoryGraphWriteResult:
        with self.atomic():
            result = self.upsert_candidate(candidate, entity_status="candidate")
            if not result.inserted or result.fact.status is MemoryFactStatus.CANDIDATE:
                return result
            with self._write_scope():
                fact = self.graph.update_status(result.fact.id, MemoryFactStatus.CANDIDATE, reason=reason)
            return MemoryGraphWriteResult(fact=fact, inserted=True, reason=reason)

    def list_facts(self, *, status=None, query: str | None = None, limit: int = 50) -> list[MemoryGraphFact]:
        return self.graph.list_facts(status=status, query=query, limit=limit)

    def search_active(self, query: str, *, limit: int = 5) -> list[MemoryGraphFact]:
        return self.graph.search_active(query, limit=limit)

    def get(self, fact_id: str) -> MemoryGraphFact:
        return self.graph.get(fact_id)

    def update_status(
        self,
        fact_id: str,
        status: MemoryFactStatus | str,
        *,
        reason: str | None = None,
        lifecycle_metadata: Mapping[str, object] | None = None,
        superseded_by: str | None = None,
    ) -> MemoryGraphFact:
        with self.atomic():
            with self._write_scope():
                self.graph.update_status(
                    fact_id,
                    status,
                    reason=reason,
                    lifecycle_metadata=lifecycle_metadata,
                )
            self.deactivate_fact_references(
                fact_id,
                reason=reason or "memory_lifecycle_changed",
            )
            return self.graph.get(fact_id)

    def archive_resolved_contradictions(
        self,
        superseded_fact_id: str,
        *,
        reason: str = "resolved_by_supersession",
    ) -> tuple[str, ...]:
        """Archive active conflict edges whose historical endpoint was replaced."""
        self.graph.get(superseded_fact_id)
        rows = self.conn.execute(
            """
            SELECT id FROM memory_graph_facts
            WHERE statement_kind = 'relation'
              AND relation_type = 'contradicts'
              AND status = 'active'
              AND (subject_fact_id = ? OR object_fact_id = ?)
            ORDER BY id
            """,
            (superseded_fact_id, superseded_fact_id),
        ).fetchall()
        archived: list[str] = []
        with self.atomic():
            for row in rows:
                relation_id = str(row["id"])
                with self._write_scope():
                    self.graph.update_status(
                        relation_id,
                        MemoryFactStatus.ARCHIVED,
                        reason=reason,
                    )
                archived.append(relation_id)
        return tuple(archived)

    def _ensure_candidate_subject(
        self,
        candidate: MemoryFactCandidate,
        *,
        entity_status: str = "active",
    ) -> MemoryEntity:
        entity_type = _candidate_entity_type(candidate)
        if entity_status == "candidate":
            entity_key = _candidate_entity_key(candidate, entity_type)
            existing = self.conn.execute(
                "SELECT id FROM memory_entities WHERE entity_key = ?",
                (entity_key,),
            ).fetchone()
            if existing is not None:
                return self.get_entity(str(existing["id"]))
            return self.create_entity(
                entity_type=entity_type,
                canonical_name=candidate.subject,
                entity_key=entity_key,
                status="candidate",
                confidence=candidate.confidence,
                metadata={
                    "source_hash": sha256_hex(candidate.source_text),
                    "source_type": candidate.source_type,
                    "candidate": True,
                },
            )
        matches = self.find_candidates(entity_type=entity_type, name=candidate.subject)
        if len(matches) > 1:
            raise EntityAmbiguityError("candidate_subject_ambiguous")
        if matches:
            return matches[0]
        return self.create_entity(
            entity_type=entity_type,
            canonical_name=candidate.subject,
            status=entity_status,
            confidence=candidate.confidence,
            metadata={"source_type": candidate.source_type},
        )

    def find_candidates(self, *, entity_type: str, name: str, include_aliases: bool = True) -> list[MemoryEntity]:
        normalized_type = _validated_entity_type(entity_type)
        fingerprint = lookup_fingerprint(normalized_type, name)
        rows = self.conn.execute(
            """
            SELECT * FROM memory_entities
            WHERE entity_type = ? AND lookup_fingerprint = ? AND status = 'active'
            ORDER BY created_at, id
            """,
            (normalized_type, fingerprint),
        ).fetchall()
        entities = {_map_entity(row).id: _map_entity(row) for row in rows}
        if include_aliases:
            alias_rows = self.conn.execute(
                """
                SELECT e.*
                FROM memory_entity_aliases a
                JOIN memory_entities e ON e.id = a.entity_id
                WHERE e.entity_type = ? AND a.normalized_alias = ?
                  AND a.status = 'active' AND e.status = 'active'
                ORDER BY e.created_at, e.id
                """,
                (normalized_type, normalize_entity_name(name)),
            ).fetchall()
            for row in alias_rows:
                entity = _map_entity(row)
                entities.setdefault(entity.id, entity)
        return list(entities.values())

    def find_candidate_entities_by_source(
        self,
        *,
        entity_type: str,
        name: str,
        source_hash: str,
    ) -> list[MemoryEntity]:
        """Find an extraction candidate only within the same source payload.

        Candidate entities are deliberately not globally merged by name: two
        people can share a name.  Replaying the same source, however, must be
        idempotent so the review queue does not grow on every poll/retry.
        """
        normalized_type = _validated_entity_type(entity_type)
        fingerprint = lookup_fingerprint(normalized_type, name)
        rows = self.conn.execute(
            """
            SELECT * FROM memory_entities
            WHERE entity_type = ? AND lookup_fingerprint = ? AND status = 'candidate'
            ORDER BY created_at, id
            """,
            (normalized_type, fingerprint),
        ).fetchall()
        matches: list[MemoryEntity] = []
        for row in rows:
            try:
                metadata = json.loads(str(row["metadata_json"] or "{}"))
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            if isinstance(metadata, dict) and str(metadata.get("source_hash") or "") == source_hash:
                matches.append(_map_entity(row))
        return matches

    def add_alias(self, entity_id: str, alias: str, *, status: str = "candidate") -> EntityAlias:
        entity = self.get_entity(entity_id)
        cleaned = _clean_name(alias)
        if not cleaned:
            raise EntityGraphError("alias_required")
        if status not in {"candidate", "active", "rejected"}:
            raise EntityGraphError("invalid_entity_alias_status")
        normalized = normalize_entity_name(cleaned)
        conflict = self.conn.execute(
            """
            SELECT e.id
            FROM memory_entity_aliases a
            JOIN memory_entities e ON e.id = a.entity_id
            WHERE e.entity_type = ? AND a.normalized_alias = ?
              AND a.status = 'active' AND e.status = 'active' AND e.id != ?
            LIMIT 1
            """,
            (entity.entity_type, normalized, entity.id),
        ).fetchone()
        if conflict is not None and status == "active":
            raise EntityAmbiguityError("alias_matches_multiple_entities")
        existing = self.conn.execute(
            """
            SELECT * FROM memory_entity_aliases
            WHERE entity_id = ? AND normalized_alias = ?
            """,
            (entity.id, normalized),
        ).fetchone()
        if (
            existing is not None
            and str(existing["alias"]) == cleaned
            and str(existing["status"]) == status
        ):
            return _map_alias(existing)
        alias_id = new_id()
        now = utc_now_iso()
        with self._write_scope():
            self.conn.execute(
                """
                INSERT INTO memory_entity_aliases (
                    id, entity_id, alias, normalized_alias, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id, normalized_alias) DO UPDATE SET
                    alias = excluded.alias, status = excluded.status
                """,
                (alias_id, entity.id, cleaned, normalized, status, now),
            )
        row = self.conn.execute(
            """
            SELECT * FROM memory_entity_aliases
            WHERE entity_id = ? AND normalized_alias = ?
            """,
            (entity.id, normalized),
        ).fetchone()
        assert row is not None
        return _map_alias(row)

    def bind_entity_evidence(self, *, entity_id: str, evidence_id: str, role: str) -> None:
        self.get_entity(entity_id)
        if role not in EVIDENCE_ROLES:
            raise EntityGraphError("invalid_entity_evidence_role")
        exists = self.conn.execute("SELECT 1 FROM memory_evidence WHERE id = ?", (evidence_id,)).fetchone()
        if exists is None:
            raise EntityGraphError("evidence_not_found")
        with self._write_scope():
            self.conn.execute(
                """
                INSERT OR IGNORE INTO memory_entity_evidence(entity_id, evidence_id, role, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (entity_id, evidence_id, role, utc_now_iso()),
            )

    def create_claim(
        self,
        *,
        subject_entity_id: str,
        predicate: str,
        literal_value: str,
        category: str = "claim",
        source_text: str,
        source_type: str = "user_message",
        confidence: float = 0.8,
        evidence_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryGraphFact:
        with self.atomic():
            return self._create_claim_impl(
                subject_entity_id=subject_entity_id,
                predicate=predicate,
                literal_value=literal_value,
                category=category,
                source_text=source_text,
                source_type=source_type,
                confidence=confidence,
                evidence_id=evidence_id,
                metadata=metadata,
            )

    def _create_claim_impl(
        self,
        *,
        subject_entity_id: str,
        predicate: str,
        literal_value: str,
        category: str = "claim",
        source_text: str,
        source_type: str = "user_message",
        confidence: float = 0.8,
        evidence_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryGraphFact:
        subject = self.get_entity(subject_entity_id)
        if not literal_value.strip():
            raise EntityGraphError("claim_value_required")
        result = self._upsert_typed_claim(
            MemoryFactCandidate(
                category=category,
                subject=subject.canonical_name,
                predicate=predicate,
                object=literal_value.strip(),
                source_text=source_text,
                source_type=source_type,
                confidence=confidence,
                entity_type=subject.entity_type,
                metadata_json=json.dumps(dict(metadata or {}), ensure_ascii=True, sort_keys=True),
            ),
            subject_id=subject.id,
            evidence_id=evidence_id,
        )
        conflict = self._active_conflict_for_claim(result.fact.id)
        if conflict is not None:
            conflict_evidence_id = None
            if evidence_id is not None:
                pair = ":".join(sorted((result.fact.id, conflict.id)))
                conflict_evidence_id = f"evidence-conflict-{hashlib.sha256(pair.encode()).hexdigest()[:32]}"
            self._create_relation_impl(
                relation_type="contradicts",
                subject_fact_id=result.fact.id,
                object_fact_id=conflict.id,
                source_text=source_text,
                source_type=source_type,
                confidence=confidence,
                evidence_id=conflict_evidence_id,
            )
        return self.graph.get(result.fact.id)

    def create_relation(
        self,
        *,
        relation_type: str,
        subject_entity_id: str | None = None,
        subject_fact_id: str | None = None,
        object_entity_id: str | None = None,
        object_fact_id: str | None = None,
        source_text: str,
        source_type: str = "user_message",
        confidence: float = 0.7,
        evidence_id: str | None = None,
    ) -> MemoryGraphFact:
        with self.atomic():
            return self._create_relation_impl(
                relation_type=relation_type,
                subject_entity_id=subject_entity_id,
                subject_fact_id=subject_fact_id,
                object_entity_id=object_entity_id,
                object_fact_id=object_fact_id,
                source_text=source_text,
                source_type=source_type,
                confidence=confidence,
                evidence_id=evidence_id,
            )

    def _create_relation_impl(
        self,
        *,
        relation_type: str,
        subject_entity_id: str | None = None,
        subject_fact_id: str | None = None,
        object_entity_id: str | None = None,
        object_fact_id: str | None = None,
        source_text: str,
        source_type: str = "user_message",
        confidence: float = 0.7,
        evidence_id: str | None = None,
    ) -> MemoryGraphFact:
        relation = _validated_relation(relation_type)
        subject_kind = _endpoint_kind(subject_entity_id, subject_fact_id)
        object_kind = _endpoint_kind(object_entity_id, object_fact_id)
        self._validate_relation_endpoints(
            relation=relation,
            subject_kind=subject_kind,
            subject_entity_id=subject_entity_id,
            subject_fact_id=subject_fact_id,
            object_kind=object_kind,
            object_entity_id=object_entity_id,
            object_fact_id=object_fact_id,
        )
        # Contradiction is symmetric. Persist one deterministic orientation so
        # retries cannot create a second fact for the reversed pair.
        if relation == "contradicts" and subject_fact_id and object_fact_id:
            subject_fact_id, object_fact_id = sorted((subject_fact_id, object_fact_id))
        # A relation without a durable evidence binding is never eligible for
        # graph traversal or prompt context.  Confidence alone cannot prove a
        # relationship, including a model score of 1.0.
        if evidence_id is None:
            status = "quarantined"
        else:
            status = "active" if confidence >= 0.65 else "candidate"
        subject_label = _endpoint_label(subject_entity_id, subject_fact_id)
        object_label = _endpoint_label(object_entity_id, object_fact_id)
        existing_id = self._find_typed_relation(
            relation_type=relation,
            subject_entity_id=subject_entity_id,
            subject_fact_id=subject_fact_id,
            object_entity_id=object_entity_id,
            object_fact_id=object_fact_id,
        )
        evidence_replayed = (
            existing_id is not None
            and evidence_id is not None
            and self._evidence_is_bound(existing_id, evidence_id)
        )
        with self._write_scope():
            if existing_id is None:
                result = self.graph.upsert_candidate(
                    MemoryFactCandidate(
                        category="relation",
                        subject=subject_label,
                        predicate=relation,
                        object=object_label,
                        source_text=source_text,
                        source_type=source_type,
                        confidence=confidence,
                        memory_type="relation",
                        subject_identity_key=subject_label,
                        object_identity_key=object_label,
                    ),
                    detect_conflict=False,
                )
            elif evidence_replayed:
                result = MemoryGraphWriteResult(
                    fact=self.graph.get(existing_id),
                    inserted=False,
                    reason="evidence_replayed",
                )
            else:
                result = MemoryGraphWriteResult(
                    fact=self.graph.record_support(existing_id),
                    inserted=False,
                    reason="already_recorded",
                )
        fact = result.fact
        if fact.statement_kind is not None and not _relation_identity_matches(
            fact,
            relation_type=relation,
            subject_entity_id=subject_entity_id,
            subject_fact_id=subject_fact_id,
            object_entity_id=object_entity_id,
            object_fact_id=object_fact_id,
        ):
            raise EntityGraphError("typed_relation_identity_conflict")
        with self._write_scope():
            can_promote_candidate = (
                not evidence_replayed
                and evidence_id is not None
                and fact.status in {MemoryFactStatus.CANDIDATE, MemoryFactStatus.QUARANTINED}
            )
            if fact.statement_kind is None or can_promote_candidate:
                self.conn.execute(
                    """
                    UPDATE memory_graph_facts
                    SET statement_kind = 'relation', subject_entity_id = ?, subject_fact_id = ?,
                        object_entity_id = ?, object_fact_id = ?, relation_type = ?, status = ?
                    WHERE id = ?
                    """,
                    (
                        subject_entity_id,
                        subject_fact_id,
                        object_entity_id,
                        object_fact_id,
                        relation,
                        status,
                        fact.id,
                    ),
                )
            if evidence_id is not None:
                self._ensure_fact_evidence(
                    fact_id=fact.id,
                    evidence_id=evidence_id,
                    source_type=source_type,
                    source_text=source_text,
                    confidence=confidence,
                )
        return self.graph.get(fact.id)

    def _find_typed_relation(
        self,
        *,
        relation_type: str,
        subject_entity_id: str | None,
        subject_fact_id: str | None,
        object_entity_id: str | None,
        object_fact_id: str | None,
    ) -> str | None:
        rows = self.conn.execute(
            """
            SELECT id
            FROM memory_graph_facts
            WHERE statement_kind = 'relation'
              AND relation_type = ?
              AND subject_entity_id IS ?
              AND subject_fact_id IS ?
              AND object_entity_id IS ?
              AND object_fact_id IS ?
            ORDER BY created_at, id
            """,
            (
                relation_type,
                subject_entity_id,
                subject_fact_id,
                object_entity_id,
                object_fact_id,
            ),
        ).fetchall()
        if len(rows) > 1:
            raise EntityGraphError("typed_relation_identity_ambiguous")
        return str(rows[0]["id"]) if rows else None

    def _validate_relation_endpoints(
        self,
        *,
        relation: str,
        subject_kind: str,
        subject_entity_id: str | None,
        subject_fact_id: str | None,
        object_kind: str,
        object_entity_id: str | None,
        object_fact_id: str | None,
    ) -> None:
        if subject_kind == "missing" or object_kind == "missing":
            raise EntityGraphError("relation_endpoint_required")
        if subject_kind == "entity":
            self.get_entity(subject_entity_id or "")
        else:
            self.graph.get(subject_fact_id or "")
        if object_kind == "entity":
            self.get_entity(object_entity_id or "")
        else:
            self.graph.get(object_fact_id or "")

        if relation in ENTITY_RELATION_TYPES:
            if subject_kind != "entity" or object_kind != "entity":
                raise EntityGraphError("relation_endpoint_type_invalid")
            return

        if relation in {"contradicts", "supersedes"}:
            if subject_kind != "fact" or object_kind != "fact":
                raise EntityGraphError("relation_endpoint_type_invalid")
            return

        if relation == "supports":
            if object_kind != "fact" or subject_kind not in {"entity", "fact"}:
                raise EntityGraphError("relation_endpoint_type_invalid")
            if subject_kind == "entity" and self.get_entity(subject_entity_id or "").entity_type != "source":
                raise EntityGraphError("supports_subject_must_be_source")
            return

        if relation == "derived_from":
            if subject_kind not in {"entity", "fact"} or object_kind not in {"entity", "fact"}:
                raise EntityGraphError("relation_endpoint_type_invalid")
            if object_kind == "entity" and self.get_entity(object_entity_id or "").entity_type != "source":
                raise EntityGraphError("derived_from_object_must_be_source")
            return

        if relation == "documented_in":
            if subject_kind not in {"entity", "fact"} or object_kind != "entity":
                raise EntityGraphError("relation_endpoint_type_invalid")
            if self.get_entity(object_entity_id or "").entity_type != "wiki_page":
                raise EntityGraphError("documented_in_object_must_be_wiki_page")
            return

        raise EntityGraphError("relation_endpoint_type_invalid")

    def list_relations(
        self,
        *,
        status: str = "active",
        limit: int = 200,
        vault_id: str | None = None,
    ) -> list[EntityRelation]:
        rows = self.conn.execute(
            """
            SELECT * FROM memory_graph_facts
            WHERE statement_kind = 'relation' AND status = ?
            ORDER BY updated_at DESC, id
            LIMIT ?
            """,
            (status, max(1, min(limit, 1000))),
        ).fetchall()
        return [
            EntityRelation(
                fact=self.graph.get(str(row["id"])),
                relation_type=str(row["relation_type"]),
                subject_entity_id=row["subject_entity_id"],
                subject_fact_id=row["subject_fact_id"],
                object_entity_id=row["object_entity_id"],
                object_fact_id=row["object_fact_id"],
            )
            for row in rows
            if _relation_row_recallable(self.conn, row, vault_id=vault_id)
        ]

    def fact_visible_in_vault(self, fact_id: str, *, vault_id: str | None) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM memory_graph_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
        return row is not None and _artifact_scope_allowed(self.conn, fact_id, vault_id)

    def statement_recallable(self, fact_id: str, *, vault_id: str | None) -> bool:
        row = self.conn.execute(
            "SELECT * FROM memory_graph_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
        if row is None:
            return False
        if str(row["statement_kind"] or "") == "relation":
            return _relation_row_recallable(self.conn, row, vault_id=vault_id)
        return _fact_row_recallable(self.conn, fact_id, vault_id=vault_id)

    def recall_references(self, fact_id: str, *, vault_id: str | None) -> RecallReferences:
        """Read safe provenance for a fact that has already passed recall gates."""
        row = self.conn.execute(
            "SELECT subject_entity_id, object_entity_id FROM memory_graph_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()
        if row is None or not self.statement_recallable(fact_id, vault_id=vault_id):
            return RecallReferences()
        entity_ids = tuple(
            dict.fromkeys(
                str(value)
                for value in (row[0], row[1])
                if value is not None and str(value).strip()
            )
        )
        evidence_rows = self.conn.execute(
            "SELECT id FROM memory_evidence WHERE fact_id = ? ORDER BY created_at, id",
            (fact_id,),
        ).fetchall()
        evidence_ids = tuple(str(item[0]) for item in evidence_rows)
        source_refs: list[str] = []
        clauses = ["fact_id = ?", "status = 'active'", "artifact_type IN ('source', 'wiki_page')"]
        params: list[object] = [fact_id]
        if vault_id is None:
            clauses.append("vault_id IS NULL")
        else:
            clauses.append("(vault_id IS NULL OR vault_id = ?)")
            params.append(vault_id)
        rows = self.conn.execute(
            f"SELECT artifact_ref FROM memory_fact_artifact_bindings WHERE {' AND '.join(clauses)} ORDER BY artifact_type, artifact_ref",
            tuple(params),
        ).fetchall()
        for item in rows:
            value = safe_relative_source_reference(item[0])
            if value is not None:
                source_refs.append(value)
        return RecallReferences(
            entity_ids=entity_ids,
            evidence_ids=evidence_ids,
            source_refs=tuple(dict.fromkeys(source_refs)),
        )

    def answerable_facts(
        self,
        *,
        query: str | None = None,
        vault_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryGraphFact]:
        """Return only typed, evidenced facts permitted for prompt context."""
        clauses = [
            "f.statement_kind IN ('claim', 'relation')",
            "f.status = 'active'",
            "f.confidence >= 0.65",
            "(f.statement_kind != 'relation' OR f.relation_type NOT IN ('contradicts', 'supersedes'))",
            "EXISTS (SELECT 1 FROM memory_evidence e WHERE e.fact_id = f.id)",
            "NOT EXISTS (SELECT 1 FROM memory_graph_facts c "
            "WHERE c.statement_kind = 'relation' AND c.relation_type = 'contradicts' "
            "AND c.status = 'active' AND (c.subject_fact_id = f.id OR c.object_fact_id = f.id) "
            "AND NOT EXISTS (SELECT 1 FROM memory_graph_facts s "
            "WHERE s.statement_kind = 'relation' AND s.relation_type = 'supersedes' "
            "AND s.status = 'active' AND (s.object_fact_id = c.subject_fact_id OR s.object_fact_id = c.object_fact_id)))",
            "NOT EXISTS (SELECT 1 FROM memory_graph_facts s "
            "WHERE s.statement_kind = 'relation' AND s.relation_type = 'supersedes' "
            "AND s.status = 'active' AND s.object_fact_id = f.id)",
            "(f.expires_at IS NULL OR f.expires_at > ?)",
        ]
        params: list[object] = [utc_now_iso()]
        # Artifact bindings are a scope gate, not a second fact source.  A
        # fact with no binding is a global chat fact; a global binding applies
        # to every Vault; a scoped binding applies only to that Vault.  This
        # form also permits a fact with both a current and an historical
        # cross-Vault binding while excluding the foreign artifact itself.
        if vault_id is None:
            clauses.append(
                "(NOT EXISTS (SELECT 1 FROM memory_fact_artifact_bindings b "
                "WHERE b.fact_id = f.id AND b.status = 'active') "
                "OR EXISTS (SELECT 1 FROM memory_fact_artifact_bindings b "
                "WHERE b.fact_id = f.id AND b.status = 'active' AND b.vault_id IS NULL))"
            )
        else:
            clauses.append(
                "(NOT EXISTS (SELECT 1 FROM memory_fact_artifact_bindings b "
                "WHERE b.fact_id = f.id AND b.status = 'active') "
                "OR EXISTS (SELECT 1 FROM memory_fact_artifact_bindings b "
                "WHERE b.fact_id = f.id AND b.status = 'active' "
                "AND (b.vault_id IS NULL OR b.vault_id = ?)))"
            )
            params.append(vault_id)
        if query and query.strip():
            pattern = f"%{query.strip().casefold()}%"
            clauses.append(
                "(lower(f.subject) LIKE ? OR lower(f.predicate) LIKE ? OR lower(f.object) LIKE ? "
                "OR lower(f.source_text) LIKE ?)"
            )
            params.extend([pattern] * 4)
        params.append(max(1, min(limit, 200)))
        rows = self.conn.execute(
            f"""
            SELECT f.*
            FROM memory_graph_facts f
            WHERE {' AND '.join(clauses)}
            ORDER BY f.importance DESC, f.updated_at DESC, f.id
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        # SQL predicates above are intentionally broad enough for legacy
        # databases.  Re-run the same typed endpoint/lifecycle gate used by
        # traversal so a stale entity, malformed relation, or revoked fact
        # cannot enter prompt context merely because its row says `active`.
        answerable: list[MemoryGraphFact] = []
        for row in rows:
            fact = self.graph._map(row)
            if fact.statement_kind == "relation":
                if _relation_row_recallable(self.conn, row, vault_id=vault_id):
                    answerable.append(fact)
                continue
            if fact.statement_kind == "claim" and _fact_row_recallable(
                self.conn,
                fact.id,
                vault_id=vault_id,
            ):
                answerable.append(fact)
        return answerable

    def answerable_graph_facts(
        self,
        *,
        query: str,
        vault_id: str | None = None,
        max_hops: int = 2,
        limit: int = 50,
    ) -> list[MemoryGraphFact]:
        """Combine direct matches with a bounded, evidence-gated graph walk."""
        cap = max(1, min(limit, GRAPH_CONTEXT_MAX_FACTS))
        all_facts = self.answerable_facts(vault_id=vault_id, limit=200)
        terms = _graph_query_terms(query)
        selected_ids: list[str] = [
            fact.id
            for fact in all_facts
            if not terms or _fact_matches_graph_terms(fact, terms)
        ]
        for entity_id in _exact_query_entity_ids(self, query):
            for relation in self.traverse(
                entity_id,
                max_hops=max_hops,
                limit=min(cap, GRAPH_CONTEXT_MAX_PATHS),
                vault_id=vault_id,
            ):
                if relation.relation_type in {"contradicts", "supersedes"}:
                    # Conflict and version paths are diagnostic context only;
                    # they must never become deterministic answer material.
                    continue
                if relation.fact.id not in selected_ids and relation.fact.id in {fact.id for fact in all_facts}:
                    selected_ids.append(relation.fact.id)
        by_id = {fact.id: fact for fact in all_facts}
        selected: list[MemoryGraphFact] = []
        used_chars = 0
        for fact_id in selected_ids:
            fact = by_id.get(fact_id)
            if fact is None:
                continue
            snippet_chars = len(f"{fact.subject} {fact.predicate} {fact.object}")
            if selected and used_chars + snippet_chars > GRAPH_CONTEXT_MAX_CHARS:
                continue
            selected.append(fact)
            used_chars += snippet_chars
            if len(selected) >= cap:
                break
        return selected

    def traverse(
        self,
        entity_id: str,
        *,
        max_hops: int = 2,
        limit: int = 100,
        vault_id: str | None = None,
    ) -> list[EntityRelation]:
        entity = self.get_entity(entity_id)
        if entity.status != "active" or entity.risk_tier not in {"low", "medium"}:
            return []
        hops = max(1, min(max_hops, 2))
        cap = max(1, min(limit, 1000))
        seen_endpoints = {("entity", entity_id)}
        frontier = deque([("entity", entity_id, 0)])
        relation_ids: list[str] = []
        while frontier and len(relation_ids) < cap:
            endpoint_kind, current, depth = frontier.popleft()
            if endpoint_kind == "entity":
                endpoint_clause = "(subject_entity_id = ? OR object_entity_id = ?)"
                endpoint_params: tuple[object, ...] = (current, current)
            else:
                endpoint_clause = "(subject_fact_id = ? OR object_fact_id = ?)"
                endpoint_params = (current, current)
            rows = self.conn.execute(
                f"""
                SELECT * FROM memory_graph_facts
                WHERE statement_kind = 'relation' AND status = 'active'
                  AND {endpoint_clause}
                ORDER BY updated_at DESC, id
                LIMIT ?
                """,
                (*endpoint_params, cap),
            ).fetchall()
            for row in rows:
                if not _relation_row_recallable(self.conn, row, vault_id=vault_id):
                    continue
                relation_id = str(row["id"])
                if relation_id in relation_ids:
                    continue
                relation_ids.append(relation_id)
                if depth + 1 >= hops:
                    continue
                endpoints = (
                    ("entity", row["subject_entity_id"]),
                    ("fact", row["subject_fact_id"]),
                    ("entity", row["object_entity_id"]),
                    ("fact", row["object_fact_id"]),
                )
                for next_kind, endpoint in endpoints:
                    key = (next_kind, endpoint)
                    if isinstance(endpoint, str) and endpoint and key not in seen_endpoints:
                        seen_endpoints.add(key)
                        frontier.append((next_kind, endpoint, depth + 1))
        return [self._relation_by_id(item) for item in relation_ids[:cap]]

    def bind_wiki_page(
        self,
        *,
        vault_id: str,
        page_entity_id: str,
        wiki_relative_path: str,
        content_hash: str | None,
        revision: int | None = None,
        status: str = "active",
    ) -> str:
        entity = self.get_entity(page_entity_id)
        if entity.entity_type != "wiki_page":
            raise EntityGraphError("wiki_binding_requires_page_entity")
        path = _safe_wiki_path(wiki_relative_path)
        row_id = new_id()
        with self._write_scope():
            self.conn.execute(
                """
                INSERT INTO wiki_page_bindings (
                    id, vault_id, page_entity_id, wiki_relative_path, content_hash,
                    revision, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vault_id, page_entity_id) DO UPDATE SET
                    wiki_relative_path = excluded.wiki_relative_path,
                    content_hash = excluded.content_hash,
                    revision = excluded.revision,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (row_id, vault_id, entity.id, path, content_hash, revision or 0, status, utc_now_iso()),
            )
        row = self.conn.execute(
            "SELECT id FROM wiki_page_bindings WHERE vault_id = ? AND page_entity_id = ?",
            (vault_id, entity.id),
        ).fetchone()
        assert row is not None
        return str(row["id"])

    def get_wiki_binding(self, *, vault_id: str, wiki_relative_path: str):
        path = _safe_wiki_path(wiki_relative_path)
        row = self.conn.execute(
            "SELECT * FROM wiki_page_bindings WHERE vault_id = ? AND wiki_relative_path = ?",
            (vault_id, path),
        ).fetchone()
        return row

    def update_wiki_binding(
        self,
        binding_id: str,
        *,
        content_hash: str | None,
        status: str,
        revision: int | None = None,
    ) -> None:
        if status not in {"active", "stale", "quarantined", "forgotten"}:
            raise EntityGraphError("invalid_wiki_binding_status")
        row = self.conn.execute(
            "SELECT content_hash, status, revision FROM wiki_page_bindings WHERE id = ?",
            (binding_id,),
        ).fetchone()
        if row is None:
            raise EntityGraphError("wiki_binding_not_found")
        next_revision = int(row["revision"] or 0) if revision is None else max(0, int(revision))
        if (
            str(row["content_hash"] or "") == str(content_hash or "")
            and str(row["status"]) == status
            and int(row["revision"] or 0) == next_revision
        ):
            return
        with self._write_scope():
            self.conn.execute(
                """
                UPDATE wiki_page_bindings
                SET content_hash = ?, status = ?, revision = ?, updated_at = ?
                WHERE id = ?
                """,
                (content_hash, status, next_revision, utc_now_iso(), binding_id),
            )

    def list_wiki_bindings(self, *, vault_id: str, status: str | None = None):
        clauses = ["vault_id = ?"]
        params: list[object] = [vault_id]
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        return self.conn.execute(
            f"SELECT * FROM wiki_page_bindings WHERE {' AND '.join(clauses)} ORDER BY wiki_relative_path",
            tuple(params),
        ).fetchall()

    def bind_artifact(
        self,
        *,
        fact_id: str,
        vault_id: str | None,
        artifact_type: str,
        artifact_ref: str,
        status: str = "active",
    ) -> str:
        if artifact_type not in {"source", "wiki_page", "fts_chunk"}:
            raise EntityGraphError("invalid_artifact_type")
        self.graph.get(fact_id)
        binding_id = new_id()
        with self._write_scope():
            self.conn.execute(
                """
                INSERT INTO memory_fact_artifact_bindings (
                    id, fact_id, vault_id, artifact_type, artifact_ref, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fact_id, vault_id, artifact_type, artifact_ref) DO UPDATE SET
                    status = excluded.status, updated_at = excluded.updated_at
                """,
                (binding_id, fact_id, vault_id, artifact_type, artifact_ref, status, utc_now_iso(), utc_now_iso()),
            )
        row = self.conn.execute(
            """
            SELECT id FROM memory_fact_artifact_bindings
            WHERE fact_id = ? AND vault_id IS ? AND artifact_type = ? AND artifact_ref = ?
            """,
            (fact_id, vault_id, artifact_type, artifact_ref),
        ).fetchone()
        assert row is not None
        return str(row["id"])

    def revoke_fact_artifacts(self, fact_id: str, *, reason: str = "memory_lifecycle_changed") -> None:
        with self._write_scope():
            self.conn.execute(
                """
                UPDATE memory_fact_artifact_bindings
                SET status = 'revoked', updated_at = ?
                WHERE fact_id = ? AND status = 'active'
                """,
                (utc_now_iso(), fact_id),
            )

    def deactivate_fact_references(
        self,
        fact_id: str,
        *,
        reason: str = "memory_lifecycle_changed",
    ) -> tuple[str, ...]:
        fact = self.graph.get(fact_id)
        if fact.status not in _FACT_REFERENCE_INACTIVE_STATUSES:
            return ()
        with self.atomic():
            self.revoke_fact_artifacts(fact.id, reason=reason)
            rows = self.conn.execute(
                """
                SELECT id
                FROM memory_graph_facts
                WHERE statement_kind = 'relation'
                  AND relation_type = 'documented_in'
                  AND status = 'active'
                  AND (subject_fact_id = ? OR object_fact_id = ?)
                ORDER BY created_at, id
                """,
                (fact.id, fact.id),
            ).fetchall()
            relation_ids = tuple(str(row["id"]) for row in rows)
            for relation_id in relation_ids:
                with self._write_scope():
                    self.graph.update_status(
                        relation_id,
                        MemoryFactStatus.ARCHIVED,
                        reason=reason,
                    )
        return relation_ids

    def start_projection_generation(self, *, schema_version: str = "llmwiki-graph-v1") -> ProjectionGeneration:
        generation_id = new_id()
        # Generation bookkeeping describes a derived artifact; it must not
        # advance the authority revision or make the artifact stale by itself.
        with self._projection_metadata_scope():
            self.conn.execute(
                """
                INSERT INTO graph_projection_generations (
                    id, backend, schema_version, source_revision, status, built_at, error_code
                ) VALUES (?, 'kuzu', ?, ?, 'building', NULL, NULL)
                """,
                (generation_id, schema_version, self.source_revision()),
            )
        return self.get_generation(generation_id)

    def finish_projection_generation(
        self,
        generation_id: str,
        *,
        success: bool,
        error_code: str | None = None,
    ) -> ProjectionGeneration:
        generation = self.get_generation(generation_id)
        current_revision = self.source_revision()
        status = "active" if success and generation.source_revision == current_revision else "stale"
        if not success:
            status = "failed"
        with self._projection_metadata_scope():
            if status == "active":
                # There is one authoritative active generation.  Older files
                # remain on disk until maintenance removes them, but their
                # metadata can never win a latest-active lookup.
                self.conn.execute(
                    """
                    UPDATE graph_projection_generations
                    SET status = 'stale', error_code = COALESCE(error_code, 'replaced_by_new_generation')
                    WHERE backend = 'kuzu' AND status = 'active' AND id != ?
                    """,
                    (generation_id,),
                )
            self.conn.execute(
                """
                UPDATE graph_projection_generations
                SET status = ?, built_at = ?, error_code = ?
                WHERE id = ?
                """,
                (status, utc_now_iso(), error_code, generation_id),
            )
        return self.get_generation(generation_id)

    def get_generation(self, generation_id: str) -> ProjectionGeneration:
        row = self.conn.execute(
            "SELECT * FROM graph_projection_generations WHERE id = ?", (generation_id,)
        ).fetchone()
        if row is None:
            raise EntityGraphError("projection_generation_not_found")
        return ProjectionGeneration(
            id=str(row["id"]),
            backend=str(row["backend"]),
            schema_version=str(row["schema_version"]),
            source_revision=int(row["source_revision"]),
            status=str(row["status"]),
            built_at=row["built_at"],
            error_code=row["error_code"],
        )

    @contextmanager
    def _write_scope(self) -> Iterator[None]:
        """Run one authority write and advance the source revision on change.

        ``sqlite3.Connection.total_changes`` is monotonic for the lifetime of
        a connection, so the delta gives us a transaction-local changed bit
        without asking every caller to duplicate row-count checks.  A failed
        write never leaves ``_dirty`` set for the next transaction.
        """
        before = self.conn.total_changes
        outer = self._transaction_depth == 0
        if outer:
            self.conn.execute("BEGIN")
        try:
            yield
        except BaseException:
            if outer:
                self.conn.rollback()
                self._dirty = False
            raise
        else:
            changed = self.conn.total_changes != before
            if changed:
                self._dirty = True
            if outer:
                if self._dirty:
                    self._increment_revision_in_transaction()
                self.conn.commit()
                self._dirty = False

    @contextmanager
    def _projection_metadata_scope(self) -> Iterator[None]:
        """Persist derived-generation state without changing source revision."""
        if self._transaction_depth > 0:
            yield
            return
        with _sqlite_write_transaction(self.conn):
            yield

    def _increment_revision_in_transaction(self) -> None:
        self.conn.execute(
            "UPDATE graph_source_state SET revision = revision + 1, updated_at = ? WHERE id = 1",
            (utc_now_iso(),),
        )

    def _ensure_evidence(self, evidence_id: str) -> None:
        row = self.conn.execute("SELECT 1 FROM memory_evidence WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            raise EntityGraphError("evidence_not_found")

    def _evidence_is_bound(self, fact_id: str, evidence_id: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM memory_evidence WHERE id = ? AND fact_id = ?",
                (evidence_id, fact_id),
            ).fetchone()
            is not None
        )

    def _ensure_fact_evidence(
        self,
        *,
        fact_id: str,
        evidence_id: str,
        source_type: str,
        source_text: str,
        confidence: float,
    ) -> None:
        existing = self.conn.execute(
            "SELECT fact_id FROM memory_evidence WHERE id = ?", (evidence_id,)
        ).fetchone()
        if existing is not None:
            if existing["fact_id"] not in {None, fact_id}:
                raise EntityGraphError("evidence_already_bound")
            if existing["fact_id"] == fact_id:
                return
            self.conn.execute(
                "UPDATE memory_evidence SET fact_id = COALESCE(fact_id, ?) WHERE id = ?",
                (fact_id, evidence_id),
            )
            return
        self.conn.execute(
            """
            INSERT INTO memory_evidence (
                id, fact_id, source_type, source_text_hash, source_excerpt, confidence, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?)
            """,
            (
                evidence_id,
                fact_id,
                source_type,
                hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                source_text[:1000],
                confidence,
                utc_now_iso(),
            ),
        )

    def _bind_relation_evidence(self, fact_id: str, evidence_id: str, source_type: str, source_text: str, confidence: float) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO memory_evidence (
                id, fact_id, source_type, source_text_hash, source_excerpt, confidence, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?)
            """,
            (
                evidence_id,
                fact_id,
                source_type,
                hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                source_text[:1000],
                confidence,
                utc_now_iso(),
            ),
        )

    def _relation_by_id(self, relation_id: str) -> EntityRelation:
        row = self.conn.execute("SELECT * FROM memory_graph_facts WHERE id = ?", (relation_id,)).fetchone()
        if row is None:
            raise EntityGraphError("relation_not_found")
        return EntityRelation(
            fact=self.graph.get(relation_id),
            relation_type=str(row["relation_type"]),
            subject_entity_id=row["subject_entity_id"],
            subject_fact_id=row["subject_fact_id"],
            object_entity_id=row["object_entity_id"],
            object_fact_id=row["object_fact_id"],
        )


def normalize_entity_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.casefold().split())
    return text.strip(" \t\r\n.,;:!?，。；：！？、()[]{}<>《》『』「」")


def _graph_query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in normalize_entity_name(query).replace("?", " ").replace(",", " ").split():
        term = normalize_entity_name(raw)
        if len(term) >= 2 and term not in _GRAPH_QUERY_STOP_WORDS:
            terms.append(term)
    return tuple(dict.fromkeys(terms))


def _fact_matches_graph_terms(fact: MemoryGraphFact, terms: tuple[str, ...]) -> bool:
    text = normalize_entity_name(" ".join((fact.subject, fact.predicate, fact.object, fact.source_text)))
    tokens = frozenset(re.findall(r"[\w-]+", text, flags=re.UNICODE))
    return any(term in tokens if term.isascii() else term in text for term in terms)


def _exact_query_entity_ids(store: MemoryEntityGraphStore, query: str) -> tuple[str, ...]:
    candidates = [query.strip(), *_graph_query_terms(query)]
    entity_ids: list[str] = []
    for candidate in dict.fromkeys(item for item in candidates if item.strip()):
        for entity_type in sorted(ENTITY_TYPES):
            for entity in store.find_candidates(entity_type=entity_type, name=candidate):
                if entity.id not in entity_ids:
                    entity_ids.append(entity.id)
    return tuple(entity_ids[:50])


def lookup_fingerprint(entity_type: str, name: str) -> str:
    normalized_type = _validated_entity_type(entity_type)
    normalized_name = normalize_entity_name(name)
    return hashlib.sha256(f"{normalized_type}\x1f{normalized_name}".encode("utf-8")).hexdigest()


def _validated_entity_type(value: str) -> str:
    normalized = str(value).strip().casefold()
    if normalized not in ENTITY_TYPES:
        raise EntityGraphError("invalid_entity_type")
    return normalized


def _validated_entity_status(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in ENTITY_STATUSES:
        raise EntityGraphError("invalid_entity_status")
    return normalized


def _validated_risk_tier(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in {"low", "medium", "high"}:
        raise EntityGraphError("invalid_entity_risk_tier")
    return normalized


def _candidate_entity_type(candidate: MemoryFactCandidate) -> str:
    explicit = str(candidate.entity_type or "").strip().casefold()
    if explicit in ENTITY_TYPES:
        return explicit
    category = str(candidate.category or "").strip().casefold()
    if category in {"preference", "boundary", "goal", "event", "project", "person"}:
        return category
    subject = normalize_entity_name(candidate.subject)
    if subject in {"self", "myself", "user", "我", "自己"}:
        return "self"
    return "concept"


def _candidate_entity_key(candidate: MemoryFactCandidate, entity_type: str) -> str:
    origin = candidate.user_message_id or (
        f"{candidate.conversation_id or 'no-conversation'}:{sha256_hex(candidate.source_text)}"
    )
    payload = "\x1f".join(
        ("candidate-entity-v1", entity_type, normalize_entity_name(candidate.subject), origin)
    )
    return f"candidate-origin:{sha256_hex(payload)[:40]}"


def _legacy_entity_type(category: str, subject: str) -> str:
    """Map a legacy fact to a typed entity without guessing from its value.

    Legacy rows do not carry an entity type.  Only the old categorical field
    and an exact self marker are durable enough for a conservative migration;
    arbitrary text is kept as a ``concept`` rather than being inferred as a
    person, project, or identity.
    """
    normalized_category = normalize_entity_name(category).replace("-", "_")
    normalized_subject = normalize_entity_name(subject)
    if normalized_subject in {"self", "myself", "user", "我", "自己", "本人"}:
        return "self"
    category_map = {
        "preference": "preference",
        "preferences": "preference",
        "偏好": "preference",
        "boundary": "boundary",
        "boundaries": "boundary",
        "边界": "boundary",
        "goal": "goal",
        "goals": "goal",
        "目标": "goal",
        "event": "event",
        "events": "event",
        "事件": "event",
        "project": "project",
        "projects": "project",
        "project_context": "project",
        "项目": "project",
        "person": "person",
        "people": "person",
        "relationship": "person",
        "人物": "person",
        "source": "source",
        "来源": "source",
        "wiki_page": "wiki_page",
        "wiki": "wiki_page",
        "页面": "wiki_page",
        "decision": "decision",
        "decisions": "decision",
        "决策": "decision",
        "concept": "concept",
        "概念": "concept",
    }
    return category_map.get(normalized_category, "concept")


def _candidate_evidence_id(fact_id: str, candidate: MemoryFactCandidate) -> str:
    payload = "\x1f".join(
        (
            fact_id,
            candidate.source_type,
            candidate.source_text,
            candidate.conversation_id or "",
            candidate.user_message_id or "",
        )
    )
    return f"evidence-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:40]}"


def _validated_relation(value: str) -> str:
    normalized = str(value).strip().casefold()
    if normalized not in RELATION_TYPES:
        raise EntityGraphError("invalid_relation_type")
    return normalized


def _clean_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.split()).strip()
    return text.strip(" \t\r\n.,;:!?，。；：！？、()[]{}<>《》『』「」")


def _safe_wiki_path(value: str) -> str:
    path = str(value or "").replace("\\", "/").strip()
    parts = tuple(part for part in path.split("/") if part)
    if not parts or parts[0].casefold() != "wiki" or path.startswith("/") or ".." in parts:
        raise EntityGraphError("wiki_binding_path_invalid")
    if any(part.startswith(".") for part in parts) or not path.casefold().endswith(".md"):
        raise EntityGraphError("wiki_binding_path_invalid")
    return "/".join(parts)


def _endpoint_kind(entity_id: str | None, fact_id: str | None) -> str:
    if bool(entity_id) == bool(fact_id):
        return "missing"
    return "entity" if entity_id else "fact"


def _endpoint_label(entity_id: str | None, fact_id: str | None) -> str:
    return f"entity:{entity_id}" if entity_id else f"fact:{fact_id}"


def _key_part(value: object) -> str:
    return str(value or "").casefold().strip()


def _relation_identity_matches(
    fact: MemoryGraphFact,
    *,
    relation_type: str,
    subject_entity_id: str | None,
    subject_fact_id: str | None,
    object_entity_id: str | None,
    object_fact_id: str | None,
) -> bool:
    return (
        fact.statement_kind == "relation"
        and fact.relation_type == relation_type
        and fact.subject_entity_id == subject_entity_id
        and fact.subject_fact_id == subject_fact_id
        and fact.object_entity_id == object_entity_id
        and fact.object_fact_id == object_fact_id
    )


def _relation_row_recallable(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    vault_id: str | None = None,
) -> bool:
    """Return whether a typed relation is safe for graph context.

    The check intentionally re-validates endpoint types and evidence instead
    of trusting a status string or a projection row.  Kuzu and the visual
    projection both call this boundary before exposing a relation.
    """
    if str(row["statement_kind"] or "") != "relation" or str(row["status"] or "") != "active":
        return False
    relation_type = str(row["relation_type"] or "").casefold()
    if relation_type not in RELATION_TYPES or float(row["confidence"] or 0.0) < 0.65:
        return False
    subject_entity = row["subject_entity_id"]
    subject_fact = row["subject_fact_id"]
    object_entity = row["object_entity_id"]
    object_fact = row["object_fact_id"]
    if bool(subject_entity) == bool(subject_fact) or bool(object_entity) == bool(object_fact):
        return False

    subject_type = _entity_type_for_recall(conn, subject_entity)
    object_type = _entity_type_for_recall(conn, object_entity)
    if subject_entity and subject_type is None or object_entity and object_type is None:
        return False
    if relation_type in ENTITY_RELATION_TYPES:
        if not subject_entity or not object_entity:
            return False
    elif relation_type in {"contradicts", "supersedes"}:
        if not subject_fact or not object_fact:
            return False
    elif relation_type == "supports":
        if not object_fact or (subject_entity and subject_type != "source"):
            return False
        if not subject_entity and not subject_fact:
            return False
    elif relation_type == "derived_from":
        if not (subject_entity or subject_fact) or not (object_entity or object_fact):
            return False
        if object_entity and object_type != "source":
            return False
    elif relation_type == "documented_in":
        if not (subject_entity or subject_fact) or not object_entity or object_type != "wiki_page":
            return False
    else:
        return False

    if not _artifact_scope_allowed(conn, str(row["id"]), vault_id):
        return False
    if conn.execute(
        "SELECT 1 FROM memory_evidence WHERE fact_id = ? LIMIT 1",
        (row["id"],),
    ).fetchone() is None:
        return False
    if not evaluate_memory_content(str(row["source_text"] or "")).allowed:
        return False

    # A provenance/version relation may point at historical facts so that the
    # UI can show the chain.  Ordinary answer-context relations may not point
    # at forgotten, expired, sensitive or superseded facts.
    if relation_type not in {"contradicts", "supersedes"}:
        for fact_id in (subject_fact, object_fact):
            if fact_id and not _fact_row_recallable(conn, str(fact_id), vault_id=vault_id):
                return False
    return _lifecycle_metadata_allowed(row)


def _fact_row_recallable(
    conn: sqlite3.Connection,
    fact_id: str,
    *,
    vault_id: str | None = None,
) -> bool:
    row = conn.execute(
        "SELECT * FROM memory_graph_facts WHERE id = ?",
        (fact_id,),
    ).fetchone()
    if row is None or str(row["status"] or "") != "active":
        return False
    if str(row["statement_kind"] or "") not in {"claim", "relation"}:
        return False
    if float(row["confidence"] or 0.0) < 0.65:
        return False
    # A claim inherits the lifecycle and risk gate of its subject entity.
    # This closes the otherwise possible path where forgetting an entity (or
    # a direct legacy status update) leaves its claim answerable.
    if str(row["statement_kind"] or "") == "claim":
        subject_entity_id = row["subject_entity_id"]
        if not subject_entity_id:
            return False
        entity = conn.execute(
            "SELECT status, risk_tier FROM memory_entities WHERE id = ?",
            (str(subject_entity_id),),
        ).fetchone()
        if entity is None or str(entity["status"] or "") != "active":
            return False
        if str(entity["risk_tier"] or "high") not in {"low", "medium"}:
            return False
    if conn.execute(
        "SELECT 1 FROM memory_evidence WHERE fact_id = ? LIMIT 1",
        (fact_id,),
    ).fetchone() is None:
        return False
    if not evaluate_memory_content(str(row["source_text"] or "")).allowed:
        return False
    if not _artifact_scope_allowed(conn, fact_id, vault_id):
        return False
    if authority_superseded_by(conn, fact_id) or _has_unresolved_contradiction(conn, fact_id):
        return False
    return _lifecycle_metadata_allowed(row)


def _has_unresolved_contradiction(conn: sqlite3.Connection, fact_id: str) -> bool:
    rows = conn.execute(
        """
        SELECT CASE WHEN subject_fact_id = ? THEN object_fact_id ELSE subject_fact_id END AS other_fact_id
        FROM memory_graph_facts
        WHERE statement_kind = 'relation'
          AND relation_type = 'contradicts'
          AND status = 'active'
          AND (subject_fact_id = ? OR object_fact_id = ?)
        ORDER BY updated_at DESC, id DESC
        """,
        (fact_id, fact_id, fact_id),
    ).fetchall()
    for row in rows:
        other_id = str(row["other_fact_id"] or "")
        if not other_id:
            return True
        # A correction can leave a legacy active contradiction edge.  The
        # authoritative supersedes relation resolves that pair in favor of
        # the replacement and must not quarantine the current fact.
        if authority_superseded_by(conn, other_id) == fact_id:
            continue
        return True
    return False


def _entity_type_for_recall(conn: sqlite3.Connection, entity_id: object) -> str | None:
    if not entity_id:
        return None
    row = conn.execute(
        "SELECT entity_type FROM memory_entities "
        "WHERE id = ? AND status = 'active' AND risk_tier IN ('low', 'medium')",
        (str(entity_id),),
    ).fetchone()
    return str(row[0]) if row is not None else None


def _artifact_scope_allowed(
    conn: sqlite3.Connection,
    fact_id: str,
    vault_id: str | None,
) -> bool:
    if not _table_exists_for_recall(conn, "memory_fact_artifact_bindings"):
        return True
    active = conn.execute(
        "SELECT vault_id FROM memory_fact_artifact_bindings "
        "WHERE fact_id = ? AND status = 'active'",
        (fact_id,),
    ).fetchall()
    if not active:
        return True
    allowed = {None} if vault_id is None else {None, vault_id}
    return any(row[0] in allowed for row in active)


def _lifecycle_metadata_allowed(row: sqlite3.Row) -> bool:
    expires_at = row["expires_at"] if "expires_at" in row.keys() else None
    if expires_at:
        try:
            expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        if expires <= datetime.now(timezone.utc):
            return False
    raw_metadata = row["metadata_json"] if "metadata_json" in row.keys() else None
    if raw_metadata:
        try:
            metadata = json.loads(str(raw_metadata))
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(metadata, dict):
            return False
        if str(metadata.get("risk_tier") or "").casefold() in {"high", "sensitive"}:
            return False
        for key in ("sensitive", "conflicts", "uncertainties"):
            value = metadata.get(key)
            if value:
                return False
    return True


def _table_exists_for_recall(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _map_entity(row: sqlite3.Row) -> MemoryEntity:
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return MemoryEntity(
        id=str(row["id"]),
        entity_key=str(row["entity_key"]),
        lookup_fingerprint=str(row["lookup_fingerprint"]),
        entity_type=str(row["entity_type"]),
        canonical_name=str(row["canonical_name"]),
        normalized_name=str(row["normalized_name"]),
        status=str(row["status"]),
        risk_tier=str(row["risk_tier"]),
        confidence=float(row["confidence"]),
        metadata=metadata if isinstance(metadata, dict) else {},
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _map_alias(row: sqlite3.Row) -> EntityAlias:
    return EntityAlias(
        id=str(row["id"]),
        entity_id=str(row["entity_id"]),
        alias=str(row["alias"]),
        normalized_alias=str(row["normalized_alias"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
    )
