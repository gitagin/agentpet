"""Weekly memory review query and read-model orchestration."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.models.memory import (
    MemoryReviewAction,
    MemoryReviewCategory,
    MemoryReviewItemResponse,
    MemoryReviewResponse,
    MemoryReviewSummaryResponse,
)
from app.models.enums import MemoryFactStatus
from app.services.memory_policy import evaluate_memory_content


class MemoryReviewQueries:
    """Read-side queries backing the weekly memory review."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def recent_candidates(self, *, cutoff: str, limit: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT *
            FROM memory_candidates
            WHERE created_at >= ? OR updated_at >= ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (cutoff, cutoff, limit),
        ).fetchall()

    def recent_facts(self, *, cutoff: str, limit: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT *
            FROM memory_graph_facts
            WHERE created_at >= ? OR updated_at >= ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (cutoff, cutoff, limit),
        ).fetchall()


class MemoryReviewService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._queries = MemoryReviewQueries(conn)

    def build(
        self,
        *,
        days: int,
        limit: int,
        now: datetime | None = None,
    ) -> MemoryReviewResponse:
        generated_at = now or datetime.now(timezone.utc)
        window_days = max(1, min(days, 31))
        item_limit = max(1, min(limit, 100))
        cutoff = (generated_at - timedelta(days=window_days)).isoformat()
        items = [
            *[
                memory_review_candidate_item(row)
                for row in self._queries.recent_candidates(cutoff=cutoff, limit=item_limit)
            ],
            *[
                memory_review_fact_item(row)
                for row in self._queries.recent_facts(cutoff=cutoff, limit=item_limit)
            ],
        ]
        items.sort(key=lambda item: (item.updated_at, item.review_id), reverse=True)
        items = items[:item_limit]
        summary_counts = {"kept": 0, "temporary": 0, "ignored": 0}
        for item in items:
            summary_counts[item.category] += 1
        return MemoryReviewResponse(
            generated_at=generated_at.isoformat(),
            window_days=window_days,
            summary=MemoryReviewSummaryResponse(**summary_counts),
            items=items,
        )


def memory_review_candidate_item(row: sqlite3.Row) -> MemoryReviewItemResponse:
    category = memory_review_category(
        status=str(row["status"]),
        memory_kind=str(row["memory_kind"]),
        memory_scope=str(row["memory_scope"]),
        expires_at=row["expires_at"],
        target_type="candidate",
    )
    memory_kind = str(row["memory_kind"])
    review_status = str(row["status"])
    return MemoryReviewItemResponse(
        review_id=f"candidate:{row['id']}",
        target_type="candidate",
        target_id=str(row["id"]),
        category=category,
        summary=safe_review_summary(str(row["summary"])),
        memory_kind=memory_kind,
        memory_scope=str(row["memory_scope"]),
        lifecycle_status=review_status,
        risk_tier=str(row["risk_tier"]),
        confidence=float(row["confidence"]),
        importance=float(row["importance"]),
        evidence_count=int(row["evidence_count"]),
        expires_at=row["expires_at"],
        updated_at=str(row["updated_at"]),
        source=str(row["source_track"]),
        allowed_actions=memory_review_allowed_actions(
            target_type="candidate",
            review_status=review_status,
            memory_kind=memory_kind,
        ),
    )


def memory_review_fact_item(row: sqlite3.Row) -> MemoryReviewItemResponse:
    memory_kind = row["memory_type"] or row["category"]
    lifecycle_status = graph_lifecycle_status(str(row["status"])) or str(row["status"])
    category = memory_review_category(
        status=lifecycle_status,
        memory_kind=str(memory_kind or ""),
        memory_scope=None,
        expires_at=row["expires_at"],
        target_type="fact",
    )
    return MemoryReviewItemResponse(
        review_id=f"fact:{row['id']}",
        target_type="fact",
        target_id=str(row["id"]),
        category=category,
        summary=safe_review_summary(f"{row['subject']} {row['predicate']} {row['object']}"),
        memory_kind=str(memory_kind) if memory_kind else None,
        memory_scope=None,
        lifecycle_status=lifecycle_status,
        risk_tier=None,
        confidence=float(row["confidence"]),
        importance=float(row["importance"]),
        evidence_count=int(row["support_count"]),
        expires_at=row["expires_at"],
        updated_at=str(row["updated_at"]),
        source=str(row["source_type"]),
        allowed_actions=memory_review_allowed_actions(
            target_type="fact",
            review_status=lifecycle_status,
            memory_kind=str(memory_kind or ""),
        ),
    )


def graph_lifecycle_status(fact_status: str) -> str | None:
    if fact_status == MemoryFactStatus.QUARANTINED.value:
        return "candidate"
    if fact_status in {MemoryFactStatus.WRONG.value, MemoryFactStatus.SENSITIVE_BLOCKED.value}:
        return "rejected"
    try:
        return MemoryFactStatus(fact_status).value
    except ValueError:
        return None


def memory_review_category(
    *,
    status: str,
    memory_kind: str,
    memory_scope: str | None,
    expires_at: str | None,
    target_type: str,
) -> MemoryReviewCategory:
    if expires_at or memory_kind == "recent_state" or memory_scope == "temporary":
        return "temporary"
    if status in {"candidate", "quarantined", "rejected", "wrong", "sensitive_blocked", "forgotten"}:
        return "ignored"
    if target_type == "candidate" and status == "stale":
        return "ignored"
    return "kept"


def memory_review_allowed_actions(
    *,
    target_type: str,
    review_status: str,
    memory_kind: str,
) -> list[MemoryReviewAction]:
    actions: list[MemoryReviewAction] = ["keep", "edit", "forget", "only_this_week"]
    if target_type == "candidate" and review_status in {"candidate", "quarantined"}:
        actions.append("forget")
    if memory_kind == "project_context":
        actions.append("mark_completed")
    return list(dict.fromkeys(actions))


def safe_review_summary(value: str) -> str:
    return value if evaluate_memory_content(value).allowed else "[redacted sensitive content]"
