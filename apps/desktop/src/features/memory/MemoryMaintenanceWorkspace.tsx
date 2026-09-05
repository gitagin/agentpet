import {
  AlertTriangle,
  Brain,
  CalendarClock,
  Check,
  CircleCheck,
  Database,
  Loader2,
  Pencil,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { useConfirmationDialog } from "../../hooks/useConfirmationDialog";
import { formatDate } from "../../services/dateFormatting";
import type { MemoryReviewAction, MemoryReviewItem } from "../../types";
import type { MaintenanceLoadStatus, UseMemoryMaintenanceResult } from "./useMemoryMaintenance";

type MemoryMaintenanceWorkspaceProps = {
  api: UseMemoryMaintenanceResult;
};

const hygieneTypeLabels: Record<string, string> = {
  stale_recent_state: "过期状态",
  low_confidence_stale: "低置信度过期",
  sensitive_candidate: "敏感候选",
};

const reviewActionLabels: Record<MemoryReviewAction, string> = {
  keep: "保留",
  edit: "编辑",
  forget: "忘记",
  only_this_week: "仅本周",
  mark_completed: "标记完成",
};

const memoryKindLabels: Record<string, string> = {
  candidate: "待确认记忆",
  fact: "长期记忆",
  goal: "目标",
  preference: "个人偏好",
  relation: "实体关系",
  task: "任务",
};

const lifecycleLabels: Record<string, string> = {
  active: "使用中",
  archived: "已归档",
  candidate: "待确认",
  completed: "已完成",
  hidden: "已隐藏",
  pending: "待确认",
  rejected: "已拒绝",
};

const sourceLabels: Record<string, string> = {
  explicit_user: "用户明确说明",
  user_message: "用户消息",
  assistant_message: "助手消息",
  consolidation: "本机记忆整理",
  imported_source: "导入资料",
};

const internalSummary = /(?:entity|fact|candidate):[0-9a-f-]{16,}|\b(?:prefers|contradicts|related_to)\b/i;

function readableMemoryKind(item: MemoryReviewItem): string {
  return memoryKindLabels[item.memory_kind || ""] || memoryKindLabels[item.target_type] || "记忆";
}

function readableSummary(item: MemoryReviewItem): string {
  return internalSummary.test(item.summary) ? `一条${readableMemoryKind(item)}` : item.summary;
}

function readableLifecycle(status: string): string {
  return lifecycleLabels[status] || "状态待核验";
}

function readableSource(source: string): string {
  return sourceLabels[source] || "本机记录";
}

function reviewActionIcon(action: MemoryReviewAction) {
  if (action === "keep") return <Check size={14} aria-hidden="true" />;
  if (action === "edit") return <Pencil size={14} aria-hidden="true" />;
  if (action === "forget") return <Trash2 size={14} aria-hidden="true" />;
  if (action === "mark_completed") return <CircleCheck size={14} aria-hidden="true" />;
  return <CalendarClock size={14} aria-hidden="true" />;
}

function riskLabel(tier: string): string {
  if (tier === "high") {
    return "高风险";
  }
  if (tier === "medium") {
    return "中风险";
  }
  return "低风险";
}

function SectionStatus({ status, error, onRetry }: { status: MaintenanceLoadStatus; error: string; onRetry: () => void }) {
  if (status === "loading") {
    return <p className="llmwiki-inline-success" role="status"><Loader2 className="spin" size={14} />加载中…</p>;
  }
  if (status === "error") {
    return <div className="llmwiki-inline-error" role="alert">{error}<button type="button" className="text-button" onClick={onRetry}>重试</button></div>;
  }
  return null;
}

function emptyHint(loading: boolean, hasContent: boolean, message: string) {
  if (loading || hasContent) {
    return null;
  }
  return <p className="llmwiki-muted">{message}</p>;
}

export function MemoryMaintenanceWorkspace({ api }: MemoryMaintenanceWorkspaceProps) {
  const { confirm, confirmationDialog } = useConfirmationDialog();
  const { loadAssets, loadHygiene, loadReview } = api;
  const [editingReviewId, setEditingReviewId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");

  useEffect(() => {
    void loadAssets();
    void loadHygiene();
    void loadReview();
    // 打开该工作区时加载一次；三个 loader 均为稳定引用。
  }, [loadAssets, loadHygiene, loadReview]);

  const allLoading = api.assetsStatus === "loading" || api.hygieneStatus === "loading" || api.reviewStatus === "loading";

  function refreshAll() {
    void api.loadAssets();
    void api.loadHygiene();
    void api.loadReview();
  }

  async function handleHygieneAction(suggestionId: string, requiresConfirmation: boolean, actionLabel: string) {
    let confirmed = false;
    if (requiresConfirmation) {
      const ok = await confirm({
        title: "确认执行整理建议？",
        message: `${actionLabel} 会修改本地记忆，且该操作不可撤销。`,
        confirmLabel: "确认执行",
      });
      if (!ok) {
        return;
      }
      confirmed = true;
    }
    await api.applyHygiene(suggestionId, confirmed);
  }

  function startEdit(item: MemoryReviewItem) {
    setEditingReviewId(item.review_id);
    setEditDraft(item.summary);
  }

  function cancelEdit() {
    setEditingReviewId(null);
    setEditDraft("");
  }

  async function saveEdit(item: MemoryReviewItem) {
    await api.applyReviewAction(item, "edit", editDraft.trim());
    cancelEdit();
  }

  const reviewItems = api.review?.items || [];
  const reviewSummary = api.review?.summary || { kept: 0, temporary: 0, ignored: 0 };

  return (
    <section className="llmwiki-workspace-panel llmwiki-maintenance-workspace" aria-label="记忆维护工作区">
      {confirmationDialog}
      <header className="llmwiki-panel-header">
        <div>
          <p className="llmwiki-eyebrow">记忆维护</p>
          <h2>健康检查与整理</h2>
          <p className="llmwiki-panel-description">查看本地资产的规模，处理过期与敏感记忆，并按周复核哪些记忆值得保留。</p>
        </div>
        <div className="llmwiki-panel-actions">
          <button type="button" className="icon-button" onClick={refreshAll} disabled={allLoading} aria-label="刷新维护面板" title="刷新维护面板">
            <RefreshCw size={16} className={allLoading ? "is-spinning" : ""} />
          </button>
        </div>
      </header>

      <div className="llmwiki-maintenance-grid">
        {/* 本地资产统计 */}
        <section className="feature-window-panel maintenance-card" aria-label="本地资产统计">
          <div className="section-heading">
            <strong><Database size={15} aria-hidden="true" /> 本地资产统计</strong>
            <span>本机保存了多少资料与记忆。</span>
          </div>
          <SectionStatus status={api.assetsStatus} error={api.assetsError} onRetry={() => void api.loadAssets()} />
          {api.assets ? (
            <dl className="maintenance-stat-grid">
              <div><dt>聊天日记</dt><dd>{api.assets.chat_diary_entries} 条 / {api.assets.chat_diary_days} 天</dd></div>
              <div><dt>长期记忆</dt><dd>{api.assets.long_term_memory_count} 条</dd></div>
              <div><dt>Wiki 页面</dt><dd>{api.assets.wiki_page_count} 页</dd></div>
              <div><dt>任务</dt><dd>{api.assets.completed_task_count} / {api.assets.task_count} 已完成</dd></div>
              <div><dt>可回滚操作</dt><dd>{api.assets.reversible_operation_count} 条</dd></div>
              <div><dt>最近整理</dt><dd>{api.assets.latest_organization_at ? formatDate(api.assets.latest_organization_at, { style: "mediumDateTime" }) : "暂无"}</dd></div>
            </dl>
          ) : emptyHint(api.assetsStatus === "loading", Boolean(api.assets), "加载资产统计后显示。")}
        </section>

        {/* 记忆卫生建议 */}
        <section className="feature-window-panel maintenance-card" aria-label="记忆卫生建议">
          <div className="section-heading">
            <strong><Sparkles size={15} aria-hidden="true" /> 记忆卫生建议</strong>
            <span>过期或敏感的记忆会影响召回质量，可以在这里整理。</span>
          </div>
          <SectionStatus status={api.hygieneStatus} error={api.hygieneError} onRetry={() => void api.loadHygiene()} />
          {api.hygieneNotice ? <p className="llmwiki-inline-success" role="status">{api.hygieneNotice}</p> : null}
          {api.hygiene?.suggestions.length ? (
            <ul className="maintenance-item-list">
              {api.hygiene.suggestions.map((suggestion) => {
                const busy = api.hygieneActionIds.has(suggestion.id);
                return (
                  <li key={suggestion.id} className="maintenance-item">
                    <div className="maintenance-item-copy">
                      <strong>{suggestion.title}</strong>
                      <p>{suggestion.summary}</p>
                      <small>{hygieneTypeLabels[suggestion.type] || suggestion.type} · {riskLabel(suggestion.risk_tier)} · {suggestion.impact}</small>
                    </div>
                    <div className="maintenance-item-actions">
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => void handleHygieneAction(suggestion.id, suggestion.requires_confirmation, suggestion.action_label)}
                        disabled={busy}
                      >
                        {busy ? <Loader2 className="spin" size={14} /> : <Check size={14} />}
                        {suggestion.action_label}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : emptyHint(api.hygieneStatus === "loading", Boolean(api.hygiene?.suggestions.length), "当前没有需要整理的记忆。")}
        </section>

        {/* 每周记忆回顾 */}
        <section className="feature-window-panel maintenance-card" aria-label="每周记忆回顾">
          <div className="section-heading">
            <strong><CalendarClock size={15} aria-hidden="true" /> 每周记忆回顾</strong>
            <span>按周复核：保留、仅本周、标记完成或忘记。</span>
          </div>
          <SectionStatus status={api.reviewStatus} error={api.reviewError} onRetry={() => void api.loadReview()} />
          {api.reviewNotice ? <p className="llmwiki-inline-success" role="status">{api.reviewNotice}</p> : null}
          {api.review ? (
            <p className="maintenance-review-summary">
              本周 {api.review.window_days} 天：保留 {reviewSummary.kept} · 仅本周 {reviewSummary.temporary} · 忽略 {reviewSummary.ignored}
            </p>
          ) : null}
          {reviewItems.length ? (
            <ul className="maintenance-item-list">
              {reviewItems.map((item) => {
                const editing = editingReviewId === item.review_id;
                return (
                  <li key={item.review_id} className="maintenance-item">
                    <div className="maintenance-item-copy">
                      <strong>{readableSummary(item)}</strong>
                      <p>{readableMemoryKind(item)} · {readableLifecycle(item.lifecycle_status)} · 置信度 {Math.round(item.confidence * 100)}% · {item.evidence_count} 个证据</p>
                      <small>来源：{readableSource(item.source)}</small>
                      {editing ? (
                        <textarea
                          className="maintenance-edit-input"
                          value={editDraft}
                          aria-label="编辑后的记忆内容"
                          rows={4}
                          onChange={(event) => setEditDraft(event.target.value)}
                        />
                      ) : null}
                    </div>
                    <div className="maintenance-item-actions">
                      {editing ? (
                        <>
                          <button type="button" className="primary" onClick={() => void saveEdit(item)} disabled={!editDraft.trim() || api.reviewActionIds.size > 0}>
                            保存修改
                          </button>
                          <button type="button" className="secondary" onClick={cancelEdit} aria-label="取消编辑">
                            <X size={14} />取消
                          </button>
                        </>
                      ) : (
                        item.allowed_actions.map((action) => {
                          const key = `${item.target_type}:${item.target_id}:${action}`;
                          const busy = api.reviewActionIds.has(key);
                          const dangerous = action === "forget";
                          const actionClass = dangerous ? "danger" : action === "keep" ? "secondary is-positive" : "secondary";
                          return (
                            <button
                              key={action}
                              type="button"
                              className={actionClass}
                              onClick={() => (action === "edit" ? startEdit(item) : void api.applyReviewAction(item, action))}
                              disabled={busy}
                            >
                              {busy ? <Loader2 className="spin" size={14} /> : reviewActionIcon(action)}
                              {reviewActionLabels[action]}
                            </button>
                          );
                        })
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : emptyHint(api.reviewStatus === "loading", reviewItems.length > 0, "本周没有待复核的记忆。")}
        </section>

        {/* 伴侣记忆整合 */}
        <section className="feature-window-panel maintenance-card" aria-label="伴侣记忆整合">
          <div className="section-heading">
            <strong><Brain size={15} aria-hidden="true" /> 伴侣记忆整合</strong>
            <span>把聊天中的零散信息合并为结构化记忆。</span>
          </div>
          <div className="maintenance-consolidation-row">
            <button
              type="button"
              className="primary"
              onClick={() => void api.runConsolidation()}
              disabled={api.consolidationRunning}
            >
              {api.consolidationRunning ? <Loader2 className="spin" size={15} /> : <Brain size={15} />}
              {api.consolidationRunning ? "整合中…" : "运行一次整合"}
            </button>
            {api.consolidation ? (
              <span className="maintenance-consolidation-result" role="status">
                读取 {api.consolidation.source_count} 条 → 产出 {api.consolidation.output_count} 条，跳过 {api.consolidation.skipped_count} 条
                {api.consolidation.completed_at ? ` · ${formatDate(api.consolidation.completed_at, { fallback: "完成" })}` : ""}
              </span>
            ) : null}
          </div>
          {api.consolidationNotice ? (
            <p className={api.consolidationFailed ? "llmwiki-inline-error" : "llmwiki-inline-success"} role="status">
              {api.consolidationNotice}
            </p>
          ) : null}
          <p className="field-note">
            <AlertTriangle size={13} aria-hidden="true" /> 整合只在本机运行，产出会写入记忆图谱并留下可回滚的操作记录。
          </p>
        </section>
      </div>
    </section>
  );
}
