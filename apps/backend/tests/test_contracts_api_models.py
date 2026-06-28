import pytest
from pydantic import ValidationError

from app.models.api import HealthResponse
from app.models.common import ErrorResponse
from app.models.enums import (
    AgentRunStatus,
    AuditResult,
    ConversationStatus,
    IndexJobStatus,
    MemoryProposalStatus,
    MessageStatus,
    NoteStatus,
    ReminderStatus,
    TaskStatus,
    ToolCallStatus,
)
from app.models.visible_continuity import (
    VisibleContinuityPlaybackPreview,
    VisibleContinuitySnapshotResponse,
    VisibleContinuityTodayCard,
)


def enum_values(enum_type: type) -> set[str]:
    return {member.value for member in enum_type}


def test_health_response_contract_excludes_sensitive_runtime_state() -> None:
    forbidden_fields = {
        "active_vault_id",
        "vault_id",
        "vault_path",
        "root_path",
            "model_provider",
            "model_base_url",
            "chat_model",
        "model_config",
        "api_key",
        "token",
        "authorization",
        "username",
    }

    assert set(HealthResponse.model_fields).isdisjoint(forbidden_fields)

    response = HealthResponse.model_validate(
        {
            "status": "ok",
            "version": "0.0.1-alpha",
            "database": "ok",
            "active_vault_id": "must-not-leak",
            "root_path": "%USERPROFILE%/PetMemoryVault",
            "model_provider": "openai-compatible",
        }
    )

    dumped = response.model_dump()
    assert dumped == {"status": "ok", "version": "0.0.1-alpha", "database": "ok", "components": {}}
    assert set(dumped).isdisjoint(forbidden_fields)


def test_error_response_contract_requires_documented_shape() -> None:
    response = ErrorResponse.model_validate(
        {
            "error": {
                "code": "vault_path_denied",
                "message": "Path is outside the authorized vault.",
                "request_id": "req_123",
            }
        }
    )

    assert response.model_dump() == {
        "error": {
            "code": "vault_path_denied",
            "message": "Path is outside the authorized vault.",
            "request_id": "req_123",
            "details": {},
        }
    }

    with pytest.raises(ValidationError):
        ErrorResponse.model_validate(
            {
                "error": {
                    "code": "missing_request_id",
                    "message": "request_id is required by the API error contract.",
                }
            }
        )


def test_visible_continuity_snapshot_model_contract_supports_empty_partial_and_full_shapes() -> None:
    empty = VisibleContinuitySnapshotResponse(
        today_card=VisibleContinuityTodayCard(
            title="Today is ready when you are",
            summary="No recent local activity yet.",
        ),
        playback_preview=VisibleContinuityPlaybackPreview(
            period="weekly",
            title="Weekly playback is warming up",
            summary="Not enough local history yet.",
        ),
    )
    assert empty.recent_receipts == []
    assert empty.project_cards == []
    assert empty.today_card.source_count == 0

    partial = VisibleContinuitySnapshotResponse.model_validate(
        {
            "today_card": {
                "title": "Continue from local context",
                "summary": "Pulled together 1 organization receipt.",
                "carry_over_items": [],
                "suggested_next_steps": ["Review the latest memory receipt if you want to undo anything."],
                "continuation_prompts": ["Review what you organized recently and suggest what to continue."],
                "source_count": 1,
                "updated_at": "2026-06-02T12:00:00Z",
            },
            "recent_receipts": [
                {
                    "action_id": "action-1",
                    "action_type": "chat.daily_archive",
                    "title": "Archived chat diary",
                    "summary": "Wrote a safe diary entry.",
                    "decision": "auto",
                    "risk_tier": "low",
                    "status": "completed",
                    "reversible": False,
                    "reverted_by": None,
                    "reverts_action_id": None,
                    "target_path": "Memories/Daily/2026/06/2026-06-02.md",
                    "created_at": "2026-06-02T12:00:00Z",
                }
            ],
            "project_cards": [],
            "playback_preview": {
                "period": "weekly",
                "title": "Weekly playback is warming up",
                "summary": "Not enough local history yet.",
                "source_count": 0,
            },
        }
    )
    assert partial.recent_receipts[0].decision == "auto"
    assert partial.recent_receipts[0].risk_tier == "low"
    assert partial.recent_receipts[0].status == "completed"

    full = VisibleContinuitySnapshotResponse.model_validate(
        {
            "today_card": {
                "title": "Continue from the latest local context",
                "summary": "Pulled together 2 recent message(s), 1 open task(s), 1 diary memory object(s).",
                "carry_over_items": ["Task: Ship visible continuity", "Agent Pet: Active"],
                "suggested_next_steps": ["Continue Agent Pet from the latest open thread."],
                "continuation_prompts": ["Help me continue this task: Ship visible continuity"],
                "source_count": 4,
                "updated_at": "2026-06-02T13:00:00Z",
            },
            "recent_receipts": [
                {
                    "action_id": "action-2",
                    "action_type": "wiki.answer_summary.write",
                    "title": "Saved Wiki summary",
                    "summary": "Saved a reusable summary.",
                    "decision": "auto",
                    "risk_tier": "low",
                    "status": "completed",
                    "reversible": True,
                    "reverted_by": None,
                    "reverts_action_id": None,
                    "target_path": "Wiki/Companion/Summaries/visible-continuity.md",
                    "created_at": "2026-06-02T12:30:00Z",
                }
            ],
            "project_cards": [
                {
                    "project_id": "agent-pet",
                    "title": "Agent Pet",
                    "current_state": "Active",
                    "recent_progress": "Open task: Ship visible continuity",
                    "next_step": "Continue Agent Pet from the latest open thread.",
                    "blockers": [],
                    "last_touched_at": "2026-06-02T13:00:00Z",
                    "sources": ["tasks:task-1"],
                }
            ],
            "playback_preview": {
                "period": "weekly",
                "title": "Weekly local playback preview",
                "summary": "Found local activity from the last 7 days.",
                "themes": ["visible continuity"],
                "completed": ["Baseline audit"],
                "stuck_points": [],
                "next_focus": ["visible continuity"],
                "source_count": 3,
            },
        }
    )
    assert full.project_cards[0].project_id == "agent-pet"
    assert full.playback_preview.period == "weekly"


@pytest.mark.parametrize(
    ("enum_type", "expected"),
    [
        (ConversationStatus, {"active", "archived"}),
        (MessageStatus, {"partial", "completed", "failed", "cancelled"}),
        (NoteStatus, {"indexed", "deleted", "failed"}),
        (MemoryProposalStatus, {"pending", "confirmed", "rejected", "failed"}),
        (TaskStatus, {"pending", "done", "cancelled"}),
        (ReminderStatus, {"scheduled", "unscheduled", "triggered", "cancelled", "failed"}),
        (IndexJobStatus, {"queued", "running", "success", "failed"}),
        (AgentRunStatus, {"running", "success", "failed", "cancelled"}),
        (ToolCallStatus, {"running", "success", "failed", "denied"}),
        (AuditResult, {"allowed", "denied", "failed"}),
    ],
)
def test_documented_status_enums_are_exact(enum_type: type, expected: set[str]) -> None:
    assert enum_values(enum_type) == expected
