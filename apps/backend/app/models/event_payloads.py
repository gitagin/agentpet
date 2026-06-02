from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


class MemoryProposalActionFields(BaseModel):
    proposal_id: str
    status: str


class AgentMemoryProposalFields(MemoryProposalActionFields):
    target_path: str | None = None


class ContinuityProposalFields(BaseModel):
    proposal_id: str
    kind: Literal["identity", "relationship", "mood", "energy", "open_thread"]
    summary: str
    evidence: str
    confidence: float
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    status: str


class ContextBudgetFields(BaseModel):
    strategy: str
    candidate_count: int
    selected_count: int
    duplicate_drop_count: int = 0
    per_scope_drop_count: int = 0
    budget_drop_count: int = 0
    item_budget: int
    per_scope_limit: int
    char_budget: int
    used_chars: int
    source_counts: dict[str, int] = Field(default_factory=dict)
    selected_scopes: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ContextBudgetData:
    strategy: str
    candidate_count: int
    selected_count: int
    duplicate_drop_count: int
    per_scope_drop_count: int
    budget_drop_count: int
    item_budget: int
    per_scope_limit: int
    char_budget: int
    used_chars: int
    source_counts: dict[str, int]
    selected_scopes: tuple[str, ...]


class AgentActionFields(BaseModel):
    action_id: str
    action_type: str


class AgentActionDecisionFields(AgentActionFields):
    risk_tier: Literal["low", "medium", "high"]
    decision: Literal["auto", "notify", "ask"]
    status: str
    title: str
    summary: str = ""
    target_paths: list[str] = Field(default_factory=list)
    reversible: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)
    source_agent_run_id: str | None = None
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    reverted_by: str | None = None
    reverts_action_id: str | None = None
    error: str | None = None
    source: dict[str, str] = Field(default_factory=dict)
    diff_summary: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class TaskCreateFields(BaseModel):
    task_id: str
    reminder_id: str | None = None
    status: str


class AgentTaskFields(TaskCreateFields):
    title: str | None = None
    reminder_status: str | None = None
    remind_at: str | None = None
    timezone: str | None = None
    timezone_label: str | None = None


class WikiProposalCoreFields(BaseModel):
    status: str
    title: str
    markdown_preview: str = ""
    source_message_id: str | None = None


class WikiTargetProposalFields(WikiProposalCoreFields):
    target_path: str


class AgentWikiProposalFields(WikiProposalCoreFields):
    proposal_type: Literal["ingest", "query_archive", "synthesize", "lint"] = "ingest"
    run_id: str | None = None
    source_id: str | None = None
    source_hash: str | None = None
    review_id: str | None = None
    review_status: str | None = None
    summary: str = ""
    review_summary: str = ""
    target_paths: list[str] = Field(default_factory=list)
    recommended_targets: list[str] = Field(default_factory=list)
    findings: list[dict[str, object]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    lint_summary: dict[str, object] = Field(default_factory=dict)
    write_report: bool | None = None
