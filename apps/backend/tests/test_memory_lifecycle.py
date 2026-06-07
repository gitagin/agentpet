from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.models.enums import MemoryFactStatus
from app.services.memory_candidates import MemoryCandidateCreate
from app.services.memory_graph import MemoryFactCandidate, facts_to_context_lines
from app.services.memory_lifecycle import MemoryLifecycleService, MemoryLifecycleTransitionError
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack


def build_service(tmp_path: Path) -> tuple[MemoryLifecycleService, Path]:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    return MemoryLifecycleService(db_path), db_path


def create_candidate(
    service: MemoryLifecycleService,
    *,
    kind: MemoryKind,
    summary: str,
    normalized_value: str,
    status: LifecycleStatus,
    scope: MemoryScope = MemoryScope.GLOBAL,
) -> str:
    return service.candidates.create_candidate(
        MemoryCandidateCreate(
            memory_kind=kind,
            memory_scope=scope,
            summary=summary,
            normalized_value=normalized_value,
            source_text=summary,
            source_track=SourceTrack.SLOW_CONSOLIDATION,
            risk_tier=RiskTier.LOW,
            confidence=0.8,
            importance=0.7,
            status=status,
        )
    ).id


def test_candidate_state_machine_allows_required_paths_and_rejects_invalid(tmp_path: Path) -> None:
    service, db_path = build_service(tmp_path)
    try:
        candidate_id = create_candidate(
            service,
            kind=MemoryKind.PREFERENCE,
            summary="User prefers concise answers.",
            normalized_value="preference:concise",
            status=LifecycleStatus.CANDIDATE,
        )

        activated = service.transition_candidate(candidate_id, LifecycleStatus.ACTIVE, reason="user_kept")
        stale = service.transition_candidate(candidate_id, LifecycleStatus.STALE, reason="old_preference_review")
        active_again = service.transition_candidate(candidate_id, LifecycleStatus.ACTIVE, reason="user_confirmed_again")
        forgotten = service.transition_candidate(candidate_id, LifecycleStatus.FORGOTTEN, reason="user_forget")

        assert activated.from_status is LifecycleStatus.CANDIDATE
        assert stale.from_status is LifecycleStatus.ACTIVE
        assert active_again.from_status is LifecycleStatus.STALE
        assert forgotten.to_status is LifecycleStatus.FORGOTTEN
        with pytest.raises(MemoryLifecycleTransitionError, match="invalid_lifecycle_transition"):
            service.transition_candidate(candidate_id, LifecycleStatus.ACTIVE, reason="cannot_restore_forgotten")
    finally:
        service.close()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT from_status, to_status, reason FROM memory_lifecycle_events WHERE candidate_id = ? ORDER BY created_at",
            (candidate_id,),
        ).fetchall()
    assert [row[1] for row in rows] == ["active", "stale", "active", "forgotten"]


def test_completed_project_candidate_is_archived_not_current(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        project_id = create_candidate(
            service,
            kind=MemoryKind.PROJECT_CONTEXT,
            scope=MemoryScope.PROJECT,
            summary="User is working on Project Atlas.",
            normalized_value="project:atlas",
            status=LifecycleStatus.ACTIVE,
        )

        completed = service.mark_candidate_completed(project_id)

        assert completed.status is LifecycleStatus.ARCHIVED
        assert service.candidates.list_candidates(status=LifecycleStatus.ACTIVE, memory_kind=MemoryKind.PROJECT_CONTEXT) == []
    finally:
        service.close()


def test_new_related_project_supersedes_old_project_without_deleting_history(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        old_id = create_candidate(
            service,
            kind=MemoryKind.PROJECT_CONTEXT,
            scope=MemoryScope.PROJECT,
            summary="User is working on Project Atlas.",
            normalized_value="project:atlas",
            status=LifecycleStatus.ACTIVE,
        )
        replacement_id = create_candidate(
            service,
            kind=MemoryKind.PROJECT_CONTEXT,
            scope=MemoryScope.PROJECT,
            summary="User is now working on Project Borealis.",
            normalized_value="project:borealis",
            status=LifecycleStatus.CANDIDATE,
        )

        old, replacement = service.supersede_candidate(old_id, replacement_id)

        assert old.status is LifecycleStatus.SUPERSEDED
        assert old.superseded_by == replacement.id
        assert replacement.status is LifecycleStatus.ACTIVE
    finally:
        service.close()


def test_user_boundary_is_not_superseded_by_ordinary_preference(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        boundary_id = create_candidate(
            service,
            kind=MemoryKind.BOUNDARY,
            summary="User does not want nagging.",
            normalized_value="boundary:do_not_nag",
            status=LifecycleStatus.ACTIVE,
        )
        preference_id = create_candidate(
            service,
            kind=MemoryKind.PREFERENCE,
            summary="User likes proactive reminders.",
            normalized_value="preference:proactive_reminders",
            status=LifecycleStatus.ACTIVE,
        )

        with pytest.raises(MemoryLifecycleTransitionError, match="boundary_memory_requires_explicit_boundary_override"):
            service.supersede_candidate(boundary_id, preference_id)

        assert service.candidates.get_candidate(boundary_id).status is LifecycleStatus.ACTIVE
    finally:
        service.close()


def test_graph_fact_lifecycle_events_and_superseded_metadata(tmp_path: Path) -> None:
    service, db_path = build_service(tmp_path)
    try:
        old = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category="project_context",
                memory_type="project_context",
                subject="current project",
                predicate="is",
                object="Atlas",
                source_text="I am working on Project Atlas.",
                confidence=0.9,
            )
        ).fact
        replacement = service.graph.insert_candidate(
            MemoryFactCandidate(
                category="project_context",
                memory_type="project_context",
                subject="current project",
                predicate="is",
                object="Borealis",
                source_text="I am now working on Project Borealis.",
                confidence=0.8,
            )
        ).fact

        stale = service.transition_fact(old.id, LifecycleStatus.STALE, reason="project_has_not_appeared_recently")
        reactivated = service.transition_fact(old.id, LifecycleStatus.ACTIVE, reason="user_reopened_project")
        old_after, replacement_after = service.supersede_fact(old.id, replacement.id)
        completed_fact = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category="project_context",
                memory_type="project_context",
                subject="side project",
                predicate="is",
                object="Done",
                source_text="The side project is completed.",
                confidence=0.9,
            )
        ).fact
        completed = service.mark_fact_completed(completed_fact.id)

        assert stale.to_status is LifecycleStatus.STALE
        assert completed.status is MemoryFactStatus.ARCHIVED
        assert reactivated.to_status is LifecycleStatus.ACTIVE
        assert old_after.status is MemoryFactStatus.SUPERSEDED
        assert old_after.superseded_by == replacement.id
        assert replacement_after.status is MemoryFactStatus.ACTIVE
        assert facts_to_context_lines([old_after]) == []
        assert [fact.id for fact in service.graph.search_active("current project")] == [replacement.id]
    finally:
        service.close()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT fact_id, from_status, to_status, metadata_json FROM memory_lifecycle_events WHERE fact_id = ? ORDER BY created_at",
            (old.id,),
        ).fetchall()
    assert [row["to_status"] for row in rows] == ["stale", "active", "superseded"]
    assert json.loads(rows[-1]["metadata_json"]) == {"superseded_by": replacement.id}
