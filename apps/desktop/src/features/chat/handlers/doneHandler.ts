import { extractSseText } from "../chatStreamUtils";
import { stripAssistantActionDirectivesFromMarkdown } from "../assistantActionDirectives";
import type { StreamHandlerInput } from "../streamDispatcher";

export function doneHandler({ messageId, sseEvent, payload, context }: StreamHandlerInput) {
  const { petChat, setMessages } = context;
  const doneText = extractSseText(sseEvent, payload);
  const streamedRawReplyText = petChat.assistantRawReplyRef.current;
  const rawReplyText =
    sseEvent.event === "done"
      ? streamedRawReplyText.trim()
        ? streamedRawReplyText
        : doneText
      : doneText || streamedRawReplyText;
  if (rawReplyText) {
    petChat.setAssistantReplyText(rawReplyText);
  }
  const petActionHints = petChat.assistantHiddenReplyTextsRef.current;
  if (!stripAssistantActionDirectivesFromMarkdown(rawReplyText).trim()) {
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
            content: rawReplyText || message.content,
            live2d_action_hints: petActionHints.length > 0 ? petActionHints : message.live2d_action_hints,
            status: "completed",
          }
        : message,
    ),
  );
  petChat.startReplyPaging(messageId);
}
