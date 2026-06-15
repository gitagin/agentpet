import { extractSseText } from "../chatStreamUtils";
import type { StreamHandlerInput } from "../streamDispatcher";

export function doneHandler({ messageId, sseEvent, payload, context }: StreamHandlerInput) {
  const { petChat, setMessages } = context;
  const doneText = extractSseText(sseEvent, payload);
  if (doneText) {
    petChat.setAssistantReplyText(doneText);
  }
  const visibleReplyText = petChat.assistantReplyRef.current;
  if (!visibleReplyText.trim()) {
    petChat.failStream(messageId, "没有收到可显示回复", "AI 只返回了括号内的隐藏动作，没有可展示给用户的内容。");
    return;
  }
  petChat.replyStartedRef.current = true;
  setMessages((current) =>
    current.map((message) =>
      message.id === messageId
        ? {
            ...message,
            content: visibleReplyText,
            status: "completed",
          }
        : message,
    ),
  );
  petChat.startReplyPaging(messageId);
}
