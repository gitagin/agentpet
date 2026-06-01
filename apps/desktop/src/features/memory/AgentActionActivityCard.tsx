import { Loader2, RotateCcw } from "lucide-react";
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
};

export function AgentActionActivityCard({ entry, reverting, onRevert }: AgentActionActivityCardProps) {
  const action = entry.action;
  const display = getAgentActionDisplayFields(action);
  const attention = isAttentionAgentAction(action);
  const canRevert = canRevertAgentAction(action);

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

      {action.error ? <p className="field-note error">{action.error}</p> : null}
      {action.reverted_by ? <p className="field-note">已由 {action.reverted_by} 撤销。</p> : null}
      {action.reverts_action_id ? <p className="field-note">这是撤销记录，来源活动：{action.reverts_action_id}。</p> : null}
      {!canRevert && action.reversible && action.status !== "reverted" ? (
        <p className="field-note">当前状态不可自动撤销。</p>
      ) : null}
      {action.decision === "ask" && action.status === "pending" ? (
        <p className="field-note error">该活动需要人工确认；请处理下方对应的高风险确认项。</p>
      ) : null}

      {canRevert ? (
        <div className="button-row compact-actions">
          <button
            type="button"
            className="secondary"
            onClick={() => onRevert(action)}
            disabled={reverting}
            title={`撤销 ${display.actionName}`}
          >
            {reverting ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
            撤销
          </button>
        </div>
      ) : null}
    </article>
  );
}
