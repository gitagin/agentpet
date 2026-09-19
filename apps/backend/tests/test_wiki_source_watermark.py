import asyncio

import pytest

from app.agents.nodes.chat import _chat_node
from app.agents.nodes.wiki_retrieval import wiki_knowledge_retrieval_node
from app.agents.services import AgentRuntimeServices
from app.services.wiki.snapshot_reader import WikiSnapshotReader
from app.services.wiki.generations import WikiGenerationStore
from app.services.wiki.publication import WikiPublicationService
from tests.test_wiki_publication import published
from tests.test_wiki_read_tools import read_tools
from tests.test_wiki_query_node import graph
from tests.wiki_fixtures import indexed_citation


PATH = "Wiki/Concepts/Product-P.md"


def observer(service, vault, generation):
    reader = WikiSnapshotReader(service.database, service.wiki, authorize=lambda v, p: v == vault)
    return reader, reader.pin(generation)


def test_source_insertion_detected_without_timestamp_ordering(published):
    service, vault, _, generation = published
    reader, pin = observer(service, vault, generation)
    before = reader.source_observation(pin, [PATH])
    assert before["status"] == "unchanged_since_capture"
    with service.database.session() as conn:
        conn.execute(
            """INSERT INTO wiki_sources(id, source_hash, title, source_type, content_preview,
                       vault_id, created_at, updated_at)
               SELECT 'new-source', 'new-hash', 'New', 'file', '', vault_id, created_at, updated_at
               FROM wiki_sources WHERE vault_id = ? LIMIT 1""", (vault,),
        )
    after = reader.source_observation(pin, [PATH])
    assert after["status"] == "changed_since_capture"
    assert after["watermark"] != before["watermark"]
    assert reader.read(pin, PATH).content


def test_foreign_notes_and_personal_memory_do_not_change_knowledge_watermark(published, tmp_path):
    service, vault, _, generation = published
    reader, pin = observer(service, vault, generation)
    before = reader.source_observation(pin, [PATH])
    indexed_citation(service.database, tmp_path / "OtherVault", "Notes/Source.md")
    indexed_citation(service.database, service.wiki.writer.vault_root, "Memory/Preference.md")
    assert reader.source_observation(pin, [PATH]) == before
    indexed_citation(service.database, service.wiki.writer.vault_root, "Notes/Source.md")
    assert reader.source_observation(pin, [PATH])["status"] == "changed_since_capture"


def test_legacy_dependency_has_unknown_baseline_and_denied_page_leaks_nothing(published):
    service, vault, _, generation = published
    with service.database.session() as conn:
        conn.execute(
            """UPDATE wiki_generation_dependencies
               SET dependency_json = json_remove(dependency_json, '$.source_watermark')
               WHERE generation = ?""", (generation,),
        )
    reader, pin = observer(service, vault, generation)
    assert reader.source_observation(pin, [PATH])["status"] == "baseline_unknown"
    reader.authorize = lambda v, p: False
    with pytest.raises(ValueError, match="access_denied"):
        reader.source_observation(pin, [PATH])


def test_new_note_during_answer_blocks_output_without_revoking_old_roots(read_tools):
    tools, _, service, _, _ = read_tools
    services = AgentRuntimeServices(wiki_reader=tools.wiki_reader)
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(state, services))
    gate = state["agent_state"].wiki_evidence_gate
    assert state["agent_state"].citations
    assert gate.source_observation == "unchanged_since_capture"
    assert gate.freshness == "unknown"

    class Model:
        async def complete(self, **kwargs):
            indexed_citation(service.database, service.wiki.writer.vault_root, "Notes/New.md")
            return "SHOULD_NOT_SEND"

    services.chat_model = Model()
    asyncio.run(_chat_node(state, services, lambda _: False))
    assert state.get("failed")
    assert "SHOULD_NOT_SEND" not in state["agent_state"].response_text


def test_note_before_query_marks_pending_but_does_not_claim_automatic_staleness(read_tools):
    tools, _, service, _, _ = read_tools
    indexed_citation(service.database, service.wiki.writer.vault_root, "Notes/New.md")
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(state, AgentRuntimeServices(wiki_reader=tools.wiki_reader)))
    gate = state["agent_state"].wiki_evidence_gate
    assert state["agent_state"].citations
    assert gate.source_observation == "changed_since_capture"
    assert gate.freshness == "unknown"
    assert gate.freshness_reason == "source_relevance_check_pending"


def test_new_generation_does_not_reset_unmodified_page_watermark(published):
    service, vault, _, generation = published
    indexed_citation(service.database, service.wiki.writer.vault_root, "Notes/New.md")
    store = WikiGenerationStore(service.database)
    newer = store.stage(vault, base_generation=generation, changes={})
    store.promote(vault, newer, validate=WikiPublicationService(service.database, service.wiki)._validate)
    reader, pin = observer(service, vault, newer)
    assert reader.source_observation(pin, [PATH])["status"] == "changed_since_capture"
