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

export type AgentOutcomeKey =
  | "chat"
  | "task_reminder"
  | "knowledge_page"
  | "memory_review"
  | "cited_answer"
  | "relationship_continuity";

export type AgentModelDefinition = {
  id: AgentModelId;
  label: string;
  description: string;
  outcome: AgentOutcomeKey;
  outcomeLabel: string;
};

export const agentOutcomeDefinitions: Record<AgentOutcomeKey, { label: string; description: string }> = {
  chat: {
    label: "聊天",
    description: "把检索、记忆和任务结果组织成最终回复。",
  },
  task_reminder: {
    label: "任务",
    description: "识别待办、时间和提醒需求，并生成本地任务结果。",
  },
  knowledge_page: {
    label: "知识",
    description: "把可复用来源材料整理为知识页、摘要或报告。",
  },
  memory_review: {
    label: "记忆",
    description: "把高价值内容转为长期记忆候选，并保留复核路径。",
  },
  cited_answer: {
    label: "带引用回答",
    description: "检索本地记忆、聊天日记和知识整理上下文，为回答提供来源。",
  },
  relationship_continuity: {
    label: "连续性",
    description: "维护身份、关系、情绪和未完话题等长期陪伴状态。",
  },
};

export const agentModelDefinitions: AgentModelDefinition[] = [
  { id: "chat_agent", label: "最终回复", description: "生成用户可见的聊天回复。", outcome: "chat", outcomeLabel: "聊天" },
  { id: "task_agent", label: "任务创建", description: "创建本地任务和提醒。", outcome: "task_reminder", outcomeLabel: "任务" },
  { id: "wiki_manager_agent", label: "知识页写入", description: "维护本机知识页。", outcome: "knowledge_page", outcomeLabel: "知识" },
  { id: "memory_proposal_agent", label: "记忆复核", description: "准备可能需要确认的长期记忆项。", outcome: "memory_review", outcomeLabel: "记忆" },
  { id: "diary_memory_extractor_agent", label: "日记结构化", description: "从聊天日记提取事件、主题和情绪。", outcome: "memory_review", outcomeLabel: "记忆" },
  { id: "memory_retrieval_agent", label: "记忆检索", description: "搜索个人记忆和每日聊天记录。", outcome: "cited_answer", outcomeLabel: "带引用回答" },
  { id: "knowledge_retrieval_agent", label: "知识检索", description: "搜索本机知识页。", outcome: "cited_answer", outcomeLabel: "带引用回答" },
  { id: "continuity_agent", label: "连续性", description: "提取身份、关系和情绪连续性；高风险内容仍需复核。", outcome: "relationship_continuity", outcomeLabel: "连续性" },
  { id: "semantic_analysis_agent", label: "意图路由", description: "判断意图与上下文需求。", outcome: "chat", outcomeLabel: "聊天" },
];

export const agentModelCountLabel = "结果路由";

export function agentOutcomeLabel(agentId: AgentModelId | string): string {
  return agentModelDefinitions.find((agent) => agent.id === agentId)?.outcomeLabel || "路由";
}

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
    const savedEnabled = status.enabled ?? true;
    const hasUnsavedDraft = hasUnsavedAgentModelDraft(draft);
    return {
      ...draft,
      provider: hasUnsavedDraft ? draft.provider : savedProvider,
      base_url: hasUnsavedDraft ? draft.base_url : savedBaseUrl,
      model: hasUnsavedDraft ? draft.model : savedModel,
      enabled: hasUnsavedDraft ? draft.enabled : savedEnabled,
      configured: status.configured,
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
  const enabled = config.enabled ?? true;
  const masked = keyStatus?.masked || config.masked || draft.masked;
  return {
    provider,
    base_url: baseUrl,
    model,
    api_key: "",
    enabled,
    configured: config.configured,
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
