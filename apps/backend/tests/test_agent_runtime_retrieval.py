from __future__ import annotations

import asyncio

from tests.agent_runtime_fakes import (
    FakeCompanionReportStore,
    FakeMultiScopeRetrieval,
    FakePersonalEmptyDailyRetrieval,
    FakeRegistryChatModel,
    FakeRetrieval,
    FakeScopedRetrieval,
    FakeSemanticModel,
    assert_langgraph_events,
    first_event,
    make_state,
)

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.services.chat_model import AgentId, AgentModelRegistry


def test_langgraph_runtime_preserves_core_search_event_contract() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        runtime = LangGraphAgentRuntime(AgentRuntimeServices(retrieval=retrieval))

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert events[0].event == "status"
    assert [event.citation.source_scope for event in events if event.event == "citation"] == [
        "personal_memory",
        "knowledge_base",
    ]
    assert any(event.event == "token" for event in events)
    assert events[-1].event == "done"
    assert first_event(events, "citation").citation.relative_path == "People/Ada.md"


def test_langgraph_semantic_agent_drives_memory_retrieval_before_chat() -> None:
    async def run_case():
        retrieval = FakeScopedRetrieval()
        semantic_model = FakeSemanticModel(
            {
                "needs_context": True,
                "source_scope": "personal_memory",
                "query": "用户喜欢什么水果",
                "answer_style": "concise",
                "confidence": 0.92,
                "reason": "personal preference question",
            }
        )
        memory_retrieval_model = FakeRegistryChatModel(None, "memory checked")
        chat_model = FakeRegistryChatModel(None, "我翻到记录里写着你喜欢苹果。")
        memory_model = FakeRegistryChatModel("propose_memory", "memory answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.MEMORY_RETRIEVAL_AGENT: memory_retrieval_model,
                        AgentId.CHAT_AGENT: chat_model,
                        AgentId.MEMORY_PROPOSAL_AGENT: memory_model,
                    }
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("Can you use the earlier context?"))]
        return retrieval, semantic_model, memory_retrieval_model, chat_model, memory_model, events

    retrieval, semantic_model, memory_retrieval_model, chat_model, memory_model, events = asyncio.run(run_case())

    assert semantic_model.calls[0][0] == "Can you use the earlier context?"
    assert memory_retrieval_model.calls[0][2] == ["search_memory"]
    assert retrieval.calls == [("用户喜欢什么水果", 5, "fts", "personal_memory")]
    assert memory_model.calls == []
    assert "用户喜欢苹果" in chat_model.calls[-1][0]
    assert "Memories/Preferences.md" in chat_model.calls[-1][0]
    assert_langgraph_events(events, ["citation", "token", "done"])
    assert first_event(events, "token").text == "我翻到记录里写着你喜欢苹果。"


def test_langgraph_semantic_agent_drives_knowledge_retrieval_before_chat() -> None:
    async def run_case():
        retrieval = FakeScopedRetrieval()
        semantic_model = FakeSemanticModel(
            {
                "needs_context": True,
                "source_scope": "knowledge_base",
                "query": "runtime docs",
                "answer_style": "grounded",
                "confidence": 0.92,
                "reason": "knowledge-base question",
            }
        )
        knowledge_retrieval_model = FakeRegistryChatModel(None, "knowledge checked")
        chat_model = FakeRegistryChatModel(None, "knowledge answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.KNOWLEDGE_RETRIEVAL_AGENT: knowledge_retrieval_model,
                        AgentId.CHAT_AGENT: chat_model,
                    }
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("search docs for runtime"))]
        return retrieval, knowledge_retrieval_model, chat_model, events

    retrieval, knowledge_retrieval_model, chat_model, events = asyncio.run(run_case())

    assert knowledge_retrieval_model.calls[0][2] == ["search_memory"]
    assert retrieval.calls == [("runtime docs", 5, "fts", "knowledge_base")]
    assert "Wiki/Runtime.md" in chat_model.calls[-1][0]
    assert_langgraph_events(events, ["citation", "token", "done"])


def test_langgraph_falls_back_to_daily_chat_as_weak_evidence_when_personal_memory_empty() -> None:
    async def run_case():
        retrieval = FakePersonalEmptyDailyRetrieval()
        semantic_model = FakeSemanticModel(
            {
                "needs_context": True,
                "source_scope": "personal_memory",
                "query": "用户喜欢什么水果",
                "answer_style": "concise",
                "confidence": 0.9,
                "reason": "personal preference question",
            }
        )
        memory_retrieval_model = FakeRegistryChatModel(None, "memory checked")
        chat_model = FakeRegistryChatModel(None, "我只在聊天日记里看到你提过苹果，还没沉淀为长期记忆。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.MEMORY_RETRIEVAL_AGENT: memory_retrieval_model,
                        AgentId.CHAT_AGENT: chat_model,
                    }
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("Can you use the earlier context?"))]
        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("用户喜欢什么水果", 5, "fts", "personal_memory"),
        ("用户喜欢什么水果", 5, "fts", "daily_chat"),
    ]
    assert "上下文范围：daily_chat" in chat_model.calls[-1][0]
    assert "还没沉淀为长期记忆" in chat_model.calls[-1][0]
    assert first_event(events, "citation").citation.source_scope == "daily_chat"
    assert any(getattr(event, "stage", None) == "daily_chat_fallback" for event in events)
    assert_langgraph_events(events, ["citation", "token", "done"])


def test_langgraph_forces_date_recall_to_daily_chat_even_when_semantic_model_misroutes() -> None:
    async def run_case():
        retrieval = FakePersonalEmptyDailyRetrieval()
        semantic_model = FakeSemanticModel(
            {
                "needs_context": True,
                "source_scope": "personal_memory",
                "query": "用户喜欢什么水果",
                "answer_style": "grounded",
                "confidence": 0.9,
                "reason": "bad model route",
            }
        )
        memory_retrieval_model = FakeRegistryChatModel(None, "memory checked")
        chat_model = FakeRegistryChatModel(None, "5月4号的聊天日记里，你说过自己喜欢苹果。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.MEMORY_RETRIEVAL_AGENT: memory_retrieval_model,
                        AgentId.CHAT_AGENT: chat_model,
                    }
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("我在5月4号说了什么事情吗？"))]
        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [("我在5月4号说了什么事情吗？", 5, "fts", "daily_chat")]
    assert "上下文范围：daily_chat" in chat_model.calls[-1][0]
    assert "用户说自己喜欢苹果" in chat_model.calls[-1][0]
    assert_langgraph_events(events, ["citation", "token", "done"])


def test_langgraph_aggregates_and_compresses_companion_memory_route_scopes() -> None:
    async def run_case():
        retrieval = FakeMultiScopeRetrieval()
        chat_model = FakeRegistryChatModel(None, "companion memory answer")
        reports = FakeCompanionReportStore()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                companion_retrieval_reports=reports,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.CHAT_AGENT: chat_model,
                    }
                ),
            )
        )

        events = [
            event
            async for event in runtime.run(make_state("What do you remember about my coding style?"))
        ]
        return retrieval, chat_model, reports, events

    retrieval, chat_model, reports, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("What do you remember about my coding style?", 5, "fts", "personal_memory"),
        ("What do you remember about my coding style?", 5, "fts", "diary_objects"),
        ("What do you remember about my coding style?", 5, "fts", "daily_chat"),
    ]
    citation_events = [event for event in events if event.event == "citation"]
    assert [event.citation.source_scope for event in citation_events] == [
        "personal_memory",
        "personal_memory",
        "diary_objects",
        "daily_chat",
    ]
    assert "Ada prefers concise status updates." in chat_model.calls[-1][0]
    assert "Ada felt focused after a refactor review." in chat_model.calls[-1][0]
    assert "This lower priority personal memory should be compressed away." not in chat_model.calls[-1][0]
    assert "上下文范围：all" in chat_model.calls[-1][0]
    budget_event = first_event(events, "context_budget")
    assert budget_event.strategy == "deterministic_v1"
    assert budget_event.candidate_count == 5
    assert budget_event.selected_count == 4
    assert reports.records[0][0] == "run-1"
    assert reports.records[0][1] == "What do you remember about my coding style?"
    assert reports.records[0][2].selected_count == 4
    assert_langgraph_events(events, ["context_budget", "citation", "citation", "citation", "citation", "token", "done"])
