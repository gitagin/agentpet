from typing import Literal

from pydantic import BaseModel, Field

from .memory import AgentActionResponse
from .wiki import WikiPageResponse


class RetrospectiveSourceReference(BaseModel):
    kind: str
    id: str
    label: str
    path: str | None = None
    created_at: str | None = None


class RetrospectiveTopic(BaseModel):
    name: str
    count: int
    sources: list[RetrospectiveSourceReference] = Field(default_factory=list)


class RetrospectiveDiarySummary(BaseModel):
    id: str
    summary: str
    topic: str | None = None
    source_path: str | None = None
    occurred_at: str


class RetrospectiveMemoryItem(BaseModel):
    id: str
    summary: str
    category: str
    status: str
    confidence: float
    source_path: str | None = None
    created_at: str


class RetrospectiveTaskStats(BaseModel):
    total: int = 0
    completed: int = 0
    pending: int = 0
    cancelled: int = 0
    overdue: int = 0
    sources: list[RetrospectiveSourceReference] = Field(default_factory=list)


class RetrospectiveWikiItem(BaseModel):
    path: str
    title: str
    action_type: str
    created_at: str
    action_id: str | None = None


class RetrospectivePreference(BaseModel):
    name: str
    count: int
    sources: list[RetrospectiveSourceReference] = Field(default_factory=list)


class RetrospectiveWindow(BaseModel):
    days: int
    label: str
    start_at: str
    end_at: str
    summary: dict[str, int] = Field(default_factory=dict)
    topics: list[RetrospectiveTopic] = Field(default_factory=list)
    diary_summaries: list[RetrospectiveDiarySummary] = Field(default_factory=list)
    long_term_memories: list[RetrospectiveMemoryItem] = Field(default_factory=list)
    tasks: RetrospectiveTaskStats = Field(default_factory=RetrospectiveTaskStats)
    wiki_updates: list[RetrospectiveWikiItem] = Field(default_factory=list)
    repeated_preferences: list[RetrospectivePreference] = Field(default_factory=list)
    has_data: bool = False


class RetrospectiveResponse(BaseModel):
    generated_at: str
    windows: list[RetrospectiveWindow] = Field(default_factory=list)


RetrospectiveReportPeriod = Literal["weekly", "monthly"]


class RetrospectiveReportRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    period: RetrospectiveReportPeriod | None = None


class RetrospectiveReportResponse(BaseModel):
    page: WikiPageResponse
    action: AgentActionResponse
    markdown: str
