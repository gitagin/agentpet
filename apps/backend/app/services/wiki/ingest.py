import re

from .common import *
from .common import _CachedIngestPreview
from .contracts import page_type_for_path
from .mapping import _map_plan
from .utility import _dumps_list, _dumps_object, _preview_text, _source_hash, _unique

from .import_handler import _import_preview_request
from .ingest_identity import (
    _identity_metadata_equal,
    assert_ingest_source_matches,
    assert_ingest_source_scope,
    source_identity_v2_enabled,
    wiki_ingest_intent_key,
)
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
from .ingest_identity import assert_independent_ingest_source

class WikiIngestWorkflowMixin(WikiIngestReviewMixin, WikiIngestStorageMixin):

    async def compile_ingest(self, request: WikiIngestPreviewRequest) -> WikiIngestPreviewResponse:
        from .compiler import COMPILER_KEY, compile_source

        assert_independent_ingest_source(request.source_type)
        _, model = self._resolve_review_model(None)
        if model is None:
            return self.preview_ingest(request.model_copy(update={"source_metadata": {
                **request.source_metadata, "compilation_status": "model_not_configured",
            }}))
        clean_metadata = {k: v for k, v in request.source_metadata.items() if k != COMPILER_KEY}
        request = request.model_copy(update={"source_metadata": clean_metadata})
        plans, summary, metadata = await compile_source(self.wiki, model, request, database=self.database)
        metadata["compilation_status"] = "compiled"
        return self._preview_with_plans(request.model_copy(update={"source_metadata": metadata}), plans, summary)

    async def compile_import(self, request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewResponse:
        return await self.compile_ingest(_import_preview_request(request))

    def preview_ingest(self, request: WikiIngestPreviewRequest) -> WikiIngestPreviewResponse:
        from .compiler import COMPILER_KEY

        request = request.model_copy(update={"source_metadata": {
            k: v for k, v in request.source_metadata.items() if k != COMPILER_KEY
        }})
        return self._preview_with_plans(
            request, _build_ingest_page_plans(request, _source_hash(request.content)),
            _summary_from_source(request.content),
        )

    def _preview_with_plans(self, request, plans, summary) -> WikiIngestPreviewResponse:
        self.wiki.ensure_core_files()
        source_hash = _source_hash(request.content)
        source_id = self._existing_source_id(source_hash) or new_id()
        run_id = new_id()
        preview_token = new_id()
        response = WikiIngestPreviewResponse(
            run_id=run_id,
            source_id=source_id,
            source_hash=source_hash,
            status="preview",
            page_plans=plans,
            summary=summary,
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
        from .compiler import COMPILER_KEY, assert_snapshots_current

        compilation = ingest_request.source_metadata.get(COMPILER_KEY, {})
        if compilation:
            assert_snapshots_current(self.wiki, compilation["context_hashes"], database=self.database)
        with self.database.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing_run = conn.execute(
                "SELECT * FROM wiki_workflow_runs WHERE id = ?", (run_id or preview.run_id,)
            ).fetchone()
            if existing_run is not None:
                existing_source = conn.execute(
                    "SELECT * FROM wiki_sources WHERE id = ?", (existing_run["source_id"],)
                ).fetchone()
                original_request = self._validated_ingest_request(
                    conn, existing_run["request_json"], existing_source
                )
                if (
                    existing_run["workflow_type"] != "ingest"
                    or existing_run["status"] != "planned"
                    or original_request != ingest_request
                ):
                    raise WikiWorkflowError("wiki_ingest_run_identity_conflict")
            source_id = preview.source_id
            v2_enabled = source_identity_v2_enabled(conn)
            matched: sqlite3.Row | None = None
            # 身份全等但内容变化 → (新 hash, 新 raw, 新 preview),触发版本 bump 写账本
            bumped: tuple[str, str, str] | None = None
            if v2_enabled:
                # v2 身份规则(设计 §5.1-3):身份全等+内容全等→复用;身份全等+内容变→
                # 同 id 版本 bump(旧内容快照入 wiki_source_version_history);身份无匹配→
                # 新建行(同 hash 多行合法);多候选命中同身份或 legacy 行身份不可判定→
                # fail closed(复用既有错误码,不新增)。
                candidates = conn.execute(
                    """
                    SELECT s.* FROM wiki_sources s
                    LEFT JOIN vaults v ON v.id = s.vault_id
                    WHERE s.source_type = ?
                      AND COALESCE(s.source_uri, '') = COALESCE(?, '')
                      AND (s.vault_id IS NULL OR v.root_path = ?)
                    """,
                    (
                        ingest_request.source_type,
                        ingest_request.source_uri,
                        str(self.wiki.writer.vault_root.resolve()),
                    ),
                ).fetchall()
                identity_matches = [
                    row for row in candidates if _identity_metadata_equal(row, ingest_request)
                ]
                if len(identity_matches) > 1:
                    raise WikiWorkflowError("wiki_ingest_source_identity_conflict")
                if identity_matches:
                    matched = identity_matches[0]
                    assert_ingest_source_scope(conn, matched, self.wiki.writer.vault_root)
                    if (
                        str(matched["source_hash"]) != preview.source_hash
                        or (matched["raw_content"] or None) != ingest_request.content
                    ):
                        bumped = (
                            preview.source_hash,
                            ingest_request.content,
                            _preview_text(ingest_request.content),
                        )
                else:
                    # 身份无匹配 → 新建行:preview.source_id 是 hash 召回得到的旧行 id,
                    # 不能复用,必须分配全新 id(同 hash 多行各自独立)。
                    source_id = new_id()
            else:
                # legacy 行为(hash-first 复用,与 v2 开关关闭时完全一致)
                existing = conn.execute(
                    "SELECT * FROM wiki_sources WHERE source_hash = ?",
                    (preview.source_hash,),
                ).fetchone()
                if existing is not None:
                    assert_ingest_source_scope(conn, existing, self.wiki.writer.vault_root)
                    assert_ingest_source_matches(existing, ingest_request)
                    matched = existing
            if matched is not None:
                source_id = str(matched["id"])
                if bumped is not None:
                    # 版本 bump:旧内容快照入账本,同 id 原地更新内容与版本号
                    conn.execute(
                        """
                        INSERT INTO wiki_source_version_history(
                            source_id, source_version, content_hash, content_preview,
                            raw_content, reason, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
                            matched["source_version"],
                            str(matched["source_hash"]),
                            matched["content_preview"],
                            matched["raw_content"],
                            "content_updated",
                            now,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE wiki_sources
                        SET source_hash = ?, raw_content = ?, content_preview = ?,
                            source_version = source_version + 1, updated_at = ?
                        WHERE id = ?
                        """,
                        (*bumped, now, source_id),
                    )
            else:
                vault_id = VaultRepository(conn).upsert(self.wiki.writer.vault_root)
                conn.execute(
                    """
                    INSERT INTO wiki_sources(
                        id, source_hash, title, source_type, source_uri, content_preview,
                        raw_content, tags_json, links_json, metadata_json, created_at, updated_at,
                        vault_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        preview.source_hash,
                        ingest_request.title,
                        ingest_request.source_type,
                        ingest_request.source_uri,
                        _preview_text(ingest_request.content),
                        ingest_request.content,
                        _dumps_list(ingest_request.tags),
                        _dumps_list(ingest_request.links),
                        _dumps_object(ingest_request.source_metadata),
                        now,
                        now,
                        vault_id,
                    ),
                )
            if v2_enabled:
                # v2 页面路径统一(设计 §2.4/§2.5):来源页统一为 {slug}-{source_id[:12]}.md,
                # 正文注入「来源标识」双标记(版本号随行),旧「来源哈希」标记继续保留;
                # 派生页内容中引用的旧来源路径同步替换为新路径。
                version_row = conn.execute(
                    "SELECT source_version FROM wiki_sources WHERE id = ?", (source_id,)
                ).fetchone()
                source_version = int(version_row["source_version"]) if version_row else 1
                legacy_target: str | None = None
                v2_target: str | None = None
                rewritten_plans = []
                for plan in preview.page_plans:
                    if (
                        legacy_target is None
                        and plan.target_path.startswith("Wiki/Sources/")
                        and plan.target_path.endswith(".md")
                    ):
                        slug = plan.target_path[len("Wiki/Sources/"):-len(".md")]
                        slug = re.sub(r"-[0-9a-f]{12}$", "", slug)
                        legacy_target = plan.target_path
                        v2_target = f"Wiki/Sources/{slug}-{source_id[:12]}.md"
                        content = plan.content
                        if "- 来源标识：" not in content:
                            content = content.replace(
                                "- 来源哈希：",
                                "- 来源标识：`" + source_id + "`（版本 " + str(source_version) + "）\n- 来源哈希：",
                                1,
                            )
                        plan = plan.model_copy(update={"target_path": v2_target, "content": content})
                    elif v2_target is not None and plan.target_path != legacy_target:
                        plan = plan.model_copy(update={
                            "content": plan.content.replace(legacy_target, v2_target),
                        })
                    rewritten_plans.append(plan)
                preview = preview.model_copy(update={"page_plans": rewritten_plans})
            version_row = conn.execute(
                "SELECT source_version FROM wiki_sources WHERE id = ?", (source_id,)
            ).fetchone()
            confirmed = preview.model_copy(
                update={
                    "run_id": run_id or preview.run_id,
                    "source_id": source_id,
                    "status": "planned",
                    "preview_token": None,
                    "source_version": int(version_row["source_version"]) if version_row else None,
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
                        tags_json, links_json, status, target_content_hash, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        target_content_hash = excluded.target_content_hash,
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
                        _dumps_list(plan.tags),
                        _dumps_list(plan.links),
                        "planned",
                        plan.target_content_hash or self.wiki.writer.current_hash(plan.target_path) or WIKI_TARGET_ABSENT_HASH,
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
            ingest_request = self._validated_ingest_request(conn, run["request_json"], source_row)
            assert_independent_ingest_source(ingest_request.source_type)
            source_title = ingest_request.title
            # 来源页路径以运行记录为准(v2 下已统一为 {slug}-{source_id[:12]}.md)
            source_path = next(
                (
                    str(row["target_path"])
                    for row in rows
                    if str(row["target_path"]).startswith("Wiki/Sources/")
                ),
                f"Wiki/Sources/{slugify_wiki_title(source_title)}.md",
            )
            v2_enabled = source_identity_v2_enabled(conn)
            source_id_for_path = str(run["source_id"])
            source_hash = str(source_row["source_hash"])
            source_type = ingest_request.source_type
            raw_content = ingest_request.content
            source_metadata = ingest_request.source_metadata

        from .compiler import COMPILER_KEY, CompilerError, assert_snapshots_current

        compilation = source_metadata.get(COMPILER_KEY, {})
        if compilation:
            source_path = compilation["source_path"]
            if v2_enabled and source_path not in approved:
                # v2:来源页路径已统一为 source_id 后缀,编译元数据中的旧 hash12 路径同步映射
                slug = source_path[len("Wiki/Sources/"):-len(".md")]
                slug = re.sub(r"-[0-9a-f]{12}$", "", slug)
                mapped = f"Wiki/Sources/{slug}-{source_id_for_path[:12]}.md"
                if mapped in approved:
                    source_path = mapped
            if source_path not in approved:
                raise CompilerError("wiki_compilation_source_must_be_approved")
            # Written targets use their persisted post-write hash on retry; other read dependencies
            # must still match the snapshot used to generate the proposal.
            expected_hashes = dict(compilation["context_hashes"])
            for row in rows:
                if row["status"] == "written":
                    expected_hashes[str(row["target_path"])] = str(row["target_content_hash"])
            assert_snapshots_current(self.wiki, expected_hashes, database=self.database)
            plans.sort(key=lambda plan: plan.target_path != source_path)
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
                compiled_meta = compilation.get("pages", {}).get(plan.target_path, {})
                metadata = closure.page_metadata()
                for key in ("entity_ids", "fact_ids", "evidence_ids"):
                    metadata[key] = _unique([*compiled_meta.get(key, []), *metadata[key]])
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
                        sources=compiled_meta.get("sources", [source_path]),
                        disputed=compiled_meta.get("disputed", False),
                        aliases=compiled_meta.get("aliases", []),
                        authors=compiled_meta.get("authors", []),
                        contributors=compiled_meta.get("contributors", []),
                        expiry=compiled_meta.get("expiry"),
                        wiki_id=compiled_meta.get("wiki_id"),
                        **metadata,
                        inference=page_type != "source",
                        source_message_id=request.run_id,
                        target_content_hash=plan.target_content_hash,
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
                self._update_page_result(
                    plan.id,
                    status="written",
                    index_job_id=page.index_job_id,
                    error=None,
                    target_content_hash=self.wiki.writer.current_hash(page.relative_path),
                )
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
            if compilation and plan.target_path == source_path and result.status == "failed":
                break

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
                            "publication": {"status": "pending" if run_status == "applied" else "not_eligible"},
                        },
                        ensure_ascii=True,
                    ),
                    utc_now_iso(),
                    request.run_id,
                ),
            )
            conn.commit()
        if run_status == "applied":
            from .publication import WikiPublicationService
            from .generations import WikiGenerationError

            publication = None
            try:
                WikiPublicationService(self.database, self.wiki).publish_ingest(request.run_id)
            except (WikiGenerationError, WikiWorkflowError, WikiMemoryClosureError) as exc:
                publication = {"status": "blocked", "reason": str(exc)}
            except Exception as exc:
                publication = {"status": "failed", "reason": exc.__class__.__name__}
            if publication is not None:
                with self.database.session() as conn:
                    conn.execute(
                        """UPDATE wiki_workflow_runs
                           SET result_json = json_set(result_json, '$.publication', json(?)),
                               updated_at = ? WHERE id = ?
                             AND COALESCE(json_extract(result_json, '$.publication.status'), '') != 'published'""",
                        (json.dumps(publication), utc_now_iso(), request.run_id),
                    )
        return WikiIngestApplyResponse(
            run_id=request.run_id,
            status=run_status,
            pages_written=pages_written,
            page_results=results,
            index_updated=index_updated,
            log_appended=log_appended,
            lint_summary=lint_summary,
        )
