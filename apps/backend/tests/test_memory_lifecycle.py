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


def test_graph_fact_lifecycle_events_and_authority_supersedes_relation(tmp_path: Path) -> None:
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
        relation = conn.execute(
            """
            SELECT subject_fact_id
            FROM memory_graph_facts
            WHERE statement_kind = 'relation'
              AND relation_type = 'supersedes'
              AND object_fact_id = ?
              AND status = 'active'
            """,
            (old.id,),
        ).fetchone()
    assert [row["to_status"] for row in rows] == ["stale", "active", "superseded"]
    assert relation["subject_fact_id"] == replacement.id
    assert json.loads(rows[-1]["metadata_json"]) == {"replacement_fact_id": replacement.id}


def test_forgetting_fact_revokes_wiki_references_and_preserves_semantic_relations(
    tmp_path: Path,
) -> None:
    service, _ = build_service(tmp_path)
    try:
        preference = service.graph.create_entity(
            entity_type="preference",
            canonical_name="preferred editor",
        )
        source = service.graph.create_entity(
            entity_type="source",
            canonical_name="Editor preference source",
        )
        page = service.graph.create_entity(
            entity_type="wiki_page",
            canonical_name="Editor preference",
        )
        fact = service.graph.create_claim(
            subject_entity_id=preference.id,
            predicate="is",
            literal_value="JetBrains",
            category="preference",
            source_text="My preferred editor is JetBrains.",
            source_type="explicit_user",
            evidence_id="evidence-editor-jetbrains",
        )
        conflicting_fact = service.graph.create_claim(
            subject_entity_id=preference.id,
            predicate="is",
            literal_value="VS Code",
            category="preference",
            source_text="An older source says VS Code.",
            source_type="explicit_user",
            evidence_id="evidence-editor-vscode",
        )
        historical_fact = service.graph.create_claim(
            subject_entity_id=preference.id,
            predicate="was",
            literal_value="Vim",
            category="preference",
            source_text="The historical editor was Vim.",
            source_type="explicit_user",
            evidence_id="evidence-editor-vim",
        )
        documented_in = service.graph.create_relation(
            relation_type="documented_in",
            subject_fact_id=fact.id,
            object_entity_id=page.id,
            source_text="The Wiki page documents the editor preference.",
            source_type="wiki_binding",
            evidence_id="evidence-editor-documented-in",
        )
        supports = service.graph.create_relation(
            relation_type="supports",
            subject_entity_id=source.id,
            object_fact_id=fact.id,
            source_text="The source supports the editor preference.",
            source_type="wiki_binding",
            evidence_id="evidence-editor-supports",
        )
        contradicts = service.graph.create_relation(
            relation_type="contradicts",
            subject_fact_id=conflicting_fact.id,
            object_fact_id=fact.id,
            source_text="The editor claims conflict.",
            source_type="explicit_user",
            evidence_id="evidence-editor-contradicts",
        )
        supersedes = service.graph.create_relation(
            relation_type="supersedes",
            subject_fact_id=fact.id,
            object_fact_id=historical_fact.id,
            source_text="The current editor replaces the historical editor.",
            source_type="explicit_user",
            evidence_id="evidence-editor-supersedes",
        )
        source_binding_id = service.graph.bind_artifact(
            fact_id=fact.id,
            vault_id=None,
            artifact_type="source",
            artifact_ref="Wiki/Sources/Editor-preference.md",
        )
        page_binding_id = service.graph.bind_artifact(
            fact_id=fact.id,
            vault_id=None,
            artifact_type="wiki_page",
            artifact_ref="Wiki/Preferences/Editor.md",
        )

        service.transition_fact(
            fact.id,
            LifecycleStatus.FORGOTTEN,
            reason="user_forget_wiki_fact",
        )

        relation_rows = service.conn.execute(
            "SELECT id, relation_type, status FROM memory_graph_facts WHERE id IN (?, ?, ?, ?) ORDER BY id",
            (documented_in.id, supports.id, contradicts.id, supersedes.id),
        ).fetchall()
        relation_statuses = {
            str(row["id"]): (str(row["relation_type"]), str(row["status"]))
            for row in relation_rows
        }
        binding_rows = service.conn.execute(
            "SELECT id, status FROM memory_fact_artifact_bindings WHERE id IN (?, ?) ORDER BY id",
            (source_binding_id, page_binding_id),
        ).fetchall()
        documented_events = service.conn.execute(
            """
            SELECT from_status, to_status, reason
            FROM memory_lifecycle_events
            WHERE fact_id = ?
            ORDER BY created_at, id
            """,
            (documented_in.id,),
        ).fetchall()

        assert service.graph.get(fact.id).status is MemoryFactStatus.FORGOTTEN
        assert relation_statuses[documented_in.id] == ("documented_in", "archived")
        assert relation_statuses[supports.id] == ("supports", "active")
        assert relation_statuses[contradicts.id] == ("contradicts", "active")
        assert relation_statuses[supersedes.id] == ("supersedes", "active")
        assert {str(row["id"]): str(row["status"]) for row in binding_rows} == {
            source_binding_id: "revoked",
            page_binding_id: "revoked",
        }
        assert [tuple(row) for row in documented_events] == [
            ("active", "archived", "user_forget_wiki_fact")
        ]
    finally:
        service.close()


def test_superseding_fact_revokes_wiki_references_without_removing_history(
    tmp_path: Path,
) -> None:
    service, _ = build_service(tmp_path)
    try:
        preference = service.graph.create_entity(
            entity_type="preference",
            canonical_name="preferred editor",
        )
        page = service.graph.create_entity(
            entity_type="wiki_page",
            canonical_name="Editor preference",
        )
        old_fact = service.graph.create_claim(
            subject_entity_id=preference.id,
            predicate="is",
            literal_value="VS Code",
            category="preference",
            source_text="My preferred editor was VS Code.",
            source_type="explicit_user",
            evidence_id="evidence-superseded-editor-old",
        )
        replacement = service.graph.create_claim(
            subject_entity_id=preference.id,
            predicate="is",
            literal_value="JetBrains",
            category="preference",
            source_text="My preferred editor is now JetBrains.",
            source_type="explicit_user",
            evidence_id="evidence-superseded-editor-new",
        )
        documented_in = service.graph.create_relation(
            relation_type="documented_in",
            subject_fact_id=old_fact.id,
            object_entity_id=page.id,
            source_text="The Wiki page documents the old editor preference.",
            source_type="wiki_binding",
            evidence_id="evidence-superseded-editor-page",
        )
        binding_id = service.graph.bind_artifact(
            fact_id=old_fact.id,
            vault_id=None,
            artifact_type="wiki_page",
            artifact_ref="Wiki/Preferences/Editor.md",
        )

        old_after, replacement_after = service.supersede_fact(
            old_fact.id,
            replacement.id,
            reason="user_corrected_editor",
            allow_boundary_override=True,
        )

        documented_row = service.conn.execute(
            "SELECT id, status FROM memory_graph_facts WHERE id = ?",
            (documented_in.id,),
        ).fetchone()
        binding_row = service.conn.execute(
            "SELECT id, status FROM memory_fact_artifact_bindings WHERE id = ?",
            (binding_id,),
        ).fetchone()
        supersedes_rows = service.conn.execute(
            """
            SELECT id, status
            FROM memory_graph_facts
            WHERE statement_kind = 'relation'
              AND relation_type = 'supersedes'
              AND subject_fact_id = ?
              AND object_fact_id = ?
            """,
            (replacement.id, old_fact.id),
        ).fetchall()

        assert old_after.status is MemoryFactStatus.SUPERSEDED
        assert replacement_after.status is MemoryFactStatus.ACTIVE
        assert tuple(documented_row) == (documented_in.id, "archived")
        assert tuple(binding_row) == (binding_id, "revoked")
        assert len(supersedes_rows) == 1
        assert str(supersedes_rows[0]["status"]) == "active"
    finally:
        service.close()


def test_editing_linked_candidate_supersedes_fact_and_forget_revokes_replacement(
    tmp_path: Path,
) -> None:
    service, db_path = build_service(tmp_path)
    try:
        entity = service.graph.create_entity(
            entity_type="preference",
            canonical_name="editor",
            confidence=0.96,
        )
        old_fact = service.graph.create_claim(
            subject_entity_id=entity.id,
            predicate="is",
            literal_value="VS Code",
            category="preference",
            source_text="Remember this: my favorite editor is VS Code.",
            source_type="explicit_user",
            confidence=0.96,
            evidence_id="evidence-linked-candidate-old",
        )
        old_candidate_id = create_candidate(
            service,
            kind=MemoryKind.PREFERENCE,
            summary="User preference for editor: VS Code.",
            normalized_value="preference:editor=vs code",
            status=LifecycleStatus.ACTIVE,
        )
        service.candidates.attach_fact(old_candidate_id, old_fact.id)

        corrected = service.apply_feedback(
            target_type="candidate",
            target_id=old_candidate_id,
            operation="edit",
            feedback_text="I switched to JetBrains.",
            replacement_object="JetBrains",
        )
        assert corrected.replacement_target_id
        replacement_candidate = service.candidates.get_candidate(
            str(corrected.replacement_target_id)
        )
        assert replacement_candidate.fact_id
        replacement_fact_id = str(replacement_candidate.fact_id)
        assert service.graph.get(old_fact.id).status is MemoryFactStatus.SUPERSEDED
        assert service.graph.get(replacement_fact_id).status is MemoryFactStatus.ACTIVE
        assert service.graph.answerable_facts(query="VS Code") == []
        assert [fact.id for fact in service.graph.answerable_facts(query="JetBrains")] == [
            replacement_fact_id
        ]
        event_count_before_replay = service.conn.execute(
            """
            SELECT COUNT(*) FROM memory_lifecycle_events
            WHERE (candidate_id = ? OR fact_id = ?) AND to_status = 'superseded'
            """,
            (old_candidate_id, old_fact.id),
        ).fetchone()[0]
        replayed_old, replayed_replacement = service.supersede_candidate(
            old_candidate_id,
            replacement_candidate.id,
            reason="user_edited_memory",
            allow_boundary_override=True,
        )
        assert replayed_old.status is LifecycleStatus.SUPERSEDED
        assert replayed_replacement.id == replacement_candidate.id
        assert service.conn.execute(
            """
            SELECT COUNT(*) FROM memory_lifecycle_events
            WHERE (candidate_id = ? OR fact_id = ?) AND to_status = 'superseded'
            """,
            (old_candidate_id, old_fact.id),
        ).fetchone()[0] == event_count_before_replay

        forgotten = service.apply_feedback(
            target_type="candidate",
            target_id=replacement_candidate.id,
            operation="forget",
            feedback_text="Forget this editor preference.",
        )
        assert forgotten.status is LifecycleStatus.FORGOTTEN
        assert service.graph.get(replacement_fact_id).status is MemoryFactStatus.FORGOTTEN
        assert service.graph.answerable_facts(query="JetBrains") == []
    finally:
        service.close()

    with sqlite3.connect(db_path) as conn:
        relation_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM memory_graph_facts
            WHERE statement_kind = 'relation'
              AND relation_type = 'supersedes'
              AND object_fact_id = ?
            """,
            (old_fact.id,),
        ).fetchone()[0]
    assert relation_count == 1


def test_editing_fact_target_replaces_and_forgets_linked_candidate(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    try:
        entity = service.graph.create_entity(
            entity_type="preference",
            canonical_name="editor",
            confidence=0.96,
        )
        old_fact = service.graph.create_claim(
            subject_entity_id=entity.id,
            predicate="is",
            literal_value="VS Code",
            category="preference",
            source_text="Remember this: my preferred editor is VS Code.",
            source_type="explicit_user",
            confidence=0.96,
            evidence_id="evidence-fact-target-candidate-old",
        )
        old_candidate_id = create_candidate(
            service,
            kind=MemoryKind.PREFERENCE,
            summary="User preference for editor: VS Code.",
            normalized_value="preference:editor=vs code",
            status=LifecycleStatus.ACTIVE,
        )
        service.candidates.attach_fact(old_candidate_id, old_fact.id)

        corrected = service.apply_feedback(
            target_type="fact",
            target_id=old_fact.id,
            operation="edit",
            feedback_text="JetBrains",
            replacement_object="JetBrains",
        )

        assert corrected.replacement_target_id is not None
        replacement_fact_id = str(corrected.replacement_target_id)
        old_candidate = service.candidates.get_candidate(old_candidate_id)
        assert old_candidate.status is LifecycleStatus.SUPERSEDED
        assert old_candidate.superseded_by is not None
        replacement_candidate = service.candidates.get_candidate(
            old_candidate.superseded_by
        )
        assert replacement_candidate.status is LifecycleStatus.ACTIVE
        assert replacement_candidate.fact_id == replacement_fact_id

        forgotten = service.apply_feedback(
            target_type="fact",
            target_id=replacement_fact_id,
            operation="forget",
            feedback_text="Forget this editor preference.",
        )

        assert forgotten.status is LifecycleStatus.FORGOTTEN
        assert service.candidates.get_candidate(replacement_candidate.id).status is LifecycleStatus.FORGOTTEN
        assert service.graph.get(replacement_fact_id).status is MemoryFactStatus.FORGOTTEN
    finally:
        service.close()
