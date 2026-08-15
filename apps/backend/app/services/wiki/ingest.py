from .common import *
from .common import _CachedIngestPreview
from .contracts import page_type_for_path
from .mapping import _map_plan
from .utility import _json_list, _json_object, _preview_text, _source_hash, _unique

from .import_handler import _import_preview_request
from .ingest_identity import wiki_ingest_intent_key
from .markdown import _ingest_log_details, _summary_from_source
from .planning import _build_ingest_page_plans
from .memory_closure import (
    WikiMemoryClosureError,
    finalize_wiki_memory_closure,
    prepare_wiki_memory_closure,
)
from app.repositories.storage import VaultRepository
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.wiki_reconciler import bind_authoritative_wiki_page
from app.storage.markdown import read_markdown

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
        self._cache_ingest_preview(
            preview_token,
            request,
            response,
            intent_key=wiki_ingest_intent_key(request, plans),
        )
        return response

    def preview_import(self, request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewResponse:
        return self.preview_ingest(_import_preview_request(request))

    def confirm_ingest(
        self,
        request: WikiIngestConfirmRequest,
        *,
        run_id: str | None = None,
    ) -> WikiIngestPreviewResponse:
        if not request.user_confirmed:
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_not_confirmed")
        cached = self._get_ingest_preview(request.preview_token)
        confirmed = self._confirm_cached_ingest(cached, run_id=run_id)
        self.discard_ingest_preview(request.preview_token)
        return confirmed

    def confirm_ingest_intent(
        self,
        intent_key: str,
        *,
        user_confirmed: bool,
        run_id: str | None = None,
    ) -> WikiIngestPreviewResponse:
        if not user_confirmed:
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_not_confirmed")
        preview_token, cached = self._get_ingest_preview_for_intent(intent_key)
        confirmed = self._confirm_cached_ingest(cached, run_id=run_id)
        self.discard_ingest_preview(preview_token)
        return confirmed

    def _confirm_cached_ingest(
        self,
        cached: _CachedIngestPreview,
        *,
        run_id: str | None,
    ) -> WikiIngestPreviewResponse:
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
            confirmed = preview.model_copy(
                update={
                    "run_id": run_id or preview.run_id,
                    "source_id": source_id,
                    "status": "planned",
                    "preview_token": None,
                }
            )
            conn.execute(
                """
                INSERT INTO wiki_workflow_runs(
                    id, workflow_type, source_id, status, request_json, result_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_id = excluded.source_id,
                    status = excluded.status,
                    request_json = excluded.request_json,
                    result_json = excluded.result_json,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id or preview.run_id,
                    "ingest",
                    source_id,
                    "planned",
                    ingest_request.model_dump_json(),
                    confirmed.model_dump_json(),
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
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title,
                        target_path = excluded.target_path,
                        operation = excluded.operation,
                        section = excluded.section,
                        content = excluded.content,
                        tags_json = excluded.tags_json,
                        links_json = excluded.links_json,
                        status = CASE
                            WHEN wiki_workflow_page_updates.status = 'written' THEN 'written'
                            ELSE excluded.status
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        f"{run_id or preview.run_id}:{sha256_hex(plan.target_path)[:24]}",
                        run_id or preview.run_id,
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
        return confirmed

    def apply_ingest(
        self,
        request: WikiIngestApplyRequest,
        *,
        action_marker: str | None = None,
    ) -> WikiIngestApplyResponse:
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
            source_row = (
                conn.execute("SELECT * FROM wiki_sources WHERE id = ?", (run["source_id"],)).fetchone()
                if run["source_id"] is not None
                else None
            )
            source_title = str(source_row["title"]) if source_row is not None else "来源"
            source_path = f"Wiki/Sources/{slugify_wiki_title(source_title)}.md"
            source_hash = str(source_row["source_hash"] or "") if source_row is not None else ""
            source_type = str(source_row["source_type"] or "manual") if source_row is not None else "manual"
            raw_content = str(
                source_row["raw_content"] or source_row["content_preview"] or ""
            ) if source_row is not None else ""
            try:
                source_metadata = json.loads(str(source_row["metadata_json"] or "{}")) if source_row is not None else {}
            except json.JSONDecodeError:
                source_metadata = {}

        if source_row is None or not run["source_id"] or not source_hash:
            raise WikiWorkflowError("Wiki ingest source record is missing")
        try:
            with self.database.session() as conn:
                closure = prepare_wiki_memory_closure(
                    conn,
                    vault_root=self.wiki.writer.vault_root,
                    source_id=str(run["source_id"]),
                    source_hash=source_hash,
                    source_title=source_title,
                    source_type=source_type,
                    raw_content=raw_content,
                    source_path=source_path,
                    source_metadata=source_metadata if isinstance(source_metadata, dict) else {},
                )
        except WikiMemoryClosureError as exc:
            with self.database.session() as conn:
                conn.execute(
                    "UPDATE wiki_workflow_runs SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                    (
                        "failed",
                        json.dumps(
                            {"pages_written": 0, "page_count": len(plans), "closure_error": exc.reason},
                            ensure_ascii=True,
                        ),
                        utc_now_iso(),
                        request.run_id,
                    ),
                )
            raise WikiWorkflowError(exc.reason) from exc

        results: list[WikiIngestPageResult] = []
        for plan in plans:
            try:
                content = plan.content
                if action_marker:
                    content = f"{action_marker}\n{content}"
                page_type = page_type_for_path(plan.target_path)
                page = self.wiki.write_page(
                    WikiPageWriteRequest(
                        title=plan.title,
                        content=content,
                        operation=plan.operation,  # type: ignore[arg-type]
                        target_path=plan.target_path,
                        section=plan.section,
                        tags=plan.tags,
                        links=plan.links,
                        page_type=page_type,
                        confidence="medium",
                        sources=[source_path],
                        **closure.page_metadata(),
                        inference=page_type != "source",
                        source_message_id=request.run_id,
                    ),
                    action_marker=action_marker,
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
        closure_result = None
        closure_error: str | None = None
        if run_status == "applied":
            try:
                with self.database.session() as conn:
                    closure_result = finalize_wiki_memory_closure(
                        conn,
                        preparation=closure,
                        vault_root=self.wiki.writer.vault_root,
                        source_type=source_type,
                        written_paths=tuple(
                            result.relative_path
                            for result in results
                            if result.status in {"created", "updated"}
                        ),
                    )
            except WikiMemoryClosureError as exc:
                run_status = "failed"
                closure_error = exc.reason
            except Exception as exc:
                run_status = "failed"
                closure_error = f"closure_finalize_failed:{exc.__class__.__name__}"
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
                dedupe_marker=action_marker,
            )
            log_appended = True
            lint_summary = self.wiki.core_lint_summary()
            with self.database.session() as conn:
                vault_id = VaultRepository(conn).upsert(
                    self.wiki.writer.vault_root,
                    name=self.wiki.writer.vault_root.name or "Vault",
                )
                conn.commit()
                graph = MemoryEntityGraphStore(conn)
                try:
                    for result in results:
                        if result.status not in {"created", "updated"}:
                            continue
                        page_path = self.wiki.writer.vault_root.joinpath(
                            *result.relative_path.split("/")
                        )
                        bind_authoritative_wiki_page(
                            graph,
                            vault_id=vault_id,
                            relative_path=result.relative_path,
                            parsed=read_markdown(page_path),
                            status="active" if run_status == "applied" else "quarantined",
                        )
                finally:
                    graph.close()
        with self.database.session() as conn:
            conn.execute(
                "UPDATE wiki_workflow_runs SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (
                    run_status,
                    json.dumps(
                        {
                            "pages_written": pages_written,
                            "page_count": len(results),
                            "closure": {
                                "active_fact_ids": list(closure_result.active_fact_ids),
                                "active_entity_ids": list(closure_result.active_entity_ids),
                                "artifact_binding_ids": list(closure_result.artifact_binding_ids),
                            }
                            if closure_result is not None
                            else {},
                            "closure_error": closure_error,
                        },
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
