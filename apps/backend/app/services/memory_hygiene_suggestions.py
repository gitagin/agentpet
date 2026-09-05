from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from app.services.memory_hygiene import TERMINAL_CANDIDATE_STATUSES, TERMINAL_FACT_STATUSES
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_policy import evaluate_memory_content
from app.services.memory_taxonomy import LOW_CONFIDENCE_THRESHOLD, LifecycleStatus, MemoryKind, MemoryScope, RiskTier
from app.storage.database import open_database_connection

from app.utils.sqlite import optional_str
from app.utils.time import coerce_datetime


MemoryHygieneSuggestionType = Literal[
    "stale_recent_state",
    "low_confidence_stale",
    "sensitive_candidate",
]
MemoryHygieneSuggestionTargetType = Literal["candidate", "fact"]
SUGGESTION_TYPES = frozenset(
    {
        "stale_recent_state",
        "low_confidence_stale",
        "sensitive_candidate",
    }
)


class MemoryHygieneSuggestionError(ValueError):
    pass


class MemoryHygieneSuggestionConfirmationRequired(MemoryHygieneSuggestionError):
    pass


class MemoryHygieneSuggestionExpired(MemoryHygieneSuggestionError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryHygieneSuggestion:
    id: str
    type: MemoryHygieneSuggestionType
    title: str
    summary: str
    impact: str
    risk_tier: str
    destructive: bool
    requires_confirmation: bool
    action_label: str
    target_type: MemoryHygieneSuggestionTargetType = field(repr=False, compare=False)
    target_id: str = field(repr=False, compare=False)
    from_status: str = field(repr=False, compare=False)
    to_status: str = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class MemoryHygieneSuggestionApplyResult:
    suggestion_id: str
    type: MemoryHygieneSuggestionType
    status: str


class MemoryHygieneSuggestionService:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.lifecycle = MemoryLifecycleService(self.conn)
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def close(self) -> None:
        self.lifecycle.close()
        if self._owns_connection:
            self.conn.close()

    def preview(
        self,
        *,
        now: datetime | str | None = None,
        stale_candidate_before: datetime | str | None = None,
        low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        limit: int = 100,
    ) -> tuple[MemoryHygieneSuggestion, ...]:
        current_time = coerce_datetime(now) if now is not None else self.now_provider()
        stale_before = (
            coerce_datetime(stale_candidate_before)
            if stale_candidate_before is not None
            else current_time - timedelta(days=30)
        )
        item_limit = max(1, min(limit, 200))
        suggestions: list[MemoryHygieneSuggestion] = []
        for scanner in (
            lambda: self._stale_recent_state_suggestions(current_time, item_limit),
            lambda: self._low_confidence_stale_suggestions(stale_before, low_confidence_threshold, item_limit),
            lambda: self._sensitive_candidate_suggestions(item_limit),
        ):
            if len(suggestions) >= item_limit:
                break
            remaining = item_limit - len(suggestions)
            suggestions.extend(scanner()[:remaining])
        return tuple(_dedupe_suggestions(suggestions)[:item_limit])

    def apply(
        self,
        suggestion_id: str,
        *,
        confirmed: bool,
        agent_action_id: str | None = None,
    ) -> MemoryHygieneSuggestionApplyResult:
        if not confirmed:
            raise MemoryHygieneSuggestionConfirmationRequired("hygiene_confirmation_required")
        suggestion = next((item for item in self.preview() if item.id == suggestion_id), None)
        if suggestion is None:
            raise MemoryHygieneSuggestionExpired("hygiene_suggestion_expired")
        if suggestion.target_type == "candidate":
            transition = self.lifecycle.transition_candidate(
                suggestion.target_id,
                suggestion.to_status,
                reason=f"hygiene_suggestion:{suggestion.type}",
                agent_action_id=agent_action_id,
            )
            return MemoryHygieneSuggestionApplyResult(
                suggestion_id=suggestion.id,
                type=suggestion.type,
                status=transition.to_status.value,
            )
        transition = self.lifecycle.transition_fact(
            suggestion.target_id,
            suggestion.to_status,
            reason=f"hygiene_suggestion:{suggestion.type}",
            agent_action_id=agent_action_id,
        )
        return MemoryHygieneSuggestionApplyResult(
            suggestion_id=suggestion.id,
            type=suggestion.type,
            status=transition.to_status.value,
        )

    def read_effect(
        self,
        *,
        suggestion_id: str,
        suggestion_type: str,
        target_type: str,
        target_id: str,
        to_status: str,
        agent_action_id: str,
    ) -> dict[str, object] | None:
        target_column = "candidate_id" if target_type == "candidate" else "fact_id"
        rows = self.conn.execute(
            f"""
            SELECT id, from_status, to_status, reason
            FROM memory_lifecycle_events
            WHERE agent_action_id = ?
              AND {target_column} = ?
              AND reason = ?
            ORDER BY created_at, id
            LIMIT 2
            """,
            (agent_action_id, target_id, f"hygiene_suggestion:{suggestion_type}"),
        ).fetchall()
        if len(rows) != 1 or str(rows[0]["to_status"]) != to_status:
            return None
        table = "memory_candidates" if target_type == "candidate" else "memory_graph_facts"
        target = self.conn.execute(
            f"SELECT status FROM {table} WHERE id = ?",
            (target_id,),
        ).fetchone()
        if target is None or str(target["status"]) != to_status:
            return None
        return {
            "suggestion_id": suggestion_id,
            "suggestion_type": suggestion_type,
            "target_type": target_type,
            "target_id": target_id,
            "status": to_status,
            "state_ref": f"memory-hygiene:{suggestion_id}",
            "observed_effect": "memory_lifecycle_transition",
        }

    def recover_action_parameters(
        self,
        *,
        suggestion_id: str,
        agent_action_id: str,
    ) -> dict[str, object] | None:
        """Reconstruct a hygiene claim from its bound lifecycle event.

        The action receipt intentionally omits target identifiers.  The
        lifecycle event is the private authority that binds those identifiers
        to the durable claim, so a retry can rebuild the exact policy payload
        without exposing memory contents in the public action metadata.
        """
        rows = self.conn.execute(
            """
            SELECT candidate_id, fact_id, from_status, to_status, reason
            FROM memory_lifecycle_events
            WHERE agent_action_id = ?
              AND reason LIKE 'hygiene_suggestion:%'
            ORDER BY created_at, id
            LIMIT 2
            """,
            (agent_action_id,),
        ).fetchall()
        if len(rows) != 1:
            return None
        row = rows[0]
        candidate_id = str(row["candidate_id"] or "")
        fact_id = str(row["fact_id"] or "")
        if bool(candidate_id) == bool(fact_id):
            return None
        reason = str(row["reason"] or "")
        suggestion_type = reason.removeprefix("hygiene_suggestion:").strip()
        if suggestion_type not in SUGGESTION_TYPES:
            return None
        from_status = str(row["from_status"] or "")
        to_status = str(row["to_status"] or "")
        target_type = "candidate" if candidate_id else "fact"
        target_id = candidate_id or fact_id
        if not from_status or not to_status or not target_id:
            return None
        table = "memory_candidates" if target_type == "candidate" else "memory_graph_facts"
        target = self.conn.execute(
            f"SELECT status FROM {table} WHERE id = ?",
            (target_id,),
        ).fetchone()
        if target is None or str(target["status"]) != to_status:
            return None
        return {
            "suggestion_id": suggestion_id,
            "suggestion_type": suggestion_type,
            "target_type": target_type,
            "target_id": target_id,
            "from_status": from_status,
            "to_status": to_status,
            "confirmed": True,
        }

    def _stale_recent_state_suggestions(self, now: datetime, limit: int) -> list[MemoryHygieneSuggestion]:
        suggestions: list[MemoryHygieneSuggestion] = []
        candidate_rows = self.conn.execute(
            """
            SELECT id, status, memory_kind, memory_scope, expires_at, updated_at
            FROM memory_candidates
            WHERE status NOT IN (?, ?, ?, ?)
              AND expires_at IS NOT NULL
              AND (memory_kind = ? OR memory_scope = ?)
            ORDER BY expires_at ASC, updated_at ASC
            LIMIT ?
            """,
            (
                *TERMINAL_CANDIDATE_STATUSES,
                MemoryKind.RECENT_STATE.value,
                MemoryScope.TEMPORARY.value,
                limit,
            ),
        ).fetchall()
        for row in candidate_rows:
            if not _is_due(row["expires_at"], now):
                continue
            suggestions.append(
                self._build_suggestion(
                    suggestion_type="stale_recent_state",
                    target_type="candidate",
                    target_id=str(row["id"]),
                    from_status=str(row["status"]),
                    to_status=LifecycleStatus.ARCHIVED.value,
                    updated_at=str(row["updated_at"]),
                    expires_at=optional_str(row["expires_at"]),
                )
            )

        fact_rows = self.conn.execute(
            """
            SELECT id, status, memory_type, category, expires_at, updated_at
            FROM memory_graph_facts
            WHERE status NOT IN (?, ?, ?, ?, ?, ?)
              AND expires_at IS NOT NULL
              AND (memory_type = ? OR category = ?)
            ORDER BY expires_at ASC, updated_at ASC
            LIMIT ?
            """,
            (
                *TERMINAL_FACT_STATUSES,
                MemoryKind.RECENT_STATE.value,
                MemoryKind.RECENT_STATE.value,
                limit,
            ),
        ).fetchall()
        for row in fact_rows:
            if not _is_due(row["expires_at"], now):
                continue
            suggestions.append(
                self._build_suggestion(
                    suggestion_type="stale_recent_state",
                    target_type="fact",
                    target_id=str(row["id"]),
                    from_status=str(row["status"]),
                    to_status=LifecycleStatus.ARCHIVED.value,
                    updated_at=str(row["updated_at"]),
                    expires_at=optional_str(row["expires_at"]),
                )
            )
        return suggestions

    def _low_confidence_stale_suggestions(
        self,
        stale_before: datetime,
        low_confidence_threshold: float,
        limit: int,
    ) -> list[MemoryHygieneSuggestion]:
        rows = self.conn.execute(
            """
            SELECT id, status, confidence, updated_at
            FROM memory_candidates
            WHERE status = ?
              AND last_confirmed_at IS NULL
              AND confidence < ?
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (LifecycleStatus.CANDIDATE.value, low_confidence_threshold, limit),
        ).fetchall()
        suggestions: list[MemoryHygieneSuggestion] = []
        for row in rows:
            if coerce_datetime(str(row["updated_at"])) >= stale_before:
                continue
            suggestions.append(
                self._build_suggestion(
                    suggestion_type="low_confidence_stale",
                    target_type="candidate",
                    target_id=str(row["id"]),
                    from_status=str(row["status"]),
                    to_status=LifecycleStatus.REJECTED.value,
                    updated_at=str(row["updated_at"]),
                    confidence=str(row["confidence"]),
                )
            )
        return suggestions

    def _sensitive_candidate_suggestions(self, limit: int) -> list[MemoryHygieneSuggestion]:
        rows = self.conn.execute(
            """
            SELECT id, summary, normalized_value, status, memory_scope, risk_tier, updated_at
            FROM memory_candidates
            WHERE status NOT IN (?, ?, ?, ?)
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (*TERMINAL_CANDIDATE_STATUSES, limit),
        ).fetchall()
        suggestions: list[MemoryHygieneSuggestion] = []
        for row in rows:
            if not _candidate_is_sensitive(row):
                continue
            suggestions.append(
                self._build_suggestion(
                    suggestion_type="sensitive_candidate",
                    target_type="candidate",
                    target_id=str(row["id"]),
                    from_status=str(row["status"]),
                    to_status=LifecycleStatus.REJECTED.value,
                    updated_at=str(row["updated_at"]),
                    risk_tier=str(row["risk_tier"]),
                    memory_scope=str(row["memory_scope"]),
                )
            )
        return suggestions

    def _build_suggestion(
        self,
        *,
        suggestion_type: MemoryHygieneSuggestionType,
        target_type: MemoryHygieneSuggestionTargetType,
        target_id: str,
        from_status: str,
        to_status: str,
        updated_at: str,
        **extra: str | None,
    ) -> MemoryHygieneSuggestion:
        text = _suggestion_text(suggestion_type)
        suggestion_id = _opaque_suggestion_id(
            suggestion_type,
            target_type,
            target_id,
            from_status,
            to_status,
            updated_at,
            *[f"{key}={value or ''}" for key, value in sorted(extra.items())],
        )
        return MemoryHygieneSuggestion(
            id=suggestion_id,
            type=suggestion_type,
            title=text["title"],
            summary=text["summary"],
            impact=text["impact"],
            risk_tier=text["risk_tier"],
            destructive=False,
            requires_confirmation=True,
            action_label=text["action_label"],
            target_type=target_type,
            target_id=target_id,
            from_status=from_status,
            to_status=to_status,
        )


def _suggestion_text(suggestion_type: MemoryHygieneSuggestionType) -> dict[str, str]:
    if suggestion_type == "stale_recent_state":
        return {
            "title": "临时状态已过期",
            "summary": "有一条临时状态已经到期，建议归档。",
            "impact": "归档后不会再作为当前记忆使用。",
            "risk_tier": "low",
            "action_label": "归档",
        }
    if suggestion_type == "low_confidence_stale":
        return {
            "title": "低置信候选长期未确认",
            "summary": "有一条低置信候选长期没有被确认，建议忽略。",
            "impact": "忽略后不会再作为当前记忆使用。",
            "risk_tier": "low",
            "action_label": "忽略",
        }
    return {
        "title": "检测到不适合保存的敏感候选",
        "summary": "有一条候选记忆不适合保存，建议安全拒绝。",
        "impact": "拒绝后不会进入普通记忆或回答上下文。",
        "risk_tier": "low",
        "action_label": "安全拒绝",
    }


def _candidate_is_sensitive(row: sqlite3.Row) -> bool:
    if str(row["risk_tier"]) == RiskTier.HIGH.value:
        return True
    if str(row["memory_scope"]) == MemoryScope.SENSITIVE.value:
        return True
    decision = evaluate_memory_content(f"{row['summary']}\n{row['normalized_value']}")
    return not decision.allowed


def _dedupe_suggestions(suggestions: list[MemoryHygieneSuggestion]) -> list[MemoryHygieneSuggestion]:
    seen: set[str] = set()
    deduped: list[MemoryHygieneSuggestion] = []
    for suggestion in suggestions:
        if suggestion.id in seen:
            continue
        seen.add(suggestion.id)
        deduped.append(suggestion)
    return deduped


def _opaque_suggestion_id(*parts: str) -> str:
    payload = "\x1f".join(("memory_hygiene_suggestion_v1", *[str(part) for part in parts]))
    return "hyg_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _is_due(value: str | None, now: datetime) -> bool:
    if not value:
        return False
    return coerce_datetime(value) <= now




