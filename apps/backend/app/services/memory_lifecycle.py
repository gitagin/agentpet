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
    _candidate_hash,
)
from app.services.memory_graph import MemoryGraphFact
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, SourceTrack, fact_lifecycle_status
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
    def __init__(self, db: str | Path | sqlite3.Connection) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.candidates = MemoryCandidateStore(self.conn)
        self.entity_graph = MemoryEntityGraphStore(self.conn)
        self._graph = self.entity_graph.graph

    @property
    def graph(self) -> MemoryEntityGraphStore:
        return self.entity_graph

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
                agent_action_id=agent_action_id,
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
        _sync_linked_fact: bool = True,
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
        if _sync_linked_fact:
            self._sync_linked_fact_status(
                candidate,
                target=target,
                reason=reason,
                superseded_by=superseded_by,
            )
        return MemoryLifecycleTransitionResult(
            target_type="candidate",
            target_id=candidate.id,
            from_status=candidate.status,
            to_status=target,
            reason=reason,
            superseded_by=superseded_by,
        )

    def _sync_linked_fact_status(
        self,
        candidate: MemoryCandidateRecord,
        *,
        target: LifecycleStatus,
        reason: str,
        superseded_by: str | None,
    ) -> None:
        fact_id = candidate.fact_id
        if not fact_id:
            return
        replacement_fact_id = None
        if superseded_by:
            replacement = self.candidates.get_candidate(superseded_by)
            replacement_fact_id = replacement.fact_id
            if replacement_fact_id is None:
                return
        fact_status = _candidate_status_to_fact_status(target)
        self.transition_fact(
            fact_id,
            fact_status,
            reason=reason,
            superseded_by=replacement_fact_id,
            _sync_candidates=False,
        )

    def transition_fact(
        self,
        fact_id: str,
        to_status: LifecycleStatus | MemoryFactStatus | str,
        *,
        reason: str,
        superseded_by: str | None = None,
        agent_action_id: str | None = None,
        _sync_candidates: bool = True,
    ) -> MemoryLifecycleTransitionResult:
        fact_target = _coerce_fact_status(to_status)
        target = fact_lifecycle_status(fact_target)
        fact = self._graph.get(fact_id)
        current = fact_lifecycle_status(fact.status)
        _validate_fact_transition(current, target, superseded_by=superseded_by)
        previous_event_rowid = int(
            self.conn.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM memory_lifecycle_events WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()[0]
        )
        with self.entity_graph.atomic():
            self.entity_graph.update_status(
                fact.id,
                fact_target,
                reason=reason,
                lifecycle_metadata=(
                    {"replacement_fact_id": superseded_by}
                    if superseded_by
                    else None
                ),
            )
            if fact_target is MemoryFactStatus.ACTIVE:
                # 事实激活后，其 subject/object 实体若仍是候选态，会卡住召回门
                # （claim 继承 subject 实体的生命周期），导致确认后节点从投影消失。
                self.entity_graph.activate_fact_endpoints(fact.id, reason=reason)
        if agent_action_id is not None:
            events = self.conn.execute(
                """
                SELECT id
                FROM memory_lifecycle_events
                WHERE fact_id = ?
                  AND to_status = ?
                  AND reason = ?
                  AND rowid > ?
                ORDER BY created_at, id
                """,
                (
                    fact_id,
                    target.value,
                    reason,
                    previous_event_rowid,
                ),
            ).fetchall()
            if len(events) != 1:
                raise MemoryLifecycleTransitionError("fact_lifecycle_event_binding_ambiguous")
            with self.conn:
                self.conn.execute(
                    "UPDATE memory_lifecycle_events SET agent_action_id = ? WHERE id = ?",
                    (agent_action_id, str(events[0][0])),
                )
        if _sync_candidates:
            self._sync_linked_candidates(
                fact.id,
                target=target,
                reason=reason,
            )
        return MemoryLifecycleTransitionResult(
            target_type="fact",
            target_id=fact.id,
            from_status=current,
            to_status=target,
            reason=reason,
            superseded_by=superseded_by,
        )

    def _sync_linked_candidates(
        self,
        fact_id: str,
        *,
        target: LifecycleStatus,
        reason: str,
    ) -> None:
        rows = self.conn.execute(
            "SELECT id, status FROM memory_candidates WHERE fact_id = ?",
            (fact_id,),
        ).fetchall()
        for row in rows:
            current = LifecycleStatus(str(row["status"]))
            if current is target:
                continue
            # 事实恢复（如 ARCHIVED→ACTIVE）不能把终态候选（rejected/forgotten/
            # archived/superseded）强行复活——那会绕过"候选不可恢复"策略。
            try:
                _validate_transition(current, target, superseded_by=None)
            except MemoryLifecycleTransitionError:
                continue
            self.candidates.transition(
                candidate_id=str(row["id"]),
                to_status=target,
                reason=reason,
                metadata={"trigger": "linked_fact", "fact_id": fact_id},
            )

    def mark_candidate_completed(self, candidate_id: str, *, reason: str = "user_marked_completed") -> MemoryCandidateRecord:
        candidate = self.candidates.get_candidate(candidate_id)
        if candidate.memory_kind is not MemoryKind.PROJECT_CONTEXT:
            raise MemoryLifecycleTransitionError("only_project_context_can_be_marked_completed")
        target = LifecycleStatus.ARCHIVED if candidate.status in {LifecycleStatus.ACTIVE, LifecycleStatus.STALE} else LifecycleStatus.REJECTED
        self.transition_candidate(candidate.id, target, reason=reason)
        return self.candidates.get_candidate(candidate.id)

    def mark_fact_completed(self, fact_id: str, *, reason: str = "user_marked_completed") -> MemoryGraphFact:
        fact = self._graph.get(fact_id)
        if not _fact_is_project_context(fact):
            raise MemoryLifecycleTransitionError("only_project_context_can_be_marked_completed")
        self.transition_fact(fact.id, LifecycleStatus.ARCHIVED, reason=reason)
        return self._graph.get(fact.id)

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
        if old.fact_id and not replacement.fact_id:
            raise MemoryLifecycleTransitionError("replacement_candidate_fact_required")
        if replacement.status is LifecycleStatus.CANDIDATE:
            self.transition_candidate(replacement.id, LifecycleStatus.ACTIVE, reason="replacement_promoted")
            replacement = self.candidates.get_candidate(replacement.id)
        if old.status is LifecycleStatus.SUPERSEDED:
            if old.superseded_by != replacement.id:
                raise MemoryLifecycleTransitionError("candidate_supersession_conflict")
            if old.fact_id and replacement.fact_id:
                self.supersede_fact(
                    old.fact_id,
                    replacement.fact_id,
                    reason=reason,
                    allow_boundary_override=allow_boundary_override,
                    _sync_candidates=False,
                )
            return old, replacement
        if old.fact_id and replacement.fact_id:
            self.supersede_fact(
                old.fact_id,
                replacement.fact_id,
                reason=reason,
                allow_boundary_override=allow_boundary_override,
                _sync_candidates=False,
            )
            self.transition_candidate(
                old.id,
                LifecycleStatus.SUPERSEDED,
                reason=reason,
                superseded_by=replacement.id,
                _sync_linked_fact=False,
            )
        else:
            self.transition_candidate(
                old.id,
                LifecycleStatus.SUPERSEDED,
                reason=reason,
                superseded_by=replacement.id,
            )
        return self.candidates.get_candidate(old.id), self.candidates.get_candidate(replacement.id)

    def supersede_fact(
        self,
        old_fact_id: str,
        replacement_fact_id: str,
        *,
        reason: str = "new_memory_supersedes_old",
        allow_boundary_override: bool = False,
        _sync_candidates: bool = True,
    ) -> tuple[MemoryGraphFact, MemoryGraphFact]:
        old = self._graph.get(old_fact_id)
        replacement = self._graph.get(replacement_fact_id)
        _ensure_boundary_can_be_superseded(
            old_kind=_fact_memory_kind(old),
            replacement_kind=_fact_memory_kind(replacement),
            allow=allow_boundary_override,
        )
        if fact_lifecycle_status(old.status) is LifecycleStatus.SUPERSEDED:
            if old.superseded_by != replacement.id:
                raise MemoryLifecycleTransitionError("fact_supersession_conflict")
            return old, replacement
        with self.entity_graph.atomic():
            if fact_lifecycle_status(replacement.status) is LifecycleStatus.CANDIDATE:
                self.transition_fact(replacement.id, LifecycleStatus.ACTIVE, reason="replacement_promoted")
            self.entity_graph.create_relation(
                relation_type="supersedes",
                subject_fact_id=replacement.id,
                object_fact_id=old.id,
                source_text=reason,
                source_type="user_feedback",
                confidence=1.0,
                evidence_id=f"supersedes-{replacement.id}-{old.id}",
            )
            self.transition_fact(
                old.id,
                LifecycleStatus.SUPERSEDED,
                reason=reason,
                superseded_by=replacement.id,
                _sync_candidates=_sync_candidates,
            )
            self.entity_graph.archive_resolved_contradictions(
                old.id,
                reason="resolved_by_supersession",
            )
        return self._graph.get(old.id), self._graph.get(replacement.id)

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
                replacement_object=replacement_object,
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
        replacement_object: str | None,
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
            replacement_value = replacement_text or replacement_object
            replacement = self._create_replacement_candidate(candidate, replacement_value)
            if candidate.fact_id:
                replacement_fact = self._create_replacement_fact(
                    self._graph.get(candidate.fact_id),
                    feedback_text=feedback_text,
                    replacement_text=replacement_value,
                    replacement_subject=None,
                    replacement_predicate=None,
                    replacement_object=None,
                )
                replacement = self.candidates.attach_fact(replacement.id, replacement_fact.id)
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
        fact = self._graph.get(fact_id)
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
            return fact_lifecycle_status(completed.status), None
        if operation == "edit":
            replacement = self._create_replacement_fact(
                fact,
                feedback_text=feedback_text,
                replacement_text=replacement_text,
                replacement_subject=replacement_subject,
                replacement_predicate=replacement_predicate,
                replacement_object=replacement_object,
            )
            linked_candidates = self._linked_candidates(fact.id)
            if linked_candidates:
                replacement_value = replacement_object or replacement_text
                for candidate in linked_candidates:
                    replacement_candidate = self._create_replacement_candidate(
                        candidate,
                        replacement_value,
                    )
                    replacement_candidate = self.candidates.attach_fact(
                        replacement_candidate.id,
                        replacement.id,
                    )
                    if replacement_candidate.fact_id != replacement.id:
                        raise MemoryLifecycleTransitionError(
                            "replacement_candidate_fact_conflict"
                        )
                    self.supersede_candidate(
                        candidate.id,
                        replacement_candidate.id,
                        reason="user_edited_memory",
                        allow_boundary_override=True,
                    )
                old = self._graph.get(fact.id)
            else:
                old, _ = self.supersede_fact(
                    fact.id,
                    replacement.id,
                    reason="user_edited_memory",
                    allow_boundary_override=True,
                )
            return fact_lifecycle_status(old.status), replacement.id
        if operation == "make_temporary":
            updated = self._make_fact_temporary(fact, expires_at)
            return fact_lifecycle_status(updated.status), None
        raise MemoryLifecycleTransitionError("invalid_memory_feedback_operation")

    def _linked_candidates(self, fact_id: str) -> tuple[MemoryCandidateRecord, ...]:
        rows = self.conn.execute(
            "SELECT id FROM memory_candidates WHERE fact_id = ? ORDER BY created_at, id",
            (fact_id,),
        ).fetchall()
        return tuple(self.candidates.get_candidate(str(row[0])) for row in rows)

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
        value = _required_text(object_value, "edit_requires_replacement_text")
        subject = replacement_subject or old.subject
        predicate = replacement_predicate or old.predicate
        entity_id = old.subject_entity_id
        if entity_id is None:
            entity_type = old.entity_type if old.entity_type in {
                "self", "person", "project", "preference", "boundary", "goal", "event", "concept", "source", "wiki_page", "decision"
            } else "concept"
            matches = self.entity_graph.find_candidates(entity_type=entity_type, name=subject)
            if len(matches) > 1:
                raise MemoryLifecycleTransitionError("edit_subject_ambiguous")
            entity_id = matches[0].id if matches else self.entity_graph.create_entity(
                entity_type=entity_type,
                canonical_name=subject,
                confidence=max(old.confidence, 0.8),
            ).id
        replacement = self.entity_graph.create_claim(
            subject_entity_id=entity_id,
            predicate=predicate,
            literal_value=value,
            category=old.category,
            source_text=feedback_text or replacement_text or value,
            source_type="user_feedback",
            confidence=max(old.confidence, 0.8),
            evidence_id=f"evidence-feedback-{old.id}-{entity_id}",
        )
        if replacement.id == old.id:
            raise MemoryLifecycleTransitionError("edit_replacement_must_change_memory")
        return replacement

    def _make_candidate_temporary(self, candidate: MemoryCandidateRecord, expires_at: str | None) -> MemoryCandidateRecord:
        expiry = _required_text(expires_at, "make_temporary_requires_expires_at")
        if candidate.status is not LifecycleStatus.ACTIVE:
            self.transition_candidate(candidate.id, LifecycleStatus.ACTIVE, reason="temporary_memory_promoted")
        new_kind = MemoryKind.RECENT_STATE
        new_scope = MemoryScope.TEMPORARY
        new_hash = _candidate_hash(
            kind=new_kind,
            scope=new_scope,
            summary=candidate.summary,
            normalized_value=candidate.normalized_value,
            source_track=candidate.source_track,
            source_text_hash=candidate.source_text_hash,
        )
        with self.conn:
            self.conn.execute(
                """
                UPDATE memory_candidates
                SET memory_kind = ?,
                    memory_scope = ?,
                    expires_at = ?,
                    candidate_hash = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (new_kind.value, new_scope.value, expiry, new_hash, utc_now_iso(), candidate.id),
            )
        return self.candidates.get_candidate(candidate.id)

    def _make_fact_temporary(self, fact: MemoryGraphFact, expires_at: str | None) -> MemoryGraphFact:
        expiry = _required_text(expires_at, "make_temporary_requires_expires_at")
        if fact_lifecycle_status(fact.status) is not LifecycleStatus.ACTIVE:
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
        return self._graph.get(fact.id)


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
        return fact_lifecycle_status(status)
    if str(status) == MemoryFactStatus.QUARANTINED.value:
        return LifecycleStatus.CANDIDATE
    return LifecycleStatus(str(status))


def _coerce_fact_status(status: LifecycleStatus | MemoryFactStatus | str) -> MemoryFactStatus:
    if isinstance(status, MemoryFactStatus):
        return status
    if isinstance(status, LifecycleStatus):
        return MemoryFactStatus(status.value)
    return MemoryFactStatus(str(status))


def _candidate_status_to_fact_status(status: LifecycleStatus) -> MemoryFactStatus:
    try:
        return MemoryFactStatus(status.value)
    except ValueError as exc:
        raise MemoryLifecycleTransitionError(
            f"candidate_status_not_supported_by_fact:{status.value}"
        ) from exc


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
