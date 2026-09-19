import asyncio

import pytest

from app.agents.nodes.chat import _chat_node
from app.agents.nodes.wiki_retrieval import wiki_knowledge_retrieval_node
from app.agents.services import AgentRuntimeServices
from app.api.services import adapters
from tests.test_wiki_archive_authority import archive_service, citation
from tests.test_wiki_gate import Reader
from tests.test_wiki_query_node import graph


def runtime(service, monkeypatch):
    with service.database.session() as conn:
        vault_id = conn.execute("SELECT id FROM vaults LIMIT 1").fetchone()["id"]
    monkeypatch.setattr(adapters, "active_vault_id", lambda _: vault_id)
    monkeypatch.setattr(adapters, "retrieval_service", lambda _: service.retrieval)
    return adapters.RuntimeRetrievalAdapter(object())


def test_fallback_search_excludes_wiki_and_cache_is_not_shared(archive_service, monkeypatch):
    wiki = citation(archive_service, "Wiki/Sources/Source.md")
    note = citation(archive_service, "Notes/Source.md")
    adapter = runtime(archive_service, monkeypatch)
    with archive_service.database.session() as conn:
        vault = conn.execute("SELECT id FROM vaults LIMIT 1").fetchone()["id"]
    query = "source"
    archive_service.retrieval.search(vault_id=vault, query=query, source_scope="knowledge_base", mode="hybrid")
    response = asyncio.run(adapter.search_vault_notes(query))
    assert [item.relative_path for item in response.results] == [note.relative_path]
    assert response.results[0].retrieval_mode == "wiki_vault_fallback"
    assert response.results[0].snippet == note.snippet
    restored, errors = archive_service.retrieval.restore_citations(
        vault_id=vault, citations=[wiki], vault_notes_only=True,
    )
    assert not restored and errors


def test_exported_wiki_and_denied_notes_cannot_supply_fallback(archive_service, monkeypatch):
    citation(archive_service, "Notes/Export.md",
             content="---\nwiki_id: export\npage_type: concept\n---\n# Source\nSource claim.\n")
    note = citation(archive_service, "Notes/Ordinary.md")
    adapter = runtime(archive_service, monkeypatch)
    response = asyncio.run(adapter.search_vault_notes("source"))
    assert [item.relative_path for item in response.results] == [note.relative_path]
    archive_service.retrieval.candidate_filter = lambda _: False
    assert not asyncio.run(adapter.search_vault_notes("source")).results


def test_fallback_rechecks_external_edits_and_vault_switch(archive_service, monkeypatch):
    citation(archive_service, "Notes/Source.md")
    adapter = runtime(archive_service, monkeypatch)
    results = asyncio.run(adapter.search_vault_notes("source")).results
    assert results
    archive_service.wiki.writer.resolve_markdown_path("Notes/Source.md").write_text(
        "# Source\nChanged evidence.", encoding="utf-8",
    )
    with pytest.raises(ValueError, match="authority_failed"):
        asyncio.run(adapter.restore_vault_notes(results))
    monkeypatch.setattr(adapters, "active_vault_id", lambda _: "different-vault")
    with pytest.raises(ValueError, match="vault_changed"):
        asyncio.run(adapter.restore_vault_notes(results))


def test_fallback_emits_full_chunks_but_blocks_answer_after_revocation(archive_service, monkeypatch):
    source = citation(archive_service, "Notes/Source.md")
    adapter = runtime(archive_service, monkeypatch)
    state = graph()
    state["agent_state"].user_message = "source"
    services = AgentRuntimeServices(wiki_reader=Reader(), retrieval=adapter)
    asyncio.run(wiki_knowledge_retrieval_node(state, services))
    fallback = [item for item in state["agent_state"].citations if item.retrieval_mode == "wiki_vault_fallback"]
    assert len(fallback) == 1 and fallback[0].snippet == source.snippet
    assert state["wiki_reading"]["vault_fallback"] == "read"
    assert state["agent_state"].wiki_evidence_gate.coverage == "not_assessed"
    assert state["agent_state"].wiki_evidence_gate.freshness == "unknown"

    class Model:
        async def complete(self, **kwargs):
            archive_service.retrieval.candidate_filter = lambda _: False
            return "REVOKED_ANSWER"

    services.chat_model = Model()
    asyncio.run(_chat_node(state, services, lambda _: False))
    assert state.get("failed")
    assert "REVOKED_ANSWER" not in state["agent_state"].response_text


def test_personal_scope_does_not_invoke_fallback():
    class Retrieval:
        async def search_vault_notes(self, *args, **kwargs):
            raise AssertionError("must not broaden personal scope")

        async def restore_vault_notes(self, *args, **kwargs):
            raise AssertionError("must not read notes")

    state = graph()
    state["agent_state"].semantic_analysis.source_scope = "personal_memory"
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=Reader(), retrieval=Retrieval()),
    ))
    assert state["wiki_reading"]["stop_reason"] == "source_scope_denied"


def test_oversized_fallback_is_reported_not_silently_truncated(archive_service, monkeypatch):
    citation(archive_service, "Notes/Large.md", content="# Source\n" + "source details " * 1100)
    adapter = runtime(archive_service, monkeypatch)
    state = graph()
    state["agent_state"].user_message = "source"
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=Reader(), retrieval=adapter),
    ))
    assert "Notes/Large.md" in state["wiki_reading"]["fallback_unread"]
    assert state["agent_state"].wiki_evidence_gate.budget_exhausted
    citations = state["agent_state"].citations
    assert sum(len(item.snippet) for item in citations) <= 12000
    with archive_service.database.session() as conn:
        for item in citations:
            if item.retrieval_mode == "wiki_vault_fallback":
                row = conn.execute("SELECT content FROM note_chunks WHERE id = ?", (item.chunk_id,)).fetchone()
                assert row["content"] == item.snippet
