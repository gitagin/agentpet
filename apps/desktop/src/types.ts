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

export type DesktopVaultRevealMode = "open" | "show";

export type DesktopVaultRevealResult = {
  status: "opened" | "shown" | "rejected" | "failed";
  relative_path?: string;
  reason?: string;
};

export type DesktopFeatureWindowMode = "chat" | "memory" | "growth" | "world" | "settings";
export type DesktopPetInputMode = "chat" | "note" | "task" | "wiki" | "review";

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
      setUiState?: (key: string, value: string | null) => Promise<void> | void;
      getSidecarStatus?: () => Promise<DesktopSidecarStatus>;
      apiRequest?: (pathOrUrl: string, options?: DesktopApiRequestOptions) => Promise<DesktopApiResponse>;
      revealVaultPath?: (
        relativePath: string,
        mode: DesktopVaultRevealMode,
      ) => Promise<DesktopVaultRevealResult>;
      startSseStream?: (streamId: string, pathOrUrl: string) => Promise<{ streamId: string }>;
      cancelSseStream?: (streamId: string) => Promise<void>;
      onSseChunk?: (callback: (streamId: string, chunk: string) => void) => () => void;
      onSseEnd?: (callback: (streamId: string) => void) => () => void;
      onSseError?: (callback: (streamId: string, error: DesktopSseError) => void) => () => void;
      showReminderNotification?: (
        payload: DesktopReminderNotificationRequest,
      ) => Promise<DesktopReminderNotificationResult>;
      getWindowMode?: () => Promise<"pet" | "control" | "stage" | "agent" | DesktopFeatureWindowMode>;
      openControlWindow?: (targetId?: string) => Promise<void>;
      openAgent?: () => Promise<void>;
      closeAgent?: () => Promise<void>;
      openStage?: (mode?: "stage" | "agent" | DesktopFeatureWindowMode) => Promise<void>;
      openFeatureWindow?: (mode: DesktopFeatureWindowMode) => Promise<void>;
      hidePetWindow?: () => Promise<void>;
      quitApp?: () => Promise<void>;
      getPetMousePassthroughStatus?: () => Promise<DesktopPetMousePassthroughStatus>;
      setPetShortcutBarVisible?: (visible: boolean) => Promise<DesktopPetMousePassthroughStatus>;
      setPetInputVisible?: (visible: boolean) => Promise<DesktopPetMousePassthroughStatus>;
      onPetInputModeRequested?: (callback: (mode: DesktopPetInputMode) => void) => () => void;
      beginPetWindowDrag?: () => void;
      activatePetWindowDrag?: () => void;
      endPetWindowDrag?: () => void;
      onPetDragCancelled?: (callback: () => void) => () => void;
      onControlTargetRequested?: (callback: (targetId: string) => void) => () => void;
      onStageRouteRequested?: (callback: (mode: "stage" | "agent" | DesktopFeatureWindowMode) => void) => () => void;
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
  retrieval_scopes?: string[];
  retrieval_context_budget?: ChatContextBudget;
  events?: ChatToolEvent[];
  negotiation_steps?: ChatNegotiationStep[];
  negotiation_done?: ChatNegotiationDone;
  wiki_proposals?: ChatWikiProposal[];
  memory_proposals?: MemoryProposal[];
  continuity_proposals?: ChatContinuityProposal[];
  continuity_signal?: ChatContinuitySignal;
  agent_actions?: AgentAction[];
  memory_receipts?: MemoryReceiptItem[];
  task_actions?: TaskItem[];
  agent_run_id?: string;
  retrieval_attempted?: boolean;
  live2d_action_hints?: string[];
};

export type ChatContextBudget = {
  strategy: string;
  candidate_count: number;
  selected_count: number;
  duplicate_drop_count?: number;
  per_scope_drop_count?: number;
  budget_drop_count?: number;
  item_budget: number;
  per_scope_limit: number;
  char_budget: number;
  used_chars: number;
  source_counts?: Record<string, number>;
  selected_scopes?: string[];
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
  source_scope?: "personal_memory" | "diary_objects" | "daily_chat" | "knowledge_base" | "pending_memory" | "all" | string;
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
  source_scope?: "personal_memory" | "diary_objects" | "daily_chat" | "knowledge_base" | "pending_memory" | "all" | string;
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

export type LocalAssetStatsResponse = {
  vault_configured: boolean;
  vault_id?: string | null;
  chat_diary_days: number;
  chat_diary_entries: number;
  long_term_memory_count: number;
  wiki_page_count: number;
  task_count: number;
  completed_task_count: number;
  latest_organization_at?: string | null;
  reversible_operation_count: number;
};

export type GrowthDimension = {
  key: string;
  label: string;
  level: number;
  level_label: string;
  current_value: number;
  next_threshold?: number | null;
  progress: number;
  description: string;
  data_sources: string[];
  last_changed_at?: string | null;
};

export type GrowthEvent = {
  event_id: string;
  occurred_at: string;
  dimension_key: string;
  title: string;
  summary: string;
  source_action_id: string;
  source_action_type: string;
  target_paths: string[];
};

export type GrowthSnapshotResponse = {
  generated_at: string;
  dimensions: GrowthDimension[];
  events: GrowthEvent[];
  stats: LocalAssetStatsResponse;
};

export type ProactiveTriggerFrequency = "off" | "low" | "normal" | "high";

export type HabitLoopCandidate = {
  trigger_id: string;
  content_type: string;
  title: string;
  message: string;
  suggested_prompt: string;
  source_count: number;
  sources: string[];
};

export type HabitLoopTriggerRequest = {
  timezone: string;
};

export type HabitLoopTriggerResponse = {
  should_trigger: boolean;
  reason: string;
  frequency: ProactiveTriggerFrequency;
  daily_limit: number;
  daily_count: number;
  cooldown_minutes: number;
  next_eligible_at?: string | null;
  quiet_hours: string;
  candidate?: HabitLoopCandidate | null;
  action_id?: string | null;
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

export type MemoryReviewCategory = "kept" | "temporary" | "ignored";

export type MemoryReviewAction = "keep" | "edit" | "forget" | "only_this_week" | "mark_completed";

export type MemoryReviewItem = {
  review_id: string;
  target_type: "candidate" | "fact";
  target_id: string;
  category: MemoryReviewCategory;
  summary: string;
  memory_kind?: string | null;
  memory_scope?: string | null;
  lifecycle_status: string;
  risk_tier?: string | null;
  confidence: number;
  importance: number;
  evidence_count: number;
  expires_at?: string | null;
  updated_at: string;
  source: string;
  allowed_actions: MemoryReviewAction[];
};

export type MemoryReviewResponse = {
  generated_at: string;
  window_days: number;
  summary: Record<MemoryReviewCategory, number>;
  items: MemoryReviewItem[];
  redaction_note: string;
};

export type MemoryProfileProjectionItem = {
  id: string;
  category: string;
  summary: string;
  confidence: number;
  importance: number;
  status_label: string;
  risk_label: string;
  source_label: string;
  updated_at: string;
  permissions_summary: string;
  can_revoke: boolean;
  available_actions: string[];
};

export type MemoryProfileProjectionResponse = {
  generated_at: string;
  identity: MemoryProfileProjectionItem[];
  preferences: MemoryProfileProjectionItem[];
  boundaries: MemoryProfileProjectionItem[];
  projects: MemoryProfileProjectionItem[];
  relationships: MemoryProfileProjectionItem[];
  recent_state: MemoryProfileProjectionItem[];
  conflicts: MemoryProfileProjectionItem[];
  needs_confirmation: MemoryProfileProjectionItem[];
  filtered: MemoryProfileProjectionItem[];
  redaction_note: string;
};

export type MemoryProfileActionKind = "forget" | "mark_inaccurate" | "keep" | "make_temporary" | "mark_stale";

export type MemoryProfileAvailableAction = {
  action: MemoryProfileActionKind;
  label: string;
  requires_confirmation: boolean;
};

export type MemoryProfileSourceSummary = {
  label: string;
  description: string;
  evidence_count_label?: string | null;
  last_seen_label?: string | null;
  safety_note?: string | null;
};

export type MemoryProfileDetail = {
  id: string;
  summary: string;
  category_label: string;
  status_label: string;
  confidence_label: string;
  importance_label: string;
  source_label: string;
  permissions: string[];
  safety_note?: string | null;
  updated_at: string;
  source_summary?: MemoryProfileSourceSummary | null;
  available_actions: MemoryProfileAvailableAction[];
};

export type MemoryProfileActionRequest = {
  action: MemoryProfileActionKind;
  confirmed: boolean;
  expires_at?: string | null;
  feedback_text?: string;
};

export type MemoryProfileActionResponse = {
  ok: boolean;
  message: string;
  item_id: string;
};

export type MemoryReceiptKind =
  | "remembered"
  | "skipped"
  | "needs_confirmation"
  | "updated"
  | "forgotten"
  | "filtered"
  | "used_for_answer"
  | string;

export type MemoryReceiptItem = {
  id: string;
  kind: MemoryReceiptKind;
  title: string;
  detail: string;
  safety_note?: string | null;
  action_label?: string | null;
  related_memory_id?: string | null;
  created_at: string;
};

export type MemoryReceiptResponse = {
  generated_at: string;
  items: MemoryReceiptItem[];
  redaction_note: string;
};

export type MemoryReviewActionRequest = {
  target_type: "candidate" | "fact";
  target_id: string;
  action: MemoryReviewAction;
  feedback_text?: string;
  replacement_text?: string | null;
  replacement_subject?: string | null;
  replacement_predicate?: string | null;
  replacement_object?: string | null;
};

export type MemoryFeedbackResponse = {
  target_type: "candidate" | "fact";
  target_id: string;
  operation: string;
  status: string;
  feedback_event_id: string;
  replacement_target_id?: string | null;
  action_id: string;
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
  | "semantic_analysis_agent"
  | "retrieval_agent"
  | "action_agent"
  | "reflection_agent";

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
  local_privacy_mode: boolean;
  proactive_trigger_frequency: ProactiveTriggerFrequency;
  use_negotiation: boolean;
  max_rounds: number;
  high_risk_confirmation_required: boolean;
  updated_at?: string | null;
};

export type AutomationSettingsUpdateRequest = Pick<
  AutomationSettings,
  | "auto_chat_diary"
  | "auto_structured_memory"
  | "auto_long_term_memory"
  | "auto_wiki_organize"
  | "local_privacy_mode"
  | "proactive_trigger_frequency"
  | "use_negotiation"
  | "max_rounds"
>;

export type TtsSettingsStatus = "disabled" | "ready" | "provider_not_configured" | string;

export type TtsSettingsVoiceConfig = {
  id: string;
  provider: string;
  label: string;
  locale?: string | null;
  gender?: string | null;
  description?: string | null;
};

export type TtsSettingsResponse = {
  enabled: boolean;
  auto_play_assistant_reply: boolean;
  auto_play_reminders: boolean;
  provider: string;
  base_url?: string | null;
  model?: string | null;
  voice: TtsSettingsVoiceConfig | null;
  speed: number;
  volume: number;
  response_format: string;
  requires_api_key: boolean;
  api_style: string;
  auth_header_name?: string | null;
  request_template?: Record<string, unknown> | null;
  audio_json_path?: string | null;
  audio_encoding: string;
  mime_type?: string | null;
  cache_enabled: boolean;
  night_quiet_mode: boolean;
  configured: boolean;
  status: TtsSettingsStatus;
  key_configured: boolean;
  key_masked?: string | null;
  updated_at?: string | null;
};

export type TtsSettingsUpdateRequest = Pick<
  TtsSettingsResponse,
  | "enabled"
  | "auto_play_assistant_reply"
  | "auto_play_reminders"
  | "provider"
  | "base_url"
  | "model"
  | "voice"
  | "speed"
  | "volume"
  | "response_format"
  | "requires_api_key"
  | "api_style"
  | "auth_header_name"
  | "request_template"
  | "audio_json_path"
  | "audio_encoding"
  | "mime_type"
  | "cache_enabled"
  | "night_quiet_mode"
>;

export type TtsKeyRequest = {
  provider: string;
  api_key: string;
};

export type TtsKeyResponse = {
  provider: string;
  status: string;
  configured: boolean;
  masked: string;
};

export type TtsSynthesisApiRequest = {
  text: string;
  provider?: string | null;
  voice?: TtsSettingsVoiceConfig | null;
  speed: number;
  volume: number;
  cache_enabled?: boolean;
};

export type TtsSynthesisApiResponse = {
  provider: string;
  mime_type: string;
  audio_base64: string;
  duration_ms?: number | null;
  cache_hit: boolean;
};

export type TtsCacheClearResponse = {
  status: string;
  cleared_entries: number;
  cleared_bytes: number;
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
  tts_settings?: TtsSettingsResponse;
};

export type MemoryGraphFact = {
  fact_id: string;
  category: string;
  subject: string;
  predicate: string;
  object: string;
  status: "candidate" | "active" | "quarantined" | "archived" | "rejected" | "wrong" | "sensitive_blocked" | string;
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

export type MemoryGraphExportItem = Omit<MemoryGraphFact, "source_text"> & {
  metadata: Record<string, unknown>;
};

export type MemoryGraphExportPreviewResponse = {
  generated_at: string;
  format: "json" | "markdown";
  item_count: number;
  items: MemoryGraphExportItem[];
  json_preview: string;
  markdown_preview: string;
  redaction_note: string;
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

export type RetrospectiveSourceReference = {
  kind: string;
  id: string;
  label: string;
  path?: string | null;
  created_at?: string | null;
};

export type RetrospectiveReportPeriod = "weekly" | "monthly";

export type RetrospectiveTopic = {
  name: string;
  count: number;
  sources: RetrospectiveSourceReference[];
};

export type RetrospectiveDiarySummary = {
  id: string;
  summary: string;
  topic?: string | null;
  source_path?: string | null;
  occurred_at: string;
};

export type RetrospectiveMemoryItem = {
  id: string;
  summary: string;
  category: string;
  status: string;
  confidence: number;
  source_path?: string | null;
  created_at: string;
};

export type RetrospectiveTaskStats = {
  total: number;
  completed: number;
  pending: number;
  cancelled: number;
  overdue: number;
  sources: RetrospectiveSourceReference[];
};

export type RetrospectiveWikiItem = {
  path: string;
  title: string;
  action_type: string;
  created_at: string;
  action_id?: string | null;
};

export type RetrospectivePreference = {
  name: string;
  count: number;
  sources: RetrospectiveSourceReference[];
};

export type RetrospectiveWindow = {
  days: number;
  label: string;
  start_at: string;
  end_at: string;
  summary: Record<string, number>;
  topics: RetrospectiveTopic[];
  diary_summaries: RetrospectiveDiarySummary[];
  long_term_memories: RetrospectiveMemoryItem[];
  tasks: RetrospectiveTaskStats;
  wiki_updates: RetrospectiveWikiItem[];
  repeated_preferences: RetrospectivePreference[];
  has_data: boolean;
};

export type RetrospectiveResponse = {
  generated_at: string;
  windows: RetrospectiveWindow[];
};

export type RetrospectiveReportResponse = {
  page: WikiPageResponse;
  action: AgentAction;
  markdown: string;
};

export type VisibleContinuityTodayCard = {
  title: string;
  summary: string;
  carry_over_items: string[];
  suggested_next_steps: string[];
  continuation_prompts: string[];
  source_count: number;
  updated_at?: string | null;
};

export type VisibleContinuityReceipt = {
  action_id: string;
  action_type: string;
  title: string;
  summary: string;
  decision: AgentActionDecision;
  risk_tier: AgentActionRiskTier;
  status: string;
  reversible: boolean;
  reverted_by?: string | null;
  reverts_action_id?: string | null;
  target_path?: string | null;
  created_at: string;
};

export type VisibleContinuityProjectCard = {
  project_id: string;
  title: string;
  current_state: string;
  recent_progress: string;
  next_step: string;
  blockers: string[];
  last_touched_at?: string | null;
  sources: string[];
};

export type VisibleContinuityPlaybackPreview = {
  period: "weekly" | "monthly";
  title: string;
  summary: string;
  themes: string[];
  completed: string[];
  stuck_points: string[];
  next_focus: string[];
  source_count: number;
};

export type VisibleContinuitySnapshotResponse = {
  today_card: VisibleContinuityTodayCard;
  recent_receipts: VisibleContinuityReceipt[];
  project_cards: VisibleContinuityProjectCard[];
  playback_preview: VisibleContinuityPlaybackPreview;
};

export type VaultStatusResponse = {
  configured: boolean;
  active_vault_id?: string | null;
  root_path?: string | null;
  root_path_label?: string | null;
  name?: string | null;
  latest_indexed_at?: string | null;
  markdown_count: number;
  wiki_page_count: number;
  diary_page_count: number;
};

export type VaultInitRequest = {
  path: string;
  create_if_missing?: boolean;
  confirmed?: boolean;
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

export type {
  TtsPlaybackError,
  TtsPlaybackErrorCode,
  TtsPlaybackItem,
  TtsPlaybackQueueController,
  TtsPlaybackState,
  TtsPlaybackStatus,
  TtsProviderId,
  TtsProviderRegistry,
  TtsSettings,
  TtsSynthesisRequest,
  TtsSynthesisResult,
  TtsVoice,
  TtsVoiceGender,
  UseTtsPlaybackQueueOptions,
} from "./features/tts";
