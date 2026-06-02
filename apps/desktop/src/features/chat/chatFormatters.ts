import type { ChatMessage, Citation } from "../../types";

const CITATION_SOURCE_SCOPE_LABELS: Record<string, string> = {
  personal_memory: "长期记忆",
  diary_objects: "结构化日记",
  daily_chat: "每日聊天日记",
  knowledge_base: "Wiki/知识库",
  pending_memory: "待确认记忆",
  all: "全部本地资产",
};

const CITATION_RETRIEVAL_MODE_LABELS: Record<string, string> = {
  graph: "图谱",
  graph_active: "图谱",
  vector: "向量检索",
  fts: "全文搜索",
  hybrid: "混合检索",
  multi_source: "多源检索",
};

export function formatCitationSourceScope(sourceScope: Citation["source_scope"]): string | null {
  if (!sourceScope) {
    return null;
  }
  return CITATION_SOURCE_SCOPE_LABELS[sourceScope] || sourceScope;
}

export function formatCitationRetrievalMode(retrievalMode: Citation["retrieval_mode"]): string | null {
  if (!retrievalMode) {
    return null;
  }
  return CITATION_RETRIEVAL_MODE_LABELS[retrievalMode] || retrievalMode;
}

export function formatCitationSourceLabel(citations: Citation[]): string {
  return formatCitationSourceScope(citations[0]?.source_scope) || "本地资产";
}

export function formatCitationSourceScopes(sourceScopes: string[] | undefined): string {
  const labels = (sourceScopes || [])
    .map((scope) => formatCitationSourceScope(scope))
    .filter((label): label is string => Boolean(label));
  return Array.from(new Set(labels)).join(" / ");
}

export function formatRunStatus(status: NonNullable<ChatMessage["status"]>): string {
  const labels: Record<NonNullable<ChatMessage["status"]>, string> = {
    partial: "生成中",
    completed: "已完成",
    failed: "失败，请查看消息",
    cancelled: "已取消",
  };
  return labels[status];
}

export function formatMessageRole(role: ChatMessage["role"]): string {
  const labels: Record<ChatMessage["role"], string> = {
    user: "用户",
    assistant: "助手",
    system: "系统",
  };
  return labels[role];
}
