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

export function AgentActionActivityCard({ entry, reverting, onRevert, onRevealTarget }: AgentActionActivityCardProps) {
  const action = entry.action;
  const display = getAgentActionDisplayFields(action);
  const attention = isAttentionAgentAction(action);
  const canRevert = canRevertAgentAction(action);
  const targetPaths = action.target_paths.filter((targetPath) => targetPath.toLowerCase().endsWith(".md"));
  const showAuditDetails = !isSkippedAction(action);
  const auditDetails = [
    action.title && action.title !== display.actionName ? `原始标题：${action.title}` : "",
    action.summary && action.summary !== display.summary ? `原始摘要：${action.summary}` : "",
    action.metadata?.skipped_reason ? `原始跳过原因：${String(action.metadata.skipped_reason)}` : "",
  ].filter(Boolean);

  return (
    <article className={`proposal agent-activity-item ${attention ? "pending" : "confirmed"}`}>
      <div className="continuity-proposal-head agent-action-head">
        <div>
          <strong>{display.actionName}</strong>
          <small>
            {display.actionTypeLabel} / {display.riskTierLabel} / {display.statusLabel}
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

      <p className="agent-action-summary">{display.summary}</p>

      <div className="agent-action-fields">
        <small>目标文件：{display.targetPathLabel}</small>
        <small>创建时间：{display.createdTimeLabel}</small>
        {action.diff_summary ? <small>差异：{action.diff_summary}</small> : null}
        {display.sourceLabel ? <small>来源：{display.sourceLabel}</small> : null}
      </div>

      {showAuditDetails && auditDetails.length > 0 ? (
        <details className="agent-action-audit-details">
          <summary>整理详情</summary>
          {auditDetails.map((detail) => (
            <small key={detail}>{detail}</small>
          ))}
        </details>
      ) : null}

      {action.error ? <p className="field-note error">{action.error}</p> : null}
      {action.reverted_by ? <p className="field-note success">已撤回，并生成新的活动记录：{action.reverted_by}。</p> : null}
      {action.reverts_action_id ? <p className="field-note success">这是撤回记录，来源活动：{action.reverts_action_id}。</p> : null}
      {!canRevert && action.reversible && action.status !== "reverted" ? (
        <p className="field-note">当前状态不可自动撤回。</p>
      ) : null}
      {action.decision === "ask" && action.status === "pending" ? (
        <p className="field-note error">该活动需要人工确认；请处理下方对应的高风险确认项。</p>
      ) : null}

      {onRevealTarget && targetPaths.length > 0 ? (
        <div className="agent-action-targets" aria-label="本机目标文件">
          {targetPaths.map((targetPath) => (
            <div key={targetPath} className="agent-action-target-row">
              <span>{targetPath}</span>
              <div className="button-row compact-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onRevealTarget(targetPath, "open")}
                  title={`打开 ${targetPath}`}
                >
                  <ExternalLink size={16} />
                  打开文件
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onRevealTarget(targetPath, "show")}
                  title={`在文件夹中显示 ${targetPath}`}
                >
                  <FolderSearch size={16} />
                  显示位置
                </button>
              </div>
            </div>
          ))}
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
            title={`撤回 ${display.actionName}`}
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
