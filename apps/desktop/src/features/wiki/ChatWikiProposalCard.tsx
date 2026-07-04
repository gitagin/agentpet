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
    <article
      key={proposal.id}
      id={`wiki-proposal-${message.id}-${proposal.id}`}
      className={`proposal wiki-chat-proposal ${proposal.state}`}
    >
      <div className="wiki-chat-proposal-head">
        <div>
          <strong>{proposal.title}</strong>
          <small>
            {formatChatWikiProposalType(proposal.proposal_type)} / {formatChatWikiProposalState(proposal.state)}
            {proposal.backend_status ? ` / 处理${formatTaskStatus(proposal.backend_status)}` : ""}
          </small>
        </div>
        <span>{proposal.selected_targets.length || targetOptions.length} 个目标</span>
      </div>
      {proposal.summary || proposal.review_summary ? <p>{proposal.review_summary || proposal.summary}</p> : null}
      <dl className="details wiki-chat-proposal-meta">
        <div>
          <dt>处理状态</dt>
          <dd>{proposal.review_status ? formatTaskStatus(proposal.review_status) : formatChatWikiProposalState(proposal.state)}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{proposal.source_hash || proposal.source_id ? "已识别本次来源" : "未知"}</dd>
        </div>
      </dl>
      <div className="wiki-chat-proposal-targets" aria-label="资料整理确认目标">
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
          title={canApply ? "将已选择目标写入本机资料页" : "需要先确认，并选择至少一个带必要校验信息的目标"}
        >
          {proposal.state === "applying" ? <Loader2 className="spin" size={16} /> : <FileDown size={16} />}
          确认写入
        </button>
      </div>
    </article>
  );
}

function formatChatWikiProposalType(type: string): string {
  const labels: Record<string, string> = {
    ingest: "资料整理",
    query_archive: "查询整理",
    synthesize: "综合整理",
    lint: "检查修复",
  };
  return labels[type] || "资料整理";
}
