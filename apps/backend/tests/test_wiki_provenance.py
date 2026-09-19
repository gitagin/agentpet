from __future__ import annotations

import asyncio
import json

import pytest

from app.models.wiki import (
    WikiIngestApplyRequest,
    WikiIngestPreviewRequest,
    WikiIngestReviewRequest,
)
from app.services.evidence_policy import (
    ProvenanceKind,
    independent_source_rejection_reason,
    source_provenance_kind,
)
from app.services.wiki.common import WikiWorkflowError
from app.services.wiki.memory_closure import (
    WikiMemoryClosureError,
    prepare_wiki_memory_closure,
)
from app.storage.database import Database
from tests.test_wiki_ingest_source_identity import confirm
from tests.test_wiki_workflows import _workflow_service


@pytest.fixture
def service(tmp_path):
    return _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault")


@pytest.mark.parametrize("label,kind", [
    ("manual", ProvenanceKind.RAW_SOURCE),
    ("file", ProvenanceKind.RAW_SOURCE),
    ("user_message", ProvenanceKind.USER_STATEMENT),
    ("wiki", ProvenanceKind.COMPILED_WIKI),
    ("synthesis", ProvenanceKind.SYNTHESIS),
    ("report", ProvenanceKind.QUERY_REPORT),
    ("agent_chat", ProvenanceKind.ASSISTANT_OUTPUT),
    (" ASSISTANT_OUTPUT ", ProvenanceKind.ASSISTANT_OUTPUT),
    ("unknown", None),
    ("", None),
])
def test_source_classification_does_not_invent_unknown_provenance(label, kind):
    assert source_provenance_kind(label) == kind
    assert bool(independent_source_rejection_reason(label)) == (
        kind not in {ProvenanceKind.RAW_SOURCE, ProvenanceKind.USER_STATEMENT}
    )


@pytest.mark.parametrize("source_type", [
    "assistant_output", "agent_chat", "wiki", "synthesis", "report", "unknown",
])
def test_non_root_input_remains_recorded_but_cannot_compile_or_apply(service, source_type):
    request = WikiIngestPreviewRequest(
        title="Unverified input", content="Product P uses supplier A.",
        source_type=source_type,
        source_metadata={"provenance_kind": "RAW_SOURCE", "verified": True},
    )
    confirmed = confirm(service, service.preview_ingest(request))
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(
        run_id=confirmed.run_id,
    )))
    reason = independent_source_rejection_reason(source_type)

    with pytest.raises(WikiWorkflowError, match=reason):
        asyncio.run(service.compile_ingest(request))
    with pytest.raises(WikiWorkflowError, match=reason):
        service.validate_ingest_application(confirmed.run_id)
    with pytest.raises(WikiWorkflowError, match=reason):
        service.apply_ingest(WikiIngestApplyRequest(
            run_id=confirmed.run_id,
            approved_targets=[plan.target_path for plan in confirmed.page_plans],
            review_id=review.review_id, review_acknowledged=True,
        ))
    with service.database.session() as conn:
        with pytest.raises(WikiMemoryClosureError, match=reason):
            prepare_wiki_memory_closure(
                conn, vault_root=service.wiki.writer.vault_root,
                source_id=confirmed.source_id, source_hash=confirmed.source_hash,
                source_title=request.title, source_type=source_type,
                raw_content=request.content, source_path=confirmed.page_plans[0].target_path,
                source_metadata=request.source_metadata,
            )
        assert conn.execute(
            "SELECT source_type FROM wiki_sources WHERE id = ?", (confirmed.source_id,)
        ).fetchone()[0] == source_type
        assert conn.execute("SELECT COUNT(*) FROM memory_entities").fetchone()[0] == 0
    assert all(
        not (service.wiki.writer.vault_root / plan.target_path).exists()
        for plan in confirmed.page_plans
    )


@pytest.mark.parametrize("source_type", ["manual", "file", "user_message"])
def test_original_material_still_uses_existing_ingest_workflow(service, source_type):
    request = WikiIngestPreviewRequest(
        title="Source", content="Product P uses supplier A.", source_type=source_type,
    )
    confirmed = confirm(service, service.preview_ingest(request))
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(
        run_id=confirmed.run_id,
    )))
    response = service.apply_ingest(WikiIngestApplyRequest(
        run_id=confirmed.run_id,
        approved_targets=[plan.target_path for plan in confirmed.page_plans],
        review_id=review.review_id, review_acknowledged=True,
    ))
    assert response.status == "applied"
    with service.database.session() as conn:
        row = conn.execute(
            "SELECT metadata_json FROM memory_candidates WHERE normalized_value = ?",
            (f"wiki-source-id:{confirmed.source_id}",),
        ).fetchone()
        assert json.loads(row["metadata_json"])["provenance_kind"] == source_provenance_kind(source_type)


@pytest.mark.parametrize("source_kind", ["file", "folder"])
@pytest.mark.parametrize("frontmatter,expected", [
    ("page_type: report", "query_report"),
    ("wiki_id: generated-page\npage_type: concept", "compiled_wiki"),
    ("wiki_id: generated-page\npage_type: synthesis", "synthesis"),
])
def test_import_preserves_known_derived_identity(service, tmp_path, source_kind, frontmatter, expected):
    from app.models.wiki import WikiSourceImportPreviewRequest

    import_root = tmp_path / "imports"
    import_root.mkdir()
    source = import_root / "export.md"
    source.write_text(f"---\n{frontmatter}\n---\nAn exported claim.\n", encoding="utf-8")
    preview = service.preview_import(WikiSourceImportPreviewRequest(
        source_kind=source_kind, import_root=str(import_root),
        source_path="export.md" if source_kind == "file" else ".",
    ))
    confirmed = confirm(service, preview)
    stored = service._load_ingest_run(confirmed.run_id)
    assert stored.source_type == (expected if source_kind == "file" else "compiled_wiki")
    with pytest.raises(WikiWorkflowError, match="derived_source_requires_verified_roots"):
        service.validate_ingest_application(confirmed.run_id)


@pytest.mark.parametrize("relative,page_type", [
    ("Wiki/Companion/Summaries/old.md", "source"),
    ("Wiki/Reports/query.md", "report"),
])
def test_compiler_rejects_derived_context_but_maintenance_can_read(service, relative, page_type):
    from app.services.wiki.compiler import CompilerError, read_evidence_snapshot, read_snapshot

    path = service.wiki.writer.vault_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\npage_type: {page_type}\n---\nAn assistant claim.\n", encoding="utf-8",
    )
    assert "An assistant claim." in read_snapshot(service.wiki, relative).text
    with pytest.raises(CompilerError, match="requires_verified_roots"):
        read_evidence_snapshot(service.wiki, relative, database=service.database)


def test_synthesis_rechecks_persisted_root_nature(service):
    from app.models.wiki import WikiSynthesizeRequest
    from tests.test_wiki_workflows import _ingest_source_page

    paths = [_ingest_source_page(service, title=title) for title in ("Alpha", "Beta")]
    with service.database.session() as conn:
        conn.execute("UPDATE wiki_sources SET source_type = 'assistant_output'")
    with pytest.raises(WikiWorkflowError, match="derived_source_requires_verified_roots"):
        service.synthesize(WikiSynthesizeRequest(
            title="Combined claim", content="A generated conclusion.", source_paths=paths,
        ))
    assert not (service.wiki.writer.vault_root / "Wiki/Syntheses/Combined-claim.md").exists()


def test_source_readback_rechecks_root_nature(service):
    from app.services.wiki.memory_closure import _read_source_content

    confirmed = confirm(service, service.preview_ingest(WikiIngestPreviewRequest(
        title="Input", content="A recorded source.",
    )))
    with service.database.session() as conn:
        source = conn.execute(
            "SELECT vault_id FROM wiki_sources WHERE id = ?", (confirmed.source_id,),
        ).fetchone()
        conn.execute(
            "UPDATE wiki_sources SET source_type = 'assistant_output' WHERE id = ?",
            (confirmed.source_id,),
        )
        with pytest.raises(WikiMemoryClosureError, match="derived_source_requires_verified_roots"):
            _read_source_content(conn, confirmed.source_id, source["vault_id"])


def test_compiler_catalog_excludes_reports_even_before_index_refresh(service):
    from app.services.wiki.compiler import related_pages
    from tests.test_wiki_workflows import _ingest_source_page

    source_path = _ingest_source_page(service, title="Topic source")

    for relative in ("Wiki/Reports/answer.md", "Wiki/Companion/Summaries/answer.md"):
        path = service.wiki.writer.vault_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Generated answer\nAn unverified claim.", encoding="utf-8")
    concept = service.wiki.writer.vault_root / "Wiki/Concepts/Topic.md"
    concept.parent.mkdir(parents=True, exist_ok=True)
    concept.write_text(
        f"---\nsources:\n  - {source_path}\n---\n# Topic\nAn existing note.", encoding="utf-8",
    )
    from tests.wiki_fixtures import indexed_citation
    indexed_citation(service.database, service.wiki.writer.vault_root, "Wiki/Concepts/Topic.md")

    class CatalogModel:
        async def complete(self, *, user_message, system_prompt):
            catalog = json.loads(user_message)["catalog"]
            assert {entry["path"] for entry in catalog} == {"Wiki/Concepts/Topic.md", source_path}
            return '{"paths": []}'

    assert asyncio.run(related_pages(service.wiki, CatalogModel(), [], database=service.database)) == {}
