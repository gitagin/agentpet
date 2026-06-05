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
            "version": "1.0",
            "database": "ok",
            "active_vault_id": "must-not-leak",
            "root_path": "D:/PetMemoryVault",
            "model_provider": "openai-compatible",
        }
    )

    dumped = response.model_dump()
    assert dumped == {"status": "ok", "version": "1.0", "database": "ok", "components": {}}
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
