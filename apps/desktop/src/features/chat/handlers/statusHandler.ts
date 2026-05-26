import type { StreamHandlerInput } from "../streamDispatcher";

export function statusHandler({ messageId, payload, context }: StreamHandlerInput) {
  const { petChat, appendChatEvent } = context;
  const stageLabel = formatAgentStage(payload?.stage);
  const statusMessage = typeof payload?.message === "string" && payload.message ? payload.message : "智能体正在处理请求。";
  if (!petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: stageLabel || "智能体状态",
      message: statusMessage,
      tone: "thinking",
    });
    petChat.scheduleStreamWatchdog(
      "仍在等待回复",
      "后端还在处理，模型暂时没有返回第一段内容。",
      12000,
      () => petChat.failStream(messageId, "模型回复超时", "后端仍在处理，但模型长时间没有返回可显示内容。"),
    );
  }
  appendChatEvent(messageId, {
    label: stageLabel ? `智能体状态 · ${stageLabel}` : "智能体状态",
    detail: statusMessage,
    tone: "info",
  });
}

function formatAgentStage(stage: unknown): string | null {
  if (typeof stage !== "string" || !stage) {
    return null;
  }
  const labels: Record<string, string> = {
    route: "路由",
    semantic_analysis: "语义分析",
    personal_memory_retrieval: "翻记忆本",
    daily_chat_retrieval: "查聊天日记",
    daily_chat_fallback: "补查聊天日记",
    knowledge_base_retrieval: "查资料库",
    multi_source_retrieval: "查记忆和资料",
    chat_generation: "生成回复",
    background_memory: "后台保存记忆",
  };
  return labels[stage] || stage;
}
