from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from apps.backend.tests._schema import migrate_db
from app.services.memory_candidates import MemoryCandidateStore
from app.services.memory_consolidation import MemoryConsolidationService, REDACTED_EVIDENCE
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, SourceTrack


def build_service(tmp_path: Path) -> tuple[MemoryConsolidationService, Path]:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    service = MemoryConsolidationService(
        MemoryCandidateStore(db_path),
        now_provider=lambda: datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    return service, db_path


def test_one_off_emotion_becomes_temporary_recent_state_not_durable_fact(tmp_path: Path) -> None:
    service, db_path = build_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="I feel anxious today because the release deadline is close.",
            assistant_answer="Let's keep the next step small.",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    item = result.items[0]
    assert item.candidate.memory_kind is MemoryKind.RECENT_STATE
    assert item.candidate.memory_scope is MemoryScope.TEMPORARY
    assert item.candidate.status is LifecycleStatus.CANDIDATE
    assert item.candidate.expires_at == "2026-05-22T12:00:00Z"
    assert item.candidate.metadata["recall_permissions"]["can_persist"] is False
    assert item.evidence is not None
    assert "anxious today" in item.evidence.source_excerpt

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_graph_facts").fetchone()[0] == 0


def test_repeated_stable_preference_stays_candidate_and_gains_confidence(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        first = service.consolidate(user_message="Please keep replies concise.", assistant_answer="Got it.")
        second = service.consolidate(user_message="Please keep replies concise.", assistant_answer="Still concise.")
    finally:
        service.close()

    first_candidate = first.items[0].candidate
    second_candidate = second.items[0].candidate
    assert second_candidate.id == first_candidate.id
    assert second_candidate.memory_kind is MemoryKind.PREFERENCE
    assert second_candidate.status is LifecycleStatus.CANDIDATE
    assert second_candidate.confidence > first_candidate.confidence
    assert second_candidate.evidence_count > first_candidate.evidence_count
    assert second_candidate.metadata["recall_permissions"]["can_proactively_mention"] is False


def test_assistant_personality_inference_is_downgraded_and_not_persistable(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="The deploy checklist slipped.",
            assistant_answer="The user is an anxious person, so I should be careful.",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    item = result.items[0]
    assert item.candidate.memory_kind is MemoryKind.INFERENCE
    assert item.candidate.source_track is SourceTrack.MODEL_EXTRACTED
    assert item.candidate.status is LifecycleStatus.CANDIDATE
    assert item.candidate.metadata["recall_permissions"]["can_persist"] is False
    assert item.candidate.metadata["requires_confirmation"] is True
    assert item.evidence is not None
    assert item.evidence.source_type == "assistant_inference"


def test_sensitive_content_records_rejected_redacted_safety_event(tmp_path: Path) -> None:
    service, db_path = build_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="Please remember this \u5bc6\u7801 for the service account.",
            assistant_answer="I cannot save credentials.",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    assert result.rejected_count == 1
    item = result.items[0]
    assert item.candidate.memory_scope is MemoryScope.SENSITIVE
    assert item.candidate.status is LifecycleStatus.REJECTED
    assert item.candidate.risk_tier.value == "high"
    assert item.evidence is not None
    assert item.evidence.source_excerpt == REDACTED_EVIDENCE
    assert item.lifecycle_event is not None
    assert item.lifecycle_event.to_status is LifecycleStatus.REJECTED

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        candidate = conn.execute("SELECT source_text FROM memory_candidates").fetchone()
        evidence = conn.execute("SELECT source_excerpt FROM memory_evidence").fetchone()
        assert candidate["source_text"] == ""
        assert evidence["source_excerpt"] == REDACTED_EVIDENCE
        assert conn.execute("SELECT COUNT(*) FROM memory_graph_facts").fetchone()[0] == 0


def test_explicit_remember_is_high_confidence_active_candidate_without_vault_write(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="Remember this: my favorite editor is VS Code.",
            assistant_answer="Saved as a candidate.",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    item = result.items[0]
    assert item.candidate.memory_kind is MemoryKind.PREFERENCE
    assert item.candidate.source_track is SourceTrack.EXPLICIT_USER
    assert item.candidate.status is LifecycleStatus.ACTIVE
    assert item.candidate.confidence >= 0.9
    assert item.candidate.metadata["recall_permissions"]["can_persist"] is True
    assert not (tmp_path / "Memories").exists()
