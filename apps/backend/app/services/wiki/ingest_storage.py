from .common import *
from .common import _CachedIngestPreview, _INGEST_PREVIEW_CACHE, _PREVIEW_TOKEN_TTL_SECONDS, _StoredIngestRun
from .mapping import _map_ingest_review, _map_plan
from .utility import _dumps_list


class WikiIngestStorageMixin:

    def _existing_source_id(self, source_hash: str) -> str | None:
        with self.database.session() as conn:
            row = conn.execute("SELECT id FROM wiki_sources WHERE source_hash = ?", (source_hash,)).fetchone()
        return str(row["id"]) if row is not None else None

    def _cache_ingest_preview(
        self,
        preview_token: str,
        request: WikiIngestPreviewRequest,
        response: WikiIngestPreviewResponse,
        *,
        intent_key: str,
    ) -> None:
        self._prune_expired_ingest_previews()
        _INGEST_PREVIEW_CACHE[preview_token] = _CachedIngestPreview(
            request=request,
            response=response,
            intent_key=intent_key,
            scope_key=self._ingest_preview_scope_key(),
            expires_at=time.monotonic() + _PREVIEW_TOKEN_TTL_SECONDS,
        )

    def _get_ingest_preview(self, preview_token: str) -> _CachedIngestPreview:
        self._prune_expired_ingest_previews()
        cached = _INGEST_PREVIEW_CACHE.get(preview_token)
        if (
            cached is None
            or cached.expires_at < time.monotonic()
            or cached.scope_key != self._ingest_preview_scope_key()
        ):
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_token_expired")
        return cached

    def ingest_intent_key(self, preview_token: str) -> str:
        return self._get_ingest_preview(preview_token).intent_key

    def _get_ingest_preview_for_intent(self, intent_key: str) -> tuple[str, _CachedIngestPreview]:
        self._prune_expired_ingest_previews()
        scope_key = self._ingest_preview_scope_key()
        matches = [
            (token, cached)
            for token, cached in _INGEST_PREVIEW_CACHE.items()
            if cached.intent_key == intent_key and cached.scope_key == scope_key
        ]
        if not matches:
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_token_expired")
        return max(matches, key=lambda item: item[1].expires_at)

    def discard_ingest_preview(self, preview_token: str) -> None:
        _INGEST_PREVIEW_CACHE.pop(preview_token, None)

    def _ingest_preview_scope_key(self) -> str:
        canonical = json.dumps(
            {
                "database": str(self.database.path.resolve()),
                "vault": str(self.wiki.writer.vault_root.resolve()),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256_hex(canonical)

    def _prune_expired_ingest_previews(self) -> None:
        now = time.monotonic()
        for token, cached in list(_INGEST_PREVIEW_CACHE.items()):
            if cached.expires_at < now:
                _INGEST_PREVIEW_CACHE.pop(token, None)

    def _load_ingest_run(self, run_id: str) -> _StoredIngestRun:
        with self.database.session() as conn:
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
            source_title=str(run["title"] or "未命名来源"),
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
        with self.database.session() as conn:
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

    def get_ingest_review(self, review_id: str) -> WikiIngestReviewResponse | None:
        with self.database.session() as conn:
            row = conn.execute(
                "SELECT * FROM wiki_ingest_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
        return _map_ingest_review(row) if row is not None else None

    def _insert_review(
        self,
        response: WikiIngestReviewResponse,
        *,
        review_id: str | None = None,
    ) -> WikiIngestReviewResponse:
        now = utc_now_iso()
        review_id = review_id or response.review_id or new_id()
        with self.database.session() as conn:
            conn.execute(
                """
                INSERT INTO wiki_ingest_reviews(
                    id, run_id, source_id, reviewer_agent_id, status, summary,
                    findings_json, recommended_targets_json, model_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    run_id = excluded.run_id,
                    source_id = excluded.source_id,
                    reviewer_agent_id = excluded.reviewer_agent_id,
                    status = excluded.status,
                    summary = excluded.summary,
                    findings_json = excluded.findings_json,
                    recommended_targets_json = excluded.recommended_targets_json,
                    model_error = excluded.model_error,
                    updated_at = excluded.updated_at
                """,
                (
                    review_id,
                    response.run_id,
                    self._source_id_for_run(response.run_id),
                    response.reviewer_agent_id,
                    response.status,
                    response.summary,
                    json.dumps([finding.model_dump() for finding in response.findings], ensure_ascii=True),
                    _dumps_list(response.recommended_targets),
                    response.model_error,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM wiki_ingest_reviews WHERE id = ?", (review_id,)).fetchone()
        return _map_ingest_review(row)

    def _source_id_for_run(self, run_id: str) -> str | None:
        with self.database.session() as conn:
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
        target_content_hash: str | None = None,
    ) -> None:
        with self.database.session() as conn:
            conn.execute(
                """
                UPDATE wiki_workflow_page_updates
                SET status = ?, index_job_id = ?, error = ?, updated_at = ?,
                    target_content_hash = COALESCE(?, target_content_hash)
                WHERE id = ?
                """,
                (status, index_job_id, error, utc_now_iso(), target_content_hash, page_update_id),
            )
            conn.commit()
