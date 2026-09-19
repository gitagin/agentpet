import type {
  ChatDailyHistoryMessage,
  ChatMessage,
  Citation,
  DiagnosticsExportResponse,
  MemorySearchResult,
} from "../types";
import type { LastIndexRun } from "../features/settings/settingsTypes";
import { firstUseOnboardingStorageKey } from "../features/onboarding/useFirstUseOnboarding";
import { petEntryHintStorageKey } from "../features/pet/usePetWindowController";
import { wikiArchiveCandidateStorageKey } from "../features/wiki/wikiConstants";
import { writeRendererUiState } from "../services/rendererUiState";
import { getPetInputModeOption, type PetInputMode } from "../features/chat/petInputModes";
import { normalizeAnswerBasis } from "../features/chat/answerBasis";

const FALLBACK_DAILY_HISTORY_TIME_ZONE = "Asia/Shanghai";

export function displayTextForInputMode(mode: PetInputMode, rawText: string): string {
  const text = rawText.trim();
  if (mode === "chat") {
    return text;
  }
  const label = getPetInputModeOption(mode).label;
  return text ? `${label}：${text}` : label;
}

export function resolveDailyHistoryTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK_DAILY_HISTORY_TIME_ZONE;
  } catch {
    return FALLBACK_DAILY_HISTORY_TIME_ZONE;
  }
}

export function chatMessageFromDailyHistory(message: ChatDailyHistoryMessage): ChatMessage | null {
  if (message.role !== "user" && message.role !== "assistant") {
    return null;
  }
  const status = ["partial", "completed", "failed", "cancelled"].includes(message.status)
    ? (message.status as ChatMessage["status"])
    : undefined;
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    status,
    agent_run_id: message.agent_run_id ?? undefined,
    answer_basis: message.role === "assistant" && status === "completed"
      ? normalizeAnswerBasis(message.answer_basis) : "not_assessed",
  };
}

export function readTtsPlaybackDurationMs(item: unknown): number | null {
  const record = item && typeof item === "object" ? (item as Record<string, unknown>) : null;
  const synthesis = record?.synthesis && typeof record.synthesis === "object"
    ? (record.synthesis as Record<string, unknown>)
    : null;
  const result = record?.result && typeof record.result === "object"
    ? (record.result as Record<string, unknown>)
    : null;

  for (const value of [record?.durationMs, synthesis?.durationMs, result?.durationMs]) {
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      return value;
    }
  }
  return null;
}

export function clearRendererResettableState(): void {
  for (const key of [
    "agent-pet.base-url",
    firstUseOnboardingStorageKey,
    petEntryHintStorageKey,
    wikiArchiveCandidateStorageKey,
  ]) {
    void writeRendererUiState(key, null);
  }
}

export function findCitationTargetId(citation: Citation, results: MemorySearchResult[]): string | undefined {
  const matched = results.find((result) =>
    citation.chunk_id
      ? result.chunk_id === citation.chunk_id
      : result.relative_path === citation.relative_path,
  );
  return matched ? `search-result-${matched.chunk_id}` : undefined;
}

export function formatIssueSeverity(severity: string): string {
  const labels: Record<string, string> = {
    error: "错误",
    warning: "警告",
    info: "提示",
  };
  return labels[severity] || severity;
}

export function getSearchEmptyNotice(
  query: string,
  lastIndexRun: LastIndexRun | null,
  diagnostics: DiagnosticsExportResponse | null,
): string {
  const recentCompletedIndex = diagnostics?.recent_index_jobs.find((job) =>
    ["completed", "done", "indexed", "success"].includes(job.status.toLowerCase()),
  );
  if (lastIndexRun || recentCompletedIndex) {
    return `没有找到“${query}”的结果。最近已有整理记录，请换一个关键词，或确认目标本地文件已在当前资料文件夹中。`;
  }
  return `没有找到“${query}”的结果。当前页面还没有整理完成记录，请先设置资料文件夹或点击“刷新”后再搜索。`;
}

export function scrollToWorkflowTarget(targetId?: string): void {
  if (targetId) {
    document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}
