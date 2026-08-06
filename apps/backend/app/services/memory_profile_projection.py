from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.services.memory_policy import evaluate_memory_content
from app.services.memory_taxonomy import LOW_CONFIDENCE_THRESHOLD, LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack
from app.storage.database import open_database_connection
from app.utils.time import utc_now_iso


REDACTED_SUMMARY = "这条记忆包含敏感或不适合展示的细节，已隐藏。"
FILTERED_SUMMARY = "这条记忆已被过滤或撤回，细节不再展示。"
SUPERSEDED_SUMMARY = "这条旧记忆已被更新替换，不再作为当前画像使用。"


@dataclass(frozen=True, slots=True)
class MemoryProfileProjectionItem:
    id: str
    category: str
    summary: str
    confidence: float
    importance: float
    status_label: str
    risk_label: str
    source_label: str
    updated_at: str
    permissions_summary: str
    can_revoke: bool = False
    available_actions: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MemoryProfileProjectionAction:
    action: str
    label: str
    requires_confirmation: bool = True


@dataclass(frozen=True, slots=True)
class MemoryProfileProjectionSourceSummary:
    label: str
    description: str
    evidence_count_label: str | None = None
    last_seen_label: str | None = None
    safety_note: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryProfileProjectionDetail:
    id: str
    summary: str
    category_label: str
    status_label: str
    confidence_label: str
    importance_label: str
    source_label: str
    permissions: list[str]
    safety_note: str | None
    updated_at: str
    source_summary: MemoryProfileProjectionSourceSummary | None = None
    available_actions: list[MemoryProfileProjectionAction] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MemoryProfileProjectionTarget:
    item: MemoryProfileProjectionItem
    target_type: str
    target_id: str | None
    group: str
    raw_status: str
    raw_kind: str
    sensitive: bool


@dataclass(frozen=True, slots=True)
class MemoryProfileProjection:
    generated_at: str
    identity: list[MemoryProfileProjectionItem] = field(default_factory=list)
    preferences: list[MemoryProfileProjectionItem] = field(default_factory=list)
    boundaries: list[MemoryProfileProjectionItem] = field(default_factory=list)
    projects: list[MemoryProfileProjectionItem] = field(default_factory=list)
    relationships: list[MemoryProfileProjectionItem] = field(default_factory=list)
    recent_state: list[MemoryProfileProjectionItem] = field(default_factory=list)
    conflicts: list[MemoryProfileProjectionItem] = field(default_factory=list)
    needs_confirmation: list[MemoryProfileProjectionItem] = field(default_factory=list)
    filtered: list[MemoryProfileProjectionItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _SourceStats:
    count: int
    source_values: tuple[str, ...]
    last_seen_at: str | None


class MemoryProfileProjectionService:
    """Build a read-only, user-facing profile projection from existing memory tables."""

    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def build(self, *, limit: int = 120) -> MemoryProfileProjection:
        groups = _empty_groups()
        item_limit = max(1, min(limit, 300))
        for row in self._candidate_rows(item_limit):
            group, item = _candidate_item(row)
            groups[group].append(item)
        for row in self._fact_rows(item_limit):
            group, item = _fact_item(row)
            groups[group].append(item)
        for row in self._continuity_rows(item_limit):
            group, item = _continuity_item(row)
            groups[group].append(item)
        for items in groups.values():
            items.sort(key=lambda item: (item.updated_at, item.importance, item.confidence), reverse=True)
            del items[item_limit:]
        return MemoryProfileProjection(generated_at=utc_now_iso(), **groups)

    def get_detail(self, item_id: str) -> MemoryProfileProjectionDetail | None:
        target = self.resolve_target(item_id)
        if target is None:
            return None
        return _target_detail(target, source_summary=self._source_summary(target))

    def resolve_target(self, item_id: str) -> MemoryProfileProjectionTarget | None:
        for row in self._candidate_rows(300):
            group, item = _candidate_item(row)
            if item.id == item_id:
                return _candidate_target(row, group, item)
        for row in self._fact_rows(300):
            group, item = _fact_item(row)
            if item.id == item_id:
                return _fact_target(row, group, item)
        for row in self._continuity_rows(300):
            group, item = _continuity_item(row)
            if item.id == item_id:
                return _continuity_target(row, group, item)
        return None

    def _candidate_rows(self, limit: int) -> list[sqlite3.Row]:
        if not _table_exists(self.conn, "memory_candidates"):
            return []
        return self.conn.execute(
            """
            SELECT
                id, memory_kind, memory_scope, summary, source_track, risk_tier,
                confidence, importance, evidence_count, status, expires_at,
                superseded_by, fact_id, metadata_json, updated_at
            FROM memory_candidates
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def _fact_rows(self, limit: int) -> list[sqlite3.Row]:
        if not _table_exists(self.conn, "memory_graph_facts"):
            return []
        return self.conn.execute(
            """
            SELECT
                id, category, subject, predicate, object, status, confidence,
                source_type, support_count, conflicts_with, memory_type,
                entity_type, expires_at, metadata_json, importance, updated_at
            FROM memory_graph_facts
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def _continuity_rows(self, limit: int) -> list[sqlite3.Row]:
        if not _table_exists(self.conn, "continuity_state"):
            return []
        return self.conn.execute(
            """
            SELECT state_key, value, confidence, updated_at
            FROM continuity_state
            ORDER BY updated_at DESC, state_key ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def _source_summary(self, target: MemoryProfileProjectionTarget) -> MemoryProfileProjectionSourceSummary | None:
        if target.sensitive or target.group == "filtered":
            return MemoryProfileProjectionSourceSummary(
                label="来源细节已隐藏",
                description="为了保护隐私和安全，这条记忆的来源细节没有展示。",
                safety_note="来源细节已隐藏。",
            )
        if target.target_id is None:
            return None

        stats = self._source_stats(target)
        if stats.count <= 0:
            return None

        return MemoryProfileProjectionSourceSummary(
            label=target.item.source_label,
            description=_source_summary_description(
                source_label=target.item.source_label,
                source_values=stats.source_values,
                count=stats.count,
            ),
            evidence_count_label=f"有 {stats.count} 条安全来源",
            last_seen_label=_last_seen_label(stats.last_seen_at or target.item.updated_at),
            safety_note="来源内容已做安全摘要，未显示原文。",
        )

    def _source_stats(self, target: MemoryProfileProjectionTarget) -> _SourceStats:
        if target.target_type == "candidate":
            return self._candidate_source_stats(target.target_id or "")
        if target.target_type == "fact":
            return self._fact_source_stats(target.target_id or "")
        return _SourceStats(count=0, source_values=(), last_seen_at=None)

    def _candidate_source_stats(self, candidate_id: str) -> _SourceStats:
        row = self.conn.execute(
            """
            SELECT evidence_count, source_track, updated_at
            FROM memory_candidates
            WHERE id = ?
            """,
            (candidate_id,),
        ).fetchone()
        if row is None:
            return _SourceStats(count=0, source_values=(), last_seen_at=None)

        evidence = _evidence_stats(self.conn, "candidate_id", candidate_id)
        evidence_count = int(evidence["count"]) if evidence else 0
        fallback_count = int(row["evidence_count"] or 0)
        source_values = _split_source_values(evidence["source_values"] if evidence else None)
        if not source_values:
            source_values = (str(row["source_track"] or ""),)
        return _SourceStats(
            count=evidence_count if evidence_count > 0 else fallback_count,
            source_values=source_values,
            last_seen_at=str((evidence["last_seen_at"] if evidence else None) or row["updated_at"] or ""),
        )

    def _fact_source_stats(self, fact_id: str) -> _SourceStats:
        row = self.conn.execute(
            """
            SELECT support_count, source_type, updated_at
            FROM memory_graph_facts
            WHERE id = ?
            """,
            (fact_id,),
        ).fetchone()
        if row is None:
            return _SourceStats(count=0, source_values=(), last_seen_at=None)

        evidence = _evidence_stats(self.conn, "fact_id", fact_id)
        evidence_count = int(evidence["count"]) if evidence else 0
        fallback_count = int(row["support_count"] or 0)
        source_values = _split_source_values(evidence["source_values"] if evidence else None)
        if not source_values:
            source_values = (str(row["source_type"] or ""),)
        return _SourceStats(
            count=evidence_count if evidence_count > 0 else fallback_count,
            source_values=source_values,
            last_seen_at=str((evidence["last_seen_at"] if evidence else None) or row["updated_at"] or ""),
        )


def _empty_groups() -> dict[str, list[MemoryProfileProjectionItem]]:
    return {
        "identity": [],
        "preferences": [],
        "boundaries": [],
        "projects": [],
        "relationships": [],
        "recent_state": [],
        "conflicts": [],
        "needs_confirmation": [],
        "filtered": [],
    }


def _candidate_item(row: sqlite3.Row) -> tuple[str, MemoryProfileProjectionItem]:
    status = str(row["status"])
    kind = str(row["memory_kind"])
    scope = str(row["memory_scope"])
    risk = str(row["risk_tier"])
    confidence = _clamp(row["confidence"])
    importance = _clamp(row["importance"])
    base_group = _profile_group(kind=kind, scope=scope, category=kind, entity_type=None, expires_at=row["expires_at"])
    is_sensitive = _is_sensitive(
        summary=str(row["summary"]),
        risk_tier=risk,
        scope=scope,
        status=status,
    )
    group = _projection_group(
        base_group=base_group,
        status=status,
        confidence=confidence,
        risk_tier=risk,
        sensitive=is_sensitive,
        superseded_by=row["superseded_by"],
        conflicts_with=None,
    )
    summary = _display_summary(str(row["summary"]), group=group, status=status, sensitive=is_sensitive)
    can_revoke = group not in {"filtered"} and status in {"active", "candidate", "stale"}
    item = MemoryProfileProjectionItem(
        id=_profile_id("candidate", row["id"]),
        category=base_group,
        summary=summary,
        confidence=confidence,
        importance=importance,
        status_label=_status_label(status, group=group),
        risk_label=_risk_label(risk, is_sensitive),
        source_label=_source_label(str(row["source_track"]), support_count=int(row["evidence_count"] or 0)),
        updated_at=str(row["updated_at"]),
        permissions_summary=_permissions_summary(
            group=group,
            status=status,
            kind=kind,
            risk_tier=risk,
            confidence=confidence,
            sensitive=is_sensitive,
        ),
        can_revoke=can_revoke,
        available_actions=_action_labels(_available_action_keys(target_type="candidate", group=group, status=status, kind=kind, sensitive=is_sensitive)),
    )
    return group, item


def _fact_item(row: sqlite3.Row) -> tuple[str, MemoryProfileProjectionItem]:
    status = str(row["status"])
    metadata = _json_object(row["metadata_json"])
    risk = str(metadata.get("risk_tier") or RiskTier.LOW.value)
    kind = str(row["memory_type"] or row["category"] or MemoryKind.FACT.value)
    confidence = _clamp(row["confidence"])
    importance = _clamp(row["importance"])
    superseded_by = _optional_text(metadata.get("superseded_by"))
    summary = _fact_summary(row)
    base_group = _profile_group(
        kind=kind,
        scope=str(metadata.get("memory_scope") or ""),
        category=str(row["category"]),
        entity_type=str(row["entity_type"] or ""),
        expires_at=row["expires_at"],
    )
    is_sensitive = _is_sensitive(summary=summary, risk_tier=risk, scope=str(metadata.get("memory_scope") or ""), status=status)
    group = _projection_group(
        base_group=base_group,
        status=status,
        confidence=confidence,
        risk_tier=risk,
        sensitive=is_sensitive,
        superseded_by=superseded_by,
        conflicts_with=row["conflicts_with"],
    )
    display = _display_summary(summary, group=group, status=status, sensitive=is_sensitive)
    can_revoke = group not in {"filtered"} and status in {"active", "candidate", "quarantined", "stale"}
    item = MemoryProfileProjectionItem(
        id=_profile_id("graph", row["id"]),
        category=base_group,
        summary=display,
        confidence=confidence,
        importance=importance,
        status_label=_status_label(status, group=group),
        risk_label=_risk_label(risk, is_sensitive),
        source_label=_source_label(str(row["source_type"]), support_count=int(row["support_count"] or 0)),
        updated_at=str(row["updated_at"]),
        permissions_summary=_permissions_summary(
            group=group,
            status=status,
            kind=kind,
            risk_tier=risk,
            confidence=confidence,
            sensitive=is_sensitive,
        ),
        can_revoke=can_revoke,
        available_actions=_action_labels(_available_action_keys(target_type="fact", group=group, status=status, kind=kind, sensitive=is_sensitive)),
    )
    return group, item


def _continuity_item(row: sqlite3.Row) -> tuple[str, MemoryProfileProjectionItem]:
    state_key = str(row["state_key"])
    confidence = _clamp(row["confidence"])
    base_group = _continuity_group(state_key)
    status = LifecycleStatus.ACTIVE.value if confidence >= LOW_CONFIDENCE_THRESHOLD else LifecycleStatus.CANDIDATE.value
    sensitive = _is_sensitive(summary=str(row["value"]), risk_tier=RiskTier.LOW.value, scope="", status=status)
    group = _projection_group(
        base_group=base_group,
        status=status,
        confidence=confidence,
        risk_tier=RiskTier.LOW.value,
        sensitive=sensitive,
        superseded_by=None,
        conflicts_with=None,
    )
    if base_group == "recent_state" and group not in {"filtered", "needs_confirmation"}:
        group = "recent_state"
    item = MemoryProfileProjectionItem(
        id=_profile_id("continuity", state_key),
        category=base_group,
        summary=_display_summary(str(row["value"]), group=group, status=status, sensitive=sensitive),
        confidence=confidence,
        importance=0.5,
        status_label="近期状态" if base_group == "recent_state" and group != "needs_confirmation" else _status_label(status, group=group),
        risk_label=_risk_label(RiskTier.LOW.value, sensitive),
        source_label="来自陪伴状态整理",
        updated_at=str(row["updated_at"]),
        permissions_summary="只作为近期状态" if base_group == "recent_state" else _permissions_summary(
            group=group,
            status=status,
            kind=MemoryKind.FACT.value,
            risk_tier=RiskTier.LOW.value,
            confidence=confidence,
            sensitive=sensitive,
        ),
        can_revoke=False,
        available_actions=[],
    )
    return group, item


def _candidate_target(row: sqlite3.Row, group: str, item: MemoryProfileProjectionItem) -> MemoryProfileProjectionTarget:
    status = str(row["status"])
    kind = str(row["memory_kind"])
    sensitive = _is_sensitive(
        summary=str(row["summary"]),
        risk_tier=str(row["risk_tier"]),
        scope=str(row["memory_scope"]),
        status=status,
    )
    return MemoryProfileProjectionTarget(
        item=item,
        target_type="candidate",
        target_id=str(row["id"]),
        group=group,
        raw_status=status,
        raw_kind=kind,
        sensitive=sensitive,
    )


def _fact_target(row: sqlite3.Row, group: str, item: MemoryProfileProjectionItem) -> MemoryProfileProjectionTarget:
    status = str(row["status"])
    metadata = _json_object(row["metadata_json"])
    kind = str(row["memory_type"] or row["category"] or MemoryKind.FACT.value)
    risk = str(metadata.get("risk_tier") or RiskTier.LOW.value)
    sensitive = _is_sensitive(
        summary=_fact_summary(row),
        risk_tier=risk,
        scope=str(metadata.get("memory_scope") or ""),
        status=status,
    )
    return MemoryProfileProjectionTarget(
        item=item,
        target_type="fact",
        target_id=str(row["id"]),
        group=group,
        raw_status=status,
        raw_kind=kind,
        sensitive=sensitive,
    )


def _continuity_target(row: sqlite3.Row, group: str, item: MemoryProfileProjectionItem) -> MemoryProfileProjectionTarget:
    status = LifecycleStatus.ACTIVE.value if _clamp(row["confidence"]) >= LOW_CONFIDENCE_THRESHOLD else LifecycleStatus.CANDIDATE.value
    return MemoryProfileProjectionTarget(
        item=item,
        target_type="continuity",
        target_id=None,
        group=group,
        raw_status=status,
        raw_kind=MemoryKind.RECENT_STATE.value,
        sensitive=_is_sensitive(summary=str(row["value"]), risk_tier=RiskTier.LOW.value, scope="", status=status),
    )


def _target_detail(
    target: MemoryProfileProjectionTarget,
    *,
    source_summary: MemoryProfileProjectionSourceSummary | None,
) -> MemoryProfileProjectionDetail:
    action_keys = _available_action_keys(
        target_type=target.target_type,
        group=target.group,
        status=target.raw_status,
        kind=target.raw_kind,
        sensitive=target.sensitive,
    )
    return MemoryProfileProjectionDetail(
        id=target.item.id,
        summary=target.item.summary,
        category_label=_category_label(target.item.category, target.group),
        status_label=target.item.status_label,
        confidence_label=_confidence_label(target.item.confidence),
        importance_label=_importance_label(target.item.importance),
        source_label=target.item.source_label,
        permissions=_permission_labels(
            group=target.group,
            status=target.raw_status,
            kind=target.raw_kind,
            sensitive=target.sensitive,
        ),
        safety_note=_safety_note(target),
        updated_at=target.item.updated_at,
        source_summary=source_summary,
        available_actions=[
            MemoryProfileProjectionAction(action=action, label=_action_label(action), requires_confirmation=True)
            for action in action_keys
        ],
    )


def _profile_id(target_type: str, raw_id: object) -> str:
    material = f"profile-projection:{target_type}:{raw_id}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"profile_{digest}"


def _available_action_keys(*, target_type: str, group: str, status: str, kind: str, sensitive: bool) -> list[str]:
    if target_type not in {"candidate", "fact"}:
        return []
    if sensitive or group == "filtered" or status in {"forgotten", "rejected", "wrong", "sensitive_blocked", "archived", "superseded"}:
        return []
    actions: list[str] = []
    if status in {"candidate", "quarantined", "stale"} or group == "needs_confirmation":
        actions.append("keep")
    if status in {"active", "candidate", "quarantined", "stale"}:
        actions.extend(["forget", "mark_inaccurate"])
    if group != "recent_state" and kind != MemoryKind.RECENT_STATE.value and status in {"active", "stale"}:
        actions.append("make_temporary")
    if status == "active" and group not in {"recent_state", "needs_confirmation"}:
        actions.append("mark_stale")
    return list(dict.fromkeys(actions))


def _action_labels(actions: list[str]) -> list[str]:
    return [_action_label(action) for action in actions]


def _action_label(action: str) -> str:
    labels = {
        "forget": "撤回",
        "mark_inaccurate": "标记不准确",
        "keep": "确认记住",
        "make_temporary": "暂时保留",
        "mark_stale": "标记过期",
    }
    return labels.get(action, "管理记忆")


def _category_label(category: str, group: str) -> str:
    labels = {
        "identity": "身份",
        "preferences": "偏好",
        "boundaries": "边界",
        "projects": "项目",
        "relationships": "关系",
        "recent_state": "近期状态",
        "needs_confirmation": "待确认",
        "filtered": "已过滤",
        "conflicts": "已替换",
    }
    return labels.get(group) or labels.get(category, "记忆")


def _confidence_label(value: float) -> str:
    if value >= 0.8:
        return "可信度较高"
    if value >= LOW_CONFIDENCE_THRESHOLD:
        return "可信度中等"
    return "还需要确认"


def _importance_label(value: float) -> str:
    if value >= 0.75:
        return "比较重要"
    if value >= 0.45:
        return "普通重要"
    return "轻量参考"


def _permission_labels(*, group: str, status: str, kind: str, sensitive: bool) -> list[str]:
    if sensitive or group == "filtered":
        return ["不会用于普通回答", "细节已隐藏"]
    if group == "needs_confirmation" or status in {"candidate", "quarantined", "stale"}:
        return ["需要你确认后再作为稳定画像使用"]
    if group == "recent_state" or kind == MemoryKind.RECENT_STATE.value:
        return ["只作为近期状态参考", "不会当作长期事实"]
    if kind == MemoryKind.INFERENCE.value:
        return ["只影响语气", "不会主动提及"]
    if group == "relationships":
        return ["可用于回答", "不会主动提及"]
    return ["可用于回答"]


def _safety_note(target: MemoryProfileProjectionTarget) -> str | None:
    if target.sensitive or target.group == "filtered":
        return "这条记忆包含敏感或不适合展示的细节，细节已隐藏。"
    if target.group == "conflicts":
        return "这条记忆已经被更新或替换，不会作为当前画像使用。"
    return None


def _profile_group(
    *,
    kind: str,
    scope: str,
    category: str,
    entity_type: str | None,
    expires_at: object,
) -> str:
    normalized = {kind, scope, category, entity_type or ""}
    if kind == MemoryKind.RECENT_STATE.value or scope == MemoryScope.TEMPORARY.value or expires_at:
        return "recent_state"
    if kind == MemoryKind.PREFERENCE.value or category in {"preference", "preferences"}:
        return "preferences"
    if kind == MemoryKind.BOUNDARY.value or category in {"boundary", "boundaries"}:
        return "boundaries"
    if kind == MemoryKind.PROJECT_CONTEXT.value or scope == MemoryScope.PROJECT.value or category in {"project", "project_context"}:
        return "projects"
    if scope == MemoryScope.RELATIONSHIP.value or "relationship" in normalized or "relationships" in normalized:
        return "relationships"
    if normalized & {"identity", "profile", "user_identity", "person", "name"}:
        return "identity"
    return "identity"


def _projection_group(
    *,
    base_group: str,
    status: str,
    confidence: float,
    risk_tier: str,
    sensitive: bool,
    superseded_by: object,
    conflicts_with: object,
) -> str:
    if sensitive or risk_tier == RiskTier.HIGH.value or status in {"forgotten", "rejected", "wrong", "sensitive_blocked", "archived"}:
        return "filtered"
    if status == "superseded" or superseded_by or conflicts_with:
        return "conflicts"
    if status in {"candidate", "quarantined", "stale"} or confidence < LOW_CONFIDENCE_THRESHOLD:
        return "needs_confirmation"
    return base_group


def _display_summary(raw: str, *, group: str, status: str, sensitive: bool) -> str:
    if status in {"forgotten", "rejected", "wrong", "archived"}:
        return FILTERED_SUMMARY
    if status == "superseded":
        return SUPERSEDED_SUMMARY
    if sensitive or _unsafe_text(raw):
        return REDACTED_SUMMARY
    return _compact(raw, 220)


def _fact_summary(row: sqlite3.Row) -> str:
    parts = [str(row["subject"]).strip(), str(row["predicate"]).strip(), str(row["object"]).strip()]
    return " ".join(part for part in parts if part)


def _is_sensitive(*, summary: str, risk_tier: str, scope: str, status: str) -> bool:
    if risk_tier == RiskTier.HIGH.value or scope == MemoryScope.SENSITIVE.value or status == "sensitive_blocked":
        return True
    return not evaluate_memory_content(summary).allowed or _looks_like_secret_or_path(summary)


def _unsafe_text(value: str) -> bool:
    return not evaluate_memory_content(value).allowed or _looks_like_secret_or_path(value)


def _looks_like_secret_or_path(value: str) -> bool:
    return any(
        pattern.search(value)
        for pattern in (
            re.compile(r"\b[A-Za-z]:[\\/][^\s]+"),
            re.compile(r"\\\\[^\s\\]+\\[^\s]+"),
            re.compile(r"\bAuthorization\b", re.IGNORECASE),
            re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
        )
    )


def _status_label(status: str, *, group: str) -> str:
    if group == "needs_confirmation":
        return "待确认"
    if group == "conflicts":
        return "已替换" if status == "superseded" else "有冲突"
    labels = {
        "active": "已确认",
        "candidate": "待确认",
        "quarantined": "待确认",
        "stale": "待复核",
        "archived": "已归档",
        "forgotten": "已忘记",
        "rejected": "已过滤",
        "wrong": "已过滤",
        "superseded": "已替换",
        "sensitive_blocked": "已隐藏细节",
    }
    return labels.get(status, "待复核")


def _risk_label(risk_tier: str, sensitive: bool) -> str:
    if sensitive or risk_tier == RiskTier.HIGH.value:
        return "敏感，已隐藏细节"
    if risk_tier == RiskTier.MEDIUM.value:
        return "需要谨慎"
    return "普通"


def _source_label(source: str, *, support_count: int) -> str:
    if support_count > 1:
        return "来自多次聊天"
    labels = {
        SourceTrack.EXPLICIT_USER.value: "来自用户明确要求",
        SourceTrack.SLOW_CONSOLIDATION.value: "来自聊天后的整理",
        SourceTrack.MODEL_EXTRACTED.value: "来自聊天后的整理",
        SourceTrack.DIARY.value: "来自日记整理",
        SourceTrack.CONTINUITY.value: "来自陪伴状态整理",
        SourceTrack.IMMEDIATE.value: "来自一次聊天",
        "user_message": "来自一次聊天",
        "chat_message": "来自一次聊天",
        "chat": "来自一次聊天",
        "user_feedback": "来自用户明确要求",
    }
    return labels.get(source, "来自整理记录")


def _source_summary_description(*, source_label: str, source_values: tuple[str, ...], count: int) -> str:
    buckets = {_source_bucket(value) for value in source_values}
    if count > 1 and ("chat" in buckets or "explicit" in buckets or "system" in buckets):
        return "这条记忆由几次相关对话整理而来。"
    if "explicit" in buckets or "用户明确要求" in source_label:
        return "这条记忆来自你明确表达过的要求或确认。"
    if "diary" in buckets or "日记" in source_label:
        return "这条记忆来自日记整理后的安全摘要。"
    if "chat" in buckets or "一次聊天" in source_label:
        return "这条记忆来自一次聊天后的整理。"
    if "system" in buckets or "整理" in source_label:
        return "这条记忆来自聊天后的系统整理。"
    return "这条记忆来自本地记忆整理记录。"


def _source_bucket(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {SourceTrack.EXPLICIT_USER.value, "user_message", "user_feedback", "explicit_user"}:
        return "explicit"
    if normalized in {SourceTrack.IMMEDIATE.value, "chat", "chat_message", "conversation"}:
        return "chat"
    if normalized in {SourceTrack.DIARY.value, "diary", "diary_object", "daily_chat"}:
        return "diary"
    if normalized in {SourceTrack.SLOW_CONSOLIDATION.value, SourceTrack.MODEL_EXTRACTED.value, "system", "system_summary"}:
        return "system"
    if normalized == SourceTrack.CONTINUITY.value:
        return "continuity"
    return "local"


def _last_seen_label(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return f"最近更新于 {text[:10]}"


def _split_source_values(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    values = []
    for part in str(value).split(","):
        text = part.strip()
        if text:
            values.append(text)
    return tuple(values)


def _evidence_stats(conn: sqlite3.Connection, column: str, target_id: str) -> sqlite3.Row | None:
    if column not in {"candidate_id", "fact_id"} or not _table_exists(conn, "memory_evidence"):
        return None
    return conn.execute(
        f"""
        SELECT
            COUNT(*) AS count,
            MAX(created_at) AS last_seen_at,
            GROUP_CONCAT(DISTINCT source_type) AS source_values
        FROM memory_evidence
        WHERE {column} = ?
        """,
        (target_id,),
    ).fetchone()


def _permissions_summary(
    *,
    group: str,
    status: str,
    kind: str,
    risk_tier: str,
    confidence: float,
    sensitive: bool,
) -> str:
    if sensitive or risk_tier == RiskTier.HIGH.value or group == "filtered":
        return "不会用于普通回答"
    if group == "needs_confirmation" or status in {"candidate", "quarantined", "stale"} or confidence < LOW_CONFIDENCE_THRESHOLD:
        return "需要确认后使用"
    if group == "recent_state" or kind == MemoryKind.RECENT_STATE.value:
        return "只作为近期状态"
    if kind == MemoryKind.INFERENCE.value:
        return "只影响语气"
    if group == "relationships":
        return "可用于回答，不会主动提及"
    return "可用于回答"


def _continuity_group(state_key: str) -> str:
    if state_key in {"identity_traits"}:
        return "identity"
    if state_key in {"relationship_summary"}:
        return "relationships"
    if state_key in {"unresolved_threads"}:
        return "projects"
    return "recent_state"


def _json_object(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _compact(value: str, limit: int) -> str:
    compacted = " ".join(str(value).split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(0, limit - 1)].rstrip() + "…"


def _clamp(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(0.0, min(1.0, number))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    return row is not None
