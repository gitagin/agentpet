import type {
  AgentActionListResponse,
  AgentActionRevertResponse,
  AgentModelConfigRequest,
  AgentModelConfigResponse,
  AgentModelId,
  AgentModelKeyRequest,
  AutomationSettings,
  AutomationSettingsUpdateRequest,
  ChatAcceptedResponse,
  ChatDailyHistoryResponse,
  ContinuityProposalActionResponse,
  ContinuityProposalListResponse,
  ContinuityStateResponse,
  ChatRequest,
  CompanionConsolidationRunRequest,
  CompanionConsolidationRunResponse,
  CompanionRetrievalReportListResponse,
  DiagnosticsExportResponse,
  GrowthSnapshotResponse,
  HabitLoopTriggerRequest,
  HabitLoopTriggerResponse,
  LocalAssetStatsResponse,
  LocalStateResetResponse,
  MemoryProposalActionResponse,
  MemoryProposalCreateResponse,
  MemoryProposalDraft,
  MemoryProposalListResponse,
  MemoryGraphExportPreviewResponse,
  MemoryGraphFactActionResponse,
  MemoryGraphFactListResponse,
  MemoryGraphProjectionResponse,
  MemoryFeedbackResponse,
  MemoryHygieneActionResponse,
  MemoryHygienePreviewResponse,
  MemoryProfileActionRequest,
  MemoryProfileActionResponse,
  MemoryProfileDetail,
  MemoryProfileProjectionResponse,
  MemoryReceiptResponse,
  MemorySearchResponse,
  MemoryReviewActionRequest,
  MemoryReviewResponse,
  ModelKeyResponse,
  ModelConfigResponse,
  ModelHealthResponse,
  ModelTestResponse,
  RetrospectiveReportPeriod,
  RetrospectiveReportResponse,
  RetrospectiveResponse,
  SettingsStatusResponse,
  SettingsUpdateRequest,
  SettingsUpdateResponse,
  CurrentTaskResponse,
  TaskActionResponse,
  TaskApprovalResponse,
  TaskCreateResponse,
  TaskDraft,
  TaskListResponse,
  TaskLogsResponse,
  TaskStepsResponse,
  TtsSettingsResponse,
  TtsSettingsUpdateRequest,
  TtsKeyRequest,
  TtsKeyResponse,
  TtsCacheClearResponse,
  TtsSynthesisApiRequest,
  TtsSynthesisApiResponse,
  VaultIndexResponse,
  VaultInitResponse,
  VaultStatusResponse,
  VisibleContinuitySnapshotResponse,
  WikiIngestApplyResponse,
  WikiIngestApplyRequest,
  WikiIngestConfirmRequest,
  WikiIngestPreviewResponse,
  WikiIngestRequest,
  WikiIngestReviewRequest,
  WikiIngestReviewResponse,
  WikiIndexResponse,
  WikiDiagnosticQueueRequest,
  WikiDiagnosticQueueResponse,
  WikiLintRunRequest,
  WikiLintRunResponse,
  WikiLogResponse,
  WikiQueryArchiveDetailResponse,
  WikiQueryArchiveHistoryResponse,
  WikiQueryArchiveRequest,
  WikiQueryArchiveResponse,
  WikiSchemaStatus,
  WikiSynthesizeRequest,
  WikiSynthesizeResponse,
} from "../types";
import { ApiClient } from "./apiClient";

export class DesktopApi {
  constructor(private readonly client: ApiClient) {}

  startChat(request: ChatRequest, signal?: AbortSignal): Promise<ChatAcceptedResponse> {
    return this.client.post<ChatAcceptedResponse>("/api/chat", request, signal);
  }

  getDailyChatHistory(
    options: { date?: string; timezone?: string; limit?: number } = {},
    signal?: AbortSignal,
  ): Promise<ChatDailyHistoryResponse> {
    const params = new URLSearchParams();
    if (options.date?.trim()) {
      params.set("date", options.date.trim());
    }
    if (options.timezone?.trim()) {
      params.set("timezone", options.timezone.trim());
    }
    if (typeof options.limit === "number") {
      params.set("limit", String(options.limit));
    }
    const query = params.toString();
    return this.client.get<ChatDailyHistoryResponse>(`/api/chat/daily-history${query ? `?${query}` : ""}`, signal);
  }

  listAgentActions(
    limit = 50,
    agentRunId?: string | null,
    signal?: AbortSignal,
  ): Promise<AgentActionListResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (agentRunId?.trim()) {
      params.set("agent_run_id", agentRunId.trim());
    }
    return this.client.get<AgentActionListResponse>(`/api/agent/actions?${params.toString()}`, signal);
  }

  revertAgentAction(actionId: string, signal?: AbortSignal): Promise<AgentActionRevertResponse> {
    return this.client.post<AgentActionRevertResponse>(
      `/api/agent/actions/${encodeURIComponent(actionId)}/revert`,
      {},
      signal,
    );
  }

  searchMemory(query: string, signal?: AbortSignal): Promise<MemorySearchResponse> {
    return this.client.post<MemorySearchResponse>(
      "/api/memory/search",
      { query, top_k: 8, mode: "fts" },
      signal,
    );
  }

  getLocalAssetStats(signal?: AbortSignal): Promise<LocalAssetStatsResponse> {
    return this.client.get<LocalAssetStatsResponse>("/api/memory/local-assets", signal);
  }

  getMemoryProfileProjection(signal?: AbortSignal): Promise<MemoryProfileProjectionResponse> {
    return this.client.get<MemoryProfileProjectionResponse>("/api/memory/profile-projection", signal);
  }

  getMemoryGraphProjection(signal?: AbortSignal): Promise<MemoryGraphProjectionResponse> {
    return this.client.get<MemoryGraphProjectionResponse>("/api/memory/graph-projection", signal);
  }

  getMemoryProfileDetail(itemId: string, signal?: AbortSignal): Promise<MemoryProfileDetail> {
    return this.client.get<MemoryProfileDetail>(
      `/api/memory/profile-projection/items/${encodeURIComponent(itemId)}`,
      signal,
    );
  }

  submitMemoryProfileAction(
    itemId: string,
    request: MemoryProfileActionRequest,
    signal?: AbortSignal,
  ): Promise<MemoryProfileActionResponse> {
    return this.client.post<MemoryProfileActionResponse>(
      `/api/memory/profile-projection/items/${encodeURIComponent(itemId)}/actions`,
      request,
      signal,
    );
  }

  getMemoryReceipts(
    agentRunId?: string | null,
    signal?: AbortSignal,
  ): Promise<MemoryReceiptResponse> {
    const params = new URLSearchParams();
    if (agentRunId?.trim()) {
      params.set("agent_run_id", agentRunId.trim());
    }
    const query = params.toString();
    return this.client.get<MemoryReceiptResponse>(`/api/memory/receipts${query ? `?${query}` : ""}`, signal);
  }

  getGrowthSnapshot(signal?: AbortSignal): Promise<GrowthSnapshotResponse> {
    return this.client.get<GrowthSnapshotResponse>("/api/growth/snapshot", signal);
  }

  triggerHabitLoop(
    request: HabitLoopTriggerRequest,
    signal?: AbortSignal,
  ): Promise<HabitLoopTriggerResponse> {
    return this.client.post<HabitLoopTriggerResponse>("/api/habit-loop/trigger", request, signal);
  }

  createMemoryProposal(
    draft: MemoryProposalDraft,
    signal?: AbortSignal,
  ): Promise<MemoryProposalCreateResponse> {
    return this.client.post<MemoryProposalCreateResponse>("/api/memory/proposals", draft, signal);
  }

  listMemoryProposals(signal?: AbortSignal): Promise<MemoryProposalListResponse> {
    return this.client.get<MemoryProposalListResponse>("/api/memory/proposals", signal);
  }

  listMemoryGraphFacts(
    status?: string | null,
    query?: string | null,
    limit = 50,
    signal?: AbortSignal,
  ): Promise<MemoryGraphFactListResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status?.trim()) {
      params.set("status", status.trim());
    }
    if (query?.trim()) {
      params.set("query", query.trim());
    }
    return this.client.get<MemoryGraphFactListResponse>(`/api/memory/graph/facts?${params.toString()}`, signal);
  }

  confirmMemoryGraphFact(factId: string, signal?: AbortSignal): Promise<MemoryGraphFactActionResponse> {
    return this.client.post<MemoryGraphFactActionResponse>(
      `/api/memory/graph/facts/${encodeURIComponent(factId)}/confirm`,
      {},
      signal,
    );
  }

  markMemoryGraphFactWrong(factId: string, signal?: AbortSignal): Promise<MemoryGraphFactActionResponse> {
    return this.client.post<MemoryGraphFactActionResponse>(
      `/api/memory/graph/facts/${encodeURIComponent(factId)}/wrong`,
      {},
      signal,
    );
  }

  archiveMemoryGraphFact(factId: string, signal?: AbortSignal): Promise<MemoryGraphFactActionResponse> {
    return this.client.post<MemoryGraphFactActionResponse>(
      `/api/memory/graph/facts/${encodeURIComponent(factId)}/archive`,
      {},
      signal,
    );
  }

  sensitiveBlockMemoryGraphFact(factId: string, signal?: AbortSignal): Promise<MemoryGraphFactActionResponse> {
    return this.client.post<MemoryGraphFactActionResponse>(
      `/api/memory/graph/facts/${encodeURIComponent(factId)}/sensitive-block`,
      {},
      signal,
    );
  }

  getMemoryGraphExportPreview(
    format: "json" | "markdown" = "markdown",
    status?: string | null,
    query?: string | null,
    limit = 100,
    signal?: AbortSignal,
  ): Promise<MemoryGraphExportPreviewResponse> {
    const params = new URLSearchParams({ format, limit: String(limit) });
    if (status?.trim()) {
      params.set("status", status.trim());
    }
    if (query?.trim()) {
      params.set("query", query.trim());
    }
    return this.client.get<MemoryGraphExportPreviewResponse>(
      `/api/memory/graph/export-preview?${params.toString()}`,
      signal,
    );
  }

  runCompanionConsolidation(
    request: CompanionConsolidationRunRequest = {},
    signal?: AbortSignal,
  ): Promise<CompanionConsolidationRunResponse> {
    return this.client.post<CompanionConsolidationRunResponse>(
      "/api/memory/companion/consolidation/runs",
      request,
      signal,
    );
  }

  listCompanionContextReports(limit = 20, agentRunId?: string | null, signal?: AbortSignal): Promise<CompanionRetrievalReportListResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (agentRunId?.trim()) {
      params.set("agent_run_id", agentRunId.trim());
    }
    return this.client.get<CompanionRetrievalReportListResponse>(
      `/api/memory/companion/context-reports?${params.toString()}`,
      signal,
    );
  }

  getWeeklyMemoryReview(days = 7, limit = 30, signal?: AbortSignal): Promise<MemoryReviewResponse> {
    const params = new URLSearchParams({ days: String(days), limit: String(limit) });
    return this.client.get<MemoryReviewResponse>(`/api/memory/reviews/weekly?${params.toString()}`, signal);
  }

  applyWeeklyMemoryReviewAction(
    request: MemoryReviewActionRequest,
    signal?: AbortSignal,
  ): Promise<MemoryFeedbackResponse> {
    return this.client.post<MemoryFeedbackResponse>("/api/memory/reviews/weekly/actions", request, signal);
  }

  getMemoryHygienePreview(signal?: AbortSignal): Promise<MemoryHygienePreviewResponse> {
    return this.client.get<MemoryHygienePreviewResponse>("/api/memory/hygiene/preview", signal);
  }

  applyMemoryHygieneSuggestion(
    suggestionId: string,
    confirmed: boolean,
    signal?: AbortSignal,
  ): Promise<MemoryHygieneActionResponse> {
    return this.client.post<MemoryHygieneActionResponse>(
      "/api/memory/hygiene/actions",
      { suggestion_id: suggestionId, confirmed },
      signal,
    );
  }

  getRetrospectives(signal?: AbortSignal): Promise<RetrospectiveResponse> {
    return this.client.get<RetrospectiveResponse>("/api/memory/retrospectives", signal);
  }

  getVisibleContinuitySnapshot(signal?: AbortSignal): Promise<VisibleContinuitySnapshotResponse> {
    return this.client.get<VisibleContinuitySnapshotResponse>("/api/today/snapshot", signal);
  }

  writeRetrospectiveReport(days: number, signal?: AbortSignal): Promise<RetrospectiveReportResponse> {
    return this.client.post<RetrospectiveReportResponse>("/api/memory/retrospectives/report", { days }, signal);
  }

  writeRetrospectivePeriodReport(
    period: RetrospectiveReportPeriod,
    signal?: AbortSignal,
  ): Promise<RetrospectiveReportResponse> {
    return this.client.post<RetrospectiveReportResponse>("/api/memory/retrospectives/report", { period }, signal);
  }

  confirmMemoryProposal(
    proposalId: string,
    signal?: AbortSignal,
  ): Promise<MemoryProposalActionResponse> {
    return this.client.post<MemoryProposalActionResponse>(
      `/api/memory/proposals/${encodeURIComponent(proposalId)}/confirm`,
      {},
      signal,
    );
  }

  rejectMemoryProposal(
    proposalId: string,
    reason: string,
    signal?: AbortSignal,
  ): Promise<MemoryProposalActionResponse> {
    return this.client.post<MemoryProposalActionResponse>(
      `/api/memory/proposals/${encodeURIComponent(proposalId)}/reject`,
      { reason },
      signal,
    );
  }

  getContinuityState(signal?: AbortSignal): Promise<ContinuityStateResponse> {
    return this.client.get<ContinuityStateResponse>("/api/continuity/state", signal);
  }

  listContinuityProposals(signal?: AbortSignal): Promise<ContinuityProposalListResponse> {
    return this.client.get<ContinuityProposalListResponse>("/api/continuity/proposals", signal);
  }

  confirmContinuityProposal(
    proposalId: string,
    signal?: AbortSignal,
  ): Promise<ContinuityProposalActionResponse> {
    return this.client.post<ContinuityProposalActionResponse>(
      `/api/continuity/proposals/${encodeURIComponent(proposalId)}/confirm`,
      {},
      signal,
    );
  }

  rejectContinuityProposal(
    proposalId: string,
    reason: string,
    signal?: AbortSignal,
  ): Promise<ContinuityProposalActionResponse> {
    return this.client.post<ContinuityProposalActionResponse>(
      `/api/continuity/proposals/${encodeURIComponent(proposalId)}/reject`,
      { reason },
      signal,
    );
  }

  createTask(draft: TaskDraft, signal?: AbortSignal): Promise<TaskCreateResponse> {
    return this.client.post<TaskCreateResponse>("/api/tasks", draft, signal);
  }

  listTasks(signal?: AbortSignal): Promise<TaskListResponse> {
    return this.client.get<TaskListResponse>("/api/tasks", signal);
  }

  listTodayTasks(timezone?: string | null, signal?: AbortSignal): Promise<TaskListResponse> {
    const params = new URLSearchParams();
    if (timezone?.trim()) {
      params.set("timezone", timezone.trim());
    }
    const query = params.toString();
    return this.client.get<TaskListResponse>(`/api/tasks/today${query ? `?${query}` : ""}`, signal);
  }

  completeTask(taskId: string, signal?: AbortSignal): Promise<TaskActionResponse> {
    return this.client.post<TaskActionResponse>(`/api/tasks/${encodeURIComponent(taskId)}/complete`, {}, signal);
  }

  cancelTask(taskId: string, signal?: AbortSignal): Promise<TaskActionResponse> {
    return this.client.post<TaskActionResponse>(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {}, signal);
  }

  fetchCurrentTask(signal?: AbortSignal): Promise<CurrentTaskResponse> {
    return this.client.get<CurrentTaskResponse>("/api/tasks/current", signal);
  }

  fetchTaskSteps(taskId: string, signal?: AbortSignal): Promise<TaskStepsResponse> {
    return this.client.get<TaskStepsResponse>(`/api/tasks/${encodeURIComponent(taskId)}/steps`, signal);
  }

  fetchTaskLogs(taskId: string, signal?: AbortSignal): Promise<TaskLogsResponse> {
    return this.client.get<TaskLogsResponse>(`/api/tasks/${encodeURIComponent(taskId)}/logs`, signal);
  }

  approveTask(taskId: string, signal?: AbortSignal): Promise<TaskApprovalResponse> {
    return this.client.post<TaskApprovalResponse>(`/api/tasks/${encodeURIComponent(taskId)}/approve`, {}, signal);
  }

  rejectTask(taskId: string, signal?: AbortSignal): Promise<TaskApprovalResponse> {
    return this.client.post<TaskApprovalResponse>(`/api/tasks/${encodeURIComponent(taskId)}/reject`, {}, signal);
  }

  exportDiagnostics(signal?: AbortSignal): Promise<DiagnosticsExportResponse> {
    return this.client.get<DiagnosticsExportResponse>("/api/diagnostics/export", signal);
  }

  resetLocalState(confirmation: string, signal?: AbortSignal): Promise<LocalStateResetResponse> {
    return this.client.post<LocalStateResetResponse>(
      "/api/diagnostics/reset-local-state",
      { confirmation },
      signal,
    );
  }

  getSettingsStatus(signal?: AbortSignal): Promise<SettingsStatusResponse> {
    return this.client.get<SettingsStatusResponse>("/api/settings", signal);
  }

  getAutomationSettings(signal?: AbortSignal): Promise<AutomationSettings> {
    return this.client.get<AutomationSettings>("/api/settings/automation", signal);
  }

  saveAutomationSettings(
    request: AutomationSettingsUpdateRequest,
    signal?: AbortSignal,
  ): Promise<AutomationSettings> {
    return this.client.put<AutomationSettings>("/api/settings/automation", request, signal);
  }

  getTtsSettings(signal?: AbortSignal): Promise<TtsSettingsResponse> {
    return this.client.get<TtsSettingsResponse>("/api/settings/tts", signal);
  }

  saveTtsSettings(
    request: TtsSettingsUpdateRequest,
    signal?: AbortSignal,
  ): Promise<TtsSettingsResponse> {
    return this.client.put<TtsSettingsResponse>("/api/settings/tts", request, signal);
  }

  saveTtsKey(request: TtsKeyRequest, signal?: AbortSignal): Promise<TtsKeyResponse> {
    return this.client.put<TtsKeyResponse>("/api/settings/tts-key", request, signal);
  }

  synthesizeTts(
    request: TtsSynthesisApiRequest,
    signal?: AbortSignal,
  ): Promise<TtsSynthesisApiResponse> {
    return this.client.post<TtsSynthesisApiResponse>("/api/tts/synthesize", request, signal);
  }

  clearTtsCache(signal?: AbortSignal): Promise<TtsCacheClearResponse> {
    return this.client.request<TtsCacheClearResponse>("/api/tts/cache", { method: "DELETE", signal });
  }

  saveModelKey(provider: string, apiKey: string, signal?: AbortSignal): Promise<ModelKeyResponse> {
    return this.client.put<ModelKeyResponse>("/api/settings/model-key", { provider, api_key: apiKey }, signal);
  }

  saveModelConfig(provider: string, baseUrl: string, model: string, signal?: AbortSignal): Promise<ModelConfigResponse> {
    return this.client.put<ModelConfigResponse>(
      "/api/settings/model-config",
      { provider, base_url: baseUrl, model },
      signal,
    );
  }

  updateSettings(request: SettingsUpdateRequest, signal?: AbortSignal): Promise<SettingsUpdateResponse> {
    return this.client.patch<SettingsUpdateResponse>("/api/settings", request, signal);
  }

  getModelHealth(signal?: AbortSignal): Promise<ModelHealthResponse> {
    return this.client.get<ModelHealthResponse>("/api/settings/model-health", signal);
  }

  testModelConnection(signal?: AbortSignal): Promise<ModelTestResponse> {
    return this.client.post<ModelTestResponse>("/api/settings/model-test", {}, signal);
  }

  saveAgentModelConfig(
    request: AgentModelConfigRequest,
    signal?: AbortSignal,
  ): Promise<AgentModelConfigResponse> {
    return this.client.put<AgentModelConfigResponse>(
      `/api/settings/agent-models/${encodeURIComponent(request.agent_id)}/config`,
      { provider: request.provider, base_url: request.base_url, model: request.model, enabled: request.enabled },
      signal,
    );
  }

  saveAgentModelKey(request: AgentModelKeyRequest, signal?: AbortSignal): Promise<AgentModelConfigResponse> {
    return this.client.put<AgentModelConfigResponse>(
      `/api/settings/agent-models/${encodeURIComponent(request.agent_id)}/key`,
      { provider: request.provider, api_key: request.api_key },
      signal,
    );
  }

  testAgentModelConnection(agentId: AgentModelId | string, signal?: AbortSignal): Promise<ModelTestResponse> {
    return this.client.post<ModelTestResponse>("/api/settings/model-test", { agent_id: agentId }, signal);
  }

  getVaultStatus(signal?: AbortSignal): Promise<VaultStatusResponse> {
    return this.client.get<VaultStatusResponse>("/api/vaults/status", signal);
  }

  initVault(path: string, createIfMissing: boolean, signal?: AbortSignal): Promise<VaultInitResponse> {
    return this.client.post<VaultInitResponse>(
      "/api/vaults/init",
      { path, create_if_missing: createIfMissing, confirmed: true },
      signal,
    );
  }

  indexVault(vaultId: string, signal?: AbortSignal): Promise<VaultIndexResponse> {
    return this.client.post<VaultIndexResponse>(`/api/vaults/${encodeURIComponent(vaultId)}/index`, {}, signal);
  }

  previewWikiIngest(
    request: WikiIngestRequest,
    signal?: AbortSignal,
  ): Promise<WikiIngestPreviewResponse> {
    return this.client.post<WikiIngestPreviewResponse>("/api/wiki/ingest/preview", request, signal);
  }

  applyWikiIngest(
    request: WikiIngestApplyRequest,
    signal?: AbortSignal,
  ): Promise<WikiIngestApplyResponse> {
    return this.client.post<WikiIngestApplyResponse>("/api/wiki/ingest/apply", request, signal);
  }

  confirmWikiIngest(
    request: WikiIngestConfirmRequest,
    signal?: AbortSignal,
  ): Promise<WikiIngestPreviewResponse> {
    return this.client.post<WikiIngestPreviewResponse>("/api/wiki/ingest/confirm", request, signal);
  }

  reviewWikiIngest(
    request: WikiIngestReviewRequest,
    signal?: AbortSignal,
  ): Promise<WikiIngestReviewResponse> {
    return this.client.post<WikiIngestReviewResponse>("/api/wiki/ingest/review", request, signal);
  }

  getWikiSchema(signal?: AbortSignal): Promise<WikiSchemaStatus> {
    return this.client.get<WikiSchemaStatus>("/api/wiki/schema", signal);
  }

  getWikiIndex(signal?: AbortSignal): Promise<WikiIndexResponse> {
    return this.client.get<WikiIndexResponse>("/api/wiki/index", signal);
  }

  getWikiLog(limit = 20, signal?: AbortSignal): Promise<WikiLogResponse> {
    return this.client.get<WikiLogResponse>(
      `/api/wiki/log?limit=${encodeURIComponent(String(limit))}`,
      signal,
    );
  }

  synthesizeWiki(
    request: WikiSynthesizeRequest,
    signal?: AbortSignal,
  ): Promise<WikiSynthesizeResponse> {
    return this.client.post<WikiSynthesizeResponse>("/api/wiki/synthesize", request, signal);
  }

  archiveWikiQuery(
    request: WikiQueryArchiveRequest,
    signal?: AbortSignal,
  ): Promise<WikiQueryArchiveResponse> {
    return this.client.post<WikiQueryArchiveResponse>("/api/wiki/query-archives", request, signal);
  }

  listWikiQueryArchives(limit = 20, signal?: AbortSignal): Promise<WikiQueryArchiveHistoryResponse> {
    return this.client.get<WikiQueryArchiveHistoryResponse>(
      `/api/wiki/query-archives?limit=${encodeURIComponent(String(limit))}`,
      signal,
    );
  }

  getWikiQueryArchive(archiveId: string, signal?: AbortSignal): Promise<WikiQueryArchiveDetailResponse> {
    return this.client.get<WikiQueryArchiveDetailResponse>(
      `/api/wiki/query-archives/${encodeURIComponent(archiveId)}`,
      signal,
    );
  }

  runWikiLint(
    request: WikiLintRunRequest = {},
    signal?: AbortSignal,
  ): Promise<WikiLintRunResponse> {
    return this.client.post<WikiLintRunResponse>("/api/wiki/lint", request, signal);
  }

  getWikiDiagnosticQueue(
    request: WikiDiagnosticQueueRequest = {},
    signal?: AbortSignal,
  ): Promise<WikiDiagnosticQueueResponse> {
    return this.client.post<WikiDiagnosticQueueResponse>("/api/wiki/diagnostics/queue", request, signal);
  }
}
