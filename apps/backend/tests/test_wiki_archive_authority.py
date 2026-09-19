from types import SimpleNamespace

import pytest

from app.models.api import QueryArchiveRequest
from app.services.memory import SafeMarkdownWriter
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.wiki import WikiService
from app.services.wiki_workflows import QueryArchiveRejectedError, WikiWorkflowService
from app.storage.database import Database, MigrationRunner
from tests.wiki_fixtures import indexed_citation


@pytest.fixture
def archive_service(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    MigrationRunner(database).apply()
    return WikiWorkflowService(database, WikiService(
        SafeMarkdownWriter(tmp_path / "Vault"), index_refresh=lambda _: "test-index",
    ))


def citation(service, path="Wiki/Sources/Source.md", **kwargs):
    return indexed_citation(service.database, service.wiki.writer.vault_root, path, **kwargs)


def request_for(*citations, **kwargs):
    return QueryArchiveRequest(question="What does the source say?", answer="A derived answer.",
        citations=list(citations), target_path="Wiki/Reports/Answer.md", **kwargs)


@pytest.mark.parametrize("field,value", [
    ("note_id", "forged"), ("chunk_id", "forged"),
    ("relative_path", "Wiki/Sources/Other.md"), ("relative_path", "../Secret.md"),
    ("content_hash", "forged"), ("content_hash", None), ("source_scope", "personal_memory"),
])
def test_forged_reference_is_rejected_without_writes(archive_service, field, value):
    source = citation(archive_service).model_copy(update={field: value})
    request = request_for(source)
    assert not archive_service.lint_query_archive(request).passed
    with pytest.raises(QueryArchiveRejectedError):
        archive_service.archive_query(request)
    assert not (archive_service.wiki.writer.vault_root / request.target_path).exists()
    with archive_service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_query_archives").fetchone()[0] == 0


def test_client_descriptions_and_permissions_are_not_authority(archive_service):
    source = citation(archive_service)
    forged = source.model_copy(update={
        "snippet": "Invented secret evidence", "title": "Forged title", "heading": "Forged heading",
        "fact_id": "forged-fact", "evidence_refs": ["forged-evidence"], "lifecycle_status": "active",
    })
    lint = archive_service.lint_query_archive(request_for(source, forged))
    assert lint.passed
    assert len(lint.normalized_citations) == 1
    restored = lint.normalized_citations[0]
    assert restored.snippet == source.snippet
    assert restored.title == source.title
    assert restored.fact_id is None and restored.evidence_refs == []
    assert "Invented secret evidence" not in lint.markdown_preview


@pytest.mark.parametrize("status", ["forgotten", "stale", "quarantined"])
def test_approval_does_not_freeze_source_authority(archive_service, status):
    source = citation(archive_service)
    request = request_for(source)
    assert archive_service.plan_query_archive(request).status == "planned"
    graph = MemoryEntityGraphStore(archive_service.database.path)
    try:
        row = graph.conn.execute("SELECT * FROM wiki_page_bindings").fetchone()
        graph.update_wiki_binding(row["id"], content_hash=row["content_hash"], status=status)
    finally:
        graph.close()
    with pytest.raises(QueryArchiveRejectedError):
        archive_service.archive_query(request)


@pytest.mark.parametrize("path", ["Wiki/Sources/Source.md", "Notes/Source.md"])
def test_external_edit_rejects_old_citation_without_reindex(archive_service, path):
    source = citation(archive_service, path)
    request = request_for(source)
    assert archive_service.lint_query_archive(request).passed
    archive_service.wiki.writer.resolve_markdown_path(path).write_text("Changed source.", encoding="utf-8")
    lint = archive_service.lint_query_archive(request)
    assert not lint.passed
    assert lint.markdown_preview == ""


def test_cross_vault_identity_cannot_be_used_even_with_matching_text(archive_service, tmp_path):
    foreign = indexed_citation(archive_service.database, tmp_path / "OtherVault", "Notes/Source.md")
    citation(archive_service, "Notes/Source.md")
    lint = archive_service.lint_query_archive(request_for(foreign))
    assert not lint.passed
    assert lint.normalized_citations == []


def test_runtime_candidate_filter_is_reused(archive_service):
    source = citation(archive_service)
    archive_service.retrieval.candidate_filter = lambda _: False
    assert not archive_service.lint_query_archive(request_for(source)).passed


def test_unreviewed_wiki_cannot_be_archived_as_evidence(archive_service):
    source = citation(archive_service, reviewed=False)
    assert not archive_service.lint_query_archive(request_for(source)).passed


def test_report_stays_derived_and_cannot_seed_another_answer(archive_service):
    source = citation(archive_service)
    archive = archive_service.archive_query(request_for(source))
    report = citation(archive_service, archive.page.relative_path)
    with archive_service.database.session() as conn:
        binding = conn.execute("SELECT status FROM wiki_page_bindings WHERE wiki_relative_path = ?",
            (archive.page.relative_path,)).fetchone()
    assert binding["status"] == "quarantined"
    assert not archive_service.lint_query_archive(request_for(report)).passed
    assert archive_service.get_query_archive(archive.archive_id).answer == "A derived answer."


def test_legacy_report_binding_does_not_authorize_its_claims(archive_service):
    source = citation(archive_service, "Wiki/Reports/Legacy.md",
        content="---\npage_type: report\n---\n# Report\nLegacyclaim from an assistant.\n")
    assert not archive_service.lint_query_archive(request_for(source)).passed
    with archive_service.database.session() as conn:
        vault_id = conn.execute("SELECT id FROM vaults").fetchone()["id"]
    assert archive_service.retrieval.search(vault_id=vault_id, query="Legacyclaim").results == []


def test_mixed_source_flag_does_not_bypass_citation_validation(archive_service):
    source = citation(archive_service)
    personal = citation(archive_service, "Memory/Preference.md")
    assert not archive_service.lint_query_archive(request_for(source, personal)).passed
    assert archive_service.lint_query_archive(request_for(source, personal, allow_mixed_sources=True)).passed
    forged = personal.model_copy(update={"chunk_id": "missing"})
    assert not archive_service.lint_query_archive(request_for(source, forged, allow_mixed_sources=True)).passed


def test_sensitive_authoritative_text_is_not_echoed_in_lint(archive_service):
    source = citation(archive_service, "Notes/Secret.md", content="# Secret\npassword: test-secret-only\n")
    lint = archive_service.lint_query_archive(request_for(source))
    assert not lint.passed
    assert lint.normalized_citations == []
    assert "test-secret-only" not in lint.model_dump_json()


@pytest.mark.parametrize("canonical_parameters", [True, False])
def test_archive_receipt_rechecks_authority(archive_service, monkeypatch, canonical_parameters):
    from app.api.services import adapters

    source = citation(archive_service)
    request = request_for(source)
    key = "a" * 64
    marker = adapters._workflow_action_marker(key)
    archive_service.archive_query(request,
        archive_id=adapters._stable_effect_id("wiki-archive", key), action_marker=marker)
    monkeypatch.setattr(adapters, "wiki_workflow_service", lambda _: archive_service)
    result = {"canonical_parameters": request.model_dump()} if canonical_parameters else {}
    receipt = SimpleNamespace(idempotency_key=key, result=result)
    reader = adapters._wiki_query_archive_reader(None)
    assert reader(receipt) is not None
    archive_service.wiki.writer.resolve_markdown_path(source.relative_path).unlink()
    assert reader(receipt) is None


def test_api_archive_rejects_forged_reference(client_factory, tmp_path):
    from tests.conftest import auth_headers

    root = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        response = client.post("/api/vaults/init", headers=auth_headers(),
            json={"path": str(root), "create_if_missing": True, "confirmed": True})
        assert response.status_code == 200
        source = indexed_citation(client.app.state.database, root, "Wiki/Sources/Test.md")
        forged = source.model_copy(update={"chunk_id": "forged"})
        payload = request_for(forged).model_dump(mode="json")
        lint = client.post("/api/wiki/query-archives/lint", headers=auth_headers(), json=payload)
        assert lint.status_code == 200 and lint.json()["passed"] is False
        write = client.post("/api/wiki/query-archives", headers=auth_headers(), json=payload)
        assert write.status_code == 422
        assert not (root / payload["target_path"]).exists()
