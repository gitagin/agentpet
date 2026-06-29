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
  vaultConfigured: boolean;
  indexRequired: boolean;
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
  onTryKnowledgeSnippet?: () => void;
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

function recentWikiPages(indexStatus: WikiIndexResponse | null): WikiIndexEntry[] {
  return [...(indexStatus?.entries || [])]
    .sort((left, right) => wikiTimeValue(right.updated_at) - wikiTimeValue(left.updated_at))
    .slice(0, 6);
}

export function WikiBrowserPanel({
  vaultConfigured,
  indexRequired,
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
  onTryKnowledgeSnippet,
}: WikiBrowserPanelProps) {
  const workflowBusy = workflowAction !== null;
  const recentPages = recentWikiPages(indexStatus);
  const lintIssues = lintResult?.issues.slice(0, 5) || [];
  const diagnosticItems = diagnosticsQueue?.items.slice(0, 5) || [];
  const noWikiPages = Boolean(indexStatus && indexStatus.entries.length === 0);
  const readinessState = !vaultConfigured
    ? {
        tone: "error",
        title: "未设置本机文件夹",
        description: "请先在设置中选择保存位置，之后才能写入资料页。",
      }
    : indexRequired
      ? {
          tone: "warning",
          title: "需要索引",
          description: "整理完成后刷新状态，最近生成的资料页会显示为卡片。",
        }
      : noWikiPages
        ? {
            tone: "empty",
            title: "还没有资料页",
            description: "从上方整理器粘贴一段材料，预览后即可生成第一张卡片。",
          }
        : null;
  const recentSummary = readinessState
    ? readinessState.description
    : indexStatus
      ? `最近 ${recentPages.length} 个页面，索引更新于 ${formatWikiTime(indexStatus.updated_at)}。`
      : coreStatus === "loading"
        ? "正在读取最近整理出的页面。"
        : "刷新状态后会显示最近整理出的页面。";

  return (
    <Panel id="wiki-browser-panel" icon={<BookOpen size={18} />} title="最近整理出的资料页">
      <div className="wiki-browser-shell">
        <section className="wiki-recent-output" aria-label="最近资料页">
          <div className="section-heading">
            <strong>最近生成的资料页</strong>
            <span>{recentSummary}</span>
          </div>
          {readinessState ? (
            <div className={`wiki-readiness-banner ${readinessState.tone}`} aria-label="资料整理状态">
              <div>
                <strong>{readinessState.title}</strong>
                <span>{readinessState.description}</span>
              </div>
            </div>
          ) : null}
          {onTryKnowledgeSnippet ? (
            <div className="guided-trial-actions" aria-label="试用资料整理操作">
              <button type="button" className="secondary" onClick={onTryKnowledgeSnippet} disabled={workflowBusy}>
                <BookOpen size={16} />
                粘贴知识片段
              </button>
            </div>
          ) : null}
          <div className="wiki-recent-page-grid">
            {recentPages.length > 0 ? (
              recentPages.map((entry) => (
                <article key={entry.relative_path} className="wiki-page-card">
                  <div className="wiki-page-card-head">
                    <BookOpen size={16} aria-hidden="true" />
                    <div>
                      <strong>{entry.title}</strong>
                      <small>{entry.page_type || "页面"}</small>
                    </div>
                  </div>
                  <p>{entry.summary || "还没有摘要。"}</p>
                  <dl className="wiki-page-card-meta">
                    <div>
                      <dt>路径</dt>
                      <dd>{entry.relative_path}</dd>
                    </div>
                    <div>
                      <dt>更新时间</dt>
                      <dd>{formatWikiTime(entry.updated_at)}</dd>
                    </div>
                    <div>
                      <dt>类型</dt>
                      <dd>{entry.page_type || "页面"}</dd>
                    </div>
                    <div>
                      <dt>来源</dt>
                      <dd>{entry.source_count} 条</dd>
                    </div>
                  </dl>
                </article>
              ))
            ) : (
              <p className="field-note">还没有可展示的资料页。请从上方整理器创建或更新一个页面。</p>
            )}
          </div>
        </section>

        <details className="wiki-browser-maintenance" aria-label="知识库状态和维护记录">
          <summary>
            <strong>状态、日志与只读检查</strong>
            <span>刷新索引信号、查看更新日志、诊断提示和查询归档。</span>
          </summary>
          <section className="wiki-browser-hero" aria-label="知识库准备状态">
            <dl className="details wiki-browser-status-grid">
              <div>
                <dt>本机文件夹</dt>
                <dd>{vaultConfigured ? "已绑定" : "未绑定"}</dd>
              </div>
              <div>
                <dt>索引</dt>
                <dd>{indexRequired ? "需要刷新" : indexStatus ? `${indexStatus.entries.length} 页` : "未加载"}</dd>
              </div>
              <div>
                <dt>规则</dt>
                <dd>{schemaStatus?.exists ? `已加载 / ${formatWikiTime(schemaStatus.updated_at)}` : "未加载"}</dd>
              </div>
              <div>
                <dt>页面</dt>
                <dd>{indexStatus ? `${indexStatus.entries.length} 页 / ${formatWikiTime(indexStatus.updated_at)}` : "未加载"}</dd>
              </div>
              <div>
                <dt>日志</dt>
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
                刷新历史
              </button>
              <button type="button" className="secondary" onClick={onLoadDiagnosticsQueue} disabled={workflowBusy}>
                {workflowAction === "diagnostics" ? <Loader2 className="spin" size={16} /> : <CircleAlert size={16} />}
                只读检查
              </button>
            </div>
            {coreError ? <p className="field-note error">{coreError}</p> : null}
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
              <span>这里不会写入文件；生成报告或修复页面仍在高级维护中处理。</span>
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
        </details>
      </div>
    </Panel>
  );
}
