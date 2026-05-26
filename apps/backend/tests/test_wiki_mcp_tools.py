from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.mcp.wiki_tools import McpToolUnavailableError, create_wiki_mcp_adapter
from app.models.api import (
    MemorySearchResponse,
    MemorySearchResult,
)
from app.services.memory import MarkdownWriteError, SafeMarkdownWriter
from app.services.wiki import WikiService
from app.services.wiki_workflows import WikiWorkflowService
from app.storage.database import Database, MigrationRunner


class FakeRetrieval:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def search(
        self,
        query: str,
        top_k: int = 8,
        mode: str = "hybrid",
        source_scope: str = "knowledge_base",
    ) -> MemorySearchResponse:
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "mode": mode,
                "source_scope": source_scope,
            }
        )
        return MemorySearchResponse(results=[_citation("Wiki/Sources/Runtime.md")])


def test_wiki_mcp_adapter_exposes_expected_tool_shapes(tmp_path: Path) -> None:
    adapter = create_wiki_mcp_adapter(wiki=WikiService(SafeMarkdownWriter(tmp_path)))

    tools = adapter.tool_map()

    assert set(tools) == {
        "search_wiki",
        "read_page",
        "plan_ingest",
        "plan_query_archive",
        "plan_synthesis",
        "plan_lint",
        "agent_context",
    }
    descriptor = tools["plan_ingest"].descriptor()
    assert descriptor["name"] == "plan_ingest"
    assert descriptor["input_schema"]["type"] == "object"
    assert "properties" in descriptor["input_schema"]


def test_wiki_mcp_search_delegates_to_async_retrieval(tmp_path: Path) -> None:
    retrieval = FakeRetrieval()
    adapter = create_wiki_mcp_adapter(
        wiki=WikiService(SafeMarkdownWriter(tmp_path)),
        retrieval=retrieval,
    )

    result = asyncio.run(adapter.search_wiki("runtime", top_k=3, mode="fts"))

    assert retrieval.calls == [
        {
            "query": "runtime",
            "top_k": 3,
            "mode": "fts",
            "source_scope": "knowledge_base",
        }
    ]
    assert result["results"][0]["relative_path"] == "Wiki/Sources/Runtime.md"


def test_wiki_mcp_read_page_is_limited_to_wiki_paths(tmp_path: Path) -> None:
    wiki = WikiService(SafeMarkdownWriter(tmp_path))
    wiki.write_page(
        _write_request(
            title="Runtime",
            content="Runtime page content.",
            target_path="Wiki/Runtime.md",
        )
    )
    adapter = create_wiki_mcp_adapter(wiki=wiki)

    result = asyncio.run(adapter.read_page("Wiki/Runtime.md"))

    assert result["relative_path"] == "Wiki/Runtime.md"
    assert "Runtime page content." in result["content"]
    with pytest.raises(MarkdownWriteError):
        asyncio.run(adapter.read_page("../Runtime.md"))
    with pytest.raises(MarkdownWriteError):
        asyncio.run(adapter.read_page("Memories/Runtime.md"))


def test_wiki_mcp_plan_tools_do_not_write_markdown_pages(tmp_path: Path) -> None:
    vault_root = tmp_path / "Vault"
    adapter = create_wiki_mcp_adapter(
        wiki=WikiService(SafeMarkdownWriter(vault_root)),
        workflow=_workflow_service(tmp_path / "state.sqlite3", vault_root),
    )

    ingest = asyncio.run(
        adapter.plan_ingest(
            title="Runtime Source",
            content="# Runtime Source\n\nFact for [[Runtime]].",
            links=["Runtime"],
            max_pages=2,
        )
    )
    archive = asyncio.run(
        adapter.plan_query_archive(
            question="What is runtime?",
            answer="Runtime is a Wiki concept.",
            citations=[_citation("Wiki/Sources/Runtime-Source.md").model_dump()],
        )
    )
    synthesis = asyncio.run(
        adapter.plan_synthesis(
            title="Runtime Synthesis",
            content="Runtime source supports synthesis.",
            source_paths=["Wiki/Sources/Runtime-Source.md"],
        )
    )
    lint = asyncio.run(adapter.plan_lint(write_report=True))

    assert ingest["proposal_type"] == "ingest"
    assert ingest["review"]["status"] == "model_not_configured"
    assert archive["proposal_type"] == "query_archive"
    assert synthesis["proposal_type"] == "synthesize"
    assert lint["proposal_type"] == "lint"
    assert not (vault_root / "Wiki" / "Sources" / "Runtime-Source.md").exists()
    assert not (vault_root / "Wiki" / "Reports").exists()
    assert not (vault_root / "Wiki" / "Syntheses").exists()


def test_wiki_mcp_agent_context_can_include_index_log_and_search(tmp_path: Path) -> None:
    wiki = WikiService(SafeMarkdownWriter(tmp_path))
    wiki.write_page(
        _write_request(
            title="Runtime",
            content="Runtime page content.",
            target_path="Wiki/Runtime.md",
        )
    )
    wiki.refresh_index()
    wiki.append_log("test", "Runtime", "- created")
    adapter = create_wiki_mcp_adapter(wiki=wiki, retrieval=FakeRetrieval())

    context = asyncio.run(
        adapter.agent_context(query="runtime", include_index=True, include_log=True)
    )

    assert context["schema"]["path"] == "Wiki/AGENTS.md"
    assert context["pages"][0]["relative_path"] == "Wiki/Runtime.md"
    assert any(entry["relative_path"] == "Wiki/Runtime.md" for entry in context["index"]["entries"])
    assert context["log"]["entries"][0]["operation"] == "test"
    assert context["search"]["results"][0]["relative_path"] == "Wiki/Sources/Runtime.md"


def test_wiki_mcp_search_reports_unavailable_when_retrieval_missing(tmp_path: Path) -> None:
    adapter = create_wiki_mcp_adapter(wiki=WikiService(SafeMarkdownWriter(tmp_path)))

    with pytest.raises(McpToolUnavailableError) as exc:
        asyncio.run(adapter.search_wiki("runtime"))

    assert exc.value.tool_name == "search_wiki"


class _AsyncWikiWorkflowService:
    def __init__(self, service: WikiWorkflowService) -> None:
        self.service = service

    async def preview_ingest(self, request):
        return self.service.preview_ingest(request)

    async def confirm_ingest(self, request):
        return self.service.confirm_ingest(request)

    async def review_ingest(self, request):
        return await self.service.review_ingest(request)

    async def plan_query_archive(self, request):
        return self.service.plan_query_archive(request)

    async def plan_synthesis(self, request):
        return self.service.plan_synthesis(request)

    async def plan_lint(self, request):
        return self.service.plan_lint(request)


def _workflow_service(db_path: Path, vault_root: Path) -> _AsyncWikiWorkflowService:
    database = Database(db_path)
    MigrationRunner(database).apply()
    wiki = WikiService(SafeMarkdownWriter(vault_root), index_refresh=lambda _path: "scheduled:test-vault")
    return _AsyncWikiWorkflowService(WikiWorkflowService(database, wiki))


def _citation(relative_path: str) -> MemorySearchResult:
    return MemorySearchResult(
        note_id=f"note-{relative_path}",
        chunk_id=f"chunk-{relative_path}",
        relative_path=relative_path,
        title=Path(relative_path).stem,
        heading="Summary",
        snippet="Relevant snippet.",
        score=1.0,
        source_scope="knowledge_base",
        retrieval_mode="fts",
    )


def _write_request(**kwargs):
    from app.models.api import WikiPageWriteRequest

    return WikiPageWriteRequest(**kwargs)
