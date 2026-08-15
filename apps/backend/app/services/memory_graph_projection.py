from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.models.enums import MemoryFactStatus
from app.services.memory_entity_graph import (
    RELATION_TYPES,
    _fact_row_recallable as _authority_fact_recallable,
    _relation_row_recallable as _authority_relation_recallable,
)
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
    confidence: float = 0.0
    evidence_count: int = 0


@dataclass(frozen=True, slots=True)
class MemoryGraphProjectionEdge:
    id: str
    from_node: str
    to_node: str
    type: GraphEdgeType
    strength: float
    status: str = "active"
    updated_at: str | None = None
    evidence_count: int = 0
    risk: GraphRiskTier = "low"
    available_actions: list[str] = field(default_factory=list)


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
    # These are authority references, never exposed in the public projection.
    # Edges may only be created when both endpoints resolve through these refs.
    entity_id: str | None = None
    fact_id: str | None = None


class MemoryGraphProjectionService:
    """Build a user-facing, read-only memory graph projection from existing safe memory surfaces."""

    def __init__(self, db: str | Path | sqlite3.Connection, *, vault_id: str | None = None) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.vault_id = vault_id

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
        drafts: list[_NodeDraft] = [_NodeDraft(center, "overview", entity_id=self._self_entity_id())]

        profile_service = MemoryProfileProjectionService(self.conn)
        projection = profile_service.build(limit=node_limit)
        drafts.extend(
            self._profile_node_drafts(
                projection,
                profile_service=profile_service,
                remaining=node_limit - len(drafts),
            )
        )
        if len(drafts) < node_limit:
            drafts.extend(self._diary_node_drafts(remaining=node_limit - len(drafts)))

        # Claims are first-class Wiki graph material.  The previous projection
        # only surfaced profile/diary summaries and relation endpoints, which
        # made an evidenced standalone claim disappear from the workspace.
        if len(drafts) < node_limit:
            drafts.extend(self._claim_node_drafts(remaining=node_limit - len(drafts)))

        # Relation endpoints are authoritative SQLite entities/facts. Add only
        # safe endpoints that participate in an evidenced active relation.
        relation_rows = self._controlled_relation_rows()
        if relation_rows and len(drafts) < node_limit:
            drafts.extend(
                self._relation_endpoint_drafts(
                    relation_rows,
                    existing=drafts,
                    remaining=node_limit - len(drafts),
                )
            )

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
        edges = _edges_for(
            drafts,
            center_id=center.id,
            existing_node_ids=node_ids,
            relation_rows=relation_rows,
        )
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

    def _profile_node_drafts(
        self,
        projection,
        *,
        profile_service: MemoryProfileProjectionService,
        remaining: int,
    ) -> list[_NodeDraft]:
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
                target = profile_service.resolve_target(item.id)
                entity_id: str | None = None
                fact_id: str | None = None
                if target is not None and target.target_id:
                    if target.target_type == "fact":
                        fact_id = target.target_id
                        if _table_has_columns(self.conn, "memory_graph_facts", "subject_entity_id"):
                            row = self.conn.execute(
                                "SELECT subject_entity_id FROM memory_graph_facts WHERE id = ?",
                                (fact_id,),
                            ).fetchone()
                            if row is not None:
                                entity_id = row["subject_entity_id"]
                    elif target.target_type == "candidate":
                        if _table_has_columns(self.conn, "memory_candidates", "fact_id"):
                            row = self.conn.execute(
                                "SELECT fact_id FROM memory_candidates WHERE id = ?",
                                (target.target_id,),
                            ).fetchone()
                            if row is not None:
                                fact_id = row["fact_id"]
                drafts.append(
                    _profile_item_draft(
                        item,
                        group=group,
                        node_type=node_type,
                        subtitle=subtitle,
                        cluster_key=cluster_key,
                        entity_id=entity_id,
                        fact_id=fact_id,
                    )
                )
        return drafts

    def _self_entity_id(self) -> str | None:
        if not _table_has_columns(self.conn, "memory_entities", "id", "entity_type"):
            return None
        row = self.conn.execute(
            "SELECT id FROM memory_entities WHERE entity_type = 'self' AND status = 'active' LIMIT 1"
        ).fetchone()
        return str(row["id"]) if row is not None else None

    def _controlled_relation_rows(self) -> list[sqlite3.Row]:
        required = (
            "id",
            "statement_kind",
            "relation_type",
            "status",
            "confidence",
            "subject_entity_id",
            "subject_fact_id",
            "object_entity_id",
            "object_fact_id",
        )
        if not _table_has_columns(self.conn, "memory_graph_facts", *required):
            return []
        if not _table_exists(self.conn, "memory_evidence"):
            return []
        placeholders = ", ".join("?" for _ in RELATION_TYPES)
        rows = self.conn.execute(
            f"""
            SELECT f.*
                   ,(SELECT COUNT(*) FROM memory_evidence e WHERE e.fact_id = f.id) AS evidence_count
            FROM memory_graph_facts f
            WHERE f.statement_kind = 'relation'
              AND f.status = 'active'
              AND f.relation_type IN ({placeholders})
              AND f.confidence >= 0.65
              AND (
                    (f.subject_entity_id IS NOT NULL AND f.subject_fact_id IS NULL)
                    OR (f.subject_entity_id IS NULL AND f.subject_fact_id IS NOT NULL)
                  )
              AND (
                    (f.object_entity_id IS NOT NULL AND f.object_fact_id IS NULL)
                    OR (f.object_entity_id IS NULL AND f.object_fact_id IS NOT NULL)
                  )
              AND EXISTS (
                    SELECT 1 FROM memory_evidence e
                    WHERE e.fact_id = f.id
                  )
            ORDER BY f.updated_at DESC, f.id
            LIMIT 1000
            """,
            tuple(sorted(RELATION_TYPES)),
        ).fetchall()
        return [
            row
            for row in rows
            if _authority_relation_recallable(self.conn, row, vault_id=self.vault_id)
        ]

    def _relation_endpoint_drafts(
        self,
        relation_rows: list[sqlite3.Row],
        *,
        existing: list[_NodeDraft],
        remaining: int,
    ) -> list[_NodeDraft]:
        if remaining <= 0:
            return []
        known_entities = {draft.entity_id for draft in existing if draft.entity_id}
        known_facts = {draft.fact_id for draft in existing if draft.fact_id}
        drafts: list[_NodeDraft] = []
        endpoint_pairs: list[tuple[str, str]] = []
        for row in relation_rows:
            for endpoint in (row["subject_entity_id"], row["object_entity_id"]):
                if isinstance(endpoint, str) and endpoint and endpoint not in known_entities:
                    endpoint_pairs.append(("entity", endpoint))
            for endpoint in (row["subject_fact_id"], row["object_fact_id"]):
                if isinstance(endpoint, str) and endpoint and endpoint not in known_facts:
                    endpoint_pairs.append(("fact", endpoint))
        seen: set[tuple[str, str]] = set()
        for kind, endpoint_id in endpoint_pairs:
            if len(drafts) >= remaining or (kind, endpoint_id) in seen:
                continue
            seen.add((kind, endpoint_id))
            if kind == "entity":
                if not _table_exists(self.conn, "memory_entities"):
                    continue
                row = self.conn.execute(
                    "SELECT * FROM memory_entities WHERE id = ? AND status = 'active'",
                    (endpoint_id,),
                ).fetchone()
                if row is None or str(row["risk_tier"] or "low") == "high":
                    continue
                label = _safe_text(str(row["canonical_name"]), fallback="一个实体")
                node = MemoryGraphProjectionNode(
                    id=_opaque_id("mg", "node", "entity", endpoint_id),
                    type=_entity_node_type(str(row["entity_type"])),
                    label=label,
                    subtitle=_entity_subtitle(str(row["entity_type"])),
                    status="active",
                    risk_tier="low",
                    size=0.95,
                    confidence_label=_confidence_label(float(row["confidence"] or 0.0)),
                    source_label="来自受控实体",
                    updated_at=str(row["updated_at"]),
                    available_actions=[],
                )
                drafts.append(_NodeDraft(node, "entities", entity_id=endpoint_id))
                known_entities.add(endpoint_id)
            else:
                row = self.conn.execute(
                    "SELECT * FROM memory_graph_facts WHERE id = ? AND status = 'active'",
                    (endpoint_id,),
                ).fetchone()
                if (
                    row is None
                    or not _authority_fact_recallable(self.conn, endpoint_id, vault_id=self.vault_id)
                    or _unsafe_text(f"{row['subject']} {row['predicate']} {row['object']}")
                ):
                    continue
                label = _safe_text(
                    f"{row['subject']} {row['predicate']} {row['object']}",
                    fallback="一条已确认事实",
                )
                node = MemoryGraphProjectionNode(
                    id=_opaque_id("mg", "node", "fact", endpoint_id),
                    type="source",
                    label=label,
                    subtitle="受控事实",
                    status="active",
                    risk_tier="low",
                    size=0.9,
                    confidence_label=_confidence_label(float(row["confidence"] or 0.0)),
                    source_label="来自有证据事实",
                    updated_at=str(row["updated_at"]),
                    available_actions=[],
                )
                drafts.append(_NodeDraft(node, "facts", fact_id=endpoint_id))
                known_facts.add(endpoint_id)
        return drafts

    def _claim_node_drafts(self, *, remaining: int) -> list[_NodeDraft]:
        if remaining <= 0 or not _table_exists(self.conn, "memory_graph_facts"):
            return []
        rows = self.conn.execute(
            """
            SELECT f.*
            FROM memory_graph_facts f
            WHERE f.statement_kind = 'claim'
              AND f.status = 'active'
              AND f.confidence >= 0.65
              AND NOT EXISTS (
                    SELECT 1
                    FROM memory_graph_facts conflict
                    WHERE conflict.statement_kind = 'relation'
                      AND conflict.relation_type = 'contradicts'
                      AND conflict.status = 'active'
                      AND (conflict.subject_fact_id = f.id OR conflict.object_fact_id = f.id)
              )
              AND (f.expires_at IS NULL OR f.expires_at > ?)
              AND EXISTS (SELECT 1 FROM memory_evidence e WHERE e.fact_id = f.id)
            ORDER BY f.importance DESC, f.updated_at DESC, f.id
            LIMIT ?
            """,
            (utc_now_iso(), max(1, min(remaining * 2, 120))),
        ).fetchall()
        drafts: list[_NodeDraft] = []
        for row in rows:
            if len(drafts) >= remaining:
                break
            if not _authority_fact_recallable(self.conn, str(row["id"]), vault_id=self.vault_id):
                continue
            fact_id = str(row["id"])
            if any(draft.fact_id == fact_id for draft in drafts):
                continue
            label = _safe_text(
                f"{row['subject']} {row['predicate']} {row['object']}",
                fallback="一条已验证事实",
            )
            node = MemoryGraphProjectionNode(
                id=_opaque_id("mg", "node", "fact", fact_id),
                type=_entity_node_type(str(row["entity_type"] or "source")),
                label=label,
                subtitle="有证据的事实",
                status="active",
                risk_tier="low",
                size=_node_size(float(row["importance"] or 0.0), float(row["confidence"] or 0.0)),
                confidence_label=_confidence_label(float(row["confidence"] or 0.0)),
                source_label="来自受控事实",
                updated_at=str(row["updated_at"]),
                available_actions=["correct", "forget", "archive"],
            )
            drafts.append(_NodeDraft(node, "facts", fact_id=fact_id, entity_id=row["subject_entity_id"] or None))
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
    entity_id: str | None = None,
    fact_id: str | None = None,
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
    return _NodeDraft(
        node,
        "hidden" if hidden else cluster_key,
        entity_id=entity_id,
        fact_id=fact_id,
    )


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
    return _NodeDraft(node, cluster_key)


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


def _edges_for(
    drafts: list[_NodeDraft],
    *,
    center_id: str,
    existing_node_ids: set[str],
    relation_rows: list[sqlite3.Row] | None = None,
) -> list[MemoryGraphProjectionEdge]:
    """Create visual membership and evidenced SQLite relation edges.

    The old implementation grouped summaries/topics and invented ``related_to``
    edges.  A shared word is not a relationship, so this function deliberately
    has no text/token input.  Semantic edges can only come from a persisted,
    typed relation row whose evidence and lifecycle gate passed in
    ``_controlled_relation_rows``.
    """
    edges: list[MemoryGraphProjectionEdge] = []
    for draft in drafts:
        if draft.node.id == center_id or draft.node.id not in existing_node_ids:
            continue
        # This is layout membership, not a semantic relation.  Keeping a
        # distinct edge type makes the provenance boundary visible to clients.
        edges.append(_edge(center_id, draft.node.id, "belongs_to", 0.7 if draft.node.status == "active" else 0.52))

    by_entity = {
        draft.entity_id: draft.node.id
        for draft in drafts
        if draft.entity_id
        and draft.node.id in existing_node_ids
        and draft.node.status == "active"
        and draft.node.risk_tier != "hidden"
    }
    by_fact = {
        draft.fact_id: draft.node.id
        for draft in drafts
        if draft.fact_id
        and draft.node.id in existing_node_ids
        and draft.node.status == "active"
        and draft.node.risk_tier != "hidden"
    }
    for row in relation_rows or ():
        relation_type = str(row["relation_type"] or "").casefold()
        if relation_type not in RELATION_TYPES:
            continue
        from_node = _endpoint_node(row, side="subject", by_entity=by_entity, by_fact=by_fact)
        to_node = _endpoint_node(row, side="object", by_entity=by_entity, by_fact=by_fact)
        if from_node is None or to_node is None or from_node == to_node:
            continue
        strength = float(row["confidence"] or 0.0)
        status = str(row["status"] or "active")
        edges.append(
            _edge(
                from_node,
                to_node,
                relation_type,
                strength,
                edge_key=row["id"],
                status=status,
                updated_at=str(row["updated_at"]) if row["updated_at"] else None,
                evidence_count=int(row["evidence_count"] or 0),
                risk=_row_risk(row),
                available_actions=_statement_actions(status),
            )
        )
    return _dedupe_edges(edges)


def _edge(
    from_node: str,
    to_node: str,
    edge_type: GraphEdgeType,
    strength: float,
    *,
    edge_key: object | None = None,
    status: str = "active",
    updated_at: str | None = None,
    evidence_count: int = 0,
    risk: GraphRiskTier = "low",
    available_actions: list[str] | None = None,
) -> MemoryGraphProjectionEdge:
    return MemoryGraphProjectionEdge(
        id=_opaque_id("mge", "edge", from_node, to_node, edge_type, edge_key or ""),
        from_node=from_node,
        to_node=to_node,
        type=edge_type,
        strength=max(0.1, min(1.0, strength)),
        status=status,
        updated_at=updated_at,
        evidence_count=max(0, evidence_count),
        risk=risk,
        available_actions=list(available_actions or []),
    )


def _statement_actions(status: str) -> list[str]:
    if status in {"candidate", "quarantined"}:
        return ["confirm", "correct", "forget", "archive"]
    if status == "active":
        return ["correct", "forget", "archive"]
    return ["forget"]


def _row_risk(row: sqlite3.Row) -> GraphRiskTier:
    metadata = _json_object(row["metadata_json"] if "metadata_json" in row.keys() else None)
    value = str(metadata.get("risk_tier") or metadata.get("risk") or "low").casefold()
    return value if value in {"low", "medium", "high", "hidden"} else "low"


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


def _json_object(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_has_columns(conn: sqlite3.Connection, table: str, *columns: str) -> bool:
    if not _table_exists(conn, table):
        return False
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    available = {str(row[1]) for row in rows}
    return all(column in available for column in columns)


def _endpoint_node(
    row: sqlite3.Row,
    *,
    side: str,
    by_entity: dict[str, str],
    by_fact: dict[str, str],
) -> str | None:
    entity_id = row[f"{side}_entity_id"]
    fact_id = row[f"{side}_fact_id"]
    if isinstance(entity_id, str) and entity_id:
        return by_entity.get(entity_id)
    if isinstance(fact_id, str) and fact_id:
        return by_fact.get(fact_id)
    return None


def _entity_node_type(entity_type: str) -> GraphNodeType:
    return {
        "self": "user",
        "preference": "preference",
        "boundary": "boundary",
        "project": "project",
        "goal": "project",
        "event": "episode",
        "person": "source",
        "concept": "source",
        "source": "source",
        "wiki_page": "source",
        "decision": "project",
    }.get(entity_type, "source")


def _entity_subtitle(entity_type: str) -> str:
    return {
        "self": "自己",
        "person": "人物实体",
        "project": "项目实体",
        "preference": "偏好实体",
        "boundary": "边界实体",
        "goal": "目标实体",
        "event": "事件实体",
        "concept": "概念实体",
        "source": "来源实体",
        "wiki_page": "Wiki 页面实体",
        "decision": "决策实体",
    }.get(entity_type, "受控实体")


def _opaque_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(("memory_graph_projection_v1", *[str(part) for part in parts]))
    return f"{prefix}_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
