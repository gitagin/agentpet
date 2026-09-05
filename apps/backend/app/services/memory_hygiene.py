from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.models.enums import MemoryFactStatus
from app.services.memory_candidates import MemoryCandidateRecord
from app.services.memory_lifecycle import MemoryLifecycleService, MemoryLifecycleTransitionError
from app.services.memory_policy import evaluate_memory_content
from app.services.memory_taxonomy import LOW_CONFIDENCE_THRESHOLD, LifecycleStatus, MemoryKind, MemoryScope
from app.utils.time import utc_now_iso

from app.utils.time import coerce_datetime


TERMINAL_CANDIDATE_STATUSES = {
    LifecycleStatus.ARCHIVED.value,
    LifecycleStatus.FORGOTTEN.value,
    LifecycleStatus.REJECTED.value,
    LifecycleStatus.SUPERSEDED.value,
}
TERMINAL_FACT_STATUSES = {
    MemoryFactStatus.ARCHIVED.value,
    MemoryFactStatus.FORGOTTEN.value,
    MemoryFactStatus.REJECTED.value,
    MemoryFactStatus.SUPERSEDED.value,
    MemoryFactStatus.WRONG.value,
    MemoryFactStatus.SENSITIVE_BLOCKED.value,
}


@dataclass(frozen=True, slots=True)
class MemoryHygieneAction:
    target_type: str
    target_id: str
    action: str
    from_status: str
    to_status: str
    reason: str
    superseded_by: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryHygieneRunResult:
    actions: tuple[MemoryHygieneAction, ...]

    @property
    def action_count(self) -> int:
        return len(self.actions)

    def count(self, action: str) -> int:
        return sum(1 for item in self.actions if item.action == action)


class MemoryHygieneService:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.lifecycle = MemoryLifecycleService(db)
        self.conn = self.lifecycle.conn
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def close(self) -> None:
        self.lifecycle.close()

    def run(
        self,
        *,
        now: datetime | str | None = None,
        stale_candidate_before: datetime | str | None = None,
        low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        limit: int = 500,
    ) -> MemoryHygieneRunResult:
        current_time = coerce_datetime(now) if now is not None else self.now_provider()
        stale_before = (
            coerce_datetime(stale_candidate_before)
            if stale_candidate_before is not None
            else current_time - timedelta(days=30)
        )
        action_limit = max(1, min(limit, 2000))
        actions: list[MemoryHygieneAction] = []
        for runner in (
            lambda: self._reject_policy_violating_candidates(action_limit),
            lambda: self._archive_expired_recent_state(current_time, action_limit),
            lambda: self._merge_duplicate_candidates(action_limit),
            lambda: self._reject_stale_low_confidence_candidates(
                stale_before=stale_before,
                low_confidence_threshold=low_confidence_threshold,
                limit=action_limit,
            ),
            lambda: self._supersede_weaker_conflicting_facts(action_limit),
        ):
            if len(actions) >= action_limit:
                break
            remaining = action_limit - len(actions)
            actions.extend(runner()[:remaining])
        return MemoryHygieneRunResult(actions=tuple(actions))

    def _reject_policy_violating_candidates(self, limit: int) -> list[MemoryHygieneAction]:
        rows = self.conn.execute(
            """
            SELECT id, summary, normalized_value, status
            FROM memory_candidates
            WHERE status NOT IN (?, ?, ?, ?)
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (*TERMINAL_CANDIDATE_STATUSES, limit),
        ).fetchall()
        actions: list[MemoryHygieneAction] = []
        for row in rows:
            policy = evaluate_memory_content(f"{row['summary']}\n{row['normalized_value']}")
            if policy.allowed:
                continue
            reason = f"hygiene_policy_rejected:{policy.reason or 'sensitive_content'}"
            transition = self.lifecycle.transition_candidate(row["id"], LifecycleStatus.REJECTED, reason=reason)
            actions.append(
                MemoryHygieneAction(
                    target_type="candidate",
                    target_id=transition.target_id,
                    action="reject_sensitive_candidate",
                    from_status=transition.from_status.value,
                    to_status=transition.to_status.value,
                    reason=reason,
                )
            )
        return actions

    def _archive_expired_recent_state(self, now: datetime, limit: int) -> list[MemoryHygieneAction]:
        actions: list[MemoryHygieneAction] = []
        rows = self.conn.execute(
            """
            SELECT id, status, expires_at
            FROM memory_candidates
            WHERE status NOT IN (?, ?, ?, ?)
              AND expires_at IS NOT NULL
              AND (memory_kind = ? OR memory_scope = ?)
            ORDER BY expires_at ASC
            LIMIT ?
            """,
            (
                *TERMINAL_CANDIDATE_STATUSES,
                MemoryKind.RECENT_STATE.value,
                MemoryScope.TEMPORARY.value,
                limit,
            ),
        ).fetchall()
        for row in rows:
            if not _is_due(row["expires_at"], now):
                continue
            reason = "hygiene_expired_recent_state"
            transition = self.lifecycle.transition_candidate(row["id"], LifecycleStatus.ARCHIVED, reason=reason)
            actions.append(
                MemoryHygieneAction(
                    target_type="candidate",
                    target_id=transition.target_id,
                    action="archive_expired_recent_state",
                    from_status=transition.from_status.value,
                    to_status=transition.to_status.value,
                    reason=reason,
                )
            )

        fact_rows = self.conn.execute(
            """
            SELECT id, status, expires_at
            FROM memory_graph_facts
            WHERE status NOT IN (?, ?, ?, ?, ?, ?)
              AND expires_at IS NOT NULL
              AND (memory_type = ? OR category = ?)
            ORDER BY expires_at ASC
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
            reason = "hygiene_expired_recent_state"
            transition = self.lifecycle.transition_fact(row["id"], LifecycleStatus.ARCHIVED, reason=reason)
            actions.append(
                MemoryHygieneAction(
                    target_type="fact",
                    target_id=transition.target_id,
                    action="archive_expired_recent_state",
                    from_status=transition.from_status.value,
                    to_status=transition.to_status.value,
                    reason=reason,
                )
            )
        return actions

    def _merge_duplicate_candidates(self, limit: int) -> list[MemoryHygieneAction]:
        candidates = self.lifecycle.candidates.list_candidates(limit=limit)
        groups: dict[tuple[str, str, str], list[MemoryCandidateRecord]] = defaultdict(list)
        for candidate in candidates:
            if candidate.status.value in TERMINAL_CANDIDATE_STATUSES:
                continue
            key_value = (candidate.normalized_value or candidate.summary).strip().casefold()
            if not key_value:
                continue
            groups[(candidate.memory_kind.value, candidate.memory_scope.value, key_value)].append(candidate)

        actions: list[MemoryHygieneAction] = []
        for duplicates in groups.values():
            if len(duplicates) < 2:
                continue
            keeper = sorted(duplicates, key=_candidate_keeper_key)[0]
            for duplicate in duplicates:
                if duplicate.id == keeper.id:
                    continue
                self._merge_candidate_evidence(keeper_id=keeper.id, duplicate=duplicate)
                reason = "hygiene_duplicate_candidate_merged"
                transition = self.lifecycle.transition_candidate(
                    duplicate.id,
                    LifecycleStatus.SUPERSEDED,
                    reason=reason,
                    superseded_by=keeper.id,
                )
                actions.append(
                    MemoryHygieneAction(
                        target_type="candidate",
                        target_id=transition.target_id,
                        action="merge_duplicate_candidate",
                        from_status=transition.from_status.value,
                        to_status=transition.to_status.value,
                        reason=reason,
                        superseded_by=keeper.id,
                    )
                )
        return actions

    def _merge_candidate_evidence(self, *, keeper_id: str, duplicate: MemoryCandidateRecord) -> None:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                "UPDATE memory_evidence SET candidate_id = ? WHERE candidate_id = ?",
                (keeper_id, duplicate.id),
            )
            self.conn.execute(
                """
                UPDATE memory_candidates
                SET evidence_count = (
                        SELECT COUNT(*)
                        FROM memory_evidence
                        WHERE candidate_id = ?
                    ),
                    confidence = MAX(confidence, ?),
                    importance = MAX(importance, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (keeper_id, duplicate.confidence, duplicate.importance, now, keeper_id),
            )
            self.conn.execute(
                "UPDATE memory_candidates SET evidence_count = 0, updated_at = ? WHERE id = ?",
                (now, duplicate.id),
            )

    def _reject_stale_low_confidence_candidates(
        self,
        *,
        stale_before: datetime,
        low_confidence_threshold: float,
        limit: int,
    ) -> list[MemoryHygieneAction]:
        rows = self.conn.execute(
            """
            SELECT id, status, updated_at
            FROM memory_candidates
            WHERE status = ?
              AND last_confirmed_at IS NULL
              AND confidence < ?
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (LifecycleStatus.CANDIDATE.value, low_confidence_threshold, limit),
        ).fetchall()
        actions: list[MemoryHygieneAction] = []
        for row in rows:
            updated_at = coerce_datetime(row["updated_at"])
            if updated_at >= stale_before:
                continue
            reason = "hygiene_stale_low_confidence_candidate"
            transition = self.lifecycle.transition_candidate(row["id"], LifecycleStatus.REJECTED, reason=reason)
            actions.append(
                MemoryHygieneAction(
                    target_type="candidate",
                    target_id=transition.target_id,
                    action="reject_stale_low_confidence_candidate",
                    from_status=transition.from_status.value,
                    to_status=transition.to_status.value,
                    reason=reason,
                )
            )
        return actions

    def _supersede_weaker_conflicting_facts(self, limit: int) -> list[MemoryHygieneAction]:
        facts = self.conn.execute(
            """
            SELECT id, conflict_key, object, confidence, support_count, updated_at
            FROM memory_graph_facts
            WHERE status = ?
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (MemoryFactStatus.ACTIVE.value, limit),
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for fact in facts:
            groups[str(fact["conflict_key"])].append(fact)

        actions: list[MemoryHygieneAction] = []
        for group in groups.values():
            if len(group) < 2:
                continue
            strongest = sorted(group, key=_fact_strength_key)[0]
            strongest_updated_at = coerce_datetime(strongest["updated_at"])
            for fact in group:
                if fact["id"] == strongest["id"] or str(fact["object"]).casefold() == str(strongest["object"]).casefold():
                    continue
                fact_updated_at = coerce_datetime(fact["updated_at"])
                if float(strongest["confidence"]) <= float(fact["confidence"]) or strongest_updated_at <= fact_updated_at:
                    continue
                reason = "hygiene_conflict_superseded_by_stronger_fact"
                try:
                    old, replacement = self.lifecycle.supersede_fact(
                        str(fact["id"]),
                        str(strongest["id"]),
                        reason=reason,
                    )
                except MemoryLifecycleTransitionError:
                    transition = self.lifecycle.transition_fact(str(fact["id"]), LifecycleStatus.STALE, reason=reason)
                    actions.append(
                        MemoryHygieneAction(
                            target_type="fact",
                            target_id=transition.target_id,
                            action="mark_conflicting_fact_stale",
                            from_status=transition.from_status.value,
                            to_status=transition.to_status.value,
                            reason=reason,
                        )
                    )
                    continue
                actions.append(
                    MemoryHygieneAction(
                        target_type="fact",
                        target_id=old.id,
                        action="supersede_conflicting_fact",
                        from_status=LifecycleStatus.ACTIVE.value,
                        to_status=old.status.value,
                        reason=reason,
                        superseded_by=replacement.id,
                    )
                )
        return actions


def _candidate_keeper_key(candidate: MemoryCandidateRecord) -> tuple[int, float, int, str, str]:
    status_rank = {
        LifecycleStatus.ACTIVE: 0,
        LifecycleStatus.CANDIDATE: 1,
        LifecycleStatus.STALE: 2,
    }.get(candidate.status, 3)
    return (status_rank, -candidate.confidence, -candidate.evidence_count, candidate.updated_at, candidate.id)


def _fact_strength_key(row: sqlite3.Row) -> tuple[float, int, str, str]:
    return (-float(row["confidence"]), -int(row["support_count"]), str(row["updated_at"]), str(row["id"]))


def _is_due(value: str | None, now: datetime) -> bool:
    if not value:
        return False
    return coerce_datetime(value) <= now


