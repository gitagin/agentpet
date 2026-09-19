import asyncio

import pytest

from app.agents.nodes.chat import _fallback_text_search_tool_call, _run_model_chat_with_tools
from app.agents.retrieval.scoping import _guard_search_memory_tools
from app.agents.services import AgentRuntimeServices
from app.agents.state import SemanticAnalysisResult
from app.agents.tools import AgentToolSet
from app.services.chat_model import ChatModelRunResult
from tests.agent_runtime_fakes import FakeRetrieval, make_state


SCOPES = ("knowledge_base", "personal_memory")


def test_all_is_expanded_only_to_explicit_sources():
    retrieval = FakeRetrieval()
    tools = _guard_search_memory_tools(
        [AgentToolSet(retrieval=retrieval).search_memory_tool()],
        forced_source_scope="all", allowed_source_scopes=SCOPES,
    )
    result = asyncio.run(tools[0].ainvoke({"query": "Ada", "source_scope": "all"}))
    assert [call[3] for call in retrieval.calls] == list(SCOPES)
    assert {item.source_scope for item in result.results} == set(SCOPES)
    assert result.metadata["enforced_source_scopes"] == list(SCOPES)


def test_outside_scope_rejected_before_search():
    retrieval = FakeRetrieval()
    tools = _guard_search_memory_tools(
        [AgentToolSet(retrieval=retrieval).search_memory_tool()],
        allowed_source_scopes=SCOPES,
    )
    with pytest.raises(ValueError, match="scope_not_authorized"):
        asyncio.run(tools[0].ainvoke({"query": "Ada", "source_scope": "daily_chat"}))
    assert retrieval.calls == []


def test_empty_scope_list_does_not_mean_unrestricted():
    with pytest.raises(ValueError, match="invalid_explicit_retrieval_scopes"):
        _guard_search_memory_tools([], allowed_source_scopes=())


def test_chat_tool_scope_is_bound_to_original_request():
    retrieval = FakeRetrieval()
    state = make_state("根据我的知识库和长期记忆，列出 Ada 的偏好")
    state.semantic_analysis = SemanticAnalysisResult(needs_context=True, source_scope="all")

    class Model:
        async def complete_with_tools(self, **kwargs):
            tool = next(tool for tool in kwargs["tools"] if tool.name == "search_memory")
            await tool.ainvoke({"query": "Ada", "source_scope": "all"})
            return ChatModelRunResult(text="Done.", raw_result={})

    asyncio.run(_run_model_chat_with_tools(
        AgentRuntimeServices(retrieval=retrieval, chat_model=Model()), state,
    ))
    assert [call[3] for call in retrieval.calls] == list(SCOPES)


def test_text_tool_fallback_cannot_expand_explicit_knowledge_scope():
    retrieval = FakeRetrieval()
    state = make_state("查一下知识库中的 Ada")
    result = asyncio.run(_fallback_text_search_tool_call(
        AgentRuntimeServices(retrieval=retrieval), state,
        '<tool_call><function=search_memory><parameter=query>Ada</parameter></function></tool_call>',
    ))
    assert result is not None
    assert [call[3] for call in retrieval.calls] == ["knowledge_base"]
