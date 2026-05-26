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
