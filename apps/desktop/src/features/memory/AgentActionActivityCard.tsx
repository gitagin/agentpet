import { ExternalLink, FolderSearch, Loader2, RotateCcw } from "lucide-react";
import type { AgentAction } from "../../types";
import {
  canRevertAgentAction,
  getAgentActionDisplayFields,
  isAttentionAgentAction,
  type AgentActivityLogEntry,
} from "../../services/agentActivity";

type AgentActionActivityCardProps = {
  entry: Extract<AgentActivityLogEntry, { kind: "agent_action" }>;
  reverting: boolean;
  onRevert: (action: AgentAction) => void;
  onRevealTarget?: (relativePath: string, mode: "open" | "show") => void;
};

function isSkippedAction(action: AgentAction): boolean {
  const actionType = action.action_type.toLocaleLowerCase();
  return action.status === "skipped" || actionType.endsWith(".skip") || actionType.includes(".skip.");
}

function safeActivityText(value: string | undefined | null, fallback: string): string {
  const text = value?.trim();
  if (!text) {
    return fallback;
  }
  const internalPattern =
    /receipt:used:[^\s]+|\b(agent_actions?|agent_run_id|memory_candidates?|lifecycle_status|related_memory_id|target_id|source_text|source_excerpt|fts|vector|sidecar|runtime|authorization|token|skipped|saveable|confirmation-only|automation_disabled)\b|candidate:|fact:|\b(?:candidate|fact)[_-][A-Za-z0-9][\w-]*\b|[A-Za-z]:[\\/]|\\\\/i;
  return internalPattern.test(text) ? fallback : text;
}

function safeTargetPathLabel(value: string | undefined | null): string {
  return safeActivityText(value, "目标文件细节已隐藏");
}

export function AgentActionActivityCard({ entry, reverting, onRevert, onRevealTarget }: AgentActionActivityCardProps) {
  const action = entry.action;
  const display = getAgentActionDisplayFields(action);
  const attention = isAttentionAgentAction(action);
  const canRevert = canRevertAgentAction(action);
  const targetPaths = action.target_paths.filter((targetPath) => targetPath.toLowerCase().endsWith(".md"));
  const showAuditDetails = !isSkippedAction(action);
  const auditDetails = [
    action.title && action.title !== display.actionName
      ? `原始标题：${safeActivityText(action.title, "标题细节已隐藏")}`
      : "",
    action.summary && action.summary !== display.summary
      ? `原始摘要：${safeActivityText(action.summary, "摘要细节已隐藏")}`
      : "",
    action.metadata?.skipped_reason
      ? `跳过原因：${safeActivityText(String(action.metadata.skipped_reason), "原因细节已隐藏")}`
      : "",
  ].filter(Boolean);
  const actionName = safeActivityText(display.actionName, "整理记录");
  const actionTypeLabel = safeActivityText(display.actionTypeLabel, "本地整理");
  const summary = safeActivityText(display.summary, "这条整理记录包含内部细节，已隐藏。");
  const diffSummary = safeActivityText(action.diff_summary, "差异细节已隐藏。");
  const sourceLabel = safeActivityText(display.sourceLabel, "来源已安全摘要");
  const errorMessage = safeActivityText(action.error, "这次整理没有完成，请稍后重试。");
  const targetPathLabel = safeTargetPathLabel(display.targetPathLabel);

  return (
    <article id={entry.id} className={`proposal agent-activity-item ${attention ? "pending" : "confirmed"}`}>
      <div className="continuity-proposal-head agent-action-head">
        <div>
          <strong>{actionName}</strong>
          <small>
            {actionTypeLabel} / {display.riskTierLabel} / {display.statusLabel}
          </small>
        </div>
        <span>{display.createdTimeLabel}</span>
      </div>

      <div className="agent-action-badges" aria-label="整理活动状态">
        <span>{display.riskTierLabel}</span>
        <span>{display.decisionLabel}</span>
        <span>{display.statusLabel}</span>
        <span>{display.reversibleLabel}</span>
      </div>

      <p className="agent-action-summary">{summary}</p>

      <div className="agent-action-fields">
        <small>目标文件：{targetPathLabel}</small>
        <small>创建时间：{display.createdTimeLabel}</small>
        {action.diff_summary ? <small>差异：{diffSummary}</small> : null}
        {display.sourceLabel ? <small>来源：{sourceLabel}</small> : null}
      </div>

      {showAuditDetails && auditDetails.length > 0 ? (
        <details className="agent-action-audit-details">
          <summary>整理详情</summary>
          {auditDetails.map((detail) => (
            <small key={detail}>{detail}</small>
          ))}
        </details>
      ) : null}

      {action.error ? <p className="field-note error">{errorMessage}</p> : null}
      {action.reverted_by ? <p className="field-note success">已撤回，并留下新的活动记录。</p> : null}
      {action.reverts_action_id ? <p className="field-note success">这是撤回记录，来源活动细节已隐藏。</p> : null}
      {!canRevert && action.reversible && action.status !== "reverted" ? (
        <p className="field-note">当前状态不可自动撤回。</p>
      ) : null}
      {action.decision === "ask" && action.status === "pending" ? (
        <p className="field-note error">该活动需要人工确认；请处理下方对应的高风险确认项。</p>
      ) : null}

      {onRevealTarget && targetPaths.length > 0 ? (
        <div className="agent-action-targets" aria-label="本机目标文件">
          {targetPaths.map((targetPath) => {
            const targetLabel = safeTargetPathLabel(targetPath);
            return (
              <div key={targetPath} className="agent-action-target-row">
                <span>{targetLabel}</span>
              <div className="button-row compact-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onRevealTarget(targetPath, "open")}
                  title={`打开 ${targetLabel}`}
                >
                  <ExternalLink size={16} />
                  打开文件
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onRevealTarget(targetPath, "show")}
                  title={`在文件夹中显示 ${targetLabel}`}
                >
                  <FolderSearch size={16} />
                  显示位置
                </button>
              </div>
            </div>
            );
          })}
        </div>
      ) : null}

      {canRevert ? (
        <>
          <p className="field-note">撤回前会再次确认；确认后会按本机快照恢复关联文件，并留下新的活动记录。</p>
        <div className="button-row compact-actions">
          <button
            type="button"
            className="secondary"
            onClick={() => onRevert(action)}
            disabled={reverting}
            title={`撤回 ${actionName}`}
          >
            {reverting ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
            撤回
          </button>
        </div>
        </>
      ) : null}
    </article>
  );
}
