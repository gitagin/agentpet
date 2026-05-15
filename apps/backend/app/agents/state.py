from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.api import MemorySearchResult
from app.models.enums import AgentIntent, AgentRunStatus

from .memory_router import MemoryRoute


class AgentRoute(BaseModel):
    intent: AgentIntent
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class SemanticAnalysisResult(BaseModel):
    needs_context: bool = False
    source_scope: Literal["none", "personal_memory", "diary_objects", "daily_chat", "knowledge_base", "all"] = "none"
    query: str = ""
    answer_style: Literal["casual", "concise", "grounded", "clarifying"] = "casual"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class AgentState(BaseModel):
    conversation_id: str
    message_id: str
    agent_run_id: str
    user_message: str
    status: AgentRunStatus = AgentRunStatus.RUNNING
    route: AgentRoute | None = None
    memory_route: MemoryRoute | None = None
    semantic_analysis: SemanticAnalysisResult | None = None
    citations: list[MemorySearchResult] = Field(default_factory=list)
    response_text: str = ""
    proposal_id: str | None = None
    task_id: str | None = None
    reminder_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def intent(self) -> AgentIntent | None:
        return self.route.intent if self.route else None
