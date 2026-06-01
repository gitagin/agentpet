import type { AgentAction, ChatMessage, ChatWikiProposal, ContinuityProposal, MemoryProposal } from "../types";

export type AgentActivityLogEntry =
  | { kind: "agent_action"; id: string; sortAt: string; sortKey: number; action: AgentAction }
  | { kind: "memory_proposal"; id: string; sortAt: string; sortKey: number; proposal: MemoryProposal }
  | { kind: "continuity_proposal"; id: string; sortAt: string; sortKey: number; proposal: ContinuityProposal }
  | { kind: "wiki_proposal"; id: string; sortAt: string; sortKey: number; message: ChatMessage; proposal: ChatWikiProposal };

function pickPayloadString(payload: Record<string, unknown> | null, keys: string[]): string | null {
  if (!payload) {
    return null;
  }
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function pickPayloadStringArray(payload: Record<string, unknown> | null, key: string): string[] {
  const value = payload?.[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return Array.from(
    new Set(
      value
        .map((item) => (typeof item === "string" ? item.trim() : ""))
        .filter(Boolean),
    ),
  );
}

function pickPayloadStringRecord(payload: Record<string, unknown> | null, key: string): Record<string, string> {
  const value = payload?.[key];
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).flatMap(([entryKey, entryValue]) =>
      typeof entryValue === "string" && entryValue.trim() ? [[entryKey, entryValue.trim()]] : [],
    ),
  );
}

function normalizeAgentActionRiskTier(value: string | null): AgentAction["risk_tier"] {
  return value === "medium" || value === "high" ? value : "low";
}

function normalizeAgentActionDecision(value: string | null, requiresConfirmation: boolean): AgentAction["decision"] {
  if (value === "notify" || value === "ask") {
    return value;
  }
  return requiresConfirmation ? "ask" : "auto";
}

export function normalizeAgentAction(payload: Record<string, unknown> | null): AgentAction | null {
  if (!payload) {
    return null;
  }
  const actionId = pickPayloadString(payload, ["action_id", "id"]);
  if (!actionId) {
    return null;
  }
  const actionType = pickPayloadString(payload, ["action_type", "type"]) || "agent_action";
  const requiresConfirmation = payload.requires_confirmation === true;
  const createdAt = pickPayloadString(payload, ["created_at"]) || new Date().toISOString();
  const status = pickPayloadString(payload, ["status"]) || "completed";
  const metadata =
    payload.metadata && typeof payload.metadata === "object" && !Array.isArray(payload.metadata)
      ? (payload.metadata as Record<string, unknown>)
      : {};

  return {
    action_id: actionId,
    source_agent_run_id: pickPayloadString(payload, ["source_agent_run_id", "agent_run_id"]),
    source_conversation_id: pickPayloadString(payload, ["source_conversation_id", "conversation_id"]),
    source_message_id: pickPayloadString(payload, ["source_message_id", "message_id"]),
    action_type: actionType,
    risk_tier: normalizeAgentActionRiskTier(pickPayloadString(payload, ["risk_tier"])),
    decision: normalizeAgentActionDecision(pickPayloadString(payload, ["decision"]), requiresConfirmation),
    status,
    title: pickPayloadString(payload, ["title"]) || formatAgentActionType(actionType),
    summary: pickPayloadString(payload, ["summary", "message", "description"]) || "",
    target_paths: pickPayloadStringArray(payload, "target_paths"),
    reversible: payload.reversible === true,
    reverted_by: pickPayloadString(payload, ["reverted_by"]),
    reverts_action_id: pickPayloadString(payload, ["reverts_action_id"]),
    error: pickPayloadString(payload, ["error"]),
    source: pickPayloadStringRecord(payload, "source"),
    diff_summary: pickPayloadString(payload, ["diff_summary"]) || "",
    metadata,
    created_at: createdAt,
    updated_at: pickPayloadString(payload, ["updated_at"]) || createdAt,
    completed_at: pickPayloadString(payload, ["completed_at"]) || (status === "completed" ? createdAt : null),
  };
}

export function formatAgentActionType(actionType: string): string {
  const labels: Record<string, string> = {
    "agent_action.revert": "撤销自动整理",
    "chat.daily_archive": "已归档聊天日记",
    "continuity.identity": "连续性身份整理",
    "continuity.relationship": "连续性关系整理",
    "continuity.mood": "连续性情绪整理",
    "continuity.energy": "连续性能量整理",
    "continuity.open_thread": "连续性话题整理",
    "diary.structured_memory": "已提取结构化日记",
    "markdown.bulk_rewrite": "批量改写 Markdown",
    "markdown.delete": "删除 Markdown",
    "markdown.move": "移动 Markdown",
    "memory.long_term.write": "已更新长期记忆",
    "memory.promote_conflict": "记忆冲突整理",
    "sqlite.schema_change": "SQLite 结构变更",
    "vault.bind": "绑定 Vault",
    "vault.switch": "切换 Vault",
    "wiki.ingest.apply": "资料库页面应用",
    "wiki.lint.repair": "资料库检查修复",
    "wiki.lint.report": "已生成资料库检查报告",
    "wiki.answer_summary.write": "已自动总结到资料库",
    "wiki.page.write": "已整理资料库页面",
    "wiki.page.replace_section": "资料库章节替换",
    "wiki.query_archive.write": "已归档资料库查询",
    "wiki.synthesize.write": "已综合整理资料库",
  };
  return labels[actionType] || actionType.split(".").join(" / ");
}

export function formatAgentActionRiskTier(riskTier: AgentAction["risk_tier"]): string {
  const labels: Record<AgentAction["risk_tier"], string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
  };
  return labels[riskTier];
}

export function formatAgentActionDecision(decision: AgentAction["decision"]): string {
  const labels: Record<AgentAction["decision"], string> = {
    auto: "自动完成",
    notify: "已通知",
    ask: "需确认",
  };
  return labels[decision];
}

export function formatAgentActionStatus(status: string): string {
  const labels: Record<string, string> = {
    applying: "正在应用",
    cancelled: "已取消",
    completed: "已完成",
    failed: "失败",
    pending: "待处理",
    rejected: "已拒绝",
    reverted: "已撤销",
    running: "处理中",
  };
  return labels[status] || status;
}

export function formatAgentActivityTimestamp(value: string): string {
  const time = Date.parse(value);
  if (Number.isNaN(time)) {
    return value || "无时间";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(time));
}

export function agentActivitySortKey(value: string): number {
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function isManualMemoryProposal(proposal: MemoryProposal): boolean {
  return proposal.status === "pending" || proposal.status === "failed";
}

function isManualContinuityProposal(proposal: ContinuityProposal): boolean {
  return proposal.status === "pending";
}

function isManualChatWikiProposal(proposal: ChatWikiProposal): boolean {
  return proposal.state !== "applied" && proposal.state !== "rejected";
}

export function canRevertAgentAction(action: AgentAction): boolean {
  return action.reversible && action.status === "completed" && !action.reverted_by && !action.reverts_action_id;
}

export function isAttentionAgentAction(action: AgentAction): boolean {
  return action.risk_tier === "high" || action.decision === "ask" || action.status === "failed" || Boolean(action.error);
}

export type AgentActionDisplayFields = {
  actionName: string;
  actionTypeLabel: string;
  riskTierLabel: string;
  decisionLabel: string;
  statusLabel: string;
  targetPathLabel: string;
  summary: string;
  reversibleLabel: string;
  createdTimeLabel: string;
  updatedTimeLabel: string;
  sourceLabel: string;
};

export function formatAgentActionSource(action: AgentAction): string {
  return Object.entries(action.source || {})
    .filter(([, value]) => Boolean(value))
    .map(([key, value]) => `${key}=${value}`)
    .join(" / ");
}

export function formatAgentActionTargetPaths(action: AgentAction): string {
  return action.target_paths.length > 0 ? action.target_paths.join(", ") : "无目标文件";
}

export function getAgentActionDisplayFields(action: AgentAction): AgentActionDisplayFields {
  const actionTypeLabel = formatAgentActionType(action.action_type);
  return {
    actionName: action.title || actionTypeLabel,
    actionTypeLabel,
    riskTierLabel: formatAgentActionRiskTier(action.risk_tier),
    decisionLabel: formatAgentActionDecision(action.decision),
    statusLabel: formatAgentActionStatus(action.status),
    targetPathLabel: formatAgentActionTargetPaths(action),
    summary: action.summary || "无摘要",
    reversibleLabel: canRevertAgentAction(action) ? "可撤销" : action.reversible ? "撤销不可用" : "不可撤销",
    createdTimeLabel: formatAgentActivityTimestamp(action.created_at),
    updatedTimeLabel: formatAgentActivityTimestamp(action.updated_at || action.created_at),
    sourceLabel: formatAgentActionSource(action),
  };
}

export function getAgentActionSearchText(action: AgentAction): string {
  const display = getAgentActionDisplayFields(action);
  return [
    display.actionName,
    display.actionTypeLabel,
    action.action_type,
    display.targetPathLabel,
    action.summary,
    action.diff_summary,
    action.error || "",
  ]
    .join(" ")
    .toLocaleLowerCase();
}

export function buildAgentActivityEntries(
  agentActions: AgentAction[],
  proposals: MemoryProposal[],
  continuityProposals: ContinuityProposal[],
  messages: ChatMessage[],
): AgentActivityLogEntry[] {
  const manualSortBase = 9_000_000_000_000_000;
  const entries: AgentActivityLogEntry[] = agentActions.map((action) => ({
    kind: "agent_action",
    id: `agent-action-${action.action_id}`,
    sortAt: action.updated_at || action.created_at,
    sortKey: agentActivitySortKey(action.updated_at || action.created_at),
    action,
  }));

  proposals.filter(isManualMemoryProposal).forEach((proposal, index) => {
    entries.push({
      kind: "memory_proposal",
      id: `memory-proposal-${proposal.proposal_id}`,
      sortAt: "待确认",
      sortKey: manualSortBase - index,
      proposal,
    });
  });

  continuityProposals.filter(isManualContinuityProposal).forEach((proposal, index) => {
    entries.push({
      kind: "continuity_proposal",
      id: `continuity-proposal-${proposal.proposal_id}`,
      sortAt: proposal.updated_at || proposal.created_at,
      sortKey: manualSortBase - 1000 - index,
      proposal,
    });
  });

  messages.forEach((message, messageIndex) => {
    (message.wiki_proposals || []).filter(isManualChatWikiProposal).forEach((proposal, proposalIndex) => {
      entries.push({
        kind: "wiki_proposal",
        id: `wiki-proposal-${message.id}-${proposal.id}`,
        sortAt: proposal.updated_at,
        sortKey: manualSortBase - 2000 - messageIndex * 100 - proposalIndex,
        message,
        proposal,
      });
    });
  });

  return entries.sort((left, right) => right.sortKey - left.sortKey);
}
