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
