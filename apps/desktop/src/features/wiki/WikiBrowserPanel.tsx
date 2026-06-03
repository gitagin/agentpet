import { BookOpen, CircleAlert, Clock3, FolderOpen, Loader2, RefreshCw } from "lucide-react";
import { Panel } from "../../components/layout";
import type {
  WikiDiagnosticQueueResponse,
  WikiIndexEntry,
  WikiIndexResponse,
  WikiLintRunResponse,
  WikiLogResponse,
  WikiQueryArchiveHistoryItem,
  WikiSchemaStatus,
} from "../../types";
import type { WikiAsyncStatus, WikiWorkflowAction } from "./wikiTypes";
import {
  formatWikiArchiveHistoryMeta,
  formatWikiDiagnosticKind,
  getWikiArchiveId,
} from "./wikiUtils";
import { formatTaskStatus } from "../tasks/taskReducer";

type WikiBrowserPanelProps = {
  schemaStatus: WikiSchemaStatus | null;
  indexStatus: WikiIndexResponse | null;
  logStatus: WikiLogResponse | null;
  lintResult: WikiLintRunResponse | null;
  diagnosticsQueue: WikiDiagnosticQueueResponse | null;
  archiveHistory: WikiQueryArchiveHistoryItem[];
  archiveHistoryStatus: WikiAsyncStatus;
  archiveHistoryError: string;
  archiveHistoryLoading: boolean;
  coreStatus: WikiAsyncStatus;
  coreError: string;
  workflowAction: WikiWorkflowAction | null;
  openingArchiveId: string | null;
  formatIssueSeverity: (severity: string) => string;
  onLoadCoreStatus: () => void;
  onLoadArchiveHistory: () => void;
  onLoadDiagnosticsQueue: () => void;
  onOpenArchive: (archiveId: string) => void;
};

function wikiTimeValue(value?: string | null): number {
  if (!value) {
    return 0;
  }
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function formatWikiTime(value?: string | null): string {
  const time = wikiTimeValue(value);
  if (!time) {
    return "无时间";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(time));
}

function recentSummaryPages(indexStatus: WikiIndexResponse | null): WikiIndexEntry[] {
  return (indexStatus?.entries || [])
    .filter((entry) => entry.relative_path.startsWith("Wiki/Companion/Summaries/"))
    .sort((left, right) => wikiTimeValue(right.updated_at) - wikiTimeValue(left.updated_at))
    .slice(0, 5);
}

export function WikiBrowserPanel({
  schemaStatus,
  indexStatus,
  logStatus,
  lintResult,
  diagnosticsQueue,
  archiveHistory,
  archiveHistoryStatus,
  archiveHistoryError,
  archiveHistoryLoading,
  coreStatus,
  coreError,
  workflowAction,
  openingArchiveId,
  formatIssueSeverity,
  onLoadCoreStatus,
  onLoadArchiveHistory,
  onLoadDiagnosticsQueue,
  onOpenArchive,
}: WikiBrowserPanelProps) {
  const workflowBusy = workflowAction !== null;
  const summaryPages = recentSummaryPages(indexStatus);
  const lintIssues = lintResult?.issues.slice(0, 5) || [];
  const diagnosticItems = diagnosticsQueue?.items.slice(0, 5) || [];

  return (
    <Panel id="wiki-browser-panel" icon={<BookOpen size={18} />} title="知识浏览">
      <div className="wiki-browser-shell">
        <section className="wiki-browser-hero" aria-label="知识库状态">
          <div className="section-heading">
            <strong>知识库状态</strong>
            <span>
              {indexStatus
                ? `${indexStatus.entries.length} 个知识页面，更新于 ${formatWikiTime(indexStatus.updated_at)}。`
                : coreStatus === "loading"
                  ? "正在读取知识页面、更新日志和安全检查状态。"
                  : "尚未加载知识库状态。"}
            </span>
          </div>
          <dl className="details wiki-browser-status-grid">
            <div>
              <dt>维护规则</dt>
              <dd>{schemaStatus?.exists ? `已加载 / ${formatWikiTime(schemaStatus.updated_at)}` : "未加载"}</dd>
            </div>
            <div>
              <dt>知识页面</dt>
              <dd>{indexStatus ? `${indexStatus.entries.length} 页 / ${formatWikiTime(indexStatus.updated_at)}` : "未加载"}</dd>
            </div>
            <div>
              <dt>更新日志</dt>
              <dd>{logStatus ? `${logStatus.entries.length} 条 / ${formatWikiTime(logStatus.updated_at)}` : "未加载"}</dd>
            </div>
            <div>
              <dt>只读检查</dt>
              <dd>{lintResult ? `${lintResult.summary.pages ?? 0} 页 / ${lintResult.summary.issues ?? lintResult.issues.length} 个问题` : "未运行"}</dd>
            </div>
          </dl>
          <div className="button-row">
            <button type="button" className="secondary" onClick={onLoadCoreStatus} disabled={coreStatus === "loading" || workflowBusy}>
              {coreStatus === "loading" ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
              刷新状态
            </button>
            <button type="button" className="secondary" onClick={onLoadArchiveHistory} disabled={archiveHistoryLoading || workflowBusy}>
              {archiveHistoryLoading ? <Loader2 className="spin" size={16} /> : <Clock3 size={16} />}
              刷新查询历史
            </button>
            <button type="button" className="secondary" onClick={onLoadDiagnosticsQueue} disabled={workflowBusy}>
              {workflowAction === "diagnostics" ? <Loader2 className="spin" size={16} /> : <CircleAlert size={16} />}
              只读检查
            </button>
          </div>
          {coreError ? <p className="field-note error">{coreError}</p> : null}
        </section>

        <section className="wiki-browser-section" aria-label="最近自动总结页">
          <div className="section-heading">
            <strong>最近自动总结页</strong>
            <span>桌宠从对话中沉淀的知识页面，按最近更新时间展示。</span>
          </div>
          <div className="wiki-browser-list">
            {summaryPages.length > 0 ? (
              summaryPages.map((entry) => (
                <article key={entry.relative_path} className="wiki-browser-item">
                  <strong>{entry.title}</strong>
                  <span>{entry.page_type === "summary" ? "自动总结页面" : "知识页面"}</span>
                  <small>{entry.summary || "无摘要"} / 更新于 {formatWikiTime(entry.updated_at)}</small>
                  <details className="wiki-technical-details">
                    <summary>页面位置</summary>
                    <small>{entry.relative_path}</small>
                  </details>
                </article>
              ))
            ) : (
              <p className="field-note">还没有自动总结页，或索引尚未刷新。</p>
            )}
          </div>
        </section>

        <section className="wiki-browser-section" aria-label="最近更新日志">
          <div className="section-heading">
            <strong>最近更新日志</strong>
            <span>只展示最近的知识库更新记录。</span>
          </div>
          <div className="wiki-browser-list">
            {logStatus?.entries.length ? (
              logStatus.entries.slice(0, 6).map((entry) => (
                <article key={`${entry.timestamp}-${entry.operation}-${entry.title}`} className="wiki-browser-item">
                  <strong>{entry.operation} / {entry.title}</strong>
                  <span>{entry.timestamp}</span>
                  <small>{entry.details || "无详情"}</small>
                </article>
              ))
            ) : (
              <p className="field-note">还没有可显示的知识库更新日志。</p>
            )}
          </div>
        </section>

        <section className="wiki-browser-section" aria-label="只读检查和诊断提示">
          <div className="section-heading">
            <strong>只读检查和诊断提示</strong>
            <span>这里不会写入文件；生成报告或修复页面仍在下方高级维护中处理。</span>
          </div>
          <div className="message-events wiki-browser-events">
            {lintIssues.map((issue, index) => (
              <span key={`lint-${issue.code}-${issue.path || index}`} className={issue.severity === "error" ? "error" : undefined}>
                <strong>{formatIssueSeverity(issue.severity)} / {issue.code}</strong>
                {issue.path ? `${issue.path}${issue.target ? ` -> ${issue.target}` : ""}：` : ""}
                {issue.message}
              </span>
            ))}
            {diagnosticItems.map((item) => (
              <span key={`diagnostic-${item.id}`} className={item.severity === "error" ? "error" : undefined}>
                <strong>{formatIssueSeverity(item.severity)} / {formatWikiDiagnosticKind(item.kind)}</strong>
                {item.related_paths.length ? `${item.related_paths.join(", ")}：` : ""}
                {item.question}
              </span>
            ))}
            {lintIssues.length === 0 && diagnosticItems.length === 0 ? (
              <span>
                <strong>暂无提示</strong>
                尚未运行只读检查，当前没有可展示的问题。
              </span>
            ) : null}
          </div>
        </section>

        <section className="wiki-browser-section" aria-label="查询历史入口">
          <div className="section-heading">
            <strong>查询历史</strong>
            <span>
              {archiveHistoryStatus === "error"
                ? archiveHistoryError
                : archiveHistory.length > 0
                  ? `${archiveHistory.length} 条近期归档，可打开查看详情。`
                  : "还没有查询归档。"}
            </span>
          </div>
          {archiveHistoryError ? <p className="field-note error">{archiveHistoryError}</p> : null}
          <div className="wiki-archive-history-list">
            {archiveHistory.slice(0, 6).map((archive, index) => {
              const archiveId = getWikiArchiveId(archive);
              const opening = Boolean(archiveId && openingArchiveId === archiveId);
              return (
                <article key={archiveId || `${archive.target_path}-${index}`} className="wiki-archive-history-item">
                  <div className="wiki-archive-history-main">
                    <strong>{archive.title || archive.page?.title || archive.target_path}</strong>
                    <span>{archive.question}</span>
                    <small>{formatWikiArchiveHistoryMeta(archive, formatTaskStatus)}</small>
                  </div>
                  <p>{archive.answer_preview}</p>
                  <button type="button" className="secondary" onClick={() => onOpenArchive(archiveId)} disabled={workflowBusy || !archiveId || Boolean(openingArchiveId)}>
                    {opening ? <Loader2 className="spin" size={16} /> : <FolderOpen size={16} />}
                    打开
                  </button>
                </article>
              );
            })}
          </div>
        </section>
      </div>
    </Panel>
  );
}
