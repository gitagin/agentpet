from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.models.enums import MemoryFactStatus
from app.services.memory_hygiene_suggestions import MemoryHygieneSuggestionService
from app.services.memory_policy import evaluate_memory_content
from app.services.memory_profile_projection import MemoryProfileProjectionItem, MemoryProfileProjectionService
from app.storage.database import open_database_connection
from app.utils.time import utc_now_iso


GraphNodeType = str
GraphNodeStatus = str
GraphRiskTier = str
GraphEdgeType = str

REDACTED_MEMORY_LABEL = "有一条已隐藏的记忆"
REDACTED_CLEANUP_LABEL = "有一条需要安全处理的记忆"
REDACTION_NOTE = "敏感内容、原始证据、授权信息和本机路径不会显示。"


@dataclass(frozen=True, slots=True)
class MemoryGraphProjectionNode:
    id: str
    type: GraphNodeType
    label: str
    subtitle: str
    status: GraphNodeStatus
    risk_tier: GraphRiskTier
    size: float
    confidence_label: str
    source_label: str
    updated_at: str
    available_actions: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MemoryGraphProjectionEdge:
    id: str
    from_node: str
    to_node: str
    type: GraphEdgeType
    strength: float


@dataclass(frozen=True, slots=True)
class MemoryGraphProjectionCluster:
    id: str
    label: str
    node_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MemoryGraphProjectionSummary:
    total_nodes: int
    pending_count: int
    cleanup_count: int
    hidden_count: int


@dataclass(frozen=True, slots=True)
class MemoryGraphProjection:
    generated_at: str
    nodes: list[MemoryGraphProjectionNode]
    edges: list[MemoryGraphProjectionEdge]
    clusters: list[MemoryGraphProjectionCluster]
    summary: MemoryGraphProjectionSummary
    redaction_note: str = REDACTION_NOTE


@dataclass(frozen=True, slots=True)
class _NodeDraft:
    node: MemoryGraphProjectionNode
    cluster_key: str
    topics: tuple[str, ...] = ()


class MemoryGraphProjectionService:
    """Build a user-facing, read-only memory graph projection from existing safe memory surfaces."""

    def __init__(self, db: str | Path | sqlite3.Connection) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def build(self, *, max_nodes: int = 40) -> MemoryGraphProjection:
        node_limit = max(5, min(max_nodes, 80))
        generated_at = utc_now_iso()
        center = MemoryGraphProjectionNode(
            id=_opaque_id("mg", "node", "user", "center"),
            type="user",
            label="我",
            subtitle="记忆中心",
            status="active",
            risk_tier="low",
            size=1.45,
            confidence_label="由你掌控",
            source_label="本机记忆图谱",
            updated_at=generated_at,
            available_actions=[],
        )
        drafts: list[_NodeDraft] = [_NodeDraft(center, "overview")]

        projection = MemoryProfileProjectionService(self.conn).build(limit=node_limit)
        drafts.extend(self._profile_node_drafts(projection, remaining=node_limit - len(drafts)))
        if len(drafts) < node_limit:
            drafts.extend(self._diary_node_drafts(remaining=node_limit - len(drafts)))

        cleanup_count = 0
        if len(drafts) < node_limit:
            cleanup_drafts, cleanup_count = self._cleanup_node_drafts(remaining=node_limit - len(drafts))
            drafts.extend(cleanup_drafts)
        else:
            cleanup_count = self._cleanup_count()

        drafts = _dedupe_nodes(drafts)[:node_limit]
        nodes = [draft.node for draft in drafts]
        node_ids = {node.id for node in nodes}
        clusters = _clusters_for(drafts, existing_node_ids=node_ids)
        edges = _edges_for(drafts, center_id=center.id, existing_node_ids=node_ids)
        summary = MemoryGraphProjectionSummary(
            total_nodes=len(nodes),
            pending_count=sum(1 for node in nodes if node.status == "pending"),
            cleanup_count=cleanup_count,
            hidden_count=sum(1 for node in nodes if node.status == "hidden" or node.risk_tier == "hidden"),
        )
        return MemoryGraphProjection(
            generated_at=generated_at,
            nodes=nodes,
            edges=edges,
            clusters=clusters,
            summary=summary,
        )

    def _profile_node_drafts(self, projection, *, remaining: int) -> list[_NodeDraft]:
        if remaining <= 0:
            return []
        drafts: list[_NodeDraft] = []
        for group, node_type, subtitle, cluster_key in (
            ("preferences", "preference", "偏好", "preferences"),
            ("boundaries", "boundary", "边界", "boundaries"),
            ("projects", "project", "项目", "projects"),
            ("needs_confirmation", "pending", "待确认", "pending"),
            ("recent_state", "episode", "近期状态", "episodes"),
            ("conflicts", "archived", "已更新", "archived"),
            ("filtered", "archived", "已归档", "archived"),
        ):
            items = getattr(projection, group)
            for item in items:
                if len(drafts) >= remaining:
                    return drafts
                drafts.append(_profile_item_draft(item, group=group, node_type=node_type, subtitle=subtitle, cluster_key=cluster_key))
        return drafts

    def _diary_node_drafts(self, *, remaining: int) -> list[_NodeDraft]:
        if remaining <= 0 or not _table_exists(self.conn, "diary_memory_objects"):
            return []
        rows = self.conn.execute(
            """
            SELECT id, type, summary, topic, emotion, people_json, keywords_json,
                   importance, confidence, status, occurred_at, updated_at
            FROM diary_memory_objects
            ORDER BY
                CASE status WHEN 'active' THEN 0 WHEN 'candidate' THEN 1 WHEN 'quarantined' THEN 2 ELSE 3 END,
                importance DESC,
                confidence DESC,
                occurred_at DESC
            LIMIT ?
            """,
            (max(1, min(remaining * 2, 80)),),
        ).fetchall()
        drafts: list[_NodeDraft] = []
        for row in rows:
            if len(drafts) >= remaining:
                break
            drafts.append(_diary_row_draft(row))
        return drafts

    def _cleanup_node_drafts(self, *, remaining: int) -> tuple[list[_NodeDraft], int]:
        suggestions = self._cleanup_suggestions(limit=max(remaining, 1))
        drafts: list[_NodeDraft] = []
        for suggestion in suggestions[:remaining]:
            hidden = suggestion.type == "sensitive_candidate" or _unsafe_text(f"{suggestion.title}\n{suggestion.summary}")
            label = REDACTED_CLEANUP_LABEL if hidden else _cleanup_label(suggestion.type)
            drafts.append(
                _NodeDraft(
                    MemoryGraphProjectionNode(
                        id=_opaque_id("mg", "node", "cleanup", suggestion.id),
                        type="cleanup",
                        label=label,
                        subtitle="需要整理",
                        status="hidden" if hidden else "pending",
                        risk_tier="hidden" if hidden else "low",
                        size=0.72,
                        confidence_label="建议检查",
                        source_label="来自本机整理建议",
                        updated_at=utc_now_iso(),
                        available_actions=[],
                    ),
                    "cleanup",
                    ("cleanup",),
                )
            )
        return drafts, len(suggestions)

    def _cleanup_count(self) -> int:
        return len(self._cleanup_suggestions(limit=200))

    def _cleanup_suggestions(self, *, limit: int):
        if not _table_exists(self.conn, "memory_candidates") or not _table_exists(self.conn, "memory_graph_facts"):
            return ()
        service = MemoryHygieneSuggestionService(self.conn)
        try:
            return service.preview(limit=limit)
        finally:
            service.close()


def _cleanup_label(suggestion_type: str) -> str:
    labels = {
        "stale_recent_state": "临时状态已过期",
        "low_confidence_stale": "有一条不确定的记忆待整理",
        "sensitive_candidate": REDACTED_CLEANUP_LABEL,
    }
    return labels.get(suggestion_type, "有一条记忆需要整理")


def _profile_item_draft(
    item: MemoryProfileProjectionItem,
    *,
    group: str,
    node_type: GraphNodeType,
    subtitle: str,
    cluster_key: str,
) -> _NodeDraft:
    hidden = _profile_item_hidden(item)
    status = _profile_status(item, group=group, hidden=hidden)
    safe_label = REDACTED_MEMORY_LABEL if hidden else _safe_text(item.summary, fallback="一条记忆")
    if group in {"filtered", "conflicts"} and not hidden:
        safe_label = "一条已归档或已更新的记忆"
    node = MemoryGraphProjectionNode(
        id=_opaque_id("mg", "node", "profile", group, item.id, item.updated_at),
        type="pending" if status == "pending" else node_type,
        label=safe_label,
        subtitle=subtitle,
        status=status,
        risk_tier="hidden" if hidden else "low",
        size=_node_size(item.importance, item.confidence, multiplier=0.7 if group == "recent_state" else 1.0),
        confidence_label=_confidence_label(item.confidence, hidden=hidden),
        source_label="细节已隐藏" if hidden else _safe_text(item.source_label, fallback="来自本机整理"),
        updated_at=item.updated_at,
        available_actions=[],
    )
    return _NodeDraft(node, "hidden" if hidden else cluster_key, _topic_tokens(item.summary, item.category, subtitle))


def _diary_row_draft(row: sqlite3.Row) -> _NodeDraft:
    raw_type = str(row["type"] or "event")
    node_type, subtitle, cluster_key = _diary_type_labels(raw_type)
    status = _status_from_raw(str(row["status"]))
    hidden = status == "hidden" or _unsafe_text(
        "\n".join(
            (
                str(row["summary"] or ""),
                str(row["topic"] or ""),
                str(row["emotion"] or ""),
                " ".join(_json_list(row["people_json"])),
                " ".join(_json_list(row["keywords_json"])),
            )
        )
    )
    label = REDACTED_MEMORY_LABEL if hidden else _safe_text(str(row["summary"]), fallback="一段聊天回忆")
    if hidden:
        status = "hidden"
        cluster_key = "hidden"
    node = MemoryGraphProjectionNode(
        id=_opaque_id("mg", "node", "diary", row["id"], row["updated_at"]),
        type=node_type,
        label=label,
        subtitle=subtitle,
        status=status,
        risk_tier="hidden" if hidden else "low",
        size=_node_size(float(row["importance"] or 0), float(row["confidence"] or 0), multiplier=0.85),
        confidence_label=_confidence_label(float(row["confidence"] or 0), hidden=hidden),
        source_label="细节已隐藏" if hidden else "来自聊天日记",
        updated_at=str(row["updated_at"]),
        available_actions=[],
    )
    topics = _topic_tokens(str(row["topic"] or ""), str(row["emotion"] or ""), *list(_json_list(row["keywords_json"]))[:3])
    return _NodeDraft(node, cluster_key, topics)


def _profile_item_hidden(item: MemoryProfileProjectionItem) -> bool:
    return "敏感" in item.risk_label or "隐藏" in item.risk_label or _unsafe_text(item.summary)


def _profile_status(item: MemoryProfileProjectionItem, *, group: str, hidden: bool) -> GraphNodeStatus:
    if hidden:
        return "hidden"
    if group == "needs_confirmation" or "待确认" in item.status_label or "待复核" in item.status_label:
        return "pending"
    if group in {"filtered", "conflicts"} or "归档" in item.status_label or "过滤" in item.status_label or "替换" in item.status_label:
        return "archived"
    return "active"


def _status_from_raw(value: str) -> GraphNodeStatus:
    if value in {MemoryFactStatus.CANDIDATE.value, MemoryFactStatus.QUARANTINED.value, MemoryFactStatus.STALE.value}:
        return "pending"
    if value in {
        MemoryFactStatus.ARCHIVED.value,
        MemoryFactStatus.FORGOTTEN.value,
        MemoryFactStatus.REJECTED.value,
        MemoryFactStatus.SUPERSEDED.value,
        MemoryFactStatus.WRONG.value,
    }:
        return "archived"
    if value == MemoryFactStatus.SENSITIVE_BLOCKED.value:
        return "hidden"
    return "active"


def _diary_type_labels(value: str) -> tuple[GraphNodeType, str, str]:
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized == "qa":
        return "qa", "问答", "episodes"
    if normalized == "mood":
        return "mood", "心情", "episodes"
    if normalized == "project_update":
        return "project", "项目进展", "projects"
    return "episode", "情景", "episodes"


def _clusters_for(drafts: list[_NodeDraft], *, existing_node_ids: set[str]) -> list[MemoryGraphProjectionCluster]:
    labels = {
        "overview": "我",
        "preferences": "偏好",
        "boundaries": "边界",
        "projects": "项目",
        "episodes": "情景",
        "sources": "资料",
        "pending": "待确认",
        "cleanup": "需要整理",
        "archived": "已归档",
        "hidden": "已隐藏",
    }
    grouped: dict[str, list[str]] = {}
    for draft in drafts:
        if draft.node.id not in existing_node_ids:
            continue
        grouped.setdefault(draft.cluster_key, []).append(draft.node.id)
    return [
        MemoryGraphProjectionCluster(
            id=f"cluster_{key}",
            label=labels.get(key, "记忆"),
            node_ids=list(dict.fromkeys(node_ids)),
        )
        for key, node_ids in grouped.items()
        if node_ids
    ]


def _edges_for(drafts: list[_NodeDraft], *, center_id: str, existing_node_ids: set[str]) -> list[MemoryGraphProjectionEdge]:
    edges: list[MemoryGraphProjectionEdge] = []
    for draft in drafts:
        if draft.node.id == center_id or draft.node.id not in existing_node_ids:
            continue
        edges.append(_edge(center_id, draft.node.id, "related_to", 0.7 if draft.node.status == "active" else 0.52))

    by_topic: dict[str, list[str]] = {}
    for draft in drafts:
        if draft.node.id not in existing_node_ids:
            continue
        for topic in draft.topics:
            by_topic.setdefault(topic, []).append(draft.node.id)
    for node_ids in by_topic.values():
        unique_ids = list(dict.fromkeys(node_ids))
        if len(unique_ids) < 2:
            continue
        anchor = unique_ids[0]
        for related_id in unique_ids[1:4]:
            if anchor != related_id:
                edges.append(_edge(anchor, related_id, "related_to", 0.42))
    return _dedupe_edges(edges)


def _edge(from_node: str, to_node: str, edge_type: GraphEdgeType, strength: float) -> MemoryGraphProjectionEdge:
    return MemoryGraphProjectionEdge(
        id=_opaque_id("mge", "edge", from_node, to_node, edge_type),
        from_node=from_node,
        to_node=to_node,
        type=edge_type,
        strength=max(0.1, min(1.0, strength)),
    )


def _dedupe_nodes(drafts: list[_NodeDraft]) -> list[_NodeDraft]:
    seen: set[str] = set()
    deduped: list[_NodeDraft] = []
    for draft in drafts:
        if draft.node.id in seen:
            continue
        seen.add(draft.node.id)
        deduped.append(draft)
    return deduped


def _dedupe_edges(edges: list[MemoryGraphProjectionEdge]) -> list[MemoryGraphProjectionEdge]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[MemoryGraphProjectionEdge] = []
    for edge in edges:
        key = (edge.from_node, edge.to_node, edge.type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped


def _node_size(importance: float, confidence: float, *, multiplier: float = 1.0) -> float:
    value = 0.72 + (max(0.0, min(1.0, importance)) * 0.38) + (max(0.0, min(1.0, confidence)) * 0.2)
    return round(max(0.5, min(1.45, value * multiplier)), 2)


def _confidence_label(value: float, *, hidden: bool = False) -> str:
    if hidden:
        return "细节已隐藏"
    if value >= 0.8:
        return "较确定"
    if value >= 0.65:
        return "基本确定"
    return "需要确认"


def _safe_text(value: str, *, fallback: str) -> str:
    text = str(value or "").strip()
    if not text or _unsafe_text(text):
        return fallback
    return _compact(text, 48)


def _unsafe_text(value: str) -> bool:
    text = str(value or "")
    if not text:
        return False
    if not evaluate_memory_content(text).allowed:
        return True
    return any(
        pattern.search(text)
        for pattern in (
            re.compile(r"\b[A-Za-z]:[\\/][^\s]+"),
            re.compile(r"\\\\[^\s\\]+\\[^\s]+"),
            re.compile(r"\bAuthorization\b", re.IGNORECASE),
            re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
        )
    )


def _compact(value: str, limit: int) -> str:
    text = " ".join(value.strip().split())
    if len(text) <= limit:
        return text
    return f"{text[: max(1, limit - 1)].rstrip()}…"


def _topic_tokens(*values: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for value in values:
        text = str(value or "").strip().casefold()
        if not text or _unsafe_text(text):
            continue
        for part in re.split(r"[\s,，。；;:/\\|]+", text):
            part = part.strip()
            if len(part) >= 2 and part not in {"记忆", "情景", "项目", "偏好", "边界"}:
                tokens.append(part[:32])
    return tuple(list(dict.fromkeys(tokens))[:4])


def _json_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed if isinstance(item, str) and item.strip())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _opaque_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(("memory_graph_projection_v1", *[str(part) for part in parts]))
    return f"{prefix}_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
