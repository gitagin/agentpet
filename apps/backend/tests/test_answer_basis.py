import asyncio

from app.agents.events import AgentDoneEvent, AgentReplyReadyEvent
from app.agents.nodes.chat import _chat_node, _validated_model_response
from app.agents.nodes.finish import _finish_node
from app.agents.retrieval.compression import stable_citation_id
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentRoute, SemanticAnalysisResult
from app.models.enums import AgentIntent
from tests.agent_runtime_fakes import make_state
from tests.test_wiki_gate import citation


def test_general_answer_is_unverified_not_local_grounded():
    state = make_state("Explain the concept.")
    _validated_model_response({}, state, "A general explanation.", grounding_results=())
    assert state.answer_basis == "general_unverified"
    assert state.grounding_validation == "not_applicable"


def test_only_actual_answer_context_receives_local_basis():
    state = make_state("Explain X.")
    item = citation()
    state.citations = [item]
    _validated_model_response({}, state, "A contextual answer.", grounding_results=())
    assert state.answer_basis == "not_assessed"
    assert state.grounding_validation == "not_applicable"
    _validated_model_response({}, state, "A contextual answer.", grounding_results=(item,))
    assert state.answer_basis == "local_evidence_context"
    assert state.grounding_validation == "passed"


def test_citation_not_used_in_context_is_rejected_not_certified():
    state = make_state("Explain X.")
    item = citation()
    state.citations = [item]
    answer = stable_citation_id(item)
    result = _validated_model_response({}, state, answer, grounding_results=())
    assert result != answer
    assert state.answer_basis == "validation_failed"
    assert state.grounding_validation == "failed"


def test_missing_project_evidence_never_invokes_model_and_emits_basis():
    state = make_state("What does this project use?")
    state.route = AgentRoute(intent=AgentIntent.SEARCH_MEMORY, confidence=1, reason="project")
    state.semantic_analysis = SemanticAnalysisResult(needs_context=True, source_scope="knowledge_base")

    class Model:
        async def complete(self, **kwargs):
            raise AssertionError("project facts need local evidence")

    graph = {"agent_state": state, "events": []}
    asyncio.run(_chat_node(graph, AgentRuntimeServices(chat_model=Model()), lambda _: False))
    asyncio.run(_finish_node(graph))
    done = next(event for event in graph["events"] if isinstance(event, AgentDoneEvent))
    assert done.answer_basis == "insufficient_local_evidence"
    ready = AgentReplyReadyEvent(
        agent_run_id=done.agent_run_id, intent=done.intent, text=done.text, answer_basis=done.answer_basis,
    )
    assert ready.model_dump()["answer_basis"] == "insufficient_local_evidence"


def test_old_or_unassessed_completion_does_not_default_to_verified():
    event = AgentDoneEvent(agent_run_id="run", intent=AgentIntent.CHAT, text="Answer")
    assert event.answer_basis == "not_assessed"
    assert AgentReplyReadyEvent(agent_run_id="run", intent=AgentIntent.CHAT).answer_basis == "not_assessed"
