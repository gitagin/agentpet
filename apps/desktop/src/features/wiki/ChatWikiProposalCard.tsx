import { Check, FileDown, Loader2, X } from "lucide-react";
import type { ChatMessage, ChatWikiProposal } from "../../types";
import {
  formatChatWikiProposalState,
  getWikiProposalTargetOptions,
  isSupportedChatWikiProposalType,
} from "../../services/chatWikiProposals";
import { formatTaskStatus } from "../tasks/taskReducer";
import { formatChatWikiProposalResultPaths } from "./wikiUtils";

type ChatWikiProposalCardProps = {
  message: ChatMessage;
  proposal: ChatWikiProposal;
  formatIssueSeverity: (severity: string) => string;
  onConfirm: (messageId: string, proposalId: string) => void;
  onReject: (messageId: string, proposalId: string) => void;
  onToggleTarget: (messageId: string, proposalId: string, targetPath: string, selected: boolean) => void;
  onApply: (messageId: string, proposalId: string) => void;
};

export function ChatWikiProposalCard({
  message,
  proposal,
  formatIssueSeverity,
  onConfirm,
  onReject,
  onToggleTarget,
  onApply,
}: ChatWikiProposalCardProps) {
  const targetOptions = getWikiProposalTargetOptions(proposal);
  const selectedTargets = new Set(proposal.selected_targets);
  const canEditTargets = proposal.state === "pending" || proposal.state === "confirmed" || proposal.state === "failed";
  const canConfirm = proposal.state === "pending";
  const canReject = proposal.state !== "rejected" && proposal.state !== "applied" && proposal.state !== "applying";
  const canApply =
    isSupportedChatWikiProposalType(proposal.proposal_type) &&
    (proposal.state === "confirmed" || proposal.state === "failed") &&
    (proposal.proposal_type !== "ingest" || (Boolean(proposal.run_id && proposal.review_id) && proposal.selected_targets.length > 0));
  const resultPaths = formatChatWikiProposalResultPaths(proposal.apply_result);

  return (
    <article key={proposal.id} className={`proposal wiki-chat-proposal ${proposal.state}`}>
      <div className="wiki-chat-proposal-head">
        <div>
          <strong>{proposal.title}</strong>
          <small>
            {proposal.proposal_type} / {formatChatWikiProposalState(proposal.state)}
            {proposal.backend_status ? ` / 后端 ${formatTaskStatus(proposal.backend_status)}` : ""}
          </small>
        </div>
        <span>{proposal.review_id || proposal.run_id || proposal.id}</span>
      </div>
      {proposal.summary || proposal.review_summary ? <p>{proposal.review_summary || proposal.summary}</p> : null}
      <dl className="details wiki-chat-proposal-meta">
        <div>
          <dt>run_id</dt>
          <dd>{proposal.run_id || "无"}</dd>
        </div>
        <div>
          <dt>review_id</dt>
          <dd>{proposal.review_id || "无"}</dd>
        </div>
        <div>
          <dt>审查</dt>
          <dd>{proposal.review_status ? formatTaskStatus(proposal.review_status) : "未知"}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{proposal.source_hash ? proposal.source_hash.slice(0, 12) : proposal.source_id || "未知"}</dd>
        </div>
      </dl>
      <div className="wiki-chat-proposal-targets" aria-label="Wiki proposal targets">
        <strong>目标页面</strong>
        {targetOptions.length > 0 ? (
          targetOptions.map((targetPath) => (
            <label key={`${proposal.id}-${targetPath}`} className="wiki-chat-proposal-target">
              <input
                type="checkbox"
                checked={selectedTargets.has(targetPath)}
                disabled={!canEditTargets}
                onChange={(event) => onToggleTarget(message.id, proposal.id, targetPath, event.target.checked)}
              />
              <span>{targetPath}</span>
            </label>
          ))
        ) : (
          <span>该确认项没有包含目标页面。</span>
        )}
      </div>
      {proposal.findings.length > 0 ? (
        <div className="message-events">
          {proposal.findings.slice(0, 4).map((finding, index) => (
            <span
              key={`${proposal.id}-${finding.code}-${finding.target_path || index}`}
              className={finding.severity === "error" ? "error" : undefined}
            >
              <strong>{formatIssueSeverity(finding.severity)} / {finding.code}</strong>
              {finding.target_path ? `${finding.target_path}: ` : ""}
              {finding.message}
            </span>
          ))}
        </div>
      ) : null}
      {proposal.markdown_preview ? <pre className="diff-preview">{proposal.markdown_preview}</pre> : null}
      {proposal.error ? <p className="field-note error">{proposal.error}</p> : null}
      {resultPaths ? <p className="field-note">已应用页面：{resultPaths}</p> : null}
      <div className="button-row">
        <button type="button" className="secondary" onClick={() => onConfirm(message.id, proposal.id)} disabled={!canConfirm}>
          <Check size={16} />
          确认
        </button>
        <button type="button" className="secondary" onClick={() => onReject(message.id, proposal.id)} disabled={!canReject}>
          <X size={16} />
          拒绝
        </button>
        <button
          type="button"
          onClick={() => onApply(message.id, proposal.id)}
          disabled={!canApply}
          title={canApply ? "将已选择目标写入 Vault" : "需要先确认，并选择至少一个带 run_id 与 review_id 的目标"}
        >
          {proposal.state === "applying" ? <Loader2 className="spin" size={16} /> : <FileDown size={16} />}
          确认写入
        </button>
      </div>
    </article>
  );
}
