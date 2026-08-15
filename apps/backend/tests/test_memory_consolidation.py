from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.services.memory_candidates import MemoryCandidateStore
from app.services.memory_consolidation import MemoryConsolidationService, REDACTED_EVIDENCE
from app.services.memory_entity_graph import MemoryEntityGraphStore
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
    assert second_candidate.evidence_count == first_candidate.evidence_count
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


def test_explicit_remember_materializes_typed_graph_fact_and_replays(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    candidates = MemoryCandidateStore(db_path)
    service = MemoryConsolidationService(
        candidates,
        entity_graph=MemoryEntityGraphStore(candidates.conn),
    )
    try:
        first = service.consolidate(
            user_message="Remember this: my favorite editor is VS Code.",
        )
        second = service.consolidate(
            user_message="Remember this: my favorite editor is VS Code.",
        )
        assert first.items[0].graph_fact_id
        assert first.items[0].graph_status == "active"
        assert second.items[0].graph_fact_id == first.items[0].graph_fact_id
        fact = service.entity_graph.get(str(first.items[0].graph_fact_id))
        assert fact.status.value == "active"
        assert service.entity_graph.answerable_facts(query="editor")[0].object == "VS Code"
        row = candidates.conn.execute(
            "SELECT fact_id FROM memory_candidates WHERE id = ?",
            (first.items[0].candidate.id,),
        ).fetchone()
        assert row[0] == first.items[0].graph_fact_id
        assert candidates.conn.execute(
            "SELECT COUNT(*) FROM memory_graph_facts WHERE statement_kind = 'claim'"
        ).fetchone()[0] == 1
    finally:
        service.close()


@pytest.mark.parametrize(
    ("message", "expected_kind", "expected_subject", "expected_predicate", "expected_value"),
    (
        (
            "Remember this: my timezone = Asia/Shanghai.",
            MemoryKind.FACT,
            "自己",
            "timezone",
            "Asia/Shanghai",
        ),
        (
            "Please remember that I prefer keyboard navigation.",
            MemoryKind.PREFERENCE,
            "preference",
            "is",
            "keyboard navigation",
        ),
    ),
)
def test_explicit_fallback_parser_materializes_the_same_typed_claim(
    tmp_path: Path,
    message: str,
    expected_kind: MemoryKind,
    expected_subject: str,
    expected_predicate: str,
    expected_value: str,
) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    candidates = MemoryCandidateStore(db_path)
    service = MemoryConsolidationService(
        candidates,
        entity_graph=MemoryEntityGraphStore(candidates.conn),
    )
    try:
        result = service.consolidate(user_message=message)

        item = result.items[0]
        assert item.candidate.memory_kind is expected_kind
        assert item.candidate.status is LifecycleStatus.ACTIVE
        assert item.candidate.fact_id == item.graph_fact_id
        fact = service.entity_graph.get(str(item.graph_fact_id))
        assert (fact.subject, fact.predicate, fact.object) == (
            expected_subject,
            expected_predicate,
            expected_value,
        )
        assert [row.id for row in service.entity_graph.answerable_facts(query=expected_value)] == [fact.id]
    finally:
        service.close()


def test_chinese_compound_remember_creates_active_preference_candidate(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="明天下午三点提醒我给张老师回邮件，并记住我更喜欢下午开会。",
            assistant_answer="已创建提醒，并整理这条偏好。",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    item = result.items[0]
    assert item.candidate.memory_kind is MemoryKind.PREFERENCE
    assert item.candidate.source_track is SourceTrack.EXPLICIT_USER
    assert item.candidate.status is LifecycleStatus.ACTIVE
    assert "下午开会" in item.candidate.summary
    assert item.candidate.metadata["recall_permissions"]["can_persist"] is True


@pytest.mark.parametrize(
    "message",
    (
        "请记得我更喜欢下午开会",
        "请帮我记住我更喜欢下午开会",
        "I want you to remember that I prefer afternoon meetings.",
        "Could you please remember that I prefer afternoon meetings?",
        "Could you remember that I prefer afternoon meetings?",
    ),
)
def test_polite_remember_command_creates_active_preference_candidate(tmp_path: Path, message: str) -> None:
    service, _ = build_service(tmp_path)
    try:
        result = service.consolidate(
            user_message=message,
            assistant_answer="已按当前策略整理这条偏好。",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    item = result.items[0]
    assert item.candidate.memory_kind is MemoryKind.PREFERENCE
    assert item.candidate.source_track is SourceTrack.EXPLICIT_USER
    assert item.candidate.status is LifecycleStatus.ACTIVE
    assert "afternoon meetings" in item.candidate.normalized_value or "下午开会" in item.candidate.normalized_value
    assert item.candidate.confidence >= 0.9
    assert item.candidate.metadata["recall_permissions"]["can_persist"] is True


def test_chinese_recall_questions_are_not_promoted_to_explicit_memory(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        results = [
            service.consolidate(
                user_message=message,
                assistant_answer="我会先查本地记录再回答。",
            )
            for message in (
                "你还记得我更喜欢下午开会",
                "你记得我更喜欢下午开会吗？",
            )
        ]
    finally:
        service.close()

    assert all(result.candidate_count == 0 for result in results)
    assert all(result.skipped_reason == "no_signal" for result in results)


@pytest.mark.parametrize(
    "message",
    (
        "Do you remember that I prefer afternoon meetings?",
        "Do you still remember that I prefer afternoon meetings?",
        "What do you remember? I prefer afternoon meetings.",
    ),
)
def test_english_recall_question_is_not_promoted_to_memory(tmp_path: Path, message: str) -> None:
    service, _ = build_service(tmp_path)
    try:
        result = service.consolidate(
            user_message=message,
            assistant_answer="I will search local records before answering.",
        )
    finally:
        service.close()

    assert result.candidate_count == 0
    assert result.skipped_reason == "no_signal"
