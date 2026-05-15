from __future__ import annotations

import hashlib
import html
import inspect
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models.api import (
    MemorySearchResult,
    QueryArchiveDetailResponse,
    QueryArchiveHistoryItem,
    QueryArchiveHistoryResponse,
    QueryArchiveLintResponse,
    QueryArchiveRequest,
    QueryArchiveResponse,
    WikiLintProposal,
    WikiLintRequest,
    WikiIngestApplyRequest,
    WikiIngestApplyResponse,
    WikiIngestPagePlan,
    WikiIngestPageResult,
    WikiIngestPreviewRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewFinding,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiPageResponse,
    WikiPageWriteRequest,
    WikiQueryArchiveProposal,
    WikiSourceImportPreviewRequest,
    WikiSynthesisProposal,
    WikiSynthesizeRequest,
    WikiSynthesizeResponse,
)
from app.models.common import new_id
from app.models.enums import AgentId
from app.services.chat_model import ChatModelError
from app.services.tasks import utc_now_iso
from app.services.wiki import WikiService, slugify_wiki_title
from app.storage.database import Database
from app.storage.markdown import parse_markdown


class WikiReviewModelProtocol(Protocol):
    def complete(self, *, user_message: str, system_prompt: str | None = None): ...


ReviewModelResolver = Callable[[AgentId], WikiReviewModelProtocol | None]


class WikiWorkflowError(Exception):
    code = "wiki_workflow_failed"


class QueryArchiveRejectedError(WikiWorkflowError):
    code = "query_archive_rejected"

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("查询归档未通过检查。")


class QueryArchiveNotFoundError(WikiWorkflowError):
    code = "query_archive_not_found"

    def __init__(self, archive_id: str) -> None:
        self.archive_id = archive_id
        super().__init__(f"未找到查询归档：{archive_id}")


class WikiIngestApplyRejectedError(WikiWorkflowError):
    code = "wiki_ingest_apply_rejected"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class WikiSourceImportRejectedError(WikiWorkflowError):
    code = "wiki_source_import_rejected"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _StoredPagePlan:
    id: str
    title: str
    target_path: str
    operation: str
    section: str | None
    content: str
    tags: list[str]
    links: list[str]


@dataclass(frozen=True)
class _StoredIngestRun:
    id: str
    source_id: str | None
    source_title: str
    source_type: str
    source_uri: str | None
    raw_content: str
    page_plans: list[_StoredPagePlan]


class WikiWorkflowService:
    def __init__(
        self,
        database: Database,
        wiki: WikiService,
        *,
        review_model: WikiReviewModelProtocol | None = None,
        review_agent_id: AgentId | str | None = None,
        review_model_resolver: ReviewModelResolver | None = None,
    ) -> None:
        self.database = database
        self.wiki = wiki
        self.review_model = review_model
        self.review_agent_id = AgentId(review_agent_id or AgentId.WIKI_MANAGER_AGENT)
        self.review_model_resolver = review_model_resolver
        self._ensure_schema()

    def preview_ingest(self, request: WikiIngestPreviewRequest) -> WikiIngestPreviewResponse:
        self.wiki.ensure_core_files()
        source_hash = _source_hash(request.content)
        source_id = new_id()
        run_id = new_id()
        plans = _build_ingest_page_plans(request, source_hash)
        now = utc_now_iso()
        with self.database.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM wiki_sources WHERE source_hash = ?",
                (source_hash,),
            ).fetchone()
            if existing is not None:
                source_id = str(existing["id"])
                conn.execute(
                    """
                    UPDATE wiki_sources
                    SET title = ?, source_type = ?, source_uri = ?, content_preview = ?,
                        raw_content = ?, tags_json = ?, links_json = ?, metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        request.title,
                        request.source_type,
                        request.source_uri,
                        _preview_text(request.content),
                        request.content,
                        _json_list(request.tags),
                        _json_list(request.links),
                        _json_object(request.source_metadata),
                        now,
                        source_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO wiki_sources(
                        id, source_hash, title, source_type, source_uri, content_preview,
                        raw_content, tags_json, links_json, metadata_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        source_hash,
                        request.title,
                        request.source_type,
                        request.source_uri,
                        _preview_text(request.content),
                        request.content,
                        _json_list(request.tags),
                        _json_list(request.links),
                        _json_object(request.source_metadata),
                        now,
                        now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO wiki_workflow_runs(
                    id, workflow_type, source_id, status, request_json, result_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    "ingest",
                    source_id,
                    "planned",
                    request.model_dump_json(),
                    json.dumps({"source_hash": source_hash}, ensure_ascii=True),
                    now,
                    now,
                ),
            )
            for plan in plans:
                conn.execute(
                    """
                    INSERT INTO wiki_workflow_page_updates(
                        id, run_id, title, target_path, operation, section, content,
                        tags_json, links_json, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id(),
                        run_id,
                        plan.title,
                        plan.target_path,
                        plan.operation,
                        plan.section,
                        plan.content,
                        _json_list(plan.tags),
                        _json_list(plan.links),
                        "planned",
                        now,
                        now,
                    ),
                )
            conn.commit()
        return WikiIngestPreviewResponse(
            run_id=run_id,
            source_id=source_id,
            source_hash=source_hash,
            status="planned",
            page_plans=plans,
            summary=_summary_from_source(request.content),
            source_metadata=request.source_metadata,
        )

    def preview_import(self, request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewResponse:
        return self.preview_ingest(_import_preview_request(request))

    async def review_ingest(self, request: WikiIngestReviewRequest) -> WikiIngestReviewResponse:
        if not request.force_refresh:
            existing = self._latest_review(request.run_id, reviewer_agent_id=request.reviewer_agent_id)
            if existing is not None:
                return existing

        run = self._load_ingest_run(request.run_id)
        reviewer_agent_id, review_model = self._resolve_review_model(request.reviewer_agent_id)

        if review_model is None:
            response = _deterministic_review_response(
                run,
                reviewer_agent_id=reviewer_agent_id.value,
                status="model_not_configured",
                model_error="model_not_configured",
            )
            return self._insert_review(response)

        try:
            model_text = await _complete_model(
                review_model,
                user_message=_review_user_message(run),
                system_prompt=_review_system_prompt(),
            )
            response = _parse_model_review(
                model_text,
                run,
                reviewer_agent_id=reviewer_agent_id.value,
            )
        except ChatModelError as exc:
            response = _deterministic_review_response(
                run,
                reviewer_agent_id=reviewer_agent_id.value,
                status="failed",
                model_error=exc.code,
                summary=f"Model review failed: {exc.code}. Deterministic review was preserved.",
            )
        except Exception as exc:
            response = _deterministic_review_response(
                run,
                reviewer_agent_id=reviewer_agent_id.value,
                status="failed",
                model_error=getattr(exc, "code", exc.__class__.__name__),
                summary="Model review failed. Deterministic review was preserved.",
            )
        return self._insert_review(response)

    def apply_ingest(self, request: WikiIngestApplyRequest) -> WikiIngestApplyResponse:
        with self.database.connect() as conn:
            run = conn.execute(
                "SELECT * FROM wiki_workflow_runs WHERE id = ? AND workflow_type = ?",
                (request.run_id, "ingest"),
            ).fetchone()
            if run is None:
                raise WikiWorkflowError(f"Wiki ingest run not found: {request.run_id}")
            if not request.review_acknowledged:
                raise WikiIngestApplyRejectedError("review_acknowledged_required")
            if not request.review_id:
                raise WikiIngestApplyRejectedError("review_id_required")
            review = conn.execute(
                "SELECT run_id FROM wiki_ingest_reviews WHERE id = ?",
                (request.review_id,),
            ).fetchone()
            if review is None:
                raise WikiIngestApplyRejectedError("review_id_invalid")
            if str(review["run_id"]) != request.run_id:
                raise WikiIngestApplyRejectedError("review_run_mismatch")

            approved_targets = _unique(request.approved_targets or [])
            if not approved_targets:
                raise WikiIngestApplyRejectedError("approved_targets_required")
            rows = conn.execute(
                """
                SELECT *
                FROM wiki_workflow_page_updates
                WHERE run_id = ?
                ORDER BY created_at, target_path
                """,
                (request.run_id,),
            ).fetchall()
            plan_targets = {str(row["target_path"]) for row in rows}
            invalid_targets = [target for target in approved_targets if target not in plan_targets]
            if invalid_targets:
                raise WikiIngestApplyRejectedError(
                    "approved_targets_not_in_run: " + ", ".join(invalid_targets)
                )
            approved = set(approved_targets)
            plans = [_map_plan(row) for row in rows if str(row["target_path"]) in approved]

        results: list[WikiIngestPageResult] = []
        for plan in plans:
            try:
                page = self.wiki.write_page(
                    WikiPageWriteRequest(
                        title=plan.title,
                        content=plan.content,
                        operation=plan.operation,  # type: ignore[arg-type]
                        target_path=plan.target_path,
                        section=plan.section,
                        tags=plan.tags,
                        links=plan.links,
                        source_message_id=request.run_id,
                    )
                )
                result = WikiIngestPageResult(
                    title=page.title,
                    relative_path=page.relative_path,
                    status=page.status,
                    operation=page.operation,
                    index_job_id=page.index_job_id,
                )
                self._update_page_result(plan.id, status="written", index_job_id=page.index_job_id, error=None)
            except Exception as exc:
                result = WikiIngestPageResult(
                    title=plan.title,
                    relative_path=plan.target_path,
                    status="failed",
                    operation=plan.operation,
                    error=str(exc),
                )
                self._update_page_result(plan.id, status="failed", index_job_id=None, error=str(exc))
            results.append(result)

        pages_written = sum(1 for result in results if result.status in {"created", "updated"})
        run_status = "applied" if pages_written == len(results) else "partial" if pages_written else "failed"
        index_updated = False
        log_appended = False
        lint_summary: dict[str, object] = {}
        if pages_written:
            self.wiki.refresh_index()
            index_updated = True
            self.wiki.append_log(
                "ingest",
                request.run_id,
                _ingest_log_details(run_status=run_status, pages_written=pages_written, results=results),
            )
            log_appended = True
            lint_summary = self.wiki.core_lint_summary()
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE wiki_workflow_runs SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (
                    run_status,
                    json.dumps(
                        {"pages_written": pages_written, "page_count": len(results)},
                        ensure_ascii=True,
                    ),
                    utc_now_iso(),
                    request.run_id,
                ),
            )
            conn.commit()
        return WikiIngestApplyResponse(
            run_id=request.run_id,
            status=run_status,
            pages_written=pages_written,
            page_results=results,
            index_updated=index_updated,
            log_appended=log_appended,
            lint_summary=lint_summary,
        )

    def lint_query_archive(self, request: QueryArchiveRequest) -> QueryArchiveLintResponse:
        return _lint_query_archive(request)

    def plan_query_archive(self, request: QueryArchiveRequest) -> WikiQueryArchiveProposal:
        lint = self.lint_query_archive(request)
        title = request.title or _default_query_title(request.question)
        target_path = request.target_path or f"Wiki/Reports/{slugify_wiki_title(title)}.md"
        section = request.section or _query_archive_section(request)
        return WikiQueryArchiveProposal(
            status="planned" if lint.passed else "rejected",
            title=title,
            target_path=target_path,
            section=section,
            tags=_unique(["query-archive", *request.tags]),
            lint=lint,
            markdown_preview=lint.markdown_preview,
            agent_run_id=request.agent_run_id,
            source_message_id=request.source_message_id,
        )

    def archive_query(self, request: QueryArchiveRequest) -> QueryArchiveResponse:
        lint = self.lint_query_archive(request)
        if not lint.passed:
            raise QueryArchiveRejectedError(lint.errors)
        archive_id = new_id()
        title = request.title or _default_query_title(request.question)
        target_path = request.target_path or f"Wiki/Reports/{slugify_wiki_title(title)}.md"
        section = request.section or _query_archive_section(request)
        page = self.wiki.write_page(
            WikiPageWriteRequest(
                title=title,
                content=lint.markdown_preview,
                operation="replace_section",
                target_path=target_path,
                section=section,
                tags=["query-archive", *request.tags],
                links=_citation_links(lint.normalized_citations),
                source_message_id=request.source_message_id or request.agent_run_id,
            )
        )
        self._insert_query_archive(
            archive_id=archive_id,
            request=request,
            lint=lint,
            title=title,
            target_path=target_path,
            section=section,
            page=page,
        )
        self.wiki.refresh_index()
        self.wiki.append_log(
            "query",
            title,
            f"- 问题：{request.question.strip()}\n- 页面：`{page.relative_path}`\n- 引用：{len(lint.normalized_citations)}",
        )
        return QueryArchiveResponse(archive_id=archive_id, page=page, lint=lint)

    def plan_synthesis(self, request: WikiSynthesizeRequest) -> WikiSynthesisProposal:
        target_path = request.target_path or f"Wiki/Syntheses/{slugify_wiki_title(request.title)}.md"
        return WikiSynthesisProposal(
            title=request.title,
            target_path=target_path,
            tags=_unique(["synthesis", *request.tags]),
            links=_unique([*request.links, *request.source_paths]),
            source_paths=_unique(request.source_paths),
            markdown_preview=_synthesis_markdown(request),
        )

    def synthesize(self, request: WikiSynthesizeRequest) -> WikiSynthesizeResponse:
        target_path = request.target_path or f"Wiki/Syntheses/{slugify_wiki_title(request.title)}.md"
        content = _synthesis_markdown(request)
        page = self.wiki.write_page(
            WikiPageWriteRequest(
                title=request.title,
                content=content,
                operation="replace_section",
                target_path=target_path,
                section="综合整理",
                tags=_unique(["synthesis", *request.tags]),
                links=_unique([*request.links, *request.source_paths]),
            )
        )
        self.wiki.refresh_index()
        self.wiki.append_log(
            "synthesize",
            request.title,
            f"- 页面：`{page.relative_path}`\n- 来源路径：{len(request.source_paths)}",
        )
        return WikiSynthesizeResponse(page=page, index_updated=True, log_appended=True)

    def plan_lint(self, request: WikiLintRequest | None = None) -> WikiLintProposal:
        lint_request = request or WikiLintRequest()
        date = utc_now_iso()[:10]
        target_path = f"Wiki/Reports/Lint-{date}.md" if lint_request.write_report else None
        markdown = "\n".join(
            [
                "## Wiki Lint Proposal",
                "",
                f"- write_report: `{str(lint_request.write_report).lower()}`",
                f"- target_path: `{target_path or ''}`",
                "",
                "This proposal does not run a Markdown write. Confirm the lint action before writing a report.",
            ]
        ).strip()
        return WikiLintProposal(
            write_report=lint_request.write_report,
            target_path=target_path,
            markdown_preview=markdown,
        )

    def list_query_archives(self, limit: int = 20) -> QueryArchiveHistoryResponse:
        capped_limit = _history_limit(limit)
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM wiki_query_archives
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (capped_limit,),
            ).fetchall()
        return QueryArchiveHistoryResponse(archives=[_map_query_archive_item(row) for row in rows])

    def get_query_archive(self, archive_id: str) -> QueryArchiveDetailResponse:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM wiki_query_archives WHERE id = ?",
                (archive_id,),
            ).fetchone()
        if row is None:
            raise QueryArchiveNotFoundError(archive_id)
        return _map_query_archive_detail(row)

    def _load_ingest_run(self, run_id: str) -> _StoredIngestRun:
        with self.database.connect() as conn:
            run = conn.execute(
                """
                SELECT r.id, r.source_id, s.title, s.source_type, s.source_uri, s.raw_content, s.content_preview
                FROM wiki_workflow_runs r
                LEFT JOIN wiki_sources s ON s.id = r.source_id
                WHERE r.id = ? AND r.workflow_type = ?
                """,
                (run_id, "ingest"),
            ).fetchone()
            if run is None:
                raise WikiWorkflowError(f"Wiki ingest run not found: {run_id}")
            rows = conn.execute(
                """
                SELECT *
                FROM wiki_workflow_page_updates
                WHERE run_id = ?
                ORDER BY created_at, rowid
                """,
                (run_id,),
            ).fetchall()
        return _StoredIngestRun(
            id=str(run["id"]),
            source_id=str(run["source_id"]) if run["source_id"] is not None else None,
            source_title=str(run["title"] or "Untitled Source"),
            source_type=str(run["source_type"] or "manual"),
            source_uri=str(run["source_uri"]) if run["source_uri"] is not None else None,
            raw_content=str(run["raw_content"] or run["content_preview"] or ""),
            page_plans=[_map_plan(row) for row in rows],
        )

    def _latest_review(
        self,
        run_id: str,
        *,
        reviewer_agent_id: AgentId | None = None,
    ) -> WikiIngestReviewResponse | None:
        params: tuple[str, ...]
        reviewer_clause = ""
        if reviewer_agent_id is None:
            params = (run_id,)
        else:
            reviewer_clause = "AND reviewer_agent_id = ?"
            params = (run_id, reviewer_agent_id.value)
        with self.database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM wiki_ingest_reviews
                WHERE run_id = ?
                {reviewer_clause}
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return _map_ingest_review(row) if row is not None else None

    def _insert_review(self, response: WikiIngestReviewResponse) -> WikiIngestReviewResponse:
        now = utc_now_iso()
        review_id = response.review_id or new_id()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO wiki_ingest_reviews(
                    id, run_id, source_id, reviewer_agent_id, status, summary,
                    findings_json, recommended_targets_json, model_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    response.run_id,
                    self._source_id_for_run(response.run_id),
                    response.reviewer_agent_id,
                    response.status,
                    response.summary,
                    json.dumps([finding.model_dump() for finding in response.findings], ensure_ascii=True),
                    _json_list(response.recommended_targets),
                    response.model_error,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM wiki_ingest_reviews WHERE id = ?", (review_id,)).fetchone()
        return _map_ingest_review(row)

    def _source_id_for_run(self, run_id: str) -> str | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT source_id FROM wiki_workflow_runs WHERE id = ?", (run_id,)).fetchone()
        return str(row["source_id"]) if row is not None and row["source_id"] is not None else None

    def _resolve_review_model(
        self,
        requested_agent_id: AgentId | None,
    ) -> tuple[AgentId, WikiReviewModelProtocol | None]:
        if self.review_model_resolver is None:
            return self.review_agent_id, self.review_model
        if requested_agent_id is not None:
            return requested_agent_id, self.review_model_resolver(requested_agent_id)
        for agent_id in (self.review_agent_id, AgentId.SEMANTIC_ANALYSIS_AGENT):
            model = self.review_model_resolver(agent_id)
            if model is not None:
                return agent_id, model
        return self.review_agent_id, None

    def _insert_query_archive(
        self,
        *,
        archive_id: str,
        request: QueryArchiveRequest,
        lint: QueryArchiveLintResponse,
        title: str,
        target_path: str,
        section: str,
        page: WikiPageResponse,
    ) -> None:
        now = utc_now_iso()
        tags = ["query-archive", *request.tags]
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO wiki_query_archives(
                    id, question, answer_preview, answer, title, target_path, section,
                    tags_json, citations_json, citation_count, agent_run_id, source_message_id,
                    page_title, page_operation, page_status, index_job_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    archive_id,
                    request.question.strip(),
                    _answer_preview(request.answer),
                    request.answer.strip(),
                    title,
                    target_path,
                    section,
                    _json_list(tags),
                    _json_citations(lint.normalized_citations),
                    len(lint.normalized_citations),
                    request.agent_run_id,
                    request.source_message_id,
                    page.title,
                    page.operation,
                    page.status,
                    page.index_job_id,
                    now,
                    now,
                ),
            )
            conn.commit()

    def _update_page_result(
        self,
        page_update_id: str,
        *,
        status: str,
        index_job_id: str | None,
        error: str | None,
    ) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE wiki_workflow_page_updates
                SET status = ?, index_job_id = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, index_job_id, error, utc_now_iso(), page_update_id),
            )
            conn.commit()

    def _ensure_schema(self) -> None:
        with self.database.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS wiki_sources (
                    id TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_uri TEXT,
                    content_preview TEXT NOT NULL,
                    raw_content TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    links_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS wiki_workflow_runs (
                    id TEXT PRIMARY KEY,
                    workflow_type TEXT NOT NULL,
                    source_id TEXT REFERENCES wiki_sources(id),
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS wiki_workflow_page_updates (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES wiki_workflow_runs(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    section TEXT,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    links_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    index_job_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS wiki_query_archives (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer_preview TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    title TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    section TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    citation_count INTEGER NOT NULL DEFAULT 0,
                    agent_run_id TEXT,
                    source_message_id TEXT,
                    page_title TEXT NOT NULL,
                    page_operation TEXT NOT NULL,
                    page_status TEXT NOT NULL,
                    index_job_id TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_wiki_query_archives_created
                ON wiki_query_archives(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_wiki_query_archives_target
                ON wiki_query_archives(target_path);
                CREATE TABLE IF NOT EXISTS wiki_ingest_reviews (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES wiki_workflow_runs(id) ON DELETE CASCADE,
                    source_id TEXT REFERENCES wiki_sources(id),
                    reviewer_agent_id TEXT,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    findings_json TEXT NOT NULL DEFAULT '[]',
                    recommended_targets_json TEXT NOT NULL DEFAULT '[]',
                    model_error TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_wiki_ingest_reviews_run
                ON wiki_ingest_reviews(run_id, created_at DESC);
                """
            )
            _ensure_column(conn, "wiki_sources", "raw_content", "TEXT")
            _ensure_column(conn, "wiki_sources", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
            conn.commit()

def _build_ingest_page_plans(request: WikiIngestPreviewRequest, source_hash: str) -> list[WikiIngestPagePlan]:
    parsed = parse_markdown(request.content, fallback_title=request.title)
    source_path = f"Wiki/Sources/{slugify_wiki_title(request.title)}.md"
    source_links = _unique([*request.links, *parsed.links])
    plans: list[WikiIngestPagePlan] = []
    _append_ingest_plan(
        plans,
        _source_page_plan(request, source_hash=source_hash, source_path=source_path, source_links=source_links),
        max_pages=request.max_pages,
    )

    related_titles = _related_titles(request, parsed.links, parsed.tags)
    entity_candidates = _entity_candidates(request, parsed)
    comparison_candidates = _comparison_candidates(request, parsed, related_titles, entity_candidates)
    concept_plans = [
        _concept_page_plan(title, request=request, source_path=source_path)
        for title in related_titles
    ]
    entity_plans = [
        _entity_page_plan(candidate, request=request, source_path=source_path, related_titles=related_titles)
        for candidate in entity_candidates
    ]
    comparison_plans = [
        _comparison_page_plan(candidate, request=request, source_path=source_path)
        for candidate in comparison_candidates
    ]

    seed_plans: list[WikiIngestPagePlan] = []
    if concept_plans:
        seed_plans.append(concept_plans[0])
    if entity_plans:
        seed_plans.append(entity_plans[0])
    if comparison_plans:
        seed_plans.append(comparison_plans[0])
    if _should_plan_synthesis(parsed, related_titles, entity_candidates, comparison_candidates):
        seed_plans.append(
            _synthesis_page_plan(
                request,
                source_path=source_path,
                related_titles=related_titles,
                entity_candidates=entity_candidates,
                comparison_candidates=comparison_candidates,
            )
        )
    if _should_plan_maintenance(request.content, parsed):
        seed_plans.append(
            _maintenance_page_plan(
                request,
                source_path=source_path,
                related_titles=related_titles,
            )
        )

    for plan in [
        *seed_plans,
        *concept_plans[1:],
        *entity_plans[1:],
        *comparison_plans[1:],
    ]:
        _append_ingest_plan(plans, plan, max_pages=request.max_pages)
        if len(plans) >= request.max_pages:
            break
    return plans


def _import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    if request.source_kind == "file":
        return _file_import_preview_request(request)
    if request.source_kind == "folder":
        return _folder_import_preview_request(request)
    if request.source_kind == "url":
        return _url_import_preview_request(request)
    if request.source_kind == "webpage_text":
        return _webpage_text_import_preview_request(request)
    if request.source_kind == "image_asset":
        return _image_asset_import_preview_request(request)
    raise WikiSourceImportRejectedError(f"unsupported_source_kind:{request.source_kind}")


def _file_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    path = _resolve_import_path(request.import_root, request.source_path)
    if not path.is_file():
        raise WikiSourceImportRejectedError("source_file_not_found")
    if _is_binary_asset(path):
        return _asset_preview_request(request, path, content=None)
    content = _read_text_file(path)
    title = request.title or path.stem
    metadata = _base_import_metadata(request, source_uri=str(path))
    metadata.update(
        {
            "resolved_path": str(path),
            "file_name": path.name,
            "file_size_bytes": path.stat().st_size,
        }
    )
    return WikiIngestPreviewRequest(
        title=title,
        content=content,
        source_type="file",
        source_uri=str(path),
        tags=_unique(["import/file", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _folder_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    folder = _resolve_import_path(request.import_root, request.source_path)
    if not folder.is_dir():
        raise WikiSourceImportRejectedError("source_folder_not_found")
    files = [
        path
        for path in sorted(folder.rglob("*"))
        if path.is_file() and not _is_hidden_relative(folder, path)
    ][: request.max_files]
    if not files:
        raise WikiSourceImportRejectedError("source_folder_empty")
    sections: list[str] = []
    file_metadata: list[dict[str, object]] = []
    for path in files:
        relative = path.relative_to(folder).as_posix()
        if _is_binary_asset(path):
            text = _asset_markdown(path, title=relative)
            kind = "asset"
        else:
            text = _read_text_file(path)
            kind = "text"
        sections.extend([f"## {relative}", "", text.strip(), ""])
        file_metadata.append(
            {
                "relative_path": relative,
                "file_name": path.name,
                "file_size_bytes": path.stat().st_size,
                "kind": kind,
            }
        )
    title = request.title or folder.name
    metadata = _base_import_metadata(request, source_uri=str(folder))
    metadata.update(
        {
            "resolved_path": str(folder),
            "file_count": len(files),
            "files": file_metadata,
        }
    )
    return WikiIngestPreviewRequest(
        title=title,
        content="\n".join(sections).strip(),
        source_type="folder",
        source_uri=str(folder),
        tags=_unique(["import/folder", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _url_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    if not request.url:
        raise WikiSourceImportRejectedError("url_required")
    content = _supplied_web_content(request)
    if not content:
        raise WikiSourceImportRejectedError("url_import_requires_supplied_text_or_html")
    title = request.title or _title_from_url(request.url)
    metadata = _base_import_metadata(request, source_uri=request.url)
    metadata.update({"url": request.url, "network_fetch": False})
    return WikiIngestPreviewRequest(
        title=title,
        content=content,
        source_type="url",
        source_uri=request.url,
        tags=_unique(["import/url", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _webpage_text_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    content = _supplied_web_content(request)
    if not content:
        raise WikiSourceImportRejectedError("webpage_text_required")
    title = request.title or (request.url and _title_from_url(request.url)) or "Imported Webpage"
    metadata = _base_import_metadata(request, source_uri=request.url)
    if request.url:
        metadata["url"] = request.url
    return WikiIngestPreviewRequest(
        title=title,
        content=content,
        source_type="webpage_text",
        source_uri=request.url,
        tags=_unique(["import/webpage", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _image_asset_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    if request.source_path:
        path = _resolve_import_path(request.import_root, request.source_path)
        if not path.is_file():
            raise WikiSourceImportRejectedError("source_asset_not_found")
        return _asset_preview_request(request, path, content=request.text)
    if not request.url:
        raise WikiSourceImportRejectedError("asset_source_required")
    title = request.title or _title_from_url(request.url)
    metadata = _base_import_metadata(request, source_uri=request.url)
    metadata.update({"url": request.url, "asset_kind": "remote"})
    content = request.text.strip() if request.text and request.text.strip() else _asset_markdown(None, title=title)
    return WikiIngestPreviewRequest(
        title=title,
        content=content,
        source_type="image_asset",
        source_uri=request.url,
        tags=_unique(["import/asset", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _asset_preview_request(
    request: WikiSourceImportPreviewRequest,
    path: Path,
    *,
    content: str | None,
) -> WikiIngestPreviewRequest:
    title = request.title or path.stem
    metadata = _base_import_metadata(request, source_uri=str(path))
    metadata.update(
        {
            "resolved_path": str(path),
            "file_name": path.name,
            "file_size_bytes": path.stat().st_size,
            "asset_kind": "local",
        }
    )
    return WikiIngestPreviewRequest(
        title=title,
        content=content.strip() if content and content.strip() else _asset_markdown(path, title=title),
        source_type="image_asset" if request.source_kind == "image_asset" else "file",
        source_uri=str(path),
        tags=_unique(["import/asset", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _build_basic_ingest_page_plans(request: WikiIngestPreviewRequest, source_hash: str) -> list[WikiIngestPagePlan]:
    parsed = parse_markdown(request.content, fallback_title=request.title)
    source_slug = slugify_wiki_title(request.title)
    source_path = f"Wiki/Sources/{source_slug}.md"
    source_links = _unique([*request.links, *parsed.links])
    tags = _unique([*request.tags, *parsed.tags, "source"])
    plans = [
        WikiIngestPagePlan(
            title=request.title,
            target_path=source_path,
            operation="replace_section",
            section="来源摘要",
            content=_source_summary_markdown(request, source_hash, source_links),
            tags=tags,
            links=source_links,
        )
    ]
    related_titles = _related_titles(request, parsed.links)
    for title in related_titles[: max(0, request.max_pages - 1)]:
        plans.append(
            WikiIngestPagePlan(
                title=title,
                target_path=f"Wiki/Concepts/{slugify_wiki_title(title)}.md",
                operation="replace_section",
                section=f"来源：{request.title}",
                content=_concept_update_markdown(title, request, source_path),
                tags=_unique([*request.tags, "concept"]),
                links=[request.title],
            )
        )
    return plans[: request.max_pages]


@dataclass(frozen=True)
class _EntityCandidate:
    title: str
    kind: str
    evidence: str = ""


@dataclass(frozen=True)
class _ComparisonCandidate:
    left: str
    right: str
    reason: str = ""


def _source_page_plan(
    request: WikiIngestPreviewRequest,
    *,
    source_hash: str,
    source_path: str,
    source_links: list[str],
) -> WikiIngestPagePlan:
    return WikiIngestPagePlan(
        title=request.title,
        target_path=source_path,
        operation="replace_section",
        section="Source Summary",
        content=_source_summary_markdown(request, source_hash, source_links),
        tags=_unique([*request.tags, *parse_markdown(request.content, fallback_title=request.title).tags, "source"]),
        links=source_links,
    )


def _concept_page_plan(
    title: str,
    *,
    request: WikiIngestPreviewRequest,
    source_path: str,
) -> WikiIngestPagePlan:
    return WikiIngestPagePlan(
        title=title,
        target_path=f"Wiki/Concepts/{slugify_wiki_title(title)}.md",
        operation="replace_section",
        section=f"Source: {request.title}",
        content=_concept_update_markdown(title, request, source_path),
        tags=_unique([*request.tags, "concept"]),
        links=[request.title],
    )


def _entity_page_plan(
    candidate: _EntityCandidate,
    *,
    request: WikiIngestPreviewRequest,
    source_path: str,
    related_titles: list[str],
) -> WikiIngestPagePlan:
    return WikiIngestPagePlan(
        title=candidate.title,
        target_path=f"Wiki/Entities/{slugify_wiki_title(candidate.title)}.md",
        operation="replace_section",
        section=f"Source: {request.title}",
        content=_entity_update_markdown(candidate, request, source_path),
        tags=_unique([*request.tags, "entity", candidate.kind]),
        links=_unique([request.title, source_path, *related_titles]),
    )


def _comparison_page_plan(
    candidate: _ComparisonCandidate,
    *,
    request: WikiIngestPreviewRequest,
    source_path: str,
) -> WikiIngestPagePlan:
    title = _comparison_title(candidate)
    return WikiIngestPagePlan(
        title=title,
        target_path=f"Wiki/Comparisons/{slugify_wiki_title(title)}.md",
        operation="replace_section",
        section=f"Source: {request.title}",
        content=_comparison_update_markdown(candidate, request, source_path),
        tags=_unique([*request.tags, "comparison"]),
        links=_unique([request.title, source_path, candidate.left, candidate.right]),
    )


def _synthesis_page_plan(
    request: WikiIngestPreviewRequest,
    *,
    source_path: str,
    related_titles: list[str],
    entity_candidates: list[_EntityCandidate],
    comparison_candidates: list[_ComparisonCandidate],
) -> WikiIngestPagePlan:
    title = f"{request.title} Synthesis"
    return WikiIngestPagePlan(
        title=title,
        target_path=f"Wiki/Syntheses/{slugify_wiki_title(title)}.md",
        operation="replace_section",
        section=f"Synthesis: {request.title}",
        content=_ingest_synthesis_markdown(
            request,
            source_path=source_path,
            related_titles=related_titles,
            entity_candidates=entity_candidates,
            comparison_candidates=comparison_candidates,
        ),
        tags=_unique([*request.tags, "synthesis"]),
        links=_unique(
            [
                request.title,
                source_path,
                *related_titles,
                *(candidate.title for candidate in entity_candidates),
                *(_comparison_title(candidate) for candidate in comparison_candidates),
            ]
        ),
    )


def _maintenance_page_plan(
    request: WikiIngestPreviewRequest,
    *,
    source_path: str,
    related_titles: list[str],
) -> WikiIngestPagePlan:
    title = f"{request.title} Maintenance"
    return WikiIngestPagePlan(
        title=title,
        target_path=f"Wiki/Reports/{slugify_wiki_title(title)}.md",
        operation="replace_section",
        section=f"Maintenance: {request.title}",
        content=_maintenance_markdown(request, source_path=source_path),
        tags=_unique([*request.tags, "maintenance", "conflict-review"]),
        links=_unique([request.title, source_path, *related_titles]),
    )


def _append_ingest_plan(
    plans: list[WikiIngestPagePlan],
    plan: WikiIngestPagePlan,
    *,
    max_pages: int,
) -> None:
    if len(plans) >= max_pages:
        return
    existing_paths = {item.target_path.casefold() for item in plans}
    if plan.target_path.casefold() in existing_paths:
        return
    plans.append(plan)


def _entity_candidates(request: WikiIngestPreviewRequest, parsed) -> list[_EntityCandidate]:
    candidates: list[_EntityCandidate] = []
    for tag in _unique([*request.tags, *parsed.tags]):
        candidate = _entity_candidate_from_tag(tag)
        if candidate is not None:
            candidates.append(candidate)

    for key, value in parsed.frontmatter.items():
        kind = _entity_kind_from_key(str(key))
        if kind is None:
            continue
        for title in _candidate_values(value):
            candidates.append(_EntityCandidate(title=title, kind=kind, evidence=f"frontmatter:{key}"))

    for match in re.finditer(
        r"(?im)^\s*(?:[-*]\s*)?(entity|entities|person|people|company|organization|project|paper)\s*:\s*(.+)$",
        parsed.body,
    ):
        kind = _entity_kind_from_key(match.group(1)) or "entity"
        for title in _candidate_values(match.group(2)):
            candidates.append(_EntityCandidate(title=title, kind=kind, evidence=match.group(0).strip()))

    for chunk in parsed.chunks:
        kind = _entity_kind_from_heading(chunk.heading or "")
        if kind is None:
            continue
        for title in _bullet_values(chunk.content):
            candidates.append(_EntityCandidate(title=title, kind=kind, evidence=chunk.heading or "heading"))

    return _unique_entity_candidates(candidates)


def _entity_candidate_from_tag(tag: str) -> _EntityCandidate | None:
    marker, _, raw_title = tag.partition("/")
    kind = _entity_kind_from_key(marker)
    title = _clean_title_candidate(raw_title.replace("-", " ").replace("_", " ")) if raw_title else ""
    if kind is None or not title:
        return None
    return _EntityCandidate(title=title, kind=kind, evidence=f"tag:{tag}")


def _entity_kind_from_key(value: str) -> str | None:
    normalized = value.strip().casefold().replace("-", "_")
    return {
        "entity": "entity",
        "entities": "entity",
        "person": "person",
        "people": "person",
        "author": "person",
        "authors": "person",
        "company": "organization",
        "companies": "organization",
        "organization": "organization",
        "organizations": "organization",
        "org": "organization",
        "project": "project",
        "projects": "project",
        "paper": "paper",
        "papers": "paper",
    }.get(normalized)


def _entity_kind_from_heading(heading: str) -> str | None:
    normalized = heading.casefold()
    if any(marker in normalized for marker in ("people", "person", "authors")):
        return "person"
    if any(marker in normalized for marker in ("companies", "company", "organizations", "organization")):
        return "organization"
    if "projects" in normalized or "project" in normalized:
        return "project"
    if "papers" in normalized or "paper" in normalized:
        return "paper"
    if "entities" in normalized or "entity" in normalized:
        return "entity"
    return None


def _candidate_values(value) -> list[str]:
    raw_values = value if isinstance(value, list) else re.split(r"[,;]", str(value))
    return [
        cleaned
        for raw in raw_values
        if (cleaned := _clean_title_candidate(str(raw)))
    ]


def _bullet_values(content: str) -> list[str]:
    values: list[str] = []
    for line in content.splitlines():
        match = re.match(r"\s*(?:[-*]|\d+[.)])\s+(.+)$", line)
        if match:
            values.extend(_candidate_values(match.group(1)))
    return values


def _unique_entity_candidates(candidates: list[_EntityCandidate]) -> list[_EntityCandidate]:
    by_title: dict[str, _EntityCandidate] = {}
    for candidate in candidates:
        key = candidate.title.casefold()
        if key not in by_title:
            by_title[key] = candidate
    return list(by_title.values())


def _comparison_candidates(
    request: WikiIngestPreviewRequest,
    parsed,
    related_titles: list[str],
    entity_candidates: list[_EntityCandidate],
) -> list[_ComparisonCandidate]:
    candidates: list[_ComparisonCandidate] = []
    for chunk in parsed.chunks:
        heading_candidate = _comparison_from_heading(chunk.heading or "")
        if heading_candidate is not None:
            candidates.append(heading_candidate)
        candidates.extend(_comparisons_from_wikilink_pairs(chunk.content))

    names = _unique([*related_titles, *(candidate.title for candidate in entity_candidates)])
    if not candidates and _has_comparison_signal(request.content) and len(names) >= 2:
        candidates.append(_ComparisonCandidate(left=names[0], right=names[1], reason="comparison-signal"))
    return _unique_comparison_candidates(candidates)


def _comparison_from_heading(heading: str) -> _ComparisonCandidate | None:
    match = re.search(r"(.+?)\s+(?:vs\.?|versus|compared with|compared to)\s+(.+)", heading, flags=re.IGNORECASE)
    if match is None:
        return None
    left = _clean_title_candidate(match.group(1))
    right = _clean_title_candidate(match.group(2))
    if not left or not right or left.casefold() == right.casefold():
        return None
    return _ComparisonCandidate(left=left, right=right, reason="heading")


def _comparisons_from_wikilink_pairs(content: str) -> list[_ComparisonCandidate]:
    candidates: list[_ComparisonCandidate] = []
    pattern = re.compile(
        r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]\s+"
        r"(?:vs\.?|versus|compared with|compared to)\s+"
        r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(content):
        left = _clean_title_candidate(match.group(1))
        right = _clean_title_candidate(match.group(2))
        if left and right and left.casefold() != right.casefold():
            candidates.append(_ComparisonCandidate(left=left, right=right, reason="wikilink-pair"))
    return candidates


def _unique_comparison_candidates(candidates: list[_ComparisonCandidate]) -> list[_ComparisonCandidate]:
    by_pair: dict[tuple[str, str], _ComparisonCandidate] = {}
    for candidate in candidates:
        key = (candidate.left.casefold(), candidate.right.casefold())
        reverse_key = (candidate.right.casefold(), candidate.left.casefold())
        if key not in by_pair and reverse_key not in by_pair:
            by_pair[key] = candidate
    return list(by_pair.values())


def _comparison_title(candidate: _ComparisonCandidate) -> str:
    return f"{candidate.left} vs {candidate.right}"


def _should_plan_synthesis(
    parsed,
    related_titles: list[str],
    entity_candidates: list[_EntityCandidate],
    comparison_candidates: list[_ComparisonCandidate],
) -> bool:
    headings = _unique(chunk.heading for chunk in parsed.chunks if chunk.heading)
    return (
        len(related_titles) + len(entity_candidates) >= 2
        or len(headings) >= 3
        or bool(comparison_candidates)
    )


def _should_plan_maintenance(content: str, parsed) -> bool:
    text = " ".join([content, *(chunk.heading or "" for chunk in parsed.chunks)]).casefold()
    return any(
        marker in text
        for marker in (
            "conflict",
            "contradict",
            "inconsistent",
            "stale",
            "duplicate",
            "drift",
            "todo",
            "follow-up",
            "open question",
            "unclear",
            "disagreement",
        )
    )


def _has_comparison_signal(content: str) -> bool:
    normalized = content.casefold()
    return any(marker in normalized for marker in (" vs ", " versus ", " compared with ", " compared to ", "tradeoff"))


def _clean_title_candidate(value: str) -> str:
    text = re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", r"\1", value)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.split(r"\s+-\s+|\s+--\s+|\s+\|\s+|\s+\(", text, maxsplit=1)[0]
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n#`'\".,;:")
    if not text or text.casefold() in {"entity", "entities", "people", "projects", "papers"}:
        return ""
    if text.casefold().startswith(("http://", "https://")):
        return ""
    return text[:80].rstrip()


def _entity_update_markdown(
    candidate: _EntityCandidate,
    request: WikiIngestPreviewRequest,
    source_path: str,
) -> str:
    lines = [
        f"## Source: {request.title}",
        "",
        f"- Entity type: `{candidate.kind}`",
        f"- Source page: `{source_path}`",
    ]
    if candidate.evidence:
        lines.append(f"- Extraction signal: {candidate.evidence}")
    lines.extend(["", _summary_from_source(request.content, max_lines=4)])
    return "\n".join(lines).strip()


def _comparison_update_markdown(
    candidate: _ComparisonCandidate,
    request: WikiIngestPreviewRequest,
    source_path: str,
) -> str:
    lines = [
        f"## Source: {request.title}",
        "",
        f"- Source page: `{source_path}`",
        f"- Compared pages: [[{candidate.left}]] and [[{candidate.right}]]",
        f"- Extraction signal: {candidate.reason or 'comparison'}",
        "",
        _summary_from_source(request.content, max_lines=4),
    ]
    return "\n".join(lines).strip()


def _ingest_synthesis_markdown(
    request: WikiIngestPreviewRequest,
    *,
    source_path: str,
    related_titles: list[str],
    entity_candidates: list[_EntityCandidate],
    comparison_candidates: list[_ComparisonCandidate],
) -> str:
    lines = [
        f"## Synthesis: {request.title}",
        "",
        f"- Source page: `{source_path}`",
        f"- Related concepts: {', '.join(related_titles) if related_titles else 'none'}",
        f"- Entities: {', '.join(candidate.title for candidate in entity_candidates) if entity_candidates else 'none'}",
        f"- Comparisons: {', '.join(_comparison_title(candidate) for candidate in comparison_candidates) if comparison_candidates else 'none'}",
        "",
        _summary_from_source(request.content, max_lines=5),
    ]
    return "\n".join(lines).strip()


def _maintenance_markdown(request: WikiIngestPreviewRequest, *, source_path: str) -> str:
    signals = _maintenance_signals(request.content)
    lines = [
        f"## Maintenance: {request.title}",
        "",
        f"- Source page: `{source_path}`",
        f"- Signals: {', '.join(signals) if signals else 'review'}",
        "- Action: review conflicts, stale claims, duplicates, and missing follow-up pages before applying as durable truth.",
        "",
        _summary_from_source(request.content, max_lines=5),
    ]
    return "\n".join(lines).strip()


def _maintenance_signals(content: str) -> list[str]:
    normalized = content.casefold()
    return [
        marker
        for marker in (
            "conflict",
            "contradict",
            "inconsistent",
            "stale",
            "duplicate",
            "drift",
            "todo",
            "follow-up",
            "open question",
            "unclear",
            "disagreement",
        )
        if marker in normalized
    ]


def _lint_query_archive(request: QueryArchiveRequest) -> QueryArchiveLintResponse:
    errors: list[str] = []
    warnings: list[str] = []
    normalized = _dedupe_citations(request.citations)
    knowledge = [citation for citation in normalized if citation.source_scope == "knowledge_base"]
    non_knowledge = [citation for citation in normalized if citation.source_scope != "knowledge_base"]
    if not normalized:
        errors.append("archive_requires_at_least_one_citation")
    if not knowledge:
        errors.append("archive_requires_knowledge_base_citation")
    if non_knowledge and not request.allow_mixed_sources:
        errors.append("archive_contains_non_knowledge_citation")
    elif non_knowledge:
        warnings.append("archive_contains_mixed_source_citations")
    markdown = _query_archive_markdown(request, normalized)
    return QueryArchiveLintResponse(
        passed=not errors,
        errors=errors,
        warnings=warnings,
        normalized_citations=normalized,
        markdown_preview=markdown,
    )


def _source_summary_markdown(
    request: WikiIngestPreviewRequest,
    source_hash: str,
    links: list[str],
) -> str:
    summary = _summary_from_source(request.content)
    lines = [
        f"## 来源摘要",
        "",
        f"- 来源类型：`{request.source_type}`",
        f"- 来源哈希：`{source_hash}`",
    ]
    if request.source_uri:
        lines.append(f"- 来源地址：{request.source_uri}")
    if links:
        lines.append("- 关联链接：" + ", ".join(f"[[{link}]]" for link in links))
    lines.extend(["", summary])
    return "\n".join(lines).strip()


def _concept_update_markdown(title: str, request: WikiIngestPreviewRequest, source_path: str) -> str:
    excerpt = _summary_from_source(request.content, max_lines=3)
    return "\n".join(
        [
            f"## 来源：{request.title}",
            "",
            f"- 来源页面：`{source_path}`",
            f"- 来源类型：`{request.source_type}`",
            "",
            excerpt,
        ]
    ).strip()


def _query_archive_markdown(request: QueryArchiveRequest, citations: list[MemorySearchResult]) -> str:
    lines = [
        "## 查询归档",
        "",
        "### 问题",
        "",
        request.question.strip(),
        "",
        "### 回答",
        "",
        request.answer.strip(),
        "",
        "### 引用",
        "",
        "| 来源 | 标题 | 范围 | 检索方式 | 摘要 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for citation in citations:
        lines.append(
            "| "
            + " | ".join(
                [
                    _table_cell(citation.relative_path),
                    _table_cell(citation.heading or ""),
                    _table_cell(citation.source_scope),
                    _table_cell(citation.retrieval_mode),
                    _table_cell(citation.snippet),
                ]
            )
            + " |"
        )
    if request.agent_run_id or request.source_message_id:
        lines.extend(["", "### 元数据", ""])
        if request.agent_run_id:
            lines.append(f"- 智能体运行：`{request.agent_run_id}`")
        if request.source_message_id:
            lines.append(f"- 来源消息：`{request.source_message_id}`")
    return "\n".join(lines).strip()


def _synthesis_markdown(request: WikiSynthesizeRequest) -> str:
    lines = [
        "## 综合整理",
        "",
        request.content.strip(),
    ]
    if request.source_paths:
        lines.extend(["", "### 来源页面", ""])
        for path in request.source_paths:
            lines.append(f"- [[{path}]]")
    return "\n".join(lines).strip()


def _ingest_log_details(
    *,
    run_status: str,
    pages_written: int,
    results: list[WikiIngestPageResult],
) -> str:
    lines = [
        f"- 状态：{run_status}",
        f"- 已写入页面：{pages_written}",
        "- 页面：",
    ]
    for result in results:
        lines.append(f"  - `{result.relative_path}` ({result.status})")
    return "\n".join(lines)


def _summary_from_source(content: str, *, max_lines: int = 8) -> str:
    parsed = parse_markdown(content, fallback_title="来源")
    lines = []
    for line in parsed.body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("# "):
            continue
        lines.append(stripped)
        if len(lines) >= max_lines:
            break
    if not lines:
        lines = [parsed.title]
    return "\n".join(f"- {line}" for line in lines)


def _related_titles(
    request: WikiIngestPreviewRequest,
    parsed_links: list[str],
    parsed_tags: list[str] | None = None,
) -> list[str]:
    titles = [*request.links, *parsed_links]
    for tag in _unique([*request.tags, *(parsed_tags or [])]):
        title = _concept_title_from_tag(tag)
        if title:
            titles.append(title)
    return [title for title in _unique(titles) if title and title.casefold() != request.title.casefold()]


def _concept_title_from_tag(tag: str) -> str:
    marker, separator, raw_title = tag.partition("/")
    if separator and _entity_kind_from_key(marker) is not None:
        return ""
    value = raw_title if separator else tag
    return value.replace("-", " ").replace("_", " ").strip().title()


def _dedupe_citations(citations: list[MemorySearchResult]) -> list[MemorySearchResult]:
    seen: set[tuple[str, str, str]] = set()
    normalized: list[MemorySearchResult] = []
    for citation in citations:
        key = (
            citation.chunk_id or citation.relative_path,
            citation.heading or "",
            citation.snippet.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(citation)
    return normalized


def _citation_links(citations: list[MemorySearchResult]) -> list[str]:
    return _unique(citation.title for citation in citations if citation.title)


def _default_query_title(question: str) -> str:
    compact = re.sub(r"\s+", " ", question).strip()
    if len(compact) > 72:
        compact = compact[:72].rstrip()
    return f"查询归档 - {compact or '回答'}"


def _query_archive_section(request: QueryArchiveRequest) -> str:
    if request.agent_run_id:
        return f"查询归档 - {request.agent_run_id}"
    digest = hashlib.sha256(f"{request.question}\n{request.answer}".encode("utf-8")).hexdigest()[:12]
    return f"查询归档 - {digest}"


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
    )


def _deterministic_review_response(
    run: _StoredIngestRun,
    *,
    reviewer_agent_id: str,
    status: str,
    model_error: str | None = None,
    summary: str | None = None,
) -> WikiIngestReviewResponse:
    targets = [plan.target_path for plan in run.page_plans]
    findings = [
        WikiIngestReviewFinding(
            severity="info",
            code="source_claims_extracted",
            message=f"Source has {_non_empty_line_count(run.raw_content)} non-empty lines and {len(run.page_plans)} planned page updates.",
            target_path=targets[0] if targets else None,
        )
    ]
    missing_link_targets = _missing_link_targets(run.page_plans)
    findings.extend(
        WikiIngestReviewFinding(
            severity="warning",
            code="missing_link_review_needed",
            message=f"Planned content references [[{target}]]. Confirm whether this page should exist or be created.",
            target_path=None,
        )
        for target in missing_link_targets[:5]
    )
    if not run.page_plans:
        findings.append(
            WikiIngestReviewFinding(
                severity="error",
                code="no_page_plans",
                message="No page plans were generated for this ingest run.",
            )
        )
    return WikiIngestReviewResponse(
        review_id=new_id(),
        run_id=run.id,
        status=status,  # type: ignore[arg-type]
        summary=summary
        or f"Deterministic review prepared {len(run.page_plans)} page plans for source '{run.source_title}'.",
        findings=findings,
        recommended_targets=targets,
        reviewer_agent_id=reviewer_agent_id,
        model_error=model_error,
    )


def _parse_model_review(
    text: str,
    run: _StoredIngestRun,
    *,
    reviewer_agent_id: str,
) -> WikiIngestReviewResponse:
    data = _json_object_from_text(text)
    if data is None:
        base = _deterministic_review_response(
            run,
            reviewer_agent_id=reviewer_agent_id,
            status="failed",
            model_error="invalid_review_json",
            summary=_plain_text_summary(text) or "Model review was not valid JSON. Deterministic review was preserved.",
        )
        return base

    findings = _model_findings(data.get("findings"))
    recommended = _valid_review_targets(data.get("recommended_targets"), run)
    if not recommended:
        recommended = [plan.target_path for plan in run.page_plans]
    summary = str(data.get("summary") or "").strip() or _plain_text_summary(text)
    return WikiIngestReviewResponse(
        review_id=new_id(),
        run_id=run.id,
        status="reviewed",
        summary=summary or f"Model review prepared {len(recommended)} recommended targets.",
        findings=findings,
        recommended_targets=recommended,
        reviewer_agent_id=reviewer_agent_id,
    )


async def _complete_model(model: WikiReviewModelProtocol, *, user_message: str, system_prompt: str) -> str:
    result = model.complete(user_message=user_message, system_prompt=system_prompt)
    if inspect.isawaitable(result):
        result = await result
    return str(result).strip()


def _review_system_prompt() -> str:
    return (
        "You are reviewing a local-first LLM wiki ingest plan. "
        "Return only JSON with keys summary, findings, recommended_targets. "
        "findings is an array of objects with severity info|warning|error, code, message, target_path. "
        "Do not ask to write files and do not include secrets."
    )


def _review_user_message(run: _StoredIngestRun) -> str:
    plans = [
        {
            "title": plan.title,
            "target_path": plan.target_path,
            "operation": plan.operation,
            "section": plan.section,
            "tags": plan.tags,
            "links": plan.links,
            "content_preview": _preview_text(plan.content, 700),
        }
        for plan in run.page_plans
    ]
    payload = {
        "run_id": run.id,
        "source": {
            "id": run.source_id,
            "title": run.source_title,
            "type": run.source_type,
            "uri": run.source_uri,
            "content_preview": _preview_text(run.raw_content, 6000),
        },
        "page_plans": plans,
    }
    return json.dumps(payload, ensure_ascii=False)


def _json_object_from_text(text: str) -> dict[str, object] | None:
    stripped = text.strip()
    candidates = [stripped]
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _model_findings(value) -> list[WikiIngestReviewFinding]:
    if not isinstance(value, list):
        return []
    findings: list[WikiIngestReviewFinding] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "info").strip()
        if severity not in {"info", "warning", "error"}:
            severity = "info"
        code = str(item.get("code") or "model_review_note").strip()[:80] or "model_review_note"
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        target_path = item.get("target_path")
        findings.append(
            WikiIngestReviewFinding(
                severity=severity,  # type: ignore[arg-type]
                code=code,
                message=message[:1000],
                target_path=str(target_path).strip() if target_path else None,
            )
        )
    return findings


def _valid_review_targets(value, run: _StoredIngestRun) -> list[str]:
    valid = {plan.target_path for plan in run.page_plans}
    if not isinstance(value, list):
        return []
    return _unique(str(item) for item in value if str(item) in valid)


def _missing_link_targets(plans: list[_StoredPagePlan]) -> list[str]:
    plan_titles = {plan.title.casefold() for plan in plans}
    plan_paths = {Path(plan.target_path).stem.replace("-", " ").casefold() for plan in plans}
    linked: list[str] = []
    for plan in plans:
        linked.extend(plan.links)
        linked.extend(re.findall(r"\[\[([^\]]+)\]\]", plan.content))
    return [
        link
        for link in _unique(link.split("|", 1)[0].strip() for link in linked)
        if link.casefold() not in plan_titles and link.replace("-", " ").casefold() not in plan_paths
    ]


def _plain_text_summary(text: str, limit: int = 600) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit].rstrip()


def _non_empty_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _resolve_import_path(import_root: str | None, source_path: str | None) -> Path:
    if not import_root:
        raise WikiSourceImportRejectedError("import_root_required")
    if not source_path:
        raise WikiSourceImportRejectedError("source_path_required")
    root = Path(import_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise WikiSourceImportRejectedError("import_root_not_found")
    raw_path = Path(source_path).expanduser()
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WikiSourceImportRejectedError("source_path_outside_import_root") from exc
    return resolved


def _read_text_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WikiSourceImportRejectedError("source_file_not_utf8") from exc
    if not text.strip():
        raise WikiSourceImportRejectedError("source_file_empty")
    return text


def _is_binary_asset(path: Path) -> bool:
    return path.suffix.casefold() in {
        ".apng",
        ".avif",
        ".bmp",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".webp",
        ".pdf",
        ".zip",
    }


def _is_hidden_relative(root: Path, path: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _supplied_web_content(request: WikiSourceImportPreviewRequest) -> str:
    if request.text and request.text.strip():
        return request.text.strip()
    if request.html and request.html.strip():
        return _html_to_text(request.html)
    return ""


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|h[1-6]|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [re.sub(r"\s+", " ", html.unescape(line)).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _title_from_url(url: str) -> str:
    cleaned = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", url).strip("/")
    tail = cleaned.rsplit("/", 1)[-1] or cleaned
    title = re.sub(r"[-_]+", " ", tail).strip()
    return title.title() if title else "Imported URL"


def _asset_markdown(path: Path | None, *, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        "Asset import preview.",
    ]
    if path is not None:
        lines.extend(
            [
                "",
                f"- File name: `{path.name}`",
                f"- File size bytes: `{path.stat().st_size}`",
                f"- Extension: `{path.suffix.casefold()}`",
            ]
        )
    return "\n".join(lines).strip()


def _base_import_metadata(request: WikiSourceImportPreviewRequest, *, source_uri: str | None) -> dict[str, object]:
    return {
        "importer": "wiki_source_import",
        "source_kind": request.source_kind,
        "source_uri": source_uri,
    }


def _preview_text(content: str, limit: int = 2000) -> str:
    return content[:limit]


def _answer_preview(answer: str, limit: int = 320) -> str:
    compact = re.sub(r"\s+", " ", answer).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip()


def _json_list(values: list[str]) -> str:
    return json.dumps(_unique(values), ensure_ascii=True)


def _json_object(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_citations(citations: list[MemorySearchResult]) -> str:
    return json.dumps([citation.model_dump() for citation in citations], ensure_ascii=True)


def _load_json_list(value) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data if str(item).strip()] if isinstance(data, list) else []


def _load_citations(value) -> list[MemorySearchResult]:
    if not value:
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    citations: list[MemorySearchResult] = []
    for item in data:
        try:
            citations.append(MemorySearchResult.model_validate(item))
        except (TypeError, ValueError):
            continue
    return _dedupe_citations(citations)


def _load_review_findings(value) -> list[WikiIngestReviewFinding]:
    if not value:
        return []
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    findings: list[WikiIngestReviewFinding] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            findings.append(WikiIngestReviewFinding.model_validate(item))
        except (TypeError, ValueError):
            continue
    return findings


def _history_limit(limit: int) -> int:
    return min(max(int(limit), 1), 100)


def _unique(values) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
