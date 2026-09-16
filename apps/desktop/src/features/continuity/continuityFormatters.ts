import type {
  ChatContinuitySignal,
  ContinuityProposal,
  ContinuityProposalKind,
  ContinuityProposalStatus,
} from "../../types";
import { pickPayloadString } from "../chat/chatStreamUtils";

export function normalizeContinuityProposal(payload: Record<string, unknown> | null): ContinuityProposal | null {
  if (!payload) {
    return null;
  }
  const proposalId = pickPayloadString(payload, ["proposal_id", "id"]);
  const kind = pickPayloadString(payload, ["kind"]);
  const summary = pickPayloadString(payload, ["summary"]);
  const evidence = pickPayloadString(payload, ["evidence"]) || "";
  if (!proposalId || !isContinuityKind(kind) || !summary) {
    return null;
  }
  const confidence =
    typeof payload.confidence === "number"
      ? payload.confidence
      : Number.parseFloat(String(payload.confidence ?? "0"));
  const now = new Date().toISOString();
  return {
    proposal_id: proposalId,
    kind,
    summary,
    evidence,
    confidence: Number.isFinite(confidence) ? confidence : 0,
    source_conversation_id: pickPayloadString(payload, ["source_conversation_id"]),
    source_message_id: pickPayloadString(payload, ["source_message_id"]),
    agent_run_id: pickPayloadString(payload, ["agent_run_id"]),
    status: (pickPayloadString(payload, ["status"]) as ContinuityProposalStatus | null) || "pending",
    rejected_reason: pickPayloadString(payload, ["rejected_reason"]),
    created_at: pickPayloadString(payload, ["created_at"]) || now,
    updated_at: pickPayloadString(payload, ["updated_at"]) || now,
  };
}

export function normalizeContinuitySignal(payload: Record<string, unknown> | null): ChatContinuitySignal | null {
  if (!payload) {
    return null;
  }
  const kind = pickPayloadString(payload, ["kind"]) || "relationship";
  const rawTitle = pickPayloadString(payload, ["title"]);
  const title = kind === "open_thread" ? "下次接着聊" : rawTitle || "陪伴状态已更新";
  const summary = pickPayloadString(payload, ["summary"]);
  if (!summary) {
    return null;
  }
  const intensity = pickPayloadString(payload, ["intensity"]) || "medium";
  const displayHint =
    kind === "open_thread"
      ? "只在本机作为下次接着聊的提示；不会写入本地文件。"
      : pickPayloadString(payload, ["display_hint"]) || "只作为本机陪伴提示；不会写入本地文件。";
  const keys = Array.isArray(payload.source_state_keys)
    ? payload.source_state_keys.filter((value): value is string => typeof value === "string")
    : [];
  return {
    kind,
    title,
    summary,
    intensity,
    display_hint: displayHint,
    source_state_keys: keys,
    source_proposal_id: pickPayloadString(payload, ["source_proposal_id"]),
  };
}

export function formatContinuityKind(kind: ContinuityProposalKind | string): string {
  const labels: Record<ContinuityProposalKind, string> = {
    identity: "身份线索",
    relationship: "关系理解",
    mood: "情绪状态",
    energy: "能量水平",
    open_thread: "下次接着聊",
  };
  return isContinuityKind(kind) ? labels[kind] : kind;
}

export function formatContinuityStatus(status: ContinuityProposalStatus): string {
  const labels: Record<string, string> = {
    pending: "待确认",
    confirmed: "已确认",
    rejected: "已拒绝",
  };
  return labels[status] || status;
}

export function formatConfidence(confidence: number): string {
  if (!Number.isFinite(confidence)) {
    return "未知";
  }
  return `${Math.round(confidence * 100)}%`;
}

function isContinuityKind(value: unknown): value is ContinuityProposalKind {
  return (
    value === "identity" ||
    value === "relationship" ||
    value === "mood" ||
    value === "energy" ||
    value === "open_thread"
  );
}
