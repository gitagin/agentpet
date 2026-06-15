import { FileText, Loader2, RotateCcw, ShieldAlert } from "lucide-react";
import type { VisibleContinuityReceipt } from "./visibleContinuityTypes";

type MemoryReceiptListProps = {
  receipts: VisibleContinuityReceipt[];
  revertingReceiptIds?: Set<string>;
  onRevertReceipt?: (receipt: VisibleContinuityReceipt) => void;
};

export function MemoryReceiptList({
  receipts,
  revertingReceiptIds = new Set(),
  onRevertReceipt,
}: MemoryReceiptListProps) {
  if (receipts.length === 0) {
    return (
      <section className="visible-continuity-section" aria-label="最近整理记录">
        <SectionTitle />
        <p className="visible-continuity-muted">暂时还没有自动整理记录。</p>
      </section>
    );
  }

  return (
    <section className="visible-continuity-section" aria-label="最近整理记录">
      <SectionTitle />
      <div className="visible-continuity-receipt-list">
        {receipts.map((receipt) => {
          const canRevert = canRevertReceipt(receipt);
          const reverting = revertingReceiptIds.has(receipt.action_id);
          return (
            <article key={receipt.action_id} className={`visible-continuity-receipt ${receipt.risk_tier}`}>
              <div className="visible-continuity-item-head">
                <strong>{formatReceiptTitle(receipt)}</strong>
                <span>{formatDecision(receipt.decision)}</span>
              </div>
              <dl className="visible-continuity-receipt-facts">
                <div>
                  <dt>发生了什么</dt>
                  <dd>{formatActionType(receipt.action_type)}</dd>
                </div>
                <div>
                  <dt>原因</dt>
                  <dd>{formatReceiptSummary(receipt)}</dd>
                </div>
                <div>
                  <dt>撤销</dt>
                  <dd>{formatUndoState(receipt)}</dd>
                </div>
              </dl>
              <div className="visible-continuity-badges">
                <span>{formatRisk(receipt.risk_tier)}</span>
                <span>{formatStatus(receipt.status)}</span>
                <span>{formatActionType(receipt.action_type)}</span>
              </div>
              {receipt.target_path ? (
                <small className="visible-continuity-path">
                  <FileText size={14} aria-hidden="true" />
                  {receipt.target_path}
                </small>
              ) : (
                <small className="visible-continuity-path muted">
                  <ShieldAlert size={14} aria-hidden="true" />
                  没有可展示的安全本地文件目标。
                </small>
              )}
              {receipt.decision === "ask" && receipt.status === "pending" ? (
                <p className="field-note error">
                  这条高风险整理项仍需要在记忆活动队列中确认。
                </p>
              ) : null}
              {receipt.reverted_by ? (
                <p className="field-note">
                  已由活动 {receipt.reverted_by} 撤销。
                </p>
              ) : null}
              {receipt.reverts_action_id ? (
                <p className="field-note">
                  这条记录是 {receipt.reverts_action_id} 的撤销记录。
                </p>
              ) : null}
              {canRevert && onRevertReceipt ? (
                <div className="button-row compact-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => onRevertReceipt(receipt)}
                    disabled={reverting}
                    title={`撤销 ${formatReceiptTitle(receipt)}`}
                  >
                    {reverting ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
                    撤销
                  </button>
                </div>
              ) : null}
              {!canRevert && receipt.reversible && !receipt.reverted_by && !receipt.reverts_action_id ? (
                <p className="field-note">
                  这条记录有回滚快照，但当前状态不能自动撤销。
                </p>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function SectionTitle() {
  return (
    <div className="visible-continuity-section-head compact">
      <RotateCcw size={18} aria-hidden="true" />
      <div>
        <h3>最近整理记录</h3>
        <p>桌宠自动整理、跳过或保存过的内容。</p>
      </div>
    </div>
  );
}

export function canRevertReceipt(receipt: VisibleContinuityReceipt): boolean {
  return (
    receipt.reversible &&
    receipt.status === "completed" &&
    !receipt.reverted_by &&
    !receipt.reverts_action_id
  );
}

function formatDecision(value: VisibleContinuityReceipt["decision"]): string {
  const labels: Record<VisibleContinuityReceipt["decision"], string> = {
    ask: "需要确认",
    auto: "自动执行",
    notify: "已通知",
  };
  return labels[value];
}

function formatActionType(value: string): string {
  const labels: Record<string, string> = {
    "agent_action.revert": "已恢复到之前的本地文件状态。",
    "chat.auto_memory.skip": "已跳过自动记忆整理。",
    "chat.daily_archive": "已把聊天保存到本地日记。",
    "diary.structured_memory": "已提取结构化日记记忆。",
    "memory.consolidation.safety_event": "已记录安全事件。",
    "memory.consolidation.skip": "已跳过慢记忆整理。",
    "memory.long_term.write": "已保存或更新长期记忆。",
    "memory.long_term.skip": "已跳过长期记忆。",
    "wiki.answer_summary.write": "已保存可复用的 Wiki 摘要。",
    "wiki.answer_summary.skip": "已跳过 Wiki 摘要。",
    "wiki.page.write": "已创建或更新知识页。",
  };
  return labels[value] || value;
}

export function formatReceiptTitle(receipt: VisibleContinuityReceipt): string {
  const normalized = receipt.title.trim().toLocaleLowerCase();
  if (normalized === "skipped sensitive memory") {
    return "已跳过敏感记忆";
  }
  if (normalized.startsWith("skipped automatic organization")) {
    return "已跳过自动整理";
  }
  if (normalized.startsWith("skipped long-term memory")) {
    return "已跳过长期记忆";
  }
  if (normalized.startsWith("skipped wiki summary")) {
    return "已跳过 Wiki 摘要";
  }
  if (normalized.startsWith("skipped slow memory consolidation")) {
    return "已跳过慢记忆整理";
  }
  if (normalized === "saved weekly summary") {
    return "已保存周摘要";
  }
  return receipt.title;
}

function formatReceiptSummary(receipt: VisibleContinuityReceipt): string {
  const normalized = receipt.summary.trim().toLocaleLowerCase();
  if (normalized === "blocked [redacted].") {
    return "已按安全策略拦截敏感内容。";
  }
  if (normalized.includes("organization are disabled")) {
    return "自动整理策略当前关闭，因此本轮没有写入本地资产。";
  }
  if (normalized.includes("confirmation-only")) {
    return "这次内容需要先确认，因此没有直接写入长期记忆。";
  }
  if (normalized.includes("sensitive")) {
    return "这次内容可能包含敏感信息，已按安全策略跳过写入。";
  }
  if (normalized.includes("too short") || normalized.includes("low-value")) {
    return "这次内容较短或临时性较强，没有形成值得长期保存的整理项。";
  }
  if (normalized.includes("not contain enough reusable knowledge") || normalized.includes("did not produce saveable")) {
    return "这次回复没有提炼出适合沉淀到知识库的可复用内容。";
  }
  return receipt.summary;
}

function formatRisk(value: VisibleContinuityReceipt["risk_tier"]): string {
  const labels: Record<VisibleContinuityReceipt["risk_tier"], string> = {
    high: "高风险",
    low: "低风险",
    medium: "中风险",
  };
  return labels[value];
}

function formatStatus(value: string): string {
  const labels: Record<string, string> = {
    completed: "已完成",
    failed: "失败",
    pending: "待处理",
    reverted: "已撤销",
    skipped: "已跳过",
  };
  return labels[value] || value;
}

function formatUndoState(receipt: VisibleContinuityReceipt): string {
  if (receipt.reverted_by) {
    return "已撤销。";
  }
  if (receipt.reverts_action_id) {
    return "撤销记录。";
  }
  if (canRevertReceipt(receipt)) {
    return "可在这里撤销。";
  }
  if (receipt.reversible) {
    return "已有回滚快照，但当前状态暂时不能撤销。";
  }
  if (receipt.risk_tier === "high" || receipt.decision === "ask") {
    return "仅支持手动确认路径。";
  }
  return "不能自动撤销。";
}
