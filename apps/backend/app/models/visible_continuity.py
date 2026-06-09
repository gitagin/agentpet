from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VisibleContinuityTodayCard(BaseModel):
    title: str
    summary: str
    carry_over_items: list[str] = Field(default_factory=list)
    suggested_next_steps: list[str] = Field(default_factory=list)
    continuation_prompts: list[str] = Field(default_factory=list)
    source_count: int = 0
    updated_at: str | None = None


class VisibleContinuityReceipt(BaseModel):
    action_id: str
    action_type: str
    title: str
    summary: str
    decision: Literal["auto", "notify", "ask"]
    risk_tier: Literal["low", "medium", "high"]
    status: str = "completed"
    reversible: bool
    reverted_by: str | None = None
    reverts_action_id: str | None = None
    target_path: str | None = None
    created_at: str


class VisibleContinuityProjectCard(BaseModel):
    project_id: str
    title: str
    current_state: str
    recent_progress: str
    next_step: str
    blockers: list[str] = Field(default_factory=list)
    last_touched_at: str | None = None
    sources: list[str] = Field(default_factory=list)


class VisibleContinuityPlaybackPreview(BaseModel):
    period: Literal["weekly", "monthly"]
    title: str
    summary: str
    themes: list[str] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)
    stuck_points: list[str] = Field(default_factory=list)
    next_focus: list[str] = Field(default_factory=list)
    source_count: int = 0


class VisibleContinuitySnapshotResponse(BaseModel):
    today_card: VisibleContinuityTodayCard
    recent_receipts: list[VisibleContinuityReceipt] = Field(default_factory=list)
    project_cards: list[VisibleContinuityProjectCard] = Field(default_factory=list)
    playback_preview: VisibleContinuityPlaybackPreview
