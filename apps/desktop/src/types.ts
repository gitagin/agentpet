export type HealthResponse = {
  status: string;
  version: string;
  database: string;
};

export type ApiErrorBody = {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
    details?: Record<string, unknown>;
  };
};

export type ConnectionSettings = {
  baseUrl: string;
};

export type DesktopSidecarConfig = ConnectionSettings;

export type DesktopApiRequestOptions = {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  auth?: boolean;
};

export type DesktopApiResponse = {
  status: number;
  statusText: string;
  headers: Record<string, string>;
  body: string;
};

export type DesktopSseError = {
  status?: number;
  statusText?: string;
  body?: string;
  message?: string;
};

export type DesktopSidecarStatus = {
  state: "stopped" | "checking-port" | "starting" | "ready" | "error" | "stopping";
  baseUrl: string;
  host: string;
  port: number;
  managed: boolean;
  pid: number | null;
  updatedAt: string;
  health: HealthResponse | null;
  error: {
    code: string;
    message: string;
  } | null;
};

export type DesktopPetMousePassthroughStatus = {
  enabled: boolean;
  reason: string;
  changed: boolean;
};

export type DesktopReminderNotificationRequest = {
  reminder_id: string;
  title: string;
  body?: string;
};

export type DesktopReminderNotificationResult = {
  status: "shown" | "duplicate" | "unsupported" | "failed";
  reminder_id?: string;
  reason?: string;
};

declare global {
  interface Window {
    agentDesktop?: {
      platform: string;
      versions: {
        electron?: string;
        chrome?: string;
      };
      getSidecarConfig?: () => DesktopSidecarConfig;
      getUiState?: (key: string) => string | null;
      setUiState?: (key: string, value: string | null) => void;
      getSidecarStatus?: () => Promise<DesktopSidecarStatus>;
      apiRequest?: (pathOrUrl: string, options?: DesktopApiRequestOptions) => Promise<DesktopApiResponse>;
      startSseStream?: (streamId: string, pathOrUrl: string) => Promise<{ streamId: string }>;
      cancelSseStream?: (streamId: string) => Promise<void>;
      onSseChunk?: (callback: (streamId: string, chunk: string) => void) => () => void;
      onSseEnd?: (callback: (streamId: string) => void) => () => void;
      onSseError?: (callback: (streamId: string, error: DesktopSseError) => void) => () => void;
      showReminderNotification?: (
        payload: DesktopReminderNotificationRequest,
      ) => Promise<DesktopReminderNotificationResult>;
      getWindowMode?: () => Promise<"pet" | "control">;
      openControlWindow?: (targetId?: string) => Promise<void>;
      openAgent?: () => Promise<void>;
      closeAgent?: () => Promise<void>;
      openStage?: () => Promise<void>;
      quitApp?: () => Promise<void>;
      getPetMousePassthroughStatus?: () => Promise<DesktopPetMousePassthroughStatus>;
      beginPetWindowDrag?: () => void;
      activatePetWindowDrag?: () => void;
      endPetWindowDrag?: () => void;
      onPetDragCancelled?: (callback: () => void) => () => void;
      onControlTargetRequested?: (callback: (targetId: string) => void) => () => void;
      selectKnowledgeBaseFolder?: () => Promise<string | null>;
      onSidecarStatusChanged?: (
        callback: (status: DesktopSidecarStatus) => void,
      ) => () => void;
    };
  }
}

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  status?: "partial" | "completed" | "failed" | "cancelled";
  citations?: Citation[];
  events?: ChatToolEvent[];
  negotiation_steps?: ChatNegotiationStep[];
  negotiation_done?: ChatNegotiationDone;
  wiki_proposals?: ChatWikiProposal[];
  continuity_proposals?: ChatContinuityProposal[];
  continuity_signal?: ChatContinuitySignal;
  agent_run_id?: string;
};

export type ChatNegotiationAction = "invoking" | "reviewing" | "revising" | "synthesizing";

export type ChatNegotiationStep = {
  round: number;
  agent: string;
  action: ChatNegotiationAction;
  reasoning: string;
  confidence: number;
  message: string;
};

export type ChatNegotiationDone = {
  total_rounds: number;
  agents_invoked: string[];
  total_latency_ms: number;
  final_confidence: number;
  fallback: boolean;
};

export type Citation = {
  note_id?: string;
  chunk_id?: string;
  relative_path: string;
  title?: string;
  heading?: string | null;
  snippet?: string;
  score?: number;
  source_scope?: "personal_memory" | "diary_objects" | "daily_chat" | "knowledge_base" | "pending_memory" | "all";
  retrieval_mode?: "graph" | "vector" | "fts" | "hybrid" | string;
};

export type ChatToolEvent = {
  id: string;
  label: string;
  detail: string;
  tone?: "info" | "success" | "error";
};

export type AgentActionRiskTier = "low" | "medium" | "high";

export type AgentActionDecision = "auto" | "notify" | "ask";

export type AgentAction = {
  action_id: string;
  source_agent_run_id?: string | null;
  source_conversation_id?: string | null;
  source_message_id?: string | null;
  action_type: string;
  risk_tier: AgentActionRiskTier;
  decision: AgentActionDecision;
  status: string;
  title: string;
  summary: string;
  target_paths: string[];
  reversible: boolean;
  reverted_by?: string | null;
  reverts_action_id?: string | null;
  error?: string | null;
  source: Record<string, string>;
  diff_summary: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

export type AgentActionListResponse = {
  actions: AgentAction[];
};

export type AgentActionRevertResponse = {
  action: AgentAction;
  reverted: AgentAction;
};

export type ChatWikiProposalState = "pending" | "confirmed" | "rejected" | "applying" | "applied" | "failed";

export type ChatWikiProposal = {
  id: string;
  proposal_type: "ingest" | "query_archive" | "synthesize" | "lint" | string;
  state: ChatWikiProposalState;
  backend_status?: string | null;
  title: string;
  run_id?: string | null;
  source_id?: string | null;
  source_hash?: string | null;
  review_id?: string | null;
  review_status?: string | null;
  summary?: string;
  review_summary?: string;
  target_paths: string[];
  recommended_targets: string[];
  selected_targets: string[];
  findings: WikiIngestReviewFinding[];
  markdown_preview?: string;
  source_message_id?: string | null;
  error?: string | null;
  agent_run_id?: string | null;
  write_report?: boolean | null;
  lint_summary?: Record<string, unknown>;
  apply_result?: WikiIngestApplyResponse | WikiQueryArchiveResponse | WikiSynthesizeResponse | WikiLintRunResponse | null;
  updated_at: string;
};

export type ContinuityProposalKind = "identity" | "relationship" | "mood" | "energy" | "open_thread";

export type ContinuityProposalStatus = "pending" | "confirmed" | "rejected" | string;

export type ContinuityProposal = {
  proposal_id: string;
  kind: ContinuityProposalKind;
  summary: string;
  evidence: string;
  confidence: number;
  source_conversation_id?: string | null;
  source_message_id?: string | null;
  agent_run_id?: string | null;
  status: ContinuityProposalStatus;
  rejected_reason?: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatContinuityProposal = ContinuityProposal;

export type ContinuityProposalListResponse = {
  proposals: ContinuityProposal[];
};

export type ContinuityProposalActionResponse = {
  proposal_id: string;
  status: ContinuityProposalStatus;
};

export type ChatContinuitySignal = {
  kind: "open_thread" | "mood_energy" | "relationship" | string;
  title: string;
  summary: string;
  intensity: "medium" | "high" | string;
  display_hint: string;
  source_state_keys: string[];
};

export type ContinuityStateItem = {
  state_key: string;
  value: string;
  confidence: number;
  source_proposal_id?: string | null;
  source_conversation_id?: string | null;
  source_message_id?: string | null;
  agent_run_id?: string | null;
  updated_at: string;
};

export type ContinuityStateResponse = {
  identity_traits?: string | null;
  relationship_summary?: string | null;
  current_mood?: string | null;
  mood_momentum?: string | null;
  energy_level?: string | null;
  unresolved_threads?: string | null;
  recent_emotional_signals?: string | null;
  updated_at?: string | null;
  items: ContinuityStateItem[];
};

export type ChatRequest = {
  conversation_id?: string | null;
  message: string;
};

export type ChatAcceptedResponse = {
  conversation_id: string;
  message_id: string;
  agent_run_id: string;
  stream_url: string;
};

export type MemorySearchResult = {
  note_id: string;
  chunk_id: string;
  relative_path: string;
  title: string;
  heading?: string | null;
  snippet: string;
  score: number;
  source_scope?: "personal_memory" | "diary_objects" | "daily_chat" | "knowledge_base" | "pending_memory" | "all";
  retrieval_mode?: "graph" | "vector" | "fts" | "hybrid" | string;
};

export type MemorySearchResponse = {
  results: MemorySearchResult[];
  metadata: {
    semantic_available: boolean;
    retrieval_mode?: string;
    vector_available?: boolean;
    vector_error?: string;
  };
};

export type WikiIngestOperation = "create" | "append" | "replace_section";

export type WikiIngestRequest = {
  title: string;
  content: string;
  source_type?: string;
  source_uri?: string | null;
  tags?: string[];
  links?: string[];
  max_pages?: number;
};

export type WikiIngestPagePlan = {
  title: string;
  target_path: string;
  operation: WikiIngestOperation;
  section?: string | null;
  content: string;
  tags: string[];
  links: string[];
};

export type WikiIngestPreviewResponse = {
  run_id: string;
  source_id: string;
  source_hash: string;
  status: string;
  page_plans: WikiIngestPagePlan[];
  summary: string;
  source_metadata?: Record<string, unknown>;
  preview_token?: string | null;
};

export type WikiIngestConfirmRequest = {
  preview_token: string;
  user_confirmed: boolean;
};

export type WikiIngestApplyRequest = {
  run_id: string;
  approved_targets?: string[] | null;
  review_id?: string | null;
  review_acknowledged?: boolean;
};

export type WikiIngestReviewRequest = {
  run_id: string;
  reviewer_agent_id?: string | null;
  force_refresh?: boolean;
};

export type WikiIngestReviewFinding = {
  severity: "info" | "warning" | "error" | string;
  code: string;
  message: string;
  target_path?: string | null;
};

export type WikiIngestReviewResponse = {
  review_id: string;
  run_id: string;
  status: "reviewed" | "model_not_configured" | "failed" | string;
  summary: string;
  findings: WikiIngestReviewFinding[];
  recommended_targets: string[];
  model_error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type WikiPageResponse = {
  title: string;
  relative_path: string;
  operation: string;
  status: string;
  index_job_id?: string | null;
};

export type WikiIngestPageResult = WikiPageResponse & {
  error?: string | null;
};

export type WikiIngestApplyResponse = {
  run_id: string;
  status: string;
  pages_written: number;
  page_results: WikiIngestPageResult[];
  index_updated?: boolean;
  log_appended?: boolean;
  lint_summary?: Record<string, unknown>;
};

export type WikiSchemaStatus = {
  path: string;
  exists: boolean;
  updated_at?: string | null;
  content: string;
};

export type WikiIndexEntry = {
  title: string;
  relative_path: string;
  page_type: string;
  summary: string;
  source_count: number;
  updated_at?: string | null;
};

export type WikiIndexResponse = {
  path: string;
  updated_at?: string | null;
  entries: WikiIndexEntry[];
  content: string;
};

export type WikiLogEntry = {
  timestamp: string;
  operation: string;
  title: string;
  details: string;
};

export type WikiLogResponse = {
  path: string;
  updated_at?: string | null;
  entries: WikiLogEntry[];
  content: string;
};

export type WikiSynthesizeRequest = {
  title: string;
  content: string;
  source_paths?: string[];
  target_path?: string | null;
  tags?: string[];
  links?: string[];
};

export type WikiSynthesizeResponse = {
  page: WikiPageResponse;
  index_updated?: boolean;
  log_appended?: boolean;
};

export type WikiQueryArchiveRequest = {
  question: string;
  answer: string;
  citations: MemorySearchResult[];
  title?: string | null;
  target_path?: string | null;
  section?: string | null;
  tags?: string[];
  agent_run_id?: string | null;
  source_message_id?: string | null;
  allow_mixed_sources?: boolean;
};

export type WikiQueryArchiveLintResponse = {
  passed: boolean;
  errors: string[];
  warnings: string[];
  normalized_citations: MemorySearchResult[];
  markdown_preview: string;
};

export type WikiQueryArchiveResponse = {
  archive_id?: string;
  page: WikiPageResponse;
  lint: WikiQueryArchiveLintResponse;
};

export type WikiQueryArchiveHistoryItem = {
  archive_id?: string;
  id?: string;
  question: string;
  answer_preview: string;
  title: string;
  target_path: string;
  section?: string | null;
  tags: string[];
  citation_count: number;
  agent_run_id?: string | null;
  source_message_id?: string | null;
  created_at: string;
  updated_at: string;
  page?: WikiPageResponse;
  page_title?: string;
  page_operation?: string;
  page_status?: string;
  index_job_id?: string | null;
};

export type WikiQueryArchiveHistoryResponse = {
  archives: WikiQueryArchiveHistoryItem[];
};

export type WikiQueryArchiveDetailResponse = WikiQueryArchiveHistoryItem & {
  id: string;
  answer: string;
  citations: MemorySearchResult[];
  page: WikiPageResponse;
};

export type WikiLintIssue = {
  severity: "info" | "warning" | "error" | string;
  code: string;
  message: string;
  path?: string | null;
  target?: string | null;
};

export type WikiLintRunRequest = {
  write_report?: boolean;
};

export type WikiLintRunResponse = {
  generated_at: string;
  summary: Record<string, number>;
  issues: WikiLintIssue[];
  research_questions: Array<{
    question: string;
    reason: string;
    related_paths: string[];
  }>;
  repair_proposals?: WikiLintRepairProposal[];
  report_page?: WikiPageResponse | null;
};

export type WikiLintRepairProposal = {
  proposal_id: string;
  status: string;
  issue_code: string;
  title: string;
  target_path?: string | null;
  operation: "create" | "append" | "replace_section" | "reindex" | "review" | "delete_index_record" | string;
  reason: string;
  markdown_preview: string;
  related_paths: string[];
};

export type WikiDiagnosticQueueKind = "contradiction" | "stale_claim" | "missing_link" | "missing_concept";

export type WikiDiagnosticQueueRequest = {
  kinds?: WikiDiagnosticQueueKind[];
  limit?: number;
  include_repair_preview?: boolean;
};

export type WikiDiagnosticQueueItem = {
  id: string;
  kind: WikiDiagnosticQueueKind;
  severity: "info" | "warning" | "error";
  title: string;
  question: string;
  reason: string;
  related_paths: string[];
  target?: string | null;
  issue_code: string;
  repair_proposal?: WikiLintRepairProposal | null;
  created_at: string;
};

export type WikiDiagnosticQueueResponse = {
  generated_at: string;
  summary: Record<string, number>;
  items: WikiDiagnosticQueueItem[];
};

export type MemoryProposalType = "preference" | "fact" | "event" | "goal" | "rule";

export type MemoryProposalDraft = {
  type: MemoryProposalType;
  content: string;
  target_path: string;
  source_message_id?: string | null;
};

export type MemoryProposal = MemoryProposalDraft & {
  proposal_id: string;
  status: "pending" | "confirmed" | "rejected" | "failed";
  preview_markdown?: string;
  diff?: string | null;
  target_content_hash?: string | null;
  written_path?: string | null;
};

export type MemoryProposalCreateResponse = {
  proposal_id: string;
  status: MemoryProposal["status"];
  preview_markdown: string;
  target_path: string;
  diff?: string | null;
  target_content_hash?: string | null;
};

export type MemoryProposalActionResponse = {
  proposal_id: string;
  status: string;
  written_path?: string | null;
  index_job_id?: string | null;
};

export type MemoryProposalListItem = Partial<MemoryProposalDraft> & {
  proposal_id: string;
  status: MemoryProposal["status"];
  preview_markdown: string;
  target_path: string;
  diff?: string | null;
};

export type MemoryProposalListResponse = {
  proposals: MemoryProposalListItem[];
};

export type TaskDraft = {
  title: string;
  description: string;
  due_at?: string | null;
  remind_at?: string | null;
  timezone: string;
  source_text?: string | null;
};

export type TaskItem = {
  task_id: string;
  reminder_id?: string | null;
  title: string;
  description?: string;
  status: string;
  reminder_status?: string | null;
  due_at?: string | null;
  remind_at?: string | null;
  timezone?: string | null;
  timezone_label?: string | null;
  source_text?: string | null;
  triggered_at?: string | null;
};

export type TaskCreateResponse = {
  task_id: string;
  reminder_id?: string | null;
  status: string;
  metadata: Record<string, string>;
};

export type TaskListResponse = {
  tasks: TaskItem[];
};

export type TaskActionResponse = {
  task_id: string;
  status: string;
};

export type TaskWorkspaceItem = {
  task_id: string;
  title: string;
  description: string;
  status: string;
  due_at: string;
  source_text: string;
  needs_approval: boolean;
  approval_action: string;
};

export type CurrentTaskResponse = {
  task: TaskWorkspaceItem | null;
};

export type TaskStepItem = {
  index: number;
  tool_name: string;
  status: string;
  duration_ms: number;
};

export type TaskStepsResponse = {
  steps: TaskStepItem[];
};

export type TaskLogItem = {
  timestamp: string;
  content: string;
};

export type TaskLogsResponse = {
  logs: TaskLogItem[];
};

export type TaskApprovalResponse = {
  task_id: string;
  status: string;
  approved: boolean;
  rejected: boolean;
};

export type DiagnosticsDatabaseStatus = {
  path_configured: boolean;
  reachable: boolean;
  quick_check?: string | null;
  migration_versions: string[];
  table_counts: Record<string, number>;
};

export type DiagnosticsVaultStatus = {
  configured: boolean;
  active_vault_id?: string | null;
  vault_count: number;
  names: string[];
};

export type DiagnosticsIndexJobSummary = {
  id: string;
  vault_id: string;
  type: string;
  status: string;
  files_seen: number;
  files_indexed: number;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type DiagnosticsAuditLogSummary = {
  id: string;
  actor: string;
  action: string;
  target_path_present: boolean;
  target_name?: string | null;
  result: string;
  reason?: string | null;
  created_at: string;
};

export type DiagnosticsExportResponse = {
  generated_at: string;
  app: Record<string, string>;
  database: DiagnosticsDatabaseStatus;
  vault: DiagnosticsVaultStatus;
  model_configured: boolean;
  recent_index_jobs: DiagnosticsIndexJobSummary[];
  recent_audit_logs: DiagnosticsAuditLogSummary[];
};

export type LocalStateResetResponse = {
  status: string;
  cleared_tables: Record<string, number>;
  removed_paths: string[];
};

export type ModelKeyResponse = {
  provider: string;
  status: string;
  masked: string;
};

export type AgentModelId =
  | "chat_agent"
  | "diary_memory_extractor_agent"
  | "semantic_analysis_agent"
  | "memory_retrieval_agent"
  | "knowledge_retrieval_agent"
  | "wiki_manager_agent"
  | "memory_proposal_agent"
  | "continuity_agent"
  | "task_agent";

export type AgentModelSettings = {
  agent_id: AgentModelId | string;
  provider: string | null;
  base_url: string | null;
  model: string | null;
  enabled?: boolean;
  configured: boolean;
  masked?: string | null;
};

export type AgentModelConfigRequest = {
  agent_id: AgentModelId | string;
  provider: string;
  base_url: string;
  model: string;
  enabled: boolean;
};

export type AgentModelHealth = {
  agent_id: AgentModelId | string;
  source: "agent_specific" | "global_fallback" | "hardcoded_default" | string;
  model: string;
};

export type ModelHealthResponse = {
  global_configured: boolean;
  agents_configured: number;
  agents_fallback_to_global: number;
  agents_fallback_to_default: number;
  agent_details: AgentModelHealth[];
};

export type AgentModelKeyRequest = {
  agent_id: AgentModelId | string;
  provider: string;
  api_key: string;
};

export type ModelConfigResponse = {
  provider: string;
  base_url: string;
  model: string;
  status: string;
};

export type AutomationSettings = {
  auto_chat_diary: boolean;
  auto_structured_memory: boolean;
  auto_long_term_memory: boolean;
  auto_wiki_organize: boolean;
  use_negotiation: boolean;
  max_rounds: number;
  high_risk_confirmation_required: boolean;
  updated_at?: string | null;
};

export type SettingsUpdateRequest = {
  provider?: string;
  base_url?: string;
  model?: string;
  use_negotiation?: boolean;
  max_rounds?: number;
};

export type SettingsUpdateResponse = ModelConfigResponse & {
  agents_using_global: number;
  automation?: AutomationSettings | null;
};

export type AgentModelConfigResponse = ModelConfigResponse & {
  agent_id: AgentModelId | string;
  enabled: boolean;
  configured: boolean;
  masked?: string | null;
};

export type EmbeddingConfigRequest = {
  provider: string;
  base_url: string;
  model: string;
  dimensions?: number | null;
};

export type EmbeddingKeyRequest = {
  provider?: string | null;
  api_key: string;
};

export type EmbeddingConfigResponse = {
  provider: string;
  base_url: string;
  model: string;
  dimensions?: number | null;
  status: string;
  configured: boolean;
  masked?: string | null;
};

export type EmbeddingTestResponse = {
  status: "ok" | "failed" | string;
  provider?: string | null;
  base_url?: string | null;
  model?: string | null;
  dimensions?: number | null;
  latency_ms?: number | null;
  message: string;
  error_code?: string | null;
  error_detail?: string | null;
};

export type ModelTestResponse = {
  status: "ok" | "failed" | string;
  agent_id?: AgentModelId | string | null;
  provider?: string | null;
  base_url?: string | null;
  model?: string | null;
  latency_ms?: number | null;
  message: string;
  error_code?: string | null;
  error_detail?: string | null;
};

export type SettingsStatusResponse = {
  model_provider: string | null;
  model_base_url: string | null;
  chat_model: string | null;
  model_configured: boolean;
  embedding_provider?: string | null;
  embedding_base_url?: string | null;
  embedding_model?: string | null;
  embedding_dimensions?: number | null;
  embedding_configured?: boolean;
  vault_configured: boolean;
  agent_models?: AgentModelSettings[];
  automation: AutomationSettings;
};

export type MemoryGraphFact = {
  fact_id: string;
  category: string;
  subject: string;
  predicate: string;
  object: string;
  status: "candidate" | "active" | "quarantined" | "archived" | "rejected" | string;
  confidence: number;
  source_text: string;
  source_type: string;
  support_count: number;
  conflicts_with?: string | null;
  memory_type?: string | null;
  entity_type?: string | null;
  occurred_at?: string | null;
  expires_at?: string | null;
  metadata_json?: string | null;
  importance?: number | null;
  created_at: string;
  updated_at: string;
};

export type DiaryMemorySource = {
  source_type: string;
  source_id: string;
  conversation_id?: string | null;
  user_message_id?: string | null;
  assistant_message_id?: string | null;
  agent_run_id?: string | null;
  markdown_path?: string | null;
  note_id?: string | null;
  chunk_id?: string | null;
};

export type DiaryMemoryObject = {
  id: string;
  vault_id: string;
  type: string;
  summary: string;
  topic?: string | null;
  emotion?: string | null;
  people: string[];
  keywords: string[];
  importance: number;
  confidence: number;
  occurred_at: string;
  timezone: string;
  status: string;
  extraction_model?: string | null;
  created_at: string;
  updated_at: string;
  sources: DiaryMemorySource[];
};

export type DiaryMemorySearchResponse = {
  objects: DiaryMemoryObject[];
};

export type MemoryGraphFactListResponse = {
  facts: MemoryGraphFact[];
};

export type MemoryGraphFactActionResponse = {
  fact_id: string;
  status: string;
};

export type CompanionConsolidationRunRequest = {
  from?: string | null;
  to?: string | null;
  limit?: number;
};

export type CompanionConsolidationRunResponse = {
  run_id: string;
  status: string;
  source_count: number;
  output_count: number;
  skipped_count: number;
  reason?: string | null;
  fact_ids: string[];
  started_at: string;
  completed_at?: string | null;
};

export type CompanionRetrievalReport = {
  id: string;
  agent_run_id: string;
  strategy: string;
  candidate_count: number;
  selected_count: number;
  duplicate_drop_count: number;
  per_scope_drop_count: number;
  budget_drop_count: number;
  item_budget: number;
  per_scope_limit: number;
  char_budget: number;
  used_chars: number;
  source_counts: Record<string, number>;
  selected_scopes: string[];
  created_at: string;
};

export type CompanionRetrievalReportListResponse = {
  reports: CompanionRetrievalReport[];
};

export type VaultStatusResponse = {
  configured: boolean;
  active_vault_id?: string | null;
  root_path?: string | null;
  name?: string | null;
};

export type VaultInitRequest = {
  path: string;
  create_if_missing?: boolean;
};

export type VaultInitResponse = {
  vault_id: string;
  status: string;
  root_path?: string | null;
  name?: string | null;
};

export type VaultIndexResponse = {
  index_job_id: string;
  status: string;
  files_seen: number;
  files_indexed: number;
};
