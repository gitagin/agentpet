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
          <strong>长期记忆确认 · {memoryTypeLabels[proposal.type]}</strong>
          <small>高风险确认 / {formatProposalStatus(proposal.status)}</small>
        </div>
        <span>{proposal.proposal_id}</span>
      </div>
      <p>{proposal.content || proposal.preview_markdown || "无预览内容"}</p>
      <small>目标：{proposal.target_path}</small>
      {proposal.diff ? <small>差异：{formatDiffSummary(proposal.diff)}</small> : null}
      <div className="button-row">
        <button
          type="button"
          className="secondary"
          disabled={busy || proposal.status !== "pending"}
          onClick={() => onAct(proposal.proposal_id, "confirm")}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
          确认
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || proposal.status !== "pending"}
          onClick={() => onAct(proposal.proposal_id, "reject")}
        >
          <X size={16} />
          拒绝
        </button>
      </div>
    </article>
  );
}
