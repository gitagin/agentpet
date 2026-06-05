from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models.enums import AgentId
from app.models.api import (
    MemorySearchResult,
    QueryArchiveRequest,
    WikiIngestApplyRequest,
    WikiIngestConfirmRequest,
    WikiIngestPreviewRequest,
    WikiIngestReviewRequest,
    WikiLintRequest,
    WikiPageWriteRequest,
    WikiSourceImportPreviewRequest,
    WikiSynthesizeRequest,
)
from app.repositories.storage import VaultRepository
from app.services.memory import SafeMarkdownWriter
from app.services.retrieval import RetrievalService
from app.services.wiki import WikiService
from app.services.wiki_lint import WikiLintService
from app.services.wiki_workflows import (
    QueryArchiveNotFoundError,
    QueryArchiveRejectedError,
    WikiWorkflowError,
    WikiWorkflowService,
)
from app.storage.database import Database, MigrationRunner
from tests.conftest import auth_headers


AUTH_HEADERS = auth_headers()


class FakeReviewModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append({"user_message": user_message, "system_prompt": system_prompt})
        return self.response


@pytest.fixture()
def api_client(tmp_path: Path, client_factory) -> Iterator[tuple[TestClient, Path]]:
    db_path = tmp_path / "state.sqlite3"
    with client_factory(sqlite_name="state.sqlite3", data_dir=tmp_path / "data") as client:
        yield client, db_path


def test_ingest_preview_is_bounded_and_does_not_write_pages(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)

    response = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Knowledge Wiki Theory",
            content="# Knowledge Wiki Theory\n\nIngest creates summaries.\n\n[[Query]]\n[[Lint]]",
            tags=["wiki-workflow"],
            links=["Ingest"],
            max_pages=2,
        )
    )

    assert response.status == "preview"
    assert response.preview_token
    assert len(response.page_plans) == 2
    assert response.page_plans[0].target_path == "Wiki/Sources/Knowledge-Wiki-Theory.md"
    assert response.page_plans[1].target_path.startswith("Wiki/Concepts/")
    assert (vault_root / "Wiki" / "AGENTS.md").exists()
    assert (vault_root / "Wiki" / "index.md").exists()
    assert (vault_root / "Wiki" / "log.md").exists()

    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_page_updates").fetchone()[0] == 0

    confirmed = _confirm_ingest(service, response)
    assert confirmed.status == "planned"
    assert confirmed.preview_token is None
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_page_updates").fetchone()[0] == 2
        source = conn.execute("SELECT raw_content FROM wiki_sources WHERE id = ?", (confirmed.source_id,)).fetchone()
    assert source["raw_content"] == "# Knowledge Wiki Theory\n\nIngest creates summaries.\n\n[[Query]]\n[[Lint]]"


def test_ingest_preview_adds_cross_page_maintenance_plans(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)

    response = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Agent Wiki Maintenance",
            content=(
                "# Agent Wiki Maintenance\n\n"
                "## Entities\n"
                "- Andrej Karpathy\n"
                "- Obsidian Vault\n\n"
                "## Agent Runtime vs Control Panel\n"
                "[[Agent Runtime]] vs [[Control Panel]] exposes conflict and stale control-panel drift.\n"
                "#llm-wiki"
            ),
            links=["Agent Runtime", "Control Panel"],
            tags=["llm-wiki"],
            max_pages=10,
        )
    )

    paths = [plan.target_path for plan in response.page_plans]
    assert paths[0] == "Wiki/Sources/Agent-Wiki-Maintenance.md"
    assert "Wiki/Concepts/Agent-Runtime.md" in paths
    assert "Wiki/Entities/Andrej-Karpathy.md" in paths
    assert "Wiki/Entities/Obsidian-Vault.md" in paths
    assert "Wiki/Comparisons/Agent-Runtime-vs-Control-Panel.md" in paths
    assert "Wiki/Syntheses/Agent-Wiki-Maintenance-Synthesis.md" in paths
    assert "Wiki/Reports/Agent-Wiki-Maintenance-Maintenance.md" in paths
    assert len(paths) <= 10

    comparison = next(plan for plan in response.page_plans if plan.target_path.startswith("Wiki/Comparisons/"))
    assert "comparison" in comparison.tags
    assert "[[Agent Runtime]] 和 [[Control Panel]]" in comparison.content
    maintenance = next(plan for plan in response.page_plans if plan.target_path.startswith("Wiki/Reports/"))
    assert "conflict-review" in maintenance.tags
    assert "conflict" in maintenance.content.casefold()
    assert not _vault_file(vault_root, "Wiki/Comparisons/Agent-Runtime-vs-Control-Panel.md").exists()

    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_page_updates").fetchone()[0] == 0

    _confirm_ingest(service, response)
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_page_updates").fetchone()[0] == len(paths)


def test_file_import_preview_stores_raw_content_metadata_and_does_not_write_pages(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    import_root = tmp_path / "imports"
    import_root.mkdir()
    source_file = import_root / "notes.md"
    source_file.write_text("# Imported Notes\n\nFile import fact for [[Importer]].", encoding="utf-8")
    service = _workflow_service(database, vault_root)

    response = service.preview_import(
        WikiSourceImportPreviewRequest(
            source_kind="file",
            import_root=str(import_root),
            source_path="notes.md",
            tags=["import-test"],
            max_pages=2,
        )
    )

    assert response.status == "preview"
    assert response.source_metadata["source_kind"] == "file"
    assert response.source_metadata["file_name"] == "notes.md"
    assert response.page_plans[0].target_path == "Wiki/Sources/notes.md"
    assert not _vault_file(vault_root, response.page_plans[0].target_path).exists()

    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 0

    confirmed = _confirm_ingest(service, response)
    with database.connect() as conn:
        row = conn.execute(
            "SELECT raw_content, source_type, source_uri, metadata_json FROM wiki_sources WHERE id = ?",
            (confirmed.source_id,),
        ).fetchone()
    assert row["raw_content"] == "# Imported Notes\n\nFile import fact for [[Importer]]."
    assert row["source_type"] == "file"
    assert row["source_uri"] == str(source_file.resolve())
    metadata = json.loads(row["metadata_json"])
    assert metadata["resolved_path"] == str(source_file.resolve())
    assert metadata["source_kind"] == "file"


def test_folder_import_preview_stays_inside_import_root_and_defers_wiki_writes(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    import_root = tmp_path / "imports"
    import_root.mkdir()
    (import_root / "a.md").write_text("# A\n\nFolder fact A.", encoding="utf-8")
    (import_root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    service = _workflow_service(database, vault_root)

    response = service.preview_import(
        WikiSourceImportPreviewRequest(
            source_kind="folder",
            import_root=str(import_root),
            source_path=".",
            title="Import Folder",
            max_files=5,
            max_pages=1,
        )
    )

    assert response.source_metadata["source_kind"] == "folder"
    assert response.source_metadata["file_count"] == 2
    assert "Folder fact A." in response.summary
    assert not _vault_file(vault_root, response.page_plans[0].target_path).exists()
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 0

    confirmed = _confirm_ingest(service, response)
    with database.connect() as conn:
        row = conn.execute("SELECT raw_content, metadata_json FROM wiki_sources WHERE id = ?", (confirmed.source_id,)).fetchone()
    assert "## a.md" in row["raw_content"]
    assert "## image.png" in row["raw_content"]
    assert json.loads(row["metadata_json"])["files"][1]["file_name"] == "image.png"

    with pytest.raises(WikiWorkflowError, match="source_path_outside_import_root"):
        service.preview_import(
            WikiSourceImportPreviewRequest(
                source_kind="file",
                import_root=str(import_root),
                source_path=str(outside),
            )
        )


def test_url_and_webpage_import_preview_use_supplied_content_without_network(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)

    with pytest.raises(WikiWorkflowError, match="url_import_requires_supplied_text_or_html"):
        service.preview_import(
            WikiSourceImportPreviewRequest(
                source_kind="url",
                url="https://example.test/article",
            )
        )

    response = service.preview_import(
        WikiSourceImportPreviewRequest(
            source_kind="url",
            url="https://example.test/article",
            html="<html><body><h1>Article</h1><p>Supplied webpage fact.</p></body></html>",
            max_pages=1,
        )
    )

    assert response.source_metadata["network_fetch"] is False
    assert response.source_metadata["url"] == "https://example.test/article"
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 0

    confirmed = _confirm_ingest(service, response)
    with database.connect() as conn:
        row = conn.execute("SELECT raw_content, source_type, metadata_json FROM wiki_sources WHERE id = ?", (confirmed.source_id,)).fetchone()
    assert "Supplied webpage fact." in row["raw_content"]
    assert row["source_type"] == "url"
    assert json.loads(row["metadata_json"])["network_fetch"] is False
    assert not _vault_file(vault_root, response.page_plans[0].target_path).exists()

    webpage = service.preview_import(
        WikiSourceImportPreviewRequest(
            source_kind="webpage_text",
            title="Copied Webpage",
            text="Copied webpage text for preview.",
            max_pages=1,
        )
    )
    assert webpage.source_metadata["source_kind"] == "webpage_text"
    assert not _vault_file(vault_root, webpage.page_plans[0].target_path).exists()


def test_image_asset_import_preview_stores_asset_metadata_and_apply_writes_later(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    import_root = tmp_path / "imports"
    import_root.mkdir()
    image = import_root / "diagram.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nasset")
    service = _workflow_service(database, vault_root)

    preview = service.preview_import(
        WikiSourceImportPreviewRequest(
            source_kind="image_asset",
            import_root=str(import_root),
            source_path="diagram.png",
            text="Diagram shows the importer review flow.",
            max_pages=1,
        )
    )

    assert preview.source_metadata["asset_kind"] == "local"
    assert preview.source_metadata["file_name"] == "diagram.png"
    assert not _vault_file(vault_root, preview.page_plans[0].target_path).exists()
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 0

    confirmed = _confirm_ingest(service, preview)
    with database.connect() as conn:
        row = conn.execute("SELECT raw_content, metadata_json FROM wiki_sources WHERE id = ?", (confirmed.source_id,)).fetchone()
    assert row["raw_content"] == "Diagram shows the importer review flow."
    assert json.loads(row["metadata_json"])["file_size_bytes"] == image.stat().st_size

    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
    applied = service.apply_ingest(
        WikiIngestApplyRequest(
            run_id=confirmed.run_id,
            approved_targets=[confirmed.page_plans[0].target_path],
            review_id=review.review_id,
            review_acknowledged=True,
        )
    )
    assert applied.pages_written == 1
    assert _vault_file(vault_root, confirmed.page_plans[0].target_path).exists()


def test_ingest_apply_writes_only_approved_targets_and_schedules_index(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root, index_job_id="scheduled:vault-1")
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Source A",
            content="# Source A\n\nFact for [[Concept A]].",
            links=["Concept A"],
            max_pages=3,
        )
    )
    preview = _confirm_ingest(service, preview)
    approved = [preview.page_plans[0].target_path]
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id)))

    applied = service.apply_ingest(
        WikiIngestApplyRequest(
            run_id=preview.run_id,
            approved_targets=approved,
            review_id=review.review_id,
            review_acknowledged=True,
        )
    )

    assert applied.status == "applied"
    assert applied.pages_written == 1
    assert applied.index_updated is True
    assert applied.log_appended is True
    assert applied.lint_summary["wiki_pages"] >= 1
    assert [result.relative_path for result in applied.page_results] == approved
    assert applied.page_results[0].index_job_id == "scheduled:vault-1"
    assert (vault_root / "Wiki" / "Sources" / "Source-A.md").exists()
    assert "Wiki/Sources/Source-A.md" in (vault_root / "Wiki" / "index.md").read_text(encoding="utf-8")
    assert "ingest |" in (vault_root / "Wiki" / "log.md").read_text(encoding="utf-8")
    assert not (vault_root / "Wiki" / "Concepts" / "Concept-A.md").exists()


def test_ingest_apply_unknown_run_is_stable_error_and_does_not_write(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)

    with pytest.raises(WikiWorkflowError, match="missing-run"):
        service.apply_ingest(WikiIngestApplyRequest(run_id="missing-run"))

    assert not (vault_root / "Wiki").exists()


def test_ingest_apply_requires_review_id_and_writes_nothing(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)
    preview, _review = _reviewed_ingest(service)

    _assert_apply_rejected_without_writes(
        service,
        database,
        vault_root,
        preview,
        WikiIngestApplyRequest(
            run_id=preview.run_id,
            approved_targets=[preview.page_plans[0].target_path],
            review_acknowledged=True,
        ),
        "review_id_required",
    )


def test_ingest_apply_requires_review_acknowledgement_and_writes_nothing(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)
    preview, review = _reviewed_ingest(service)

    _assert_apply_rejected_without_writes(
        service,
        database,
        vault_root,
        preview,
        WikiIngestApplyRequest(
            run_id=preview.run_id,
            approved_targets=[preview.page_plans[0].target_path],
            review_id=review.review_id,
        ),
        "review_acknowledged_required",
    )


def test_ingest_apply_requires_approved_targets_and_writes_nothing(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)
    preview, review = _reviewed_ingest(service)

    _assert_apply_rejected_without_writes(
        service,
        database,
        vault_root,
        preview,
        WikiIngestApplyRequest(
            run_id=preview.run_id,
            approved_targets=[],
            review_id=review.review_id,
            review_acknowledged=True,
        ),
        "approved_targets_required",
    )


def test_ingest_apply_rejects_target_outside_run_and_writes_nothing(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)
    preview, review = _reviewed_ingest(service)

    _assert_apply_rejected_without_writes(
        service,
        database,
        vault_root,
        preview,
        WikiIngestApplyRequest(
            run_id=preview.run_id,
            approved_targets=[preview.page_plans[0].target_path, "Wiki/Sources/Outside.md"],
            review_id=review.review_id,
            review_acknowledged=True,
        ),
        "approved_targets_not_in_run",
    )


def test_ingest_apply_rejects_review_from_other_run_and_writes_nothing(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)
    first_preview, first_review = _reviewed_ingest(service, title="First Source")
    second_preview, _second_review = _reviewed_ingest(service, title="Second Source")

    _assert_apply_rejected_without_writes(
        service,
        database,
        vault_root,
        second_preview,
        WikiIngestApplyRequest(
            run_id=second_preview.run_id,
            approved_targets=[second_preview.page_plans[0].target_path],
            review_id=first_review.review_id,
            review_acknowledged=True,
        ),
        "review_run_mismatch",
    )
    for plan in first_preview.page_plans:
        assert not _vault_file(vault_root, plan.target_path).exists()


def test_ingest_review_with_model_persists_findings_and_recommendations(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    model = FakeReviewModel(
        """
        {
          "summary": "Review found one strong source update.",
          "findings": [
            {
              "severity": "warning",
              "code": "missing_link",
              "message": "Confirm the related concept page.",
              "target_path": "Wiki/Concepts/Review-Concept.md"
            }
          ],
          "recommended_targets": ["Wiki/Sources/Review-Source.md"]
        }
        """
    )
    service = _workflow_service(database, vault_root, review_model=model)
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Review Source",
            content="# Review Source\n\nFact for [[Review Concept]].",
            links=["Review Concept"],
            max_pages=2,
        )
    )
    preview = _confirm_ingest(service, preview)

    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id)))

    assert review.status == "reviewed"
    assert review.summary == "Review found one strong source update."
    assert review.findings[0].code == "missing_link"
    assert review.recommended_targets == ["Wiki/Sources/Review-Source.md"]
    assert model.calls
    assert "Review Source" in model.calls[0]["user_message"]
    assert not (vault_root / "Wiki" / "Sources" / "Review-Source.md").exists()

    cached = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id)))
    assert cached.review_id == review.review_id

    with database.connect() as conn:
        row = conn.execute("SELECT status, findings_json FROM wiki_ingest_reviews WHERE id = ?", (review.review_id,)).fetchone()
    assert row["status"] == "reviewed"
    assert "missing_link" in row["findings_json"]


def test_ingest_review_without_model_is_stable_degraded_path(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Offline Review",
            content="# Offline Review\n\nOffline fact.",
            max_pages=1,
        )
    )
    preview = _confirm_ingest(service, preview)

    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id)))

    assert review.status == "model_not_configured"
    assert review.model_error == "model_not_configured"
    assert review.recommended_targets == [preview.page_plans[0].target_path]
    assert review.findings[0].code == "source_claims_extracted"

    applied = service.apply_ingest(
        WikiIngestApplyRequest(
            run_id=preview.run_id,
            approved_targets=review.recommended_targets,
            review_id=review.review_id,
            review_acknowledged=True,
        )
    )
    assert applied.pages_written == 1


def test_ingest_review_falls_back_to_semantic_model_when_wiki_model_missing(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    semantic_model = FakeReviewModel('{"summary":"Semantic review","findings":[],"recommended_targets":[]}')
    service = _workflow_service(
        database,
        vault_root,
        review_model_resolver=lambda agent_id: semantic_model if agent_id == AgentId.SEMANTIC_ANALYSIS_AGENT else None,
    )
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Semantic Fallback",
            content="# Semantic Fallback\n\nFallback fact.",
            max_pages=1,
        )
    )
    preview = _confirm_ingest(service, preview)

    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id)))

    assert review.status == "reviewed"
    assert review.reviewer_agent_id == "semantic_analysis_agent"
    assert review.summary == "Semantic review"
    assert semantic_model.calls


def test_ingest_review_uses_requested_reviewer_agent(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    wiki_model = FakeReviewModel('{"summary":"Wiki review","findings":[],"recommended_targets":[]}')
    semantic_model = FakeReviewModel('{"summary":"Semantic review","findings":[],"recommended_targets":[]}')
    service = _workflow_service(
        database,
        vault_root,
        review_model_resolver=lambda agent_id: semantic_model
        if agent_id == AgentId.SEMANTIC_ANALYSIS_AGENT
        else wiki_model
        if agent_id == AgentId.WIKI_MANAGER_AGENT
        else None,
    )
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Requested Reviewer",
            content="# Requested Reviewer\n\nReviewer fact.",
            max_pages=1,
        )
    )
    preview = _confirm_ingest(service, preview)

    review = asyncio.run(
        service.review_ingest(
            WikiIngestReviewRequest(
                run_id=preview.run_id,
                reviewer_agent_id=AgentId.SEMANTIC_ANALYSIS_AGENT,
            )
        )
    )

    assert review.status == "reviewed"
    assert review.reviewer_agent_id == "semantic_analysis_agent"
    assert review.summary == "Semantic review"
    assert not wiki_model.calls
    assert semantic_model.calls


def test_ingest_review_cache_is_scoped_to_requested_reviewer(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    wiki_model = FakeReviewModel('{"summary":"Wiki review","findings":[],"recommended_targets":[]}')
    semantic_model = FakeReviewModel('{"summary":"Semantic review","findings":[],"recommended_targets":[]}')
    service = _workflow_service(
        database,
        vault_root,
        review_model_resolver=lambda agent_id: semantic_model
        if agent_id == AgentId.SEMANTIC_ANALYSIS_AGENT
        else wiki_model
        if agent_id == AgentId.WIKI_MANAGER_AGENT
        else None,
    )
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="Reviewer Cache",
            content="# Reviewer Cache\n\nReviewer cache fact.",
            max_pages=1,
        )
    )
    preview = _confirm_ingest(service, preview)

    wiki_review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id)))
    semantic_review = asyncio.run(
        service.review_ingest(
            WikiIngestReviewRequest(
                run_id=preview.run_id,
                reviewer_agent_id=AgentId.SEMANTIC_ANALYSIS_AGENT,
            )
        )
    )

    assert wiki_review.review_id != semantic_review.review_id
    assert wiki_review.reviewer_agent_id == "wiki_manager_agent"
    assert semantic_review.reviewer_agent_id == "semantic_analysis_agent"
    assert wiki_model.calls
    assert semantic_model.calls


def test_ingest_review_unknown_run_is_stable_error(tmp_path: Path) -> None:
    service = _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault")

    with pytest.raises(WikiWorkflowError, match="missing-run"):
        asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id="missing-run")))


def test_query_archive_lint_rejects_mixed_sources_by_default(tmp_path: Path) -> None:
    service = _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault")

    lint = service.lint_query_archive(
        QueryArchiveRequest(
            question="What does the wiki say?",
            answer="It says ingest, query, and lint are core operations.",
            citations=[
                _citation("Wiki/Workflow.md", "knowledge_base"),
                _citation("Memories/Daily/2026-05-09.md", "daily_chat"),
            ],
        )
    )

    assert lint.passed is False
    assert "archive_contains_non_knowledge_citation" in lint.errors
    assert len(lint.normalized_citations) == 2


def test_query_archive_proposal_previews_without_writing_markdown(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    service = _workflow_service(database, vault_root)

    proposal = service.plan_query_archive(
        QueryArchiveRequest(
            question="What are the core wiki operations?",
            answer="Ingest, query archive, synthesize, and lint.",
            citations=[_citation("Wiki/Workflow.md")],
            title="Wiki Workflow Proposal",
            target_path="Wiki/Reports/Wiki-Workflow-Proposal.md",
            agent_run_id="run-123",
        )
    )

    assert proposal.proposal_type == "query_archive"
    assert proposal.status == "planned"
    assert proposal.target_path == "Wiki/Reports/Wiki-Workflow-Proposal.md"
    assert proposal.lint.passed is True
    assert "Ingest, query archive, synthesize, and lint." in proposal.markdown_preview
    assert not (vault_root / "Wiki" / "Reports" / "Wiki-Workflow-Proposal.md").exists()
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_query_archives").fetchone()[0] == 0


def test_synthesis_proposal_previews_without_writing_markdown(tmp_path: Path) -> None:
    vault_root = tmp_path / "Vault"
    service = _workflow_service(Database(tmp_path / "state.sqlite3"), vault_root)

    proposal = service.plan_synthesis(
        WikiSynthesizeRequest(
            title="Wiki Workflow Synthesis",
            content="The Wiki workflow now separates proposals from writes.",
            source_paths=["Wiki/Sources/Workflow.md"],
            tags=["workflow"],
        )
    )

    assert proposal.proposal_type == "synthesize"
    assert proposal.status == "planned"
    assert proposal.target_path == "Wiki/Syntheses/Wiki-Workflow-Synthesis.md"
    assert "The Wiki workflow now separates proposals from writes." in proposal.markdown_preview
    assert not (vault_root / "Wiki" / "Syntheses" / "Wiki-Workflow-Synthesis.md").exists()


def test_lint_proposal_does_not_write_report(tmp_path: Path) -> None:
    vault_root = tmp_path / "Vault"
    service = _workflow_service(Database(tmp_path / "state.sqlite3"), vault_root)

    proposal = service.plan_lint(WikiLintRequest(write_report=True))

    assert proposal.proposal_type == "lint"
    assert proposal.status == "planned"
    assert proposal.write_report is True
    assert proposal.target_path is not None
    assert proposal.target_path.startswith("Wiki/Reports/Lint-")
    assert "This proposal does not run a Markdown write" in proposal.markdown_preview
    assert not (vault_root / "Wiki" / "Reports").exists()


def test_query_archive_writes_page_with_normalized_citations(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    service = _workflow_service(database, tmp_path / "Vault")
    citation = _citation("Wiki/Workflow.md", "knowledge_base")

    response = service.archive_query(
        QueryArchiveRequest(
            question="What are the core wiki operations?",
            answer="Ingest, query archive, and lint.",
            citations=[citation, citation],
            title="Wiki Workflow Answer",
            target_path="Wiki/Reports/Wiki-Workflow-Answer.md",
            agent_run_id="run-123",
        )
    )

    assert response.archive_id
    assert response.page.relative_path == "Wiki/Reports/Wiki-Workflow-Answer.md"
    assert response.lint.passed is True
    assert len(response.lint.normalized_citations) == 1
    text = (tmp_path / "Vault" / "Wiki" / "Reports" / "Wiki-Workflow-Answer.md").read_text(encoding="utf-8")
    assert "What are the core wiki operations?" in text
    assert "| Wiki/Workflow.md |" in text
    assert "run-123" in text
    assert "query | Wiki Workflow Answer" in (tmp_path / "Vault" / "Wiki" / "log.md").read_text(encoding="utf-8")

    detail = service.get_query_archive(response.archive_id)
    assert detail.id == response.archive_id
    assert detail.answer == "Ingest, query archive, and lint."
    assert detail.target_path == response.page.relative_path
    assert detail.page.relative_path == response.page.relative_path
    assert detail.citations[0].relative_path == "Wiki/Workflow.md"
    assert detail.citation_count == 1
    assert detail.tags == ["query-archive"]

    with database.connect() as conn:
        row = conn.execute("SELECT * FROM wiki_query_archives WHERE id = ?", (response.archive_id,)).fetchone()
    assert row is not None
    assert row["page_status"] == response.page.status


def test_query_archive_history_list_orders_newest_first_and_excludes_non_archive_pages(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3")
    service = _workflow_service(database, tmp_path / "Vault")
    service.wiki.write_page(
        WikiPageWriteRequest(
            title="Manual Report",
            content="This report is not a query archive.",
            target_path="Wiki/Reports/Manual-Report.md",
        )
    )

    older = service.archive_query(
        QueryArchiveRequest(
            question="Older question?",
            answer="Older answer.",
            citations=[_citation("Wiki/Older.md")],
            title="Older Archive",
            target_path="Wiki/Reports/Older-Archive.md",
        )
    )
    newer = service.archive_query(
        QueryArchiveRequest(
            question="Newer question?",
            answer="Newer answer.",
            citations=[_citation("Wiki/Newer.md")],
            title="Newer Archive",
            target_path="Wiki/Reports/Newer-Archive.md",
            tags=["review"],
            source_message_id="message-2",
        )
    )
    with database.connect() as conn:
        with conn:
            conn.execute(
                "UPDATE wiki_query_archives SET created_at = ?, updated_at = ? WHERE id = ?",
                ("2026-05-09T00:00:00Z", "2026-05-09T00:00:00Z", older.archive_id),
            )
            conn.execute(
                "UPDATE wiki_query_archives SET created_at = ?, updated_at = ? WHERE id = ?",
                ("2026-05-09T00:01:00Z", "2026-05-09T00:01:00Z", newer.archive_id),
            )

    history = service.list_query_archives(limit=20)

    assert [item.id for item in history.archives] == [newer.archive_id, older.archive_id]
    assert all(item.target_path != "Wiki/Reports/Manual-Report.md" for item in history.archives)
    assert history.archives[0].answer_preview == "Newer answer."
    assert history.archives[0].tags == ["query-archive", "review"]
    assert history.archives[0].source_message_id == "message-2"


def test_query_archive_history_unknown_id_is_stable_error(tmp_path: Path) -> None:
    service = _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault")

    with pytest.raises(QueryArchiveNotFoundError):
        service.get_query_archive("missing-archive")


def test_query_archive_write_rejects_unlinted_answer(tmp_path: Path) -> None:
    service = _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault")

    with pytest.raises(QueryArchiveRejectedError):
        service.archive_query(
            QueryArchiveRequest(
                question="No sources?",
                answer="This should not be archived.",
                citations=[],
            )
        )


def test_wiki_lint_detects_health_gaps_and_writes_report(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    vault_root = tmp_path / "Vault"
    wiki_root = vault_root / "Wiki"
    wiki_root.mkdir(parents=True)
    (wiki_root / "Main.md").write_text("# Main\n\nLinks to [[Missing]].\n", encoding="utf-8")
    (wiki_root / "Orphan.md").write_text("# Orphan\n\nUnlinked page.\n", encoding="utf-8")
    (wiki_root / "Reports").mkdir()
    (wiki_root / "Reports" / "Old.md").write_text("# Old Report\n\nIgnored by lint.\n", encoding="utf-8")

    database = Database(db_path)
    MigrationRunner(database).apply()
    with database.connect() as conn:
        with conn:
            vault_id = VaultRepository(conn).upsert(vault_root)

    RetrievalService(database).rebuild_index(vault_id)
    (wiki_root / "Main.md").write_text("# Main\n\nChanged link to [[Missing]].\n", encoding="utf-8")

    with database.connect() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO notes(
                    id, vault_id, relative_path, title, content_hash, modified_at, status,
                    frontmatter_json, tags_json, links_json
                )
                VALUES ('note-missing', ?, 'Wiki/Deleted.md', 'Deleted', 'hash', 0, 'indexed', '{}', '[]', '[]')
                """,
                (vault_id,),
            )
            conn.execute(
                "INSERT INTO index_jobs(id, vault_id, type, status, error) VALUES ('job-failed', ?, 'full', 'failed', 'boom')",
                (vault_id,),
            )
            conn.execute(
                """
                INSERT INTO memory_graph_facts(
                    id, fact_key, conflict_key, category, subject, predicate, object, status,
                    confidence, source_text, source_type, support_count, conflicts_with, created_at, updated_at
                )
                VALUES (
                    'fact-1', 'fact-key', 'subject:predicate', 'profile', 'Subject', 'likes',
                    'Old value', 'quarantined', 0.7, 'source', 'test', 1, 'fact-0',
                    datetime('now'), datetime('now')
                )
                """
            )

    wiki = WikiService(SafeMarkdownWriter(vault_root), index_refresh=lambda _path: "scheduled:vault")
    service = WikiLintService(db_path, vault_id=vault_id, vault_root=vault_root, wiki=wiki)
    try:
        report = service.run(WikiLintRequest(write_report=True))
    finally:
        service.close()

    codes = {issue.code for issue in report.issues}
    assert {
        "graph_conflict_candidate",
        "missing_wiki_link",
        "orphan_wiki_page",
        "recent_index_job_failed",
        "wiki_index_missing_file",
        "wiki_index_stale",
        "wiki_vector_missing",
        "wiki_schema_frontmatter_missing",
    }.issubset(codes)
    assert "wiki_index_entry_missing" in codes or report.summary["issues"] >= 1
    assert report.summary["errors"] == 1
    assert report.report_page is not None
    assert report.report_page.relative_path.startswith("Wiki/Reports/Lint-")
    assert (wiki_root / "Reports" / Path(report.report_page.relative_path).name).exists()
    assert all(issue.path != "Wiki/Reports/Old.md" for issue in report.issues)
    assert report.research_questions


def test_wiki_lint_detects_missing_core_files_without_wiki_service(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    vault_root = tmp_path / "Vault"
    wiki_root = vault_root / "Wiki"
    wiki_root.mkdir(parents=True)
    (wiki_root / "Concepts").mkdir()
    (wiki_root / "Concepts" / "Core.md").write_text("# Core\n\nContent.\n", encoding="utf-8")

    database = Database(db_path)
    MigrationRunner(database).apply()
    with database.connect() as conn:
        with conn:
            vault_id = VaultRepository(conn).upsert(vault_root)

    service = WikiLintService(db_path, vault_id=vault_id, vault_root=vault_root)
    try:
        report = service.run(WikiLintRequest(write_report=False))
    finally:
        service.close()

    codes = {issue.code for issue in report.issues}
    assert "wiki_core_file_missing" in codes


def test_wiki_workflow_api_requires_auth(api_client: tuple[TestClient, Path]) -> None:
    client, _db_path = api_client

    response = client.post("/api/wiki/ingest/preview", json={"title": "A", "content": "B"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_authorization"

    review = client.post("/api/wiki/ingest/review", json={"run_id": "missing"})

    assert review.status_code == 401
    assert review.json()["error"]["code"] == "missing_authorization"


def test_wiki_ingest_confirm_rejects_expired_preview_token(
    api_client: tuple[TestClient, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _db_path = api_client
    vault_root = tmp_path / "Vault"
    init = client.post(
        "/api/vaults/init",
        headers=AUTH_HEADERS,
        json={"path": str(vault_root), "create_if_missing": True, "confirmed": True},
    )
    assert init.status_code == 200

    preview = client.post(
        "/api/wiki/ingest/preview",
        headers=AUTH_HEADERS,
        json={"title": "Expired Source", "content": "# Expired Source", "max_pages": 1},
    )
    assert preview.status_code == 200

    import app.services.wiki_workflows as wiki_workflows

    monkeypatch.setattr(wiki_workflows.time, "monotonic", lambda: 1_000_000_000.0)
    confirm = client.post(
        "/api/wiki/ingest/confirm",
        headers=AUTH_HEADERS,
        json={"preview_token": preview.json()["preview_token"], "user_confirmed": True},
    )

    assert confirm.status_code == 400
    assert confirm.json()["error"]["code"] == "wiki_ingest_preview_token_invalid"


def test_wiki_workflow_api_writes_and_audits(api_client: tuple[TestClient, Path], tmp_path: Path) -> None:
    client, db_path = api_client
    vault_root = tmp_path / "Vault"
    init = client.post(
        "/api/vaults/init",
        headers=AUTH_HEADERS,
        json={"path": str(vault_root), "create_if_missing": True, "confirmed": True},
    )
    assert init.status_code == 200

    preview = client.post(
        "/api/wiki/ingest/preview",
        headers=AUTH_HEADERS,
        json={
            "title": "API Source",
            "content": "# API Source\n\nAPI content for [[API Concept]].",
            "links": ["API Concept"],
            "max_pages": 2,
        },
    )
    assert preview.status_code == 200
    preview_payload = preview.json()

    confirm = client.post(
        "/api/wiki/ingest/confirm",
        headers=AUTH_HEADERS,
        json={"preview_token": preview_payload["preview_token"], "user_confirmed": True},
    )
    assert confirm.status_code == 200
    confirmed_payload = confirm.json()
    assert confirmed_payload["status"] == "planned"
    assert confirmed_payload["preview_token"] is None

    review = client.post(
        "/api/wiki/ingest/review",
        headers=AUTH_HEADERS,
        json={"run_id": confirmed_payload["run_id"]},
    )
    assert review.status_code == 200
    review_payload = review.json()
    assert review_payload["status"] == "model_not_configured"
    assert review_payload["recommended_targets"] == [plan["target_path"] for plan in confirmed_payload["page_plans"]]

    apply = client.post(
        "/api/wiki/ingest/apply",
        headers=AUTH_HEADERS,
        json={
            "run_id": confirmed_payload["run_id"],
            "approved_targets": [confirmed_payload["page_plans"][0]["target_path"]],
            "review_id": review_payload["review_id"],
            "review_acknowledged": True,
        },
    )
    assert apply.status_code == 200
    assert apply.json()["pages_written"] == 1

    lint = client.post(
        "/api/wiki/query-archives/lint",
        headers=AUTH_HEADERS,
        json={
            "question": "What did API Source say?",
            "answer": "API content.",
            "citations": [_citation_payload("Wiki/Sources/API-Source.md")],
        },
    )
    assert lint.status_code == 200
    assert lint.json()["passed"] is True

    archive = client.post(
        "/api/wiki/query-archives",
        headers=AUTH_HEADERS,
        json={
            "question": "What did API Source say?",
            "answer": "API content.",
            "citations": [_citation_payload("Wiki/Sources/API-Source.md")],
            "target_path": "Wiki/Reports/API-Answer.md",
        },
    )
    assert archive.status_code == 200
    archive_payload = archive.json()
    assert archive_payload["archive_id"]
    assert archive_payload["page"]["relative_path"] == "Wiki/Reports/API-Answer.md"

    history = client.get("/api/wiki/query-archives?limit=20", headers=AUTH_HEADERS)
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["archives"]] == [archive_payload["archive_id"]]

    detail = client.get(f"/api/wiki/query-archives/{archive_payload['archive_id']}", headers=AUTH_HEADERS)
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["answer"] == "API content."
    assert detail_payload["citations"][0]["relative_path"] == "Wiki/Sources/API-Source.md"
    assert detail_payload["page"]["relative_path"] == "Wiki/Reports/API-Answer.md"

    missing = client.get("/api/wiki/query-archives/missing-archive", headers=AUTH_HEADERS)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "query_archive_not_found"

    health = client.post("/api/wiki/lint", headers=AUTH_HEADERS, json={"write_report": True})
    assert health.status_code == 200
    assert health.json()["report_page"]["relative_path"].startswith("Wiki/Reports/Lint-")

    schema = client.get("/api/wiki/schema", headers=AUTH_HEADERS)
    assert schema.status_code == 200
    assert schema.json()["path"] == "Wiki/AGENTS.md"
    assert "LLM Wiki 规范" in schema.json()["content"]

    index = client.get("/api/wiki/index", headers=AUTH_HEADERS)
    assert index.status_code == 200
    assert any(entry["relative_path"] == "Wiki/Sources/API-Source.md" for entry in index.json()["entries"])

    log = client.get("/api/wiki/log", headers=AUTH_HEADERS)
    assert log.status_code == 200
    assert any(entry["operation"] in {"ingest", "query", "lint"} for entry in log.json()["entries"])

    graph = client.get("/api/wiki/graph", headers=AUTH_HEADERS)
    assert graph.status_code == 200
    graph_payload = graph.json()
    assert graph_payload["summary"]["nodes"] >= 1
    assert graph_payload["summary"]["edges"] >= 1
    assert any(node["relative_path"] == "Wiki/Sources/API-Source.md" for node in graph_payload["nodes"])
    assert all(node["vault_relative_path"].startswith("Wiki/") for node in graph_payload["nodes"])
    assert all(node["obsidian_uri"].startswith("obsidian://open?path=") for node in graph_payload["nodes"])

    synthesize = client.post(
        "/api/wiki/synthesize",
        headers=AUTH_HEADERS,
        json={
            "title": "API Synthesis",
            "content": "API Source and API Answer form a reusable synthesis.",
            "source_paths": ["Wiki/Sources/API-Source.md", "Wiki/Reports/API-Answer.md"],
            "tags": ["api"],
        },
    )
    assert synthesize.status_code == 200
    assert synthesize.json()["page"]["relative_path"] == "Wiki/Syntheses/API-Synthesis.md"
    assert synthesize.json()["index_updated"] is True

    with sqlite3.connect(db_path) as conn:
        actions = {
            row[0]
            for row in conn.execute(
                """
                SELECT action
                FROM audit_logs
                WHERE action LIKE 'wiki.%'
                """
            ).fetchall()
        }
        action_results = {
            (row[0], row[1])
            for row in conn.execute(
                """
                SELECT action, result
                FROM audit_logs
                WHERE action LIKE 'wiki.%'
                """
            ).fetchall()
        }

    assert {
        "wiki.ingest.preview",
        "wiki.ingest.confirm",
        "wiki.ingest.review",
        "wiki.ingest.apply",
        "wiki.query_archive.lint",
        "wiki.query_archive.write",
        "wiki.query_archive.list",
        "wiki.query_archive.read",
        "wiki.lint.run",
        "wiki.graph.read",
    }.issubset(actions)
    assert ("wiki.query_archive.list", "success") in action_results
    assert ("wiki.query_archive.read", "success") in action_results
    assert ("wiki.query_archive.read", "failed") in action_results


def _reviewed_ingest(service: WikiWorkflowService, *, title: str = "Apply Security Source"):
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title=title,
            content=f"# {title}\n\nFact for [[{title} Concept]].",
            links=[f"{title} Concept"],
            max_pages=2,
        )
    )
    preview = _confirm_ingest(service, preview)
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id)))
    return preview, review


def _confirm_ingest(service: WikiWorkflowService, preview):
    assert preview.preview_token
    return service.confirm_ingest(
        WikiIngestConfirmRequest(preview_token=preview.preview_token, user_confirmed=True)
    )


def _assert_apply_rejected_without_writes(
    service: WikiWorkflowService,
    database: Database,
    vault_root: Path,
    preview,
    request: WikiIngestApplyRequest,
    error_pattern: str,
) -> None:
    with pytest.raises(WikiWorkflowError, match=error_pattern):
        service.apply_ingest(request)

    for plan in preview.page_plans:
        assert not _vault_file(vault_root, plan.target_path).exists()

    with database.connect() as conn:
        run_status = conn.execute(
            "SELECT status FROM wiki_workflow_runs WHERE id = ?",
            (preview.run_id,),
        ).fetchone()["status"]
        update_statuses = [
            row["status"]
            for row in conn.execute(
                "SELECT status FROM wiki_workflow_page_updates WHERE run_id = ? ORDER BY created_at, rowid",
                (preview.run_id,),
            ).fetchall()
        ]

    assert run_status == "planned"
    assert update_statuses == ["planned"] * len(preview.page_plans)


def _vault_file(vault_root: Path, relative_path: str) -> Path:
    return vault_root.joinpath(*relative_path.split("/"))


def _workflow_service(
    database: Database,
    vault_root: Path,
    *,
    index_job_id: str = "scheduled:test-vault",
    review_model=None,
    review_model_resolver=None,
) -> WikiWorkflowService:
    MigrationRunner(database).apply()
    wiki = WikiService(SafeMarkdownWriter(vault_root), index_refresh=lambda _path: index_job_id)
    return WikiWorkflowService(database, wiki, review_model=review_model, review_model_resolver=review_model_resolver)


def _citation(relative_path: str, source_scope: str = "knowledge_base") -> MemorySearchResult:
    return MemorySearchResult(
        note_id=f"note-{relative_path}",
        chunk_id=f"chunk-{relative_path}",
        relative_path=relative_path,
        title=Path(relative_path).stem,
        heading="Summary",
        snippet="Relevant snippet.",
        score=1.0,
        source_scope=source_scope,
        retrieval_mode="fts",
    )


def _citation_payload(relative_path: str) -> dict[str, object]:
    return _citation(relative_path).model_dump()
