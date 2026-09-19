import asyncio

from app.agents.nodes.chat import _chat_node
from app.agents.nodes.wiki_retrieval import wiki_knowledge_retrieval_node
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState, SemanticAnalysisResult
from tests.test_wiki_read_tools import read_tools
from tests.test_wiki_publication import published


def graph():
    return {"agent_state": AgentState(
        conversation_id="conversation", message_id="message", agent_run_id="run",
        user_message="supplier",
        semantic_analysis=SemanticAnalysisResult(
            needs_context=True, source_scope="knowledge_base", query="supplier",
        ),
    ), "events": []}


def test_query_reads_real_pages_and_transports_snapshot_citations(read_tools):
    tools, _, _, _, generation = read_tools
    services = AgentRuntimeServices(wiki_reader=tools.wiki_reader)
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(state, services))
    citations = state["agent_state"].citations
    assert citations
    assert all(c.wiki_generation == generation and c.wiki_start_line >= 1 for c in citations)
    assert all(c.retrieval_mode == "wiki_snapshot" for c in citations)
    assert state["wiki_reading"]["coverage"] == "not_assessed"
    assert state["wiki_reading"]["used_chars"] <= 12000


def test_personal_only_scope_never_calls_wiki(read_tools):
    tools, _, _, _, _ = read_tools
    state = graph()
    state["agent_state"].semantic_analysis.source_scope = "personal_memory"
    asyncio.run(wiki_knowledge_retrieval_node(state, AgentRuntimeServices(wiki_reader=tools.wiki_reader)))
    assert state["wiki_reading"]["stop_reason"] == "source_scope_denied"
    assert not state["agent_state"].citations
    assert tools.wiki_reader._pin is None


def test_revocation_during_answer_suppresses_output(read_tools):
    tools, _, service, _, _ = read_tools
    services = AgentRuntimeServices(wiki_reader=tools.wiki_reader)
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(state, services))
    assert state["agent_state"].citations

    class Model:
        called = False

        async def complete(self, **kwargs):
            self.called = True
            with service.database.session() as conn:
                conn.execute(
                    "UPDATE memory_candidates SET status = 'forgotten' WHERE summary = 'Wiki source provenance'"
                )
            return "MUST_NOT_BE_SENT"

    model = Model()
    services.chat_model = model
    asyncio.run(_chat_node(state, services, lambda _: False))
    assert model.called
    assert state.get("failed")
    assert "MUST_NOT_BE_SENT" not in state["agent_state"].response_text
    assert all(getattr(event, "text", "") != "MUST_NOT_BE_SENT" for event in state["events"])


def test_forged_snapshot_excerpt_is_rejected_before_model(read_tools):
    tools, _, _, _, _ = read_tools
    services = AgentRuntimeServices(wiki_reader=tools.wiki_reader)
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(state, services))
    assert state["agent_state"].citations
    state["agent_state"].citations[0].snippet = "forged claim"

    class Model:
        async def complete(self, **kwargs):
            raise AssertionError("must not invoke model with forged evidence")

    services.chat_model = Model()
    asyncio.run(_chat_node(state, services, lambda _: False))
    assert state.get("failed")
    assert not state["agent_state"].response_text
