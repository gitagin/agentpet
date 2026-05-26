from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models.common import new_id
from app.services.memory_graph import MemoryFactCandidate, MemoryGraphStore
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso
from app.services.memory_policy import evaluate_memory_content


@dataclass(frozen=True, slots=True)
class CompanionConsolidationRunResult:
    run_id: str
    status: str
    source_count: int
    output_count: int
    skipped_count: int
    budget: dict[str, int]
    reason: str | None
    fact_ids: tuple[str, ...]
    started_at: str
    completed_at: str | None


class CompanionConsolidationService:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        vault_id: str,
        graph_store: MemoryGraphStore,
    ) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.vault_id = vault_id
        self.graph_store = graph_store

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def run_once(
        self,
        *,
        from_: str | None = None,
        to: str | None = None,
        limit: int = 50,
    ) -> CompanionConsolidationRunResult:
        started_at = utc_now_iso()
        existing = self._existing_run(from_=from_, to=to)
        if existing is not None:
            return self._run_result(existing["id"])

        run_id = new_id()
        normalized_limit = max(1, min(limit, 200))
        budget = {"source_limit": normalized_limit, "candidate_limit": normalized_limit}
        sources = self._source_rows(from_=from_, to=to, limit=normalized_limit)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO companion_consolidation_runs (
                    id, vault_id, status, window_started_at, window_ended_at,
                    source_count, output_count, skipped_count, reason,
                    budget_json, started_at, completed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 0, 0, 0, NULL, ?, ?, NULL, ?, ?)
                """,
                (
                    run_id,
                    self.vault_id,
                    "running",
                    from_,
                    to,
                    json.dumps(budget, sort_keys=True, separators=(",", ":")),
                    started_at,
                    started_at,
                    started_at,
                ),
            )

        fact_ids: list[str] = []
        skipped = 0
        for row in sources:
            self._record_source(run_id, row)
            candidate = _candidate_from_diary_row(row)
            if candidate is None:
                skipped += 1
                continue
            result = self.graph_store.insert_candidate(candidate, reason="companion_consolidation_v1")
            if result.inserted:
                fact_ids.append(result.fact.id)
                self._record_output(run_id, result.fact.id, result.reason)
            else:
                skipped += 1

        completed_at = utc_now_iso()
        status = "completed"
        reason = "no_active_diary_objects" if not sources else None
        with self.conn:
            self.conn.execute(
                """
                UPDATE companion_consolidation_runs
                SET status = ?,
                    source_count = ?,
                    output_count = ?,
                    skipped_count = ?,
                    reason = ?,
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, len(sources), len(fact_ids), skipped, reason, completed_at, completed_at, run_id),
            )
        return self._run_result(run_id)

    def list_runs(self, *, limit: int = 20) -> list[CompanionConsolidationRunResult]:
        rows = self.conn.execute(
            """
            SELECT id
            FROM companion_consolidation_runs
            WHERE vault_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (self.vault_id, max(1, min(limit, 100))),
        ).fetchall()
        return [self._run_result(row["id"]) for row in rows]

    def _existing_run(self, *, from_: str | None, to: str | None) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT id
            FROM companion_consolidation_runs
            WHERE vault_id = ?
              AND window_started_at IS ?
              AND window_ended_at IS ?
              AND status = 'completed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (self.vault_id, from_, to),
        ).fetchone()

    def _source_rows(self, *, from_: str | None, to: str | None, limit: int) -> list[sqlite3.Row]:
        clauses = ["vault_id = ?", "status = 'active'"]
        params: list[object] = [self.vault_id]
        if from_:
            clauses.append("occurred_at >= ?")
            params.append(from_)
        if to:
            clauses.append("occurred_at <= ?")
            params.append(to)
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM diary_memory_objects
            WHERE {' AND '.join(clauses)}
            ORDER BY importance DESC, confidence DESC, occurred_at DESC
            LIMIT ?
            """,
            (*params, max(1, min(limit, 200))),
        ).fetchall()
        return rows

    def _record_source(self, run_id: str, row: sqlite3.Row) -> None:
        source_hash = _hash_parts(row["id"], row["object_hash"], row["updated_at"])
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO companion_consolidation_run_sources (
                    run_id, source_type, source_id, source_hash, occurred_at, source_scope
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, "diary_memory_object", row["id"], source_hash, row["occurred_at"], "diary_objects"),
            )

    def _record_output(self, run_id: str, fact_id: str, reason: str | None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO companion_consolidation_run_outputs (
                    run_id, fact_id, output_type, status, reason
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, fact_id, "memory_graph_fact", "candidate", reason),
            )

    def _run_result(self, run_id: str) -> CompanionConsolidationRunResult:
        row = self.conn.execute(
            "SELECT * FROM companion_consolidation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        fact_rows = self.conn.execute(
            """
            SELECT fact_id
            FROM companion_consolidation_run_outputs
            WHERE run_id = ?
            ORDER BY fact_id
            """,
            (run_id,),
        ).fetchall()
        return CompanionConsolidationRunResult(
            run_id=row["id"],
            status=row["status"],
            source_count=int(row["source_count"]),
            output_count=int(row["output_count"]),
            skipped_count=int(row["skipped_count"]),
            budget={key: int(value) for key, value in _json_object(row["budget_json"]).items()},
            reason=row["reason"],
            fact_ids=tuple(str(item["fact_id"]) for item in fact_rows),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )


def _candidate_from_diary_row(row: sqlite3.Row) -> MemoryFactCandidate | None:
    people = _json_list(row["people_json"])
    keywords = _json_list(row["keywords_json"])
    topic = str(row["topic"] or "").strip()
    emotion = str(row["emotion"] or "").strip()
    summary = str(row["summary"] or "")
    if not evaluate_memory_content(" ".join([summary, topic, emotion, *people, *keywords])).allowed:
        return None
    source_hash = _hash_parts(row["id"], row["object_hash"], row["updated_at"])
    object_value = _compact(
        "; ".join(
            part
            for part in (
                f"topic={topic}" if topic else "",
                f"emotion={emotion}" if emotion else "",
                f"people_count={len(people)}",
                f"keyword_count={len(keywords)}",
            )
            if part
        )
        or str(row["type"] or "event"),
        240,
    )
    subject = "user"
    predicate = {
        "preference": "prefers",
        "fact": "has_context",
        "goal": "is_working_toward",
        "event": "experienced",
    }.get(str(row["type"]), "remembers")
    metadata = {
        "diary_object_id": row["id"],
        "diary_object_hash": row["object_hash"],
        "source_hash": source_hash,
        "source_scope": "diary_objects",
        "people_count": len(people),
        "keyword_count": len(keywords),
    }
    return MemoryFactCandidate(
        category="companion_memory",
        subject=subject,
        predicate=predicate,
        object=object_value,
        source_text=f"source_hash:{source_hash}",
        source_type="diary_memory_object",
        confidence=max(0.0, min(0.64, float(row["confidence"]))),
        memory_type=str(row["type"]),
        entity_type="episodic_summary",
        occurred_at=row["occurred_at"],
        metadata_json=json.dumps(metadata, sort_keys=True, separators=(",", ":")),
        importance=max(0.0, min(1.0, float(row["importance"]))),
    )


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _json_object(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _hash_parts(*values: object) -> str:
    joined = "\n".join(str(value or "") for value in values)
    return sha256_hex(joined)


def _compact(value: str, limit: int) -> str:
    compacted = " ".join(value.strip().split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(0, limit - 3)].rstrip() + "..."
