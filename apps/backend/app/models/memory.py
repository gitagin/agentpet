from typing import Literal

from pydantic import BaseModel, Field

from .enums import MemoryProposalType
from .event_payloads import AgentActionDecisionFields, AgentMemoryProposalFields, ContextBudgetFields, ContinuityProposalFields, MemoryProposalActionFields


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1); top_k: int = Field(default=8, ge=1, le=20); mode: Literal["fts", "vector", "hybrid"] = "fts"; source_scope: Literal["all", "personal_memory", "diary_objects", "daily_chat", "knowledge_base"] = "all"


class MemoryRecallPermissions(BaseModel):
    can_style_response: bool = False
    can_answer_context: bool = True
    can_proactively_mention: bool = False
    can_suggest_action: bool = False


class RetrievalContribution(BaseModel):
    channel: str
    rank: int = Field(ge=1)
    rrf_component: float = Field(gt=0.0)


class MemorySearchResult(BaseModel):
    note_id: str; chunk_id: str; relative_path: str; title: str; heading: str | None = None; snippet: str; score: float; content_hash: str | None = None; source_scope: str = "knowledge_base"; retrieval_mode: str = "fts"; retrieval_channels: list[str] = Field(default_factory=list); channel_ranks: dict[str, int] = Field(default_factory=dict); retrieval_contributions: list[RetrievalContribution] = Field(default_factory=list); recall_permissions: MemoryRecallPermissions = Field(default_factory=MemoryRecallPermissions); activation_score: float | None = None; score_breakdown: dict[str, float] = Field(default_factory=dict); filtered_reason: str | None = None; memory_kind: str | None = None; memory_scope: str | None = None; lifecycle_status: str | None = None; risk_tier: str | None = None; fact_id: str | None = None; candidate_id: str | None = None


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


class GrowthDimensionResponse(BaseModel):
    key: str
    label: str
    level: int = Field(ge=0)
    level_label: str
    current_value: int = Field(ge=0)
    next_threshold: int | None = None
    progress: int = Field(ge=0, le=100)
    description: str
    data_sources: list[str] = Field(default_factory=list)
    last_changed_at: str | None = None


class GrowthEventResponse(BaseModel):
    event_id: str
    occurred_at: str
    dimension_key: str
    title: str
    summary: str = ""
    source_action_id: str
    source_action_type: str
    target_paths: list[str] = Field(default_factory=list)


class GrowthSnapshotResponse(BaseModel):
    generated_at: str
    dimensions: list[GrowthDimensionResponse] = Field(default_factory=list)
    events: list[GrowthEventResponse] = Field(default_factory=list)
    stats: LocalAssetStatsResponse


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
    fact_id: str; category: str; subject: str; predicate: str; object: str; status: str; lifecycle_status: str | None = None; confidence: float; source_text: str; source_type: str; support_count: int = 1; conflicts_with: str | None = None; superseded_by: str | None = None; memory_type: str | None = None; entity_type: str | None = None; occurred_at: str | None = None; expires_at: str | None = None; metadata_json: str | None = None; importance: float = 0.5; created_at: str; updated_at: str


class MemoryGraphExportItem(BaseModel):
    fact_id: str; category: str; subject: str; predicate: str; object: str; status: str; lifecycle_status: str | None = None; confidence: float; source_type: str; support_count: int = 1; conflicts_with: str | None = None; superseded_by: str | None = None; memory_type: str | None = None; entity_type: str | None = None; occurred_at: str | None = None; expires_at: str | None = None; metadata: dict[str, object] = Field(default_factory=dict); importance: float = 0.5; created_at: str; updated_at: str  # noqa: A003 - `object` is the graph-triple field name (API contract); annotation-only names don't shadow the builtin at runtime


class MemoryGraphExportPreviewResponse(BaseModel):
    generated_at: str; format: Literal["json", "markdown"] = "markdown"; item_count: int; items: list[MemoryGraphExportItem] = Field(default_factory=list); json_preview: str; markdown_preview: str; redaction_note: str


class MemoryGraphFactListResponse(BaseModel):
    facts: list[MemoryGraphFactResponse] = Field(default_factory=list)


class MemoryGraphFactActionResponse(BaseModel):
    fact_id: str; status: str


MemoryGraphProjectionNodeType = Literal[
    "user",
    "preference",
    "boundary",
    "project",
    "episode",
    "mood",
    "qa",
    "source",
    "pending",
    "archived",
    "cleanup",
]
MemoryGraphProjectionStatus = Literal["active", "pending", "archived", "hidden"]
MemoryGraphProjectionRiskTier = Literal["low", "hidden"]
MemoryGraphProjectionEdgeType = Literal[
    "related_to",
    "supports",
    "came_from",
    "updates",
    "conflicts_with",
    "belongs_to",
]


class MemoryGraphProjectionNodeResponse(BaseModel):
    id: str
    type: MemoryGraphProjectionNodeType
    label: str
    subtitle: str
    status: MemoryGraphProjectionStatus
    risk_tier: MemoryGraphProjectionRiskTier
    size: float = Field(ge=0.0, le=2.0)
    confidence_label: str
    source_label: str
    updated_at: str
    available_actions: list[str] = Field(default_factory=list)


class MemoryGraphProjectionEdgeResponse(BaseModel):
    id: str
    from_: str = Field(alias="from")
    to: str
    type: MemoryGraphProjectionEdgeType
    strength: float = Field(ge=0.0, le=1.0)


class MemoryGraphProjectionClusterResponse(BaseModel):
    id: str
    label: str
    node_ids: list[str] = Field(default_factory=list)


class MemoryGraphProjectionSummaryResponse(BaseModel):
    total_nodes: int = 0
    pending_count: int = 0
    cleanup_count: int = 0
    hidden_count: int = 0


class MemoryGraphProjectionResponse(BaseModel):
    generated_at: str
    nodes: list[MemoryGraphProjectionNodeResponse] = Field(default_factory=list)
    edges: list[MemoryGraphProjectionEdgeResponse] = Field(default_factory=list)
    clusters: list[MemoryGraphProjectionClusterResponse] = Field(default_factory=list)
    summary: MemoryGraphProjectionSummaryResponse = Field(default_factory=MemoryGraphProjectionSummaryResponse)
    redaction_note: str = "敏感内容、原始证据、授权信息和本机路径不会显示。"


MemoryFeedbackTargetType = Literal["candidate", "fact"]
MemoryFeedbackOperation = Literal[
    "keep",
    "edit",
    "forget",
    "make_temporary",
    "mark_completed",
    "mark_stale",
    "reject_candidate",
]
MemoryReviewCategory = Literal["kept", "temporary", "ignored"]
MemoryReviewAction = Literal["keep", "edit", "forget", "only_this_week", "mark_completed"]


class MemoryFeedbackRequest(BaseModel):
    target_type: MemoryFeedbackTargetType
    target_id: str = Field(min_length=1)
    operation: MemoryFeedbackOperation
    feedback_text: str = ""
    replacement_text: str | None = None
    replacement_subject: str | None = None
    replacement_predicate: str | None = None
    replacement_object: str | None = None
    expires_at: str | None = None
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    source_agent_run_id: str | None = None


class MemoryFeedbackResponse(BaseModel):
    target_type: MemoryFeedbackTargetType
    target_id: str
    operation: MemoryFeedbackOperation
    status: str
    feedback_event_id: str
    replacement_target_id: str | None = None
    action_id: str


class MemoryReviewSummaryResponse(BaseModel):
    kept: int = 0
    temporary: int = 0
    ignored: int = 0


class MemoryReviewItemResponse(BaseModel):
    review_id: str
    target_type: MemoryFeedbackTargetType
    target_id: str
    category: MemoryReviewCategory
    summary: str
    memory_kind: str | None = None
    memory_scope: str | None = None
    lifecycle_status: str
    risk_tier: str | None = None
    confidence: float
    importance: float
    evidence_count: int = 0
    expires_at: str | None = None
    updated_at: str
    source: str
    allowed_actions: list[MemoryReviewAction] = Field(default_factory=list)


class MemoryReviewResponse(BaseModel):
    generated_at: str
    window_days: int
    summary: MemoryReviewSummaryResponse
    items: list[MemoryReviewItemResponse] = Field(default_factory=list)
    redaction_note: str = "Sensitive text, credentials, raw evidence, and full Authorization headers are not included."


class MemoryProfileProjectionItemResponse(BaseModel):
    id: str
    category: str
    summary: str
    confidence: float
    importance: float
    status_label: str
    risk_label: str
    source_label: str
    updated_at: str
    permissions_summary: str
    can_revoke: bool = False
    available_actions: list[str] = Field(default_factory=list)


class MemoryProfileProjectionResponse(BaseModel):
    generated_at: str
    identity: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    preferences: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    boundaries: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    projects: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    relationships: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    recent_state: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    conflicts: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    needs_confirmation: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    filtered: list[MemoryProfileProjectionItemResponse] = Field(default_factory=list)
    redaction_note: str = "敏感内容、原始证据、凭据、完整授权信息和本机绝对路径不会显示在画像里。"


MemoryProfileAction = Literal["forget", "mark_inaccurate", "keep", "make_temporary", "mark_stale"]


class MemoryProfileAvailableActionResponse(BaseModel):
    action: MemoryProfileAction
    label: str
    requires_confirmation: bool = True


class MemoryProfileSourceSummaryResponse(BaseModel):
    label: str
    description: str
    evidence_count_label: str | None = None
    last_seen_label: str | None = None
    safety_note: str | None = None


class MemoryProfileDetailResponse(BaseModel):
    id: str
    summary: str
    category_label: str
    status_label: str
    confidence_label: str
    importance_label: str
    source_label: str
    permissions: list[str] = Field(default_factory=list)
    safety_note: str | None = None
    updated_at: str
    source_summary: MemoryProfileSourceSummaryResponse | None = None
    available_actions: list[MemoryProfileAvailableActionResponse] = Field(default_factory=list)


class MemoryProfileActionRequest(BaseModel):
    action: MemoryProfileAction
    confirmed: bool = False
    expires_at: str | None = None
    feedback_text: str = ""


class MemoryProfileActionResponse(BaseModel):
    ok: bool
    message: str
    item_id: str


class MemoryReceiptItemResponse(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    safety_note: str | None = None
    action_label: str | None = None
    related_memory_id: str | None = None
    created_at: str


class MemoryReceiptResponse(BaseModel):
    generated_at: str
    items: list[MemoryReceiptItemResponse] = Field(default_factory=list)
    redaction_note: str = "回执只显示安全摘要，不显示原始证据、内部编号、凭据或本机绝对路径。"


class MemoryReviewActionRequest(BaseModel):
    target_type: MemoryFeedbackTargetType
    target_id: str = Field(min_length=1)
    action: MemoryReviewAction
    feedback_text: str = ""
    replacement_text: str | None = None
    replacement_subject: str | None = None
    replacement_predicate: str | None = None
    replacement_object: str | None = None


MemoryHygieneSuggestionType = Literal["stale_recent_state", "low_confidence_stale", "sensitive_candidate"]


class MemoryHygieneSuggestionResponse(BaseModel):
    id: str
    type: MemoryHygieneSuggestionType
    title: str
    summary: str
    impact: str
    risk_tier: str
    destructive: bool = False
    requires_confirmation: bool = True
    action_label: str


class MemoryHygienePreviewResponse(BaseModel):
    generated_at: str
    suggestions: list[MemoryHygieneSuggestionResponse] = Field(default_factory=list)
    redaction_note: str = (
        "整理建议不会显示原始证据、内部编号、本地路径、凭据或完整授权信息。"
    )


class MemoryHygieneActionRequest(BaseModel):
    suggestion_id: str = Field(min_length=1)
    confirmed: bool = False


class MemoryHygieneActionResponse(BaseModel):
    ok: bool
    suggestion_id: str
    type: MemoryHygieneSuggestionType
    status: str
    action_id: str


class CompanionConsolidationRunRequest(BaseModel):
    from_: str | None = Field(default=None, alias="from"); to: str | None = None; limit: int = Field(default=50, ge=1, le=200)


class CompanionConsolidationRunResponse(BaseModel):
    run_id: str; status: str; source_count: int; output_count: int; skipped_count: int; reason: str | None = None; fact_ids: list[str] = Field(default_factory=list); started_at: str; completed_at: str | None = None


class CompanionRetrievalExplainabilityResponse(BaseModel):
    candidate_recall_count: int = 0
    prompt_memory_ids: list[str] = Field(default_factory=list)
    prompt_items: list[dict[str, object]] = Field(default_factory=list)
    permissions_used: dict[str, int] = Field(default_factory=dict)
    activation_score_breakdowns: list[dict[str, object]] = Field(default_factory=list)
    filtered_item_reasons: list[dict[str, str]] = Field(default_factory=list)
    gates: dict[str, int] = Field(default_factory=lambda: {"expired": 0, "conflict": 0, "sensitive": 0})
    safety_note: str = "Sensitive text, credentials, raw snippets, and full Authorization headers are not included."


class CompanionRetrievalReportResponse(ContextBudgetFields):
    id: str; agent_run_id: str; created_at: str; explainability: CompanionRetrievalExplainabilityResponse = Field(default_factory=CompanionRetrievalExplainabilityResponse)


class CompanionRetrievalReportListResponse(BaseModel):
    reports: list[CompanionRetrievalReportResponse] = Field(default_factory=list)
