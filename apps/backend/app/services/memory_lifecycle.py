from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.models.enums import MemoryFactStatus
from app.services.memory_candidates import (
    MemoryCandidateCreate,
    MemoryCandidateRecord,
    MemoryCandidateStore,
    MemoryFeedbackEventCreate,
)
from app.services.memory_graph import MemoryFactCandidate, MemoryGraphFact, MemoryGraphStore
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, SourceTrack
from app.storage.database import open_database_connection
from app.utils.time import utc_now_iso


MemoryTargetType = Literal["candidate", "fact"]
MemoryFeedbackOperation = Literal[
    "keep",
    "edit",
    "forget",
    "make_temporary",
    "mark_completed",
    "mark_stale",
    "reject_candidate",
]


@dataclass(frozen=True, slots=True)
class MemoryLifecycleTransitionResult:
    target_type: MemoryTargetType
    target_id: str
    from_status: LifecycleStatus
    to_status: LifecycleStatus
    reason: str
    superseded_by: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryFeedbackApplyResult:
    target_type: MemoryTargetType
    target_id: str
    operation: MemoryFeedbackOperation
    status: LifecycleStatus
    feedback_event_id: str
    replacement_target_id: str | None = None


class MemoryLifecycleTransitionError(ValueError):
    pass


class MemoryLifecycleService:
    def __init__(self, db: str | Path | sqlite3.Connection, *, graph_root: str | Path | None = None) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.candidates = MemoryCandidateStore(self.conn)
        self.graph = MemoryGraphStore(self.conn, graph_root=graph_root)

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def transition(
        self,
        *,
        target_type: MemoryTargetType,
        target_id: str,
        to_status: LifecycleStatus | MemoryFactStatus | str,
        reason: str,
        superseded_by: str | None = None,
        source_agent_run_id: str | None = None,
        source_message_id: str | None = None,
        agent_action_id: str | None = None,
    ) -> MemoryLifecycleTransitionResult:
        """Single transition entry point with target-specific policy kept internal."""
        if target_type == "candidate":
            try:
                candidate_status = LifecycleStatus(
                    to_status.value if isinstance(to_status, (LifecycleStatus, MemoryFactStatus)) else str(to_status)
                )
            except ValueError as exc:
                raise MemoryLifecycleTransitionError(
                    f"unsupported_candidate_status:{to_status}"
                ) from exc
            return self.transition_candidate(
                target_id,
                candidate_status,
                reason=reason,
                superseded_by=superseded_by,
                source_agent_run_id=source_agent_run_id,
                source_message_id=source_message_id,
                agent_action_id=agent_action_id,
            )
        if target_type == "fact":
            return self.transition_fact(
                target_id,
                to_status,
                reason=reason,
                superseded_by=superseded_by,
            )
        raise MemoryLifecycleTransitionError(f"unsupported_memory_target_type:{target_type}")

    def transition_candidate(
        self,
        candidate_id: str,
        to_status: LifecycleStatus | str,
        *,
        reason: str,
        superseded_by: str | None = None,
        source_agent_run_id: str | None = None,
        source_message_id: str | None = None,
        agent_action_id: str | None = None,
    ) -> MemoryLifecycleTransitionResult:
        target = LifecycleStatus(to_status)
        candidate = self.candidates.get_candidate(candidate_id)
        _validate_transition(candidate.status, target, superseded_by=superseded_by)
        self.candidates.transition(
            candidate_id=candidate.id,
            to_status=target,
            reason=reason,
            source_agent_run_id=source_agent_run_id,
            source_message_id=source_message_id,
            agent_action_id=agent_action_id,
            superseded_by=superseded_by,
            metadata={"trigger": reason, "superseded_by": superseded_by} if superseded_by else {"trigger": reason},
        )
        return MemoryLifecycleTransitionResult(
            target_type="candidate",
            target_id=candidate.id,
            from_status=candidate.status,
            to_status=target,
            reason=reason,
            superseded_by=superseded_by,
        )

    def transition_fact(
        self,
        fact_id: str,
        to_status: LifecycleStatus | MemoryFactStatus | str,
        *,
        reason: str,
        superseded_by: str | None = None,
    ) -> MemoryLifecycleTransitionResult:
        fact_target = _coerce_fact_status(to_status)
        target = _fact_lifecycle_status(fact_target)
        fact = self.graph.get(fact_id)
        current = _fact_lifecycle_status(fact.status)
        _validate_fact_transition(current, target, superseded_by=superseded_by)
        self.graph.update_status(
            fact.id,
            fact_target,
            reason=reason,
            superseded_by=superseded_by,
        )
        return MemoryLifecycleTransitionResult(
            target_type="fact",
            target_id=fact.id,
            from_status=current,
            to_status=target,
            reason=reason,
            superseded_by=superseded_by,
        )

    def mark_candidate_completed(self, candidate_id: str, *, reason: str = "user_marked_completed") -> MemoryCandidateRecord:
        candidate = self.candidates.get_candidate(candidate_id)
        if candidate.memory_kind is not MemoryKind.PROJECT_CONTEXT:
            raise MemoryLifecycleTransitionError("only_project_context_can_be_marked_completed")
        target = LifecycleStatus.ARCHIVED if candidate.status in {LifecycleStatus.ACTIVE, LifecycleStatus.STALE} else LifecycleStatus.REJECTED
        self.transition_candidate(candidate.id, target, reason=reason)
        return self.candidates.get_candidate(candidate.id)

    def mark_fact_completed(self, fact_id: str, *, reason: str = "user_marked_completed") -> MemoryGraphFact:
        fact = self.graph.get(fact_id)
        if not _fact_is_project_context(fact):
            raise MemoryLifecycleTransitionError("only_project_context_can_be_marked_completed")
        self.transition_fact(fact.id, LifecycleStatus.ARCHIVED, reason=reason)
        return self.graph.get(fact.id)

    def supersede_candidate(
        self,
        old_candidate_id: str,
        replacement_candidate_id: str,
        *,
        reason: str = "new_memory_supersedes_old",
        allow_boundary_override: bool = False,
    ) -> tuple[MemoryCandidateRecord, MemoryCandidateRecord]:
        old = self.candidates.get_candidate(old_candidate_id)
        replacement = self.candidates.get_candidate(replacement_candidate_id)
        _ensure_boundary_can_be_superseded(old_kind=old.memory_kind, replacement_kind=replacement.memory_kind, allow=allow_boundary_override)
        if replacement.status is LifecycleStatus.CANDIDATE:
            self.transition_candidate(replacement.id, LifecycleStatus.ACTIVE, reason="replacement_promoted")
        self.transition_candidate(old.id, LifecycleStatus.SUPERSEDED, reason=reason, superseded_by=replacement.id)
        return self.candidates.get_candidate(old.id), self.candidates.get_candidate(replacement.id)

    def supersede_fact(
        self,
        old_fact_id: str,
        replacement_fact_id: str,
        *,
        reason: str = "new_memory_supersedes_old",
        allow_boundary_override: bool = False,
    ) -> tuple[MemoryGraphFact, MemoryGraphFact]:
        old = self.graph.get(old_fact_id)
        replacement = self.graph.get(replacement_fact_id)
        _ensure_boundary_can_be_superseded(
            old_kind=_fact_memory_kind(old),
            replacement_kind=_fact_memory_kind(replacement),
            allow=allow_boundary_override,
        )
        if _fact_lifecycle_status(replacement.status) is LifecycleStatus.CANDIDATE:
            self.transition_fact(replacement.id, LifecycleStatus.ACTIVE, reason="replacement_promoted")
        self.transition_fact(old.id, LifecycleStatus.SUPERSEDED, reason=reason, superseded_by=replacement.id)
        return self.graph.get(old.id), self.graph.get(replacement.id)

    def mark_old_project_candidates_stale(self, *, older_than_updated_at: str, limit: int = 100) -> tuple[str, ...]:
        rows = self.conn.execute(
            """
            SELECT id
            FROM memory_candidates
            WHERE memory_kind = ?
              AND status = ?
              AND updated_at < ?
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (MemoryKind.PROJECT_CONTEXT.value, LifecycleStatus.ACTIVE.value, older_than_updated_at, max(1, min(limit, 500))),
        ).fetchall()
        stale_ids: list[str] = []
        for row in rows:
            candidate_id = str(row["id"])
            self.transition_candidate(candidate_id, LifecycleStatus.STALE, reason="project_context_stale_by_age")
            stale_ids.append(candidate_id)
        return tuple(stale_ids)

    def apply_feedback(
        self,
        *,
        target_type: MemoryTargetType,
        target_id: str,
        operation: MemoryFeedbackOperation,
        feedback_text: str = "",
        replacement_text: str | None = None,
        replacement_subject: str | None = None,
        replacement_predicate: str | None = None,
        replacement_object: str | None = None,
        expires_at: str | None = None,
        source_conversation_id: str | None = None,
        source_message_id: str | None = None,
        source_agent_run_id: str | None = None,
        agent_action_id: str | None = None,
    ) -> MemoryFeedbackApplyResult:
        source_conversation_id = _existing_source_id(self.conn, "conversations", source_conversation_id)
        source_message_id = _existing_source_id(self.conn, "messages", source_message_id)
        source_agent_run_id = _existing_source_id(self.conn, "agent_runs", source_agent_run_id)
        if target_type == "candidate":
            status, replacement_id = self._apply_candidate_feedback(
                target_id,
                operation,
                feedback_text=feedback_text,
                replacement_text=replacement_text,
                expires_at=expires_at,
                source_agent_run_id=source_agent_run_id,
                source_message_id=source_message_id,
                agent_action_id=agent_action_id,
            )
            feedback_event_id = self.candidates.record_feedback(
                MemoryFeedbackEventCreate(
                    candidate_id=target_id,
                    feedback_type=_feedback_type(operation),
                    feedback_text=feedback_text,
                    requested_status=status,
                    replacement_candidate_id=replacement_id,
                    source_conversation_id=source_conversation_id,
                    source_message_id=source_message_id,
                    source_agent_run_id=source_agent_run_id,
                    agent_action_id=agent_action_id,
                    metadata=_feedback_metadata(operation=operation, replacement_target_id=replacement_id, expires_at=expires_at),
                )
            )
            return MemoryFeedbackApplyResult(
                target_type=target_type,
                target_id=target_id,
                operation=operation,
                status=status,
                feedback_event_id=feedback_event_id,
                replacement_target_id=replacement_id,
            )
        if target_type == "fact":
            status, replacement_id = self._apply_fact_feedback(
                target_id,
                operation,
                feedback_text=feedback_text,
                replacement_text=replacement_text,
                replacement_subject=replacement_subject,
                replacement_predicate=replacement_predicate,
                replacement_object=replacement_object,
                expires_at=expires_at,
            )
            feedback_event_id = self.candidates.record_feedback(
                MemoryFeedbackEventCreate(
                    fact_id=target_id,
                    feedback_type=_feedback_type(operation),
                    feedback_text=feedback_text,
                    requested_status=status,
                    source_conversation_id=source_conversation_id,
                    source_message_id=source_message_id,
                    source_agent_run_id=source_agent_run_id,
                    agent_action_id=agent_action_id,
                    metadata=_feedback_metadata(operation=operation, replacement_target_id=replacement_id, expires_at=expires_at),
                )
            )
            return MemoryFeedbackApplyResult(
                target_type=target_type,
                target_id=target_id,
                operation=operation,
                status=status,
                feedback_event_id=feedback_event_id,
                replacement_target_id=replacement_id,
            )
        raise MemoryLifecycleTransitionError("invalid_memory_feedback_target_type")

    def _apply_candidate_feedback(
        self,
        candidate_id: str,
        operation: MemoryFeedbackOperation,
        *,
        feedback_text: str,
        replacement_text: str | None,
        expires_at: str | None,
        source_agent_run_id: str | None,
        source_message_id: str | None,
        agent_action_id: str | None,
    ) -> tuple[LifecycleStatus, str | None]:
        candidate = self.candidates.get_candidate(candidate_id)
        if operation == "keep":
            result = self.transition_candidate(
                candidate.id,
                LifecycleStatus.ACTIVE,
                reason="user_kept_memory",
                source_agent_run_id=source_agent_run_id,
                source_message_id=source_message_id,
                agent_action_id=agent_action_id,
            )
            return result.to_status, None
        if operation == "reject_candidate":
            result = self.transition_candidate(
                candidate.id,
                LifecycleStatus.REJECTED,
                reason="user_rejected_candidate",
                source_agent_run_id=source_agent_run_id,
                source_message_id=source_message_id,
                agent_action_id=agent_action_id,
            )
            return result.to_status, None
        if operation == "forget":
            result = self.transition_candidate(
                candidate.id,
                LifecycleStatus.FORGOTTEN,
                reason="user_forget_memory",
                source_agent_run_id=source_agent_run_id,
                source_message_id=source_message_id,
                agent_action_id=agent_action_id,
            )
            return result.to_status, None
        if operation == "mark_stale":
            result = self.transition_candidate(
                candidate.id,
                LifecycleStatus.STALE,
                reason="user_marked_stale",
                source_agent_run_id=source_agent_run_id,
                source_message_id=source_message_id,
                agent_action_id=agent_action_id,
            )
            return result.to_status, None
        if operation == "mark_completed":
            completed = self.mark_candidate_completed(candidate.id)
            return completed.status, None
        if operation == "edit":
            replacement = self._create_replacement_candidate(candidate, replacement_text)
            old, _ = self.supersede_candidate(candidate.id, replacement.id, reason="user_edited_memory", allow_boundary_override=True)
            return old.status, replacement.id
        if operation == "make_temporary":
            updated = self._make_candidate_temporary(candidate, expires_at)
            return updated.status, None
        raise MemoryLifecycleTransitionError("invalid_memory_feedback_operation")

    def _apply_fact_feedback(
        self,
        fact_id: str,
        operation: MemoryFeedbackOperation,
        *,
        feedback_text: str,
        replacement_text: str | None,
        replacement_subject: str | None,
        replacement_predicate: str | None,
        replacement_object: str | None,
        expires_at: str | None,
    ) -> tuple[LifecycleStatus, str | None]:
        fact = self.graph.get(fact_id)
        if operation == "keep":
            result = self.transition_fact(fact.id, LifecycleStatus.ACTIVE, reason="user_kept_memory")
            return result.to_status, None
        if operation == "reject_candidate":
            raise MemoryLifecycleTransitionError("reject_candidate_requires_candidate_target")
        if operation == "forget":
            result = self.transition_fact(fact.id, LifecycleStatus.FORGOTTEN, reason="user_forget_memory")
            return result.to_status, None
        if operation == "mark_stale":
            result = self.transition_fact(fact.id, LifecycleStatus.STALE, reason="user_marked_stale")
            return result.to_status, None
        if operation == "mark_completed":
            completed = self.mark_fact_completed(fact.id)
            return _fact_lifecycle_status(completed.status), None
        if operation == "edit":
            replacement = self._create_replacement_fact(
                fact,
                feedback_text=feedback_text,
                replacement_text=replacement_text,
                replacement_subject=replacement_subject,
                replacement_predicate=replacement_predicate,
                replacement_object=replacement_object,
            )
            old, _ = self.supersede_fact(fact.id, replacement.id, reason="user_edited_memory", allow_boundary_override=True)
            return _fact_lifecycle_status(old.status), replacement.id
        if operation == "make_temporary":
            updated = self._make_fact_temporary(fact, expires_at)
            return _fact_lifecycle_status(updated.status), None
        raise MemoryLifecycleTransitionError("invalid_memory_feedback_operation")

    def _create_replacement_candidate(
        self,
        old: MemoryCandidateRecord,
        replacement_text: str | None,
    ) -> MemoryCandidateRecord:
        text = _required_text(replacement_text, "edit_requires_replacement_text")
        replacement = self.candidates.create_candidate(
            MemoryCandidateCreate(
                memory_kind=old.memory_kind,
                memory_scope=old.memory_scope,
                summary=text,
                normalized_value=text.casefold(),
                source_text=text,
                source_track=SourceTrack.EXPLICIT_USER,
                risk_tier=old.risk_tier,
                confidence=max(old.confidence, 0.8),
                importance=old.importance,
                status=LifecycleStatus.ACTIVE,
                expires_at=old.expires_at,
                metadata={"edited_from": old.id},
            )
        )
        if replacement.id == old.id:
            raise MemoryLifecycleTransitionError("edit_replacement_must_change_memory")
        return replacement

    def _create_replacement_fact(
        self,
        old: MemoryGraphFact,
        *,
        feedback_text: str,
        replacement_text: str | None,
        replacement_subject: str | None,
        replacement_predicate: str | None,
        replacement_object: str | None,
    ) -> MemoryGraphFact:
        object_value = replacement_object or replacement_text
        replacement = self.graph.insert_candidate(
            MemoryFactCandidate(
                category=old.category,
                subject=replacement_subject or old.subject,
                predicate=replacement_predicate or old.predicate,
                object=_required_text(object_value, "edit_requires_replacement_text"),
                source_text=feedback_text or replacement_text or object_value or "",
                source_type="user_feedback",
                confidence=max(old.confidence, 0.8),
                conversation_id=old.conversation_id,
                user_message_id=old.user_message_id,
                agent_run_id=old.agent_run_id,
                memory_type=old.memory_type,
                entity_type=old.entity_type,
                occurred_at=old.occurred_at,
                expires_at=old.expires_at,
                metadata_json=old.metadata_json,
                importance=old.importance,
            )
        ).fact
        if replacement.id == old.id:
            raise MemoryLifecycleTransitionError("edit_replacement_must_change_memory")
        return replacement

    def _make_candidate_temporary(self, candidate: MemoryCandidateRecord, expires_at: str | None) -> MemoryCandidateRecord:
        expiry = _required_text(expires_at, "make_temporary_requires_expires_at")
        if candidate.status is not LifecycleStatus.ACTIVE:
            self.transition_candidate(candidate.id, LifecycleStatus.ACTIVE, reason="temporary_memory_promoted")
        with self.conn:
            self.conn.execute(
                """
                UPDATE memory_candidates
                SET memory_kind = ?,
                    memory_scope = ?,
                    expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (MemoryKind.RECENT_STATE.value, MemoryScope.TEMPORARY.value, expiry, utc_now_iso(), candidate.id),
            )
        return self.candidates.get_candidate(candidate.id)

    def _make_fact_temporary(self, fact: MemoryGraphFact, expires_at: str | None) -> MemoryGraphFact:
        expiry = _required_text(expires_at, "make_temporary_requires_expires_at")
        if _fact_lifecycle_status(fact.status) is not LifecycleStatus.ACTIVE:
            self.transition_fact(fact.id, LifecycleStatus.ACTIVE, reason="temporary_memory_promoted")
        with self.conn:
            self.conn.execute(
                """
                UPDATE memory_graph_facts
                SET memory_type = ?,
                    expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (MemoryKind.RECENT_STATE.value, expiry, utc_now_iso(), fact.id),
            )
        return self.graph.get(fact.id)


def _validate_transition(
    from_status: LifecycleStatus,
    to_status: LifecycleStatus,
    *,
    superseded_by: str | None,
) -> None:
    if from_status == to_status:
        return
    allowed = {
        LifecycleStatus.CANDIDATE: {
            LifecycleStatus.ACTIVE,
            LifecycleStatus.STALE,
            LifecycleStatus.ARCHIVED,
            LifecycleStatus.FORGOTTEN,
            LifecycleStatus.REJECTED,
            LifecycleStatus.SUPERSEDED,
        },
        LifecycleStatus.ACTIVE: {
            LifecycleStatus.STALE,
            LifecycleStatus.ARCHIVED,
            LifecycleStatus.FORGOTTEN,
            LifecycleStatus.REJECTED,
            LifecycleStatus.SUPERSEDED,
        },
        LifecycleStatus.STALE: {
            LifecycleStatus.ACTIVE,
            LifecycleStatus.ARCHIVED,
            LifecycleStatus.FORGOTTEN,
            LifecycleStatus.REJECTED,
            LifecycleStatus.SUPERSEDED,
        },
    }
    if to_status not in allowed.get(from_status, set()):
        raise MemoryLifecycleTransitionError(f"invalid_lifecycle_transition:{from_status.value}->{to_status.value}")
    if to_status is LifecycleStatus.SUPERSEDED and not superseded_by:
        raise MemoryLifecycleTransitionError("superseded_transition_requires_replacement")


def _coerce_lifecycle_status(status: LifecycleStatus | MemoryFactStatus | str) -> LifecycleStatus:
    if isinstance(status, LifecycleStatus):
        return status
    if isinstance(status, MemoryFactStatus):
        return _fact_lifecycle_status(status)
    if str(status) == MemoryFactStatus.QUARANTINED.value:
        return LifecycleStatus.CANDIDATE
    return LifecycleStatus(str(status))


def _coerce_fact_status(status: LifecycleStatus | MemoryFactStatus | str) -> MemoryFactStatus:
    if isinstance(status, MemoryFactStatus):
        return status
    if isinstance(status, LifecycleStatus):
        return MemoryFactStatus(status.value)
    return MemoryFactStatus(str(status))


def _validate_fact_transition(
    from_status: LifecycleStatus,
    to_status: LifecycleStatus,
    *,
    superseded_by: str | None,
) -> None:
    # Explicit fact moderation may restore archived or rejected facts. Candidate
    # transitions intentionally retain the stricter no-restore policy.
    if from_status in {LifecycleStatus.ARCHIVED, LifecycleStatus.REJECTED} and to_status is LifecycleStatus.ACTIVE:
        return
    _validate_transition(from_status, to_status, superseded_by=superseded_by)


def _fact_lifecycle_status(status: MemoryFactStatus) -> LifecycleStatus:
    if status is MemoryFactStatus.QUARANTINED:
        return LifecycleStatus.CANDIDATE
    if status in {MemoryFactStatus.WRONG, MemoryFactStatus.SENSITIVE_BLOCKED}:
        return LifecycleStatus.REJECTED
    return LifecycleStatus(status.value)


def _ensure_boundary_can_be_superseded(*, old_kind: MemoryKind, replacement_kind: MemoryKind, allow: bool) -> None:
    if old_kind is MemoryKind.BOUNDARY and replacement_kind is not MemoryKind.BOUNDARY and not allow:
        raise MemoryLifecycleTransitionError("boundary_memory_requires_explicit_boundary_override")


def _fact_memory_kind(fact: MemoryGraphFact) -> MemoryKind:
    for raw in (fact.memory_type, fact.category):
        if not raw:
            continue
        try:
            return MemoryKind(str(raw))
        except ValueError:
            continue
    return MemoryKind.FACT


def _fact_is_project_context(fact: MemoryGraphFact) -> bool:
    return _fact_memory_kind(fact) is MemoryKind.PROJECT_CONTEXT or fact.category == "project_context"


def _feedback_type(operation: MemoryFeedbackOperation) -> str:
    if operation == "edit":
        return "correction"
    return operation


def _feedback_metadata(
    *,
    operation: MemoryFeedbackOperation,
    replacement_target_id: str | None,
    expires_at: str | None,
) -> dict[str, object]:
    metadata: dict[str, object] = {"operation": operation}
    if replacement_target_id:
        metadata["replacement_target_id"] = replacement_target_id
    if expires_at:
        metadata["expires_at"] = expires_at
    return metadata


def _required_text(value: str | None, error_code: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise MemoryLifecycleTransitionError(error_code)
    return text


def _existing_source_id(conn: sqlite3.Connection, table: Literal["conversations", "messages", "agent_runs"], value: str | None) -> str | None:
    if not value:
        return None
    row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (value,)).fetchone()
    return value if row is not None else None
