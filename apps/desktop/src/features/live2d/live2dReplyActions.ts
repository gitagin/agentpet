import type { ChatMessage } from "../../types";

export type Live2DReplyActionKey =
  | "chat_talk"
  | "chat_done"
  | "memory_found"
  | "memory_not_found"
  | "memory_save_diary"
  | "memory_confirm_needed"
  | "wiki_organize"
  | "wiki_archive"
  | "task_create"
  | "continuity_remember"
  | "emotion_comfort"
  | "system_error"
  | "celebrate_small";

const minPartialReplyCharacters = 12;

const systemErrorPatterns = [
  "error",
  "failed",
  "failure",
  "exception",
  "\u9519\u8bef",
  "\u51fa\u9519",
  "\u5931\u8d25",
  "\u5f02\u5e38",
  "\u65e0\u6cd5\u8fde\u63a5",
  "\u62b1\u6b49",
  "\u5bf9\u4e0d\u8d77",
];

const noResultPatterns = [
  "\u6ca1\u6709\u627e\u5230",
  "\u6ca1\u627e\u5230",
  "\u6ca1\u67e5\u5230",
  "\u672a\u627e\u5230",
  "\u627e\u4e0d\u5230",
  "\u6682\u65f6\u6ca1\u6709",
  "\u6ca1\u6709\u76f8\u5173",
];

const confirmPatterns = [
  "\u9700\u8981\u786e\u8ba4",
  "\u8bf7\u786e\u8ba4",
  "\u5f85\u786e\u8ba4",
  "\u8981\u4e0d\u8981",
  "\u662f\u5426\u8981",
  "\u8981\u6211",
];

const taskPatterns = [
  "todo",
  "deadline",
  "\u4efb\u52a1",
  "\u5f85\u529e",
  "\u63d0\u9192",
  "\u65e5\u7a0b",
  "\u5df2\u5b89\u6392",
  "\u5e2e\u4f60\u8bb0\u4e00\u4e0b",
];

const memoryPatterns = [
  "\u8bb0\u4f4f",
  "\u8bb0\u5fc6",
  "\u65e5\u8bb0",
  "\u5df2\u4fdd\u5b58",
  "\u4fdd\u5b58\u5230",
  "\u6c89\u6dc0",
  "\u957f\u671f\u8bb0\u5fc6",
];

const wikiPatterns = [
  "wiki",
  "\u77e5\u8bc6",
  "\u8d44\u6599",
  "\u6587\u6863",
  "\u6761\u76ee",
  "\u5f52\u6863",
  "\u6574\u7406\u6210",
];

const comfortPatterns = [
  "\u522b\u62c5\u5fc3",
  "\u6ca1\u5173\u7cfb",
  "\u6162\u6162\u6765",
  "\u6211\u5728",
  "\u966a\u4f60",
  "\u8f9b\u82e6\u4e86",
  "\u96be\u8fc7",
  "\u7126\u8651",
  "\u5bb3\u6015",
  "\u4e0d\u7528\u6025",
];

const celebratePatterns = [
  "\u592a\u597d\u4e86",
  "\u5b8c\u6210",
  "\u6210\u529f",
  "\u641e\u5b9a",
  "\u505a\u5f97\u4e0d\u9519",
  "\u606d\u559c",
  "\u5df2\u7ecf\u597d\u4e86",
];

export function resolveLive2DReplyActionKey(message?: ChatMessage | null): Live2DReplyActionKey | null {
  if (!message || message.role !== "assistant") {
    return null;
  }

  if (message.status === "failed" || message.status === "cancelled") {
    return "system_error";
  }

  if ((message.task_actions || []).length > 0) {
    return "task_create";
  }
  if ((message.memory_proposals || []).length > 0) {
    return "memory_confirm_needed";
  }
  if ((message.wiki_proposals || []).length > 0) {
    return "wiki_organize";
  }
  if (message.continuity_signal) {
    return "continuity_remember";
  }

  const text = normalizeReplyText(message.content);
  if (!text) {
    return null;
  }
  if (message.status === "partial" && text.length < minPartialReplyCharacters) {
    return null;
  }

  if (includesAny(text, noResultPatterns)) {
    return "memory_not_found";
  }
  if (includesAny(text, systemErrorPatterns)) {
    return "system_error";
  }
  if (includesAny(text, confirmPatterns)) {
    return "memory_confirm_needed";
  }
  if (includesAny(text, taskPatterns)) {
    return "task_create";
  }
  if (includesAny(text, wikiPatterns)) {
    return text.includes("\u5f52\u6863") ? "wiki_archive" : "wiki_organize";
  }
  if (includesAny(text, memoryPatterns)) {
    return "memory_save_diary";
  }
  if (includesAny(text, comfortPatterns)) {
    return "emotion_comfort";
  }
  if (includesAny(text, celebratePatterns)) {
    return "celebrate_small";
  }
  if ((message.citations || []).length > 0 || (message.events || []).length > 0) {
    return "memory_found";
  }
  return message.status === "completed" ? "chat_done" : "chat_talk";
}

function normalizeReplyText(text: string): string {
  return text.trim().toLowerCase();
}

function includesAny(text: string, patterns: string[]): boolean {
  return patterns.some((pattern) => text.includes(pattern));
}
