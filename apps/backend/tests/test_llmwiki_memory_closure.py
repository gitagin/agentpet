from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.models.api import (
    WikiIngestApplyRequest,
    WikiIngestConfirmRequest,
    WikiIngestPreviewRequest,
    WikiIngestReviewRequest,
)
from app.services.memory import SafeMarkdownWriter
from app.services.memory_entity_extraction import (
    EXTRACTION_SCHEMA_VERSION,
    EntityAmbiguityError,
    activate_extraction_candidates,
    parse_extraction_output,
    persist_extraction_candidates,
)
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.wiki import WikiService
from app.services.wiki.memory_closure import WIKI_EXTRACTION_METADATA_VERSION
from app.services.wiki_workflows import WikiWorkflowError, WikiWorkflowService
from app.storage.database import Database, MigrationRunner
from app.storage.markdown import read_markdown


def _batch_payload() -> dict[str, object]:
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "entities": [
            {
                "entity_ref": "project-atlas",
                "entity_type": "project",
                "name": "Atlas",
                "aliases": ["Atlas app"],
                "confidence": 0.92,
                "evidence": {"start": 0, "end": 24},
            }
        ],
        "claims": [
            {
                "claim_ref": "claim-status",
                "subject_entity_ref": "project-atlas",
                "predicate": "status",
                "value": "in progress",
                "fact_type": "project",
                "confidence": 0.9,
                "evidence": {"start": 0, "end": 24},
            }
        ],
        "relations": [],
        "sensitive": [],
        "conflicts": [],
        "uncertainties": [],
    }


def _extraction_metadata(provenance: str) -> dict[str, object]:
    return {
        "memory_extraction": {
            "wrapper_version": WIKI_EXTRACTION_METADATA_VERSION,
            "provenance": provenance,
            "payload": _batch_payload(),
        }
    }


def _workflow_service(tmp_path: Path) -> tuple[Database, WikiWorkflowService, Path]:
    database = Database(tmp_path / "workflow.sqlite3")
    MigrationRunner(database).apply()
    vault_root = tmp_path / "Vault"
    wiki = WikiService(
        SafeMarkdownWriter(vault_root),
        index_refresh=lambda _path: "scheduled:memory-closure",
    )
    return database, WikiWorkflowService(database, wiki), vault_root


def _confirmed_ingest(
    service: WikiWorkflowService,
    *,
    source_metadata: dict[str, object] | None = None,
    source_type: str = "manual",
):
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Atlas Status",
            content="Atlas is in progress for this project.",
            source_type=source_type,
            source_metadata=source_metadata or {},
            max_pages=1,
        )
    )
    assert preview.preview_token
    confirmed = service.confirm_ingest(
        WikiIngestConfirmRequest(
            preview_token=preview.preview_token,
            user_confirmed=True,
        )
    )
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
    request = WikiIngestApplyRequest(
        run_id=confirmed.run_id,
        approved_targets=[confirmed.page_plans[0].target_path],
        review_id=review.review_id,
        review_acknowledged=True,
    )
    return confirmed, request


def test_wiki_ingest_without_extraction_persists_source_provenance_only(tmp_path: Path) -> None:
    database, service, vault_root = _workflow_service(tmp_path)
    confirmed, request = _confirmed_ingest(service)

    applied = service.apply_ingest(request)

    assert applied.status == "applied"
    page = read_markdown(vault_root / confirmed.page_plans[0].target_path)
    with database.connect() as conn:
        source_entity = conn.execute(
            "SELECT id, status FROM memory_entities WHERE entity_type = 'source'"
        ).fetchone()
        assert source_entity is not None
        source_candidate = conn.execute(
            "SELECT id, status FROM memory_candidates WHERE normalized_value = ?",
            (confirmed.source_hash,),
        ).fetchone()
        assert source_candidate is not None
        source_evidence = conn.execute(
            "SELECT id FROM memory_evidence WHERE candidate_id = ?",
            (source_candidate["id"],),
        ).fetchone()
        assert source_evidence is not None
        active_claims = conn.execute(
            "SELECT COUNT(*) FROM memory_graph_facts "
            "WHERE statement_kind = 'claim' AND status = 'active'"
        ).fetchone()[0]
        artifact_count = conn.execute(
            "SELECT COUNT(*) FROM memory_fact_artifact_bindings"
        ).fetchone()[0]

    assert source_entity["status"] == "active"
    assert source_candidate["status"] == "candidate"
    assert active_claims == 0
    assert artifact_count == 0
    assert page.frontmatter["entity_ids"] == [source_entity["id"]]
    assert page.frontmatter["fact_ids"] == []
    assert page.frontmatter["evidence_ids"] == [source_evidence["id"]]


def test_model_extraction_stays_candidate_and_frontmatter_uses_database_ids(tmp_path: Path) -> None:
    database, service, vault_root = _workflow_service(tmp_path)
    with database.connect() as conn:
        existing_project = MemoryEntityGraphStore(conn).create_entity(
            entity_type="project",
            canonical_name="Atlas",
            status="active",
        )
    metadata = _extraction_metadata("model")
    metadata.update(
        {
            "entity_ids": ["forged-entity"],
            "fact_ids": ["forged-fact"],
            "evidence_ids": ["forged-evidence"],
        }
    )
    confirmed, request = _confirmed_ingest(service, source_metadata=metadata)

    applied = service.apply_ingest(request)

    assert applied.status == "applied"
    page = read_markdown(vault_root / confirmed.page_plans[0].target_path)
    with database.connect() as conn:
        entities = conn.execute(
            "SELECT id, entity_type, status FROM memory_entities "
            "WHERE entity_type IN ('source', 'project') ORDER BY entity_type"
        ).fetchall()
        claim = conn.execute(
            "SELECT id, status FROM memory_graph_facts WHERE statement_kind = 'claim'"
        ).fetchone()
        evidence_ids = {
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM memory_evidence WHERE id IN ({})".format(
                    ",".join("?" for _ in page.frontmatter["evidence_ids"])
                ),
                tuple(page.frontmatter["evidence_ids"]),
            ).fetchall()
        }
        artifact_count = conn.execute(
            "SELECT COUNT(*) FROM memory_fact_artifact_bindings"
        ).fetchone()[0]
        provenance_edges = conn.execute(
            "SELECT relation_type, status FROM memory_graph_facts "
            "WHERE relation_type IN ('derived_from', 'supports')"
        ).fetchall()

    assert claim is not None
    assert claim["status"] == "candidate"
    assert {row["status"] for row in entities} == {"active"}
    assert existing_project.id in {str(row["id"]) for row in entities}
    assert set(page.frontmatter["entity_ids"]) == {str(row["id"]) for row in entities}
    assert page.frontmatter["fact_ids"] == [claim["id"]]
    assert evidence_ids == set(page.frontmatter["evidence_ids"])
    assert "forged-entity" not in page.frontmatter["entity_ids"]
    assert "forged-fact" not in page.frontmatter["fact_ids"]
    assert "forged-evidence" not in page.frontmatter["evidence_ids"]
    assert provenance_edges
    assert all(row["status"] == "candidate" for row in provenance_edges)
    assert artifact_count == 0


def test_explicit_user_extraction_activates_and_replay_preserves_graph_identity(
    tmp_path: Path,
) -> None:
    database, service, vault_root = _workflow_service(tmp_path)
    confirmed, request = _confirmed_ingest(
        service,
        source_metadata=_extraction_metadata("explicit_user"),
        source_type="user_message",
    )

    first = service.apply_ingest(request)

    assert first.status == "applied"
    relative_path = confirmed.page_plans[0].target_path
    page = read_markdown(vault_root / relative_path)
    with database.connect() as conn:
        claim = conn.execute(
            "SELECT id, status FROM memory_graph_facts WHERE statement_kind = 'claim'"
        ).fetchone()
        assert claim is not None
        project = conn.execute(
            "SELECT id, status FROM memory_entities WHERE entity_type = 'project'"
        ).fetchone()
        assert project is not None
        page_binding = conn.execute(
            "SELECT id, content_hash, revision, status FROM wiki_page_bindings"
        ).fetchone()
        assert page_binding is not None
        artifacts = conn.execute(
            "SELECT id, artifact_type, artifact_ref, status "
            "FROM memory_fact_artifact_bindings ORDER BY artifact_type"
        ).fetchall()
        before_entities = tuple(
            row["id"] for row in conn.execute("SELECT id FROM memory_entities ORDER BY id")
        )
        before_facts = tuple(
            (row["id"], row["support_count"])
            for row in conn.execute(
                "SELECT id, support_count FROM memory_graph_facts ORDER BY id"
            )
        )
        before_bindings = tuple(row["id"] for row in artifacts)

    assert claim["status"] == "active"
    assert project["status"] == "active"
    assert page.frontmatter["fact_ids"] == [claim["id"]]
    assert page_binding["content_hash"] == page.content_hash
    assert page_binding["revision"] == int(str(page.frontmatter["revision"]))
    assert page_binding["status"] == "active"
    assert {
        (row["artifact_type"], row["artifact_ref"], row["status"])
        for row in artifacts
    } == {
        ("source", "Wiki/Sources/Atlas-Status.md", "active"),
        ("wiki_page", relative_path, "active"),
    }

    replayed = service.apply_ingest(request)

    assert replayed.status == "applied"
    with database.connect() as conn:
        assert before_entities == tuple(
            row["id"] for row in conn.execute("SELECT id FROM memory_entities ORDER BY id")
        )
        assert before_facts == tuple(
            (row["id"], row["support_count"])
            for row in conn.execute(
                "SELECT id, support_count FROM memory_graph_facts ORDER BY id"
            )
        )
        assert before_bindings == tuple(
            row["id"]
            for row in conn.execute(
                "SELECT id FROM memory_fact_artifact_bindings ORDER BY artifact_type"
            )
        )
        assert conn.execute("SELECT COUNT(*) FROM wiki_page_bindings").fetchone()[0] == 1


def test_failed_page_write_keeps_candidates_without_active_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, service, vault_root = _workflow_service(tmp_path)
    confirmed, request = _confirmed_ingest(
        service,
        source_metadata=_extraction_metadata("explicit_user"),
        source_type="user_message",
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated page write failure")

    monkeypatch.setattr(service.wiki, "write_page", fail_write)
    applied = service.apply_ingest(request)

    assert applied.status == "failed"
    assert applied.pages_written == 0
    assert not (vault_root / confirmed.page_plans[0].target_path).exists()
    with database.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_entities WHERE status = 'candidate'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_graph_facts WHERE statement_kind = 'claim' "
            "AND status = 'candidate'"
        ).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM wiki_page_bindings").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_fact_artifact_bindings"
        ).fetchone()[0] == 0


def test_unversioned_extraction_envelope_fails_before_page_write(tmp_path: Path) -> None:
    database, service, vault_root = _workflow_service(tmp_path)
    confirmed, request = _confirmed_ingest(
        service,
        source_metadata={
            "memory_extraction": {
                "provenance": "model",
                "payload": _batch_payload(),
            }
        },
    )

    with pytest.raises(WikiWorkflowError, match="extraction_wrapper_version_invalid"):
        service.apply_ingest(request)

    assert not (vault_root / confirmed.page_plans[0].target_path).exists()
    with database.connect() as conn:
        result = json.loads(
            conn.execute(
                "SELECT result_json FROM wiki_workflow_runs WHERE id = ?",
                (confirmed.run_id,),
            ).fetchone()["result_json"]
        )
        assert result["closure_error"] == "extraction_wrapper_version_invalid"
        assert conn.execute("SELECT COUNT(*) FROM wiki_page_bindings").fetchone()[0] == 0


def test_replaying_one_source_is_idempotent_for_candidate_entities_and_facts(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        source = "Atlas is in progress for this project."
        batch = parse_extraction_output(_batch_payload(), source)
        first = persist_extraction_candidates(
            store,
            batch,
            source_text=source,
            source_type="user_message",
            source_id="message-1",
        )
        first_revision = store.source_revision()
        second = persist_extraction_candidates(
            store,
            batch,
            source_text=source,
            source_type="user_message",
            source_id="message-1",
        )

        assert first.entities["project-atlas"].id == second.entities["project-atlas"].id
        assert first.claim_ids["claim-status"] == second.claim_ids["claim-status"]
        assert store.conn.execute("SELECT COUNT(*) FROM memory_entities").fetchone()[0] == 1
        assert store.conn.execute("SELECT COUNT(*) FROM memory_graph_facts WHERE statement_kind = 'claim'").fetchone()[0] == 1
        assert store.conn.execute("SELECT COUNT(*) FROM memory_entity_aliases").fetchone()[0] == 1
        fact = store.get(first.claim_ids["claim-status"])
        assert fact.support_count == 1
        assert store.source_revision() == first_revision
    finally:
        store.close()


def test_same_name_active_entities_require_disambiguation(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        store.create_entity(entity_type="person", canonical_name="Alex")
        store.create_entity(entity_type="person", canonical_name="Alex")
        source = "Alex is a person I know."
        payload = _batch_payload()
        payload["entities"] = [
            {
                "entity_ref": "alex",
                "entity_type": "person",
                "name": "Alex",
                "aliases": [],
                "confidence": 0.9,
                "evidence": {"start": 0, "end": 4},
            }
        ]
        payload["claims"] = []
        batch = parse_extraction_output(payload, source)
        with pytest.raises(EntityAmbiguityError, match="disambiguation"):
            persist_extraction_candidates(
                store,
                batch,
                source_text=source,
                source_type="user_message",
                source_id="message-ambiguous",
            )
        assert store.conn.execute("SELECT COUNT(*) FROM memory_graph_facts").fetchone()[0] == 0
    finally:
        store.close()


def test_confirm_correct_forget_is_cross_session_authority_closure(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    source = "Atlas is in progress for this project."
    batch = parse_extraction_output(_batch_payload(), source)

    first_session = MemoryEntityGraphStore(db)
    try:
        resolved = persist_extraction_candidates(
            first_session,
            batch,
            source_text=source,
            source_type="user_message",
            source_id="message-closure-1",
        )
        fact_id = resolved.claim_ids["claim-status"]
        assert first_session.answerable_facts(query="Atlas") == []
    finally:
        first_session.close()

    second_session = MemoryEntityGraphStore(db)
    try:
        activation = activate_extraction_candidates(second_session, resolved, explicit_user=True)
        assert fact_id in activation.fact_ids
        assert second_session.answerable_facts(query="Atlas")[0].object == "in progress"
    finally:
        second_session.close()

    third_session = MemoryEntityGraphStore(db)
    try:
        old, replacement = third_session.correct_claim(
            fact_id,
            literal_value="complete",
            source_text="User corrected Atlas status to complete.",
        )
        assert old.status.value == "superseded"
        assert [fact.object for fact in third_session.answerable_facts(query="Atlas")] == ["complete"]
        entity_id = resolved.entities["project-atlas"].id
    finally:
        third_session.close()

    fourth_session = MemoryEntityGraphStore(db)
    try:
        assert [fact.object for fact in fourth_session.answerable_facts(query="Atlas")] == ["complete"]
        fourth_session.update_entity_status(entity_id, "forgotten", reason="user_forget")
        assert fourth_session.answerable_facts(query="Atlas") == []
        assert fourth_session.answerable_graph_facts(query="Atlas") == []
        assert fourth_session.get(replacement.id).status.value == "forgotten"
    finally:
        fourth_session.close()

    final_session = MemoryEntityGraphStore(db)
    try:
        assert final_session.answerable_facts(query="Atlas") == []
    finally:
        final_session.close()


def test_forgetting_entity_blocks_a_legacy_active_claim_on_read(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        entity = store.create_entity(entity_type="project", canonical_name="Legacy")
        fact = store.create_claim(
            subject_entity_id=entity.id,
            predicate="status",
            literal_value="active",
            source_text="Legacy is active.",
            evidence_id="legacy-evidence",
        )
        store.update_entity_status(entity.id, "forgotten", reason="user_forget")
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE memory_graph_facts SET status = 'active' WHERE id = ?", (fact.id,))
            conn.commit()
        assert store.answerable_facts(query="Legacy") == []
    finally:
        store.close()
