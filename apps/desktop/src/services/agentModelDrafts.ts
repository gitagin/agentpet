import type { AgentModelId, AgentModelSettings } from "../types";

export type AgentModelDraft = {
  agent_id: AgentModelId;
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
  enabled: boolean;
  configured: boolean;
  masked: string;
  saved_enabled: boolean;
  saved_provider: string;
  saved_base_url: string;
  saved_model: string;
};

export const agentModelDefinitions: Array<{ id: AgentModelId; label: string; description: string }> = [
  { id: "wiki_manager_agent", label: "Vault \u7ef4\u62a4\u667a\u80fd\u4f53", description: "\u7ef4\u62a4\u6301\u4e45\u5316 Vault \u77e5\u8bc6\u5e93\u9875\u9762" },
  { id: "chat_agent", label: "\u5bf9\u8bdd\u667a\u80fd\u4f53", description: "\u751f\u6210\u684c\u5ba0\u6700\u7ec8\u56de\u590d" },
  { id: "diary_memory_extractor_agent", label: "\u65e5\u8bb0\u8bb0\u5fc6\u62bd\u53d6\u667a\u80fd\u4f53", description: "\u4ece\u804a\u5929\u65e5\u8bb0\u63d0\u70bc\u7ed3\u6784\u5316\u4e8b\u4ef6\u3001\u4e3b\u9898\u548c\u60c5\u7eea" },
  { id: "semantic_analysis_agent", label: "\u8bed\u4e49\u5206\u6790\u667a\u80fd\u4f53", description: "\u5224\u65ad\u610f\u56fe\u4e0e\u4e0a\u4e0b\u6587\u9700\u6c42" },
  { id: "memory_retrieval_agent", label: "\u8bb0\u5fc6\u68c0\u7d22\u667a\u80fd\u4f53", description: "\u641c\u7d22\u4e2a\u4eba\u8bb0\u5fc6\u548c\u65e5\u5e38\u804a\u5929\u8bb0\u5f55" },
  { id: "knowledge_retrieval_agent", label: "\u77e5\u8bc6\u68c0\u7d22\u667a\u80fd\u4f53", description: "\u641c\u7d22\u6301\u4e45\u5316\u77e5\u8bc6\u5e93\u6587\u6863" },
  { id: "memory_proposal_agent", label: "\u8bb0\u5fc6\u6574\u7406\u667a\u80fd\u4f53", description: "\u5904\u7406\u9700\u8981\u786e\u8ba4\u7684\u957f\u671f\u8bb0\u5fc6\u6574\u7406" },
  { id: "continuity_agent", label: "\u8fde\u7eed\u6027\u667a\u80fd\u4f53", description: "\u63d0\u70bc\u8eab\u4efd\u3001\u5173\u7cfb\u548c\u60c5\u7eea\u8fde\u7eed\u6027\uff0c\u9ad8\u98ce\u9669\u65f6\u8fdb\u5165\u786e\u8ba4" },
  { id: "task_agent", label: "\u4efb\u52a1\u667a\u80fd\u4f53", description: "\u521b\u5efa\u672c\u5730\u4efb\u52a1\u548c\u63d0\u9192" },
];

export const agentModelCountLabel = `${agentModelDefinitions.length} \u4e2a\u667a\u80fd\u4f53`;

export const defaultAgentModelDrafts = (): AgentModelDraft[] =>
  agentModelDefinitions.map((agent) => ({
    agent_id: agent.id,
    provider: "",
    base_url: "",
    model: "",
    api_key: "",
    enabled: false,
    configured: false,
    masked: "",
    saved_enabled: false,
    saved_provider: "",
    saved_base_url: "",
    saved_model: "",
  }));

export function mergeAgentModelStatus(
  current: AgentModelDraft[],
  statusItems: AgentModelSettings[] | undefined,
): AgentModelDraft[] {
  const statusById = new Map((statusItems || []).map((item) => [item.agent_id, item]));
  return current.map((draft) => {
    const status = statusById.get(draft.agent_id);
    if (!status) {
      return draft;
    }
    const savedProvider = status.provider ?? "";
    const savedBaseUrl = status.base_url ?? "";
    const savedModel = status.model ?? "";
    const savedEnabled = status.enabled ?? false;
    const hasUnsavedDraft = hasUnsavedAgentModelDraft(draft);
    return {
      ...draft,
      provider: hasUnsavedDraft ? draft.provider : savedProvider,
      base_url: hasUnsavedDraft ? draft.base_url : savedBaseUrl,
      model: hasUnsavedDraft ? draft.model : savedModel,
      enabled: hasUnsavedDraft ? draft.enabled : savedEnabled,
      configured: savedEnabled && status.configured,
      masked: status.masked || draft.masked,
      api_key: hasUnsavedDraft ? draft.api_key : "",
      saved_enabled: savedEnabled,
      saved_provider: savedProvider,
      saved_base_url: savedBaseUrl,
      saved_model: savedModel,
    };
  });
}

export function normalizeProviderDraft(provider: string): string {
  const value = provider.trim();
  const normalized = value.toLowerCase().replace(/[\uFF0D\u2014\u2013]/g, "-").replace(/\s+/g, " ");
  if (
    normalized === "openai compatible" ||
    normalized === "openai-compatible" ||
    normalized === "openai_compatible" ||
    normalized === "openai\u517c\u5bb9" ||
    normalized === "openai \u517c\u5bb9" ||
    normalized === "openai\u517c\u5bb9\u63a5\u53e3" ||
    normalized === "openai \u517c\u5bb9\u63a5\u53e3" ||
    normalized === "openai\u517c\u5bb9\u534f\u8bae" ||
    normalized === "openai \u517c\u5bb9\u534f\u8bae"
  ) {
    return "openai-compatible";
  }
  return value;
}

export function isSupportedProviderDraft(provider: string): boolean {
  const normalized = normalizeProviderDraft(provider).toLowerCase();
  return normalized === "openai-compatible" || normalized === "openai";
}

export function hasUnsavedAgentModelDraft(draft: AgentModelDraft): boolean {
  return (
    Boolean(draft.api_key.trim()) ||
    draft.enabled !== draft.saved_enabled ||
    draft.provider !== draft.saved_provider ||
    draft.base_url !== draft.saved_base_url ||
    draft.model !== draft.saved_model
  );
}

export function buildSavedAgentModelDraftPatch(
  draft: AgentModelDraft,
  config: AgentModelSettings,
  keyStatus?: Pick<AgentModelSettings, "masked"> | null,
): Partial<AgentModelDraft> {
  const provider = config.provider || "";
  const baseUrl = config.base_url || "";
  const model = config.model || "";
  const enabled = config.enabled ?? draft.enabled;
  const masked = keyStatus?.masked || config.masked || draft.masked;
  return {
    provider,
    base_url: baseUrl,
    model,
    api_key: "",
    enabled,
    configured: enabled && Boolean(masked),
    masked: masked || "",
    saved_enabled: enabled,
    saved_provider: provider,
    saved_base_url: baseUrl,
    saved_model: model,
  };
}

export function agentLabel(agentId: AgentModelId | string): string {
  return agentModelDefinitions.find((agent) => agent.id === agentId)?.label || agentId;
}
