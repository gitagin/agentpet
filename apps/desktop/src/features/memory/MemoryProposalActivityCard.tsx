import { Check, Loader2, X } from "lucide-react";
import type { AgentActivityLogEntry } from "../../services/agentActivity";
import { memoryTypeLabels } from "./memoryConstants";
import { formatDiffSummary, formatProposalStatus } from "./memoryUtils";

type MemoryProposalActivityCardProps = {
  entry: Extract<AgentActivityLogEntry, { kind: "memory_proposal" }>;
  busy: boolean;
  onAct: (proposalId: string, action: "confirm" | "reject") => void;
};

export function MemoryProposalActivityCard({ entry, busy, onAct }: MemoryProposalActivityCardProps) {
  const proposal = entry.proposal;
  return (
    <article
      key={entry.id}
      id={`memory-proposal-${proposal.proposal_id}`}
      className={`proposal memory-proposal ${proposal.status}`}
    >
      <div className="continuity-proposal-head">
        <div>
          <strong>等你确认 · {memoryTypeLabels[proposal.type]}</strong>
          <small>需要你决定是否留下 / {formatProposalStatus(proposal.status)}</small>
        </div>
        <span>{formatProposalStatus(proposal.status)}</span>
      </div>
      <p>{proposal.content || proposal.preview_markdown || "无预览内容"}</p>
      <small>保存位置：确认后写入本机记忆</small>
      {proposal.diff ? <small>变化：{formatDiffSummary(proposal.diff)}</small> : null}
      <div className="button-row">
        <button
          type="button"
          className="secondary"
          disabled={busy || proposal.status !== "pending"}
          onClick={() => onAct(proposal.proposal_id, "confirm")}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
          记住
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || proposal.status !== "pending"}
          onClick={() => onAct(proposal.proposal_id, "reject")}
        >
          <X size={16} />
          不用记
        </button>
      </div>
    </article>
  );
}
