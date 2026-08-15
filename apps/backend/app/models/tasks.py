from typing import Literal

from pydantic import BaseModel, Field

from .event_payloads import TaskCreateFields


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    due_at: str | None = None
    remind_at: str | None = None
    timezone: str | None = None
    source_text: str | None = None


class TaskCreateResponse(TaskCreateFields):
    metadata: dict[str, str] = Field(default_factory=dict)


class TaskListResponse(BaseModel):
    tasks: list[dict[str, str]] = Field(default_factory=list)


class TaskWorkspaceItem(BaseModel):
    task_id: str
    title: str
    description: str = ""
    status: str
    due_at: str = ""
    source_text: str = ""
    needs_approval: bool = False
    approval_action: str = ""


class CurrentTaskResponse(BaseModel):
    task: TaskWorkspaceItem | None = None


class TaskStepItem(BaseModel):
    index: int
    tool_name: str
    status: str
    duration_ms: int = 0


class TaskStepsResponse(BaseModel):
    steps: list[TaskStepItem] = Field(default_factory=list)


class TaskLogItem(BaseModel):
    timestamp: str
    content: str


class TaskLogsResponse(BaseModel):
    logs: list[TaskLogItem] = Field(default_factory=list)


class TaskApprovalResponse(BaseModel):
    task_id: str
    status: str
    approved: bool = False
    rejected: bool = False


class ReminderDeliveryReserveRequest(BaseModel):
    reminder_id: str = Field(min_length=1, max_length=512)
    trigger_at: str = Field(min_length=1, max_length=512)
    dispatch_kind: Literal["automatic", "manual"] = "automatic"


class ReminderDeliveryResultRequest(BaseModel):
    result_code: Literal["shown", "unsupported", "failed"]
    error: str | None = Field(default=None, max_length=500)


class ReminderDeliveryAttemptResponse(BaseModel):
    attempt_id: str
    reminder_id: str
    trigger_at: str
    dispatch_kind: Literal["automatic", "manual"]
    idempotency_key: str
    status: Literal["reserved", "display_invoked", "unknown_after_crash", "unsupported", "failed"]
    reserved_at: str
    display_invoked_at: str | None = None
    result_code: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    duplicate: bool = False


class ReminderRuntimeRecoveryResponse(BaseModel):
    unknown_attempts: int = Field(ge=0)
    recovered_reminders: int = Field(ge=0)
