from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models.wiki import (
    WikiIngestApplyRequest,
    WikiIngestConfirmRequest,
    WikiIngestPreviewRequest,
    WikiIngestReviewRequest,
)
from app.services.wiki.common import WikiWorkflowError
from app.storage.database import Database
from tests.test_wiki_workflows import _workflow_service


def confirm(service, preview):
    return service.confirm_ingest(
        WikiIngestConfirmRequest(
            preview_token=preview.preview_token, user_confirmed=True
        )
    )


def source_record(service, source_id):
    with service.database.session() as conn:
        return dict(conn.execute(
            "SELECT * FROM wiki_sources WHERE id = ?", (source_id,)
        ).fetchone())


@pytest.fixture
def service(tmp_path):
    return _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault")


@pytest.fixture
def request_data():
    return WikiIngestPreviewRequest(
        title="Original source",
        content="Product P uses supplier A.",
        source_type="manual",
        source_uri="source:original",
        source_metadata={"author": "user", "permissions": {"use": False}},
    )


@pytest.mark.parametrize("change", [
    {"source_type": "assistant_output"},
    {"source_uri": "source:different"},
    {"source_metadata": {"author": "assistant", "permissions": {"use": False}}},
    {"source_metadata": {"author": "user", "permissions": {"use": True}}},
])
def test_same_body_cannot_overwrite_source_identity(service, request_data, change):
    first = confirm(service, service.preview_ingest(request_data))
    original = source_record(service, first.source_id)
    other = service.preview_ingest(request_data.model_copy(update=change))

    with pytest.raises(WikiWorkflowError, match="source_identity_conflict"):
        confirm(service, other)

    assert source_record(service, first.source_id) == original
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_runs").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM wiki_workflow_page_updates WHERE run_id = ?",
            (other.run_id,),
        ).fetchone()[0] == 0


def test_repeated_source_is_immutable_and_runs_keep_their_own_titles(service, request_data):
    first = confirm(service, service.preview_ingest(request_data))
    original = source_record(service, first.source_id)
    second = confirm(service, service.preview_ingest(
        request_data.model_copy(update={"title": "Other display title"})
    ))

    assert first.source_id == second.source_id
    assert source_record(service, first.source_id) == original
    assert service._load_ingest_run(first.run_id).source_title == "Original source"
    assert service._load_ingest_run(second.run_id).source_title == "Other display title"


def test_compilation_status_does_not_change_source_identity(service, request_data):
    first = confirm(service, service.preview_ingest(request_data))
    original = source_record(service, first.source_id)
    second = confirm(service, service.preview_ingest(request_data.model_copy(update={
        "source_metadata": {
            **request_data.source_metadata, "compilation_status": "model_not_configured"
        }
    })))
    assert second.source_id == first.source_id
    assert source_record(service, first.source_id) == original


@pytest.mark.parametrize("payload", ["{}", "[]", "null", "invalid"])
def test_invalid_persisted_request_does_not_fall_back_to_source_row(
    service, request_data, payload
):
    confirmed = confirm(service, service.preview_ingest(request_data))
    with service.database.session() as conn:
        conn.execute(
            "UPDATE wiki_workflow_runs SET request_json = ? WHERE id = ?",
            (payload, confirmed.run_id),
        )
    with pytest.raises(WikiWorkflowError, match="wiki_ingest_request_invalid"):
        service._load_ingest_run(confirmed.run_id)


@pytest.mark.parametrize("field", ["source_type", "source_uri", "source_metadata"])
def test_missing_recorded_identity_is_not_filled_with_defaults(service, request_data, field):
    confirmed = confirm(service, service.preview_ingest(request_data))
    with service.database.session() as conn:
        conn.execute(
            "UPDATE wiki_workflow_runs SET request_json = ? WHERE id = ?",
            (request_data.model_dump_json(exclude={field}), confirmed.run_id),
        )
    with pytest.raises(WikiWorkflowError, match="wiki_ingest_request_invalid"):
        service._load_ingest_run(confirmed.run_id)


@pytest.mark.parametrize("column,value", [
    ("source_type", "assistant_output"),
    ("source_uri", "source:changed"),
    ("raw_content", "Changed body."),
    ("metadata_json", '{"author":"assistant"}'),
    ("metadata_json", "[]"),
    ("metadata_json", "invalid"),
])
def test_changed_source_rejected_before_review_and_apply(
    service, request_data, column, value
):
    confirmed = confirm(service, service.preview_ingest(request_data))
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(
        run_id=confirmed.run_id
    )))
    with service.database.session() as conn:
        conn.execute(
            f"UPDATE wiki_sources SET {column} = ? WHERE id = ?",
            (value, confirmed.source_id),
        )

    with pytest.raises(WikiWorkflowError, match="source_"):
        service._load_ingest_run(confirmed.run_id)
    with pytest.raises(WikiWorkflowError, match="source_"):
        service.apply_ingest(WikiIngestApplyRequest(
            run_id=confirmed.run_id,
            approved_targets=[p.target_path for p in confirmed.page_plans],
            review_id=review.review_id,
            review_acknowledged=True,
        ))
    for plan in confirmed.page_plans:
        assert not (service.wiki.writer.vault_root / plan.target_path).exists()


def test_concurrent_same_source_confirmation_reuses_without_rewriting(service, request_data):
    previews = [service.preview_ingest(request_data) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda preview: confirm(service, preview), previews))
    assert results[0].source_id == results[1].source_id
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_runs").fetchone()[0] == 2


def test_concurrent_conflicting_sources_cannot_mutate_winner(service, request_data):
    previews = [
        service.preview_ingest(request_data),
        service.preview_ingest(request_data.model_copy(update={"source_type": "assistant_output"})),
    ]

    def attempt(preview):
        try:
            return confirm(service, preview)
        except WikiWorkflowError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, previews))
    errors = [result for result in results if isinstance(result, WikiWorkflowError)]
    assert len(errors) == 1
    assert str(errors[0]) == "wiki_ingest_source_identity_conflict"
    success = next(result for result in results if not isinstance(result, WikiWorkflowError))
    stored = service._load_ingest_run(success.run_id)
    assert source_record(service, success.source_id)["source_type"] == stored.source_type
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_runs").fetchone()[0] == 1
