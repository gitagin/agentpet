from __future__ import annotations

import json

import pytest

from app.models.wiki import WikiIngestPreviewRequest
from app.services.memory_candidates import MemoryCandidateCreate, MemoryCandidateStore
from app.services.memory_entity_extraction import (
    ExtractionValidationError, parse_extraction_output, persist_extraction_candidates,
)
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.wiki.memory_closure import (
    WikiMemoryClosureError,
    _annotate_fact_provenance,
    _ensure_source_entity,
    _fact_is_active_and_grounded,
    finalize_wiki_memory_closure,
    prepare_wiki_memory_closure,
)
from app.storage.database import Database
from app.utils.hash import sha256_hex
from tests.test_memory_entity_extraction import _payload
from tests.test_wiki_ingest_source_identity import confirm
from tests.test_wiki_workflows import _workflow_service


@pytest.fixture
def source(tmp_path):
    service = _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault")
    request = WikiIngestPreviewRequest(title="Input", content="A source statement.")
    confirmed = confirm(service, service.preview_ingest(request))
    return service, request, confirmed


def prepare(conn, source):
    service, request, confirmed = source
    return prepare_wiki_memory_closure(
        conn, vault_root=service.wiki.writer.vault_root,
        source_id=confirmed.source_id, source_hash=confirmed.source_hash,
        source_title=request.title, source_type=request.source_type,
        raw_content=request.content, source_path=confirmed.page_plans[0].target_path,
        source_metadata=request.source_metadata,
    )


@pytest.mark.parametrize("status", ["forgotten", "rejected", "archived", "superseded"])
def test_source_candidate_replay_cannot_reactivate(source, status):
    service, _, _ = source
    with service.database.session() as conn:
        first = prepare(conn, source)
        candidates = MemoryCandidateStore(conn)
        candidates.transition(candidate_id=first.source_candidate_id, to_status=status)
        with pytest.raises(WikiMemoryClosureError, match="source_candidate_not_activatable"):
            prepare(conn, source)
        assert candidates.get_candidate(first.source_candidate_id).status.value == status


def test_candidate_forgotten_after_prepare_blocks_finalization(source):
    service, request, _ = source
    with service.database.session() as conn:
        first = prepare(conn, source)
        candidates = MemoryCandidateStore(conn)
        candidates.transition(candidate_id=first.source_candidate_id, to_status="forgotten")
        with pytest.raises(WikiMemoryClosureError, match="source_candidate_not_activatable"):
            finalize_wiki_memory_closure(
                conn, preparation=first, vault_root=service.wiki.writer.vault_root,
                source_type=request.source_type, written_paths=(first.source_path,),
            )
        assert MemoryEntityGraphStore(conn).get_entity(first.source_entity_id).status == "candidate"


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("changed_field", ["source_id", "source_hash"])
def test_source_entity_replay_rejects_misattribution(source, legacy, changed_field):
    service, request, confirmed = source
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        metadata = {"source_id": confirmed.source_id, "source_hash": confirmed.source_hash}
        metadata[changed_field] = "other-source"
        graph.create_entity(
            entity_type="source", canonical_name=request.title, status="candidate",
            entity_key=f"wiki-source:{confirmed.source_hash}" if legacy else f"wiki-source-id:{confirmed.source_id}",
            metadata=metadata,
        )
        with pytest.raises(WikiMemoryClosureError, match="source_entity_identity_mismatch"):
            prepare(conn, source)


def test_valid_legacy_entity_is_reused_without_duplicate(source):
    service, request, confirmed = source
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        entity = graph.create_entity(
            entity_type="source", canonical_name=request.title, status="candidate",
            entity_key=f"wiki-source:{confirmed.source_hash}",
            metadata={"source_id": confirmed.source_id, "source_hash": confirmed.source_hash},
        )
        assert prepare(conn, source).source_entity_id == entity.id
        assert conn.execute(
            "SELECT COUNT(*) FROM memory_entities WHERE entity_type = 'source'"
        ).fetchone()[0] == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_source_candidate_identity_mismatch_is_not_repaired_by_replay(source, legacy):
    service, request, confirmed = source
    with service.database.session() as conn:
        candidates = MemoryCandidateStore(conn)
        candidate = candidates.create_candidate(MemoryCandidateCreate(
            memory_kind="fact", memory_scope="topic", summary="Wiki source provenance",
            normalized_value=confirmed.source_hash if legacy else f"wiki-source-id:{confirmed.source_id}",
            source_text=request.content, source_track="model_extracted",
            metadata={
                "source_hash": confirmed.source_hash, "source_id": "other-origin",
                "source_type": request.source_type, "candidate_role": "wiki_source_provenance",
            },
        ))
        with pytest.raises(WikiMemoryClosureError, match="source_candidate_identity_mismatch"):
            prepare(conn, source)
        assert candidates.get_candidate(candidate.id).metadata["source_id"] == "other-origin"


def test_valid_legacy_candidate_reuses_id_and_evidence(source):
    service, request, confirmed = source
    with service.database.session() as conn:
        candidates = MemoryCandidateStore(conn)
        candidate = candidates.create_candidate(MemoryCandidateCreate(
            memory_kind="fact", memory_scope="topic", summary="Wiki source provenance",
            normalized_value=confirmed.source_hash, source_text=request.content,
            source_track="model_extracted",
            metadata={
                "source_hash": confirmed.source_hash, "source_id": confirmed.source_id,
                "source_type": request.source_type, "candidate_role": "wiki_source_provenance",
            },
        ))
        first = prepare(conn, source)
        replay = prepare(conn, source)
        assert first.source_candidate_id == replay.source_candidate_id == candidate.id
        assert first.source_evidence_id == replay.source_evidence_id
        assert conn.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0] == 1


def test_new_source_entities_do_not_share_identity_by_body_hash(source):
    service, _, confirmed = source
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        first = _ensure_source_entity(
            graph, source_id="origin-a", source_hash=confirmed.source_hash, source_title="A",
        )
        second = _ensure_source_entity(
            graph, source_id="origin-b", source_hash=confirmed.source_hash, source_title="B",
        )
        assert first.id != second.id
        assert first.metadata["source_id"] == "origin-a"
        assert second.metadata["source_id"] == "origin-b"


def test_extraction_evidence_is_source_scoped_and_replay_is_idempotent(source):
    service, _, _ = source
    text = "I use VS Code on the Atlas project."
    batch = parse_extraction_output(_payload(), text)
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        first = persist_extraction_candidates(
            graph, batch, source_text=text, source_type="manual", source_id="origin-a",
        )
        second = persist_extraction_candidates(
            graph, batch, source_text=text, source_type="manual", source_id="origin-b",
        )
        replay = persist_extraction_candidates(
            graph, batch, source_text=text, source_type="manual", source_id="origin-a",
        )
        assert first.evidence_ids == replay.evidence_ids
        assert set(first.evidence_ids).isdisjoint(second.evidence_ids)
        assert first.entities["project-atlas"].id != second.entities["project-atlas"].id
        assert first.entities["project-atlas"].id == replay.entities["project-atlas"].id


def test_annotation_preserves_other_evidence_and_requires_exact_source(source):
    service, _, _ = source
    text = "The user prefers VS Code."
    body_hash = sha256_hex(text)
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        entity = graph.create_entity(entity_type="person", canonical_name="User")
        first = graph.create_claim(
            subject_entity_id=entity.id, predicate="prefers", literal_value="VS Code",
            source_text=text, evidence_id="evidence-a",
        )
        second = graph.create_claim(
            subject_entity_id=entity.id, predicate="prefers", literal_value="VS Code",
            source_text=text, evidence_id="evidence-b",
        )
        assert first.id == second.id
        _annotate_fact_provenance(
            graph, (first.id,), source_hash=body_hash, source_id="origin-a",
            provenance="model", evidence_ids=("evidence-a",),
        )
        original = conn.execute(
            "SELECT metadata_json FROM memory_evidence WHERE id = 'evidence-a'"
        ).fetchone()[0]
        assert not _fact_is_active_and_grounded(conn, first.id, body_hash, "origin-b")
        _annotate_fact_provenance(
            graph, (first.id,), source_hash=body_hash, source_id="origin-b",
            provenance="model", evidence_ids=("evidence-b",),
        )
        assert conn.execute(
            "SELECT metadata_json FROM memory_evidence WHERE id = 'evidence-a'"
        ).fetchone()[0] == original
        fact_metadata = conn.execute(
            "SELECT metadata_json FROM memory_graph_facts WHERE id = ?", (first.id,),
        ).fetchone()[0]
        assert json.loads(fact_metadata)["source_id"] == "origin-a"
        assert _fact_is_active_and_grounded(conn, first.id, body_hash, "origin-a")
        assert _fact_is_active_and_grounded(conn, first.id, body_hash, "origin-b")
        assert not _fact_is_active_and_grounded(conn, first.id, body_hash, "origin-c")
        with pytest.raises(WikiMemoryClosureError, match="source_evidence_identity_mismatch"):
            _annotate_fact_provenance(
                graph, (first.id,), source_hash=body_hash, source_id="origin-b",
                provenance="model", evidence_ids=("evidence-a",),
            )
        assert json.loads(original)["source_id"] == "origin-a"


@pytest.mark.parametrize("verified", [True, False])
def test_legacy_extraction_replay_requires_recorded_origin(source, verified):
    service, _, _ = source
    text = "I use VS Code on the Atlas project."
    batch = parse_extraction_output(_payload(), text)
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        legacy = persist_extraction_candidates(
            graph, batch, source_text=text, source_type="manual",
        )
        if verified:
            _annotate_fact_provenance(
                graph, (*legacy.claim_ids.values(), *legacy.relation_ids),
                source_id="origin-a", source_hash=sha256_hex(text),
                provenance="model", evidence_ids=legacy.evidence_ids,
            )
            # The old candidate already recorded this origin; no hash-only inference.
            with conn:
                conn.execute(
                    "UPDATE memory_entities SET metadata_json = ? WHERE id = ?",
                    (json.dumps({"source_id": "origin-a", "source_hash": sha256_hex(text)}),
                     legacy.entities["project-atlas"].id),
                )
            replay = persist_extraction_candidates(
                graph, batch, source_text=text, source_type="manual", source_id="origin-a",
            )
            assert replay.evidence_ids == legacy.evidence_ids
            assert replay.relation_ids == legacy.relation_ids
            assert graph.get(next(iter(replay.claim_ids.values()))).support_count == 1
        else:
            count = conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0]
            with pytest.raises(ExtractionValidationError, match="legacy_evidence_provenance_unverified"):
                persist_extraction_candidates(
                    graph, batch, source_text=text, source_type="manual", source_id="origin-a",
                )
            assert conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == count
