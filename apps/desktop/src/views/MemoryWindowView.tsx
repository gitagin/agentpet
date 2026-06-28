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
  { key: "candidate", label: "候选" },
  { key: "quarantined", label: "隔离" },
  { key: "archived", label: "归档" },
  { key: "rejected", label: "拒绝" },
  { key: "wrong", label: "不准确" },
  { key: "sensitive_blocked", label: "敏感封存" },
];

const reviewCoachCards: ReviewCoachCardConfig[] = [
  {
    kind: "today",
    title: "今日复盘",
    description: "把今天的日记、任务、记忆和知识整理更新合成本地复盘。",
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
    description: "生成结合长期记忆、任务状态和知识整理输出的月度报告。",
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
      return "候选";
    case "quarantined":
      return "隔离";
    case "archived":
      return "归档";
    case "rejected":
      return "拒绝";
    case "wrong":
      return "不准确";
    case "sensitive_blocked":
      return "敏感封存";
    default:
      return status;
  }
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
  const importance = typeof fact.importance === "number" ? `，重要度 ${Math.round(fact.importance * 100)}%` : "";
  return `来自 ${fact.source_type || "未知来源"}，${support}${importance}`;
}

function memoryExportText(response: MemoryGraphExportPreviewResponse, format: MemoryExportFormat): string {
  return format === "json" ? response.json_preview : response.markdown_preview;
}

function memoryExportFileName(format: MemoryExportFormat): string {
  const day = new Date().toISOString().slice(0, 10);
  return `agent-pet-memory-${day}.${format === "json" ? "json" : "md"}`;
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
  return sources
    .slice(0, 3)
    .map((source) => source.path || `${source.kind}:${source.id}`)
    .join(" / ");
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
    { label: "知识页", value: String(stats?.wiki_page_count ?? 0), meta: "不含核心维护页", icon: BookOpen },
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
      <span>知识整理 {window.summary.wiki_updates || 0}</span>
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
            <strong>新增记忆和知识整理</strong>
            {window.long_term_memories.slice(0, 3).map((item) => (
              <p key={item.id}>
                {item.summary} <small>{item.category} / {item.status}</small>
              </p>
            ))}
            {window.wiki_updates.slice(0, 3).map((item) => (
              <p key={item.action_id || item.path}>
                {item.title} <small>{item.path}</small>
              </p>
            ))}
            {!window.long_term_memories.length && !window.wiki_updates.length ? <p>暂无新增长期记忆或知识整理。</p> : null}
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
        <EmptyState text="这个时间窗口还没有可回顾的本机积累。先完成一次聊天、任务或知识整理后再回来查看。" />
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
    { label: "知识整理", value: coverage.wiki },
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
          使用 {window.summary.diary_objects || 0} 条日记、{window.tasks.total} 个任务、{window.summary.long_term_memories || 0} 条记忆事实和 {window.summary.wiki_updates || 0} 次知识整理。
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
        <span>不经过聊天也可以创建一条可复核的记忆候选。</span>
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
    <section className="memory-review-list" aria-label="待复核记忆候选">
      <div className="section-heading compact">
        <strong>待复核候选</strong>
        <span>{pending.length} 条待确认 / 共 {proposals.length} 条候选。</span>
      </div>
      <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
        {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
        刷新候选
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
          <EmptyState text="没有待确认记忆。上方“新增记忆”会创建新的候选项。" />
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
          <span>{fact.category}</span>
          <span>风险 {formatMemoryFactRisk(fact)}</span>
          <span>置信度 {Math.round(fact.confidence * 100)}%</span>
          <span>支持 {fact.support_count}</span>
        </div>
        <dl className="memory-graph-fact-details" aria-label="记忆来源和判断">
          <div>
            <dt>来源</dt>
            <dd>
              {fact.source_type}
              {fact.memory_type ? ` / ${fact.memory_type}` : ""}
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
              <dd>{fact.conflicts_with}</dd>
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
    <section className="panel feature-window-panel memory-primary-panel" aria-label="我的记忆控制台">
      <div className="section-heading">
        <strong>{productCopy.memoryPage.title}</strong>
        <span>{productCopy.memoryPage.description}</span>
      </div>

      <div className="memory-priority-grid">
        <section className="memory-priority-block" aria-label={productCopy.memoryPage.activeSectionTitle}>
          <div className="section-heading compact">
            <strong>{productCopy.memoryPage.activeSectionTitle}</strong>
            <span>{activeFacts.length} 条正在用于陪伴和检索。</span>
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
            <span>{pendingProposals.length + candidateFacts.length} 条需要你确认或复核。</span>
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
            <span>显示最近已跳过、已撤回，或仍可撤回的整理记录。</span>
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
          <p>候选、隔离或未进入长期使用的内容。</p>
        </article>
      </div>
      <div className="button-row">
        <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          刷新复核
        </button>
      </div>
      {error ? <p className="field-note error">{error}</p> : null}
      {review?.redaction_note ? <p className="field-note">{review.redaction_note}</p> : null}
      <div className="proposal-list memory-proposal-review-list">
        {review && review.items.length > 0 ? (
          review.items.map((item) => (
            <article key={item.review_id} className={`memory-graph-fact ${item.category}`}>
              <div className="memory-graph-fact-main">
                <strong>{item.summary}</strong>
                <div className="memory-graph-fact-meta">
                  <span>{formatReviewCategory(item.category)}</span>
                  <span>{item.memory_kind || item.target_type}</span>
                  <span>{item.lifecycle_status}</span>
                  <span>置信度 {Math.round(item.confidence * 100)}%</span>
                </div>
                <p>
                  {item.source}
                  {item.expires_at ? ` / expires ${formatDate(item.expires_at)}` : ""}
                  {item.updated_at ? ` / ${formatDate(item.updated_at)}` : ""}
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
  const [searchQuery, setSearchQuery] = useState("");
  const [localAssets, setLocalAssets] = useState<LocalAssetStatsResponse | null>(null);
  const [localAssetsLoading, setLocalAssetsLoading] = useState(true);
  const [localAssetsError, setLocalAssetsError] = useState("");
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

  useEffect(() => {
    const abort = new AbortController();
    void loadLocalAssets(abort.signal);
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
      await loadLocalAssets();
      onRefresh();
    } catch (requestError) {
      setMemoryFactsError(describeError(requestError, "长期记忆状态更新失败"));
    } finally {
      setMemoryFactBusyId(null);
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
      await loadLocalAssets();
      onRefresh();
    } catch (requestError) {
      setWeeklyMemoryReviewError(describeError(requestError, "本周记忆复核操作失败"));
    } finally {
      setWeeklyMemoryReviewBusyId(null);
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

  return (
    <FeatureWindowShell
      eyebrow="记忆"
      title={productCopy.memoryPage.title}
      description={productCopy.memoryPage.description}
      activeTab="记忆"
    >
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

      <details className="memory-advanced-tools memory-review-tools">
        <summary>
          <strong>回顾和本机整理</strong>
          <span>生成回顾报告、查看本机积累和更细的来源详情。</span>
        </summary>
        <div className="memory-advanced-tools-stack">
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
              <EmptyState text="还没有复盘数据。请先完成一次聊天、任务或知识整理。" />
            )}
          </section>

          <LocalAssetDashboard
            stats={localAssets}
            loading={localAssetsLoading}
            error={localAssetsError}
            onRefresh={() => void loadLocalAssets()}
          />
        </div>
      </details>

      <details className="memory-advanced-tools">
        <summary>
          <strong>更多记忆管理</strong>
          <span>搜索更多记录、复核候选项，并查看后台整理记录。</span>
        </summary>
        <div className="memory-advanced-tools-stack">
      <section className="panel feature-window-panel memory-workbench-panel" aria-label="更多记忆工作区">
        <MemorySearchWorkbench
          query={memorySearchQuery}
          status={memorySearchStatus}
          results={memorySearchResults}
          lastQuery={memoryLastSearchQuery}
          onQueryChange={onMemorySearchQueryChange}
          onTrySearch={fillMemorySearchTrial}
          onSearch={onRunMemorySearch}
        />
        <AddMemoryForm
          draft={memoryProposalDraft}
          onDraftChange={onMemoryProposalDraftChange}
          onTryPreference={fillPreferenceTrial}
          onSubmit={onCreateMemoryProposal}
        />
        <div className="guided-trial-actions memory-review-trial-actions" aria-label="复盘快捷操作">
          <button type="button" className="secondary" onClick={() => void generateReport(1)} disabled={generatingReport !== null}>
            {generatingReport === 1 ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
            生成今日复盘
          </button>
        </div>
      </section>

      <section className="panel feature-window-panel memory-management-panel" aria-label="更多记忆管理">
        <div className="section-heading">
          <strong>复核并管理记忆事实</strong>
          <span>
            {memoryFacts.length > 0
              ? `显示 ${filteredMemoryFacts.length} / ${memoryFacts.length} 条结构化长期记忆。`
              : "还没有结构化长期记忆。"}
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
            下载 Markdown
          </button>
          <button type="button" className="secondary" onClick={() => void downloadMemoryExport("json")} disabled={exportLoading}>
            {exportLoading ? <Loader2 className="spin" size={16} /> : <Download size={16} />}
            下载 JSON
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
            title="待复核候选"
            description={`${candidateFacts.length} 条记忆事实正在等待置信度或冲突复核。`}
            facts={candidateFacts}
            loading={memoryFactsLoading}
            emptyText="当前筛选下没有匹配的待确认候选。"
            busyId={memoryFactBusyId}
            onAction={(factId, action) => void updateMemoryFactStatus(factId, action)}
          />
          <MemoryFactSection
            title="日记来源记忆"
            description={`${diaryDerivedFacts.length} 条事实来自日记或聊天提取路径。`}
            facts={diaryDerivedFacts}
            loading={memoryFactsLoading}
            emptyText="当前筛选下没有匹配的日记来源记忆事实。"
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
              <span>{exportPreview.redaction_note}</span>
            </div>
            <textarea readOnly value={memoryExportText(exportPreview, exportPreview.format)} />
          </div>
        ) : null}
      </section>

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

      <section className="panel feature-window-panel memory-activity-panel" aria-label="后台整理记录">
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
              <strong>AI 记住了什么</strong>
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
    </FeatureWindowShell>
  );
}
