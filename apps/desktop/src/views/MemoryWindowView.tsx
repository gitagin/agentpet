import { Archive, BarChart3, BookOpen, CalendarRange, CheckCircle2, Copy, Database, FileText, History, Loader2, NotebookTabs, RefreshCw, RotateCcw, Search, ShieldAlert, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "../components/layout";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import {
  buildMemoryTrustGroups,
  getAgentActionSearchText,
  type AgentActivityLogEntry,
} from "../services/agentActivity";
import type {
  LocalAssetStatsResponse,
  MemoryGraphExportPreviewResponse,
  MemoryGraphFact,
  RetrospectiveReportPeriod,
  RetrospectiveResponse,
  RetrospectiveSourceReference,
  RetrospectiveWindow,
} from "../types";
import { FeatureWindowShell } from "./FeatureWindowShell";

type MemoryActivityFilter = "all" | "auto" | "pending" | "reverted" | "failed";
type MemoryGraphStatusFilter = "all" | "active" | "candidate" | "quarantined" | "archived" | "rejected" | "wrong" | "sensitive_blocked";
type RetrospectiveReportTarget = number | RetrospectiveReportPeriod;

type MemoryWindowViewProps = {
  api: DesktopApi;
  loading: boolean;
  error: string;
  entries: AgentActivityLogEntry[];
  onRefresh: () => void;
  renderEntry: (entry: AgentActivityLogEntry) => ReactNode;
};

const activityFilters: Array<{ key: MemoryActivityFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "auto", label: "自动写入" },
  { key: "pending", label: "待确认" },
  { key: "reverted", label: "已撤销" },
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
    { label: "长期记忆", value: String(stats?.long_term_memory_count ?? 0), meta: "active / candidate", icon: Database },
    { label: "Wiki 页面", value: String(stats?.wiki_page_count ?? 0), meta: "不含核心维护页", icon: BookOpen },
    { label: "任务完成", value: taskValue, meta: "completed / total", icon: CheckCircle2 },
    { label: "最近整理", value: latest, meta: "本地活动账本", icon: History },
    { label: "可撤销操作", value: String(stats?.reversible_operation_count ?? 0), meta: "尚未撤销", icon: RotateCcw },
  ];
  return (
    <section className="panel feature-window-panel local-asset-dashboard" aria-label="本地资产仪表盘">
      <div className="section-heading">
        <strong>本地资产仪表盘</strong>
        <span>
          {stats?.vault_configured
            ? "从本地 SQLite 与 Vault 只读汇总，不上传遥测。"
            : "尚未绑定 Vault；先显示本地数据库中的积累。"}
        </span>
      </div>
      <div className="local-asset-toolbar">
        <span className="local-asset-scope">
          <BarChart3 size={16} />
          本地第二大脑
        </span>
        <button type="button" className="secondary" onClick={onRefresh} disabled={loading}>
          {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
          刷新资产
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
        <EmptyState text="还没有本地资产。完成一次聊天、记录长期记忆或生成复盘后，这里会显示积累情况。" />
      ) : null}
      {loading && !stats ? <EmptyState text="正在读取本地资产统计。" /> : null}
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
        <span>Wiki {window.summary.wiki_updates || 0}</span>
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
            <strong>新增记忆和 Wiki</strong>
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
            {!window.long_term_memories.length && !window.wiki_updates.length ? <p>暂无新增长期记忆或 Wiki 更新。</p> : null}
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
        <EmptyState text="这个时间窗口还没有可回顾的本地资产。先完成一次聊天、任务或 Wiki 整理后再回来查看。" />
      )}
      <button type="button" className="secondary" onClick={() => onGenerateReport(window.days)} disabled={busy}>
        {busy ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
        生成 Markdown 报告
      </button>
    </article>
  );
}

export default function MemoryWindowView({
  api,
  loading,
  error,
  entries,
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
  const [generatingReport, setGeneratingReport] = useState<RetrospectiveReportTarget | null>(null);
  const [memoryFacts, setMemoryFacts] = useState<MemoryGraphFact[]>([]);
  const [memoryFactsLoading, setMemoryFactsLoading] = useState(true);
  const [memoryFactsError, setMemoryFactsError] = useState("");
  const [memoryFactStatus, setMemoryFactStatus] = useState<MemoryGraphStatusFilter>("all");
  const [memoryFactQuery, setMemoryFactQuery] = useState("");
  const [memoryFactBusyId, setMemoryFactBusyId] = useState<string | null>(null);
  const [exportPreview, setExportPreview] = useState<MemoryGraphExportPreviewResponse | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportMessage, setExportMessage] = useState("");
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

  async function loadLocalAssets(signal?: AbortSignal) {
    setLocalAssetsLoading(true);
    setLocalAssetsError("");
    try {
      setLocalAssets(await api.getLocalAssetStats(signal));
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        return;
      }
      setLocalAssetsError(describeError(requestError, "本地资产统计加载失败"));
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

  useEffect(() => {
    const abort = new AbortController();
    void loadLocalAssets(abort.signal);
    void loadRetrospectives(abort.signal);
    return () => abort.abort();
  }, [api]);

  useEffect(() => {
    const abort = new AbortController();
    void loadMemoryFacts(abort.signal);
    return () => abort.abort();
  }, [api, memoryFactStatus, memoryFactQuery]);

  async function generateReport(days: number) {
    setGeneratingReport(days);
    setRetrospectiveError("");
    try {
      await api.writeRetrospectiveReport(days);
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
    try {
      await api.writeRetrospectivePeriodReport(period);
      await loadLocalAssets();
      await loadRetrospectives();
      onRefresh();
    } catch (requestError) {
      setRetrospectiveError(describeError(requestError, period === "weekly" ? "周报生成失败" : "月报生成失败"));
    } finally {
      setGeneratingReport(null);
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

  async function copyExportPreview() {
    setExportLoading(true);
    setExportMessage("");
    try {
      const status = memoryFactStatus === "all" ? null : memoryFactStatus;
      const response = await api.getMemoryGraphExportPreview("markdown", status, memoryFactQuery, 100);
      setExportPreview(response);
      const text = response.markdown_preview || response.json_preview;
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

  return (
    <FeatureWindowShell
      eyebrow="自动整理"
      title="整理"
      description="查看自动写入、撤销记录，以及需要你确认的长期记忆和状态更新。"
      activeTab="整理"
    >
      <LocalAssetDashboard
        stats={localAssets}
        loading={localAssetsLoading}
        error={localAssetsError}
        onRefresh={() => void loadLocalAssets()}
      />

      <section className="panel feature-window-panel" aria-label="长期回顾">
        <div className="section-heading">
          <strong>回顾</strong>
          <span>
            {retrospectives
              ? `按 7 / 30 / 90 天汇总本地资产，生成于 ${formatDate(retrospectives.generated_at)}。`
              : "正在读取本地长期回顾。"}
          </span>
        </div>
        <div className="retrospective-toolbar" aria-label="回顾时间窗口">
          {[7, 30, 90].map((days) => (
            <button
              key={days}
              type="button"
              className={`secondary memory-activity-filter ${activeRetrospectiveDays === days ? "active" : ""}`}
              onClick={() => setActiveRetrospectiveDays(days)}
              aria-pressed={activeRetrospectiveDays === days}
            >
              <CalendarRange size={15} />
              {days} 天
            </button>
          ))}
          <button type="button" className="secondary" onClick={() => void loadRetrospectives()} disabled={retrospectiveLoading}>
            {retrospectiveLoading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            刷新回顾
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void generatePeriodReport("weekly")}
            disabled={generatingReport === "weekly"}
          >
            {generatingReport === "weekly" ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
            生成周报
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void generatePeriodReport("monthly")}
            disabled={generatingReport === "monthly"}
          >
            {generatingReport === "monthly" ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
            生成月报
          </button>
        </div>
        {retrospectiveError ? <p className="field-note error">{retrospectiveError}</p> : null}
        {retrospectiveLoading && !activeRetrospective ? (
          <EmptyState text="正在加载本地回顾数据。" />
        ) : activeRetrospective ? (
          <RetrospectiveWindowPanel
            window={activeRetrospective}
            generatingReport={generatingReport}
            onGenerateReport={(days) => void generateReport(days)}
          />
        ) : (
          <EmptyState text="暂时没有回顾数据。先完成一次聊天、任务或 Wiki 整理后再回来查看。" />
        )}
      </section>

      <section className="panel feature-window-panel" aria-label="长期记忆控制">
        <div className="section-heading">
          <strong>长期记忆控制</strong>
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
        </div>
        {memoryFactsError ? <p className="field-note error">{memoryFactsError}</p> : null}
        {exportMessage ? <p className={`field-note ${exportMessage.includes("失败") ? "error" : ""}`}>{exportMessage}</p> : null}

        {filteredMemoryFacts.length > 0 ? (
          <div className="memory-graph-list">
            {filteredMemoryFacts.map((fact) => {
              const busy = memoryFactBusyId === fact.fact_id;
              return (
                <article key={fact.fact_id} className={`memory-graph-fact ${fact.status}`}>
                  <div className="memory-graph-fact-main">
                    <strong>{memoryFactSentence(fact)}</strong>
                    <div className="memory-graph-fact-meta">
                      <span>{formatMemoryFactStatus(fact.status)}</span>
                      <span>{fact.category}</span>
                      <span>置信度 {Math.round(fact.confidence * 100)}%</span>
                      <span>支持 {fact.support_count}</span>
                    </div>
                    <p>
                      {fact.source_type}
                      {fact.memory_type ? ` / ${fact.memory_type}` : ""}
                      {fact.updated_at ? ` / ${formatDate(fact.updated_at)}` : ""}
                    </p>
                  </div>
                  <div className="memory-graph-fact-actions">
                    {fact.status !== "active" ? (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => void updateMemoryFactStatus(fact.fact_id, "confirm")}
                        disabled={busy}
                      >
                        {busy ? <Loader2 className="spin" size={15} /> : <RotateCcw size={15} />}
                        恢复使用
                      </button>
                    ) : null}
                    {fact.status !== "wrong" ? (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => void updateMemoryFactStatus(fact.fact_id, "wrong")}
                        disabled={busy}
                      >
                        {busy ? <Loader2 className="spin" size={15} /> : <XCircle size={15} />}
                        标为不准确
                      </button>
                    ) : null}
                    {fact.status !== "archived" ? (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => void updateMemoryFactStatus(fact.fact_id, "archive")}
                        disabled={busy}
                      >
                        {busy ? <Loader2 className="spin" size={15} /> : <Archive size={15} />}
                        归档
                      </button>
                    ) : null}
                    {fact.status !== "sensitive_blocked" ? (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => void updateMemoryFactStatus(fact.fact_id, "sensitive_block")}
                        disabled={busy}
                      >
                        {busy ? <Loader2 className="spin" size={15} /> : <ShieldAlert size={15} />}
                        敏感封存
                      </button>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        ) : memoryFactsLoading ? (
          <EmptyState text="正在加载长期记忆。" />
        ) : (
          <EmptyState text="没有匹配的长期记忆。" />
        )}

        {exportPreview ? (
          <div className="memory-export-preview" aria-label="长期记忆导出预览">
            <div className="section-heading compact">
              <strong>导出预览</strong>
              <span>{exportPreview.redaction_note}</span>
            </div>
            <textarea readOnly value={exportPreview.markdown_preview} />
          </div>
        ) : null}
      </section>

      <section className="panel feature-window-panel" aria-label="最近整理活动">
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
              <span>按写入类型、跳过原因和可撤销状态归类；敏感跳过项只显示安全摘要。</span>
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
    </FeatureWindowShell>
  );
}
