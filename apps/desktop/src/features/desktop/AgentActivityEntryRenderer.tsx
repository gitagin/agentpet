import { Check, Loader2, X } from "lucide-react";
import type { AgentAction, DesktopVaultRevealMode } from "../../types";
import type { AgentActivityLogEntry } from "../../services/agentActivity";
import { AgentActionActivityCard } from "../memory/AgentActionActivityCard";
import { MemoryProposalActivityCard } from "../memory/MemoryProposalActivityCard";
import { ChatWikiProposalCard } from "../wiki/ChatWikiProposalCard";
import {
  formatConfidence,
  formatContinuityKind,
  formatContinuityStatus,
} from "../continuity/continuityFormatters";

type AgentActivityEntryRendererProps = {
  entry: AgentActivityLogEntry;
  revertingAgentActionIds: Set<string>;
  memoryProposalActionIds: Set<string>;
  continuityActionIds: Set<string>;
  formatIssueSeverity: (severity: string) => string;
  onRevertAgentAction: (action: AgentAction) => void;
  onRevealAgentActionTarget: (relativePath: string, mode: DesktopVaultRevealMode) => void;
  onActOnMemoryProposal: (proposalId: string, action: "confirm" | "reject") => void;
  onActOnContinuityProposal: (proposalId: string, action: "confirm" | "reject") => void;
  onConfirmChatWikiProposal: (messageId: string, proposalId: string) => void;
  onRejectChatWikiProposal: (messageId: string, proposalId: string) => void;
  onToggleChatWikiProposalTarget: (
    messageId: string,
    proposalId: string,
    targetPath: string,
    selected: boolean,
  ) => void;
  onApplyChatWikiProposal: (messageId: string, proposalId: string) => void;
};

export function AgentActivityEntryRenderer({
  entry,
  revertingAgentActionIds,
  memoryProposalActionIds,
  continuityActionIds,
  formatIssueSeverity,
  onRevertAgentAction,
  onRevealAgentActionTarget,
  onActOnMemoryProposal,
  onActOnContinuityProposal,
  onConfirmChatWikiProposal,
  onRejectChatWikiProposal,
  onToggleChatWikiProposalTarget,
  onApplyChatWikiProposal,
}: AgentActivityEntryRendererProps) {
  if (entry.kind === "agent_action") {
    return (
      <AgentActionActivityCard
        entry={entry}
        reverting={revertingAgentActionIds.has(entry.action.action_id)}
        onRevert={onRevertAgentAction}
        onRevealTarget={onRevealAgentActionTarget}
      />
    );
  }

  if (entry.kind === "memory_proposal") {
    return (
      <MemoryProposalActivityCard
        entry={entry}
        busy={memoryProposalActionIds.has(entry.proposal.proposal_id)}
        onAct={onActOnMemoryProposal}
      />
    );
  }

  if (entry.kind === "continuity_proposal") {
    return (
      <ContinuityProposalActivityCard
        entry={entry}
        busy={continuityActionIds.has(entry.proposal.proposal_id)}
        onAct={onActOnContinuityProposal}
      />
    );
  }

  return (
    <ChatWikiProposalCard
      message={entry.message}
      proposal={entry.proposal}
      formatIssueSeverity={formatIssueSeverity}
      onConfirm={onConfirmChatWikiProposal}
      onReject={onRejectChatWikiProposal}
      onToggleTarget={onToggleChatWikiProposalTarget}
      onApply={onApplyChatWikiProposal}
    />
  );
}

type ContinuityProposalActivityCardProps = {
  entry: Extract<AgentActivityLogEntry, { kind: "continuity_proposal" }>;
  busy: boolean;
  onAct: (proposalId: string, action: "confirm" | "reject") => void;
};

function ContinuityProposalActivityCard({ entry, busy, onAct }: ContinuityProposalActivityCardProps) {
  const proposal = entry.proposal;
  const isOpenThread = proposal.kind === "open_thread";

  return (
    <article
      id={`continuity-proposal-${proposal.proposal_id}`}
      className={`proposal continuity-proposal ${proposal.status}`}
    >
      <div className="continuity-proposal-head">
        <div>
          <strong>{isOpenThread ? "下次接着聊" : `陪伴状态确认 · ${formatContinuityKind(proposal.kind)}`}</strong>
          <small>
            {isOpenThread ? "让桌宠记住这个话题，下次可以自然接上。" : "确认后用于之后的陪伴表现。"}
            {" / "}
            {formatContinuityStatus(proposal.status)}
            {" / "}
            置信度 {formatConfidence(proposal.confidence)}
          </small>
        </div>
        <span>{formatContinuityStatus(proposal.status)}</span>
      </div>
      <p>{isOpenThread ? `要让我下次记得继续这个话题吗？${proposal.summary}` : proposal.summary}</p>
      <small>{isOpenThread ? "为什么会出现：" : "证据："}{proposal.evidence}</small>
      <small>来源：本次聊天</small>
      <div className="button-row">
        <button
          type="button"
          className="secondary"
          disabled={busy || proposal.status !== "pending"}
          onClick={() => onAct(proposal.proposal_id, "confirm")}
        >
          {busy ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
          {isOpenThread ? "记住下次聊" : "确认使用"}
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || proposal.status !== "pending"}
          onClick={() => onAct(proposal.proposal_id, "reject")}
        >
          <X size={16} />
          {isOpenThread ? "不用记" : "不使用"}
        </button>
      </div>
    </article>
  );
}
