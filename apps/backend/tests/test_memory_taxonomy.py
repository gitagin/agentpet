from app.services.memory_taxonomy import (
    LifecycleStatus,
    MemoryKind,
    MemoryScope,
    RiskTier,
    SourceTrack,
    classify_memory,
)


def test_fact_defaults_to_answer_context_and_persistence() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.FACT,
        memory_scope=MemoryScope.GLOBAL,
        source_track=SourceTrack.SLOW_CONSOLIDATION,
        confidence=0.9,
    )

    assert memory.lifecycle_status is LifecycleStatus.ACTIVE
    assert memory.risk_tier is RiskTier.LOW
    assert memory.recall_permissions.can_answer_context is True
    assert memory.recall_permissions.can_proactively_mention is True
    assert memory.recall_permissions.can_persist is True


def test_preference_defaults_to_style_answer_and_persistence() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.PREFERENCE,
        source_track=SourceTrack.DIARY,
        confidence=0.82,
    )

    assert memory.recall_permissions.can_style_response is True
    assert memory.recall_permissions.can_answer_context is True
    assert memory.recall_permissions.can_suggest_action is True
    assert memory.recall_permissions.can_persist is True


def test_recent_state_can_style_but_does_not_persist_by_default() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.RECENT_STATE,
        memory_scope=MemoryScope.TEMPORARY,
        source_track=SourceTrack.CONTINUITY,
        confidence=0.86,
        expires_at="2026-06-07T00:00:00Z",
    )

    assert memory.lifecycle_status is LifecycleStatus.ACTIVE
    assert memory.recall_permissions.can_style_response is True
    assert memory.recall_permissions.can_answer_context is True
    assert memory.recall_permissions.can_persist is False
    assert memory.recall_permissions.can_proactively_mention is False


def test_boundary_from_explicit_user_is_durable_high_priority() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.BOUNDARY,
        memory_scope=MemoryScope.GLOBAL,
        source_track=SourceTrack.EXPLICIT_USER,
        confidence=0.55,
        importance=0.2,
    )

    assert memory.lifecycle_status is LifecycleStatus.ACTIVE
    assert memory.importance == 0.9
    assert memory.requires_confirmation is False
    assert memory.recall_permissions.can_style_response is True
    assert memory.recall_permissions.can_persist is True
    assert "explicit_boundary_priority" in memory.reasons


def test_project_context_can_be_used_but_needs_lifecycle_review_without_expiry() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.PROJECT_CONTEXT,
        memory_scope=MemoryScope.PROJECT,
        source_track=SourceTrack.SLOW_CONSOLIDATION,
        confidence=0.88,
    )

    assert memory.recall_permissions.can_answer_context is True
    assert memory.recall_permissions.can_suggest_action is True
    assert memory.recall_permissions.can_persist is True
    assert "project_context_requires_lifecycle_review" in memory.reasons


def test_historical_memory_can_answer_but_not_suggest_action_when_archived() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.HISTORICAL,
        memory_scope=MemoryScope.TOPIC,
        lifecycle_status=LifecycleStatus.ARCHIVED,
        confidence=0.9,
    )

    assert memory.recall_permissions.can_answer_context is False
    assert memory.recall_permissions.can_suggest_action is False
    assert memory.recall_permissions.can_persist is False


def test_inference_cannot_persist_or_proactively_mention_by_default() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.INFERENCE,
        memory_scope=MemoryScope.RELATIONSHIP,
        source_track=SourceTrack.MODEL_EXTRACTED,
        confidence=0.9,
    )

    assert memory.lifecycle_status is LifecycleStatus.CANDIDATE
    assert memory.requires_confirmation is True
    assert memory.recall_permissions.can_persist is False
    assert memory.recall_permissions.can_proactively_mention is False
    assert "inference_not_durable_by_default" in memory.reasons


def test_immediate_inference_can_style_current_reply_only() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.INFERENCE,
        memory_scope=MemoryScope.TEMPORARY,
        source_track=SourceTrack.IMMEDIATE,
        confidence=0.8,
    )

    assert memory.lifecycle_status is LifecycleStatus.CANDIDATE
    assert memory.recall_permissions.can_style_response is True
    assert memory.recall_permissions.can_answer_context is False
    assert memory.recall_permissions.can_persist is False


def test_sensitive_memory_is_rejected_and_has_no_recall_permissions() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.FACT,
        memory_scope=MemoryScope.GLOBAL,
        source_track=SourceTrack.EXPLICIT_USER,
        confidence=1.0,
        source_text="remember my api key is sk-sensitive-secret-1234567890",
    )

    assert memory.lifecycle_status is LifecycleStatus.REJECTED
    assert memory.risk_tier is RiskTier.HIGH
    assert memory.recall_permissions.can_style_response is False
    assert memory.recall_permissions.can_answer_context is False
    assert memory.recall_permissions.can_persist is False


def test_sensitive_scope_is_rejected_even_without_sensitive_text() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.HISTORICAL,
        memory_scope=MemoryScope.SENSITIVE,
        source_track=SourceTrack.DIARY,
        confidence=0.95,
    )

    assert memory.lifecycle_status is LifecycleStatus.REJECTED
    assert memory.risk_tier is RiskTier.HIGH
    assert memory.recall_permissions.can_answer_context is False
    assert memory.recall_permissions.can_persist is False


def test_conflicting_non_explicit_memory_requires_confirmation() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.PREFERENCE,
        memory_scope=MemoryScope.GLOBAL,
        source_track=SourceTrack.MODEL_EXTRACTED,
        confidence=0.91,
        conflicting=True,
    )

    assert memory.lifecycle_status is LifecycleStatus.CANDIDATE
    assert memory.risk_tier is RiskTier.MEDIUM
    assert memory.requires_confirmation is True
    assert memory.recall_permissions.can_proactively_mention is False
    assert "conflict_requires_confirmation" in memory.reasons


def test_low_confidence_candidate_cannot_be_proactively_mentioned() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.PROJECT_CONTEXT,
        memory_scope=MemoryScope.PROJECT,
        source_track=SourceTrack.SLOW_CONSOLIDATION,
        confidence=0.42,
    )

    assert memory.lifecycle_status is LifecycleStatus.CANDIDATE
    assert memory.risk_tier is RiskTier.MEDIUM
    assert memory.requires_confirmation is True
    assert memory.recall_permissions.can_proactively_mention is False
    assert memory.recall_permissions.can_persist is False
    assert "low_confidence_candidate" in memory.reasons


def test_explicit_user_memory_overrides_low_confidence_review_default() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.PREFERENCE,
        memory_scope=MemoryScope.GLOBAL,
        source_track=SourceTrack.EXPLICIT_USER,
        confidence=0.3,
    )

    assert memory.lifecycle_status is LifecycleStatus.ACTIVE
    assert memory.requires_confirmation is False
    assert memory.recall_permissions.can_persist is True
    assert "explicit_user_priority" in memory.reasons


def test_superseded_memory_loses_recall_permissions() -> None:
    memory = classify_memory(
        memory_kind=MemoryKind.FACT,
        memory_scope=MemoryScope.GLOBAL,
        source_track=SourceTrack.SLOW_CONSOLIDATION,
        confidence=0.95,
        superseded_by="new-fact-id",
    )

    assert memory.lifecycle_status is LifecycleStatus.SUPERSEDED
    assert memory.superseded_by == "new-fact-id"
    assert memory.recall_permissions.can_answer_context is False
    assert memory.recall_permissions.can_persist is False
