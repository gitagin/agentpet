from .common import *
from .mapping import _map_query_archive_detail, _map_query_archive_item
from .utility import _answer_preview, _history_limit, _json_citations, _json_list, _unique

from .lint import _lint_query_archive
from .markdown import _citation_links, _default_query_title, _query_archive_section
from app.repositories.storage import VaultRepository
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.wiki_reconciler import bind_authoritative_wiki_page
from app.storage.markdown import read_markdown

class WikiQueryWorkflowMixin:

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

    def archive_query(
        self,
        request: QueryArchiveRequest,
        *,
        archive_id: str | None = None,
        action_marker: str | None = None,
    ) -> QueryArchiveResponse:
        lint = self.lint_query_archive(request)
        if not lint.passed:
            raise QueryArchiveRejectedError(lint.errors)
        archive_id = archive_id or new_id()
        title = request.title or _default_query_title(request.question)
        target_path = request.target_path or f"Wiki/Reports/{slugify_wiki_title(title)}.md"
        section = request.section or _query_archive_section(request)
        content = lint.markdown_preview
        if action_marker:
            content = f"{action_marker}\n{content}"
        page = self.wiki.write_page(
            WikiPageWriteRequest(
                title=title,
            content=content,
                operation="replace_section",
                target_path=target_path,
                section=section,
                tags=["query-archive", *request.tags],
                links=_citation_links(lint.normalized_citations),
                page_type="report",
                confidence="medium",
                sources=_unique(citation.relative_path for citation in lint.normalized_citations),
                inference=True,
                source_message_id=request.source_message_id or request.agent_run_id,
            ),
            action_marker=action_marker,
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
        with self.database.session() as conn:
            vault_id = VaultRepository(conn).upsert(
                self.wiki.writer.vault_root,
                name=self.wiki.writer.vault_root.name or "Vault",
            )
            conn.commit()
            graph = MemoryEntityGraphStore(conn)
            try:
                bind_authoritative_wiki_page(
                    graph,
                    vault_id=vault_id,
                    relative_path=page.relative_path,
                    parsed=read_markdown(
                        self.wiki.writer.vault_root.joinpath(*page.relative_path.split("/"))
                    ),
                )
            finally:
                graph.close()
        self.wiki.refresh_index()
        self.wiki.append_log(
            "query",
            title,
            f"- 问题：{request.question.strip()}\n- 页面：`{page.relative_path}`\n- 引用：{len(lint.normalized_citations)}",
            dedupe_marker=action_marker,
        )
        return QueryArchiveResponse(archive_id=archive_id, page=page, lint=lint)

    def list_query_archives(self, limit: int = 20) -> QueryArchiveHistoryResponse:
        capped_limit = _history_limit(limit)
        with self.database.session() as conn:
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
        with self.database.session() as conn:
            row = conn.execute(
                "SELECT * FROM wiki_query_archives WHERE id = ?",
                (archive_id,),
            ).fetchone()
        if row is None:
            raise QueryArchiveNotFoundError(archive_id)
        return _map_query_archive_detail(row)

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
        with self.database.session() as conn:
            conn.execute(
                """
                INSERT INTO wiki_query_archives(
                    id, question, answer_preview, answer, title, target_path, section,
                    tags_json, citations_json, citation_count, agent_run_id, source_message_id,
                    page_title, page_operation, page_status, index_job_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    question = excluded.question,
                    answer_preview = excluded.answer_preview,
                    answer = excluded.answer,
                    title = excluded.title,
                    target_path = excluded.target_path,
                    section = excluded.section,
                    tags_json = excluded.tags_json,
                    citations_json = excluded.citations_json,
                    citation_count = excluded.citation_count,
                    agent_run_id = excluded.agent_run_id,
                    source_message_id = excluded.source_message_id,
                    page_title = excluded.page_title,
                    page_operation = excluded.page_operation,
                    page_status = excluded.page_status,
                    index_job_id = excluded.index_job_id,
                    updated_at = excluded.updated_at
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
