import asyncio

import pytest
from pydantic import ValidationError

from app.agents.tools import AgentToolName, AgentToolSet, AgentToolUnavailableError
from app.api.services import factory
from app.api.services.adapters import RuntimeWikiReadAdapter
from app.services.wiki.generations import WikiGenerationError, WikiGenerationStore
from app.services.wiki.publication import WikiPublicationService
from app.services.wiki.snapshot_reader import WikiSnapshotReader
from tests.test_wiki_publication import published


@pytest.fixture
def read_tools(published, monkeypatch):
    service, vault, _, generation = published
    reader = WikiSnapshotReader(service.database, service.wiki, authorize=lambda v, p: v == vault)
    monkeypatch.setattr(factory, "wiki_snapshot_reader_dependency", lambda request: reader)
    events = []
    tools = AgentToolSet(wiki_reader=RuntimeWikiReadAdapter(object()), observer=events.append)
    return tools, events, service, vault, generation


def test_registered_read_tools_search_then_read_without_writes(read_tools):
    tools, events, service, _, generation = read_tools
    selected = tools.allowed_tools((AgentToolName.SEARCH_WIKI_PAGES, AgentToolName.READ_WIKI_PAGE))
    assert [tool.name for tool in selected] == ["search_wiki_pages", "read_wiki_page"]
    with service.database.session() as conn:
        before = conn.execute("SELECT COUNT(*) FROM wiki_workflow_runs").fetchone()[0]
    result = asyncio.run(selected[0].ainvoke({"query": "supplier"}))
    assert result.evidence_role == "navigation_only"
    candidate = next(c for c in result.candidates if c["relative_path"] == "Wiki/Concepts/Product-P.md")
    page = asyncio.run(selected[1].ainvoke({
        "relative_path": candidate["relative_path"], "generation": generation,
        "expected_version": candidate["content_hash"], "section": "定义",
    }))
    assert page.generation == generation
    assert "Product P uses supplier A." in page.content
    assert [event.name for event in events] == ["search_wiki_pages", "read_wiki_page"]
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_runs").fetchone()[0] == before


def test_agent_cannot_repin_after_publication(read_tools):
    tools, _, service, vault, generation = read_tools
    asyncio.run(tools.search_wiki_pages("supplier"))
    store = WikiGenerationStore(service.database)
    newer = store.stage(vault, base_generation=generation, changes={})
    store.promote(vault, newer, validate=WikiPublicationService(service.database, service.wiki)._validate)
    with pytest.raises(WikiGenerationError, match="version_mismatch"):
        asyncio.run(tools.read_wiki_page("Wiki/Concepts/Product-P.md", generation=newer))
    page = asyncio.run(tools.read_wiki_page("Wiki/Concepts/Product-P.md"))
    assert page.generation == generation


def test_read_tool_rechecks_source_after_search(read_tools):
    tools, events, service, _, _ = read_tools
    asyncio.run(tools.search_wiki_pages("supplier"))
    with service.database.session() as conn:
        conn.execute("UPDATE memory_candidates SET status = 'forgotten' WHERE summary = 'Wiki source provenance'")
    with pytest.raises(WikiGenerationError):
        asyncio.run(tools.read_wiki_page("Wiki/Concepts/Product-P.md"))
    assert [event.name for event in events] == ["search_wiki_pages"]


def test_tool_schema_does_not_accept_write_authority_or_foreign_vault(read_tools):
    tools, events, _, _, _ = read_tools
    tool = tools.read_wiki_page_tool()
    with pytest.raises(ValidationError):
        asyncio.run(tool.ainvoke({
            "relative_path": "Wiki/Concepts/Product-P.md", "user_confirmed": True, "vault_id": "foreign",
        }))
    assert events == []
    with pytest.raises(AgentToolUnavailableError):
        asyncio.run(AgentToolSet().read_wiki_page("Wiki/Concepts/Product-P.md"))
