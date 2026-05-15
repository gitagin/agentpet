from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import AgentId, MemoryProposalType


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    database: str


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1)


class ChatAcceptedResponse(BaseModel):
    conversation_id: str
    message_id: str
    agent_run_id: str
    stream_url: str


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=20)
    mode: str = "hybrid"
    source_scope: str = "all"


class MemorySearchResult(BaseModel):
    note_id: str
    chunk_id: str
    relative_path: str
    title: str
    heading: str | None = None
    snippet: str
    score: float
    source_scope: str = "knowledge_base"
    retrieval_mode: str = "fts"


class MemorySearchResponse(BaseModel):
    results: list[MemorySearchResult]
    metadata: dict[str, object] = Field(default_factory=lambda: {"semantic_available": False})


class DiaryMemorySearchRequest(BaseModel):
    query: str = ""
    type: str | None = None
    topic: str | None = None
    emotion: str | None = None
    people: list[str] = Field(default_factory=list)
    min_importance: float | None = Field(default=None, ge=0.0, le=1.0)
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    top_k: int = Field(default=8, ge=1, le=50)


class DiaryMemorySourceResponse(BaseModel):
    source_type: str
    source_id: str
    conversation_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    agent_run_id: str | None = None
    markdown_path: str | None = None
    note_id: str | None = None
    chunk_id: str | None = None


class DiaryMemoryObjectResponse(BaseModel):
    id: str
    vault_id: str
    type: str
    summary: str
    topic: str | None = None
    emotion: str | None = None
    people: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    importance: float
    confidence: float
    occurred_at: str
    timezone: str
    status: str
    extraction_model: str | None = None
    created_at: str
    updated_at: str
    sources: list[DiaryMemorySourceResponse] = Field(default_factory=list)


class DiaryMemorySearchResponse(BaseModel):
    objects: list[DiaryMemoryObjectResponse] = Field(default_factory=list)


class MemoryProposalCreateRequest(BaseModel):
    type: MemoryProposalType
    content: str = Field(min_length=1)
    target_path: str
    source_message_id: str | None = None


class MemoryProposalActionResponse(BaseModel):
    proposal_id: str
    status: str
    written_path: str | None = None
    index_job_id: str | None = None


class RejectProposalRequest(BaseModel):
    reason: str = Field(min_length=1)


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    due_at: str | None = None
    remind_at: str | None = None
    timezone: str | None = None
    source_text: str | None = None


class TaskCreateResponse(BaseModel):
    task_id: str
    reminder_id: str | None = None
    status: str
    metadata: dict[str, str] = Field(default_factory=dict)


class WikiPageWriteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    operation: Literal["create", "append", "replace_section"] = "append"
    target_path: str | None = None
    section: str | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    source_message_id: str | None = None
    page_type: str | None = Field(default=None, alias="type")
    confidence: str | None = None
    expiry: str | None = None
    authors: list[str] = Field(default_factory=list)
    contributors: list[str] = Field(default_factory=list)
    disputed: bool = False
    aliases: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class WikiPageResponse(BaseModel):
    title: str
    relative_path: str
    operation: str
    status: str
    index_job_id: str | None = None


class WikiPageSummary(BaseModel):
    title: str
    relative_path: str
    updated_at: str | None = None


class WikiPageListResponse(BaseModel):
    pages: list[WikiPageSummary] = Field(default_factory=list)


class WikiSchemaStatus(BaseModel):
    path: str = "Wiki/AGENTS.md"
    exists: bool
    updated_at: str | None = None
    content: str = ""


class WikiIndexEntry(BaseModel):
    title: str
    relative_path: str
    page_type: str
    summary: str = ""
    source_count: int = 0
    aliases: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class WikiIndexResponse(BaseModel):
    path: str = "Wiki/index.md"
    updated_at: str | None = None
    entries: list[WikiIndexEntry] = Field(default_factory=list)
    content: str = ""


class WikiGraphNode(BaseModel):
    title: str
    relative_path: str
    page_type: str
    vault_relative_path: str
    obsidian_uri: str | None = None
    indexed: bool = False
    in_degree: int = 0
    out_degree: int = 0


class WikiGraphEdge(BaseModel):
    source_path: str
    target_path: str | None = None
    target: str
    resolved: bool


class WikiBrokenLink(BaseModel):
    source_path: str
    target: str


class WikiGraphSummaryResponse(BaseModel):
    generated_at: str
    summary: dict[str, int] = Field(default_factory=dict)
    nodes: list[WikiGraphNode] = Field(default_factory=list)
    edges: list[WikiGraphEdge] = Field(default_factory=list)
    hubs: list[WikiGraphNode] = Field(default_factory=list)
    orphans: list[WikiGraphNode] = Field(default_factory=list)
    broken_links: list[WikiBrokenLink] = Field(default_factory=list)


class WikiLogEntry(BaseModel):
    timestamp: str
    operation: str
    title: str
    details: str = ""


class WikiLogResponse(BaseModel):
    path: str = "Wiki/log.md"
    updated_at: str | None = None
    entries: list[WikiLogEntry] = Field(default_factory=list)
    content: str = ""


class WikiIngestPagePlan(BaseModel):
    title: str = Field(min_length=1)
    target_path: str
    operation: Literal["create", "append", "replace_section"] = "replace_section"
    section: str | None = None
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


class WikiIngestPreviewRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_type: str = "manual"
    source_uri: str | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    max_pages: int = Field(default=15, ge=1, le=15)
    source_metadata: dict[str, object] = Field(default_factory=dict)


class WikiIngestPreviewResponse(BaseModel):
    run_id: str
    source_id: str
    source_hash: str
    status: str
    page_plans: list[WikiIngestPagePlan]
    summary: str
    source_metadata: dict[str, object] = Field(default_factory=dict)


class WikiSourceImportPreviewRequest(BaseModel):
    source_kind: Literal["file", "folder", "url", "webpage_text", "image_asset"]
    title: str | None = None
    import_root: str | None = None
    source_path: str | None = None
    url: str | None = None
    text: str | None = None
    html: str | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    max_pages: int = Field(default=15, ge=1, le=15)
    max_files: int = Field(default=20, ge=1, le=50)


class WikiIngestApplyRequest(BaseModel):
    run_id: str = Field(min_length=1)
    approved_targets: list[str] | None = None
    review_id: str | None = None
    review_acknowledged: bool = False


class WikiIngestReviewRequest(BaseModel):
    run_id: str = Field(min_length=1)
    reviewer_agent_id: AgentId | None = None
    force_refresh: bool = False


class WikiIngestReviewFinding(BaseModel):
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    target_path: str | None = None


class WikiIngestReviewResponse(BaseModel):
    review_id: str
    run_id: str
    status: Literal["reviewed", "model_not_configured", "failed"]
    summary: str = ""
    findings: list[WikiIngestReviewFinding] = Field(default_factory=list)
    recommended_targets: list[str] = Field(default_factory=list)
    reviewer_agent_id: str | None = None
    model_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class WikiIngestPageResult(BaseModel):
    title: str
    relative_path: str
    status: str
    operation: str
    index_job_id: str | None = None
    error: str | None = None


class WikiIngestApplyResponse(BaseModel):
    run_id: str
    status: str
    pages_written: int = 0
    page_results: list[WikiIngestPageResult] = Field(default_factory=list)
    index_updated: bool = False
    log_appended: bool = False
    lint_summary: dict[str, object] = Field(default_factory=dict)


class WikiSynthesizeRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_paths: list[str] = Field(default_factory=list)
    target_path: str | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


class WikiSynthesizeResponse(BaseModel):
    page: WikiPageResponse
    index_updated: bool = False
    log_appended: bool = False


class QueryArchiveRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    citations: list[MemorySearchResult] = Field(default_factory=list)
    title: str | None = None
    target_path: str | None = None
    section: str | None = None
    tags: list[str] = Field(default_factory=list)
    agent_run_id: str | None = None
    source_message_id: str | None = None
    allow_mixed_sources: bool = False


class QueryArchiveLintResponse(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    normalized_citations: list[MemorySearchResult] = Field(default_factory=list)
    markdown_preview: str = ""


class QueryArchiveResponse(BaseModel):
    archive_id: str
    page: WikiPageResponse
    lint: QueryArchiveLintResponse


class QueryArchiveHistoryItem(BaseModel):
    id: str
    question: str
    answer_preview: str
    title: str
    target_path: str
    section: str | None = None
    tags: list[str] = Field(default_factory=list)
    citation_count: int = 0
    agent_run_id: str | None = None
    source_message_id: str | None = None
    page_title: str
    page_operation: str
    page_status: str
    index_job_id: str | None = None
    created_at: str
    updated_at: str


class QueryArchiveHistoryResponse(BaseModel):
    archives: list[QueryArchiveHistoryItem] = Field(default_factory=list)


class QueryArchiveDetailResponse(QueryArchiveHistoryItem):
    answer: str
    citations: list[MemorySearchResult] = Field(default_factory=list)
    page: WikiPageResponse


class WikiLintRequest(BaseModel):
    write_report: bool = False


class WikiLintIssue(BaseModel):
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    path: str | None = None
    target: str | None = None


class WikiResearchQuestion(BaseModel):
    question: str
    reason: str
    related_paths: list[str] = Field(default_factory=list)


class WikiLintRepairProposal(BaseModel):
    proposal_type: Literal["wiki_lint_repair"] = "wiki_lint_repair"
    status: str = "proposed"
    issue_code: str
    title: str
    target_path: str | None = None
    operation: Literal["create", "append", "replace_section", "reindex", "review", "delete_index_record"]
    reason: str
    markdown_preview: str = ""
    related_paths: list[str] = Field(default_factory=list)


class WikiLintReportResponse(BaseModel):
    generated_at: str
    summary: dict[str, int] = Field(default_factory=dict)
    issues: list[WikiLintIssue] = Field(default_factory=list)
    research_questions: list[WikiResearchQuestion] = Field(default_factory=list)
    repair_proposals: list[WikiLintRepairProposal] = Field(default_factory=list)
    report_page: WikiPageResponse | None = None


class WikiQueryArchiveProposal(BaseModel):
    proposal_type: Literal["query_archive"] = "query_archive"
    status: str
    title: str
    target_path: str
    section: str | None = None
    tags: list[str] = Field(default_factory=list)
    lint: QueryArchiveLintResponse
    markdown_preview: str = ""
    agent_run_id: str | None = None
    source_message_id: str | None = None


class WikiSynthesisProposal(BaseModel):
    proposal_type: Literal["synthesize"] = "synthesize"
    status: str = "planned"
    title: str
    target_path: str
    section: str = "综合整理"
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    markdown_preview: str = ""
    source_message_id: str | None = None


class WikiLintProposal(BaseModel):
    proposal_type: Literal["lint"] = "lint"
    status: str = "planned"
    title: str = "Wiki Lint Report"
    write_report: bool = True
    target_path: str | None = None
    summary: dict[str, int] = Field(default_factory=dict)
    issues: list[WikiLintIssue] = Field(default_factory=list)
    research_questions: list[WikiResearchQuestion] = Field(default_factory=list)
    repair_proposals: list[WikiLintRepairProposal] = Field(default_factory=list)
    markdown_preview: str = ""
    source_message_id: str | None = None


class ModelKeyRequest(BaseModel):
    provider: str
    api_key: str = Field(min_length=1)


class AgentModelKeyRequest(BaseModel):
    agent_id: AgentId | None = None
    provider: str | None = None
    api_key: str = Field(min_length=1)


class ModelKeyResponse(BaseModel):
    provider: str
    status: str
    masked: str


class ModelConfigRequest(BaseModel):
    provider: str = Field(default="openai-compatible", min_length=1)
    base_url: str = Field(default="https://api.openai.com/v1", min_length=1)
    model: str = Field(default="gpt-4o-mini", min_length=1)


class AgentModelConfigRequest(ModelConfigRequest):
    agent_id: AgentId | None = None
    enabled: bool = True


class ModelConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    status: str


class EmbeddingConfigRequest(BaseModel):
    provider: str = Field(default="openai-compatible", min_length=1)
    base_url: str = Field(default="https://api.openai.com/v1", min_length=1)
    model: str = Field(default="text-embedding-3-small", min_length=1)
    dimensions: int | None = Field(default=None, ge=1)


class EmbeddingConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    dimensions: int | None = None
    status: str
    configured: bool = False
    masked: str | None = None


class EmbeddingKeyRequest(BaseModel):
    provider: str | None = None
    api_key: str = Field(min_length=1)


class EmbeddingTestResponse(BaseModel):
    status: str
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    dimensions: int | None = None
    latency_ms: int | None = None
    message: str
    error_code: str | None = None
    error_detail: str | None = None


class AgentModelConfigResponse(ModelConfigResponse):
    agent_id: AgentId
    enabled: bool = True
    configured: bool = False
    masked: str | None = None


class AgentModelsRequest(BaseModel):
    agents: list[AgentModelConfigRequest] = Field(default_factory=list)


class AgentModelsResponse(BaseModel):
    agents: list[AgentModelConfigResponse] = Field(default_factory=list)


class ModelTestRequest(BaseModel):
    agent_id: AgentId | None = None


class ModelTestResponse(BaseModel):
    status: str
    agent_id: AgentId | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    message: str
    error_code: str | None = None
    error_detail: str | None = None


class VaultStatusResponse(BaseModel):
    configured: bool = False
    active_vault_id: str | None = None
    root_path: str | None = None
    name: str | None = None


class VaultBindRequest(BaseModel):
    path: str = Field(min_length=1)
    create_if_missing: bool = False


class VaultBindResponse(BaseModel):
    vault_id: str
    status: str
    root_path: str | None = None
    name: str | None = None


class VaultIndexResponse(BaseModel):
    index_job_id: str
    status: str
    files_seen: int = 0
    files_indexed: int = 0


class MemoryProposalResponse(BaseModel):
    proposal_id: str
    status: str
    preview_markdown: str
    target_path: str
    diff: str | None = None


class MemoryProposalListResponse(BaseModel):
    proposals: list[MemoryProposalResponse] = Field(default_factory=list)


class ContinuityStateItem(BaseModel):
    state_key: str
    value: str
    confidence: float
    source_proposal_id: str | None = None
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    agent_run_id: str | None = None
    updated_at: str


class ContinuityStateResponse(BaseModel):
    identity_traits: str | None = None
    relationship_summary: str | None = None
    current_mood: str | None = None
    mood_momentum: str | None = None
    energy_level: str | None = None
    unresolved_threads: str | None = None
    recent_emotional_signals: str | None = None
    updated_at: str | None = None
    items: list[ContinuityStateItem] = Field(default_factory=list)


class ContinuityProposalResponse(BaseModel):
    proposal_id: str
    kind: Literal["identity", "relationship", "mood", "energy", "open_thread"]
    summary: str
    evidence: str
    confidence: float
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    agent_run_id: str | None = None
    status: str
    rejected_reason: str | None = None
    created_at: str
    updated_at: str


class ContinuityProposalListResponse(BaseModel):
    proposals: list[ContinuityProposalResponse] = Field(default_factory=list)


class ContinuityProposalActionResponse(BaseModel):
    proposal_id: str
    status: str


class TaskListResponse(BaseModel):
    tasks: list[dict[str, str]] = Field(default_factory=list)


class SettingsStatusResponse(BaseModel):
    model_provider: str | None = None
    model_base_url: str | None = None
    chat_model: str | None = None
    model_configured: bool = False
    embedding_provider: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_configured: bool = False
    vault_configured: bool = False
    agent_models: list[AgentModelConfigResponse] = Field(default_factory=list)


class MemoryGraphFactResponse(BaseModel):
    fact_id: str
    category: str
    subject: str
    predicate: str
    object: str
    status: str
    confidence: float
    source_text: str
    source_type: str
    support_count: int = 1
    conflicts_with: str | None = None
    memory_type: str | None = None
    entity_type: str | None = None
    occurred_at: str | None = None
    expires_at: str | None = None
    metadata_json: str | None = None
    importance: float = 0.5
    created_at: str
    updated_at: str


class MemoryGraphFactListResponse(BaseModel):
    facts: list[MemoryGraphFactResponse] = Field(default_factory=list)


class MemoryGraphFactActionResponse(BaseModel):
    fact_id: str
    status: str


class ChatStreamEvent(BaseModel):
    event: str
    data: dict[str, str]


class DiagnosticsDatabaseStatus(BaseModel):
    path_configured: bool
    reachable: bool
    quick_check: str | None = None
    migration_versions: list[str] = Field(default_factory=list)
    table_counts: dict[str, int] = Field(default_factory=dict)


class DiagnosticsVaultStatus(BaseModel):
    configured: bool
    active_vault_id: str | None = None
    vault_count: int = 0
    names: list[str] = Field(default_factory=list)


class DiagnosticsIndexJobSummary(BaseModel):
    id: str
    vault_id: str
    type: str
    status: str
    files_seen: int
    files_indexed: int
    error: str | None = None
    created_at: str
    updated_at: str


class DiagnosticsAuditLogSummary(BaseModel):
    id: str
    actor: str
    action: str
    target_path_present: bool
    target_name: str | None = None
    result: str
    reason: str | None = None
    created_at: str


class DiagnosticsExportResponse(BaseModel):
    generated_at: str
    app: dict[str, str]
    database: DiagnosticsDatabaseStatus
    vault: DiagnosticsVaultStatus
    model_configured: bool
    recent_index_jobs: list[DiagnosticsIndexJobSummary] = Field(default_factory=list)
    recent_audit_logs: list[DiagnosticsAuditLogSummary] = Field(default_factory=list)


class LocalStateResetRequest(BaseModel):
    confirmation: str


class LocalStateResetResponse(BaseModel):
    status: str
    cleared_tables: dict[str, int] = Field(default_factory=dict)
    removed_paths: list[str] = Field(default_factory=list)
