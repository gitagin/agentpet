import type { FormEvent } from "react";
import { Check, CircleAlert, FileDown, FolderOpen, ListChecks, Loader2, MessageSquareText, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { Panel } from "../../components/layout";
import type {
  ChatMessage,
  CompanionRetrievalReport,
  WikiDiagnosticQueueResponse,
  WikiIndexResponse,
  WikiIngestApplyResponse,
  WikiIngestPreviewResponse,
  WikiIngestReviewResponse,
  WikiLintRunResponse,
  WikiLogResponse,
  WikiQueryArchiveDetailResponse,
  WikiQueryArchiveHistoryItem,
  WikiQueryArchiveResponse,
  WikiSchemaStatus,
  WikiSynthesizeResponse,
} from "../../types";
import { formatTaskStatus } from "../tasks/taskReducer";
import { defaultWikiArchiveTargetPath } from "./wikiConstants";
import type { WikiAsyncStatus, WikiWorkflowAction, WikiWorkflowDraft } from "./wikiTypes";
import {
  formatWikiArchiveDetail,
  formatWikiArchiveHistoryMeta,
  formatWikiDiagnosticKind,
  formatWikiPreview,
  formatWikiWorkflowResult,
  getWikiArchiveId,
} from "./wikiUtils";

type WikiWorkflowPanelProps = {
  draft: WikiWorkflowDraft;
  tagInput: string;
  linkInput: string;
  approvedTargetsInput: string;
  reviewForceRefresh: boolean;
  preview: WikiIngestPreviewResponse | null;
  reviewResult: WikiIngestReviewResponse | null;
  applyResult: WikiIngestApplyResponse | WikiQueryArchiveResponse | WikiSynthesizeResponse | null;
  lintResult: WikiLintRunResponse | null;
  diagnosticsQueue: WikiDiagnosticQueueResponse | null;
  schemaStatus: WikiSchemaStatus | null;
  indexStatus: WikiIndexResponse | null;
  logStatus: WikiLogResponse | null;
  coreStatus: WikiAsyncStatus;
  coreError: string;
  archiveHistory: WikiQueryArchiveHistoryItem[];
  archiveHistoryStatus: WikiAsyncStatus;
  archiveHistoryError: string;
  openedArchive: WikiQueryArchiveDetailResponse | null;
  openingArchiveId: string | null;
  companionContextReports: CompanionRetrievalReport[];
  companionContextReportStatus: WikiAsyncStatus;
  companionContextReportError: string;
  lastWikiArchiveId: string | null;
  workflowAction: WikiWorkflowAction | null;
  latestArchiveMessage?: ChatMessage;
  latestKnowledgeCitationCount: number;
  archiveHistorySummary: string;
  archiveHistoryLoading: boolean;
  lintIssueCount: number;
  formatIssueSeverity: (severity: string) => string;
  onDraftChange: (patch: Partial<WikiWorkflowDraft>) => void;
  onTagInputChange: (value: string) => void;
  onLinkInputChange: (value: string) => void;
  onApprovedTargetsInputChange: (value: string) => void;
  onReviewForceRefreshChange: (value: boolean) => void;
  onPreview: (event: FormEvent) => void;
  onReview: () => void;
  onApply: () => void;
  onArchiveLatestQuery: () => void;
  onSynthesize: () => void;
  onRunLint: () => void;
  onLoadDiagnosticsQueue: () => void;
  onLoadArchiveHistory: () => void;
  onLoadCoreStatus: () => void;
  onUseReviewRecommendedTargets: () => void;
  onOpenArchive: (archiveId: string) => void;
};

export function WikiWorkflowPanel({
  draft,
  tagInput,
  linkInput,
  approvedTargetsInput,
  reviewForceRefresh,
  preview,
  reviewResult,
  applyResult,
  lintResult,
  diagnosticsQueue,
  schemaStatus,
  indexStatus,
  logStatus,
  coreStatus,
  coreError,
  archiveHistory,
  archiveHistoryStatus,
  archiveHistoryError,
  openedArchive,
  openingArchiveId,
  companionContextReports,
  companionContextReportStatus,
  companionContextReportError,
  lastWikiArchiveId,
  workflowAction,
  latestArchiveMessage,
  latestKnowledgeCitationCount,
  archiveHistorySummary,
  archiveHistoryLoading,
  lintIssueCount,
  formatIssueSeverity,
  onDraftChange,
  onTagInputChange,
  onLinkInputChange,
  onApprovedTargetsInputChange,
  onReviewForceRefreshChange,
  onPreview,
  onReview,
  onApply,
  onArchiveLatestQuery,
  onSynthesize,
  onRunLint,
  onLoadDiagnosticsQueue,
  onLoadArchiveHistory,
  onLoadCoreStatus,
  onUseReviewRecommendedTargets,
  onOpenArchive,
}: WikiWorkflowPanelProps) {
  const workflowBusy = workflowAction !== null;

  return (
    <Panel id="wiki-workflow-panel" icon={<FileDown size={18} />} title="高级资料库维护">
      <details className="stack advanced-vault-maintenance" aria-label="高级 Vault 维护工具">
        <summary>
          <strong>展开资料库页面维护工具</strong>
          <span>这些按钮调用现有 Wiki API（内部/历史命名），保留给手工预览、审查、归档、综合整理和检查；主流程优先使用上方对话。</span>
        </summary>
        <form className="stack" onSubmit={onPreview}>
          <div className="section-heading">
            <strong>维护 Obsidian 资料库里的长期记忆</strong>
            <span>这是高级维护入口，不作为日常主流程；桌宠对话会优先自动整理，只有高风险项才会进入确认流程。</span>
          </div>
          <label>
            <span>审查/应用目标</span>
            <input
              value={approvedTargetsInput}
              onChange={(event) => onApprovedTargetsInputChange(event.target.value)}
              placeholder="留空=应用预览全部页面；可用审查推荐填充"
            />
          </label>
          <div className="split">
            <label>
              <span>标题</span>
              <input value={draft.title} onChange={(event) => onDraftChange({ title: event.target.value })} placeholder="运行时笔记" />
            </label>
            <label>
              <span>来源类型</span>
              <input
                value={draft.source_type || ""}
                onChange={(event) => onDraftChange({ source_type: event.target.value })}
                placeholder="manual"
              />
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={reviewForceRefresh} onChange={(event) => onReviewForceRefreshChange(event.target.checked)} />
              <span>审查强制刷新</span>
            </label>
          </div>
          <div className="split">
            <label>
              <span>来源地址</span>
              <input
                value={draft.source_uri || ""}
                onChange={(event) => onDraftChange({ source_uri: event.target.value })}
                placeholder="可选：来源 URL 或本地引用"
              />
            </label>
            <label>
              <span>最多页面数</span>
              <input
                type="number"
                min={1}
                max={15}
                value={draft.max_pages ?? 15}
                onChange={(event) => onDraftChange({ max_pages: Number(event.target.value) })}
              />
            </label>
          </div>
          <div className="split">
            <label>
              <span>归档目标</span>
              <input
                value={draft.target_path || ""}
                onChange={(event) => onDraftChange({ target_path: event.target.value })}
                placeholder={defaultWikiArchiveTargetPath}
              />
            </label>
            <label>
              <span>归档章节</span>
              <input value={draft.section || ""} onChange={(event) => onDraftChange({ section: event.target.value })} placeholder="可选" />
            </label>
          </div>
          <label>
            <span>内容</span>
            <textarea
              value={draft.content}
              onChange={(event) => onDraftChange({ content: event.target.value })}
              placeholder="要写入 Vault/Wiki/... 的 Markdown 内容"
            />
          </label>
          <div className="split">
            <label>
              <span>标签</span>
              <input value={tagInput} onChange={(event) => onTagInputChange(event.target.value)} placeholder="desktop,wiki" />
            </label>
            <label>
              <span>关联链接</span>
              <input value={linkInput} onChange={(event) => onLinkInputChange(event.target.value)} placeholder="Wiki/Runtime.md, Wiki/API.md" />
            </label>
          </div>
          <div className="split">
            <label className="checkbox-row">
              <input type="checkbox" checked={draft.write_report} onChange={(event) => onDraftChange({ write_report: event.target.checked })} />
              <span>写入检查报告</span>
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={draft.allow_mixed_sources}
                onChange={(event) => onDraftChange({ allow_mixed_sources: event.target.checked })}
              />
              <span>允许混合来源归档</span>
            </label>
          </div>
          <div className="button-row">
            <button type="submit" disabled={workflowBusy}>
              {workflowAction === "preview" ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
              预览
            </button>
            <button type="button" className="secondary" onClick={onReview} disabled={workflowBusy || !preview}>
              {workflowAction === "review" ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
              审查
            </button>
            <button type="button" className="secondary" onClick={onApply} disabled={workflowBusy}>
              {workflowAction === "apply" ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
              应用
            </button>
            <button
              type="button"
              className="secondary"
              onClick={onArchiveLatestQuery}
              disabled={workflowBusy || latestKnowledgeCitationCount === 0}
              title={latestKnowledgeCitationCount > 0 ? "归档最近一条带 Vault 引用的已完成助手回复" : "没有可归档的知识库引用回复"}
            >
              {workflowAction === "archive" ? <Loader2 className="spin" size={16} /> : <MessageSquareText size={16} />}
              归档查询
            </button>
            <button type="button" className="secondary" onClick={onSynthesize} disabled={workflowBusy}>
              {workflowAction === "synthesize" ? <Loader2 className="spin" size={16} /> : <FileDown size={16} />}
              综合整理
            </button>
            <button type="button" className="secondary" onClick={onRunLint} disabled={workflowBusy}>
              {workflowAction === "lint" ? <Loader2 className="spin" size={16} /> : <ListChecks size={16} />}
              运行检查
            </button>
            <button type="button" className="secondary" onClick={onLoadDiagnosticsQueue} disabled={workflowBusy}>
              {workflowAction === "diagnostics" ? <Loader2 className="spin" size={16} /> : <CircleAlert size={16} />}
              只读诊断
            </button>
            <button type="button" className="secondary" onClick={onLoadArchiveHistory} disabled={workflowBusy || archiveHistoryLoading}>
              {archiveHistoryLoading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
              刷新归档
            </button>
            <button type="button" className="secondary" onClick={onLoadCoreStatus} disabled={workflowBusy || coreStatus === "loading"}>
              {coreStatus === "loading" ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
              刷新核心状态
            </button>
          </div>
          <dl className="details">
            <div>
              <dt>预览</dt>
              <dd>{preview ? `${formatTaskStatus(preview.status)} / ${preview.page_plans.length} 页 / ${preview.source_hash.slice(0, 12)}` : "无"}</dd>
            </div>
            <div>
              <dt>最近应用</dt>
              <dd>{formatWikiWorkflowResult(applyResult, formatTaskStatus)}</dd>
            </div>
            <div>
              <dt>审查</dt>
              <dd>{reviewResult ? `${formatTaskStatus(reviewResult.status)} / ${reviewResult.findings.length} 个发现 / ${reviewResult.recommended_targets.length} 个推荐` : "未运行"}</dd>
            </div>
            <div>
              <dt>Agent 引用来源</dt>
              <dd>{latestArchiveMessage ? `${latestArchiveMessage.id} / ${latestKnowledgeCitationCount} 条 Vault 引用` : "无"}</dd>
            </div>
            <div>
              <dt>检查</dt>
              <dd>{lintResult ? `${lintResult.summary.pages ?? 0} 页 / ${lintIssueCount} 个问题` : "未运行"}</dd>
            </div>
            <div>
              <dt>诊断队列</dt>
              <dd>{diagnosticsQueue ? `${diagnosticsQueue.items.length} 项 / ${diagnosticsQueue.generated_at}` : "未加载"}</dd>
            </div>
            <div>
              <dt>上下文报告</dt>
              <dd>{companionContextReportStatus === "loading" ? "刷新中" : companionContextReports.length ? `${companionContextReports.length} 条` : "未加载"}</dd>
            </div>
            <div>
              <dt>最新归档</dt>
              <dd>{lastWikiArchiveId || "无"}</dd>
            </div>
            <div>
              <dt>历史</dt>
              <dd>{archiveHistorySummary}</dd>
            </div>
            <div>
              <dt>结构</dt>
              <dd>{schemaStatus?.exists ? schemaStatus.path : coreStatus === "error" ? "异常" : "未加载"}</dd>
            </div>
            <div>
              <dt>索引</dt>
              <dd>{indexStatus ? `${indexStatus.entries.length} 条` : "未加载"}</dd>
            </div>
            <div>
              <dt>日志</dt>
              <dd>{logStatus ? `${logStatus.entries.length} 条` : "未加载"}</dd>
            </div>
          </dl>
          {coreError ? <p className="field-note error">{coreError}</p> : null}
          {preview ? <pre className="diff-preview">{formatWikiPreview(preview)}</pre> : null}
          {reviewResult ? (
            <section className="wiki-review-result" aria-label="Wiki ingest review result">
              <div className="section-heading">
                <strong>审查结果</strong>
                <span>{formatTaskStatus(reviewResult.status)} / {reviewResult.review_id}</span>
              </div>
              <p>{reviewResult.summary}</p>
              {reviewResult.model_error ? <p className="field-note error">{reviewResult.model_error}</p> : null}
              {reviewResult.recommended_targets.length > 0 ? (
                <div className="wiki-review-targets">
                  <div>
                    <strong>推荐应用目标</strong>
                    <span>{reviewResult.recommended_targets.join(", ")}</span>
                  </div>
                  <button type="button" className="secondary" onClick={onUseReviewRecommendedTargets} disabled={workflowBusy}>
                    <Check size={16} />
                    使用推荐
                  </button>
                </div>
              ) : null}
              {reviewResult.findings.length > 0 ? (
                <div className="message-events">
                  {reviewResult.findings.map((finding, index) => (
                    <span key={`${finding.code}-${finding.target_path || index}`} className={finding.severity === "error" ? "error" : undefined}>
                      <strong>{formatIssueSeverity(finding.severity)} / {finding.code}</strong>
                      {finding.target_path ? `${finding.target_path}: ` : ""}
                      {finding.message}
                    </span>
                  ))}
                </div>
              ) : null}
            </section>
          ) : null}
          {lintResult?.issues.length ? (
            <div className="message-events" aria-label="Wiki 检查问题">
              {lintResult.issues.slice(0, 6).map((issue, index) => (
                <span key={`${issue.code}-${issue.path || "wiki"}-${issue.target || index}`} className={issue.severity === "error" ? "error" : undefined}>
                  <strong>{formatIssueSeverity(issue.severity)}</strong>
                  {issue.path ? `${issue.path}${issue.target ? ` -> ${issue.target}` : ""}：` : ""}
                  {issue.message}
                </span>
              ))}
            </div>
          ) : null}
          {diagnosticsQueue?.items.length ? (
            <section className="wiki-review-result" aria-label="Wiki 只读诊断队列">
              <div className="section-heading">
                <strong>只读诊断队列</strong>
                <span>{diagnosticsQueue.items.length} 项，不写入 Vault</span>
              </div>
              <div className="message-events">
                {diagnosticsQueue.items.slice(0, 8).map((item) => (
                  <span key={item.id} className={item.severity === "error" ? "error" : undefined}>
                    <strong>{formatIssueSeverity(item.severity)} / {formatWikiDiagnosticKind(item.kind)}</strong>
                    {item.related_paths.length ? `${item.related_paths.join(", ")}：` : ""}
                    {item.question}
                    {item.repair_proposal ? ` / 建议：${item.repair_proposal.operation} ${item.repair_proposal.target_path || ""}` : ""}
                  </span>
                ))}
              </div>
            </section>
          ) : null}
          {companionContextReportError ? <p className="field-note error">{companionContextReportError}</p> : null}
          {companionContextReports.length ? (
            <section className="wiki-review-result" aria-label="Companion 上下文报告">
              <div className="section-heading">
                <strong>Companion 上下文报告</strong>
                <span>最近 {companionContextReports.length} 条，只读</span>
              </div>
              <div className="message-events">
                {companionContextReports.map((report) => (
                  <span key={report.id}>
                    <strong>{report.strategy} / {report.agent_run_id}</strong>
                    候选 {report.candidate_count}，选中 {report.selected_count}，预算丢弃 {report.budget_drop_count}，范围 {report.selected_scopes.join(", ") || "无"}
                  </span>
                ))}
              </div>
            </section>
          ) : companionContextReportStatus === "empty" ? (
            <p className="field-note">还没有 Companion 上下文报告。</p>
          ) : null}
          {openedArchive ? <pre className="diff-preview wiki-opened-archive">{formatWikiArchiveDetail(openedArchive)}</pre> : null}
          <section className="wiki-archive-history" aria-label="Wiki 查询归档历史">
            <div className="section-heading">
              <strong>查询归档历史</strong>
              <span>{archiveHistorySummary}</span>
            </div>
            {archiveHistoryError ? <p className="field-note error">{archiveHistoryError}</p> : null}
            {archiveHistory.length > 0 ? (
              <div className="wiki-archive-history-list">
                {archiveHistory.slice(0, 8).map((archive, index) => {
                  const archiveId = getWikiArchiveId(archive);
                  const opening = Boolean(archiveId && openingArchiveId === archiveId);
                  return (
                    <article
                      key={archiveId || `${archive.target_path}-${archive.created_at}-${index}`}
                      className={`wiki-archive-history-item${archiveId && archiveId === lastWikiArchiveId ? " active" : ""}`}
                    >
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
            ) : archiveHistoryStatus === "empty" ? (
              <p className="field-note">还没有查询归档。</p>
            ) : null}
          </section>
        </form>
      </details>
    </Panel>
  );
}
