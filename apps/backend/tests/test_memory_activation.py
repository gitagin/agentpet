from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.enums import MemoryFactStatus
from app.services.memory_activation import (
    MemoryActivationContext,
    MemoryActivationItem,
    MemoryActivationService,
    activation_item_from_graph_fact,
)
from app.services.memory_graph import MemoryGraphFact
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier


NOW = datetime(2026, 6, 7, 8, 0, tzinfo=timezone.utc)


def _item(
    *,
    memory_id: str = "memory-1",
    memory_kind: MemoryKind = MemoryKind.PREFERENCE,
    memory_scope: MemoryScope = MemoryScope.GLOBAL,
    lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE,
    source_scope: str = "graph_facts",
    text: str = "coding style prefers concise status updates",
    confidence: float = 0.9,
    importance: float = 0.8,
    evidence_count: int = 2,
    updated_at: str | None = None,
    expires_at: str | None = None,
    risk_tier: RiskTier = RiskTier.LOW,
) -> MemoryActivationItem:
    return MemoryActivationItem(
        memory_id=memory_id,
        target_type="fact",
        memory_kind=memory_kind,
        memory_scope=memory_scope,
        lifecycle_status=lifecycle_status,
        source_scope=source_scope,
        text=text,
        confidence=confidence,
        importance=importance,
        evidence_count=evidence_count,
        updated_at=updated_at or NOW.isoformat(),
        expires_at=expires_at,
        risk_tier=risk_tier,
    )


def _decision(item: MemoryActivationItem, *, query: str = "coding style concise status"):
    return MemoryActivationService().score(
        item,
        MemoryActivationContext(query=query, route_scopes=("graph_facts",), now=NOW),
    )


def test_forgotten_rejected_and_superseded_memories_are_never_recalled() -> None:
    expectations = {
        LifecycleStatus.FORGOTTEN: "forgotten_memory",
        LifecycleStatus.REJECTED: "rejected_memory",
        LifecycleStatus.SUPERSEDED: "superseded_memory",
    }

    for status, reason in expectations.items():
        decision = _decision(_item(lifecycle_status=status))

        assert decision.allowed is False
        assert decision.filtered_reason == reason
        assert decision.can_answer_context is False
        assert decision.can_proactively_mention is False


def test_expired_recent_state_cannot_be_used_as_current_fact() -> None:
    expired = _decision(
        _item(
            memory_kind=MemoryKind.RECENT_STATE,
            memory_scope=MemoryScope.TEMPORARY,
            text="project alpha status is blocked",
            expires_at=(NOW - timedelta(days=1)).isoformat(),
        ),
        query="project alpha status",
    )
    current = _decision(
        _item(
            memory_id="memory-2",
            memory_kind=MemoryKind.RECENT_STATE,
            memory_scope=MemoryScope.TEMPORARY,
            text="project alpha status is ready",
            expires_at=(NOW + timedelta(days=1)).isoformat(),
        ),
        query="project alpha status",
    )

    assert expired.allowed is False
    assert expired.filtered_reason == "expired_recent_state"
    assert current.allowed is True
    assert current.can_style_response is True
    assert current.can_proactively_mention is False


def test_sensitive_memory_is_filtered_before_context_use() -> None:
    decision = _decision(
        _item(
            memory_scope=MemoryScope.SENSITIVE,
            risk_tier=RiskTier.HIGH,
            text="private credential detail",
        )
    )

    assert decision.allowed is False
    assert decision.filtered_reason == "sensitive_memory"
    assert decision.can_answer_context is False
    assert decision.can_proactively_mention is False


def test_old_and_stale_memories_lose_score_while_boundaries_stay_strong() -> None:
    fresh = _decision(_item(updated_at=NOW.isoformat()))
    old = _decision(_item(memory_id="old", updated_at=(NOW - timedelta(days=180)).isoformat()))
    active_boundary = _decision(
        _item(
            memory_id="boundary",
            memory_kind=MemoryKind.BOUNDARY,
            text="status updates must stay concise",
            confidence=0.95,
            importance=0.9,
        )
    )
    stale_boundary = _decision(
        _item(
            memory_id="stale-boundary",
            memory_kind=MemoryKind.BOUNDARY,
            lifecycle_status=LifecycleStatus.STALE,
            text="status updates must stay concise",
            confidence=0.95,
            importance=0.9,
        )
    )

    assert fresh.activation_score > old.activation_score
    assert active_boundary.allowed is True
    assert stale_boundary.allowed is True
    assert active_boundary.activation_score > stale_boundary.activation_score


def test_low_confidence_inference_cannot_be_proactively_mentioned() -> None:
    decision = _decision(
        _item(
            memory_kind=MemoryKind.INFERENCE,
            memory_scope=MemoryScope.RELATIONSHIP,
            text="coding style may indicate stress during reviews",
            confidence=0.4,
            importance=0.8,
        )
    )

    assert decision.allowed is True
    assert decision.can_style_response is True
    assert decision.can_answer_context is False
    assert decision.can_proactively_mention is False


def test_query_relevance_and_scope_match_raise_activation_score() -> None:
    item = _item(text="coding style prefers concise status updates")
    matched = MemoryActivationService().score(
        item,
        MemoryActivationContext(query="coding style concise", route_scopes=("graph_facts",), now=NOW),
    )
    weak = MemoryActivationService().score(
        item,
        MemoryActivationContext(query="unrelated dinner plan", route_scopes=("knowledge_base",), now=NOW),
    )

    assert matched.activation_score > weak.activation_score
    assert matched.allowed is True


def test_graph_fact_adapter_maps_statuses_to_activation_items() -> None:
    fact = MemoryGraphFact(
        id="fact-1",
        fact_key="fact-key",
        conflict_key="conflict-key",
        category=MemoryKind.RECENT_STATE.value,
        subject="project alpha",
        predicate="status",
        object="blocked",
        status=MemoryFactStatus.STALE,
        confidence=0.8,
        source_text="Project alpha is blocked.",
        source_type="user_message",
        conversation_id=None,
        user_message_id=None,
        agent_run_id=None,
        support_count=3,
        conflicts_with=None,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        importance=0.7,
    )

    item = activation_item_from_graph_fact(fact)

    assert item.memory_kind is MemoryKind.RECENT_STATE
    assert item.lifecycle_status is LifecycleStatus.STALE
    assert item.memory_scope is MemoryScope.TEMPORARY
