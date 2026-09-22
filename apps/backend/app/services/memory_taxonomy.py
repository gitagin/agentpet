from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from app.models.enums import MemoryFactStatus
from app.services.memory_policy import evaluate_memory_content
from app.utils.coerce import clamp_unit_interval


class _StrEnum(str, Enum):
    pass


class MemoryKind(_StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    RECENT_STATE = "recent_state"
    BOUNDARY = "boundary"
    PROJECT_CONTEXT = "project_context"
    HISTORICAL = "historical"
    INFERENCE = "inference"


# 记忆种类 -> 事实范畴(A4 两轴之「事实范畴轴」;与 ContentCategory 的字符串值对齐)。
# 只有 PREFERENCE 落入用户权威类(preference),其余归事实类——
# 这正是「用户偏好 vs 外部事实」的区分点,不可混淆。
_KIND_TO_CONTENT_CATEGORY: dict[str, str] = {
    MemoryKind.FACT: "fact",
    MemoryKind.PREFERENCE: "preference",
    MemoryKind.RECENT_STATE: "event",
    MemoryKind.BOUNDARY: "rule",
    MemoryKind.PROJECT_CONTEXT: "fact",
    MemoryKind.HISTORICAL: "event",
    MemoryKind.INFERENCE: "fact",
}


def content_category_for_kind(kind: object) -> str:
    """把记忆种类归一为事实范畴(未知种类保守归 fact,不冒充用户权威)。"""
    return _KIND_TO_CONTENT_CATEGORY.get(kind, "fact")


def content_category_from_metadata(metadata: object) -> str | None:
    """从持久化 metadata 读回事实范畴,作为检索期的读侧入口。

    缺失、损坏或空值一律返回 None,**不**回退为 "fact":
    读侧若凭空断言范畴,就会把「不知道」伪装成「已判定为外部事实」。
    None 会让 evidence_policy.statement_authority 保守降级为 mixed,
    这正是写入侧没带该字段时应有的行为。
    """
    if isinstance(metadata, Mapping):
        raw = metadata.get("content_category")
    else:
        try:
            parsed = json.loads(str(metadata or ""))
        except (TypeError, ValueError):
            return None
        if not isinstance(parsed, Mapping):
            return None
        raw = parsed.get("content_category")
    value = str(raw or "").strip()
    return value or None


# 关系类型 -> 事实范畴:只登记**语义唯一**的推导。
# 目前只有 prefers 一条,依据是它的两个写入点都表示「偏好」:
#   memory_consolidation.py 的 PREFERENCE 分支(memory_kind 已是 PREFERENCE 才走这里)
#   chat_pipeline/entity_relation.py 的确定性偏好兜底(先断言 category == "preference")
# 其余关系类型一律不登记 —— 尤其 avoids:「我不喜欢/回避 X」看似也是偏好,
# 但**没有任何写入点**会为 PREFERENCE 产出 avoids,把它当偏好就是我在替代码发明规则。
_RELATION_TO_CONTENT_CATEGORY: dict[str, str] = {
    "prefers": "preference",
}


def content_category_for_relation(relation_type: object) -> str | None:
    """从关系类型重建事实范畴;无法无歧义推导时返回 None(**不猜测**)。"""
    return _RELATION_TO_CONTENT_CATEGORY.get(
        str(relation_type or "").strip().casefold()
    )


def graph_fact_content_category(fact: object) -> str | None:
    """读侧事实范畴:metadata 优先,仅在 metadata 沉默时才由关系类型重建。

    为什么需要重建:create_relation 在修复前不落 metadata,所以**旧库**里的偏好
    关系边 metadata 恒为 "{}"。若读侧只认 metadata,这批行的陈述权威轴永远失明。

    为什么是「读侧重建」而不是「数据回填迁移」:两者对唯一消费者
    (memory_read -> MemorySearchResult.content_category -> statement_authority)
    的效果完全相同,但重建不写用户数据、不进启动迁移链、且天然覆盖所有年代的行。
    优先级刻意不合并:metadata 写了就以它为准(那是写入期记录),
    重建只是 metadata 沉默时的兜底,不会覆盖任何已记录的值。
    """
    recorded = content_category_from_metadata(getattr(fact, "metadata_json", None))
    if recorded is not None:
        return recorded
    return content_category_for_relation(getattr(fact, "relation_type", None))


class MemoryScope(_StrEnum):
    GLOBAL = "global"
    PROJECT = "project"
    TOPIC = "topic"
    RELATIONSHIP = "relationship"
    TEMPORARY = "temporary"
    SENSITIVE = "sensitive"


class LifecycleStatus(_StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    FORGOTTEN = "forgotten"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class SourceTrack(_StrEnum):
    IMMEDIATE = "immediate"
    SLOW_CONSOLIDATION = "slow_consolidation"
    EXPLICIT_USER = "explicit_user"
    MODEL_EXTRACTED = "model_extracted"
    DIARY = "diary"
    CONTINUITY = "continuity"


class RiskTier(_StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RecallPermissions:
    can_style_response: bool = False
    can_answer_context: bool = False
    can_proactively_mention: bool = False
    can_suggest_action: bool = False
    can_persist: bool = False


@dataclass(frozen=True)
class MemoryTaxonomy:
    memory_kind: MemoryKind
    memory_scope: MemoryScope
    lifecycle_status: LifecycleStatus
    source_track: SourceTrack
    risk_tier: RiskTier
    confidence: float
    importance: float
    evidence_count: int
    expires_at: str | None = None
    last_confirmed_at: str | None = None
    superseded_by: str | None = None
    recall_permissions: RecallPermissions = field(default_factory=RecallPermissions)
    requires_confirmation: bool = False
    reasons: tuple[str, ...] = ()


LOW_CONFIDENCE_THRESHOLD = 0.65
PROACTIVE_CONFIDENCE_THRESHOLD = 0.75


def classify_memory(
    *,
    memory_kind: MemoryKind | str,
    memory_scope: MemoryScope | str = MemoryScope.GLOBAL,
    source_track: SourceTrack | str = SourceTrack.SLOW_CONSOLIDATION,
    lifecycle_status: LifecycleStatus | str | None = None,
    risk_tier: RiskTier | str | None = None,
    confidence: float = 0.5,
    importance: float = 0.5,
    evidence_count: int = 1,
    expires_at: str | None = None,
    last_confirmed_at: str | None = None,
    superseded_by: str | None = None,
    source_text: str = "",
    conflicting: bool = False,
    sensitive: bool = False,
) -> MemoryTaxonomy:
    kind = MemoryKind(memory_kind)
    scope = MemoryScope(memory_scope)
    track = SourceTrack(source_track)
    normalized_confidence = clamp_unit_interval(confidence)
    normalized_importance = clamp_unit_interval(importance)
    normalized_evidence = max(0, int(evidence_count))
    reasons: list[str] = []

    sensitive_reason = _sensitive_reason(source_text) if source_text else None
    is_sensitive = sensitive or scope is MemoryScope.SENSITIVE or sensitive_reason is not None
    if is_sensitive:
        reasons.append(sensitive_reason or "sensitive_scope")

    if kind is MemoryKind.BOUNDARY and track is SourceTrack.EXPLICIT_USER and not is_sensitive:
        normalized_importance = max(normalized_importance, 0.9)
        reasons.append("explicit_boundary_priority")

    explicit_user = track is SourceTrack.EXPLICIT_USER
    if explicit_user and not is_sensitive:
        reasons.append("explicit_user_priority")

    if risk_tier is None:
        computed_risk = _default_risk(
            kind=kind,
            scope=scope,
            track=track,
            confidence=normalized_confidence,
            conflicting=conflicting,
            sensitive=is_sensitive,
        )
    else:
        computed_risk = RiskTier(risk_tier)

    if lifecycle_status is None:
        computed_lifecycle = _default_lifecycle(
            kind=kind,
            track=track,
            confidence=normalized_confidence,
            conflicting=conflicting,
            sensitive=is_sensitive,
            explicit_user=explicit_user,
            superseded_by=superseded_by,
        )
    else:
        computed_lifecycle = LifecycleStatus(lifecycle_status)

    if conflicting and not explicit_user and not is_sensitive:
        reasons.append("conflict_requires_confirmation")
    if normalized_confidence < LOW_CONFIDENCE_THRESHOLD and not explicit_user and not is_sensitive:
        reasons.append("low_confidence_candidate")
    if kind is MemoryKind.INFERENCE:
        reasons.append("inference_not_durable_by_default")
    if kind is MemoryKind.RECENT_STATE:
        reasons.append("recent_state_not_durable_by_default")
    if scope is MemoryScope.RELATIONSHIP and kind is not MemoryKind.BOUNDARY:
        reasons.append("relationship_memory_review")
    if scope is MemoryScope.TEMPORARY:
        reasons.append("temporary_scope_not_durable")
    if kind is MemoryKind.PROJECT_CONTEXT and computed_lifecycle is LifecycleStatus.ACTIVE and expires_at is None:
        reasons.append("project_context_requires_lifecycle_review")

    requires_confirmation = _requires_confirmation(
        lifecycle=computed_lifecycle,
        risk=computed_risk,
        conflicting=conflicting,
        confidence=normalized_confidence,
        explicit_user=explicit_user,
        sensitive=is_sensitive,
    )
    permissions = _default_permissions(
        kind=kind,
        scope=scope,
        lifecycle=computed_lifecycle,
        track=track,
        risk=computed_risk,
        confidence=normalized_confidence,
    )
    return MemoryTaxonomy(
        memory_kind=kind,
        memory_scope=scope,
        lifecycle_status=computed_lifecycle,
        source_track=track,
        risk_tier=computed_risk,
        confidence=normalized_confidence,
        importance=normalized_importance,
        evidence_count=normalized_evidence,
        expires_at=expires_at,
        last_confirmed_at=last_confirmed_at,
        superseded_by=superseded_by,
        recall_permissions=permissions,
        requires_confirmation=requires_confirmation,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _default_risk(
    *,
    kind: MemoryKind,
    scope: MemoryScope,
    track: SourceTrack,
    confidence: float,
    conflicting: bool,
    sensitive: bool,
) -> RiskTier:
    if sensitive:
        return RiskTier.HIGH
    if conflicting or confidence < LOW_CONFIDENCE_THRESHOLD:
        return RiskTier.MEDIUM
    if kind in {MemoryKind.INFERENCE, MemoryKind.RECENT_STATE}:
        return RiskTier.MEDIUM
    if scope in {MemoryScope.RELATIONSHIP, MemoryScope.TEMPORARY} and track is not SourceTrack.EXPLICIT_USER:
        return RiskTier.MEDIUM
    return RiskTier.LOW


def _default_lifecycle(
    *,
    kind: MemoryKind,
    track: SourceTrack,
    confidence: float,
    conflicting: bool,
    sensitive: bool,
    explicit_user: bool,
    superseded_by: str | None,
) -> LifecycleStatus:
    if sensitive:
        return LifecycleStatus.REJECTED
    if superseded_by:
        return LifecycleStatus.SUPERSEDED
    if track is SourceTrack.IMMEDIATE:
        return LifecycleStatus.CANDIDATE
    if kind is MemoryKind.INFERENCE:
        return LifecycleStatus.CANDIDATE
    if conflicting and not explicit_user:
        return LifecycleStatus.CANDIDATE
    if confidence < LOW_CONFIDENCE_THRESHOLD and not explicit_user:
        return LifecycleStatus.CANDIDATE
    return LifecycleStatus.ACTIVE


def _requires_confirmation(
    *,
    lifecycle: LifecycleStatus,
    risk: RiskTier,
    conflicting: bool,
    confidence: float,
    explicit_user: bool,
    sensitive: bool,
) -> bool:
    if sensitive:
        return False
    if explicit_user:
        return False
    return (
        risk is RiskTier.MEDIUM
        or conflicting
        or confidence < LOW_CONFIDENCE_THRESHOLD
        or lifecycle is LifecycleStatus.CANDIDATE
    )


def _default_permissions(
    *,
    kind: MemoryKind,
    scope: MemoryScope,
    lifecycle: LifecycleStatus,
    track: SourceTrack,
    risk: RiskTier,
    confidence: float,
) -> RecallPermissions:
    if lifecycle in {LifecycleStatus.FORGOTTEN, LifecycleStatus.REJECTED}:
        return RecallPermissions()
    if scope is MemoryScope.SENSITIVE or risk is RiskTier.HIGH:
        return RecallPermissions()

    active = lifecycle is LifecycleStatus.ACTIVE
    immediate_candidate = lifecycle is LifecycleStatus.CANDIDATE and track is SourceTrack.IMMEDIATE
    usable = active or immediate_candidate
    low_confidence = confidence < LOW_CONFIDENCE_THRESHOLD
    high_confidence = confidence >= PROACTIVE_CONFIDENCE_THRESHOLD

    can_style = usable and kind in {
        MemoryKind.PREFERENCE,
        MemoryKind.RECENT_STATE,
        MemoryKind.BOUNDARY,
        MemoryKind.INFERENCE,
    }
    can_answer = usable and kind is not MemoryKind.INFERENCE
    can_suggest = usable and not low_confidence and kind in {
        MemoryKind.PREFERENCE,
        MemoryKind.RECENT_STATE,
        MemoryKind.BOUNDARY,
        MemoryKind.PROJECT_CONTEXT,
    }
    can_proactive = (
        usable
        and high_confidence
        and risk is RiskTier.LOW
        and kind in {MemoryKind.FACT, MemoryKind.PREFERENCE, MemoryKind.BOUNDARY, MemoryKind.PROJECT_CONTEXT}
        and scope not in {MemoryScope.RELATIONSHIP, MemoryScope.TEMPORARY}
    )
    can_persist = (
        active
        and track is not SourceTrack.IMMEDIATE
        and scope not in {MemoryScope.SENSITIVE, MemoryScope.TEMPORARY}
        and kind not in {MemoryKind.RECENT_STATE, MemoryKind.INFERENCE}
        and risk is not RiskTier.HIGH
    )
    if scope is MemoryScope.RELATIONSHIP and kind is not MemoryKind.BOUNDARY:
        can_persist = False
    return RecallPermissions(
        can_style_response=can_style,
        can_answer_context=can_answer,
        can_proactively_mention=can_proactive,
        can_suggest_action=can_suggest,
        can_persist=can_persist,
    )


def _sensitive_reason(value: str) -> str | None:
    decision = evaluate_memory_content(value)
    return None if decision.allowed else decision.reason or "sensitive_content"


def fact_lifecycle_status(status: MemoryFactStatus) -> LifecycleStatus:
    """Map a persisted fact status onto the lifecycle taxonomy."""
    if status is MemoryFactStatus.QUARANTINED:
        return LifecycleStatus.CANDIDATE
    if status in {MemoryFactStatus.WRONG, MemoryFactStatus.SENSITIVE_BLOCKED}:
        return LifecycleStatus.REJECTED
    return LifecycleStatus(status.value)

