import type { StreamHandlerInput } from "../streamDispatcher";
import { PET_BUBBLE_ERROR_HIDE_DELAY_MS } from "../chatTiming";

export function errorHandler({ messageId, sseEvent, payload, context }: StreamHandlerInput) {
  const { petChat, setMessages } = context;
  petChat.streamFailedRef.current = true;
  petChat.clearStreamWatchdogTimer();
  const errorMessage = `流式响应失败：${typeof payload?.message === "string" ? payload.message : sseEvent.data}`;
  petChat.showBubble({
    title: "回复失败",
    message: errorMessage,
    tone: "error",
  });
  petChat.scheduleHide(PET_BUBBLE_ERROR_HIDE_DELAY_MS);
  setMessages((current) =>
    current.map((chatMessage) =>
      chatMessage.id === messageId
        ? { ...chatMessage, status: "failed", content: chatMessage.content || errorMessage }
        : chatMessage,
    ),
  );
}
