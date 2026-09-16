from __future__ import annotations

from .common import *
from .common import _StoredPagePlan
from .utility import _load_citations, _load_json_list, _load_review_findings

def _map_query_archive_item(row: sqlite3.Row) -> QueryArchiveHistoryItem:
    return QueryArchiveHistoryItem(
        id=str(row["id"]),
        question=str(row["question"]),
        answer_preview=str(row["answer_preview"]),
        title=str(row["title"]),
        target_path=str(row["target_path"]),
        section=str(row["section"]) if row["section"] is not None else None,
        tags=_load_json_list(row["tags_json"]),
        citation_count=int(row["citation_count"] or 0),
        agent_run_id=str(row["agent_run_id"]) if row["agent_run_id"] is not None else None,
        source_message_id=str(row["source_message_id"]) if row["source_message_id"] is not None else None,
        page_title=str(row["page_title"]),
        page_operation=str(row["page_operation"]),
        page_status=str(row["page_status"]),
        index_job_id=str(row["index_job_id"]) if row["index_job_id"] is not None else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _map_query_archive_detail(row: sqlite3.Row) -> QueryArchiveDetailResponse:
    item = _map_query_archive_item(row)
    return QueryArchiveDetailResponse(
        **item.model_dump(),
        answer=str(row["answer"]),
        citations=_load_citations(row["citations_json"]),
        page=WikiPageResponse(
            title=item.page_title,
            relative_path=item.target_path,
            operation=item.page_operation,
            status=item.page_status,
            index_job_id=item.index_job_id,
        ),
    )


def _map_ingest_review(row: sqlite3.Row) -> WikiIngestReviewResponse:
    return WikiIngestReviewResponse(
        review_id=str(row["id"]),
        run_id=str(row["run_id"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        summary=str(row["summary"] or ""),
        findings=_load_review_findings(row["findings_json"]),
        recommended_targets=_load_json_list(row["recommended_targets_json"]),
        reviewer_agent_id=str(row["reviewer_agent_id"]) if row["reviewer_agent_id"] is not None else None,
        model_error=str(row["model_error"]) if row["model_error"] is not None else None,
        created_at=str(row["created_at"]) if row["created_at"] is not None else None,
        updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
    )


def _map_plan(row: sqlite3.Row) -> _StoredPagePlan:
    return _StoredPagePlan(
        id=str(row["id"]),
        title=str(row["title"]),
        target_path=str(row["target_path"]),
        operation=str(row["operation"]),
        section=str(row["section"]) if row["section"] is not None else None,
        content=str(row["content"]),
        tags=_load_json_list(row["tags_json"]),
        links=_load_json_list(row["links_json"]),
        target_content_hash=str(row["target_content_hash"]) if row["target_content_hash"] is not None else None,
    )
