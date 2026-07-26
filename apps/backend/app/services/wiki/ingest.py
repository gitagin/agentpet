from .common import *
from .mapping import _map_plan
from .utility import _json_list, _json_object, _preview_text, _source_hash, _unique

from .import_handler import _import_preview_request
from .markdown import _ingest_log_details, _summary_from_source
from .planning import _build_ingest_page_plans

from .ingest_review import WikiIngestReviewMixin
from .ingest_storage import WikiIngestStorageMixin

class WikiIngestWorkflowMixin(WikiIngestReviewMixin, WikiIngestStorageMixin):

    def preview_ingest(self, request: WikiIngestPreviewRequest) -> WikiIngestPreviewResponse:
        self.wiki.ensure_core_files()
        source_hash = _source_hash(request.content)
        source_id = self._existing_source_id(source_hash) or new_id()
        run_id = new_id()
        preview_token = new_id()
        plans = _build_ingest_page_plans(request, source_hash)
        response = WikiIngestPreviewResponse(
            run_id=run_id,
            source_id=source_id,
            source_hash=source_hash,
            status="preview",
            page_plans=plans,
            summary=_summary_from_source(request.content),
            source_metadata=request.source_metadata,
            preview_token=preview_token,
        )
        self._cache_ingest_preview(preview_token, request, response)
        return response

    def preview_import(self, request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewResponse:
        return self.preview_ingest(_import_preview_request(request))

    def confirm_ingest(self, request: WikiIngestConfirmRequest) -> WikiIngestPreviewResponse:
        if not request.user_confirmed:
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_not_confirmed")
        cached = self._pop_ingest_preview(request.preview_token)
        now = utc_now_iso()
        ingest_request = cached.request
        preview = cached.response
        with self.database.session() as conn:
            existing = conn.execute(
                "SELECT id FROM wiki_sources WHERE source_hash = ?",
                (preview.source_hash,),
            ).fetchone()
            source_id = preview.source_id
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
                        ingest_request.title,
                        ingest_request.source_type,
                        ingest_request.source_uri,
                        _preview_text(ingest_request.content),
                        ingest_request.content,
                        _json_list(ingest_request.tags),
                        _json_list(ingest_request.links),
                        _json_object(ingest_request.source_metadata),
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
                        preview.source_hash,
                        ingest_request.title,
                        ingest_request.source_type,
                        ingest_request.source_uri,
                        _preview_text(ingest_request.content),
                        ingest_request.content,
                        _json_list(ingest_request.tags),
                        _json_list(ingest_request.links),
                        _json_object(ingest_request.source_metadata),
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
                    preview.run_id,
                    "ingest",
                    source_id,
                    "planned",
                    ingest_request.model_dump_json(),
                    json.dumps({"source_hash": preview.source_hash}, ensure_ascii=True),
                    now,
                    now,
                ),
            )
            for plan in preview.page_plans:
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
                        preview.run_id,
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
        return preview.model_copy(update={"source_id": source_id, "status": "planned", "preview_token": None})

    def apply_ingest(self, request: WikiIngestApplyRequest) -> WikiIngestApplyResponse:
        with self.database.session() as conn:
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
        with self.database.session() as conn:
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
