from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.services.memory_policy import evaluate_memory_content
from app.services.memory_taxonomy import LOW_CONFIDENCE_THRESHOLD, MemoryKind, MemoryScope, RiskTier
from app.storage.database import open_database_connection
from app.utils.time import utc_now_iso

from app.utils.coerce import clamp_unit_interval
from app.utils.sqlite import json_object, table_exists


REDACTED_DETAIL = "这条内容包含敏感或不适合展示的细节，我没有展示原文。"


@dataclass(frozen=True, slots=True)
class MemoryReceiptItem:
    id: str
    kind: str
    title: str
    detail: str
    safety_note: str | None = None
    action_label: str | None = None
    related_memory_id: str | None = None
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class MemoryReceipt:
    generated_at: str
    items: list[MemoryReceiptItem] = field(default_factory=list)


class MemoryReceiptService:
    """Build read-only, user-facing memory receipts from reliable run-linked tables."""

    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def build(self, *, agent_run_id: str | None = None, limit: int = 50) -> MemoryReceipt:
        capped = max(1, min(limit, 100))
        items: list[MemoryReceiptItem] = []
        if agent_run_id:
            items.extend(self._candidate_receipts(agent_run_id, capped))
            items.extend(self._lifecycle_receipts(agent_run_id, capped))
            items.extend(self._action_receipts(agent_run_id, capped))
            items.extend(self._activation_receipts(agent_run_id))
            items.extend(self._retrieval_report_receipts(agent_run_id))
        else:
            items.extend(self._recent_action_receipts(capped))

        deduped = _dedupe(items)
        deduped.sort(key=lambda item: item.created_at, reverse=True)
        return MemoryReceipt(generated_at=utc_now_iso(), items=deduped[:capped])

    def _candidate_receipts(self, agent_run_id: str, limit: int) -> list[MemoryReceiptItem]:
        if not table_exists(self.conn, "memory_candidates") or not table_exists(self.conn, "memory_evidence"):
            return []
        rows = self.conn.execute(
            """
            SELECT
                c.id, c.memory_kind, c.memory_scope, c.summary, c.risk_tier,
                c.confidence, c.status, c.superseded_by, MAX(e.created_at) AS created_at
            FROM memory_candidates c
            JOIN memory_evidence e ON e.candidate_id = c.id
            WHERE e.agent_run_id = ?
            GROUP BY c.id
            ORDER BY MAX(e.created_at) DESC, c.id DESC
            LIMIT ?
            """,
            (agent_run_id, limit),
        ).fetchall()
        return [_candidate_receipt(row) for row in rows]

    def _lifecycle_receipts(self, agent_run_id: str, limit: int) -> list[MemoryReceiptItem]:
        if not table_exists(self.conn, "memory_lifecycle_events"):
            return []
        rows = self.conn.execute(
            """
            SELECT
                l.id, l.candidate_id, l.fact_id, l.to_status, l.reason, l.created_at,
                c.summary AS candidate_summary, c.memory_kind AS candidate_kind,
                c.memory_scope AS candidate_scope, c.risk_tier AS candidate_risk,
                f.subject AS fact_subject, f.predicate AS fact_predicate,
                f.object AS fact_object, f.memory_type AS fact_kind
            FROM memory_lifecycle_events l
            LEFT JOIN memory_candidates c ON c.id = l.candidate_id
            LEFT JOIN memory_graph_facts f ON f.id = l.fact_id
            WHERE l.source_agent_run_id = ?
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT ?
            """,
            (agent_run_id, limit),
        ).fetchall()
        return [_lifecycle_receipt(row) for row in rows]

    def _action_receipts(self, agent_run_id: str, limit: int) -> list[MemoryReceiptItem]:
        if not table_exists(self.conn, "agent_actions"):
            return []
        rows = self.conn.execute(
            """
            SELECT id, action_type, risk_tier, decision, status, title, summary, metadata_json, created_at
            FROM agent_actions
            WHERE source_agent_run_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (agent_run_id, limit),
        ).fetchall()
        return [item for row in rows if (item := _action_receipt(row)) is not None]

    def _recent_action_receipts(self, limit: int) -> list[MemoryReceiptItem]:
        if not table_exists(self.conn, "agent_actions"):
            return []
        rows = self.conn.execute(
            """
            SELECT id, action_type, risk_tier, decision, status, title, summary, metadata_json, created_at
            FROM agent_actions
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [item for row in rows if (item := _action_receipt(row)) is not None]

    def _activation_receipts(self, agent_run_id: str) -> list[MemoryReceiptItem]:
        if not table_exists(self.conn, "memory_activation_events"):
            return []
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN used_for_answer_context = 1 THEN 1 ELSE 0 END) AS answer_count,
                SUM(CASE WHEN used_for_style = 1 THEN 1 ELSE 0 END) AS style_count,
                SUM(CASE WHEN filtered_reason IS NOT NULL AND filtered_reason != '' THEN 1 ELSE 0 END) AS filtered_count,
                SUM(CASE WHEN filtered_reason = 'prompt_char_budget_exceeded' THEN 1 ELSE 0 END) AS budget_filtered_count,
                MAX(created_at) AS created_at
            FROM memory_activation_events
            WHERE agent_run_id = ?
            """,
            (agent_run_id,),
        ).fetchone()
        if row is None or int(row["total_count"] or 0) == 0:
            return []
        items: list[MemoryReceiptItem] = []
        answer_count = int(row["answer_count"] or 0)
        style_count = int(row["style_count"] or 0)
        filtered_count = int(row["filtered_count"] or 0)
        budget_filtered_count = int(row["budget_filtered_count"] or 0)
        created_at = str(row["created_at"] or utc_now_iso())
        if answer_count > 0 or style_count > 0:
            if answer_count > 0:
                detail = "我参考了已允许用于回答的记忆。"
            else:
                detail = "我只用已允许的记忆调整了表达方式。"
            items.append(
                MemoryReceiptItem(
                    id=_receipt_id("used_for_answer", agent_run_id),
                    kind="used_for_answer",
                    title="这次回答参考了记忆",
                    detail=detail,
                    created_at=created_at,
                )
            )
        if filtered_count > 0:
            policy_filtered_count = filtered_count - budget_filtered_count
            if budget_filtered_count and policy_filtered_count:
                filtered_detail = "它们因为权限、状态、安全或本次回答的上下文容量限制而未被采用。"
            elif budget_filtered_count:
                filtered_detail = "它们因为本次回答可用的上下文容量有限而未被采用。"
            else:
                filtered_detail = "它们因为权限、状态或安全原因被跳过。"
            items.append(
                MemoryReceiptItem(
                    id=_receipt_id("activation_filtered", agent_run_id),
                    kind="filtered",
                    title="有些记忆没有用于回答",
                    detail=filtered_detail,
                    safety_note="敏感细节已隐藏。" if policy_filtered_count else None,
                    created_at=created_at,
                )
            )
        return items

    def _retrieval_report_receipts(self, agent_run_id: str) -> list[MemoryReceiptItem]:
        if not table_exists(self.conn, "companion_retrieval_reports"):
            return []
        row = self.conn.execute(
            """
            SELECT selected_count, created_at
            FROM companion_retrieval_reports
            WHERE agent_run_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (agent_run_id,),
        ).fetchone()
        if row is None or int(row["selected_count"] or 0) <= 0:
            return []
        return [
            MemoryReceiptItem(
                id=_receipt_id("used_for_answer", agent_run_id),
                kind="used_for_answer",
                title="这次回答参考了记忆",
                detail="我参考了已允许用于回答的相关记忆。",
                created_at=str(row["created_at"]),
            )
        ]


def _candidate_receipt(row: sqlite3.Row) -> MemoryReceiptItem:
    status = str(row["status"])
    kind = str(row["memory_kind"])
    risk = str(row["risk_tier"])
    scope = str(row["memory_scope"])
    confidence = clamp_unit_interval(row["confidence"])
    sensitive = _is_sensitive(str(row["summary"]), risk_tier=risk, scope=scope)
    receipt_kind = _receipt_kind(status=status, confidence=confidence, risk_tier=risk, sensitive=sensitive)
    label = _kind_label(kind)
    detail = _safe_detail(str(row["summary"]), sensitive=sensitive)
    title_map = {
        "remembered": f"已记住一条{label}",
        "needs_confirmation": f"有一条{label}需要确认",
        "updated": f"已更新一条{label}",
        "forgotten": f"已忘记一条{label}",
        "filtered": "有一条记忆已过滤",
    }
    if receipt_kind == "remembered":
        detail = f"以后合适时我会参考：{detail}"
    elif receipt_kind == "needs_confirmation":
        detail = f"我先把它放在待确认里：{detail}"
    elif receipt_kind == "filtered":
        detail = REDACTED_DETAIL
    return MemoryReceiptItem(
        id=_receipt_id("memory", row["id"]),
        kind=receipt_kind,
        title=title_map.get(receipt_kind, "记忆状态已更新"),
        detail=detail,
        safety_note="敏感细节已隐藏。" if sensitive else None,
        action_label="查看详情" if receipt_kind in {"remembered", "needs_confirmation"} else None,
        related_memory_id=_memory_reference(row["id"]),
        created_at=str(row["created_at"]),
    )


def _lifecycle_receipt(row: sqlite3.Row) -> MemoryReceiptItem:
    status = str(row["to_status"])
    raw_summary = str(row["candidate_summary"] or _fact_summary(row) or "")
    kind = str(row["candidate_kind"] or row["fact_kind"] or MemoryKind.FACT.value)
    risk = str(row["candidate_risk"] or RiskTier.LOW.value)
    scope = str(row["candidate_scope"] or "")
    sensitive = _is_sensitive(raw_summary, risk_tier=risk, scope=scope)
    receipt_kind = _receipt_kind(status=status, confidence=1.0, risk_tier=risk, sensitive=sensitive)
    label = _kind_label(kind)
    detail = _safe_detail(raw_summary, sensitive=sensitive)
    titles = {
        "remembered": f"已确认一条{label}",
        "updated": f"已更新一条{label}",
        "forgotten": f"已忘记一条{label}",
        "filtered": "有一条记忆已过滤",
        "needs_confirmation": f"有一条{label}需要确认",
    }
    if receipt_kind == "filtered":
        detail = REDACTED_DETAIL
    return MemoryReceiptItem(
        id=_receipt_id("lifecycle", row["id"]),
        kind=receipt_kind,
        title=titles.get(receipt_kind, "记忆状态已更新"),
        detail=detail,
        safety_note="敏感细节已隐藏。" if sensitive else None,
        action_label="查看详情" if receipt_kind in {"remembered", "needs_confirmation", "updated"} else None,
        related_memory_id=_memory_reference(row["candidate_id"] or row["fact_id"]),
        created_at=str(row["created_at"]),
    )


def _action_receipt(row: sqlite3.Row) -> MemoryReceiptItem | None:
    action_type = str(row["action_type"])
    if "memory" not in action_type and "continuity" not in action_type:
        return None
    status = str(row["status"])
    metadata = json_object(row["metadata_json"])
    risk = str(row["risk_tier"])
    if risk == RiskTier.HIGH.value:
        return MemoryReceiptItem(
            id=_receipt_id("action", row["id"]),
            kind="filtered",
            title="有一条记忆已过滤",
            detail="它包含敏感或高风险内容，没有进入普通画像。",
            safety_note="敏感细节已隐藏。",
            created_at=str(row["created_at"]),
        )
    operation = str(metadata.get("operation") or "")
    if operation == "forget" or status == "reverted" or action_type.endswith(".revert"):
        return MemoryReceiptItem(
            id=_receipt_id("action", row["id"]),
            kind="forgotten",
            title="已忘记一条记忆",
            detail="我不会再把它作为当前画像使用。",
            created_at=str(row["created_at"]),
        )
    if status in {"skipped", "failed"} or action_type.endswith(".skip"):
        return MemoryReceiptItem(
            id=_receipt_id("action", row["id"]),
            kind="skipped",
            title="这次没有保存新记忆",
            detail="我没有发现需要沉淀为长期记忆的新信息。",
            created_at=str(row["created_at"]),
        )
    if str(row["decision"]) == "ask" or status == "pending":
        return MemoryReceiptItem(
            id=_receipt_id("action", row["id"]),
            kind="needs_confirmation",
            title="有一条记忆需要确认",
            detail="我会等你确认后再把它作为稳定画像使用。",
            action_label="查看详情",
            created_at=str(row["created_at"]),
        )
    if "consolidation" in action_type:
        output_count = _metadata_int(metadata, "output_count", "candidate_count", "memory_count")
        if output_count == 0:
            return MemoryReceiptItem(
                id=_receipt_id("action", row["id"]),
                kind="skipped",
                title="这次没有保存新记忆",
                detail="我没有发现需要沉淀为长期记忆的新信息。",
                created_at=str(row["created_at"]),
            )
    return MemoryReceiptItem(
        id=_receipt_id("action", row["id"]),
        kind="updated",
        title="记忆状态已更新",
        detail="我已经把这次整理结果同步到记忆状态里。",
        created_at=str(row["created_at"]),
    )


def _receipt_kind(*, status: str, confidence: float, risk_tier: str, sensitive: bool) -> str:
    if sensitive or risk_tier == RiskTier.HIGH.value or status in {"rejected", "wrong", "sensitive_blocked", "archived"}:
        return "filtered"
    if status == "forgotten":
        return "forgotten"
    if status == "superseded":
        return "updated"
    if status in {"candidate", "quarantined", "stale"} or confidence < LOW_CONFIDENCE_THRESHOLD:
        return "needs_confirmation"
    return "remembered"


def _kind_label(kind: str) -> str:
    labels = {
        MemoryKind.PREFERENCE.value: "偏好",
        MemoryKind.BOUNDARY.value: "边界",
        MemoryKind.PROJECT_CONTEXT.value: "项目记忆",
        MemoryKind.RECENT_STATE.value: "近期状态",
        MemoryKind.HISTORICAL.value: "经历",
        MemoryKind.INFERENCE.value: "推断",
        MemoryKind.FACT.value: "事实",
    }
    return labels.get(kind, "记忆")


def _safe_detail(raw: str, *, sensitive: bool) -> str:
    if sensitive or _unsafe_text(raw):
        return REDACTED_DETAIL
    compacted = " ".join(str(raw).split())
    if not compacted:
        return "这条记忆没有可展示的详情。"
    if len(compacted) > 180:
        compacted = compacted[:179].rstrip() + "…"
    return compacted


def _fact_summary(row: sqlite3.Row) -> str:
    parts = [row["fact_subject"], row["fact_predicate"], row["fact_object"]]
    return " ".join(str(part).strip() for part in parts if part)


def _is_sensitive(value: str, *, risk_tier: str, scope: str) -> bool:
    if risk_tier == RiskTier.HIGH.value or scope == MemoryScope.SENSITIVE.value:
        return True
    return _unsafe_text(value)


def _unsafe_text(value: str) -> bool:
    if not evaluate_memory_content(value).allowed:
        return True
    return any(
        pattern.search(value)
        for pattern in (
            re.compile(r"\b[A-Za-z]:[\\/][^\s]+"),
            re.compile(r"\\\\[^\s\\]+\\[^\s]+"),
            re.compile(r"\bAuthorization\b", re.IGNORECASE),
            re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
        )
    )


def _dedupe(items: list[MemoryReceiptItem]) -> list[MemoryReceiptItem]:
    ordered_keys: list[tuple[str, str]] = []
    by_key: dict[tuple[str, str], MemoryReceiptItem] = {}
    for item in items:
        key = _semantic_key(item)
        existing = by_key.get(key)
        if existing is None:
            ordered_keys.append(key)
            by_key[key] = item
        elif item.created_at > existing.created_at:
            by_key[key] = item
    return [by_key[key] for key in ordered_keys]


def _semantic_key(item: MemoryReceiptItem) -> tuple[str, str]:
    if item.kind == "used_for_answer":
        return (item.kind, "memory_context")
    return (item.kind, item.id)


def _receipt_id(*parts: object) -> str:
    return _opaque_id("mr", *parts)


def _memory_reference(value: object) -> str | None:
    if value is None or str(value) == "":
        return None
    return _opaque_id("mem", value)


def _opaque_id(prefix: str, *parts: object) -> str:
    material = "\x1f".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"




def _metadata_int(metadata: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None




