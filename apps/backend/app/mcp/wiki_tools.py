from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.models.api import (
    MemorySearchResponse,
    QueryArchiveRequest,
    WikiIngestPreviewRequest,
    WikiLintRequest,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
    WikiSynthesizeRequest,
)
from app.services.memory import MarkdownWriteError
from app.services.wiki import WIKI_ROOT, WikiService, resolve_wiki_path


ToolPayload = Mapping[str, Any] | BaseModel


class RetrievalLike(Protocol):
    def search(
        self,
        query: str,
        top_k: int = 8,
        mode: str = "hybrid",
        source_scope: str = "knowledge_base",
    ) -> MemorySearchResponse | Awaitable[MemorySearchResponse]: ...


class WikiWorkflowLike(Protocol):
    def preview_ingest(
        self, request: WikiIngestPreviewRequest
    ) -> ToolPayload | Awaitable[ToolPayload]: ...

    def review_ingest(self, request) -> ToolPayload | Awaitable[ToolPayload]: ...

    def plan_query_archive(
        self, request: QueryArchiveRequest
    ) -> WikiQueryArchiveProposal | Awaitable[WikiQueryArchiveProposal]: ...

    def plan_synthesis(
        self, request: WikiSynthesizeRequest
    ) -> WikiSynthesisProposal | Awaitable[WikiSynthesisProposal]: ...

    def plan_lint(self, request: WikiLintRequest | None = None) -> ToolPayload | Awaitable[ToolPayload]: ...


class McpToolUnavailableError(Exception):
    code = "mcp_tool_unavailable"

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"{tool_name} is not configured.")


class WikiSearchInput(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=20)
    mode: str = "hybrid"
    source_scope: str = "knowledge_base"


class WikiReadPageInput(BaseModel):
    target_path: str = Field(min_length=1)


class WikiAgentContextInput(BaseModel):
    query: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    include_index: bool = True
    include_log: bool = False


@dataclass(frozen=True, slots=True)
class McpToolSpec:
    name: str
    description: str
    input_schema: type[BaseModel]
    call: Callable[..., Awaitable[dict[str, Any]]]

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
        }


@dataclass(slots=True)
class WikiMcpToolAdapter:
    wiki: WikiService
    workflow: WikiWorkflowLike | None = None
    retrieval: RetrievalLike | None = None

    def tools(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                name="search_wiki",
                description="Search indexed Wiki knowledge-base pages.",
                input_schema=WikiSearchInput,
                call=self.search_wiki,
            ),
            McpToolSpec(
                name="read_page",
                description="Read one Markdown page from Wiki/.",
                input_schema=WikiReadPageInput,
                call=self.read_page,
            ),
            McpToolSpec(
                name="plan_ingest",
                description="Plan Wiki ingest without writing target pages.",
                input_schema=WikiIngestPreviewRequest,
                call=self.plan_ingest,
            ),
            McpToolSpec(
                name="plan_query_archive",
                description="Plan query archive Markdown without writing it.",
                input_schema=QueryArchiveRequest,
                call=self.plan_query_archive,
            ),
            McpToolSpec(
                name="plan_synthesis",
                description="Plan Wiki synthesis Markdown without writing it.",
                input_schema=WikiSynthesizeRequest,
                call=self.plan_synthesis,
            ),
            McpToolSpec(
                name="plan_lint",
                description="Plan Wiki lint/report action without writing a report.",
                input_schema=WikiLintRequest,
                call=self.plan_lint,
            ),
            McpToolSpec(
                name="agent_context",
                description="Build compact Wiki context for an agent prompt.",
                input_schema=WikiAgentContextInput,
                call=self.agent_context,
            ),
        ]

    def tool_map(self) -> dict[str, McpToolSpec]:
        return {tool.name: tool for tool in self.tools()}

    async def search_wiki(
        self,
        query: str,
        top_k: int = 8,
        mode: str = "hybrid",
        source_scope: str = "knowledge_base",
    ) -> dict[str, Any]:
        if self.retrieval is None:
            raise McpToolUnavailableError("search_wiki")
        response = await _maybe_await(
            self.retrieval.search(
                query=query,
                top_k=top_k,
                mode=mode,
                source_scope=source_scope,
            )
        )
        return _dump_model(MemorySearchResponse.model_validate(response))

    async def read_page(self, target_path: str) -> dict[str, Any]:
        relative_path = _wiki_relative_path(target_path)
        target = self.wiki.writer.resolve_markdown_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(relative_path)
        return {
            "relative_path": relative_path,
            "content": target.read_text(encoding="utf-8"),
            "updated_at": target.stat().st_mtime,
        }

    async def plan_ingest(
        self,
        title: str,
        content: str,
        source_type: str = "manual",
        source_uri: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
        max_pages: int = 15,
        source_metadata: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        workflow = self._workflow("plan_ingest")
        request = WikiIngestPreviewRequest(
            title=title,
            content=content,
            source_type=source_type,
            source_uri=source_uri,
            tags=tags or [],
            links=links or [],
            max_pages=max_pages,
            source_metadata=source_metadata or {},
        )
        preview = await _maybe_await(workflow.preview_ingest(request))
        review = None
        reviewer = getattr(workflow, "review_ingest", None)
        if reviewer is not None and _has_run_id(preview):
            review = await _maybe_await(reviewer(_review_request(_run_id(preview))))
        payload = _dump_payload(preview)
        payload["proposal_type"] = "ingest"
        if review is not None:
            payload["review"] = _dump_payload(review)
        return payload

    async def plan_query_archive(
        self,
        question: str,
        answer: str,
        citations: list[dict[str, Any]] | None = None,
        title: str | None = None,
        target_path: str | None = None,
        section: str | None = None,
        tags: list[str] | None = None,
        agent_run_id: str | None = None,
        source_message_id: str | None = None,
        allow_mixed_sources: bool = False,
    ) -> dict[str, Any]:
        workflow = self._workflow("plan_query_archive")
        response = await _maybe_await(
            workflow.plan_query_archive(
                QueryArchiveRequest(
                    question=question,
                    answer=answer,
                    citations=citations or [],
                    title=title,
                    target_path=target_path,
                    section=section,
                    tags=tags or [],
                    agent_run_id=agent_run_id,
                    source_message_id=source_message_id,
                    allow_mixed_sources=allow_mixed_sources,
                )
            )
        )
        return _dump_payload(response)

    async def plan_synthesis(
        self,
        title: str,
        content: str,
        source_paths: list[str] | None = None,
        target_path: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
    ) -> dict[str, Any]:
        workflow = self._workflow("plan_synthesis")
        response = await _maybe_await(
            workflow.plan_synthesis(
                WikiSynthesizeRequest(
                    title=title,
                    content=content,
                    source_paths=source_paths or [],
                    target_path=target_path,
                    tags=tags or [],
                    links=links or [],
                )
            )
        )
        return _dump_payload(response)

    async def plan_lint(self, write_report: bool = False) -> dict[str, Any]:
        workflow = self._workflow("plan_lint")
        response = await _maybe_await(workflow.plan_lint(WikiLintRequest(write_report=write_report)))
        return _dump_payload(response)

    async def agent_context(
        self,
        query: str | None = None,
        top_k: int = 5,
        include_index: bool = True,
        include_log: bool = False,
    ) -> dict[str, Any]:
        pages = self.wiki.list_pages()
        payload: dict[str, Any] = {
            "schema": _dump_payload(self.wiki.get_schema_status()),
            "pages": [_dump_payload(page) for page in pages[:20]],
        }
        if include_index:
            payload["index"] = _dump_payload(self.wiki.get_index())
        if include_log:
            payload["log"] = _dump_payload(self.wiki.get_log(limit=10))
        if query:
            payload["search"] = await self.search_wiki(query=query, top_k=top_k)
        return payload

    def _workflow(self, tool_name: str) -> WikiWorkflowLike:
        if self.workflow is None:
            raise McpToolUnavailableError(tool_name)
        return self.workflow


def create_wiki_mcp_adapter(
    *,
    wiki: WikiService,
    workflow: WikiWorkflowLike | None = None,
    retrieval: RetrievalLike | None = None,
) -> WikiMcpToolAdapter:
    return WikiMcpToolAdapter(wiki=wiki, workflow=workflow, retrieval=retrieval)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _dump_model(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _dump_payload(value) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return _dump_model(value)
    if isinstance(value, Mapping):
        return dict(value)
    return _dump_model(type(value).model_validate(value))


def _wiki_relative_path(target_path: str) -> str:
    normalized = target_path.replace("\\", "/").strip("/")
    if not normalized.startswith(f"{WIKI_ROOT}/"):
        raise MarkdownWriteError("wiki read target_path must be under Wiki/")
    return resolve_wiki_path(normalized.removesuffix(".md"), normalized)


def _has_run_id(value) -> bool:
    return _run_id(value) is not None


def _run_id(value) -> str | None:
    if isinstance(value, BaseModel):
        return getattr(value, "run_id", None)
    if isinstance(value, Mapping):
        run_id = value.get("run_id")
        return str(run_id) if run_id is not None else None
    return getattr(value, "run_id", None)


def _review_request(run_id: str):
    from app.models.api import WikiIngestReviewRequest

    return WikiIngestReviewRequest(run_id=run_id)


__all__ = [
    "McpToolSpec",
    "McpToolUnavailableError",
    "WikiAgentContextInput",
    "WikiMcpToolAdapter",
    "WikiReadPageInput",
    "WikiSearchInput",
    "create_wiki_mcp_adapter",
]
