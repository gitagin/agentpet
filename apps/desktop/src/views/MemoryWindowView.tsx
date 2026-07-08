import { Archive, BarChart3, BookOpen, CalendarRange, Check, CheckCircle2, Copy, Database, Download, ExternalLink, FileText, FolderSearch, History, Loader2, NotebookTabs, PlusCircle, RefreshCw, RotateCcw, Search, ShieldAlert, XCircle } from "lucide-react";
import type { FormEvent, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "../components/layout";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import {
  buildMemoryTrustGroups,
  canRevertAgentAction,
  classifyMemoryTrustEntry,
  getAgentActionSearchText,
  type AgentActivityLogEntry,
} from "../services/agentActivity";
import type {
  LocalAssetStatsResponse,
  MemoryGraphExportPreviewResponse,
  MemoryGraphFact,
  MemoryGraphProjectionResponse,
  MemoryHygienePreviewResponse,
  MemoryHygieneSuggestion,
  MemoryProfileActionKind,
  MemoryProfileDetail,
  MemoryProfileProjectionItem,
  MemoryProfileProjectionResponse,
  MemoryProposal,
  MemoryProposalDraft,
  MemoryProposalType,
  MemoryReviewAction,
  MemoryReviewItem,
  MemoryReviewResponse,
  MemorySearchResult,
  DesktopVaultRevealMode,
  RetrospectiveReportPeriod,
  RetrospectiveReportResponse,
  RetrospectiveResponse,
  RetrospectiveSourceReference,
  RetrospectiveWindow,
} from "../types";
import MemoryGraphPanel from "../features/memory/MemoryGraphPanel";
import { MemoryProposalActivityCard } from "../features/memory/MemoryProposalActivityCard";
import type { MemoryAsyncStatus } from "../features/memory/memoryReducer";
import { memoryTypeLabels, memoryTypes } from "../features/memory/memoryConstants";
import { productCopy } from "../productCopy";
import { FeatureWindowShell } from "./FeatureWindowShell";

type MemoryActivityFilter = "all" | "auto" | "pending" | "reverted" | "failed";
type MemoryGraphStatusFilter = "all" | "active" | "candidate" | "quarantined" | "archived" | "rejected" | "wrong" | "sensitive_blocked";
type MemoryExportFormat = "json" | "markdown";
type RetrospectiveReportTarget = number | RetrospectiveReportPeriod;
type ReviewCoachKind = "today" | "seven_day" | "monthly";
type MemoryProfileProjectionGroupKey =
  | "identity"
  | "preferences"
  | "boundaries"
  | "projects"
  | "relationships"
  | "recent_state"
  | "needs_confirmation";
type MemoryWorkspaceTabKey =
  | "archive"
  | "search"
  | "data"
  | "import"
  | "graph"
  | "related"
  | "heatmap"
  | "decay"
  | "diary";

type ReviewCoachCardConfig = {
  kind: ReviewCoachKind;
  title: string;
  description: string;
  windowDays: number;
  target: RetrospectiveReportTarget;
  buttonLabel: string;
};

type ReviewReportArtifact = {
  kind: ReviewCoachKind;
  title: string;
  relativePath: string;
  status: string;
  actionId?: string | null;
  generatedAt?: string | null;
};

const memoryWorkspaceTabs: Array<{ key: MemoryWorkspaceTabKey; label: string; description: string }> = [
  { key: "archive", label: "档案", description: "稳定记忆、待确认和可改正记录。" },
  { key: "search", label: "搜索", description: "按关键词找回记忆和资料线索。" },
  { key: "data", label: "数据", description: "本机积累、状态和高级备份。" },
  { key: "import", label: "导入", description: "整理文档、链接和想法到资料库。" },
  { key: "graph", label: "图谱", description: "查看记忆之间的大致关联。" },
  { key: "related", label: "关联", description: "把项目、资料和回忆串起来。" },
  { key: "heatmap", label: "热力图", description: "观察近期高频主题和回忆密度。" },
  { key: "decay", label: "衰减图", description: "处理过期、冲突和需要整理的记忆。" },
  { key: "diary", label: "日记", description: "回顾每日情景和阶段复盘。" },
];

type MemoryWindowViewProps = {
  api: DesktopApi;
  loading: boolean;
  error: string;
  entries: AgentActivityLogEntry[];
  memorySearchQuery: string;
  memorySearchStatus: MemoryAsyncStatus;
  memorySearchResults: MemorySearchResult[];
  memoryLastSearchQuery: string;
  onMemorySearchQueryChange: (query: string) => void;
  onRunMemorySearch: (event: FormEvent) => void;
  memoryProposalDraft: MemoryProposalDraft;
  memoryProposals: MemoryProposal[];
  memoryProposalActionIds: Set<string>;
  loadingMemoryProposals: boolean;
  onMemoryProposalDraftChange: (patch: Partial<MemoryProposalDraft>) => void;
  onCreateMemoryProposal: (event: FormEvent) => void;
  onActOnMemoryProposal: (proposalId: string, action: "confirm" | "reject") => void;
  onLoadMemoryProposals: () => void;
  onRefresh: () => void;
  renderEntry: (entry: AgentActivityLogEntry) => ReactNode;
};

const activityFilters: Array<{ key: MemoryActivityFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "auto", label: "自动写入" },
  { key: "pending", label: "待确认" },
  { key: "reverted", label: "已撤回" },
  { key: "failed", label: "失败" },
];

const graphStatusFilters: Array<{ key: MemoryGraphStatusFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "active", label: "使用中" },
  { key: "candidate", label: "等你确认" },
  { key: "quarantined", label: "暂不使用" },
  { key: "archived", label: "归档" },
  { key: "rejected", label: "已忽略" },
  { key: "wrong", label: "不准确" },
  { key: "sensitive_blocked", label: "敏感封存" },
];

const profileProjectionGroups: Array<{
  key: MemoryProfileProjectionGroupKey;
  title: string;
  empty: string;
}> = [
  { key: "identity", title: "身份和背景", empty: "还没有形成稳定身份画像。" },
  { key: "preferences", title: "偏好", empty: "还没有确认过的偏好。" },
  { key: "boundaries", title: "边界", empty: "还没有明确边界。" },
  { key: "projects", title: "长期项目", empty: "还没有正在跟进的长期项目。" },
  { key: "relationships", title: "关系和称呼", empty: "还没有关系相关画像。" },
  { key: "recent_state", title: "近期状态", empty: "暂无只用于近期上下文的状态。" },
  { key: "needs_confirmation", title: "需要确认", empty: "没有等待确认的记忆。" },
];

const reviewCoachCards: ReviewCoachCardConfig[] = [
  {
    kind: "today",
    title: "今日复盘",
    description: "把今天的日记、任务、记忆和资料整理更新合成本地复盘。",
    windowDays: 1,
    target: 1,
    buttonLabel: "生成今日复盘",
  },
  {
    kind: "seven_day",
    title: "7 天复盘",
    description: "总结最近一周的工作、重复主题、任务变化和新增知识。",
    windowDays: 7,
    target: 7,
    buttonLabel: "生成 7 天复盘",
  },
  {
    kind: "monthly",
    title: "月度复盘",
    description: "生成结合长期记忆、任务状态和资料整理输出的月度报告。",
    windowDays: 30,
    target: "monthly",
    buttonLabel: "生成月度复盘",
  },
];

function isPendingStatus(status: string): boolean {
  return status === "pending" || status === "applying" || status === "running";
}

function entryMatchesFilter(entry: AgentActivityLogEntry, filter: MemoryActivityFilter): boolean {
  if (filter === "all") {
    return true;
  }

  if (entry.kind === "agent_action") {
    const action = entry.action;
    if (filter === "auto") {
      return (
        action.decision === "auto" &&
        action.status === "completed" &&
        action.target_paths.length > 0 &&
        !action.reverts_action_id &&
        !action.error
      );
    }
    if (filter === "pending") {
      return isPendingStatus(action.status) || (action.decision === "ask" && action.status !== "completed");
    }
    if (filter === "reverted") {
      return action.status === "reverted" || Boolean(action.reverts_action_id);
    }
    return action.status === "failed" || Boolean(action.error);
  }

  if (entry.kind === "memory_proposal") {
    return filter === "pending" ? entry.proposal.status === "pending" : filter === "failed" && entry.proposal.status === "failed";
  }

  if (entry.kind === "continuity_proposal") {
    return filter === "pending" ? entry.proposal.status === "pending" : false;
  }

  return filter === "pending"
    ? entry.proposal.state === "pending"
    : filter === "failed" && entry.proposal.state === "failed";
}

function isMemoryControlHistoryEntry(entry: AgentActivityLogEntry): boolean {
  if (entry.kind !== "agent_action") {
    return false;
  }
  const action = entry.action;
  const trustKey = classifyMemoryTrustEntry(entry);
  const actionType = action.action_type.toLocaleLowerCase();
  const skipped = action.status === "skipped" || actionType.endsWith(".skip") || actionType.includes(".skip.");
  const reverted = action.status === "reverted" || Boolean(action.reverts_action_id) || Boolean(action.reverted_by);
  const canRevert = canRevertAgentAction(action);
  const memoryLike = trustKey !== null && trustKey !== "tasks";
  return (memoryLike || reverted) && (skipped || reverted || canRevert);
}

function entrySearchText(entry: AgentActivityLogEntry): string {
  if (entry.kind === "agent_action") {
    return getAgentActionSearchText(entry.action);
  }
  if (entry.kind === "memory_proposal") {
    const proposal = entry.proposal;
    return [proposal.target_path, proposal.written_path || "", proposal.content, proposal.preview_markdown || "", proposal.type]
      .join(" ")
      .toLocaleLowerCase();
  }
  if (entry.kind === "continuity_proposal") {
    const proposal = entry.proposal;
    return [proposal.kind, proposal.summary, proposal.evidence].join(" ").toLocaleLowerCase();
  }
  const proposal = entry.proposal;
  return [
    proposal.proposal_type,
    proposal.title,
    proposal.summary || "",
    proposal.review_summary || "",
    ...proposal.target_paths,
    ...proposal.recommended_targets,
    ...proposal.selected_targets,
  ]
    .join(" ")
    .toLocaleLowerCase();
}

function formatDate(value: string): string {
  const time = Date.parse(value);
  if (Number.isNaN(time)) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(time));
}

function formatMemoryFactStatus(status: string): string {
  switch (status) {
    case "active":
      return "使用中";
    case "candidate":
      return "等你确认";
    case "quarantined":
      return "暂不使用";
    case "archived":
      return "归档";
    case "rejected":
      return "已忽略";
    case "wrong":
      return "不准确";
    case "sensitive_blocked":
      return "敏感封存";
    default:
      return "待复核";
  }
}

function formatMemoryKindLabel(value: string | null | undefined): string {
  if (!value) {
    return "记忆";
  }
  const normalized = value.toLocaleLowerCase();
  const labels: Record<string, string> = {
    boundary: "边界",
    boundaries: "边界",
    diary: "日记",
    event: "事件",
    fact: "记住的事",
    global: "通用",
    identity: "身份",
    inference: "推断",
    preference: "偏好",
    preferences: "偏好",
    project: "项目",
    project_context: "项目",
    recent_state: "近期状态",
    relationship: "关系",
    relationships: "关系",
    temporary: "临时",
  };
  return labels[normalized] || memoryTypeLabels[normalized as MemoryProposalType] || "记忆";
}

function formatMemorySourceLabel(value: string | null | undefined): string {
  if (!value) {
    return "来源已安全摘要";
  }
  const normalized = value.toLocaleLowerCase();
  const labels: Record<string, string> = {
    chat: "来自一次聊天",
    chat_diary: "来自聊天日记",
    chat_message: "来自一次聊天",
    daily_chat: "来自聊天日记",
    diary: "来自日记整理",
    diary_object: "来自日记整理",
    explicit_user: "来自用户明确要求",
    immediate: "来自一次聊天",
    model_extracted: "来自聊天后的整理",
    slow_consolidation: "来自聊天后的整理",
    system_summary: "来自系统整理",
    user_feedback: "来自用户明确要求",
    user_message: "来自一次聊天",
  };
  return labels[normalized] || "来源已安全摘要";
}

function memoryFactSearchText(fact: MemoryGraphFact): string {
  return [
    fact.category,
    fact.subject,
    fact.predicate,
    fact.object,
    fact.status,
    fact.source_type,
    fact.memory_type || "",
    fact.entity_type || "",
  ]
    .join(" ")
    .toLocaleLowerCase();
}

function memoryFactSentence(fact: MemoryGraphFact): string {
  return `${fact.subject} ${fact.predicate} ${fact.object}`;
}

function formatMemoryFactRisk(fact: MemoryGraphFact): string {
  if (fact.status === "sensitive_blocked") {
    return "敏感封存";
  }
  if (fact.status === "quarantined" || fact.status === "wrong" || fact.status === "rejected") {
    return "需复核";
  }
  if (fact.conflicts_with || fact.confidence < 0.75) {
    return "低置信";
  }
  return "普通";
}

function formatMemoryFactReason(fact: MemoryGraphFact): string {
  const support = fact.support_count > 0 ? `${fact.support_count} 条支持` : "暂无支持计数";
  const importance = typeof fact.importance === "number" ? `，重要性 ${Math.round(fact.importance * 100)}%` : "";
  return `${formatMemorySourceLabel(fact.source_type)}，${support}${importance}`;
}

function memoryExportText(response: MemoryGraphExportPreviewResponse, format: MemoryExportFormat): string {
  return format === "json" ? response.json_preview : response.markdown_preview;
}

function memoryExportFileName(format: MemoryExportFormat): string {
  const day = new Date().toISOString().slice(0, 10);
  return `agent-pet-memory-${day}.${format === "json" ? "json" : "md"}`;
}

function temporaryProfileExpiry(): string {
  return new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
}

function profileActionConfirmText(action: MemoryProfileActionKind): string {
  const messages: Record<MemoryProfileActionKind, string> = {
    forget: "撤回后，我不会再把这条作为当前画像使用。确定继续吗？",
    mark_inaccurate: "我会把它标为不准确，并从当前画像移除。确定继续吗？",
    keep: "确认后，我之后可以在合适时参考它。确定继续吗？",
    make_temporary: "我会只在近期使用这条记忆，到期后不再当长期事实。确定继续吗？",
    mark_stale: "这条会被标记为可能过时，我会减少使用。确定继续吗？",
  };
  return messages[action];
}

function downloadTextFile(fileName: string, text: string, mimeType: string) {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function safeMemoryNotice(value: string | undefined | null): string {
  const text = value?.trim();
  if (!text) {
    return "";
  }
  if (
    /agent_run_id|memory_candidates|target_id|candidate:|fact:|\b(?:candidate|fact)[_-][A-Za-z0-9][\w-]*\b|FTS|vector|lifecycle_status|source_text|source_excerpt|Authorization|Bearer|token|[A-Za-z]:[\\/]|\\\\|\.md\b/i.test(
      text,
    )
  ) {
    return "敏感细节、原始证据和本机安全信息已隐藏。";
  }
  return text;
}

const hygieneInternalPattern =
  /\b(candidate|fact|evidence|token|authorization|bearer|fts|vector)\b|target_id|source_text|source_excerpt|agent_run_id|lifecycle_status|[A-Za-z]:[\\/]|\\\\|\/Users\//i;

function safeHygieneText(value: string | undefined | null, fallback: string): string {
  const text = value?.trim();
  if (!text || hygieneInternalPattern.test(text)) {
    return fallback;
  }
  return text;
}

function formatHygieneRisk(value: string): string {
  switch (value.toLocaleLowerCase()) {
    case "low":
      return "低风险";
    case "medium":
      return "需要确认";
    case "high":
      return "高风险";
    default:
      return "需确认";
  }
}

function formatReviewCategory(category: MemoryReviewItem["category"]): string {
  const labels: Record<MemoryReviewItem["category"], string> = {
    kept: "已保留",
    temporary: "临时",
    ignored: "已忽略",
  };
  return labels[category];
}

function formatReviewAction(action: MemoryReviewAction): string {
  const labels: Record<MemoryReviewAction, string> = {
    keep: "保留",
    edit: "编辑",
    forget: "忘记",
    only_this_week: "只保留本周",
    mark_completed: "标记完成",
  };
  return labels[action];
}

function formatSources(sources: RetrospectiveSourceReference[]): string {
  if (!sources.length) {
    return "无来源";
  }
  const labels: Record<string, string> = {
    action: "整理记录",
    agent_action: "整理记录",
    chat: "聊天",
    chat_diary: "聊天日记",
    daily_chat: "聊天日记",
    diary: "日记",
    diary_object: "日记",
    memory: "长期记忆",
    memory_candidate: "长期记忆",
    memory_fact: "长期记忆",
    task: "任务",
    wiki: "资料页",
  };
  return Array.from(new Set(sources.slice(0, 3).map((source) => labels[source.kind] || "本地来源"))).join(" / ");
}

function windowByDays(data: RetrospectiveResponse | null, days: number): RetrospectiveWindow | null {
  return data?.windows.find((window) => window.days === days) || null;
}

function countWindowCoverage(window: RetrospectiveWindow | null) {
  return {
    chatDiary: window?.summary.diary_objects || 0,
    tasks: window?.tasks.total || 0,
    longTermMemory: window?.summary.long_term_memories || 0,
    wiki: window?.summary.wiki_updates || 0,
  };
}

function reportTargetKey(target: RetrospectiveReportTarget): string {
  return String(target);
}

function reportArtifactMessage(artifact: ReviewReportArtifact): string {
  return `${artifact.title} 已保存到 ${artifact.relativePath}`;
}

function reviewKindForTarget(target: RetrospectiveReportTarget): ReviewCoachKind | null {
  if (target === 1) {
    return "today";
  }
  if (target === 7) {
    return "seven_day";
  }
  if (target === "monthly") {
    return "monthly";
  }
  return null;
}

function reviewTitleForKind(kind: ReviewCoachKind): string {
  return reviewCoachCards.find((card) => card.kind === kind)?.title || "复盘报告";
}

function hasLocalAssets(stats: LocalAssetStatsResponse): boolean {
  return (
    stats.chat_diary_days +
      stats.chat_diary_entries +
      stats.long_term_memory_count +
      stats.wiki_page_count +
      stats.task_count +
      stats.completed_task_count +
      stats.reversible_operation_count >
    0
  );
}

function countProfileProjectionItems(projection: MemoryProfileProjectionResponse | null): number {
  if (!projection) {
    return 0;
  }
  return profileProjectionGroups.reduce((total, group) => total + projection[group.key].length, 0);
}

function MemoryProfileProjectionPanel({
  projection,
  loading,
  error,
  detail,
  detailLoading,
  detailError,
  actionBusy,
  actionMessage,
  onRefresh,
  onOpenItem,
  onCloseDetail,
  onAction,
}: {
  projection: MemoryProfileProjectionResponse | null;
  loading: boolean;
  error: string;
  detail: MemoryProfileDetail | null;
  detailLoading: boolean;
  detailError: string;
  actionBusy: MemoryProfileActionKind | null;
  actionMessage: string;
  onRefresh: () => void;
  onOpenItem: (item: MemoryProfileProjectionItem) => void;
  onCloseDetail: () => void;
  onAction: (action: MemoryProfileActionKind) => void;
}) {
  const visibleCount = countProfileProjectionItems(projection);
  const filteredCount = (projection?.filtered.length || 0) + (projection?.conflicts.length || 0);
  return (
    <section className="panel feature-window-panel memory-profile-panel" aria-label="只读记忆概览">
      <div className="section-heading">
        <strong>我现在记得什么</strong>
        <span>
          {visibleCount > 0
            ? `正在展示 ${visibleCount} 条以后聊天会参考的内容。`
            : "我还没有形成稳定画像，继续聊天后会在你确认下逐步整理。"}
        </span>
      </div>
      <div className="memory-profile-toolbar">
        <span>
          <ShieldAlert size={15} />
          只读查看，不会改动记忆
        </span>
        <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          刷新记忆
        </button>
      </div>
      {error ? <p className="field-note error">{error}</p> : null}
      {loading && !projection ? (
        <EmptyState text="正在整理我可以安全展示的记忆。" />
      ) : projection && visibleCount > 0 ? (
        <>
          <div className="memory-profile-grid">
            {profileProjectionGroups.map((group) => (
              <MemoryProfileProjectionGroup
                key={group.key}
                title={group.title}
                empty={group.empty}
                items={projection[group.key]}
                onOpenItem={onOpenItem}
              />
            ))}
          </div>
          {filteredCount > 0 ? (
            <details className="memory-profile-filtered">
              <summary>
                <strong>已过滤或已替换</strong>
                <span>{filteredCount} 条不会作为当前画像使用</span>
              </summary>
              <div className="memory-profile-filtered-grid">
                <MemoryProfileProjectionGroup
                  title="已替换"
                  empty="没有已替换的旧记忆。"
                  items={projection.conflicts}
                  onOpenItem={onOpenItem}
                  compact
                />
                <MemoryProfileProjectionGroup
                  title="已隐藏"
                  empty="没有被隐藏的记忆。"
                  items={projection.filtered}
                  onOpenItem={onOpenItem}
                  compact
                />
              </div>
            </details>
          ) : null}
          <p className="field-note">{safeMemoryNotice(projection.redaction_note)}</p>
        </>
      ) : (
        <EmptyState text="我还没有形成稳定记忆，继续聊天后会在你确认下逐步整理。" />
      )}
      {detail || detailLoading || detailError ? (
        <MemoryProfileDetailDrawer
          detail={detail}
          loading={detailLoading}
          error={detailError}
          actionBusy={actionBusy}
          actionMessage={actionMessage}
          onClose={onCloseDetail}
          onAction={onAction}
        />
      ) : null}
    </section>
  );
}

function MemoryProfileProjectionGroup({
  title,
  empty,
  items,
  onOpenItem,
  compact = false,
}: {
  title: string;
  empty: string;
  items: MemoryProfileProjectionItem[];
  onOpenItem: (item: MemoryProfileProjectionItem) => void;
  compact?: boolean;
}) {
  return (
    <section className={`memory-profile-group ${compact ? "compact" : ""}`} aria-label={title}>
      <div className="memory-profile-group-head">
        <strong>{title}</strong>
        <span>{items.length} 条</span>
      </div>
      {items.length > 0 ? (
        <div className="memory-profile-item-list">
          {items.slice(0, compact ? 4 : 6).map((item) => (
            <button
              key={item.id}
              type="button"
              className="memory-profile-item"
              onClick={() => onOpenItem(item)}
              aria-label={`查看记忆详情：${item.summary}`}
            >
              <strong>{item.summary}</strong>
              <div>
                <span>{item.status_label}</span>
                <span>{item.risk_label}</span>
                <span>{item.permissions_summary}</span>
              </div>
              <p>
                来自：{item.source_label}。我会在合适时参考这条记忆。
              </p>
            </button>
          ))}
        </div>
      ) : (
        <p className="memory-profile-empty">{empty}</p>
      )}
    </section>
  );
}

function MemoryProfileDetailDrawer({
  detail,
  loading,
  error,
  actionBusy,
  actionMessage,
  onClose,
  onAction,
}: {
  detail: MemoryProfileDetail | null;
  loading: boolean;
  error: string;
  actionBusy: MemoryProfileActionKind | null;
  actionMessage: string;
  onClose: () => void;
  onAction: (action: MemoryProfileActionKind) => void;
}) {
  return (
    <aside className="memory-profile-detail-drawer" role="dialog" aria-label="记忆详情">
      <div className="memory-profile-detail-head">
        <div>
          <strong>记忆详情</strong>
          <span>只显示安全摘要，不展示原始证据</span>
        </div>
        <button type="button" className="secondary" onClick={onClose} aria-label="关闭记忆详情">
          <XCircle size={16} />
          关闭
        </button>
      </div>
      {loading ? (
        <EmptyState text="正在整理这条记忆的详情…" />
      ) : error ? (
        <p className="field-note error">{error}</p>
      ) : detail ? (
        <div className="memory-profile-detail-body">
          <strong className="memory-profile-detail-summary">{detail.summary}</strong>
          <dl className="memory-profile-detail-list">
            <div>
              <dt>分类</dt>
              <dd>{detail.category_label}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{detail.status_label}</dd>
            </div>
            <div>
              <dt>可信度</dt>
              <dd>{detail.confidence_label}</dd>
            </div>
            <div>
              <dt>重要性</dt>
              <dd>{detail.importance_label}</dd>
            </div>
            <div>
              <dt>来源</dt>
              <dd>{detail.source_label}</dd>
            </div>
            <div>
              <dt>更新时间</dt>
              <dd>{formatDate(detail.updated_at)}</dd>
            </div>
          </dl>
          <div className="memory-profile-detail-tags" aria-label="使用权限">
            {detail.permissions.map((permission) => (
              <span key={permission}>{permission}</span>
            ))}
          </div>
          <MemoryProfileSourceSummaryBlock detail={detail} />
          {detail.safety_note ? <p className="field-note">{detail.safety_note}</p> : null}
          {actionMessage ? <p className="field-note success">{actionMessage}</p> : null}
          <div className="memory-profile-detail-actions" aria-label="可用操作">
            {detail.available_actions.length > 0 ? (
              detail.available_actions.map((action) => (
                <button
                  key={action.action}
                  type="button"
                  className="secondary"
                  disabled={actionBusy !== null}
                  onClick={() => onAction(action.action)}
                >
                  {actionBusy === action.action ? <Loader2 className="spin" size={15} /> : <Check size={15} />}
                  {action.label}
                </button>
              ))
            ) : (
              <span>这条记忆当前没有可用操作。</span>
            )}
          </div>
        </div>
      ) : (
        <EmptyState text="这条记忆暂无可展示详情。" />
      )}
    </aside>
  );
}

function MemoryProfileSourceSummaryBlock({ detail }: { detail: MemoryProfileDetail }) {
  const sourceSummary = detail.source_summary;
  if (!sourceSummary) {
    return (
      <section className="memory-profile-source-summary" aria-label="来源说明">
        <strong>来源说明</strong>
        <p>暂时没有可安全展示的来源说明。</p>
      </section>
    );
  }

  const label = safeMemoryNotice(sourceSummary.label) || "来源说明";
  const description = safeMemoryNotice(sourceSummary.description) || "暂时没有可安全展示的来源说明。";
  const evidenceCount = safeMemoryNotice(sourceSummary.evidence_count_label);
  const lastSeen = safeMemoryNotice(sourceSummary.last_seen_label);
  const safetyNote = safeMemoryNotice(sourceSummary.safety_note);

  return (
    <section className="memory-profile-source-summary" aria-label="来源说明">
      <div>
        <strong>来源说明</strong>
        <span>{label}</span>
      </div>
      <p>{description}</p>
      {evidenceCount || lastSeen ? (
        <div className="memory-profile-source-meta">
          {evidenceCount ? <span>{evidenceCount}</span> : null}
          {lastSeen ? <span>{lastSeen}</span> : null}
        </div>
      ) : null}
      {safetyNote ? <p className="field-note">{safetyNote}</p> : null}
    </section>
  );
}

function LocalAssetDashboard({
  stats,
  loading,
  error,
  onRefresh,
}: {
  stats: LocalAssetStatsResponse | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
}) {
  const latest = stats?.latest_organization_at ? formatDate(stats.latest_organization_at) : "暂无";
  const taskValue = stats ? `${stats.completed_task_count}/${stats.task_count}` : "0/0";
  const items = [
    { label: "聊天日记天数", value: String(stats?.chat_diary_days ?? 0), meta: `${stats?.chat_diary_entries ?? 0} 条记录`, icon: NotebookTabs },
    { label: "长期记忆", value: String(stats?.long_term_memory_count ?? 0), meta: "使用中 / 待确认", icon: Database },
    { label: "资料页", value: String(stats?.wiki_page_count ?? 0), meta: "不含核心维护页", icon: BookOpen },
    { label: "任务完成", value: taskValue, meta: "完成 / 总数", icon: CheckCircle2 },
    { label: "最近整理", value: latest, meta: "本机记录", icon: History },
    { label: "可撤回操作", value: String(stats?.reversible_operation_count ?? 0), meta: "尚未撤回", icon: RotateCcw },
  ];
  return (
    <section className="panel feature-window-panel local-asset-dashboard" aria-label="本机积累">
      <div className="section-heading">
        <strong>本机积累</strong>
        <span>
          {stats?.vault_configured
            ? "从本机数据库与文件夹只读汇总，不上传遥测。"
            : "尚未绑定本机文件夹；先显示本机数据库中的积累。"}
        </span>
      </div>
      <div className="local-asset-toolbar">
        <span className="local-asset-scope">
          <BarChart3 size={16} />
          本地第二大脑
        </span>
        <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
        刷新积累
        </button>
      </div>
      {error ? <p className="field-note error">{error}</p> : null}
      <div className="local-asset-stat-grid">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <article key={item.label} className="local-asset-card">
              <Icon size={18} />
              <div>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.meta}</small>
              </div>
            </article>
          );
        })}
      </div>
      {!loading && stats && !hasLocalAssets(stats) ? (
        <EmptyState text="还没有本机积累。完成一次聊天、记录长期记忆或生成复盘后，这里会显示积累情况。" />
      ) : null}
      {loading && !stats ? <EmptyState text="正在读取本机积累统计。" /> : null}
    </section>
  );
}

function RetrospectiveWindowPanel({
  window,
  generatingReport,
  onGenerateReport,
}: {
  window: RetrospectiveWindow;
  generatingReport: RetrospectiveReportTarget | null;
  onGenerateReport: (days: number) => void;
}) {
  const busy = generatingReport === window.days;
  return (
    <article className="retrospective-window-panel">
      <div className="section-heading compact">
        <strong>{window.label}回顾</strong>
        <span>
          {formatDate(window.start_at)} - {formatDate(window.end_at)}
        </span>
      </div>
      <div className="retrospective-stat-grid">
        <span>日记 {window.summary.diary_objects || 0}</span>
        <span>长期记忆 {window.summary.long_term_memories || 0}</span>
        <span>任务 {window.tasks.total}</span>
      <span>资料整理 {window.summary.wiki_updates || 0}</span>
      </div>
      {window.has_data ? (
        <>
          <div className="retrospective-section">
            <strong>高频主题</strong>
            {window.topics.length ? (
              window.topics.slice(0, 5).map((topic) => (
                <p key={topic.name}>
                  {topic.name} · {topic.count} 次 <small>{formatSources(topic.sources)}</small>
                </p>
              ))
            ) : (
              <p>暂无主题聚合。</p>
            )}
          </div>
          <div className="retrospective-section">
            <strong>任务变化</strong>
            <p>
              完成 {window.tasks.completed}，未完成 {window.tasks.pending}，取消 {window.tasks.cancelled}，逾期 {window.tasks.overdue}
            </p>
          </div>
          <div className="retrospective-section">
            <strong>新增记忆和资料整理</strong>
            {window.long_term_memories.slice(0, 3).map((item) => (
              <p key={item.id}>
                {item.summary} <small>{formatMemoryKindLabel(item.category)} / {formatMemoryFactStatus(item.status)}</small>
              </p>
            ))}
            {window.wiki_updates.slice(0, 3).map((item) => (
              <p key={item.action_id || item.path}>
                {item.title} <small>{item.path}</small>
              </p>
            ))}
            {!window.long_term_memories.length && !window.wiki_updates.length ? <p>暂无新增长期记忆或资料整理。</p> : null}
          </div>
          <div className="retrospective-section">
            <strong>重复偏好/关注点</strong>
            {window.repeated_preferences.length ? (
              window.repeated_preferences.slice(0, 5).map((item) => (
                <p key={item.name}>
                  {item.name} · {item.count} 次 <small>{formatSources(item.sources)}</small>
                </p>
              ))
            ) : (
              <p>暂无重复出现的偏好或关注点。</p>
            )}
          </div>
        </>
      ) : (
        <EmptyState text="这个时间窗口还没有可回顾的本机积累。先完成一次聊天、任务或资料整理后再回来查看。" />
      )}
      <button type="button" className="secondary" onClick={() => onGenerateReport(window.days)} disabled={busy}>
        {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
        生成本地报告
      </button>
    </article>
  );
}

function ReviewCoverageList({ window }: { window: RetrospectiveWindow | null }) {
  const coverage = countWindowCoverage(window);
  const items = [
    { label: "聊天日记", value: coverage.chatDiary },
    { label: "任务", value: coverage.tasks },
    { label: "长期记忆", value: coverage.longTermMemory },
    { label: "资料整理", value: coverage.wiki },
  ];
  return (
    <dl className="review-coverage-list" aria-label="来源覆盖">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ReviewReportArtifactCard({
  artifact,
  canReveal,
  onReveal,
}: {
  artifact: ReviewReportArtifact;
  canReveal: boolean;
  onReveal: (relativePath: string, mode: DesktopVaultRevealMode) => void;
}) {
  return (
    <div className="review-report-artifact" aria-label={`${artifact.title}报告产物`}>
      <div>
        <strong>{artifact.relativePath}</strong>
        <span>{artifact.status}</span>
      </div>
      {canReveal ? (
        <div className="button-row compact-actions">
          <button type="button" className="secondary" onClick={() => onReveal(artifact.relativePath, "open")}>
            <ExternalLink size={15} />
            打开报告
          </button>
          <button type="button" className="secondary" onClick={() => onReveal(artifact.relativePath, "show")}>
            <FolderSearch size={15} />
            定位报告
          </button>
        </div>
      ) : (
        <p className="field-note">当前浏览器视图无法打开本地保存文件位置。</p>
      )}
    </div>
  );
}

function ReviewCoachCard({
  config,
  window,
  generatingReport,
  artifact,
  canRevealReports,
  onGenerate,
  onRevealReport,
}: {
  config: ReviewCoachCardConfig;
  window: RetrospectiveWindow | null;
  generatingReport: RetrospectiveReportTarget | null;
  artifact?: ReviewReportArtifact;
  canRevealReports: boolean;
  onGenerate: (config: ReviewCoachCardConfig) => void;
  onRevealReport: (relativePath: string, mode: DesktopVaultRevealMode) => void;
}) {
  const busy = generatingReport !== null && reportTargetKey(generatingReport) === reportTargetKey(config.target);
  return (
    <article className="review-coach-card">
      <div className="section-heading compact">
        <strong>{config.title}</strong>
        <span>{window ? `${formatDate(window.start_at)} - ${formatDate(window.end_at)}` : config.description}</span>
      </div>
      <p>{config.description}</p>
      <ReviewCoverageList window={window} />
      {window?.has_data ? (
        <p className="field-note">
          使用 {window.summary.diary_objects || 0} 条日记、{window.tasks.total} 个任务、{window.summary.long_term_memories || 0} 条长期记忆和 {window.summary.wiki_updates || 0} 次资料整理。
        </p>
      ) : (
        <p className="field-note">这个复盘窗口还没有本地来源数据。</p>
      )}
      <button type="button" onClick={() => onGenerate(config)} disabled={busy}>
        {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
        {config.buttonLabel}
      </button>
      {artifact ? (
        <ReviewReportArtifactCard artifact={artifact} canReveal={canRevealReports} onReveal={onRevealReport} />
      ) : null}
    </article>
  );
}

function ReviewCoachPanel({
  retrospectives,
  loading,
  error,
  message,
  generatingReport,
  reportArtifacts,
  canRevealReports,
  onRefresh,
  onGenerate,
  onRevealReport,
}: {
  retrospectives: RetrospectiveResponse | null;
  loading: boolean;
  error: string;
  message: string;
  generatingReport: RetrospectiveReportTarget | null;
  reportArtifacts: Partial<Record<ReviewCoachKind, ReviewReportArtifact>>;
  canRevealReports: boolean;
  onRefresh: () => void;
  onGenerate: (config: ReviewCoachCardConfig) => void;
  onRevealReport: (relativePath: string, mode: DesktopVaultRevealMode) => void;
}) {
  return (
    <section className="panel feature-window-panel review-coach-panel" aria-label="复盘助手">
      <div className="section-heading">
        <strong>复盘助手</strong>
        <span>
          {retrospectives
            ? `来源快照生成于 ${formatDate(retrospectives.generated_at)}。`
            : "读取本地活动并生成复盘报告，无需打开聊天。"}
        </span>
      </div>
      <div className="button-row">
        <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          刷新复盘来源
        </button>
      </div>
      {error ? <p className="field-note error">{error}</p> : null}
      {message ? <p className="field-note">{message}</p> : null}
      <div className="review-coach-grid">
        {reviewCoachCards.map((config) => (
          <ReviewCoachCard
            key={config.kind}
            config={config}
            window={windowByDays(retrospectives, config.windowDays)}
            generatingReport={generatingReport}
            artifact={reportArtifacts[config.kind]}
            canRevealReports={canRevealReports}
            onGenerate={onGenerate}
            onRevealReport={onRevealReport}
          />
        ))}
      </div>
      {loading && !retrospectives ? <EmptyState text="正在加载本地复盘来源。" /> : null}
    </section>
  );
}

function SearchResultCard({ result }: { result: MemorySearchResult }) {
  return (
    <article className="memory-search-result-card">
      <strong>{result.title || result.relative_path}</strong>
      <span>{result.snippet}</span>
      <small>
        {result.relative_path}
        {result.heading ? ` / ${result.heading}` : ""} / {result.source_scope || "memory"} / {Math.round(result.score * 100)}%
      </small>
    </article>
  );
}

function MemorySearchWorkbench({
  query,
  status,
  results,
  lastQuery,
  onQueryChange,
  onTrySearch,
  onSearch,
}: {
  query: string;
  status: MemoryAsyncStatus;
  results: MemorySearchResult[];
  lastQuery: string;
  onQueryChange: (query: string) => void;
  onTrySearch?: () => void;
  onSearch: (event: FormEvent) => void;
}) {
  const searching = status === "loading";
  return (
    <section className="memory-workbench-search" aria-label="记忆搜索">
      {onTrySearch ? (
        <div className="guided-trial-actions" aria-label="记忆搜索快捷操作">
          <button type="button" className="secondary" onClick={onTrySearch}>
            <Search size={16} />
            搜索记忆
          </button>
        </div>
      ) : null}
      <form className="memory-workbench-search-form" onSubmit={onSearch}>
        <label>
          <span>搜索记忆</span>
          <input
            type="search"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder={productCopy.memoryPage.searchPlaceholder}
          />
        </label>
        <button type="submit" disabled={searching || !query.trim()}>
          {searching ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
          搜索
        </button>
      </form>
      <div className="memory-search-results" aria-label="记忆搜索结果">
        {results.length > 0 ? (
          results.map((result) => <SearchResultCard key={`${result.note_id}-${result.chunk_id}`} result={result} />)
        ) : status === "empty" ? (
          <EmptyState text={`没有找到“${lastQuery}”的匹配记忆。`} />
        ) : status === "error" ? (
          <EmptyState text="记忆搜索失败，请稍后重试。" />
        ) : (
          <EmptyState text="输入关键词后可直接搜索记忆，不需要打开聊天。" />
        )}
      </div>
    </section>
  );
}

function AddMemoryForm({
  draft,
  onDraftChange,
  onTryPreference,
  onSubmit,
}: {
  draft: MemoryProposalDraft;
  onDraftChange: (patch: Partial<MemoryProposalDraft>) => void;
  onTryPreference?: () => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form className="memory-add-form" aria-label="新增记忆表单" onSubmit={onSubmit}>
      <div className="section-heading compact">
        <strong>新增记忆</strong>
        <span>不经过聊天也可以手动添加一条等你确认的记忆。</span>
      </div>
      {onTryPreference ? (
        <div className="guided-trial-actions" aria-label="记忆快捷操作">
          <button type="button" className="secondary" onClick={onTryPreference}>
            <PlusCircle size={16} />
            保存一个偏好
          </button>
        </div>
      ) : null}
      <div className="memory-add-grid">
        <label>
          <span>类型</span>
          <select
            value={draft.type}
            onChange={(event) => onDraftChange({ type: event.target.value as MemoryProposalType })}
          >
            {memoryTypes.map((type) => (
              <option key={type} value={type}>
                {memoryTypeLabels[type]}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>目标笔记</span>
          <input
            value={draft.target_path}
            onChange={(event) => onDraftChange({ target_path: event.target.value })}
            placeholder="Inbox/Pending Memories.md"
          />
        </label>
      </div>
      <label>
        <span>记忆内容</span>
        <textarea
          value={draft.content}
          onChange={(event) => onDraftChange({ content: event.target.value })}
          placeholder="我偏好简洁的发布检查清单。"
        />
      </label>
      <button type="submit" disabled={!draft.content.trim() || !draft.target_path.trim()}>
        <PlusCircle size={16} />
        新增记忆
      </button>
    </form>
  );
}

function MemoryProposalReviewList({
  proposals,
  loading,
  actionIds,
  onAct,
  onRefresh,
}: {
  proposals: MemoryProposal[];
  loading: boolean;
  actionIds: Set<string>;
  onAct: (proposalId: string, action: "confirm" | "reject") => void;
  onRefresh: () => void;
}) {
  const pending = proposals.filter((proposal) => proposal.status === "pending");
  return (
    <section className="memory-review-list" aria-label="等你确认的记忆">
      <div className="section-heading compact">
        <strong>等你确认</strong>
        <span>{pending.length} 条等你确认 / 共 {proposals.length} 条待处理记忆。</span>
      </div>
      <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
        {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
        刷新待确认
      </button>
      <div className="proposal-list memory-proposal-review-list">
        {proposals.length > 0 ? (
          proposals.map((proposal) => (
            <MemoryProposalActivityCard
              key={proposal.proposal_id}
              entry={{
                kind: "memory_proposal",
                id: `memory-proposal-${proposal.proposal_id}`,
                sortAt: proposal.proposal_id,
                sortKey: 0,
                proposal,
              }}
              busy={actionIds.has(proposal.proposal_id)}
              onAct={onAct}
            />
          ))
        ) : loading ? (
          <EmptyState text="正在加载待确认记忆。" />
        ) : (
          <EmptyState text="没有待确认记忆。上方可以手动添加一条希望我记住的事。" />
        )}
      </div>
    </section>
  );
}

function MemoryFactCard({
  fact,
  busy,
  onAction,
}: {
  fact: MemoryGraphFact;
  busy: boolean;
  onAction: (factId: string, action: "wrong" | "archive" | "sensitive_block" | "confirm") => void;
}) {
  return (
    <article className={`memory-graph-fact ${fact.status}`}>
      <div className="memory-graph-fact-main">
        <strong>{memoryFactSentence(fact)}</strong>
        <div className="memory-graph-fact-meta">
          <span>{formatMemoryFactStatus(fact.status)}</span>
          <span>{formatMemoryKindLabel(fact.category)}</span>
          <span>风险 {formatMemoryFactRisk(fact)}</span>
          <span>我有多确定 {Math.round(fact.confidence * 100)}%</span>
          <span>支持 {fact.support_count}</span>
        </div>
        <dl className="memory-graph-fact-details" aria-label="记忆来源和判断">
          <div>
            <dt>来源</dt>
            <dd>
              {formatMemorySourceLabel(fact.source_type)}
              {fact.memory_type ? ` / ${formatMemoryKindLabel(fact.memory_type)}` : ""}
            </dd>
          </div>
          <div>
            <dt>记住原因</dt>
            <dd>{formatMemoryFactReason(fact)}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>
              {formatMemoryFactStatus(fact.status)}
              {fact.updated_at ? ` / 更新于 ${formatDate(fact.updated_at)}` : ""}
            </dd>
          </div>
          {fact.conflicts_with ? (
            <div>
              <dt>冲突</dt>
              <dd>{safeMemoryNotice(fact.conflicts_with) || "存在可能冲突的旧记忆，细节已隐藏。"}</dd>
            </div>
          ) : null}
        </dl>
      </div>
      <div className="memory-graph-fact-actions">
        {fact.status !== "active" ? (
          <button type="button" className="secondary" onClick={() => onAction(fact.fact_id, "confirm")} disabled={busy}>
            {busy ? <Loader2 className="spin" size={15} /> : <Check size={15} />}
            确认
          </button>
        ) : null}
        {fact.status !== "wrong" ? (
          <button type="button" className="secondary" onClick={() => onAction(fact.fact_id, "wrong")} disabled={busy}>
            {busy ? <Loader2 className="spin" size={15} /> : <XCircle size={15} />}
            标为不准确
          </button>
        ) : null}
        {fact.status !== "archived" ? (
          <button type="button" className="secondary" onClick={() => onAction(fact.fact_id, "archive")} disabled={busy}>
            {busy ? <Loader2 className="spin" size={15} /> : <Archive size={15} />}
            归档
          </button>
        ) : null}
        {fact.status !== "sensitive_blocked" ? (
          <button type="button" className="secondary" onClick={() => onAction(fact.fact_id, "sensitive_block")} disabled={busy}>
            {busy ? <Loader2 className="spin" size={15} /> : <ShieldAlert size={15} />}
            敏感封存
          </button>
        ) : null}
      </div>
    </article>
  );
}

function MemoryWorkspaceTabs({
  activeTab,
  onChange,
}: {
  activeTab: MemoryWorkspaceTabKey;
  onChange: (tab: MemoryWorkspaceTabKey) => void;
}) {
  return (
    <section className="panel feature-window-panel memory-workspace-shell" aria-label="记忆工作台入口">
      <div className="section-heading">
        <strong>记忆工作台</strong>
        <span>把个人记忆、日记情景和资料库收在同一个本机工作区。</span>
      </div>
      <div className="memory-workspace-tabs" role="tablist" aria-label="记忆工作台分区">
        {memoryWorkspaceTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            id={`memory-workspace-tab-${tab.key}`}
            className={`memory-workspace-tab ${activeTab === tab.key ? "active" : ""}`}
            role="tab"
            aria-label={tab.label}
            aria-selected={activeTab === tab.key}
            aria-controls={`memory-workspace-panel-${tab.key}`}
            onClick={() => onChange(tab.key)}
          >
            <strong>{tab.label}</strong>
            <span>{tab.description}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function MemoryWorkspacePlaceholder({
  title,
  description,
  helper,
}: {
  title: string;
  description: string;
  helper: string;
}) {
  return (
    <section className="panel feature-window-panel memory-workspace-placeholder" aria-label={title}>
      <div className="section-heading">
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <EmptyState text={helper} />
    </section>
  );
}

function MemoryImportPanel() {
  return (
    <section className="panel feature-window-panel memory-import-panel" aria-label="资料导入入口">
      <div className="section-heading">
        <strong>资料库</strong>
        <span>把文档、链接和想法整理成以后能找回的资料；它现在属于记忆工作台。</span>
      </div>
      <div className="memory-import-grid">
        <article>
          <BookOpen size={18} aria-hidden="true" />
          <strong>导入资料</strong>
          <p>粘贴来源材料，预览整理计划，再写入本机资料库。</p>
        </article>
        <article>
          <Search size={18} aria-hidden="true" />
          <strong>搜索档案</strong>
          <p>从整理出的资料页和记忆线索里找回上下文。</p>
        </article>
        <article>
          <Archive size={18} aria-hidden="true" />
          <strong>维护档案</strong>
          <p>索引、日志和只读检查仍在资料库内部保留。</p>
        </article>
      </div>
      <button type="button" className="secondary memory-import-open" onClick={() => { window.location.hash = "#world"; }}>
        <ExternalLink size={16} />
        打开资料库
      </button>
    </section>
  );
}

function MemoryFactSection({
  title,
  description,
  facts,
  loading,
  emptyText,
  busyId,
  onAction,
}: {
  title: string;
  description: string;
  facts: MemoryGraphFact[];
  loading: boolean;
  emptyText: string;
  busyId: string | null;
  onAction: (factId: string, action: "wrong" | "archive" | "sensitive_block" | "confirm") => void;
}) {
  return (
    <section className="memory-fact-section" aria-label={title}>
      <div className="section-heading compact">
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <div className="memory-graph-list">
        {facts.length > 0 ? (
          facts.map((fact) => (
            <MemoryFactCard
              key={fact.fact_id}
              fact={fact}
              busy={busyId === fact.fact_id}
              onAction={onAction}
            />
          ))
        ) : loading ? (
          <EmptyState text="正在加载长期记忆。" />
        ) : (
          <EmptyState text={emptyText} />
        )}
      </div>
    </section>
  );
}

function MemoryPriorityPanel({
  activeFacts,
  candidateFacts,
  memoryFactsLoading,
  memoryFactBusyId,
  pendingProposals,
  loadingMemoryProposals,
  memoryProposalActionIds,
  recentHistoryEntries,
  onMemoryFactAction,
  onMemoryProposalAct,
  onLoadMemoryProposals,
  renderEntry,
}: {
  activeFacts: MemoryGraphFact[];
  candidateFacts: MemoryGraphFact[];
  memoryFactsLoading: boolean;
  memoryFactBusyId: string | null;
  pendingProposals: MemoryProposal[];
  loadingMemoryProposals: boolean;
  memoryProposalActionIds: Set<string>;
  recentHistoryEntries: AgentActivityLogEntry[];
  onMemoryFactAction: (factId: string, action: "wrong" | "archive" | "sensitive_block" | "confirm") => void;
  onMemoryProposalAct: (proposalId: string, action: "confirm" | "reject") => void;
  onLoadMemoryProposals: () => void;
  renderEntry: (entry: AgentActivityLogEntry) => ReactNode;
}) {
  const activePreview = activeFacts.slice(0, 3);
  const proposalPreview = pendingProposals.slice(0, 3);
  const candidatePreview = candidateFacts.slice(0, 3);
  const historyPreview = recentHistoryEntries.slice(0, 3);

  return (
    <section className="panel feature-window-panel memory-primary-panel" aria-label="记忆主视图">
      <div className="section-heading">
        <strong>{productCopy.memoryPage.primaryPanelTitle}</strong>
        <span>{productCopy.memoryPage.primaryPanelDescription}</span>
      </div>

      <div className="memory-priority-grid">
        <section className="memory-priority-block" aria-label={productCopy.memoryPage.activeSectionTitle}>
          <div className="section-heading compact">
            <strong>{productCopy.memoryPage.activeSectionTitle}</strong>
            <span>{activeFacts.length} 条以后聊天会参考。</span>
          </div>
          <div className="memory-graph-list memory-priority-list">
            {activePreview.length > 0 ? (
              activePreview.map((fact) => (
                <MemoryFactCard
                  key={fact.fact_id}
                  fact={fact}
                  busy={memoryFactBusyId === fact.fact_id}
                  onAction={onMemoryFactAction}
                />
              ))
            ) : memoryFactsLoading ? (
              <EmptyState text="正在加载长期记忆。" />
            ) : (
              <EmptyState text={productCopy.memoryPage.emptyState} />
            )}
          </div>
        </section>

        <section className="memory-priority-block" aria-label={productCopy.memoryPage.pendingSectionTitle}>
          <div className="section-heading compact">
            <strong>{productCopy.memoryPage.pendingSectionTitle}</strong>
            <span>{pendingProposals.length + candidateFacts.length} 条需要你决定是否留下。</span>
          </div>
          <button type="button" className="secondary memory-priority-refresh" onClick={onLoadMemoryProposals} disabled={loadingMemoryProposals}>
            {loadingMemoryProposals ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            刷新待确认
          </button>
          <div className="proposal-list memory-priority-list">
            {proposalPreview.length > 0 ? (
              proposalPreview.map((proposal) => (
                <MemoryProposalActivityCard
                  key={proposal.proposal_id}
                  entry={{
                    kind: "memory_proposal",
                    id: `memory-proposal-${proposal.proposal_id}`,
                    sortAt: proposal.proposal_id,
                    sortKey: 0,
                    proposal,
                  }}
                  busy={memoryProposalActionIds.has(proposal.proposal_id)}
                  onAct={onMemoryProposalAct}
                />
              ))
            ) : candidatePreview.length > 0 ? (
              candidatePreview.map((fact) => (
                <MemoryFactCard
                  key={fact.fact_id}
                  fact={fact}
                  busy={memoryFactBusyId === fact.fact_id}
                  onAction={onMemoryFactAction}
                />
              ))
            ) : loadingMemoryProposals || memoryFactsLoading ? (
              <EmptyState text="正在加载待确认记忆。" />
            ) : (
              <EmptyState text="当前没有待确认的记忆。" />
            )}
          </div>
        </section>

        <section className="memory-priority-block" aria-label={productCopy.memoryPage.recentHistoryTitle}>
          <div className="section-heading compact">
            <strong>{productCopy.memoryPage.recentHistoryTitle}</strong>
            <span>看看最近哪些记忆被跳过、撤回，或还能撤回。</span>
          </div>
          <div className="proposal-list agent-activity-log-list feature-activity-list memory-priority-list">
            {historyPreview.length > 0 ? (
              historyPreview.map((entry) => renderEntry(entry))
            ) : (
              <EmptyState text="最近没有撤回或跳过的记忆记录。" />
            )}
          </div>
        </section>
      </div>
    </section>
  );
}

function WeeklyMemoryReviewPanel({
  review,
  loading,
  error,
  busyId,
  onRefresh,
  onAction,
}: {
  review: MemoryReviewResponse | null;
  loading: boolean;
  error: string;
  busyId: string | null;
  onRefresh: () => void;
  onAction: (item: MemoryReviewItem, action: MemoryReviewAction) => void;
}) {
  const summary = review?.summary || { kept: 0, temporary: 0, ignored: 0 };
  return (
    <section className="weekly-memory-review-panel" aria-label="本周记忆复核">
      <div className="section-heading">
        <strong>本周记忆复核</strong>
        <span>短列表显示已保留、临时和已忽略的记忆；高风险写入仍按确认规则处理。</span>
      </div>
      <div className="memory-trust-group-grid">
        <article className="memory-trust-group-card active">
          <strong>已保留</strong>
          <span>{summary.kept}</span>
          <p>可继续影响回答的稳定记忆。</p>
        </article>
        <article className="memory-trust-group-card active">
          <strong>临时</strong>
          <span>{summary.temporary}</span>
          <p>带有效期或本周上下文的记忆。</p>
        </article>
        <article className="memory-trust-group-card active">
          <strong>已忽略</strong>
          <span>{summary.ignored}</span>
          <p>等你确认、暂不使用，或没有进入长期使用的内容。</p>
        </article>
      </div>
      <div className="button-row">
        <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          刷新复核
        </button>
      </div>
      {error ? <p className="field-note error">{error}</p> : null}
      {review?.redaction_note ? <p className="field-note">{safeMemoryNotice(review.redaction_note)}</p> : null}
      <div className="proposal-list memory-proposal-review-list">
        {review && review.items.length > 0 ? (
          review.items.map((item) => (
            <article key={item.review_id} className={`memory-graph-fact ${item.category}`}>
              <div className="memory-graph-fact-main">
                <strong>{item.summary}</strong>
                <div className="memory-graph-fact-meta">
                  <span>{formatReviewCategory(item.category)}</span>
                  <span>{formatMemoryKindLabel(item.memory_kind || item.target_type)}</span>
                  <span>{formatMemoryFactStatus(item.lifecycle_status)}</span>
                  <span>我有多确定 {Math.round(item.confidence * 100)}%</span>
                </div>
                <p>
                  {formatMemorySourceLabel(item.source)}
                  {item.expires_at ? ` / 到期时间 ${formatDate(item.expires_at)}` : ""}
                  {item.updated_at ? ` / 更新于 ${formatDate(item.updated_at)}` : ""}
                </p>
              </div>
              <div className="memory-graph-fact-actions">
                {item.allowed_actions.map((action) => (
                  <button
                    key={action}
                    type="button"
                    className="secondary"
                    onClick={() => onAction(item, action)}
                    disabled={busyId === item.review_id}
                  >
                    {busyId === item.review_id ? <Loader2 className="spin" size={15} /> : <Check size={15} />}
                    {formatReviewAction(action)}
                  </button>
                ))}
              </div>
            </article>
          ))
        ) : loading ? (
          <EmptyState text="正在加载本周记忆复核。" />
        ) : (
          <EmptyState text="这周还没有可复核的记忆项。" />
        )}
      </div>
    </section>
  );
}

function MemoryHygieneSuggestionPanel({
  preview,
  loading,
  error,
  busyId,
  onScan,
  onApply,
}: {
  preview: MemoryHygienePreviewResponse | null;
  loading: boolean;
  error: string;
  busyId: string | null;
  onScan: () => void;
  onApply: (item: MemoryHygieneSuggestion) => void;
}) {
  const suggestions = preview?.suggestions || [];
  return (
    <section className="weekly-memory-review-panel memory-hygiene-panel" aria-label="整理建议">
      <div className="section-heading">
        <strong>整理建议</strong>
        <span>先扫描，再逐条确认；这里只显示安全摘要。</span>
      </div>
      <div className="button-row">
        <button type="button" className="secondary" onClick={onScan} disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          扫描整理建议
        </button>
      </div>
      {error ? <p className="field-note error">{error}</p> : null}
      {preview?.redaction_note ? <p className="field-note">{safeMemoryNotice(preview.redaction_note)}</p> : null}
      <div className="proposal-list memory-hygiene-suggestion-list">
        {loading ? (
          <EmptyState text="正在检查可以安全整理的记忆……" />
        ) : preview && suggestions.length === 0 ? (
          <EmptyState text="暂时没有需要整理的记忆。" />
        ) : suggestions.length > 0 ? (
          suggestions.map((item) => (
            <article key={item.id} className="memory-graph-fact memory-hygiene-suggestion">
              <div className="memory-graph-fact-main">
                <strong>{safeHygieneText(item.title, "整理建议")}</strong>
                <div className="memory-graph-fact-meta">
                  <span>{formatHygieneRisk(item.risk_tier)}</span>
                  <span>{item.requires_confirmation ? "需要确认" : "可直接整理"}</span>
                </div>
                <p>{safeHygieneText(item.summary, "这条建议的安全摘要暂时不可显示。")}</p>
                <p>{safeHygieneText(item.impact, "应用后会更新记忆状态。")}</p>
              </div>
              <div className="memory-graph-fact-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onApply(item)}
                  disabled={busyId === item.id}
                >
                  {busyId === item.id ? <Loader2 className="spin" size={15} /> : <Check size={15} />}
                  {safeHygieneText(item.action_label, "应用建议")}
                </button>
              </div>
            </article>
          ))
        ) : (
          <EmptyState text="点击扫描整理建议，我会先检查有没有可以安全处理的记忆。" />
        )}
      </div>
    </section>
  );
}

export default function MemoryWindowView({
  api,
  loading,
  error,
  entries,
  memorySearchQuery,
  memorySearchStatus,
  memorySearchResults,
  memoryLastSearchQuery,
  onMemorySearchQueryChange,
  onRunMemorySearch,
  memoryProposalDraft,
  memoryProposals,
  memoryProposalActionIds,
  loadingMemoryProposals,
  onMemoryProposalDraftChange,
  onCreateMemoryProposal,
  onActOnMemoryProposal,
  onLoadMemoryProposals,
  onRefresh,
  renderEntry,
}: MemoryWindowViewProps) {
  const [activeFilter, setActiveFilter] = useState<MemoryActivityFilter>("all");
  const [activeWorkspaceTab, setActiveWorkspaceTab] = useState<MemoryWorkspaceTabKey>("graph");
  const [searchQuery, setSearchQuery] = useState("");
  const [localAssets, setLocalAssets] = useState<LocalAssetStatsResponse | null>(null);
  const [localAssetsLoading, setLocalAssetsLoading] = useState(true);
  const [localAssetsError, setLocalAssetsError] = useState("");
  const [memoryProfileProjection, setMemoryProfileProjection] = useState<MemoryProfileProjectionResponse | null>(null);
  const [memoryProfileLoading, setMemoryProfileLoading] = useState(true);
  const [memoryProfileError, setMemoryProfileError] = useState("");
  const [memoryProfileDetail, setMemoryProfileDetail] = useState<MemoryProfileDetail | null>(null);
  const [memoryProfileDetailLoading, setMemoryProfileDetailLoading] = useState(false);
  const [memoryProfileDetailError, setMemoryProfileDetailError] = useState("");
  const [memoryProfileActionBusy, setMemoryProfileActionBusy] = useState<MemoryProfileActionKind | null>(null);
  const [memoryProfileActionMessage, setMemoryProfileActionMessage] = useState("");
  const [memoryGraphProjection, setMemoryGraphProjection] = useState<MemoryGraphProjectionResponse | null>(null);
  const [memoryGraphLoading, setMemoryGraphLoading] = useState(true);
  const [memoryGraphError, setMemoryGraphError] = useState("");
  const [activeRetrospectiveDays, setActiveRetrospectiveDays] = useState(7);
  const [retrospectives, setRetrospectives] = useState<RetrospectiveResponse | null>(null);
  const [retrospectiveLoading, setRetrospectiveLoading] = useState(true);
  const [retrospectiveError, setRetrospectiveError] = useState("");
  const [reviewReportMessage, setReviewReportMessage] = useState("");
  const [generatingReport, setGeneratingReport] = useState<RetrospectiveReportTarget | null>(null);
  const [reviewReportArtifacts, setReviewReportArtifacts] = useState<Partial<Record<ReviewCoachKind, ReviewReportArtifact>>>({});
  const [memoryFacts, setMemoryFacts] = useState<MemoryGraphFact[]>([]);
  const [memoryFactsLoading, setMemoryFactsLoading] = useState(true);
  const [memoryFactsError, setMemoryFactsError] = useState("");
  const [memoryFactStatus, setMemoryFactStatus] = useState<MemoryGraphStatusFilter>("all");
  const [memoryFactQuery, setMemoryFactQuery] = useState("");
  const [memoryFactBusyId, setMemoryFactBusyId] = useState<string | null>(null);
  const [exportPreview, setExportPreview] = useState<MemoryGraphExportPreviewResponse | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportMessage, setExportMessage] = useState("");
  const [weeklyMemoryReview, setWeeklyMemoryReview] = useState<MemoryReviewResponse | null>(null);
  const [weeklyMemoryReviewLoading, setWeeklyMemoryReviewLoading] = useState(true);
  const [weeklyMemoryReviewError, setWeeklyMemoryReviewError] = useState("");
  const [weeklyMemoryReviewBusyId, setWeeklyMemoryReviewBusyId] = useState<string | null>(null);
  const [memoryHygienePreview, setMemoryHygienePreview] = useState<MemoryHygienePreviewResponse | null>(null);
  const [memoryHygieneLoading, setMemoryHygieneLoading] = useState(false);
  const [memoryHygieneError, setMemoryHygieneError] = useState("");
  const [memoryHygieneBusyId, setMemoryHygieneBusyId] = useState<string | null>(null);
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
  const normalizedFactQuery = memoryFactQuery.trim().toLocaleLowerCase();
  const filteredEntries = useMemo(
    () =>
      entries.filter(
        (entry) =>
          entryMatchesFilter(entry, activeFilter) &&
          (!normalizedQuery || entrySearchText(entry).includes(normalizedQuery)),
      ),
    [activeFilter, entries, normalizedQuery],
  );
  const filteredMemoryFacts = useMemo(
    () =>
      memoryFacts.filter(
        (fact) =>
          (memoryFactStatus === "all" || fact.status === memoryFactStatus) &&
          (!normalizedFactQuery || memoryFactSearchText(fact).includes(normalizedFactQuery)),
      ),
    [memoryFactStatus, memoryFacts, normalizedFactQuery],
  );
  const memoryGroups = useMemo(() => buildMemoryTrustGroups(filteredEntries), [filteredEntries]);
  const populatedGroups = memoryGroups.filter((group) => group.entries.length > 0);
  const activeRetrospective = windowByDays(retrospectives, activeRetrospectiveDays);
  const canRevealReports = Boolean(window.agentDesktop?.revealVaultPath);
  const activePriorityFacts = useMemo(() => memoryFacts.filter((fact) => fact.status === "active"), [memoryFacts]);
  const pendingPriorityFacts = useMemo(
    () => memoryFacts.filter((fact) => ["candidate", "quarantined"].includes(fact.status)),
    [memoryFacts],
  );
  const pendingMemoryProposals = useMemo(
    () => memoryProposals.filter((proposal) => proposal.status === "pending"),
    [memoryProposals],
  );
  const recentMemoryHistoryEntries = useMemo(
    () => entries.filter(isMemoryControlHistoryEntry),
    [entries],
  );
  const confirmedFacts = filteredMemoryFacts.filter((fact) => fact.status === "active");
  const candidateFacts = filteredMemoryFacts.filter((fact) => ["candidate", "quarantined"].includes(fact.status));
  const diaryDerivedFacts = filteredMemoryFacts.filter((fact) =>
    [fact.source_type, fact.memory_type, fact.category]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes("diary") || String(value).toLowerCase().includes("chat")),
  );
  const managedStatusFacts = filteredMemoryFacts.filter((fact) =>
    ["archived", "wrong", "sensitive_blocked", "rejected"].includes(fact.status),
  );

  async function loadLocalAssets(signal?: AbortSignal) {
    setLocalAssetsLoading(true);
    setLocalAssetsError("");
    try {
      setLocalAssets(await api.getLocalAssetStats(signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setLocalAssetsError(describeError(requestError, "本机积累统计加载失败"));
    } finally {
      setLocalAssetsLoading(false);
    }
  }

  async function loadMemoryProfileProjection(signal?: AbortSignal) {
    setMemoryProfileLoading(true);
    setMemoryProfileError("");
    try {
      setMemoryProfileProjection(await api.getMemoryProfileProjection(signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setMemoryProfileError(describeError(requestError, "画像加载失败"));
    } finally {
      setMemoryProfileLoading(false);
    }
  }

  async function loadMemoryGraphProjection(signal?: AbortSignal) {
    setMemoryGraphLoading(true);
    setMemoryGraphError("");
    try {
      setMemoryGraphProjection(await api.getMemoryGraphProjection(signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setMemoryGraphError("这次没能打开记忆图谱，请稍后重试。");
    } finally {
      setMemoryGraphLoading(false);
    }
  }

  async function loadMemoryProfileDetail(itemId: string, signal?: AbortSignal) {
    setMemoryProfileDetailLoading(true);
    setMemoryProfileDetailError("");
    try {
      setMemoryProfileDetail(await api.getMemoryProfileDetail(itemId, signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setMemoryProfileDetail(null);
      setMemoryProfileDetailError("这次没能打开详情，请稍后重试。");
    } finally {
      setMemoryProfileDetailLoading(false);
    }
  }

  function openMemoryProfileDetail(item: MemoryProfileProjectionItem) {
    setMemoryProfileDetail(null);
    setMemoryProfileDetailError("");
    setMemoryProfileActionMessage("");
    void loadMemoryProfileDetail(item.id);
  }

  function closeMemoryProfileDetail() {
    setMemoryProfileDetail(null);
    setMemoryProfileDetailError("");
    setMemoryProfileActionMessage("");
    setMemoryProfileActionBusy(null);
  }

  async function loadRetrospectives(signal?: AbortSignal) {
    setRetrospectiveLoading(true);
    setRetrospectiveError("");
    try {
      setRetrospectives(await api.getRetrospectives(signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setRetrospectiveError(describeError(requestError, "回顾数据加载失败"));
    } finally {
      setRetrospectiveLoading(false);
    }
  }

  async function loadMemoryFacts(signal?: AbortSignal) {
    setMemoryFactsLoading(true);
    setMemoryFactsError("");
    try {
      const status = memoryFactStatus === "all" ? null : memoryFactStatus;
      const response = await api.listMemoryGraphFacts(status, memoryFactQuery, 100, signal);
      setMemoryFacts(response.facts);
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setMemoryFactsError(describeError(requestError, "长期记忆加载失败"));
    } finally {
      setMemoryFactsLoading(false);
    }
  }

  async function loadWeeklyMemoryReview(signal?: AbortSignal) {
    setWeeklyMemoryReviewLoading(true);
    setWeeklyMemoryReviewError("");
    try {
      setWeeklyMemoryReview(await api.getWeeklyMemoryReview(7, 30, signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setWeeklyMemoryReviewError(describeError(requestError, "本周记忆复核加载失败"));
    } finally {
      setWeeklyMemoryReviewLoading(false);
    }
  }

  async function loadMemoryHygienePreview(signal?: AbortSignal) {
    setMemoryHygieneLoading(true);
    setMemoryHygieneError("");
    try {
      setMemoryHygienePreview(await api.getMemoryHygienePreview(signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setMemoryHygieneError("这次没有完成整理，请稍后重试。");
    } finally {
      setMemoryHygieneLoading(false);
    }
  }

  useEffect(() => {
    const abort = new AbortController();
    void loadLocalAssets(abort.signal);
    void loadMemoryProfileProjection(abort.signal);
    void loadMemoryGraphProjection(abort.signal);
    void loadRetrospectives(abort.signal);
    void loadWeeklyMemoryReview(abort.signal);
    return () => abort.abort();
  }, [api]);

  useEffect(() => {
    const abort = new AbortController();
    void loadMemoryFacts(abort.signal);
    return () => abort.abort();
  }, [api, memoryFactStatus, memoryFactQuery]);

  function rememberReviewArtifact(target: RetrospectiveReportTarget, response: RetrospectiveReportResponse) {
    const kind = reviewKindForTarget(target);
    if (!kind) {
      return;
    }
    const artifact: ReviewReportArtifact = {
      kind,
      title: reviewTitleForKind(kind),
      relativePath: response.page.relative_path,
      status: response.page.status,
      actionId: response.action.action_id,
      generatedAt: response.action.completed_at || response.action.created_at,
    };
    setReviewReportArtifacts((current) => ({ ...current, [kind]: artifact }));
    setReviewReportMessage(reportArtifactMessage(artifact));
  }

  async function generateReport(days: number) {
    setGeneratingReport(days);
    setRetrospectiveError("");
    setReviewReportMessage("");
    try {
      const response = await api.writeRetrospectiveReport(days);
      rememberReviewArtifact(days, response);
      await loadLocalAssets();
      await loadRetrospectives();
      onRefresh();
    } catch (requestError) {
      setRetrospectiveError(describeError(requestError, "回顾报告生成失败"));
    } finally {
      setGeneratingReport(null);
    }
  }

  async function generatePeriodReport(period: RetrospectiveReportPeriod) {
    setGeneratingReport(period);
    setRetrospectiveError("");
    setReviewReportMessage("");
    try {
      const response = await api.writeRetrospectivePeriodReport(period);
      rememberReviewArtifact(period, response);
      await loadLocalAssets();
      await loadRetrospectives();
      onRefresh();
    } catch (requestError) {
      setRetrospectiveError(describeError(requestError, period === "weekly" ? "周报生成失败" : "月报生成失败"));
    } finally {
      setGeneratingReport(null);
    }
  }

  function generateReviewFromCard(config: ReviewCoachCardConfig) {
    if (typeof config.target === "number") {
      void generateReport(config.target);
    } else {
      void generatePeriodReport(config.target);
    }
  }

  function fillMemorySearchTrial() {
    onMemorySearchQueryChange("发布清单");
  }

  function fillPreferenceTrial() {
    onMemoryProposalDraftChange({
      type: "preference",
      content: "我偏好简洁的发布清单。",
      target_path: "Inbox/Pending Memories.md",
    });
  }

  async function revealReviewReport(relativePath: string, mode: DesktopVaultRevealMode) {
    if (!window.agentDesktop?.revealVaultPath) {
      setRetrospectiveError("当前浏览器视图无法打开本地保存文件位置。");
      return;
    }
    const result = await window.agentDesktop.revealVaultPath(relativePath, mode);
    if (result.status === "failed" || result.status === "rejected") {
      setRetrospectiveError(result.reason || "报告打开失败。");
    } else {
      setRetrospectiveError("");
      setReviewReportMessage(mode === "open" ? `已打开 ${relativePath}` : `已定位 ${relativePath}`);
    }
  }

  async function updateMemoryFactStatus(
    factId: string,
    action: "wrong" | "archive" | "sensitive_block" | "confirm",
  ) {
    setMemoryFactBusyId(factId);
    setMemoryFactsError("");
    setExportMessage("");
    try {
      if (action === "wrong") {
        await api.markMemoryGraphFactWrong(factId);
      } else if (action === "archive") {
        await api.archiveMemoryGraphFact(factId);
      } else if (action === "sensitive_block") {
        await api.sensitiveBlockMemoryGraphFact(factId);
      } else {
        await api.confirmMemoryGraphFact(factId);
      }
      await loadMemoryFacts();
      await loadMemoryProfileProjection();
      await loadMemoryGraphProjection();
      await loadLocalAssets();
      onRefresh();
    } catch (requestError) {
      setMemoryFactsError(describeError(requestError, "长期记忆状态更新失败"));
    } finally {
      setMemoryFactBusyId(null);
    }
  }

  async function submitMemoryProfileAction(action: MemoryProfileActionKind) {
    if (!memoryProfileDetail) {
      return;
    }
    const confirmed = window.confirm(profileActionConfirmText(action));
    if (!confirmed) {
      return;
    }
    setMemoryProfileActionBusy(action);
    setMemoryProfileDetailError("");
    setMemoryProfileActionMessage("");
    try {
      const response = await api.submitMemoryProfileAction(memoryProfileDetail.id, {
        action,
        confirmed: true,
        expires_at: action === "make_temporary" ? temporaryProfileExpiry() : null,
        feedback_text: `memory_profile_drawer:${action}`,
      });
      setMemoryProfileActionMessage(response.message || "已更新这条记忆。");
      await loadMemoryProfileProjection();
      await loadMemoryGraphProjection();
      await loadMemoryProfileDetail(memoryProfileDetail.id);
      await loadLocalAssets();
      onRefresh();
    } catch (requestError) {
      setMemoryProfileDetailError("这次没有改动记忆，请稍后重试。");
    } finally {
      setMemoryProfileActionBusy(null);
    }
  }

  async function applyWeeklyMemoryReviewAction(item: MemoryReviewItem, action: MemoryReviewAction) {
    let replacementText: string | null = null;
    if (action === "edit") {
      replacementText = window.prompt("请输入新的记忆内容", item.summary);
      if (!replacementText?.trim()) {
        return;
      }
    }
    setWeeklyMemoryReviewBusyId(item.review_id);
    setWeeklyMemoryReviewError("");
    try {
      await api.applyWeeklyMemoryReviewAction({
        target_type: item.target_type,
        target_id: item.target_id,
        action,
        feedback_text: `weekly_memory_review:${action}`,
        replacement_text: replacementText,
      });
      await loadWeeklyMemoryReview();
      await loadMemoryFacts();
      await loadMemoryProfileProjection();
      await loadMemoryGraphProjection();
      await loadLocalAssets();
      onRefresh();
    } catch (requestError) {
      setWeeklyMemoryReviewError(describeError(requestError, "本周记忆复核操作失败"));
    } finally {
      setWeeklyMemoryReviewBusyId(null);
    }
  }

  async function applyMemoryHygieneSuggestion(item: MemoryHygieneSuggestion) {
    const confirmed = window.confirm("确定要应用这条整理建议吗？这会更新记忆状态。");
    if (!confirmed) {
      return;
    }
    setMemoryHygieneBusyId(item.id);
    setMemoryHygieneError("");
    try {
      await api.applyMemoryHygieneSuggestion(item.id, true);
      await loadMemoryHygienePreview();
      await loadMemoryProfileProjection();
      await loadMemoryGraphProjection();
      await loadWeeklyMemoryReview();
      await loadLocalAssets();
      onRefresh();
    } catch (requestError) {
      setMemoryHygieneError("这次没有完成整理，请稍后重试。");
    } finally {
      setMemoryHygieneBusyId(null);
    }
  }

  async function copyExportPreview() {
    setExportLoading(true);
    setExportMessage("");
    try {
      const status = memoryFactStatus === "all" ? null : memoryFactStatus;
      const response = await api.getMemoryGraphExportPreview("markdown", status, memoryFactQuery, 100);
      setExportPreview(response);
      const text = memoryExportText(response, "markdown");
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        setExportMessage(`已复制 ${response.item_count} 条长期记忆预览。`);
      } else {
        setExportMessage(`已生成 ${response.item_count} 条长期记忆预览。`);
      }
    } catch (requestError) {
      setExportMessage(describeError(requestError, "导出预览失败"));
    } finally {
      setExportLoading(false);
    }
  }

  async function downloadMemoryExport(format: MemoryExportFormat) {
    setExportLoading(true);
    setExportMessage("");
    try {
      const status = memoryFactStatus === "all" ? null : memoryFactStatus;
      const response = await api.getMemoryGraphExportPreview(format, status, memoryFactQuery, 100);
      setExportPreview(response);
      const text = memoryExportText(response, format);
      const fileName = memoryExportFileName(format);
      downloadTextFile(
        fileName,
        text,
        format === "json" ? "application/json;charset=utf-8" : "text/markdown;charset=utf-8",
      );
      setExportMessage(`已导出 ${response.item_count} 条长期记忆为 ${format === "json" ? "JSON" : "Markdown"}。`);
    } catch (requestError) {
      setExportMessage(describeError(requestError, "记忆导出失败"));
    } finally {
      setExportLoading(false);
    }
  }

  const activeWorkspaceTabConfig =
    memoryWorkspaceTabs.find((tab) => tab.key === activeWorkspaceTab) || memoryWorkspaceTabs[0];

  const graphPanel = (
    <MemoryGraphPanel
      projection={memoryGraphProjection}
      loading={memoryGraphLoading}
      error={memoryGraphError}
      onRefresh={() => void loadMemoryGraphProjection()}
    />
  );

  const archivePanel = (
    <>
      <MemoryPriorityPanel
        activeFacts={activePriorityFacts}
        candidateFacts={pendingPriorityFacts}
        memoryFactsLoading={memoryFactsLoading}
        memoryFactBusyId={memoryFactBusyId}
        pendingProposals={pendingMemoryProposals}
        loadingMemoryProposals={loadingMemoryProposals}
        memoryProposalActionIds={memoryProposalActionIds}
        recentHistoryEntries={recentMemoryHistoryEntries}
        onMemoryFactAction={(factId, action) => void updateMemoryFactStatus(factId, action)}
        onMemoryProposalAct={onActOnMemoryProposal}
        onLoadMemoryProposals={onLoadMemoryProposals}
        renderEntry={renderEntry}
      />

      <MemoryProfileProjectionPanel
        projection={memoryProfileProjection}
        loading={memoryProfileLoading}
        error={memoryProfileError}
        detail={memoryProfileDetail}
        detailLoading={memoryProfileDetailLoading}
        detailError={memoryProfileDetailError}
        actionBusy={memoryProfileActionBusy}
        actionMessage={memoryProfileActionMessage}
        onRefresh={() => void loadMemoryProfileProjection()}
        onOpenItem={openMemoryProfileDetail}
        onCloseDetail={closeMemoryProfileDetail}
        onAction={(action) => void submitMemoryProfileAction(action)}
      />

      <AddMemoryForm
        draft={memoryProposalDraft}
        onDraftChange={onMemoryProposalDraftChange}
        onTryPreference={fillPreferenceTrial}
        onSubmit={onCreateMemoryProposal}
      />
    </>
  );

  const searchPanel = (
    <section className="memory-workbench-panel memory-search-workspace" aria-label="记忆和资料搜索">
      <MemorySearchWorkbench
        query={memorySearchQuery}
        status={memorySearchStatus}
        results={memorySearchResults}
        lastQuery={memoryLastSearchQuery}
        onQueryChange={onMemorySearchQueryChange}
        onTrySearch={fillMemorySearchTrial}
        onSearch={onRunMemorySearch}
      />
      <MemoryWorkspacePlaceholder
        title="资料搜索入口"
        description="资料页搜索继续保留在资料库内部。"
        helper="需要搜索文档、链接或整理出的资料页时，可以从导入页打开资料库。"
      />
    </section>
  );

  const dataPanel = (
    <>
      <LocalAssetDashboard
        stats={localAssets}
        loading={localAssetsLoading}
        error={localAssetsError}
        onRefresh={() => void loadLocalAssets()}
      />

      <details className="memory-advanced-tools">
        <summary>
          <strong>高级备份与检查</strong>
          <span>{productCopy.memoryPage.advancedManagementDescription}</span>
        </summary>
        <div className="memory-advanced-tools-stack">
          <section className="panel feature-window-panel memory-management-panel" aria-label="高级备份与检查">
            <div className="section-heading">
              <strong>检查和备份记忆</strong>
              <span>
                {memoryFacts.length > 0
                  ? `显示 ${filteredMemoryFacts.length} / ${memoryFacts.length} 条长期会用到的记忆。`
                  : "还没有长期会用到的记忆。"}
              </span>
            </div>

            <div className="memory-graph-toolbar">
              <div className="memory-activity-filters" aria-label="长期记忆状态筛选">
                {graphStatusFilters.map((option) => {
                  const count =
                    option.key === "all"
                      ? memoryFacts.length
                      : memoryFacts.filter((fact) => fact.status === option.key).length;
                  const active = memoryFactStatus === option.key;
                  return (
                    <button
                      key={option.key}
                      type="button"
                      className={`secondary memory-activity-filter ${active ? "active" : ""}`}
                      onClick={() => setMemoryFactStatus(option.key)}
                      aria-pressed={active}
                    >
                      {option.label}
                      <span>{count}</span>
                    </button>
                  );
                })}
              </div>
              <label className="memory-activity-search">
                <Search size={16} />
                <input
                  type="search"
                  value={memoryFactQuery}
                  onChange={(event) => setMemoryFactQuery(event.target.value)}
                  placeholder="搜索主题、内容或类别"
                />
              </label>
            </div>

            <div className="button-row">
              <button type="button" className="secondary" onClick={() => void loadMemoryFacts()} disabled={memoryFactsLoading}>
                {memoryFactsLoading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                刷新长期记忆
              </button>
              <button type="button" className="secondary" onClick={() => void copyExportPreview()} disabled={exportLoading}>
                {exportLoading ? <Loader2 className="spin" size={16} /> : <Copy size={16} />}
                复制导出预览
              </button>
              <button type="button" className="secondary" onClick={() => void downloadMemoryExport("markdown")} disabled={exportLoading}>
                {exportLoading ? <Loader2 className="spin" size={16} /> : <Download size={16} />}
                下载 Markdown 备份
              </button>
              <button type="button" className="secondary" onClick={() => void downloadMemoryExport("json")} disabled={exportLoading}>
                {exportLoading ? <Loader2 className="spin" size={16} /> : <Download size={16} />}
                下载 JSON 备份
              </button>
            </div>
            {memoryFactsError ? <p className="field-note error">{memoryFactsError}</p> : null}
            {exportMessage ? <p className={`field-note ${exportMessage.includes("失败") ? "error" : ""}`}>{exportMessage}</p> : null}

            <div className="memory-fact-section-grid">
              <MemoryFactSection
                title="已确认记忆"
                description={`${confirmedFacts.length} 条可用于检索的使用中事实。`}
                facts={confirmedFacts}
                loading={memoryFactsLoading}
                emptyText="当前筛选下没有匹配的已确认记忆。"
                busyId={memoryFactBusyId}
                onAction={(factId, action) => void updateMemoryFactStatus(factId, action)}
              />
              <MemoryFactSection
                title="等你确认"
                description={`${candidateFacts.length} 条记忆正在等待你确认或处理冲突。`}
                facts={candidateFacts}
                loading={memoryFactsLoading}
                emptyText="当前筛选下没有匹配的待确认记忆。"
                busyId={memoryFactBusyId}
                onAction={(factId, action) => void updateMemoryFactStatus(factId, action)}
              />
              <MemoryFactSection
                title="日记来源记忆"
                description={`${diaryDerivedFacts.length} 条事实来自日记或聊天提取路径。`}
                facts={diaryDerivedFacts}
                loading={memoryFactsLoading}
                emptyText="当前筛选下没有匹配的日记来源记忆。"
                busyId={memoryFactBusyId}
                onAction={(factId, action) => void updateMemoryFactStatus(factId, action)}
              />
              <MemoryFactSection
                title="已归档或封存事实"
                description={`${managedStatusFacts.length} 条事实已归档、标错、拒绝或敏感封存。`}
                facts={managedStatusFacts}
                loading={memoryFactsLoading}
                emptyText="当前筛选下没有匹配的已归档或封存事实。"
                busyId={memoryFactBusyId}
                onAction={(factId, action) => void updateMemoryFactStatus(factId, action)}
              />
            </div>

            {exportPreview ? (
              <div className="memory-export-preview" aria-label="长期记忆导出预览">
                <div className="section-heading compact">
                  <strong>导出预览</strong>
                  <span>{safeMemoryNotice(exportPreview.redaction_note)}</span>
                </div>
                <textarea readOnly value={memoryExportText(exportPreview, exportPreview.format)} />
              </div>
            ) : null}
          </section>

          <section className="panel feature-window-panel memory-activity-panel" aria-label="整理记录">
            <div className="section-heading">
              <strong>最近整理活动</strong>
              <span>
                {entries.length > 0
                  ? `显示 ${filteredEntries.length} / ${entries.length} 条活动。`
                  : "还没有整理活动。"}
              </span>
            </div>

            <div className="memory-activity-toolbar">
              <div className="memory-activity-filters" aria-label="整理活动筛选">
                {activityFilters.map((option) => {
                  const count = entries.filter((entry) => entryMatchesFilter(entry, option.key)).length;
                  const active = activeFilter === option.key;
                  return (
                    <button
                      key={option.key}
                      type="button"
                      className={`secondary memory-activity-filter ${active ? "active" : ""}`}
                      onClick={() => setActiveFilter(option.key)}
                      aria-pressed={active}
                    >
                      {option.label}
                      <span>{count}</span>
                    </button>
                  );
                })}
              </div>
              <label className="memory-activity-search">
                <Search size={16} />
                <input
                  type="search"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="搜索目标文件、摘要或动作"
                />
              </label>
            </div>

            <div className="button-row">
              <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
                {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                刷新整理
              </button>
            </div>
            {error ? <p className="field-note error">{error}</p> : null}
            {filteredEntries.length > 0 ? (
              <div className="memory-trust-workspace" aria-label="AI 记住了什么">
                <div className="section-heading compact">
                  <strong>我记住了什么</strong>
                  <span>按写入类型、跳过原因和可撤回状态归类；敏感跳过项只显示安全摘要。</span>
                </div>
                <div className="memory-trust-group-grid">
                  {memoryGroups.map((group) => (
                    <article key={group.key} className={`memory-trust-group-card ${group.entries.length > 0 ? "active" : ""}`}>
                      <strong>{group.label}</strong>
                      <span>{group.entries.length}</span>
                      <p>{group.description}</p>
                    </article>
                  ))}
                </div>
                {populatedGroups.length > 0 ? (
                  <div className="memory-trust-group-legend">
                    {populatedGroups.map((group) => (
                      <span key={group.key}>
                        {group.label}: {group.entries.length}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="proposal-list agent-activity-log-list feature-activity-list">
              {filteredEntries.length > 0 ? (
                filteredEntries.map((entry) => renderEntry(entry))
              ) : loading ? (
                <EmptyState text="正在加载最近整理活动。" />
              ) : entries.length > 0 ? (
                <EmptyState text="没有匹配的整理活动。" />
              ) : (
                <EmptyState text="普通自动整理完成后会出现在这里；高风险写入会在这里显示确认入口。" />
              )}
            </div>
          </section>
        </div>
      </details>
    </>
  );

  const decayPanel = (
    <>
      <MemoryHygieneSuggestionPanel
        preview={memoryHygienePreview}
        loading={memoryHygieneLoading}
        error={memoryHygieneError}
        busyId={memoryHygieneBusyId}
        onScan={() => void loadMemoryHygienePreview()}
        onApply={(item) => void applyMemoryHygieneSuggestion(item)}
      />

      <section className="panel feature-window-panel memory-review-queue-panel" aria-label="更多记忆复核">
        <WeeklyMemoryReviewPanel
          review={weeklyMemoryReview}
          loading={weeklyMemoryReviewLoading}
          error={weeklyMemoryReviewError}
          busyId={weeklyMemoryReviewBusyId}
          onRefresh={() => void loadWeeklyMemoryReview()}
          onAction={(item, action) => void applyWeeklyMemoryReviewAction(item, action)}
        />

        <MemoryProposalReviewList
          proposals={memoryProposals}
          loading={loadingMemoryProposals}
          actionIds={memoryProposalActionIds}
          onAct={onActOnMemoryProposal}
          onRefresh={onLoadMemoryProposals}
        />
      </section>
    </>
  );

  const diaryPanel = (
    <>
      <ReviewCoachPanel
        retrospectives={retrospectives}
        loading={retrospectiveLoading}
        error={retrospectiveError}
        message={reviewReportMessage}
        generatingReport={generatingReport}
        reportArtifacts={reviewReportArtifacts}
        canRevealReports={canRevealReports}
        onRefresh={() => void loadRetrospectives()}
        onGenerate={generateReviewFromCard}
        onRevealReport={(relativePath, mode) => void revealReviewReport(relativePath, mode)}
      />

      <section className="panel feature-window-panel memory-source-details-panel" aria-label="复盘来源详情">
        <div className="section-heading">
          <strong>复盘来源详情</strong>
          <span>生成报告前后都可以检查每次复盘背后的本地证据。</span>
        </div>
        <div className="retrospective-toolbar" aria-label="复盘来源窗口">
          {[1, 7, 30, 90].map((days) => (
            <button
              key={days}
              type="button"
              className={`secondary memory-activity-filter ${activeRetrospectiveDays === days ? "active" : ""}`}
              onClick={() => setActiveRetrospectiveDays(days)}
              aria-pressed={activeRetrospectiveDays === days}
            >
              <CalendarRange size={15} />
              {days === 1 ? "今天" : `${days} 天`}
            </button>
          ))}
        </div>
        {retrospectiveLoading && !activeRetrospective ? (
          <EmptyState text="正在加载本地复盘数据。" />
        ) : activeRetrospective ? (
          <RetrospectiveWindowPanel
            window={activeRetrospective}
            generatingReport={generatingReport}
            onGenerateReport={(days) => void generateReport(days)}
          />
        ) : (
          <EmptyState text="还没有复盘数据。请先完成一次聊天、任务或资料整理。" />
        )}
      </section>
    </>
  );

  function renderWorkspacePanel() {
    switch (activeWorkspaceTab) {
      case "archive":
        return archivePanel;
      case "search":
        return searchPanel;
      case "data":
        return dataPanel;
      case "import":
        return <MemoryImportPanel />;
      case "related":
        return (
          <MemoryWorkspacePlaceholder
            title="关联"
            description="把偏好、项目、资料和日记情景串成更清楚的上下文。"
            helper="第一阶段先保留入口；后续会把图谱节点、资料页和日记情景连接到这里。"
          />
        );
      case "heatmap":
        return (
          <MemoryWorkspacePlaceholder
            title="热力图"
            description="观察最近哪些主题最常出现。"
            helper="第一阶段先保留入口；后续会用本机日记和记忆统计形成低压热力图。"
          />
        );
      case "decay":
        return decayPanel;
      case "diary":
        return diaryPanel;
      case "graph":
      default:
        return graphPanel;
    }
  }

  return (
    <FeatureWindowShell
      eyebrow="记忆"
      title={productCopy.memoryPage.title}
      description={productCopy.memoryPage.description}
      activeTab="记忆"
    >
      <MemoryWorkspaceTabs activeTab={activeWorkspaceTab} onChange={setActiveWorkspaceTab} />
      <div
        id={`memory-workspace-panel-${activeWorkspaceTab}`}
        className="memory-workspace-tab-panel"
        role="tabpanel"
        aria-label={`记忆工作台：${activeWorkspaceTabConfig.label}`}
      >
        {renderWorkspacePanel()}
      </div>
    </FeatureWindowShell>
  );
}
