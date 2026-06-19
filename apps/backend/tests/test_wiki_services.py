from __future__ import annotations

import pytest
from datetime import datetime, timezone

from app.models.api import WikiPageWriteRequest
from apps.backend.tests._schema import migrated_connection
from app.services.agent_actions import AgentActionCreate, AgentActionService, AgentActionStore
from app.services.memory import MarkdownWriteError, SafeMarkdownWriter
from app.services.retrospectives import RetrospectiveService
from app.services.wiki import SensitiveWikiRejectedError, WikiService, WIKI_PAGE_TEMPLATE_SECTIONS, resolve_wiki_path
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
    assert parsed.frontmatter["revision"] == "1"
    assert parsed.frontmatter["tags"] == ["architecture"]
    assert parsed.frontmatter["sources"] == ["message:message-1"]
    assert "# Project Architecture" in text
    assert "#architecture" in text
    assert "[[Memory]]" in text
    assert "message:message-1" in text
    assert (tmp_path / "Wiki" / "AGENTS.md").exists()
    assert (tmp_path / "Wiki" / "index.md").exists()
    assert (tmp_path / "Wiki" / "log.md").exists()


def test_wiki_default_schema_documents_seven_rules_and_template(tmp_path) -> None:
    service = WikiService(SafeMarkdownWriter(tmp_path))

    schema = service.get_schema_status().content

    for section in WIKI_PAGE_TEMPLATE_SECTIONS:
        assert section in schema
    assert "硬边界" in schema
    assert "证据与触发来源" in schema
    assert "审查与自检" in schema
    assert "版本与日志" in schema
    assert "术语与格式陷阱" in schema
    assert "双层日志" in schema


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
                "authors": ["action_agent"],
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
    assert parsed.frontmatter["authors"] == ["action_agent"]
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


def test_wiki_service_rejects_sensitive_policy_metadata_before_core_files(tmp_path) -> None:
    service = WikiService(SafeMarkdownWriter(tmp_path))

    with pytest.raises(SensitiveWikiRejectedError) as exc_info:
        service.write_page(
            WikiPageWriteRequest(
                title="Project Source",
                content="Reusable project source summary.",
                sources=["bearer secret-token-for-test-1234567890"],
            )
        )

    assert exc_info.value.reason == "bearer_token"
    assert not (tmp_path / "Wiki").exists()


def test_weekly_report_writes_markdown_asset_with_sources_and_reversible_action(tmp_path) -> None:
    conn = migrated_connection()
    vault = tmp_path / "Vault"
    now = "2026-06-02T00:00:00Z"
    conn.execute("INSERT INTO vaults(id, root_path, name) VALUES ('vault-1', ?, 'Vault')", (str(vault),))
    conn.execute(
        """
        INSERT INTO diary_memory_objects (
            id, vault_id, type, summary, topic, emotion, people_json,
            keywords_json, importance, confidence, occurred_at, timezone,
            status, object_hash, extraction_model, created_at, updated_at
        )
        VALUES (
            'diary-weekly-1', 'vault-1', 'event', 'Reviewed weekly report requirements.',
            'weekly planning', 'focused', '[]', '["weekly","report"]', 0.9, 0.95,
            '2026-06-01T12:00:00Z', 'UTC', 'active', 'hash-weekly-1', 'fake', ?, ?
        )
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO diary_memory_object_sources(
            object_id, source_type, source_id, markdown_path, agent_run_id
        )
        VALUES (
            'diary-weekly-1', 'chat_exchange', 'run-weekly-1',
            'Memories/Daily/2026-06-01.md', 'run-weekly-1'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO tasks(id, title, description, due_at_utc, status, source_text, created_at, updated_at)
        VALUES
            ('task-weekly-1', 'Finish report UI', '', '2026-06-01T15:00:00Z', 'done', '', '2026-06-01T10:00:00Z', '2026-06-01T16:00:00Z'),
            ('task-weekly-2', 'Review delayed report question', '', '2026-06-01T15:00:00Z', 'pending', '', '2026-06-01T10:00:00Z', '2026-06-01T11:00:00Z')
        """
    )
    writer = SafeMarkdownWriter(vault)
    action_service = AgentActionService(AgentActionStore(conn), writer=writer)
    action_service.record(
        AgentActionCreate(
            action_type="wiki.page.write",
            title="Weekly Knowledge",
            summary="created knowledge page",
            target_paths=("Wiki/Weekly-Knowledge.md",),
            reversible=True,
        )
    )
    conn.execute("UPDATE agent_actions SET created_at = ?, updated_at = ?, completed_at = ?", (now, now, now))
    conn.commit()
    service = RetrospectiveService(
        conn,
        vault_id="vault-1",
        writer=writer,
        agent_actions=action_service,
        now_provider=lambda: datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    response = service.write_period_report("weekly")

    assert response.page.relative_path.startswith("Wiki/Companion/Reports/")
    assert "-weekly-" in response.page.relative_path
    assert response.action.action_type == "wiki.weekly_report.write"
    assert response.action.reversible is True
    report_path = vault.joinpath(*response.page.relative_path.split("/"))
    markdown = report_path.read_text(encoding="utf-8")
    assert "type: weekly_report" in markdown
    assert "updated_at: 2026-06-02T00:00:00Z" in markdown
    assert "## 本周主要主题" in markdown
    assert "## 重要对话和日记摘要" in markdown
    assert "## 任务完成与延迟" in markdown
    assert "## 新增知识页" in markdown
    assert "## 值得回顾的问题" in markdown
    assert "`Memories/Daily/2026-06-01.md`" in markdown
    assert "`Wiki/Weekly-Knowledge.md`" in markdown

    monthly_response = service.write_period_report("monthly")
    monthly_path = vault.joinpath(*monthly_response.page.relative_path.split("/"))
    monthly_markdown = monthly_path.read_text(encoding="utf-8")
    assert "-monthly-" in monthly_response.page.relative_path
    assert monthly_response.action.action_type == "wiki.monthly_report.write"
    assert "type: monthly_report" in monthly_markdown
    assert "## 本月主要主题" in monthly_markdown

    monthly_updated, monthly_reverted = action_service.revert(monthly_response.action.action_id)
    assert monthly_updated.status == "reverted"
    assert monthly_reverted.action_type == "agent_action.revert"
    assert not monthly_path.exists()

    updated, reverted = action_service.revert(response.action.action_id)

    assert updated.status == "reverted"
    assert reverted.action_type == "agent_action.revert"
    assert not report_path.exists()
