from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import log1p
from typing import Iterable, Mapping

from app.models.enums import MemoryFactStatus
from app.services.memory_candidates import MemoryCandidateRecord
from app.services.memory_graph import MemoryGraphFact
from app.services.memory_taxonomy import LOW_CONFIDENCE_THRESHOLD, LifecycleStatus, MemoryKind, MemoryScope, RiskTier, fact_lifecycle_status

from app.utils.coerce import clamp_unit_interval


@dataclass(frozen=True, slots=True)
class MemoryActivationContext:
    query: str
    route_scopes: tuple[str, ...] = ()
    now: datetime | None = None
    min_score: float = 0.45


@dataclass(frozen=True, slots=True)
class MemoryActivationItem:
    memory_id: str
    target_type: str
    memory_kind: MemoryKind
    memory_scope: MemoryScope
    lifecycle_status: LifecycleStatus
    source_scope: str
    text: str
    confidence: float
    importance: float
    evidence_count: int
    updated_at: str | None = None
    expires_at: str | None = None
    last_confirmed_at: str | None = None
    risk_tier: RiskTier = RiskTier.LOW
    has_conflict: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryActivationDecision:
    item: MemoryActivationItem
    allowed: bool
    activation_score: float
    score_breakdown: dict[str, float]
    filtered_reason: str | None = None
    can_style_response: bool = False
    can_answer_context: bool = False
    can_proactively_mention: bool = False
    can_suggest_action: bool = False


class MemoryActivationService:
    def score(
        self,
        item: MemoryActivationItem,
        context: MemoryActivationContext,
    ) -> MemoryActivationDecision:
        now = _normalized_now(context.now)
        hard_gate = _hard_gate(item, context, now=now)
        breakdown = _score_breakdown(item, context, now=now)
        score = clamp_unit_interval(sum(breakdown.values()))
        if hard_gate is not None:
            return MemoryActivationDecision(
                item=item,
                allowed=False,
                activation_score=score,
                score_breakdown=breakdown,
                filtered_reason=hard_gate,
            )
        if score < context.min_score:
            return MemoryActivationDecision(
                item=item,
                allowed=False,
                activation_score=score,
                score_breakdown=breakdown,
                filtered_reason="below_activation_threshold",
            )
        can_answer = item.memory_kind is not MemoryKind.INFERENCE and item.memory_scope is not MemoryScope.SENSITIVE
        can_style = item.memory_kind in {
            MemoryKind.PREFERENCE,
            MemoryKind.RECENT_STATE,
            MemoryKind.BOUNDARY,
            MemoryKind.INFERENCE,
        }
        can_proactive = (
            can_answer
            and item.lifecycle_status is LifecycleStatus.ACTIVE
            and item.risk_tier is RiskTier.LOW
            and item.confidence >= 0.75
            and item.memory_kind not in {MemoryKind.INFERENCE, MemoryKind.RECENT_STATE}
            and item.memory_scope not in {MemoryScope.SENSITIVE, MemoryScope.TEMPORARY, MemoryScope.RELATIONSHIP}
        )
        can_suggest = (
            can_answer
            and item.confidence >= LOW_CONFIDENCE_THRESHOLD
            and item.memory_kind in {MemoryKind.PREFERENCE, MemoryKind.BOUNDARY, MemoryKind.PROJECT_CONTEXT, MemoryKind.RECENT_STATE}
        )
        return MemoryActivationDecision(
            item=item,
            allowed=True,
            activation_score=score,
            score_breakdown=breakdown,
            can_style_response=can_style,
            can_answer_context=can_answer,
            can_proactively_mention=can_proactive,
            can_suggest_action=can_suggest,
        )


def activation_item_from_graph_fact(fact: MemoryGraphFact) -> MemoryActivationItem:
    kind = _kind_from_graph_fact(fact)
    scope = _scope_for_kind(kind)
    return MemoryActivationItem(
        memory_id=fact.id,
        target_type="fact",
        memory_kind=kind,
        memory_scope=scope,
        lifecycle_status=fact_lifecycle_status(fact.status),
        source_scope="graph_facts",
        text=f"{fact.subject} {fact.predicate} {fact.object}",
        confidence=fact.confidence,
        importance=fact.importance,
        evidence_count=fact.support_count,
        updated_at=fact.updated_at,
        expires_at=fact.expires_at,
        risk_tier=RiskTier.HIGH if fact.status is MemoryFactStatus.SENSITIVE_BLOCKED else RiskTier.LOW,
        has_conflict=bool(fact.conflicts_with),
        metadata={"status": fact.status.value, "superseded_by": fact.superseded_by},
    )


def activation_item_from_candidate(candidate: MemoryCandidateRecord) -> MemoryActivationItem:
    return MemoryActivationItem(
        memory_id=candidate.id,
        target_type="candidate",
        memory_kind=candidate.memory_kind,
        memory_scope=candidate.memory_scope,
        lifecycle_status=candidate.status,
        source_scope="memory_candidates",
        text=candidate.summary,
        confidence=candidate.confidence,
        importance=candidate.importance,
        evidence_count=candidate.evidence_count,
        updated_at=candidate.updated_at,
        expires_at=candidate.expires_at,
        last_confirmed_at=candidate.last_confirmed_at,
        risk_tier=candidate.risk_tier,
        metadata=candidate.metadata,
    )


def rank_activation_decisions(
    decisions: Iterable[MemoryActivationDecision],
    *,
    limit: int,
    require_answer_context: bool = True,
) -> tuple[MemoryActivationDecision, ...]:
    allowed = [
        decision
        for decision in decisions
        if decision.allowed and (decision.can_answer_context or not require_answer_context)
    ]
    allowed.sort(key=lambda decision: (-decision.activation_score, decision.item.source_scope, decision.item.memory_id))
    return tuple(allowed[: max(1, limit)])


def _hard_gate(item: MemoryActivationItem, context: MemoryActivationContext, *, now: datetime) -> str | None:
    if item.lifecycle_status is LifecycleStatus.FORGOTTEN:
        return "forgotten_memory"
    if item.lifecycle_status is LifecycleStatus.REJECTED:
        return "rejected_memory"
    if item.lifecycle_status is LifecycleStatus.SUPERSEDED:
        return "superseded_memory"
    if item.lifecycle_status is LifecycleStatus.CANDIDATE:
        return "conflicting_memory" if item.has_conflict else "candidate_memory"
    if item.memory_scope is MemoryScope.SENSITIVE or item.risk_tier is RiskTier.HIGH:
        return "sensitive_memory"
    if item.has_conflict and item.lifecycle_status is not LifecycleStatus.ACTIVE:
        return "conflicting_memory"
    if _is_expired(item.expires_at, now=now):
        return "expired_recent_state" if item.memory_kind is MemoryKind.RECENT_STATE else "expired_memory"
    if item.lifecycle_status is LifecycleStatus.ARCHIVED and not _historical_query(context.query):
        return "archived_memory_not_current"
    return None


def _score_breakdown(item: MemoryActivationItem, context: MemoryActivationContext, *, now: datetime) -> dict[str, float]:
    relevance = _query_relevance(context.query, item.text)
    scope_match = _scope_match(item, context.route_scopes)
    lifecycle = {
        LifecycleStatus.ACTIVE: 1.0,
        LifecycleStatus.CANDIDATE: 0.55,
        LifecycleStatus.STALE: 0.35,
        LifecycleStatus.ARCHIVED: 0.2,
        LifecycleStatus.FORGOTTEN: 0.0,
        LifecycleStatus.REJECTED: 0.0,
        LifecycleStatus.SUPERSEDED: 0.0,
    }[item.lifecycle_status]
    evidence = min(log1p(max(0, item.evidence_count)) / log1p(6), 1.0)
    recency = _recency_score(item.last_confirmed_at or item.updated_at, now=now)
    conflict_penalty = -0.16 if item.has_conflict else 0.0
    expired_penalty = -0.22 if _is_expired(item.expires_at, now=now) else 0.0
    boundary_boost = 0.18 if item.memory_kind is MemoryKind.BOUNDARY else 0.0
    stale_penalty = -0.12 if item.lifecycle_status is LifecycleStatus.STALE else 0.0
    return {
        "query_relevance": 0.28 * relevance,
        "scope_match": 0.16 * scope_match,
        "lifecycle_status": 0.18 * lifecycle,
        "confidence": 0.13 * clamp_unit_interval(item.confidence),
        "importance": 0.1 * clamp_unit_interval(item.importance),
        "evidence_count": 0.05 * evidence,
        "recency": 0.05 * recency,
        "boundary_boost": boundary_boost,
        "conflict_penalty": conflict_penalty,
        "expired_penalty": expired_penalty,
        "stale_penalty": stale_penalty,
    }


def _query_relevance(query: str, text: str) -> float:
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    text_terms = _terms(text)
    if not text_terms:
        return 0.0
    overlap = len(set(query_terms) & set(text_terms))
    if overlap == 0:
        return 0.0
    return min(1.0, overlap / max(1, min(len(set(query_terms)), 6)))


def _scope_match(item: MemoryActivationItem, route_scopes: tuple[str, ...]) -> float:
    if not route_scopes:
        return 0.6
    if item.source_scope in route_scopes:
        return 1.0
    if item.source_scope == "graph_facts" and "personal_memory" in route_scopes:
        return 0.9
    if item.memory_scope.value in route_scopes:
        return 0.85
    if "all" in route_scopes:
        return 0.8
    return 0.25


def _recency_score(value: str | None, *, now: datetime) -> float:
    timestamp = _parse_time(value)
    if timestamp is None:
        return 0.35
    days = max(0.0, (now - timestamp).total_seconds() / 86400)
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.75
    if days <= 90:
        return 0.45
    return 0.2


def _is_expired(value: str | None, *, now: datetime) -> bool:
    timestamp = _parse_time(value)
    return timestamp is not None and timestamp <= now


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_now(value: datetime | None) -> datetime:
    now = value or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _terms(value: str) -> tuple[str, ...]:
    cleaned = "".join(char.casefold() if char.isalnum() else " " for char in value)
    return tuple(term for term in cleaned.split() if len(term) >= 3 and term not in _STOP_WORDS)


def _historical_query(query: str) -> bool:
    normalized = query.casefold()
    markers = ("old", "past", "previous", "history", "historical", "completed", "archived", "done", "finished")
    return any(marker in normalized for marker in markers)


def _kind_from_graph_fact(fact: MemoryGraphFact) -> MemoryKind:
    for raw in (fact.memory_type, fact.category):
        if not raw:
            continue
        try:
            return MemoryKind(str(raw))
        except ValueError:
            continue
    return MemoryKind.FACT


def _scope_for_kind(kind: MemoryKind) -> MemoryScope:
    if kind is MemoryKind.PROJECT_CONTEXT:
        return MemoryScope.PROJECT
    if kind is MemoryKind.RECENT_STATE:
        return MemoryScope.TEMPORARY
    if kind is MemoryKind.BOUNDARY:
        return MemoryScope.GLOBAL
    if kind is MemoryKind.INFERENCE:
        return MemoryScope.RELATIONSHIP
    return MemoryScope.GLOBAL






_STOP_WORDS = {
    "about",
    "after",
    "again",
    "before",
    "does",
    "have",
    "that",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "your",
}
