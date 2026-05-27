from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool

from tests.agent_runtime_fakes import (
    FakeKeywordSemanticModel,
    FakeMemory,
    FakeRegistryChatModel,
    FakeRetrieval,
    FakeTasks,
    FakeWikiWorkflow,
    assert_langgraph_events,
    first_event,
    make_state,
    non_status_event_names,
)

from app.agents import AgentRuntimeServices, AgentToolSet, LangGraphAgentRuntime, route_intent
from app.models.api import AutomationSettingsResponse
from app.models.enums import AgentIntent
from app.services.chat_model import AgentId, AgentModelRegistry


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("hello there", AgentIntent.CHAT),
        ("search memory for Ada", AgentIntent.SEARCH_MEMORY),
        ("add to wiki: Runtime: Wiki manager owns knowledge pages", AgentIntent.MANAGE_WIKI),
        ("please remember Ada likes concise updates", AgentIntent.PROPOSE_MEMORY),
        ("remind me to stretch tomorrow", AgentIntent.CREATE_TASK),
        ("5月3号我说了什么", AgentIntent.SEARCH_MEMORY),
        ("搜索记忆 Ada", AgentIntent.SEARCH_MEMORY),
        ("记住：Ada 喜欢简洁的状态更新", AgentIntent.PROPOSE_MEMORY),
        ("提醒我明天伸展", AgentIntent.CREATE_TASK),
        ("5秒钟后提醒我写笔记", AgentIntent.CREATE_TASK),
    ],
)
def test_route_intent(message: str, intent: AgentIntent) -> None:
    assert route_intent(message).intent == intent


def test_langgraph_runtime_uses_langchain_structured_tools_for_core_services() -> None:
    toolset = AgentToolSet(
        retrieval=FakeRetrieval(),
        memory=FakeMemory(),
        tasks=FakeTasks(),
    )

    tools = toolset.all_tools()

    assert all(isinstance(tool, StructuredTool) for tool in tools)
    assert [tool.name for tool in tools] == [
        "search_memory",
        "propose_memory",
        "plan_wiki_ingest",
        "plan_wiki_query_archive",
        "plan_wiki_synthesis",
        "plan_wiki_lint",
        "manage_wiki_page",
        "create_task",
    ]


def test_agent_model_registry_returns_stable_agent_clients() -> None:
    chat_model = FakeRegistryChatModel(None, "chat")
    registry = AgentModelRegistry({AgentId.CHAT_AGENT: chat_model})

    assert registry.get(AgentId.CHAT_AGENT) is chat_model
    assert registry.get("chat_agent") is chat_model

    with pytest.raises(Exception) as exc_info:
        registry.get(AgentId.TASK_AGENT)
    assert getattr(exc_info.value, "code") == "agent_model_not_configured"
    assert getattr(exc_info.value, "agent_id") == AgentId.TASK_AGENT


def test_langgraph_runtime_uses_independent_registry_models_and_allowed_tools() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        memory = FakeMemory()
        tasks = FakeTasks()
        wiki_workflow = FakeWikiWorkflow()
        chat_model = FakeRegistryChatModel(None, "chat-only")
        semantic_model = FakeKeywordSemanticModel()
        memory_retrieval_model = FakeRegistryChatModel("search_memory", "memory answer")
        knowledge_retrieval_model = FakeRegistryChatModel("search_memory", "knowledge answer")
        wiki_model = FakeRegistryChatModel(None, "wiki answer")
        memory_model = FakeRegistryChatModel("propose_memory", "memory answer")
        task_model = FakeRegistryChatModel("create_task", "task answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                memory=memory,
                tasks=tasks,
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.CHAT_AGENT: chat_model,
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.MEMORY_RETRIEVAL_AGENT: memory_retrieval_model,
                        AgentId.KNOWLEDGE_RETRIEVAL_AGENT: knowledge_retrieval_model,
                        AgentId.WIKI_MANAGER_AGENT: wiki_model,
                        AgentId.MEMORY_PROPOSAL_AGENT: memory_model,
                        AgentId.TASK_AGENT: task_model,
                    }
                ),
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        chat_events = [event async for event in runtime.run(make_state("hello"))]
        search_events = [event async for event in runtime.run(make_state("search memory for Ada"))]
        wiki_events = [event async for event in runtime.run(make_state("add to wiki: Runtime: Wiki content"))]
        memory_events = [event async for event in runtime.run(make_state("remember this: Ada likes tests"))]
        task_events = [event async for event in runtime.run(make_state("remind me to review tests"))]

        return (
            retrieval,
            chat_model,
            semantic_model,
            memory_retrieval_model,
            knowledge_retrieval_model,
            wiki_model,
            memory_model,
            task_model,
            chat_events,
            search_events,
            wiki_events,
            memory_events,
            task_events,
        )

    (
        retrieval,
        chat_model,
        semantic_model,
        memory_retrieval_model,
        knowledge_retrieval_model,
        wiki_model,
        memory_model,
        task_model,
        chat_events,
        search_events,
        wiki_events,
        memory_events,
        task_events,
    ) = asyncio.run(run_case())

    assert chat_model.calls[0][2] == []
    assert semantic_model.calls
    assert memory_retrieval_model.calls[0][2] == ["search_memory"]
    assert knowledge_retrieval_model.calls[0][2] == ["search_memory"]
    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert wiki_model.calls[0][2] == ["manage_wiki_page"]
    assert memory_model.calls == []
    assert task_model.calls[0][2] == []
    assert_langgraph_events(chat_events, ["token", "done"])
    search_event_names = non_status_event_names(search_events)
    assert search_event_names == ["citation", "citation", "token", "done"]
    assert [event.citation.source_scope for event in search_events if event.event == "citation"] == [
        "personal_memory",
        "knowledge_base",
    ]
    assert_langgraph_events(wiki_events, ["wiki_proposal", "token", "done"])
    assert_langgraph_events(memory_events, ["token", "done"])
    assert_langgraph_events(task_events, ["task", "token", "done"])


def test_langgraph_runtime_returns_stable_error_when_registry_missing_agent_model() -> None:
    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(model_registry=AgentModelRegistry({}))
        )

        return [event async for event in runtime.run(make_state("hello"))]

    events = asyncio.run(run_case())

    assert_langgraph_events(events, ["error"])
    assert first_event(events, "error").code == "agent_model_not_configured"
