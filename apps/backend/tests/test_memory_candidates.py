from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.services.memory_candidates import (
    MemoryActivationEventCreate,
    MemoryCandidateCreate,
    MemoryCandidateStore,
    MemoryEvidenceCreate,
    MemoryFeedbackEventCreate,
)
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RecallPermissions, RiskTier, SourceTrack


def test_memory_candidate_store_records_candidate_evidence_and_events(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryCandidateStore(db_path)
    try:
        candidate = store.create_candidate(
            MemoryCandidateCreate(
                memory_kind=MemoryKind.PREFERENCE,
                memory_scope=MemoryScope.GLOBAL,
                summary="User prefers concise implementation notes.",
                normalized_value="answer_style=concise",
                source_text="Please keep implementation notes concise.",
                source_track=SourceTrack.EXPLICIT_USER,
                risk_tier=RiskTier.LOW,
                confidence=0.95,
                importance=0.8,
                status=LifecycleStatus.ACTIVE,
                metadata={"source": "unit-test"},
            )
        )
        duplicate = store.create_candidate(
            MemoryCandidateCreate(
                memory_kind="preference",
                memory_scope="global",
                summary="User prefers concise implementation notes.",
                normalized_value="answer_style=concise",
                source_text="Please keep implementation notes concise.",
                source_track="explicit_user",
                risk_tier="low",
                confidence=0.9,
                importance=0.6,
                status="active",
            )
        )
        evidence = store.add_evidence(
            MemoryEvidenceCreate(
                candidate_id=candidate.id,
                source_type="chat_message",
                source_text="Please keep implementation notes concise.",
                source_excerpt="keep implementation notes concise",
                confidence=0.95,
                metadata={"message_role": "user"},
            )
        )
        transition = store.transition(
            candidate_id=candidate.id,
            to_status=LifecycleStatus.STALE,
            reason="project completed",
            metadata={"trigger": "unit-test"},
        )
        activation_id = store.record_activation(
            MemoryActivationEventCreate(
                candidate_id=candidate.id,
                activation_score=0.72,
                permissions=RecallPermissions(can_answer_context=True, can_persist=True),
                score_breakdown={"confidence": 0.95, "scope": 0.8},
                used_for_answer_context=True,
            )
        )
        feedback_id = store.record_feedback(
            MemoryFeedbackEventCreate(
                candidate_id=candidate.id,
                feedback_type="mark_stale",
                feedback_text="That project is done.",
                requested_status=LifecycleStatus.STALE,
                metadata={"surface": "unit-test"},
            )
        )

        refreshed = store.get_candidate(candidate.id)
    finally:
        store.close()

    assert duplicate.id == candidate.id
    assert duplicate.evidence_count == 2
    assert evidence.candidate_id == candidate.id
    assert evidence.source_excerpt == "keep implementation notes concise"
    assert transition.from_status is LifecycleStatus.ACTIVE
    assert transition.to_status is LifecycleStatus.STALE
    assert refreshed.status is LifecycleStatus.STALE
    assert refreshed.evidence_count == 3
    assert refreshed.metadata == {"source": "unit-test"}

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        activation = conn.execute(
            "SELECT * FROM memory_activation_events WHERE id = ?",
            (activation_id,),
        ).fetchone()
        feedback = conn.execute(
            "SELECT * FROM memory_feedback_events WHERE id = ?",
            (feedback_id,),
        ).fetchone()

    assert activation["used_for_answer_context"] == 1
    assert json.loads(activation["permissions_json"]) == {
        "can_answer_context": True,
        "can_persist": True,
        "can_proactively_mention": False,
        "can_style_response": False,
        "can_suggest_action": False,
    }
    assert feedback["feedback_type"] == "mark_stale"
    assert feedback["requested_status"] == "stale"


def test_memory_candidate_store_requires_candidate_or_fact_for_events(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryCandidateStore(db_path)
    try:
        with pytest.raises(ValueError, match="candidate_id_or_fact_id_required"):
            store.add_evidence(MemoryEvidenceCreate())
        with pytest.raises(ValueError, match="candidate_id_or_fact_id_required"):
            store.transition(to_status=LifecycleStatus.REJECTED)
        with pytest.raises(ValueError, match="candidate_id_or_fact_id_required"):
            store.record_feedback(MemoryFeedbackEventCreate())
    finally:
        store.close()
