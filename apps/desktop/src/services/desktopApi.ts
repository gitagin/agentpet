import type {
  AgentModelConfigRequest,
  AgentModelConfigResponse,
  AgentModelId,
  AgentModelKeyRequest,
  ChatAcceptedResponse,
  ContinuityProposalActionResponse,
  ContinuityProposalListResponse,
  ContinuityStateResponse,
  ChatRequest,
  DiagnosticsExportResponse,
  LocalStateResetResponse,
  MemoryProposalActionResponse,
  MemoryProposalCreateResponse,
  MemoryProposalDraft,
  MemoryProposalListResponse,
  MemorySearchResponse,
  ModelKeyResponse,
  ModelConfigResponse,
  ModelTestResponse,
  SettingsStatusResponse,
  TaskActionResponse,
  TaskCreateResponse,
  TaskDraft,
  TaskListResponse,
  VaultIndexResponse,
  VaultInitResponse,
  VaultStatusResponse,
  WikiIngestApplyResponse,
  WikiIngestApplyRequest,
  WikiIngestPreviewResponse,
  WikiIngestRequest,
  WikiIngestReviewRequest,
  WikiIngestReviewResponse,
  WikiIndexResponse,
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

  searchMemory(query: string, signal?: AbortSignal): Promise<MemorySearchResponse> {
    return this.client.post<MemorySearchResponse>(
      "/api/memory/search",
      { query, top_k: 8, mode: "fts" },
      signal,
    );
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

  completeTask(taskId: string, signal?: AbortSignal): Promise<TaskActionResponse> {
    return this.client.post<TaskActionResponse>(`/api/tasks/${encodeURIComponent(taskId)}/complete`, {}, signal);
  }

  cancelTask(taskId: string, signal?: AbortSignal): Promise<TaskActionResponse> {
    return this.client.post<TaskActionResponse>(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {}, signal);
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

  testModelConnection(signal?: AbortSignal): Promise<ModelTestResponse> {
    return this.client.post<ModelTestResponse>("/api/settings/model-test", {}, signal);
  }

  saveAgentModelConfig(
    request: AgentModelConfigRequest,
    signal?: AbortSignal,
  ): Promise<AgentModelConfigResponse> {
    return this.client.put<AgentModelConfigResponse>(
      `/api/settings/agent-models/${encodeURIComponent(request.agent_id)}/config`,
      { provider: request.provider, base_url: request.base_url, model: request.model },
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
      { path, create_if_missing: createIfMissing },
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
}
