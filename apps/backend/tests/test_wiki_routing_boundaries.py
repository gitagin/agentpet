import asyncio
import json
from types import SimpleNamespace

from app.agents.intent import route_intent
from app.agents.memory_router import explicit_memory_read_scope, route_memory
from app.agents.nodes.chat import _run_model_chat_with_tools
from app.agents.retrieval.scoping import _memory_aggregation_scopes, _semantic_from_memory_route
from app.agents.semantic import _fallback_source_scope, _parse_classifier_analysis
from app.agents.services import AgentRuntimeServices
from app.models.enums import AgentIntent
from tests.agent_runtime_fakes import FakeRegistryChatModel, make_state


def test_wiki_topic_does_not_override_general_concept_classification():
    for question in (
        "LLM Wiki 和 RAG 有什么本质区别？", "What is a wiki?",
        "API 文档是什么？", "What is a knowledge base?", "What is a Wikipedia API?",
    ):
        assert explicit_memory_read_scope(question) is None
        assert _fallback_source_scope(question) == "none"
        classifier, semantic = _parse_classifier_analysis(
            json.dumps({"intent": "chat", "confidence": 0.9}), question,
        )
        assert classifier.intent == "chat"
        assert not semantic.needs_context


def test_explicit_library_and_project_queries_override_wrong_classifier():
    for question in ("查一下 Wiki 中的 RAG", "我知识库中有什么？", "Search my wiki for RAG",
                     "我当前项目是怎么实现 RAG 的？", "What database does our project use?"):
        assert explicit_memory_read_scope(question) == "knowledge_base"
        classifier, semantic = _parse_classifier_analysis(
            json.dumps({"intent": "chat", "confidence": 0.9}), question,
        )
        assert classifier.intent == "need_retrieval"
        assert semantic.source_scope == "knowledge_base"
        assert route_intent(question).intent == AgentIntent.SEARCH_MEMORY


def test_explicit_personal_and_mixed_reads_keep_only_requested_scopes():
    personal = "我的长期记忆里有什么？"
    assert route_intent(personal).intent == AgentIntent.SEARCH_MEMORY
    assert explicit_memory_read_scope(personal) == "personal_memory"
    question = "根据我的知识库和长期记忆，列出我的项目偏好"
    state = make_state(question)
    state.memory_route = route_memory(question)
    semantic = _semantic_from_memory_route(state.memory_route, state)
    assert semantic.source_scope == "all"
    assert _memory_aggregation_scopes(state, semantic) == ("knowledge_base", "personal_memory")


def test_write_explanation_and_negation_do_not_become_write_authorization():
    for question in ("如何更新 Wiki？", "How do I update wiki?", "不要写入 Wiki，只解释概念"):
        assert route_intent(question).intent != AgentIntent.MANAGE_WIKI
        classifier, semantic = _parse_classifier_analysis(
            json.dumps({"intent": "action", "action_type": "wiki", "confidence": 1,
                        "action_params": {"content": "unrequested write"}}), question,
        )
        assert classifier.intent != "action"
        assert classifier.action_params == {}
    assert route_intent("更新 Wiki：项目使用 SQLite").intent == AgentIntent.MANAGE_WIKI


def test_chat_model_never_receives_write_tools_even_with_auto_organize_enabled():
    model = FakeRegistryChatModel(None, "Answer.")
    services = AgentRuntimeServices(
        chat_model=model, automation_settings=SimpleNamespace(auto_wiki_organize=True),
    )
    asyncio.run(_run_model_chat_with_tools(services, make_state("LLM Wiki 和 RAG 有什么区别？")))
    assert model.calls[0][2] == ["search_memory", "get_current_time"]
