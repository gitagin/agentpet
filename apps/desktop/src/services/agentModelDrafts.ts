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
  | "classification"
  | "retrieval"
  | "action"
  | "reflection"
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
    label: "聊天回复",
    description: "把检索、动作草稿和连续性上下文组织成用户可见回复。",
  },
  classification: {
    label: "意图分类",
    description: "判断用户意图、检索范围、查询词和动作类型。",
  },
  retrieval: {
    label: "统一检索",
    description: "按范围检索个人记忆、日记对象、每日聊天和资料库。",
  },
  action: {
    label: "本地动作",
    description: "统一规划提醒、资料整理和记忆候选，执行仍走确定性工具和风险策略。",
  },
  reflection: {
    label: "后台反思",
    description: "在回复后整理日记对象、长期记忆候选、连续性更新和摘要。",
  },
  task_reminder: {
    label: "任务",
    description: "识别待办、时间和提醒需求，并生成本地任务结果。",
  },
  knowledge_page: {
    label: "知识",
    description: "把可复用来源材料整理为资料页、摘要或报告。",
  },
  memory_review: {
    label: "记忆",
    description: "把高价值内容转为长期记忆候选，并保留复核路径。",
  },
  cited_answer: {
    label: "带引用回答",
    description: "检索本地记忆、聊天日记和资料整理上下文，为回答提供来源。",
  },
  relationship_continuity: {
    label: "陪伴状态",
    description: "维护身份、关系、情绪和下次接着聊等长期陪伴状态。",
  },
};

export const agentModelDefinitions: AgentModelDefinition[] = [
  {
    id: "chat_agent",
    label: "回复模型",
    description: "唯一的用户可见回复出口，负责把上下文、动作结果和陪伴状态合成为自然语言。",
    outcome: "chat",
    outcomeLabel: "聊天回复",
  },
  {
    id: "semantic_analysis_agent",
    label: "理解模型",
    description: "轻量分类器，判断意图、检索范围、查询词和动作类型；强规则命中时可跳过模型调用。",
    outcome: "classification",
    outcomeLabel: "意图分类",
  },
  {
    id: "retrieval_agent",
    label: "查找模型",
    description: "统一检索个人记忆、日记对象、每日聊天和资料库，必要时整理成引用上下文。",
    outcome: "retrieval",
    outcomeLabel: "统一检索",
  },
  {
    id: "action_agent",
    label: "行动模型",
    description: "统一规划提醒、资料整理和记忆候选；真正写入和提醒由本地工具按风险策略执行。",
    outcome: "action",
    outcomeLabel: "本地动作",
  },
  {
    id: "reflection_agent",
    label: "整理模型",
    description: "回复后在后台整理日记对象、长期记忆候选、连续性更新和可复用摘要。",
    outcome: "reflection",
    outcomeLabel: "后台反思",
  },
];

export const agentModelCountLabel = "职责模型";

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
  const currentById = new Map(current.map((draft) => [draft.agent_id, draft]));
  const statusById = new Map((statusItems || []).map((item) => [item.agent_id, item]));
  return defaultAgentModelDrafts().map((defaultDraft) => {
    const draft = currentById.get(defaultDraft.agent_id) || defaultDraft;
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
