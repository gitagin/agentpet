import type {
  ChatMessage,
  ChatWikiProposal,
  Citation,
  MemorySearchResult,
  WikiIngestApplyResponse,
  WikiIngestPreviewResponse,
  WikiPageResponse,
  WikiQueryArchiveDetailResponse,
  WikiQueryArchiveHistoryItem,
  WikiQueryArchiveResponse,
  WikiSynthesizeResponse,
} from "../../types";
import type { ChatWikiApplyResponse, WikiArchiveCandidate } from "./wikiTypes";

export function uniqueCompactList(values: Array<string | null | undefined>): string[] {
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

export function emptyToNull(value?: string | null): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

export function parseCompactList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function isCitation(value: unknown): value is MemorySearchResult {
  return Boolean(
    value &&
      typeof value === "object" &&
      "relative_path" in value &&
      typeof (value as { relative_path?: unknown }).relative_path === "string",
  );
}

function parseJson(value: string): unknown {
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

export function normalizeWikiArchiveCandidate(value: unknown): WikiArchiveCandidate | null {
  const parsed = typeof value === "string" ? parseJson(value) : value;
  if (!parsed || typeof parsed !== "object") {
    return null;
  }
  const candidate = parsed as Partial<WikiArchiveCandidate>;
  const message = candidate.message;
  if (
    !message ||
    message.role !== "assistant" ||
    message.status !== "completed" ||
    typeof message.content !== "string" ||
    !message.content.trim()
  ) {
    return null;
  }
  const citations = Array.isArray(message.citations) ? message.citations.filter(isCitation) : [];
  if (!citations.some(isKnowledgeBaseCitation)) {
    return null;
  }
  return {
    conversation_id: typeof candidate.conversation_id === "string" ? candidate.conversation_id : null,
    message: { ...message, citations },
    question: typeof candidate.question === "string" ? candidate.question : null,
    updated_at: typeof candidate.updated_at === "string" ? candidate.updated_at : new Date().toISOString(),
  };
}

export function clampWikiMaxPages(value: number | undefined): number {
  if (!Number.isFinite(value)) {
    return 15;
  }
  return Math.max(1, Math.min(15, Math.trunc(value || 15)));
}

export function isKnowledgeBaseCitation(citation: Citation): boolean {
  return citation.source_scope === "knowledge_base" || citation.relative_path.startsWith("Wiki/");
}

export function toMemorySearchResultCitation(citation: Citation): MemorySearchResult {
  const relativePath = citation.relative_path;
  const title = citation.title?.trim() || titleFromRelativePath(relativePath);
  const heading = citation.heading ?? null;
  const snippet = citation.snippet?.trim() || relativePath;
  const sourceScope =
    citation.source_scope === "knowledge_base" || relativePath.startsWith("Wiki/")
      ? "knowledge_base"
      : citation.source_scope || "knowledge_base";
  return {
    note_id: citation.note_id || relativePath,
    chunk_id: citation.chunk_id || `${relativePath}:${heading || ""}:${snippet.slice(0, 32)}`,
    relative_path: relativePath,
    title,
    heading,
    snippet,
    score: typeof citation.score === "number" ? citation.score : 1,
    source_scope: sourceScope,
    retrieval_mode: citation.retrieval_mode || "fts",
  };
}

export function findLatestArchivableAssistantMessage(messages: ChatMessage[]): ChatMessage | undefined {
  return [...messages]
    .reverse()
    .find(
      (message) =>
        message.role === "assistant" &&
        message.status === "completed" &&
        Boolean(message.content.trim()) &&
        Boolean(message.citations?.some(isKnowledgeBaseCitation)),
    );
}

export function findQuestionForAssistantMessage(messages: ChatMessage[], assistantMessageId: string): string | null {
  const assistantIndex = messages.findIndex((message) => message.id === assistantMessageId);
  if (assistantIndex <= 0) {
    return null;
  }
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "user" && message.content.trim()) {
      return message.content.trim();
    }
  }
  return null;
}

export function buildWikiArchiveTitle(citations: Citation[]): string {
  const first = citations[0];
  if (first?.title?.trim()) {
    return `查询归档 - ${first.title.trim()}`;
  }
  if (first?.heading?.trim()) {
    return `查询归档 - ${first.heading.trim()}`;
  }
  if (first?.relative_path) {
    return `查询归档 - ${first.relative_path.replace(/^Wiki\//, "").replace(/\.md$/i, "")}`;
  }
  return "查询归档";
}

export function getWikiArchiveId(archive: Pick<WikiQueryArchiveHistoryItem, "archive_id" | "id">): string {
  return archive.archive_id || archive.id || "";
}

export function formatCompactDateTime(value?: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatWikiArchiveHistoryMeta(
  archive: WikiQueryArchiveHistoryItem,
  formatTaskStatus: (status: string) => string,
): string {
  const id = getWikiArchiveId(archive);
  const pageStatus = archive.page?.status || archive.page_status;
  return uniqueCompactList([
    id ? `ID ${id.slice(0, 12)}` : null,
    archive.page?.relative_path || archive.target_path,
    `${archive.citation_count ?? 0} 条引用`,
    pageStatus ? formatTaskStatus(pageStatus) : null,
    formatCompactDateTime(archive.created_at),
  ]).join(" / ");
}

export function formatWikiArchiveDetail(detail: WikiQueryArchiveDetailResponse): string {
  const citations = detail.citations.map((citation, index) => {
    const heading = citation.heading ? ` # ${citation.heading}` : "";
    return `${index + 1}. ${citation.relative_path}${heading}`;
  });
  return [
    `归档：${getWikiArchiveId(detail) || detail.id}`,
    `问题：${detail.question}`,
    `标题：${detail.title}`,
    `目标：${detail.target_path}${detail.section ? ` / ${detail.section}` : ""}`,
    `标签：${detail.tags.length > 0 ? detail.tags.join(", ") : "无"}`,
    "",
    "回答：",
    detail.answer,
    "",
    "引用：",
    citations.length > 0 ? citations.join("\n") : "无",
  ].join("\n");
}

export function formatWikiWorkflowResult(
  result: WikiIngestApplyResponse | WikiQueryArchiveResponse | WikiSynthesizeResponse | null,
  formatTaskStatus: (status: string) => string,
): string {
  if (!result) {
    return "无";
  }
  if ("page_results" in result) {
    const core = uniqueCompactList([
      result.index_updated ? "索引已更新" : null,
      result.log_appended ? "日志已追加" : null,
      result.lint_summary && typeof result.lint_summary.issues === "number" ? `${result.lint_summary.issues} 个检查问题` : null,
    ]).join(" / ");
    return `${formatTaskStatus(result.status)} / ${result.pages_written}/${result.page_results.length} 页${core ? ` / ${core}` : ""}`;
  }
  if ("lint" in result) {
    return `${result.archive_id ? `${result.archive_id} / ` : ""}${result.page.relative_path} / ${formatTaskStatus(result.page.status)}`;
  }
  const core = uniqueCompactList([
    result.index_updated ? "索引已更新" : null,
    result.log_appended ? "日志已追加" : null,
  ]).join(" / ");
  return `${result.page.relative_path} / ${formatTaskStatus(result.page.status)}${core ? ` / ${core}` : ""}`;
}

export function formatWikiPreview(preview: WikiIngestPreviewResponse): string {
  const lines = [
    `运行：${preview.run_id}`,
    `来源：${preview.source_id}`,
    `哈希：${preview.source_hash}`,
    "",
    preview.summary,
    "",
    "计划页面：",
  ];
  preview.page_plans.forEach((plan, index) => {
    lines.push(`${index + 1}. ${plan.target_path} (${plan.operation}${plan.section ? ` / ${plan.section}` : ""})`);
  });
  return lines.join("\n");
}

export function titleFromRelativePath(relativePath: string): string {
  const filename = relativePath.split(/[\\/]/).pop() || relativePath;
  return filename.replace(/\.md$/i, "") || "资料页来源";
}

export function formatWikiDiagnosticKind(kind: string): string {
  const labels: Record<string, string> = {
    contradiction: "潜在冲突",
    stale_claim: "陈旧说法",
    missing_link: "缺失链接",
    missing_concept: "缺失概念页",
  };
  return labels[kind] || kind;
}

export function getWikiApplyIndexedPage(response: ChatWikiApplyResponse): WikiPageResponse | undefined {
  if ("page_results" in response) {
    return response.page_results.find((page) => page.index_job_id);
  }
  if ("page" in response && response.page.index_job_id) {
    return response.page;
  }
  if ("report_page" in response && response.report_page?.index_job_id) {
    return response.report_page;
  }
  return undefined;
}

export function getChatWikiApplyNoticeTone(response: ChatWikiApplyResponse): "info" | "error" | "success" {
  if ("status" in response) {
    return response.status === "applied" ? "success" : "info";
  }
  if ("summary" in response && "issues" in response) {
    return response.summary.errors ? "info" : "success";
  }
  return "success";
}

export function formatChatWikiApplyNotice(response: ChatWikiApplyResponse): string {
  if ("page_results" in response) {
    return `资料整理确认已写入：写入 ${response.pages_written}/${response.page_results.length} 个页面。`;
  }
  if ("lint" in response) {
    return `查询归档已写入：${response.page.relative_path}，引用 ${response.lint.normalized_citations.length} 条。`;
  }
  if ("page" in response) {
    return `资料库综合整理已写入：${response.page.relative_path}。`;
  }
  const issueCount = response.summary.issues ?? response.issues.length;
  return `资料库检查已完成：${issueCount} 个问题${response.report_page ? `，报告 ${response.report_page.relative_path}` : ""}。`;
}

export function formatChatWikiProposalResultPaths(result: ChatWikiProposal["apply_result"]): string {
  if (!result) {
    return "";
  }
  if ("page_results" in result) {
    return result.page_results.map((page) => page.relative_path).join(", ");
  }
  if ("page" in result) {
    return result.page.relative_path;
  }
  return result.report_page?.relative_path || "";
}
