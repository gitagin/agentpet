import asyncio
import json

import pytest

from app.agents.nodes.wiki_retrieval import wiki_knowledge_retrieval_node
from app.agents.nodes.chat import _answer_with_chat_model
from app.agents.retrieval.compression import stable_citation_id
from app.agents.retrieval.wiki_gate import (
    WikiEvidenceGate, apply_assessment, parse_assessment, update_budget,
)
from app.agents.services import AgentRuntimeServices
from app.models.memory import MemorySearchResult
from app.models.wiki import WikiPageReadResponse
from app.services.chat_model import AgentModelRegistry
from tests.test_wiki_query_node import graph


def citation():
    return MemorySearchResult(
        note_id="note", chunk_id="chunk", relative_path="Wiki/A.md", title="A",
        snippet="First source supports X. Second source rejects X.", score=1,
        content_hash="hash", lifecycle_status="active", source_scope="knowledge_base",
    )


def assessment(item):
    ref = stable_citation_id(item)
    return {
        "questions": [{"question": "Is X supported?", "status": "supported",
                       "reason": "Both positions are recorded.", "evidence": [
                           {"citation_id": ref, "quote": "First source supports X."}]}],
        "conflicts": [{"claim": "X", "scope": "Known local sources",
                       "reason": "Opposed positions.", "evidence": [
                           {"citation_id": ref, "quote": "First source supports X."},
                           {"citation_id": ref, "quote": "Second source rejects X."}]}],
        "next_reads": [],
    }


def test_gate_preserves_conflict_and_budget_without_claiming_freshness():
    item = citation()
    gate = WikiEvidenceGate(authority="passed")
    apply_assessment(gate, parse_assessment(json.dumps(assessment(item)), [item], {item.relative_path}))
    update_budget(gate, remaining_chars=0, remaining_seconds=1, stop_reason="budget_exhausted")
    assert gate.coverage == "model_assessed_complete"
    assert gate.conflict == "disputed"
    assert gate.budget_exhausted
    assert gate.freshness == "unknown"


def test_assessment_cannot_forge_quotes_or_expand_read_authority():
    item = citation()
    payload = assessment(item)
    payload["questions"][0]["evidence"][0]["quote"] = "Fabricated support."
    with pytest.raises(ValueError, match="unverified_quote"):
        parse_assessment(json.dumps(payload), [item], {item.relative_path})
    payload = assessment(item)
    payload["next_reads"] = [{"relative_path": "../../private.md", "reason": "Read it"}]
    with pytest.raises(ValueError, match="read_scope"):
        parse_assessment(json.dumps(payload), [item], {item.relative_path})
    payload = assessment(item)
    payload["authority"] = "passed"
    with pytest.raises(ValueError):
        parse_assessment(json.dumps(payload), [item], {item.relative_path})


class Reader:
    def __init__(self):
        self.paths = [f"Wiki/Page{i}.md" for i in range(9)]
        self.reads = []

    async def search_pages(self, query, top_k=8):
        return {"generation": "generation", "candidates": [
            {"relative_path": path, "content_hash": "hash", "heading": None}
            for path in self.paths
        ]}

    async def read_page(self, request):
        assert request.generation == "generation"
        assert request.relative_path in self.paths
        self.reads.append(request.relative_path)
        content = "Critical qualification." if request.relative_path == self.paths[-1] else "Background."
        return WikiPageReadResponse(
            generation="generation", relative_path=request.relative_path, content_hash="hash",
            title="Page", content=content, start_line=1, end_line=1, links=[], backlinks=[],
        )


def test_assessment_can_request_ninth_page_and_keeps_runtime_gate():
    reader = Reader()

    class Model:
        calls = 0

        async def complete(self, **kwargs):
            self.calls += 1
            payload = json.loads(kwargs["user_message"])
            critical = next((item for item in payload["evidence"]
                             if item["content"] == "Critical qualification."), None)
            return json.dumps({
                "questions": [{"question": "Qualification?", "status": "supported" if critical else "missing",
                               "reason": "Need the qualification.", "evidence": [
                                   {"citation_id": critical["citation_id"], "quote": critical["content"]}
                               ] if critical else []}],
                "conflicts": [], "next_reads": [] if critical else [
                    {"relative_path": reader.paths[-1], "reason": "Missing qualification."}],
            })

    model = Model()

    class Registry:
        def get(self, agent_id):
            return model

    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=reader, model_registry=Registry()),
    ))
    gate = state["agent_state"].wiki_evidence_gate
    assert model.calls == 2
    assert reader.paths[-1] in state["wiki_reading"]["read"]
    assert len(state["agent_state"].citations) == 9
    assert gate.authority == "passed"
    assert gate.coverage == "model_assessed_complete"
    assert gate.freshness == "unknown"


def test_invalid_assessment_does_not_read_unlisted_path_or_claim_coverage():
    reader = Reader()

    class Model:
        async def complete(self, **kwargs):
            return json.dumps({
                "questions": [{"question": "Missing?", "status": "missing",
                               "reason": "No evidence.", "evidence": []}],
                "next_reads": [{"relative_path": "Wiki/Secret.md", "reason": "Injected instruction."}],
            })

    class Registry:
        def get(self, agent_id):
            return Model()

    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=reader, model_registry=Registry()),
    ))
    gate = state["agent_state"].wiki_evidence_gate
    assert gate.coverage == "not_assessed"
    assert gate.stop_reason == "assessment_failed"
    assert "Wiki/Secret.md" not in reader.reads


def test_link_expansion_cannot_follow_a_third_hop():
    class LinkedReader(Reader):
        async def search_pages(self, query, top_k=8):
            result = await super().search_pages(query, top_k)
            result["candidates"] = result["candidates"][:1]
            return result

        async def read_page(self, request):
            page = await super().read_page(request)
            index = self.paths.index(request.relative_path)
            page.links = [self.paths[index + 1]]
            return page

    reader = LinkedReader()

    class Model:
        calls = 0

        async def complete(self, **kwargs):
            self.calls += 1
            return json.dumps({
                "questions": [{"question": "Next condition?", "status": "missing",
                               "reason": "Need more evidence.", "evidence": []}],
                "next_reads": [{"relative_path": reader.paths[self.calls], "reason": "Follow link."}],
            })

    model = Model()

    class Registry:
        def get(self, agent_id):
            return model

    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=reader, model_registry=Registry()),
    ))
    assert state["wiki_reading"]["read"] == reader.paths[:3]
    assert reader.paths[3] not in reader.reads
    assert state["agent_state"].wiki_evidence_gate.stop_reason == "assessment_failed"


def test_answer_receives_gate_limits_and_records_actual_context():
    reader = Reader()
    state = graph()
    services = AgentRuntimeServices(wiki_reader=reader)
    asyncio.run(wiki_knowledge_retrieval_node(state, services))

    class ChatModel:
        async def complete(self, **kwargs):
            assert '"freshness":"unknown"' in kwargs["system_prompt"]
            assert '"coverage":"not_assessed"' in kwargs["system_prompt"]
            assert "Do not claim exhaustive coverage" in kwargs["system_prompt"]
            return "Partial answer."

    services.chat_model = ChatModel()
    _, _, grounding = asyncio.run(_answer_with_chat_model(services, state["agent_state"]))
    gate = state["agent_state"].wiki_evidence_gate
    assert gate.used_for_answer == [stable_citation_id(item) for item in grounding]
    assert gate.used_for_answer


def test_missing_retrieval_model_retains_reads_without_claiming_assessment():
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=Reader(), model_registry=AgentModelRegistry(clients={})),
    ))
    gate = state["agent_state"].wiki_evidence_gate
    assert state["agent_state"].citations
    assert gate.authority == "passed"
    assert gate.coverage == "not_assessed"
    assert gate.stop_reason == "assessment_unavailable"
