import type { MemoryProposal, MemoryProposalListItem, MemoryProposalType } from "../../types";
import { defaultMemoryTargetPath, memoryTypes } from "./memoryConstants";

export function isMemoryProposalType(value: unknown): value is MemoryProposalType {
  return typeof value === "string" && memoryTypes.includes(value as MemoryProposalType);
}

export function formatProposalStatus(status: MemoryProposal["status"]): string {
  const labels: Record<MemoryProposal["status"], string> = {
    pending: "待确认",
    confirmed: "已确认",
    rejected: "已拒绝",
    failed: "失败，未写入",
  };
  return labels[status] || status;
}

export function formatDiffSummary(diff?: string | null): string {
  if (!diff) {
    return "无";
  }
  const added = (diff.match(/^\+/gm) || []).length;
  const removed = (diff.match(/^-/gm) || []).length;
  return `+${added} / -${removed}`;
}

export function normalizeMemoryProposalListItem(proposal: MemoryProposalListItem): MemoryProposal {
  return {
    ...proposal,
    type: isMemoryProposalType(proposal.type) ? proposal.type : "fact",
    content: proposal.content || proposal.preview_markdown || "",
    target_path: proposal.target_path || defaultMemoryTargetPath,
    status: proposal.status || "pending",
  };
}

export function normalizeMemoryProposalPayload(proposalId: string, payload: Record<string, unknown> | null): MemoryProposal {
  return {
    proposal_id: proposalId,
    status: typeof payload?.status === "string" ? (payload.status as MemoryProposal["status"]) : "pending",
    type: isMemoryProposalType(payload?.type) ? payload.type : "fact",
    content:
      typeof payload?.content === "string"
        ? payload.content
        : typeof payload?.preview_markdown === "string"
          ? payload.preview_markdown
          : "",
    target_path: typeof payload?.target_path === "string" ? payload.target_path : defaultMemoryTargetPath,
    preview_markdown: typeof payload?.preview_markdown === "string" ? payload.preview_markdown : undefined,
    diff: typeof payload?.diff === "string" ? payload.diff : undefined,
    target_content_hash: typeof payload?.target_content_hash === "string" ? payload.target_content_hash : null,
  };
}
