import type { StreamHandlerInput } from "../streamDispatcher";

export function statusHandler({ messageId, payload, context }: StreamHandlerInput) {
  const { petChat } = context;
  const stage = typeof payload?.stage === "string" ? payload.stage : null;
  const sourceScopes = normalizeSourceScopes(payload?.source_scopes);
  if (!petChat.replyStartedRef.current) {
    petChat.scheduleStreamWatchdog(
      "正在整理",
      "我在查资料，马上回来。",
      14000,
      () => petChat.failStream(messageId, "没有等到回复", "这次没有等到可显示的回复，本轮已停止。"),
    );
  }
  if (isRetrievalStage(stage)) {
    context.setMessages((current) =>
      current.map((message) =>
        message.id === messageId
          ? {
              ...message,
              retrieval_attempted: true,
              retrieval_scopes: mergeScopes(message.retrieval_scopes, sourceScopes.length ? sourceScopes : scopesForStage(stage)),
            }
          : message,
      ),
    );
  }
}

function isRetrievalStage(stage: string | null): boolean {
  return (
    stage === "personal_memory_retrieval" ||
    stage === "diary_object_retrieval" ||
    stage === "daily_chat_retrieval" ||
    stage === "daily_chat_fallback" ||
    stage === "knowledge_base_retrieval" ||
    stage === "multi_source_retrieval" ||
    stage === "multi_source_memory_retrieval"
  );
}

function normalizeSourceScopes(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function mergeScopes(current: string[] | undefined, next: string[]): string[] {
  return Array.from(new Set([...(current || []), ...next]));
}

function scopesForStage(stage: string | null): string[] {
  const scopes: Record<string, string[]> = {
    personal_memory_retrieval: ["personal_memory"],
    diary_object_retrieval: ["diary_objects"],
    daily_chat_retrieval: ["daily_chat"],
    daily_chat_fallback: ["daily_chat"],
    knowledge_base_retrieval: ["knowledge_base"],
    multi_source_retrieval: ["personal_memory", "daily_chat", "knowledge_base"],
    multi_source_memory_retrieval: ["personal_memory", "diary_objects", "daily_chat"],
  };
  return stage ? scopes[stage] || [] : [];
}
