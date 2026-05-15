from __future__ import annotations

import pytest

from app.models.api import WikiPageWriteRequest
from app.services.memory import MarkdownWriteError, SafeMarkdownWriter
from app.services.wiki import SensitiveWikiRejectedError, WikiService, resolve_wiki_path
from app.storage.markdown import read_markdown


def test_wiki_service_writes_pages_under_wiki(tmp_path) -> None:
    service = WikiService(SafeMarkdownWriter(tmp_path), index_refresh=lambda path: f"indexed:{path}")

    response = service.write_page(
        WikiPageWriteRequest(
            title="Project Architecture",
            content="The wiki manager owns durable knowledge-base pages.",
            tags=["architecture"],
            links=["[[Memory]]"],
            source_message_id="message-1",
        )
    )

    assert response.relative_path == "Wiki/Project-Architecture.md"
    assert response.status == "created"
    assert response.index_job_id == "indexed:Wiki/Project-Architecture.md"
    text = (tmp_path / "Wiki" / "Project-Architecture.md").read_text(encoding="utf-8")
    parsed = read_markdown(tmp_path / "Wiki" / "Project-Architecture.md")
    assert parsed.frontmatter["title"] == "Project Architecture"
    assert parsed.frontmatter["type"] == "page"
    assert parsed.frontmatter["tags"] == ["architecture"]
    assert parsed.frontmatter["sources"] == ["message:message-1"]
    assert "# Project Architecture" in text
    assert "#architecture" in text
    assert "[[Memory]]" in text
    assert "message:message-1" in text
    assert (tmp_path / "Wiki" / "AGENTS.md").exists()
    assert (tmp_path / "Wiki" / "index.md").exists()
    assert (tmp_path / "Wiki" / "log.md").exists()


def test_wiki_service_refreshes_index_and_appends_log(tmp_path) -> None:
    service = WikiService(SafeMarkdownWriter(tmp_path))
    service.write_page(
        WikiPageWriteRequest(
            title="Retrieval",
            content="Retrieval uses wiki pages.",
            target_path="Wiki/Concepts/Retrieval.md",
            tags=["retrieval"],
        )
    )

    index = service.refresh_index()
    log = service.append_log("ingest", "Retrieval", "- Page: `Wiki/Concepts/Retrieval.md`")

    assert any(entry.relative_path == "Wiki/Concepts/Retrieval.md" for entry in index.entries)
    assert (tmp_path / "Wiki" / "index.md").read_text(encoding="utf-8").count("Wiki/Concepts/Retrieval.md") == 1
    assert log.entries[0].operation == "ingest"
    assert log.entries[0].title == "Retrieval"


def test_wiki_service_writes_obsidian_frontmatter_and_index_metadata(tmp_path) -> None:
    service = WikiService(SafeMarkdownWriter(tmp_path))
    service.write_page(
        WikiPageWriteRequest.model_validate(
            {
                "title": "Agent Runtime",
                "content": "Runtime coordinates agents.",
                "target_path": "Wiki/Concepts/Agent-Runtime.md",
                "type": "concept",
                "confidence": "high",
                "expiry": "2026-12-31",
                "authors": ["wiki_manager_agent"],
                "contributors": ["semantic_analysis_agent"],
                "disputed": True,
                "aliases": ["Runtime", "Agent Graph"],
                "sources": ["Wiki/Sources/Runtime.md", "Wiki/Sources/Runtime.md"],
            }
        )
    )

    parsed = read_markdown(tmp_path / "Wiki" / "Concepts" / "Agent-Runtime.md")
    assert parsed.frontmatter["type"] == "concept"
    assert parsed.frontmatter["confidence"] == "high"
    assert parsed.frontmatter["expiry"] == "2026-12-31"
    assert parsed.frontmatter["authors"] == ["wiki_manager_agent"]
    assert parsed.frontmatter["contributors"] == ["semantic_analysis_agent"]
    assert parsed.frontmatter["disputed"] == "true"
    assert parsed.frontmatter["aliases"] == ["Runtime", "Agent Graph"]
    assert parsed.frontmatter["sources"] == ["Wiki/Sources/Runtime.md"]

    index = service.refresh_index()
    entry = next(item for item in index.entries if item.relative_path == "Wiki/Concepts/Agent-Runtime.md")
    assert entry.page_type == "concept"
    assert entry.source_count == 1
    assert entry.aliases == ["Runtime", "Agent Graph"]
    assert entry.sources == ["Wiki/Sources/Runtime.md"]
    assert "| concept | [[Wiki/Concepts/Agent-Runtime.md]] | Runtime coordinates agents. | Runtime, Agent Graph | 1 |" in index.content


def test_wiki_graph_summary_detects_hubs_orphans_broken_links_and_deep_links(tmp_path) -> None:
    wiki_root = tmp_path / "Wiki"
    concepts = wiki_root / "Concepts"
    concepts.mkdir(parents=True)
    (wiki_root / "index.md").write_text(
        "# Wiki Index\n\n"
        "| Type | Page | Summary | Sources | Updated |\n"
        "| --- | --- | --- | ---: | --- |\n"
        "| concept | [[Wiki/Concepts/Hub.md]] | Hub | 0 |  |\n",
        encoding="utf-8",
    )
    (concepts / "Hub.md").write_text("# Hub\n\nCentral page.\n", encoding="utf-8")
    (concepts / "Source.md").write_text("# Source\n\nLinks to [[Hub]] and [[Missing Page]].\n", encoding="utf-8")
    (concepts / "Path Source.md").write_text("# Path Source\n\nLinks by path to [[Wiki/Concepts/Hub.md]].\n", encoding="utf-8")
    (concepts / "Orphan.md").write_text("# Orphan\n\nNo links.\n", encoding="utf-8")

    graph = WikiService(SafeMarkdownWriter(tmp_path)).get_graph_summary()

    assert graph.summary["nodes"] == 5
    assert graph.summary["edges"] == 4
    assert graph.summary["resolved_edges"] == 3
    assert graph.summary["broken_links"] == 1
    hub = next(node for node in graph.nodes if node.relative_path == "Wiki/Concepts/Hub.md")
    assert hub.in_degree == 3
    assert hub.out_degree == 0
    assert hub.indexed is True
    assert hub.vault_relative_path == "Wiki/Concepts/Hub.md"
    assert hub.obsidian_uri == "obsidian://open?path=Wiki%2FConcepts%2FHub.md"
    assert graph.hubs[0].relative_path == "Wiki/Concepts/Hub.md"
    assert {node.relative_path for node in graph.orphans} == {"Wiki/Concepts/Orphan.md"}
    assert graph.broken_links[0].source_path == "Wiki/Concepts/Source.md"
    assert graph.broken_links[0].target == "Missing Page"
    assert any(edge.target_path == "Wiki/Concepts/Hub.md" and edge.resolved for edge in graph.edges)


def test_wiki_graph_summary_is_read_only_when_core_files_are_missing(tmp_path) -> None:
    wiki_root = tmp_path / "Wiki"
    wiki_root.mkdir()
    (wiki_root / "Only.md").write_text("# Only\n\nNo generated core files should appear.\n", encoding="utf-8")

    graph = WikiService(SafeMarkdownWriter(tmp_path)).get_graph_summary()

    assert graph.summary["nodes"] == 1
    assert not (wiki_root / "AGENTS.md").exists()
    assert not (wiki_root / "index.md").exists()
    assert not (wiki_root / "log.md").exists()


def test_wiki_service_replaces_named_section(tmp_path) -> None:
    service = WikiService(SafeMarkdownWriter(tmp_path))
    request = WikiPageWriteRequest(
        title="Runtime",
        content="Old text",
        target_path="Wiki/Runtime.md",
        section="Agent Flow",
    )
    service.write_page(request)

    response = service.write_page(
        request.model_copy(update={"operation": "replace_section", "content": "New text"})
    )

    assert response.status == "updated"
    text = (tmp_path / "Wiki" / "Runtime.md").read_text(encoding="utf-8")
    assert "New text" in text
    assert "Old text" not in text


def test_wiki_target_path_must_stay_under_wiki() -> None:
    with pytest.raises(MarkdownWriteError):
        resolve_wiki_path("Bad", "Memories/Bad.md")
    with pytest.raises(MarkdownWriteError):
        resolve_wiki_path("Bad", "Wiki/../Bad.md")
    with pytest.raises(MarkdownWriteError):
        resolve_wiki_path("Bad", "Wiki/Bad.txt")


def test_wiki_service_rejects_sensitive_content(tmp_path) -> None:
    service = WikiService(SafeMarkdownWriter(tmp_path))

    with pytest.raises(SensitiveWikiRejectedError):
        service.write_page(
            WikiPageWriteRequest(
                title="Credentials",
                content="api key sk-agent-memory-secret-1234567890",
            )
        )

    assert not (tmp_path / "Wiki").exists()
