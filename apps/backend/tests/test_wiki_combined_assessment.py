import asyncio
import json
import time

import pytest

from app.agents.nodes.wiki_retrieval import assess_combined_evidence, wiki_knowledge_retrieval_node
from app.agents.retrieval.wiki_gate import (
    WikiEvidenceGate, WikiAssessment, apply_assessment, reconcile_assessment, update_budget,
)
from app.agents.services import AgentRuntimeServices
from tests.test_wiki_archive_authority import archive_service, citation
from tests.test_wiki_gate import Reader
from tests.test_wiki_query_node import graph
from tests.test_wiki_vault_fallback import runtime


class CombinedModel:
    def __init__(self, *, invalid=None, revoke=None):
        self.inputs = []
        self.invalid = invalid
        self.revoke = revoke

    async def complete(self, **kwargs):
        data = json.loads(kwargs["user_message"])
        self.inputs.append(data)
        notes = [item for item in data["evidence"] if item["retrieval_mode"] == "wiki_vault_fallback"]
        wiki = data["evidence"][0]
        refs = [{"citation_id": wiki["citation_id"], "quote": wiki["content"]}]
        if notes:
            refs.append({"citation_id": notes[0]["citation_id"], "quote": notes[0]["content"]})
            assert data["allowed_paths"] == []
            assert data["previous_assessment"]
            if self.revoke:
                self.revoke()
        payload = {
            "questions": [{"question": "What qualification applies?", "status": "supported" if notes else "missing",
                           "reason": "Evaluate the known evidence.", "evidence": refs if notes else []}],
            "conflicts": [{
                "claim": "Qualification", "scope": "Local documents",
                "reason": "Different stated qualifications.", "evidence": refs,
            }] if notes else [],
            "next_reads": [],
        }
        if notes and self.invalid == "quote":
            payload["questions"][0]["evidence"][0]["quote"] = "FABRICATED_EVIDENCE"
        if notes and self.invalid == "question":
            payload["questions"][0]["question"] = "A different easier question"
        return json.dumps(payload)


def run_query(service, monkeypatch, model):
    citation(service, "Notes/Source.md", content="# Source\nRelevant qualification.\n")
    adapter = runtime(service, monkeypatch)

    class Registry:
        def get(self, agent_id):
            return model

    state = graph()
    state["agent_state"].user_message = "source"
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=Reader(), retrieval=adapter, model_registry=Registry()),
    ))
    return state


def test_combined_assessment_maps_notes_and_preserves_unknown_freshness(archive_service, monkeypatch):
    model = CombinedModel()
    state = run_query(archive_service, monkeypatch, model)
    gate = state["agent_state"].wiki_evidence_gate
    assert len(model.inputs) == state["wiki_reading"]["assessment_calls"] == 2
    assert gate.coverage == "model_assessed_complete"
    assert gate.conflict == "disputed"
    assert gate.freshness == "unknown"
    assert gate.authority == "passed"
    assert gate.assessment_reason == "combined_model_assessed_with_verified_quotes"
    assert state["wiki_reading"]["combined_assessment"] == "assessed"


@pytest.mark.parametrize("invalid", ["quote", "question"])
def test_invalid_combined_assessment_cannot_promote_coverage(archive_service, monkeypatch, invalid):
    state = run_query(archive_service, monkeypatch, CombinedModel(invalid=invalid))
    gate = state["agent_state"].wiki_evidence_gate
    assert gate.coverage == "not_assessed"
    assert gate.assessment.questions[0].status == "missing"
    assert state["wiki_reading"]["combined_assessment"] == "invalid_or_failed"


def test_revocation_during_combined_assessment_blocks_all_citation_emission(archive_service, monkeypatch):
    def revoke():
        archive_service.retrieval.candidate_filter = lambda _: False

    state = run_query(archive_service, monkeypatch, CombinedModel(revoke=revoke))
    assert state["agent_state"].wiki_evidence_gate.authority == "denied"
    assert state["agent_state"].wiki_evidence_gate.assessment is None
    assert not state["agent_state"].citations


def test_combined_assessment_cannot_exceed_shared_call_budget():
    state = graph()["agent_state"]
    state.wiki_evidence_gate = WikiEvidenceGate(coverage="not_assessed")
    report = {"assessment_calls": 3}

    class Model:
        async def complete(self, **kwargs):
            raise AssertionError("fourth assessment is forbidden")

    asyncio.run(assess_combined_evidence(
        AgentRuntimeServices(), state, [], model=Model(),
        deadline=time.monotonic() + 30, report=report,
    ))
    assert report["combined_assessment"] == "round_budget_exhausted"
    assert report["assessment_calls"] == 3


def test_supplementation_cannot_silently_erase_previous_disputes():
    previous = WikiAssessment.model_validate({
        "questions": [{"question": "Which rule?", "status": "missing", "reason": "Disputed."}],
        "conflicts": [{
            "claim": "Rule", "scope": "Same project", "reason": "Incompatible rules.",
            "evidence": [{"citation_id": "a", "quote": "Use A."}, {"citation_id": "b", "quote": "Use B."}],
        }],
    })
    current = WikiAssessment.model_validate({
        "questions": [{"question": "Which rule?", "status": "missing", "reason": "Still incomplete."}],
        "conflicts": [],
    })
    gate = WikiEvidenceGate()
    apply_assessment(gate, reconcile_assessment(previous, current))
    update_budget(gate, remaining_chars=0, remaining_seconds=1, stop_reason="budget_exhausted")
    assert gate.conflict == "disputed"
    assert gate.assessment.conflicts == previous.conflicts
    assert gate.budget_exhausted
    assert gate.coverage == "partial"
