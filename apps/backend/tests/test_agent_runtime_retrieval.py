from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
from app.models.api import MemoryRecallPermissions, MemorySearchResponse, MemorySearchResult
from app.services.chat_model import AgentId, AgentModelRegistry


class PermissionedRetrieval:
    def __init__(self) -> None:
        self.calls = []

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchResponse:
        self.calls.append((query, top_k, mode, source_scope))
        if source_scope == "personal_memory":
            return MemorySearchResponse(
                results=[
                    MemorySearchResult(
                        note_id="fact-pressure",
                        chunk_id="fact-pressure",
                        relative_path="MemoryGraph/LongTerm",
                        title="Structured Long-Term Memory",
                        heading="pressure",
                        snippet="Ada has been under pressure recently.",
                        score=0.86,
                        source_scope="personal_memory",
                        retrieval_mode="graph_activation",
                        recall_permissions=MemoryRecallPermissions(can_style_response=True, can_answer_context=False),
                        activation_score=0.86,
                        score_breakdown={"query_relevance": 0.1},
                        memory_kind="recent_state",
                        fact_id="fact-pressure",
                    ),
                    MemorySearchResult(
                        note_id="fact-project",
                        chunk_id="fact-project",
                        relative_path="MemoryGraph/LongTerm",
                        title="Structured Long-Term Memory",
                        heading="project",
                        snippet="Ada is working on project Atlas.",
                        score=0.82,
                        source_scope="personal_memory",
                        retrieval_mode="graph_activation",
                        recall_permissions=MemoryRecallPermissions(
                            can_answer_context=True,
                            can_proactively_mention=True,
                            can_suggest_action=True,
                        ),
                        activation_score=0.82,
                        score_breakdown={"query_relevance": 0.2},
                        memory_kind="project_context",
                        fact_id="fact-project",
                    ),
                ]
            )
        if source_scope == "diary_objects":
            return MemorySearchResponse(
                results=[
                    MemorySearchResult(
                        note_id="fact-style",
                        chunk_id="fact-style",
                        relative_path="DiaryMemory/fact-style",
                        title="Structured Diary Memory",
                        heading="style",
                        snippet="Ada prefers concise status updates.",
                        score=0.95,
                        source_scope="diary_objects",
                        retrieval_mode="diary_object",
                        recall_permissions=MemoryRecallPermissions(
                            can_style_response=True,
                            can_answer_context=True,
                            can_proactively_mention=True,
                            can_suggest_action=True,
                        ),
                        activation_score=0.95,
                        score_breakdown={"query_relevance": 0.3},
                        memory_kind="preference",
                        fact_id="fact-style",
                    )
                ]
            )
        return MemorySearchResponse(results=[])


class FakeActivationRecorder:
    def __init__(self) -> None:
        self.records = []

    def record_usage(self, **kwargs) -> None:
        self.records.append(kwargs)


def test_langgraph_runtime_preserves_core_search_event_contract() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert events[0].event == "status"
    retrieval_statuses = [event for event in events if event.event == "status" and event.stage in {"personal_memory_retrieval", "knowledge_base_retrieval"}]
    assert [event.source_scopes for event in retrieval_statuses] == [["personal_memory"], ["knowledge_base"]]
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
                automation_settings=SimpleNamespace(use_negotiation=False),
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
                automation_settings=SimpleNamespace(use_negotiation=False),
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
                automation_settings=SimpleNamespace(use_negotiation=False),
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
    fallback_status = next(event for event in events if getattr(event, "stage", None) == "daily_chat_fallback")
    assert fallback_status.source_scopes == ["daily_chat"]
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
                automation_settings=SimpleNamespace(use_negotiation=False),
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
                automation_settings=SimpleNamespace(use_negotiation=False),
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
    multi_source_status = next(event for event in events if getattr(event, "stage", None) == "multi_source_memory_retrieval")
    assert multi_source_status.source_scopes == ["personal_memory", "diary_objects", "daily_chat"]
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


def test_langgraph_splits_recalled_memory_by_permissions_and_records_usage() -> None:
    async def run_case():
        retrieval = PermissionedRetrieval()
        recorder = FakeActivationRecorder()
        chat_model = FakeRegistryChatModel(None, "permissioned answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                memory_activation_recorder=recorder,
                model_registry=AgentModelRegistry({AgentId.CHAT_AGENT: chat_model}),
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [
            event
            async for event in runtime.run(make_state("What do you remember about my coding style?"))
        ]
        return retrieval, recorder, chat_model, events

    retrieval, recorder, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("What do you remember about my coding style?", 5, "fts", "personal_memory"),
        ("What do you remember about my coding style?", 5, "fts", "diary_objects"),
        ("What do you remember about my coding style?", 5, "fts", "daily_chat"),
    ]
    prompt = chat_model.calls[-1][0]
    assert "Style memory (tone only; do not mention as facts):" in prompt
    assert "Use a softer, low-pressure tone" in prompt
    assert "Ada has been under pressure recently." not in prompt
    assert "Answer context (may be used as answer evidence):" in prompt
    assert "Ada prefers concise status updates." in prompt
    assert "Ada is working on project Atlas." not in prompt

    by_fact_id = {record["result"].fact_id: record for record in recorder.records}
    assert by_fact_id["fact-pressure"]["used_for_style"] is True
    assert by_fact_id["fact-pressure"]["used_for_answer_context"] is False
    assert by_fact_id["fact-style"]["used_for_answer_context"] is True
    assert by_fact_id["fact-style"]["used_for_proactive_mention"] is True
    assert by_fact_id["fact-project"]["filtered_reason"] == "permission_gate_no_prompt_section"
    assert_langgraph_events(events, ["context_budget", "citation", "citation", "citation", "token", "done"])


def test_langgraph_project_context_only_enters_prompt_for_relevant_project_queries() -> None:
    async def run_case():
        retrieval = PermissionedRetrieval()
        recorder = FakeActivationRecorder()
        chat_model = FakeRegistryChatModel(None, "project answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                memory_activation_recorder=recorder,
                model_registry=AgentModelRegistry({AgentId.CHAT_AGENT: chat_model}),
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [
            event
            async for event in runtime.run(make_state("What do you remember about my coding style project Atlas?"))
        ]
        return recorder, chat_model, events

    recorder, chat_model, events = asyncio.run(run_case())

    prompt = chat_model.calls[-1][0]
    assert "Ada is working on project Atlas." in prompt
    by_fact_id = {record["result"].fact_id: record for record in recorder.records}
    assert by_fact_id["fact-project"]["used_for_answer_context"] is True
    assert by_fact_id["fact-project"]["used_for_proactive_mention"] is True
    assert by_fact_id["fact-project"]["used_for_action_suggestion"] is True
    assert_langgraph_events(events, ["context_budget", "citation", "citation", "citation", "token", "done"])
