import { extractSseText } from "../chatStreamUtils";
import type { StreamHandlerInput } from "../streamDispatcher";

export function doneHandler({ messageId, sseEvent, payload, context }: StreamHandlerInput) {
  const { petChat, setMessages } = context;
  const doneText = extractSseText(sseEvent, payload);
  if (!petChat.assistantReplyRef.current && !doneText) {
    petChat.failStream(messageId, "没有收到回复", "后端发送了完成事件，但没有附带可显示回复。");
    return;
  }
  if (!petChat.assistantReplyRef.current && doneText) {
    petChat.replyStartedRef.current = true;
    petChat.assistantReplyRef.current = doneText;
  }
  setMessages((current) =>
    current.map((message) =>
      message.id === messageId
        ? {
            ...message,
            content: message.content || doneText,
            status: "completed",
          }
        : message,
    ),
  );
  petChat.startReplyPaging();
}
