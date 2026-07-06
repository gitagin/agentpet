import { extractSseText } from "../chatStreamUtils";
import type { StreamHandlerInput } from "../streamDispatcher";

export function doneHandler({ messageId, sseEvent, payload, context }: StreamHandlerInput) {
  const { petChat, setMessages } = context;
  const doneText = extractSseText(sseEvent, payload);
  const currentVisibleReplyText = petChat.assistantReplyRef.current;
  if (doneText && (sseEvent.event !== "done" || !currentVisibleReplyText.trim())) {
    petChat.setAssistantReplyText(doneText);
  }
  const visibleReplyText = petChat.assistantReplyRef.current;
  const petActionHints = petChat.assistantHiddenReplyTextsRef.current;
  if (!visibleReplyText.trim()) {
    petChat.failStream(messageId, "没有收到可显示回复", "AI 只返回了括号内的隐藏动作，没有可展示给用户的内容。");
    return;
  }
  const wasReplyStarted = petChat.replyStartedRef.current;
  petChat.replyStartedRef.current = true;
  if (!wasReplyStarted) {
    context.onVisibleAssistantReply?.();
  }
  setMessages((current) =>
    current.map((message) =>
      message.id === messageId
        ? {
            ...message,
            content: visibleReplyText,
            live2d_action_hints: petActionHints.length > 0 ? petActionHints : message.live2d_action_hints,
            status: "completed",
          }
        : message,
    ),
  );
  petChat.startReplyPaging(messageId);
}
