import type { AgentAction, ChatMessage, ContinuityProposal, MemoryProposal, TaskItem } from "../types";
import type { AgentOutcomeKey } from "./agentModelDrafts";
import { agentOutcomeDefinitions } from "./agentModelDrafts";

type ChatKnowledgeProposal = NonNullable<ChatMessage["wiki_proposals"]>[number];

export type AgentActivityLogEntry =
  | { kind: "agent_action"; id: string; sortAt: string; sortKey: number; action: AgentAction }
  | { kind: "memory_proposal"; id: string; sortAt: string; sortKey: number; proposal: MemoryProposal }
  | { kind: "continuity_proposal"; id: string; sortAt: string; sortKey: number; proposal: ContinuityProposal }
  | { kind: "wiki_proposal"; id: string; sortAt: string; sortKey: number; message: ChatMessage; proposal: ChatKnowledgeProposal };

export type MemoryTrustGroupKey =
  | "long_term"
  | "chat_diary"
  | "structured_diary"
  | "wiki_summary"
  | "tasks"
  | "skipped";

export type MemoryTrustGroup = {
  key: MemoryTrustGroupKey;
  label: string;
  description: string;
  entries: AgentActivityLogEntry[];
};

export type AgentOutcomeActivity = {
  key: AgentOutcomeKey;
  label: string;
  description: string;
  detail: string;
};

export const memoryTrustGroupDefinitions: Array<Omit<MemoryTrustGroup, "entries">> = [
  { key: "long_term", label: "长期记忆", description: "偏好、背景、连续性和需要确认的长期记忆。" },
  { key: "chat_diary", label: "聊天日记", description: "普通对话归档到本机日记。" },
  { key: "structured_diary", label: "结构化日记", description: "从对话中提取的主题、事件和可检索日记对象。" },
  { key: "wiki_summary", label: "知识页摘要", description: "从有价值回答沉淀出的知识页、摘要或待确认计划。" },
  { key: "tasks", label: "任务/提醒", description: "从对话创建或更新的本地任务和提醒。" },
  { key: "skipped", label: "已跳过", description: "敏感、低价值、重复或没有可保存内容的安全记录。" },
];

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
  if (actionType === "chat.auto_memory.skip") {
    return "已跳过自动整理";
  }
  if (actionType === "memory.long_term.skip") {
    return "已跳过长期记忆";
  }
  if (actionType === "wiki.answer_summary.skip") {
    return "已跳过知识页摘要";
  }
  const labels: Record<string, string> = {
    "agent_action.revert": "撤销自动整理",
    "chat.daily_archive": "已归档聊天日记",
    "continuity.identity": "连续性身份整理",
    "continuity.relationship": "连续性关系整理",
    "continuity.mood": "连续性情绪整理",
    "continuity.energy": "连续性能量整理",
    "continuity.open_thread": "连续性话题整理",
    "diary.structured_memory": "已提取结构化日记",
    "markdown.bulk_rewrite": "批量改写本机文本",
    "markdown.delete": "删除本机文本",
    "markdown.move": "移动本机文本",
    "memory.long_term.write": "已更新长期记忆",
    "memory.promote_conflict": "记忆冲突整理",
    "sqlite.schema_change": "本机数据结构变更",
    "vault.bind": "绑定本机文件夹",
    "vault.switch": "切换本机文件夹",
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
  if (status === "skipped") {
    return "已跳过";
  }
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

function isManualChatKnowledgeProposal(proposal: ChatKnowledgeProposal): boolean {
  return proposal.state !== "applied" && proposal.state !== "rejected";
}

export function canRevertAgentAction(action: AgentAction): boolean {
  return action.reversible && action.status === "completed" && !action.reverted_by && !action.reverts_action_id;
}

export function isAttentionAgentAction(action: AgentAction): boolean {
  return action.risk_tier === "high" || action.decision === "ask" || action.status === "failed" || Boolean(action.error);
}

export type AgentActionArtifactKind = "task" | "memory" | "wiki" | "review" | null;

export function isReviewReportAgentAction(action: AgentAction): boolean {
  const actionType = action.action_type.toLocaleLowerCase();
  return (
    (actionType.startsWith("wiki.") && actionType.includes("report")) ||
    actionType.includes("retrospective_report") ||
    action.target_paths.some((path) => path.toLocaleLowerCase().startsWith("wiki/companion/reports/"))
  );
}

export function classifyAgentActionArtifact(action: AgentAction): AgentActionArtifactKind {
  const actionType = action.action_type.toLocaleLowerCase();
  if (isSkippedAgentAction(action)) {
    return null;
  }
  if (isReviewReportAgentAction(action)) {
    return "review";
  }
  if (actionType.startsWith("task.")) {
    return "task";
  }
  if (
    actionType === "diary.structured_memory" ||
    actionType.startsWith("memory.long_term") ||
    actionType.startsWith("memory.proposal") ||
    actionType.startsWith("memory.promote") ||
    actionType.startsWith("continuity.")
  ) {
    return "memory";
  }
  if (actionType.startsWith("wiki.")) {
    return "wiki";
  }
  return null;
}

export function getAgentActionOutcomeKey(action: AgentAction): AgentOutcomeKey | null {
  const actionType = action.action_type.toLocaleLowerCase();
  if (isSkippedAgentAction(action)) {
    return null;
  }
  if (actionType.startsWith("task.")) {
    return "task_reminder";
  }
  if (isReviewReportAgentAction(action) || actionType.startsWith("wiki.")) {
    return "knowledge_page";
  }
  if (
    actionType === "diary.structured_memory" ||
    actionType.startsWith("memory.long_term") ||
    actionType.startsWith("memory.proposal") ||
    actionType.startsWith("memory.promote")
  ) {
    return "memory_review";
  }
  if (actionType.startsWith("continuity.")) {
    return "relationship_continuity";
  }
  return null;
}

export function buildAgentOutcomeActivities(
  actions: AgentAction[],
  tasks: TaskItem[] = [],
  memoryProposals: MemoryProposal[] = [],
  wikiProposals: ChatKnowledgeProposal[] = [],
): AgentOutcomeActivity[] {
  const details = new Map<AgentOutcomeKey, Set<string>>();
  const add = (key: AgentOutcomeKey, detail: string) => {
    const value = detail.trim();
    if (!value) {
      return;
    }
    const existing = details.get(key) ?? new Set<string>();
    existing.add(value);
    details.set(key, existing);
  };

  actions.forEach((action) => {
    const key = getAgentActionOutcomeKey(action);
    if (!key) {
      return;
    }
    const display = getAgentActionDisplayFields(action);
    add(key, `${display.statusLabel} · ${display.actionName}`);
  });

  tasks.forEach((task) => {
    add("task_reminder", `${formatAgentActionStatus(task.status)} · ${task.title}`);
  });

  memoryProposals.forEach((proposal) => {
    add("memory_review", `${proposal.status === "pending" ? "待确认" : formatAgentActionStatus(proposal.status)} · ${proposal.type}`);
  });

  wikiProposals
    .filter((proposal) => proposal.state !== "rejected")
    .forEach((proposal) => {
      add("knowledge_page", `${proposal.state === "applied" ? "已写入" : "待确认"} · ${proposal.title || proposal.proposal_type}`);
    });

  return Array.from(details.entries()).map(([key, values]) => ({
    key,
    label: agentOutcomeDefinitions[key].label,
    description: agentOutcomeDefinitions[key].description,
    detail: Array.from(values).slice(0, 3).join(" / "),
  }));
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

function isSkippedAgentAction(action: AgentAction): boolean {
  const actionType = action.action_type.toLocaleLowerCase();
  return action.status === "skipped" || actionType.endsWith(".skip") || actionType.includes(".skip.");
}

function normalizeReasonText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function formatAgentActionSkippedReason(action: AgentAction): string {
  const reason = normalizeReasonText(action.metadata?.skipped_reason);
  const summary = normalizeReasonText(action.summary);
  const searchable = `${reason} ${summary}`.toLocaleLowerCase();

  if (reason === "automation_disabled" || searchable.includes("organization are disabled") || searchable.includes("automation is disabled")) {
    return "自动整理策略当前关闭，所以这次对话只保留聊天结果，没有写入日记、长期记忆或知识页。可在配置页的“自动整理策略”里开启低风险自动整理。";
  }
  if (searchable.includes("sensitive")) {
    return "这次内容可能包含敏感信息，已按安全策略跳过写入。";
  }
  if (searchable.includes("confirmation-only")) {
    return "这次内容需要你先确认，暂时没有直接写入长期记忆。";
  }
  if (searchable.includes("too short") || searchable.includes("low-value")) {
    return "这次内容较短或临时性较强，没有形成值得长期保存的整理项。";
  }
  if (searchable.includes("not contain enough reusable knowledge") || searchable.includes("did not produce saveable")) {
    return "这次回复没有提炼出适合沉淀到知识页的可复用内容。";
  }
  if (summary) {
    return summary;
  }
  return "这次没有可保存的整理内容，所以已安全跳过。";
}

export function getAgentActionDisplayFields(action: AgentAction): AgentActionDisplayFields {
  const actionTypeLabel = formatAgentActionType(action.action_type);
  const skipped = isSkippedAgentAction(action);
  return {
    actionName: skipped ? actionTypeLabel : action.title || actionTypeLabel,
    actionTypeLabel,
    riskTierLabel: formatAgentActionRiskTier(action.risk_tier),
    decisionLabel: formatAgentActionDecision(action.decision),
    statusLabel: formatAgentActionStatus(action.status),
    targetPathLabel: formatAgentActionTargetPaths(action),
    summary: skipped ? formatAgentActionSkippedReason(action) : action.summary || "无摘要",
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
    display.sourceLabel,
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
    (message.wiki_proposals || []).filter(isManualChatKnowledgeProposal).forEach((proposal, proposalIndex) => {
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

export function classifyMemoryTrustEntry(entry: AgentActivityLogEntry): MemoryTrustGroupKey | null {
  if (entry.kind === "memory_proposal" || entry.kind === "continuity_proposal") {
    return "long_term";
  }
  if (entry.kind === "wiki_proposal") {
    return "wiki_summary";
  }

  const action = entry.action;
  const actionType = action.action_type.toLocaleLowerCase();
  if (action.status === "skipped" || actionType.endsWith(".skip") || actionType.includes(".skip.")) {
    return "skipped";
  }
  if (
    actionType.startsWith("memory.long_term") ||
    actionType.startsWith("memory.promote") ||
    actionType.startsWith("continuity.")
  ) {
    return "long_term";
  }
  if (actionType === "chat.daily_archive") {
    return "chat_diary";
  }
  if (actionType === "diary.structured_memory") {
    return "structured_diary";
  }
  if (actionType.startsWith("wiki.")) {
    return "wiki_summary";
  }
  if (actionType.startsWith("task.")) {
    return "tasks";
  }
  return null;
}

export function buildMemoryTrustGroups(entries: AgentActivityLogEntry[]): MemoryTrustGroup[] {
  const groups = memoryTrustGroupDefinitions.map((definition) => ({
    ...definition,
    entries: [] as AgentActivityLogEntry[],
  }));
  const byKey = new Map(groups.map((group) => [group.key, group]));
  entries.forEach((entry) => {
    const key = classifyMemoryTrustEntry(entry);
    if (key) {
      byKey.get(key)?.entries.push(entry);
    }
  });
  return groups;
}
