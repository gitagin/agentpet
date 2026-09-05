from __future__ import annotations

from app.agents.memory_router import MemoryRoute, MemoryRouter, route_memory
from app.agents.state import AgentState


def test_technical_knowledge_question_prefers_knowledge_base_and_avoids_diary() -> None:
    route = route_memory("How do I implement a FastAPI migration for SQLite?")

    assert route.primary_scopes == ("knowledge_base",)
    assert route.fallback_scopes == ("none",)
    assert "diary_objects" not in route.all_scopes
    assert "daily_chat" not in route.all_scopes
    assert route.answer_style == "concise"
    assert route.confidence >= 0.8
    assert route.reason == "technical_knowledge"
    assert route.legacy_source_scope == "knowledge_base"
    assert route.retrieval_top_k == 5


def test_personal_emotional_continuity_prefers_diary_then_daily_chat() -> None:
    route = route_memory("Remember when I felt anxious about the presentation?")

    assert route.primary_scopes == ("diary_objects",)
    assert route.fallback_scopes == ("daily_chat",)
    assert route.answer_style == "grounded"
    assert route.confidence >= 0.8
    assert route.reason == "personal_experience_or_emotional_continuity"
    assert route.legacy_source_scope == "daily_chat"


def test_explicit_date_recall_prefers_daily_chat() -> None:
    route = route_memory("What did I tell you on May 4 about the interview?")

    assert route.primary_scopes == ("daily_chat",)
    assert route.fallback_scopes == ("diary_objects", "personal_memory")
    assert route.answer_style == "grounded"
    assert route.reason == "explicit_date_recall"
    assert route.legacy_source_scope == "all"
    assert route.retrieval_top_k == 20


def test_relative_date_recall_prefers_daily_chat() -> None:
    for query in (
        "我昨天和你聊了什么",
        "我今天说过什么",
        "我前天记录了什么事情",
        "我后天有什么聊天记录",
    ):
        route = route_memory(query)

        assert route.primary_scopes == ("daily_chat",)
        assert route.reason == "explicit_date_recall"
        assert route.retrieval_top_k == 20


def test_long_term_preference_prefers_graph_facts_then_personal_memory_then_diary_and_daily_chat() -> None:
    route = route_memory("What do you remember about my coding style?")

    assert route.primary_scopes == ("graph_facts", "personal_memory")
    assert route.fallback_scopes == ("diary_objects", "daily_chat")
    assert route.answer_style == "grounded"
    assert route.confidence >= 0.8
    assert route.reason == "long_term_preference"
    assert route.legacy_source_scope == "all"


def test_low_confidence_ambiguous_memory_request_signals_semantic_fallback() -> None:
    route = route_memory("Can you use the earlier context?")

    assert route.primary_scopes == ()
    assert route.fallback_scopes == ("knowledge_base", "personal_memory", "diary_objects", "daily_chat")
    assert route.answer_style == "clarifying"
    assert route.confidence < 0.5
    assert route.semantic_fallback is True
    assert route.reason == "ambiguous_memory_request_semantic_fallback"
    assert route.legacy_source_scope == "all"


def test_router_is_deterministic_for_repeated_messages() -> None:
    router = MemoryRouter()
    first = router.route("What did I say on 2026-05-04?")
    second = router.route("What did I say on 2026-05-04?")

    assert first == second


def test_agent_state_can_carry_memory_route_without_requiring_runtime_wiring() -> None:
    route = route_memory("Do I prefer concise status updates?")
    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="Do I prefer concise status updates?",
        memory_route=route,
    )

    assert state.memory_route == route
    assert state.memory_route.primary_scopes == ("graph_facts", "personal_memory")


def test_preference_statement_routes_to_casual_chat_not_retrieval() -> None:
    """「我喜欢牛奶」是告知偏好（陈述句），不是检索请求，不应触发记忆检索。"""
    route = route_memory("我喜欢牛奶")

    assert route.primary_scopes == ("none",)
    assert route.all_scopes == ("none",)
    assert route.answer_style == "casual"
    assert route.reason == "no_memory_context_needed"


def test_preference_question_still_routes_to_retrieval() -> None:
    """「我喜欢什么」带疑问词，仍是询问偏好，应触发检索。"""
    route = route_memory("我喜欢什么")

    assert route.reason == "long_term_preference"
    assert route.primary_scopes == ("graph_facts", "personal_memory")
    assert route.answer_style == "grounded"


def test_graph_fact_only_route_bridges_to_legacy_personal_memory_scope() -> None:
    route = MemoryRoute(primary_scopes=("graph_facts",), query="coding style")

    assert route.primary_scopes == ("graph_facts",)
    assert route.legacy_source_scope == "personal_memory"
