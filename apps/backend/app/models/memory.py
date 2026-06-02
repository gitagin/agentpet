from typing import Literal

from pydantic import BaseModel, Field

from .enums import MemoryProposalType
from .event_payloads import AgentActionDecisionFields, AgentMemoryProposalFields, ContextBudgetFields, ContinuityProposalFields, MemoryProposalActionFields


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1); top_k: int = Field(default=8, ge=1, le=20); mode: str = "hybrid"; source_scope: str = "all"


class MemorySearchResult(BaseModel):
    note_id: str; chunk_id: str; relative_path: str; title: str; heading: str | None = None; snippet: str; score: float; source_scope: str = "knowledge_base"; retrieval_mode: str = "fts"


class MemorySearchResponse(BaseModel):
    results: list[MemorySearchResult]; metadata: dict[str, object] = Field(default_factory=lambda: {"semantic_available": False})


class DiaryMemorySearchRequest(BaseModel):
    query: str = ""; type: str | None = None; topic: str | None = None; emotion: str | None = None; people: list[str] = Field(default_factory=list); min_importance: float | None = Field(default=None, ge=0.0, le=1.0); from_: str | None = Field(default=None, alias="from"); to: str | None = None; top_k: int = Field(default=8, ge=1, le=50)


class DiaryMemorySourceResponse(BaseModel):
    source_type: str; source_id: str; conversation_id: str | None = None; user_message_id: str | None = None; assistant_message_id: str | None = None; agent_run_id: str | None = None; markdown_path: str | None = None; note_id: str | None = None; chunk_id: str | None = None


class DiaryMemoryObjectResponse(BaseModel):
    id: str; vault_id: str; type: str; summary: str; topic: str | None = None; emotion: str | None = None; people: list[str] = Field(default_factory=list); keywords: list[str] = Field(default_factory=list); importance: float; confidence: float; occurred_at: str; timezone: str; status: str; extraction_model: str | None = None; created_at: str; updated_at: str; sources: list[DiaryMemorySourceResponse] = Field(default_factory=list)


class DiaryMemorySearchResponse(BaseModel):
    objects: list[DiaryMemoryObjectResponse] = Field(default_factory=list)


class LocalAssetStatsResponse(BaseModel):
    vault_configured: bool
    vault_id: str | None = None
    chat_diary_days: int = 0
    chat_diary_entries: int = 0
    long_term_memory_count: int = 0
    wiki_page_count: int = 0
    task_count: int = 0
    completed_task_count: int = 0
    latest_organization_at: str | None = None
    reversible_operation_count: int = 0


class MemoryProposalCreateRequest(BaseModel):
    type: MemoryProposalType; content: str = Field(min_length=1); target_path: str; source_message_id: str | None = None


class MemoryProposalActionResponse(MemoryProposalActionFields):
    written_path: str | None = None; index_job_id: str | None = None; action_id: str | None = None


class RejectProposalRequest(BaseModel):
    reason: str = Field(min_length=1)


class MemoryProposalResponse(AgentMemoryProposalFields):
    preview_markdown: str; diff: str | None = None


class MemoryProposalListResponse(BaseModel):
    proposals: list[MemoryProposalResponse] = Field(default_factory=list)


class ContinuityStateItem(BaseModel):
    state_key: str; value: str; confidence: float; source_proposal_id: str | None = None; source_conversation_id: str | None = None; source_message_id: str | None = None; agent_run_id: str | None = None; updated_at: str


class ContinuityStateResponse(BaseModel):
    identity_traits: str | None = None; relationship_summary: str | None = None; current_mood: str | None = None; mood_momentum: str | None = None; energy_level: str | None = None; unresolved_threads: str | None = None; recent_emotional_signals: str | None = None; updated_at: str | None = None; items: list[ContinuityStateItem] = Field(default_factory=list)


class ContinuityProposalResponse(ContinuityProposalFields):
    agent_run_id: str | None = None; rejected_reason: str | None = None; created_at: str; updated_at: str


class ContinuityProposalListResponse(BaseModel):
    proposals: list[ContinuityProposalResponse] = Field(default_factory=list)


class ContinuityProposalActionResponse(MemoryProposalActionFields):
    pass


class AgentActionResponse(AgentActionDecisionFields):
    source_agent_run_id: str | None = None; source_conversation_id: str | None = None; source_message_id: str | None = None; reverted_by: str | None = None; reverts_action_id: str | None = None; error: str | None = None; source: dict[str, str] = Field(default_factory=dict); diff_summary: str = ""; negotiation_rounds: int = 0; total_tokens: int = 0; total_latency_ms: int = 0; created_at: str; updated_at: str; completed_at: str | None = None


class AgentActionListResponse(BaseModel):
    actions: list[AgentActionResponse] = Field(default_factory=list)


class AgentActionRevertResponse(BaseModel):
    action: AgentActionResponse; reverted: AgentActionResponse


class MemoryGraphFactResponse(BaseModel):
    fact_id: str; category: str; subject: str; predicate: str; object: str; status: str; confidence: float; source_text: str; source_type: str; support_count: int = 1; conflicts_with: str | None = None; memory_type: str | None = None; entity_type: str | None = None; occurred_at: str | None = None; expires_at: str | None = None; metadata_json: str | None = None; importance: float = 0.5; created_at: str; updated_at: str


class MemoryGraphExportItem(BaseModel):
    fact_id: str; category: str; subject: str; predicate: str; object: str; status: str; confidence: float; source_type: str; support_count: int = 1; conflicts_with: str | None = None; memory_type: str | None = None; entity_type: str | None = None; occurred_at: str | None = None; expires_at: str | None = None; metadata: dict[str, object] = Field(default_factory=dict); importance: float = 0.5; created_at: str; updated_at: str


class MemoryGraphExportPreviewResponse(BaseModel):
    generated_at: str; format: Literal["json", "markdown"] = "markdown"; item_count: int; items: list[MemoryGraphExportItem] = Field(default_factory=list); json_preview: str; markdown_preview: str; redaction_note: str


class MemoryGraphFactListResponse(BaseModel):
    facts: list[MemoryGraphFactResponse] = Field(default_factory=list)


class MemoryGraphFactActionResponse(BaseModel):
    fact_id: str; status: str


class CompanionConsolidationRunRequest(BaseModel):
    from_: str | None = Field(default=None, alias="from"); to: str | None = None; limit: int = Field(default=50, ge=1, le=200)


class CompanionConsolidationRunResponse(BaseModel):
    run_id: str; status: str; source_count: int; output_count: int; skipped_count: int; reason: str | None = None; fact_ids: list[str] = Field(default_factory=list); started_at: str; completed_at: str | None = None


class CompanionRetrievalReportResponse(ContextBudgetFields):
    id: str; agent_run_id: str; created_at: str


class CompanionRetrievalReportListResponse(BaseModel):
    reports: list[CompanionRetrievalReportResponse] = Field(default_factory=list)
