from __future__ import annotations

import sqlite3
from collections.abc import Callable

from app.models.memory import AgentActionResponse, MemoryFeedbackRequest, MemoryFeedbackResponse
from app.models.common import new_id
from app.services.agent_actions import AgentActionCreate
from app.services.memory_lifecycle import MemoryLifecycleService


class MemoryFeedbackService:
    """Applies feedback, links its event, and records one reversible-action entry."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        lifecycle_factory: Callable[[], MemoryLifecycleService],
        action_recorder: Callable[[AgentActionCreate], AgentActionResponse],
    ) -> None:
        self._conn = conn
        self._lifecycle_factory = lifecycle_factory
        self._action_recorder = action_recorder

    def apply(self, request: MemoryFeedbackRequest) -> MemoryFeedbackResponse:
        action_id = new_id()
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
            )
        finally:
            lifecycle.close()

        action = self._action_recorder(
            AgentActionCreate(
                action_id=action_id,
                action_type="memory.feedback.apply",
                title="Memory feedback applied",
                summary=f"{result.operation} {result.target_type}:{result.target_id} -> {result.status.value}",
                source_agent_run_id=request.source_agent_run_id,
                source_conversation_id=request.source_conversation_id,
                source_message_id=request.source_message_id,
                risk_tier="low",
                decision="auto",
                status="completed",
                target_paths=(),
                metadata=feedback_action_metadata(request, result),
                reversible=False,
            )
        )
        recorded_action_id = action.action_id
        with self._conn:
            self._conn.execute(
                "UPDATE memory_feedback_events SET agent_action_id = ? WHERE id = ?",
                (recorded_action_id, result.feedback_event_id),
            )
        return MemoryFeedbackResponse(
            target_type=result.target_type,
            target_id=result.target_id,
            operation=result.operation,
            status=result.status.value,
            feedback_event_id=result.feedback_event_id,
            replacement_target_id=result.replacement_target_id,
            action_id=recorded_action_id,
        )


def feedback_action_metadata(request: MemoryFeedbackRequest, result) -> dict[str, object]:
    metadata: dict[str, object] = {
        "operation": result.operation,
        "target_type": result.target_type,
        "target_id": result.target_id,
        "status": result.status.value,
        "feedback_event_id": result.feedback_event_id,
    }
    if result.replacement_target_id:
        metadata["replacement_target_id"] = result.replacement_target_id
    if request.expires_at:
        metadata["expires_at"] = request.expires_at
    if request.replacement_subject:
        metadata["replacement_subject"] = request.replacement_subject
    if request.replacement_predicate:
        metadata["replacement_predicate"] = request.replacement_predicate
    return metadata
