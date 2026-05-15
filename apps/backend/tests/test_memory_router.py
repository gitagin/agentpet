from __future__ import annotations

from app.agents.memory_router import MemoryRouter, route_memory
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


def test_long_term_preference_prefers_personal_memory_then_diary_and_daily_chat() -> None:
    route = route_memory("What do you remember about my coding style?")

    assert route.primary_scopes == ("personal_memory",)
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
    assert state.memory_route.primary_scopes == ("personal_memory",)
