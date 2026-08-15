from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.services.memory_policy import evaluate_memory_content
from app.services.memory_taxonomy import MemoryKind, MemoryScope, RiskTier, SourceTrack
from app.storage.database import open_database_connection


PromptProfilePermissionGroup = Literal["style_profile", "boundary_profile"]

MIN_STABLE_PROFILE_CONFIDENCE = 0.75
DEFAULT_PROFILE_ITEM_LIMIT = 5
DEFAULT_PROFILE_CHAR_BUDGET = 800
_FORBIDDEN_GRAPH_PROFILE_BUCKETS = {
    "relationship",
    "relationships",
    "project",
    "projects",
    "identity",
    "person",
    "name",
    "profile",
    "recent_state",
    "inference",
    "historical",
}
_GRAPH_METADATA_SEMANTIC_KEYS = {
    "category",
    "entity_type",
    "group",
    "kind",
    "memory_kind",
    "memory_scope",
    "memory_type",
    "profile_group",
    "scope",
}


@dataclass(frozen=True, slots=True)
class PromptProfileItem:
    summary: str
    category: str
    permission_group: PromptProfilePermissionGroup
    confidence: float
    importance: float
    source_label: str | None = None
    risk_tier: str = "low"


@dataclass(frozen=True, slots=True)
class PromptProfileTelemetry:
    evaluated_count: int = 0
    selected_count: int = 0
    used_chars: int = 0
    item_limit: int = DEFAULT_PROFILE_ITEM_LIMIT
    char_budget: int = DEFAULT_PROFILE_CHAR_BUDGET
    dropped_count: int = 0
    drop_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromptProfileSelection:
    items: tuple[PromptProfileItem, ...] = ()
    telemetry: PromptProfileTelemetry = field(default_factory=PromptProfileTelemetry)


@dataclass(frozen=True, slots=True)
class _PromptProfileCandidate:
    summary: str
    category: str
    permission_group: PromptProfilePermissionGroup
    confidence: float
    importance: float
    source_label: str | None
    risk_tier: str
    explicit_source: bool
    updated_at: str


class PromptProfileProvider:
    """Read-only provider for prompt-safe stable preferences and boundaries."""

    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        item_limit: int = DEFAULT_PROFILE_ITEM_LIMIT,
        char_budget: int = DEFAULT_PROFILE_CHAR_BUDGET,
    ) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.item_limit = max(1, min(int(item_limit), 20))
        self.char_budget = max(0, int(char_budget))

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def select(
        self,
        *,
        user_message: str = "",
        semantic_analysis: object | None = None,
    ) -> PromptProfileSelection:
        del user_message, semantic_analysis
        candidates = [candidate for candidate in self._iter_candidates() if candidate is not None]
        candidates.sort(
            key=lambda item: (
                0 if item.permission_group == "boundary_profile" else 1,
                -item.importance,
                -item.confidence,
                0 if item.explicit_source else 1,
                item.updated_at,
            )
        )
        selected: list[PromptProfileItem] = []
        used_chars = 0
        dropped_reasons: list[str] = []
        for candidate in candidates:
            if len(selected) >= self.item_limit:
                dropped_reasons.append("item_limit_exceeded")
                continue
            rendered = _render_item_for_budget(candidate)
            next_chars = used_chars + len(rendered) + (1 if selected else 0)
            if next_chars > self.char_budget:
                dropped_reasons.append("char_budget_exceeded")
                continue
            used_chars = next_chars
            selected.append(
                PromptProfileItem(
                    summary=candidate.summary,
                    category=candidate.category,
                    permission_group=candidate.permission_group,
                    confidence=candidate.confidence,
                    importance=candidate.importance,
                    source_label=candidate.source_label,
                    risk_tier=candidate.risk_tier,
                )
            )
        telemetry = PromptProfileTelemetry(
            evaluated_count=len(candidates),
            selected_count=len(selected),
            used_chars=used_chars,
            item_limit=self.item_limit,
            char_budget=self.char_budget,
            dropped_count=len(candidates) - len(selected),
            drop_reasons=tuple(dict.fromkeys(dropped_reasons)),
        )
        return PromptProfileSelection(items=tuple(selected), telemetry=telemetry)

    def _iter_candidates(self) -> list[_PromptProfileCandidate | None]:
        items: list[_PromptProfileCandidate | None] = []
        if _table_exists(self.conn, "memory_candidates"):
            items.extend(self._candidate_rows())
        if _table_exists(self.conn, "memory_graph_facts"):
            items.extend(self._fact_rows())
        return items

    def _candidate_rows(self) -> list[_PromptProfileCandidate | None]:
        rows = self.conn.execute(
            """
            SELECT
                memory_kind, memory_scope, summary, source_track, risk_tier,
                confidence, importance, evidence_count, status, expires_at,
                superseded_by, updated_at
            FROM memory_candidates
            WHERE status = 'active'
              AND memory_kind IN ('preference', 'boundary')
            ORDER BY updated_at DESC
            LIMIT 100
            """
        ).fetchall()
        return [_candidate_from_memory_candidate(row) for row in rows]

    def _fact_rows(self) -> list[_PromptProfileCandidate | None]:
        rows = self.conn.execute(
            """
            SELECT
                category, subject, predicate, object, status, confidence,
                source_type, support_count, memory_type, entity_type,
                expires_at, metadata_json, importance, updated_at,
                (
                    SELECT r.subject_fact_id
                    FROM memory_graph_facts r
                    WHERE r.statement_kind = 'relation'
                      AND r.relation_type = 'supersedes'
                      AND r.object_fact_id = memory_graph_facts.id
                      AND r.status = 'active'
                    ORDER BY r.updated_at DESC, r.id DESC
                    LIMIT 1
                ) AS authority_superseded_by,
                (
                    SELECT CASE
                        WHEN r.subject_fact_id = memory_graph_facts.id THEN r.object_fact_id
                        ELSE r.subject_fact_id
                    END
                    FROM memory_graph_facts r
                    WHERE r.statement_kind = 'relation'
                      AND r.relation_type = 'contradicts'
                      AND r.status = 'active'
                      AND (r.subject_fact_id = memory_graph_facts.id OR r.object_fact_id = memory_graph_facts.id)
                    ORDER BY r.updated_at DESC, r.id DESC
                    LIMIT 1
                ) AS authority_contradicted_by
            FROM memory_graph_facts
            WHERE status = 'active'
              AND (
                memory_type IN ('preference', 'boundary')
                OR category IN ('preference', 'boundary')
                OR category = ''
              )
            ORDER BY updated_at DESC
            LIMIT 100
            """
        ).fetchall()
        return [_candidate_from_graph_fact(row) for row in rows]


def _candidate_from_memory_candidate(row: sqlite3.Row) -> _PromptProfileCandidate | None:
    kind = str(row["memory_kind"] or "")
    scope = str(row["memory_scope"] or "")
    status = str(row["status"] or "")
    risk = str(row["risk_tier"] or "")
    summary = str(row["summary"] or "").strip()
    if not _allowed_common(
        summary=summary,
        kind=kind,
        scope=scope,
        status=status,
        risk_tier=risk,
        confidence=_clamp(row["confidence"]),
        expires_at=row["expires_at"],
        superseded_by=row["superseded_by"],
        conflicts_with=None,
    ):
        return None
    permission_group = _permission_group(kind)
    if permission_group is None:
        return None
    source_track = str(row["source_track"] or "")
    return _PromptProfileCandidate(
        summary=summary,
        category="preferences" if kind == MemoryKind.PREFERENCE.value else "boundaries",
        permission_group=permission_group,
        confidence=_clamp(row["confidence"]),
        importance=_clamp(row["importance"]),
        source_label=_safe_source_label(source_track),
        risk_tier="low",
        explicit_source=_is_explicit_source(source_track),
        updated_at=str(row["updated_at"] or ""),
    )


def _candidate_from_graph_fact(row: sqlite3.Row) -> _PromptProfileCandidate | None:
    metadata = _json_object(row["metadata_json"])
    kind = str(row["memory_type"] or row["category"] or "")
    scope = str(metadata.get("memory_scope") or "")
    risk = str(metadata.get("risk_tier") or RiskTier.LOW.value)
    status = str(row["status"] or "")
    summary = " ".join(str(row[key] or "").strip() for key in ("subject", "predicate", "object")).strip()
    if _graph_fact_has_forbidden_bucket(row=row, metadata=metadata):
        return None
    if not _allowed_common(
        summary=summary,
        kind=kind,
        scope=scope,
        status=status,
        risk_tier=risk,
        confidence=_clamp(row["confidence"]),
        expires_at=row["expires_at"],
        superseded_by=row["authority_superseded_by"],
        conflicts_with=row["authority_contradicted_by"],
    ):
        return None
    permission_group = _permission_group(kind)
    if permission_group is None:
        return None
    source_type = str(row["source_type"] or "")
    return _PromptProfileCandidate(
        summary=summary,
        category="preferences" if kind == MemoryKind.PREFERENCE.value else "boundaries",
        permission_group=permission_group,
        confidence=_clamp(row["confidence"]),
        importance=_clamp(row["importance"]),
        source_label=_safe_source_label(source_type),
        risk_tier="low",
        explicit_source=_is_explicit_source(source_type),
        updated_at=str(row["updated_at"] or ""),
    )


def _allowed_common(
    *,
    summary: str,
    kind: str,
    scope: str,
    status: str,
    risk_tier: str,
    confidence: float,
    expires_at: object,
    superseded_by: object,
    conflicts_with: object,
) -> bool:
    if status != "active":
        return False
    if kind not in {MemoryKind.PREFERENCE.value, MemoryKind.BOUNDARY.value}:
        return False
    if scope in {
        MemoryScope.PROJECT.value,
        MemoryScope.RELATIONSHIP.value,
        MemoryScope.TEMPORARY.value,
        MemoryScope.SENSITIVE.value,
    }:
        return False
    if risk_tier not in {RiskTier.LOW.value, "normal", "safe"}:
        return False
    if confidence < MIN_STABLE_PROFILE_CONFIDENCE:
        return False
    if superseded_by or conflicts_with:
        return False
    if _is_expired_or_temporary(expires_at):
        return False
    if not summary or _unsafe_prompt_profile_text(summary):
        return False
    return True


def _permission_group(kind: str) -> PromptProfilePermissionGroup | None:
    if kind == MemoryKind.PREFERENCE.value:
        return "style_profile"
    if kind == MemoryKind.BOUNDARY.value:
        return "boundary_profile"
    return None


def _graph_fact_has_forbidden_bucket(*, row: sqlite3.Row, metadata: dict[str, object]) -> bool:
    values: list[object] = [row["category"], row["entity_type"]]
    values.extend(metadata.get(key) for key in _GRAPH_METADATA_SEMANTIC_KEYS)
    return any(_contains_forbidden_bucket(value) for value in values)


def _contains_forbidden_bucket(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_forbidden_bucket(nested) for nested in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_forbidden_bucket(nested) for nested in value)
    text = str(value or "").strip().casefold()
    if not text:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return any(bucket in normalized for bucket in _FORBIDDEN_GRAPH_PROFILE_BUCKETS)


def _safe_source_label(source: str) -> str | None:
    if _is_explicit_source(source):
        return "来自用户明确说明"
    if source in {SourceTrack.SLOW_CONSOLIDATION.value, SourceTrack.MODEL_EXTRACTED.value}:
        return "来自聊天后的整理"
    if source == SourceTrack.DIARY.value:
        return "来自日记整理"
    if source == SourceTrack.CONTINUITY.value:
        return "来自陪伴状态整理"
    if source:
        return "来自一次聊天"
    return None


def _is_explicit_source(source: str) -> bool:
    return source in {SourceTrack.EXPLICIT_USER.value, "explicit_user", "user_feedback"}


def _unsafe_prompt_profile_text(value: str) -> bool:
    if not evaluate_memory_content(value).allowed:
        return True
    lowered = value.casefold()
    forbidden = (
        "source_text",
        "source_excerpt",
        "raw evidence",
        "agent_run_id",
        "target_id",
        "memory_candidates",
        "authorization",
        "bearer ",
        "token",
        "candidate:",
        "fact:",
        "fts",
        "vector",
        "lifecycle_status",
        "redacted",
        "已隐藏",
        "细节已隐藏",
    )
    if any(term in lowered for term in forbidden):
        return True
    return any(
        pattern.search(value)
        for pattern in (
            re.compile(r"\b[A-Za-z]:[\\/][^\s]+"),
            re.compile(r"\\\\[^\s\\]+\\[^\s]+"),
        )
    )


def _is_expired_or_temporary(value: object) -> bool:
    text = str(value or "").strip()
    # Stable profile memory excludes temporary facts even when they have not expired yet.
    # Recent/temporary context belongs in retrieval or continuity, not this section.
    return bool(text)


def _render_item_for_budget(item: _PromptProfileCandidate) -> str:
    prefix = "回答边界" if item.permission_group == "boundary_profile" else "回答偏好"
    return f"- {prefix}: {item.summary}"


def _json_object(value: object) -> dict[str, object]:
    import json

    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clamp(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None
