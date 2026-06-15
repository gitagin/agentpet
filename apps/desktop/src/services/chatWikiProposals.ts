import type { ChatWikiProposal, ChatWikiProposalState } from "../types";

export function isWikiProposalStreamEvent(eventName: string): boolean {
  const normalized = eventName.toLowerCase();
  return normalized.includes("wiki") && normalized.includes("proposal");
}

function pickPayloadString(payload: Record<string, unknown> | null, keys: string[]): string | null {
  if (!payload) {
    return null;
  }
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function uniqueCompactList(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  values.forEach((value) => {
    const trimmed = value?.trim();
    if (!trimmed || seen.has(trimmed)) {
      return;
    }
    seen.add(trimmed);
    normalized.push(trimmed);
  });
  return normalized;
}

function truncateEventDetail(value: string, maxLength = 360): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized;
}

function isSensitivePayloadKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return (
    normalized.includes("authorization") ||
    normalized.includes("token") ||
    normalized.includes("api_key") ||
    normalized.includes("password") ||
    normalized.includes("secret")
  );
}

function redactStreamPayload(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.slice(0, 5).map(redactStreamPayload);
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, entry]) => [
      key,
      isSensitivePayloadKey(key) ? "[redacted]" : redactStreamPayload(entry),
    ]),
  );
}

function formatStreamPayloadPreview(payload: Record<string, unknown> | null, rawData: string): string {
  if (payload) {
    try {
      return truncateEventDetail(JSON.stringify(redactStreamPayload(payload)));
    } catch {
      return "payload 无法序列化";
    }
  }
  return truncateEventDetail(rawData);
}

function formatWorkflowStatus(status: string): string {
  if (status === "reviewed") {
    return "已审查";
  }
  if (status === "model_not_configured") {
    return "模型未配置";
  }
  const labels: Record<string, string> = {
    pending: "待处理",
    done: "已完成",
    cancelled: "已取消",
    failed: "失败，需处理",
    scheduled: "已安排",
    unscheduled: "未安排",
    completed: "已完成",
    indexed: "已索引",
    bound: "已绑定",
  };
  return labels[status] || status;
}

export function formatWikiProposalEventDetail(
  eventName: string,
  payload: Record<string, unknown> | null,
  rawData: string,
): string {
  const summary = pickPayloadString(payload, ["summary", "message", "description"]);
  const proposalId = pickPayloadString(payload, ["proposal_id", "id", "run_id"]);
  const title = pickPayloadString(payload, ["title", "page_title"]);
  const target = pickPayloadString(payload, ["target_path", "relative_path", "path"]);
  const operation = pickPayloadString(payload, ["operation", "action"]);
  const status = pickPayloadString(payload, ["status"]);
  const pagePlanCount = Array.isArray(payload?.page_plans) ? payload.page_plans.length : null;
  const parts = [
    summary,
    title ? `标题 ${title}` : null,
    target ? `目标 ${target}` : null,
    operation ? `操作 ${operation}` : null,
    status ? `状态 ${formatWorkflowStatus(status)}` : null,
    proposalId ? `ID ${proposalId}` : null,
    pagePlanCount !== null ? `${pagePlanCount} 个页面计划` : null,
  ].filter(Boolean);

  if (parts.length > 0) {
    return truncateEventDetail(`${parts.join("；")}；需确认后才会写入本机知识页。`);
  }

  const payloadPreview = formatStreamPayloadPreview(payload, rawData);
  return payloadPreview
    ? `收到 ${eventName}：${payloadPreview}；需确认后才会写入本机知识页。`
    : `收到 ${eventName} 事件；需确认后才会写入本机知识页。`;
}

function pickPayloadStringArray(payload: Record<string, unknown> | null, key: string): string[] {
  const value = payload?.[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return uniqueCompactList(value.map((item) => (typeof item === "string" ? item : null)));
}

function normalizeWikiProposalFindings(value: unknown): ChatWikiProposal["findings"] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    .map((item) => ({
      severity: typeof item.severity === "string" ? item.severity : "info",
      code: typeof item.code === "string" && item.code.trim() ? item.code.trim() : "wiki_review_finding",
      message: typeof item.message === "string" ? item.message : "",
      target_path: typeof item.target_path === "string" ? item.target_path : null,
    }));
}

export function normalizeChatWikiProposal(payload: Record<string, unknown> | null): ChatWikiProposal | null {
  if (!payload) {
    return null;
  }
  const runId = pickPayloadString(payload, ["run_id"]);
  const reviewId = pickPayloadString(payload, ["review_id"]);
  const sourceId = pickPayloadString(payload, ["source_id"]);
  const sourceHash = pickPayloadString(payload, ["source_hash"]);
  const targetPaths = pickPayloadStringArray(payload, "target_paths");
  const recommendedTargets = pickPayloadStringArray(payload, "recommended_targets");
  const selectedTargets = recommendedTargets.length > 0 ? recommendedTargets : targetPaths;
  const proposalType = pickPayloadString(payload, ["proposal_type"]) || "ingest";
  const title = pickPayloadString(payload, ["title", "page_title"]) || "知识整理确认项";
  const id = reviewId || runId || sourceId || sourceHash || crypto.randomUUID();

  return {
    id,
    proposal_type: proposalType,
    state: "pending",
    backend_status: pickPayloadString(payload, ["status"]),
    title,
    run_id: runId,
    agent_run_id: pickPayloadString(payload, ["agent_run_id"]),
    source_id: sourceId,
    source_hash: sourceHash,
    review_id: reviewId,
    review_status: pickPayloadString(payload, ["review_status"]),
    summary: pickPayloadString(payload, ["summary"]) || "",
    review_summary: pickPayloadString(payload, ["review_summary"]) || "",
    target_paths: targetPaths,
    recommended_targets: recommendedTargets,
    selected_targets: selectedTargets,
    findings: normalizeWikiProposalFindings(payload.findings),
    markdown_preview: pickPayloadString(payload, ["markdown_preview"]) || "",
    source_message_id: pickPayloadString(payload, ["source_message_id"]),
    write_report: typeof payload.write_report === "boolean" ? payload.write_report : null,
    lint_summary:
      payload.lint_summary && typeof payload.lint_summary === "object" && !Array.isArray(payload.lint_summary)
        ? (payload.lint_summary as Record<string, unknown>)
        : undefined,
    error: null,
    apply_result: null,
    updated_at: new Date().toISOString(),
  };
}

export function mergeChatWikiProposal(
  existing: ChatWikiProposal | undefined,
  incoming: ChatWikiProposal,
): ChatWikiProposal {
  if (!existing) {
    return incoming;
  }
  return {
    ...existing,
    ...incoming,
    state: existing.state === "pending" ? incoming.state : existing.state,
    selected_targets: existing.selected_targets,
    error: existing.error,
    apply_result: existing.apply_result,
  };
}

export function getWikiProposalTargetOptions(proposal: ChatWikiProposal): string[] {
  return uniqueCompactList([
    ...proposal.recommended_targets,
    ...proposal.target_paths,
    ...proposal.selected_targets,
  ]);
}

export function isSupportedChatWikiProposalType(proposalType: string): proposalType is "ingest" | "query_archive" | "synthesize" | "lint" {
  return proposalType === "ingest" || proposalType === "query_archive" || proposalType === "synthesize" || proposalType === "lint";
}

export function formatChatWikiProposalState(state: ChatWikiProposalState): string {
  const labels: Record<ChatWikiProposalState, string> = {
    pending: "待确认",
    confirmed: "已确认",
    rejected: "已拒绝",
    applying: "正在应用",
    applied: "已应用",
    failed: "应用失败",
  };
  return labels[state] || state;
}
