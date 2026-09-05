from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import AgentId
from .event_payloads import WikiProposalCoreFields, WikiTargetProposalFields
from .memory import MemorySearchResult


class WikiPageWriteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    title: str = Field(min_length=1); content: str = Field(min_length=1); operation: Literal["create", "append", "replace_section"] = "append"; target_path: str | None = None; section: str | None = None; tags: list[str] = Field(default_factory=list); links: list[str] = Field(default_factory=list); source_message_id: str | None = None; page_type: str | None = Field(default=None, alias="type"); confidence: str | None = None; expiry: str | None = None; authors: list[str] = Field(default_factory=list); contributors: list[str] = Field(default_factory=list); disputed: bool = False; aliases: list[str] = Field(default_factory=list); sources: list[str] = Field(default_factory=list)
    wiki_id: str | None = None; entity_ids: list[str] = Field(default_factory=list); fact_ids: list[str] = Field(default_factory=list); evidence_ids: list[str] = Field(default_factory=list); revision: int = Field(default=1, ge=1); inference: bool = False; updated_at: str | None = None


class WikiPageResponse(BaseModel):
    title: str; relative_path: str; operation: str; status: str; index_job_id: str | None = None; action_id: str | None = None


class WikiPageSummary(BaseModel):
    title: str; relative_path: str; updated_at: str | None = None


class WikiPageListResponse(BaseModel):
    pages: list[WikiPageSummary] = Field(default_factory=list)


class WikiSchemaStatus(BaseModel):
    path: str = "Wiki/AGENTS.md"; exists: bool; updated_at: str | None = None; content: str = ""


class WikiIndexEntry(BaseModel):
    title: str; relative_path: str; page_type: str; summary: str = ""; source_count: int = 0; aliases: list[str] = Field(default_factory=list); sources: list[str] = Field(default_factory=list); updated_at: str | None = None


class WikiIndexResponse(BaseModel):
    path: str = "Wiki/index.md"; updated_at: str | None = None; entries: list[WikiIndexEntry] = Field(default_factory=list); content: str = ""


class WikiGraphNode(BaseModel):
    title: str; relative_path: str; page_type: str; vault_relative_path: str; obsidian_uri: str | None = None; indexed: bool = False; in_degree: int = 0; out_degree: int = 0


class WikiGraphEdge(BaseModel):
    source_path: str; target_path: str | None = None; target: str; resolved: bool


class WikiBrokenLink(BaseModel):
    source_path: str; target: str


class WikiGraphSummaryResponse(BaseModel):
    generated_at: str; summary: dict[str, int] = Field(default_factory=dict); nodes: list[WikiGraphNode] = Field(default_factory=list); edges: list[WikiGraphEdge] = Field(default_factory=list); hubs: list[WikiGraphNode] = Field(default_factory=list); orphans: list[WikiGraphNode] = Field(default_factory=list); broken_links: list[WikiBrokenLink] = Field(default_factory=list)


class WikiLogEntry(BaseModel):
    timestamp: str; operation: str; title: str; details: str = ""


class WikiLogResponse(BaseModel):
    path: str = "Wiki/log.md"; updated_at: str | None = None; entries: list[WikiLogEntry] = Field(default_factory=list); content: str = ""


class WikiIngestPagePlan(BaseModel):
    title: str = Field(min_length=1); target_path: str; operation: Literal["create", "append", "replace_section"] = "replace_section"; section: str | None = None; content: str = Field(min_length=1); tags: list[str] = Field(default_factory=list); links: list[str] = Field(default_factory=list)


class WikiIngestPreviewRequest(BaseModel):
    title: str = Field(min_length=1); content: str = Field(min_length=1); source_type: str = "manual"; source_uri: str | None = None; tags: list[str] = Field(default_factory=list); links: list[str] = Field(default_factory=list); max_pages: int = Field(default=15, ge=1, le=15); source_metadata: dict[str, object] = Field(default_factory=dict)


class WikiIngestPreviewResponse(BaseModel):
    run_id: str; source_id: str; source_hash: str; status: str; page_plans: list[WikiIngestPagePlan]; summary: str; source_metadata: dict[str, object] = Field(default_factory=dict); preview_token: str | None = None


class WikiIngestConfirmRequest(BaseModel):
    preview_token: str = Field(min_length=1); user_confirmed: bool = False


class WikiSourceImportPreviewRequest(BaseModel):
    source_kind: Literal["file", "folder", "url", "webpage_text", "image_asset"]; title: str | None = None; import_root: str | None = None; source_path: str | None = None; url: str | None = None; text: str | None = None; html: str | None = None; tags: list[str] = Field(default_factory=list); links: list[str] = Field(default_factory=list); max_pages: int = Field(default=15, ge=1, le=15); max_files: int = Field(default=100, ge=1, le=1000)


class WikiIngestApplyRequest(BaseModel):
    run_id: str = Field(min_length=1); approved_targets: list[str] | None = None; review_id: str | None = None; review_acknowledged: bool = False


class WikiIngestReviewRequest(BaseModel):
    run_id: str = Field(min_length=1); reviewer_agent_id: AgentId | None = None; force_refresh: bool = False


class WikiIngestReviewFinding(BaseModel):
    severity: Literal["info", "warning", "error"]; code: str; message: str; target_path: str | None = None


class WikiIngestReviewResponse(BaseModel):
    review_id: str; run_id: str; status: Literal["reviewed", "model_not_configured", "failed"]; summary: str = ""; findings: list[WikiIngestReviewFinding] = Field(default_factory=list); recommended_targets: list[str] = Field(default_factory=list); reviewer_agent_id: str | None = None; model_error: str | None = None; created_at: str | None = None; updated_at: str | None = None


class WikiIngestPageResult(BaseModel):
    title: str; relative_path: str; status: str; operation: str; index_job_id: str | None = None; error: str | None = None


class WikiIngestApplyResponse(BaseModel):
    run_id: str; status: str; pages_written: int = 0; page_results: list[WikiIngestPageResult] = Field(default_factory=list); index_updated: bool = False; log_appended: bool = False; lint_summary: dict[str, object] = Field(default_factory=dict)


class WikiSynthesizeRequest(BaseModel):
    title: str = Field(min_length=1); content: str = Field(min_length=1); source_paths: list[str] = Field(default_factory=list); target_path: str | None = None; tags: list[str] = Field(default_factory=list); links: list[str] = Field(default_factory=list); page_type: Literal["synthesis", "comparison", "decision", "report"] = "synthesis"; user_decision: str | None = None; evidence_ids: list[str] = Field(default_factory=list); entity_ids: list[str] = Field(default_factory=list); fact_ids: list[str] = Field(default_factory=list)


class WikiSynthesizeResponse(BaseModel):
    page: WikiPageResponse; index_updated: bool = False; log_appended: bool = False; action_id: str | None = None


class QueryArchiveRequest(BaseModel):
    question: str = Field(min_length=1); answer: str = Field(min_length=1); citations: list[MemorySearchResult] = Field(default_factory=list); title: str | None = None; target_path: str | None = None; section: str | None = None; tags: list[str] = Field(default_factory=list); agent_run_id: str | None = None; source_message_id: str | None = None; allow_mixed_sources: bool = False


class QueryArchiveLintResponse(BaseModel):
    passed: bool; errors: list[str] = Field(default_factory=list); warnings: list[str] = Field(default_factory=list); normalized_citations: list[MemorySearchResult] = Field(default_factory=list); markdown_preview: str = ""


class QueryArchiveResponse(BaseModel):
    archive_id: str; page: WikiPageResponse; lint: QueryArchiveLintResponse; action_id: str | None = None


class QueryArchiveHistoryItem(BaseModel):
    id: str; question: str; answer_preview: str; title: str; target_path: str; section: str | None = None; tags: list[str] = Field(default_factory=list); citation_count: int = 0; agent_run_id: str | None = None; source_message_id: str | None = None; page_title: str; page_operation: str; page_status: str; index_job_id: str | None = None; created_at: str; updated_at: str


class QueryArchiveHistoryResponse(BaseModel):
    archives: list[QueryArchiveHistoryItem] = Field(default_factory=list)


class QueryArchiveDetailResponse(QueryArchiveHistoryItem):
    answer: str; citations: list[MemorySearchResult] = Field(default_factory=list); page: WikiPageResponse


class WikiLintRequest(BaseModel):
    write_report: bool = False


class WikiLintIssue(BaseModel):
    severity: Literal["info", "warning", "error"]; code: str; message: str; path: str | None = None; target: str | None = None


class WikiResearchQuestion(BaseModel):
    question: str; reason: str; related_paths: list[str] = Field(default_factory=list)


class WikiLintRepairProposal(BaseModel):
    proposal_type: Literal["wiki_lint_repair"] = "wiki_lint_repair"; status: str = "proposed"; issue_code: str; title: str; target_path: str | None = None; operation: Literal["create", "append", "replace_section", "reindex", "review", "delete_index_record"]; reason: str; markdown_preview: str = ""; related_paths: list[str] = Field(default_factory=list)


class WikiLintReportResponse(BaseModel):
    generated_at: str; summary: dict[str, int] = Field(default_factory=dict); issues: list[WikiLintIssue] = Field(default_factory=list); research_questions: list[WikiResearchQuestion] = Field(default_factory=list); repair_proposals: list[WikiLintRepairProposal] = Field(default_factory=list); report_page: WikiPageResponse | None = None; action_id: str | None = None


class WikiDiagnosticQueueRequest(BaseModel):
    kinds: list[Literal["contradiction", "stale_claim", "missing_link", "missing_concept"]] = Field(default_factory=list); limit: int = Field(default=50, ge=1, le=200); include_repair_preview: bool = False


class WikiDiagnosticQueueItem(BaseModel):
    id: str; kind: Literal["contradiction", "stale_claim", "missing_link", "missing_concept"]; severity: Literal["info", "warning", "error"]; title: str; question: str; reason: str; related_paths: list[str] = Field(default_factory=list); target: str | None = None; issue_code: str; repair_proposal: WikiLintRepairProposal | None = None; created_at: str


class WikiDiagnosticQueueResponse(BaseModel):
    generated_at: str; summary: dict[str, int] = Field(default_factory=dict); items: list[WikiDiagnosticQueueItem] = Field(default_factory=list)


class WikiQueryArchiveProposal(WikiTargetProposalFields):
    proposal_type: Literal["query_archive"] = "query_archive"; section: str | None = None; tags: list[str] = Field(default_factory=list); lint: QueryArchiveLintResponse; agent_run_id: str | None = None


class WikiSynthesisProposal(WikiTargetProposalFields):
    proposal_type: Literal["synthesize"] = "synthesize"; status: str = "planned"; section: str = "综合整理"; tags: list[str] = Field(default_factory=list); links: list[str] = Field(default_factory=list); source_paths: list[str] = Field(default_factory=list)


class WikiLintProposal(WikiProposalCoreFields):
    proposal_type: Literal["lint"] = "lint"; status: str = "planned"; title: str = "Wiki Lint Report"; write_report: bool = True; target_path: str | None = None; summary: dict[str, int] = Field(default_factory=dict); issues: list[WikiLintIssue] = Field(default_factory=list); research_questions: list[WikiResearchQuestion] = Field(default_factory=list); repair_proposals: list[WikiLintRepairProposal] = Field(default_factory=list)
