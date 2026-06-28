from __future__ import annotations

from pydantic import BaseModel, Field

from .config import ProactiveTriggerFrequency


class HabitLoopTriggerRequest(BaseModel):
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class HabitLoopCandidateResponse(BaseModel):
    trigger_id: str
    content_type: str
    title: str
    message: str
    suggested_prompt: str
    source_count: int = 0
    sources: list[str] = Field(default_factory=list)


class HabitLoopTriggerResponse(BaseModel):
    should_trigger: bool
    reason: str
    frequency: ProactiveTriggerFrequency
    daily_limit: int
    daily_count: int
    cooldown_minutes: int
    next_eligible_at: str | None = None
    quiet_hours: str = "22:00-08:00"
    candidate: HabitLoopCandidateResponse | None = None
    action_id: str | None = None
