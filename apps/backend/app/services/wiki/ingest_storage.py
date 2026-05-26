from .common import *
from .common import _CachedIngestPreview, _INGEST_PREVIEW_CACHE, _PREVIEW_TOKEN_TTL_SECONDS, _StoredIngestRun
from .mapping import _map_ingest_review, _map_plan
from .review import _complete_model, _deterministic_review_response, _parse_model_review, _review_system_prompt, _review_user_message
from .utility import _json_list, _json_object, _preview_text

from .import_handler import _import_preview_request
from .markdown import _ingest_log_details
from .planning import _build_ingest_page_plans

class WikiIngestStorageMixin:

    def _existing_source_id(self, source_hash: str) -> str | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT id FROM wiki_sources WHERE source_hash = ?", (source_hash,)).fetchone()
        return str(row["id"]) if row is not None else None

    def _cache_ingest_preview(
        self,
        preview_token: str,
        request: WikiIngestPreviewRequest,
        response: WikiIngestPreviewResponse,
    ) -> None:
        self._prune_expired_ingest_previews()
        _INGEST_PREVIEW_CACHE[preview_token] = _CachedIngestPreview(
            request=request,
            response=response,
            expires_at=time.monotonic() + _PREVIEW_TOKEN_TTL_SECONDS,
        )

    def _pop_ingest_preview(self, preview_token: str) -> _CachedIngestPreview:
        self._prune_expired_ingest_previews()
        cached = _INGEST_PREVIEW_CACHE.pop(preview_token, None)
        if cached is None or cached.expires_at < time.monotonic():
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_token_expired")
        return cached

    def _prune_expired_ingest_previews(self) -> None:
        now = time.monotonic()
        for token, cached in list(_INGEST_PREVIEW_CACHE.items()):
            if cached.expires_at < now:
                _INGEST_PREVIEW_CACHE.pop(token, None)

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
