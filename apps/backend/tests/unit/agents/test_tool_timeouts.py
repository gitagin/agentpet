from __future__ import annotations

import asyncio

import pytest

from app.agents.exceptions import AgentToolTimeoutError
from app.agents.tools import AgentToolSet, TOOL_TIMEOUTS
from app.models.api import WikiIngestPreviewResponse


class SlowRetrieval:
    async def search(self, *args, **kwargs):
        await asyncio.sleep(1)


class SlowMemory:
    async def create_proposal(self, *args, **kwargs):
        await asyncio.sleep(1)


class SlowTasks:
    async def create(self, *args, **kwargs):
        await asyncio.sleep(1)


class SlowWiki:
    async def manage_page(self, *args, **kwargs):
        await asyncio.sleep(1)


class SlowWikiWorkflow:
    async def preview_ingest(self, *args, **kwargs):
        await asyncio.sleep(1)
        return WikiIngestPreviewResponse(
            run_id="run-1",
            source_id="source-1",
            source_hash="hash-1",
            status="planned",
            summary="summary",
            page_plans=[],
        )

    async def review_ingest(self, *args, **kwargs):
        await asyncio.sleep(1)

    async def plan_query_archive(self, *args, **kwargs):
        await asyncio.sleep(1)

    async def plan_synthesis(self, *args, **kwargs):
        await asyncio.sleep(1)

    async def plan_lint(self, *args, **kwargs):
        await asyncio.sleep(1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "toolset", "method_name", "kwargs"),
    [
        ("search_memory", AgentToolSet(retrieval=SlowRetrieval()), "search_memory", {"query": "apple"}),
        ("propose_memory", AgentToolSet(memory=SlowMemory()), "propose_memory", {"content": "用户喜欢苹果"}),
        ("plan_wiki_ingest", AgentToolSet(wiki_workflow=SlowWikiWorkflow()), "plan_wiki_ingest", {"title": "Ingest", "content": "content"}),
        ("plan_wiki_query_archive", AgentToolSet(wiki_workflow=SlowWikiWorkflow()), "plan_wiki_query_archive", {"question": "Q?", "answer": "A"}),
        ("plan_wiki_synthesis", AgentToolSet(wiki_workflow=SlowWikiWorkflow()), "plan_wiki_synthesis", {"title": "Synthesis", "content": "content"}),
        ("plan_wiki_lint", AgentToolSet(wiki_workflow=SlowWikiWorkflow()), "plan_wiki_lint", {}),
        ("manage_wiki_page", AgentToolSet(wiki=SlowWiki()), "manage_wiki_page", {"title": "Page", "content": "content"}),
        ("create_task", AgentToolSet(tasks=SlowTasks()), "create_task", {"title": "Buy apples"}),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
async def test_tool_methods_raise_timeout(monkeypatch, tool_name, toolset, method_name, kwargs) -> None:
    monkeypatch.setitem(TOOL_TIMEOUTS, tool_name, 0.01)

    with pytest.raises(AgentToolTimeoutError) as exc:
        await getattr(toolset, method_name)(**kwargs)

    assert exc.value.tool_name == tool_name
    assert exc.value.timeout_seconds == 0.01
    assert str(exc.value) == f"Tool '{tool_name}' timed out after 0.01s"
