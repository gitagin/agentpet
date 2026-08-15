from __future__ import annotations

import sqlite3
from collections.abc import Callable
import json

from app.models.memory import MemoryFeedbackRequest
from app.services.memory_lifecycle import MemoryFeedbackApplyResult, MemoryLifecycleService


class MemoryFeedbackService:
    """Apply and read one deterministic memory lifecycle transition.

    The action lifecycle owns the claim and receipt. This service only owns the
    domain effect and its observational metric events, so a caller cannot
    record an activity row after an uncoordinated write.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        lifecycle_factory: Callable[[], MemoryLifecycleService],
        metric_recorder: Callable[..., object] | None = None,
        correction_recorder: Callable[..., object] | None = None,
    ) -> None:
        self._conn = conn
        self._lifecycle_factory = lifecycle_factory
        self._metric_recorder = metric_recorder
        self._correction_recorder = correction_recorder

    def apply_effect(
        self,
        request: MemoryFeedbackRequest,
        *,
        agent_action_id: str,
    ) -> MemoryFeedbackApplyResult:
        lifecycle = self._lifecycle_factory()
        try:
            result = lifecycle.apply_feedback(
                target_type=request.target_type,
                target_id=request.target_id,
                operation=request.operation,
                feedback_text=request.feedback_text,
                replacement_text=request.replacement_text,
                replacement_subject=request.replacement_subject,
                replacement_predicate=request.replacement_predicate,
                replacement_object=request.replacement_object,
                expires_at=request.expires_at,
                source_conversation_id=request.source_conversation_id,
                source_message_id=request.source_message_id,
                source_agent_run_id=request.source_agent_run_id,
                agent_action_id=agent_action_id,
            )
        finally:
            lifecycle.close()

        if self._metric_recorder is not None or self._correction_recorder is not None:
            try:
                if self._metric_recorder is not None:
                    self._metric_recorder(
                        event_type="feedback_recorded",
                        idempotency_key=f"memory-feedback:{result.feedback_event_id}",
                        subject_id=request.target_id,
                        dimensions={"feedback": _metric_feedback_type(result.operation), "status": result.status.value},
                    )
                if result.operation == "edit":
                    self._record_correction(request, result.feedback_event_id, result.replacement_target_id)
                elif result.operation == "forget" and self._metric_recorder is not None:
                    self._metric_recorder(
                        event_type="forgotten",
                        idempotency_key=f"memory-forgotten:{result.feedback_event_id}",
                        subject_id=request.target_id,
                    )
            except Exception:
                # Metrics are observational and must never block a lifecycle
                # transition or its receipt.
                pass
        return result

    def read_effect(
        self,
        *,
        feedback_event_id: str | None,
        target_type: str,
        target_id: str,
        operation: str,
        agent_action_id: str,
    ) -> dict[str, object] | None:
        """Return a redacted authoritative projection for lifecycle recovery."""
        target_column = "candidate_id" if target_type == "candidate" else "fact_id"
        query = f"""
            SELECT id, candidate_id, fact_id, feedback_type, requested_status,
                   replacement_candidate_id, agent_action_id, metadata_json
            FROM memory_feedback_events
            WHERE agent_action_id = ?
              AND {target_column} = ?
        """
        parameters: list[object] = [agent_action_id, target_id]
        if feedback_event_id:
            query += " AND id = ?"
            parameters.append(feedback_event_id)
        rows = self._conn.execute(f"{query} ORDER BY created_at, id LIMIT 2", parameters).fetchall()
        if len(rows) != 1:
            return None
        row = rows[0]
        feedback_event_id = str(row["id"])
        actual_target_id = str(row["candidate_id"] or row["fact_id"] or "")
        actual_target_type = "candidate" if row["candidate_id"] is not None else "fact"
        if actual_target_type != target_type or actual_target_id != target_id:
            return None
        metadata = _json_object(row["metadata_json"])
        replacement_target_id = row["replacement_candidate_id"]
        if replacement_target_id is None:
            replacement_target_id = metadata.get("replacement_target_id")
        status = str(row["requested_status"] or "")
        if not status or str(row["feedback_type"] or "") not in _feedback_types_for_operation(operation):
            return None
        current_status = self._target_status(target_type, target_id)
        if current_status != status and not (operation == "edit" and current_status == "superseded"):
            return None
        if replacement_target_id:
            replacement_target_id = str(replacement_target_id)
            replacement_status = self._target_status(target_type, replacement_target_id)
            if replacement_status not in {"active", "candidate", "temporary"}:
                return None
        return {
            "target_type": target_type,
            "target_id": target_id,
            "operation": operation,
            "status": status,
            "feedback_event_id": feedback_event_id,
            "replacement_target_id": replacement_target_id,
            "state_ref": f"memory-feedback:{feedback_event_id}",
            "observed_effect": "memory_lifecycle_transition",
        }

    def _target_status(self, target_type: str, target_id: str) -> str | None:
        table = "memory_candidates" if target_type == "candidate" else "memory_graph_facts"
        row = self._conn.execute(f"SELECT status FROM {table} WHERE id = ?", (target_id,)).fetchone()
        return str(row[0]) if row is not None else None

    def _record_correction(
        self,
        request: MemoryFeedbackRequest,
        feedback_event_id: str,
        replacement_target_id: str | None,
    ) -> None:
        correction_recorder = self._correction_recorder
        if correction_recorder is not None:
            correction_recorder(
                idempotency_key=f"memory-correction:{feedback_event_id}",
                old_subject_id=request.target_id,
                replacement_subject_id=replacement_target_id,
            )
            return
        if self._metric_recorder is not None:
            self._metric_recorder(
                event_type="corrected",
                idempotency_key=f"memory-correction:{feedback_event_id}",
                subject_id=request.target_id,
                dimensions={"observation_status": "pending"},
            )


def _metric_feedback_type(operation: str) -> str:
    if operation == "edit":
        return "incorrect"
    if operation in {"forget", "reject_candidate"}:
        return "missing"
    return "helpful"


def _feedback_types_for_operation(operation: str) -> frozenset[str]:
    return {
        "keep": frozenset({"keep"}),
        "edit": frozenset({"correction", "rewrite"}),
        "forget": frozenset({"forget"}),
        "make_temporary": frozenset({"make_temporary"}),
        "mark_completed": frozenset({"mark_completed"}),
        "mark_stale": frozenset({"mark_stale"}),
        "reject_candidate": frozenset({"reject_candidate"}),
    }.get(operation, frozenset())


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
