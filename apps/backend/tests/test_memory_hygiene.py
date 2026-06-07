from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.models.enums import MemoryFactStatus
from app.services.memory_candidates import MemoryCandidateCreate, MemoryEvidenceCreate
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_hygiene import MemoryHygieneService
from app.services.memory_policy import MemoryPolicyDecision
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack


NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


def build_service(tmp_path: Path) -> tuple[MemoryHygieneService, Path]:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    return MemoryHygieneService(db_path, now_provider=lambda: NOW), db_path


def create_candidate(
    service: MemoryHygieneService,
    *,
    summary: str,
    normalized_value: str | None = None,
    kind: MemoryKind = MemoryKind.PREFERENCE,
    scope: MemoryScope = MemoryScope.GLOBAL,
    status: LifecycleStatus = LifecycleStatus.CANDIDATE,
    confidence: float = 0.8,
    expires_at: str | None = None,
) -> str:
    return service.lifecycle.candidates.create_candidate(
        MemoryCandidateCreate(
            memory_kind=kind,
            memory_scope=scope,
            summary=summary,
            normalized_value=normalized_value or summary.casefold(),
            source_text=f"source: {summary}",
            source_track=SourceTrack.SLOW_CONSOLIDATION,
            risk_tier=RiskTier.LOW,
            confidence=confidence,
            importance=0.6,
            status=status,
            expires_at=expires_at,
        )
    ).id


def set_candidate_updated_at(db_path: Path, candidate_id: str, updated_at: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE memory_candidates SET updated_at = ? WHERE id = ?", (updated_at, candidate_id))


def set_fact_values(db_path: Path, fact_id: str, *, confidence: float, updated_at: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE memory_graph_facts SET confidence = ?, updated_at = ? WHERE id = ?",
            (confidence, updated_at, fact_id),
        )


def insert_chat_source(db_path: Path) -> None:
    now = "2026-06-01T00:00:00Z"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("conv-hygiene-1", "Hygiene source", "active", now, now),
        )
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("msg-hygiene-1", "conv-hygiene-1", "user", "raw chat log must remain", "completed", now, now),
        )


def test_hygiene_archives_expired_recent_state_and_preserves_sources(tmp_path: Path) -> None:
    service, db_path = build_service(tmp_path)
    vault_file = tmp_path / "Vault" / "Original.md"
    vault_file.parent.mkdir()
    vault_file.write_text("# Original\n\nDo not rewrite me.\n", encoding="utf-8")
    insert_chat_source(db_path)
    try:
        candidate_id = create_candidate(
            service,
            summary="Temporary focus mode for today.",
            kind=MemoryKind.RECENT_STATE,
            scope=MemoryScope.TEMPORARY,
            status=LifecycleStatus.ACTIVE,
            expires_at="2026-06-01T00:00:00Z",
        )
        fact = service.lifecycle.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.RECENT_STATE.value,
                memory_type=MemoryKind.RECENT_STATE.value,
                subject="current focus mode",
                predicate="is",
                object="temporary",
                source_text="Current focus mode is temporary.",
                confidence=0.9,
                expires_at="2026-06-01T00:00:00Z",
            )
        ).fact

        result = service.run()
    finally:
        service.close()

    assert result.count("archive_expired_recent_state") == 2
    with sqlite3.connect(db_path) as conn:
        candidate_status = conn.execute("SELECT status FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()[0]
        fact_status = conn.execute("SELECT status FROM memory_graph_facts WHERE id = ?", (fact.id,)).fetchone()[0]
        lifecycle_count = conn.execute(
            "SELECT COUNT(*) FROM memory_lifecycle_events WHERE to_status = 'archived'"
        ).fetchone()[0]
        message = conn.execute("SELECT content FROM messages WHERE id = 'msg-hygiene-1'").fetchone()[0]
    assert candidate_status == "archived"
    assert fact_status == "archived"
    assert lifecycle_count == 2
    assert message == "raw chat log must remain"
    assert vault_file.read_text(encoding="utf-8") == "# Original\n\nDo not rewrite me.\n"


def test_hygiene_rejects_stale_low_confidence_and_policy_blocked_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import memory_hygiene

    service, db_path = build_service(tmp_path)
    monkeypatch.setattr(
        memory_hygiene,
        "evaluate_memory_content",
        lambda content: MemoryPolicyDecision(allowed="policy blocked" not in content, reason="unit_policy"),
    )
    try:
        stale_id = create_candidate(
            service,
            summary="Maybe the user likes noisy updates.",
            confidence=0.3,
        )
        policy_id = create_candidate(
            service,
            summary="policy blocked candidate",
            status=LifecycleStatus.ACTIVE,
            confidence=0.9,
        )
        set_candidate_updated_at(db_path, stale_id, "2026-04-01T00:00:00Z")

        result = service.run(stale_candidate_before="2026-05-01T00:00:00Z")
    finally:
        service.close()

    assert result.count("reject_sensitive_candidate") == 1
    assert result.count("reject_stale_low_confidence_candidate") == 1
    with sqlite3.connect(db_path) as conn:
        statuses = dict(conn.execute("SELECT id, status FROM memory_candidates").fetchall())
        reasons = [
            row[0]
            for row in conn.execute(
                "SELECT reason FROM memory_lifecycle_events WHERE to_status = 'rejected' ORDER BY created_at"
            ).fetchall()
        ]
    assert statuses[stale_id] == "rejected"
    assert statuses[policy_id] == "rejected"
    assert "hygiene_stale_low_confidence_candidate" in reasons
    assert "hygiene_policy_rejected:unit_policy" in reasons


def test_hygiene_merges_duplicate_candidates_without_deleting_evidence(tmp_path: Path) -> None:
    service, db_path = build_service(tmp_path)
    try:
        keeper_id = create_candidate(
            service,
            summary="User prefers concise replies.",
            normalized_value="reply_style=concise",
            status=LifecycleStatus.ACTIVE,
            confidence=0.9,
        )
        duplicate_id = service.lifecycle.candidates.create_candidate(
            MemoryCandidateCreate(
                memory_kind=MemoryKind.PREFERENCE,
                memory_scope=MemoryScope.GLOBAL,
                summary="Use concise replies for the user.",
                normalized_value="reply_style=concise",
                source_text="Another source says concise replies.",
                source_track=SourceTrack.SLOW_CONSOLIDATION,
                risk_tier=RiskTier.LOW,
                confidence=0.7,
                importance=0.8,
                status=LifecycleStatus.CANDIDATE,
            )
        ).id
        service.lifecycle.candidates.add_evidence(
            MemoryEvidenceCreate(
                candidate_id=duplicate_id,
                source_type="chat_message",
                source_text="Please stay concise.",
                source_excerpt="Please stay concise.",
                confidence=0.8,
            )
        )

        result = service.run()
    finally:
        service.close()

    assert result.count("merge_duplicate_candidate") == 1
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        keeper = conn.execute("SELECT evidence_count, confidence, importance FROM memory_candidates WHERE id = ?", (keeper_id,)).fetchone()
        duplicate = conn.execute("SELECT status, superseded_by FROM memory_candidates WHERE id = ?", (duplicate_id,)).fetchone()
        evidence_owner = conn.execute("SELECT candidate_id FROM memory_evidence").fetchone()[0]
        lifecycle = conn.execute(
            "SELECT to_status, metadata_json FROM memory_lifecycle_events WHERE candidate_id = ?",
            (duplicate_id,),
        ).fetchone()
    assert keeper["evidence_count"] == 3
    assert keeper["confidence"] == 0.9
    assert keeper["importance"] == 0.8
    assert duplicate["status"] == "superseded"
    assert duplicate["superseded_by"] == keeper_id
    assert evidence_owner == keeper_id
    assert lifecycle["to_status"] == "superseded"
    assert json.loads(lifecycle["metadata_json"])["superseded_by"] == keeper_id


def test_hygiene_supersedes_weaker_old_conflicting_fact(tmp_path: Path) -> None:
    service, db_path = build_service(tmp_path)
    try:
        old = service.lifecycle.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PREFERENCE.value,
                memory_type=MemoryKind.PREFERENCE.value,
                subject="preferred snack",
                predicate="is",
                object="mango",
                source_text="Preferred snack is mango.",
                confidence=0.8,
            )
        ).fact
        newer = service.lifecycle.graph.insert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PREFERENCE.value,
                memory_type=MemoryKind.PREFERENCE.value,
                subject="preferred snack",
                predicate="is",
                object="pear",
                source_text="Preferred snack is pear.",
                confidence=0.95,
            )
        ).fact
        service.lifecycle.graph.update_status(newer.id, MemoryFactStatus.ACTIVE, reason="test_stronger_fact")
        set_fact_values(db_path, old.id, confidence=0.55, updated_at="2026-05-01T00:00:00Z")
        set_fact_values(db_path, newer.id, confidence=0.95, updated_at="2026-06-01T00:00:00Z")

        result = service.run()
    finally:
        service.close()

    assert result.count("supersede_conflicting_fact") == 1
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        old_row = conn.execute("SELECT status, metadata_json FROM memory_graph_facts WHERE id = ?", (old.id,)).fetchone()
        active_objects = [
            row[0]
            for row in conn.execute(
                "SELECT object FROM memory_graph_facts WHERE status = 'active' AND subject = 'preferred snack'"
            ).fetchall()
        ]
        lifecycle = conn.execute(
            "SELECT to_status, metadata_json FROM memory_lifecycle_events WHERE fact_id = ? ORDER BY created_at DESC LIMIT 1",
            (old.id,),
        ).fetchone()
    assert old_row["status"] == "superseded"
    assert json.loads(old_row["metadata_json"])["superseded_by"] == newer.id
    assert active_objects == ["pear"]
    assert lifecycle["to_status"] == "superseded"
    assert json.loads(lifecycle["metadata_json"])["superseded_by"] == newer.id
