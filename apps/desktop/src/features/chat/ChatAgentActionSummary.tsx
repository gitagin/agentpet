import { Loader2, RotateCcw } from "lucide-react";
import type { AgentAction } from "../../types";
import {
  canRevertAgentAction,
  getAgentActionDisplayFields,
} from "../../services/agentActivity";

type ChatAgentActionSummaryProps = {
  actions: AgentAction[];
  revertingActionIds?: Set<string>;
  onRevertAgentAction?: (action: AgentAction) => void;
  onOpenMemory?: () => void;
};

function isPendingConfirmation(action: AgentAction): boolean {
  return action.decision === "ask" && action.status !== "completed" && action.status !== "reverted";
}

export function ChatAgentActionSummary({
  actions,
  revertingActionIds,
  onRevertAgentAction,
  onOpenMemory,
}: ChatAgentActionSummaryProps) {
  if (actions.length === 0) {
    return null;
  }

  const pendingCount = actions.filter(isPendingConfirmation).length;
  const failedCount = actions.filter((action) => action.status === "failed" || Boolean(action.error)).length;

  return (
    <section className="message-agent-actions" aria-label="本轮整理结果">
      <div className="message-agent-actions-head">
        <div>
          <strong>本轮整理结果</strong>
          <span>
            {failedCount > 0
              ? `${failedCount} 项失败，${actions.length - failedCount} 项已记录。`
              : pendingCount > 0
                ? `${pendingCount} 项需要确认，${actions.length - pendingCount} 项已记录。`
                : `${actions.length} 项自动整理已记录。`}
          </span>
        </div>
        {pendingCount > 0 && onOpenMemory ? (
          <button type="button" className="secondary" onClick={onOpenMemory}>
            去整理页
          </button>
        ) : null}
      </div>

      <div className="message-agent-action-list">
        {actions.map((action) => {
          const display = getAgentActionDisplayFields(action);
          const canRevert = canRevertAgentAction(action);
          const reverting = Boolean(revertingActionIds?.has(action.action_id));
          const pending = isPendingConfirmation(action);
          return (
            <article key={action.action_id} className={`message-agent-action ${pending ? "pending" : action.status}`}>
              <div>
                <strong>{display.actionName}</strong>
                <small>
                  {display.riskTierLabel} / {display.statusLabel}
                </small>
              </div>
              <p>{display.summary}</p>
              <small>目标文件：{display.targetPathLabel}</small>
              {action.error ? <small className="error">错误：{action.error}</small> : null}
              {pending ? <small className="error">需要确认后才会执行，请在整理页处理。</small> : null}
              {canRevert && onRevertAgentAction ? (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onRevertAgentAction(action)}
                  disabled={reverting}
                  title={`撤销 ${display.actionName}`}
                >
                  {reverting ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
                  撤销
                </button>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
