import type { StreamHandlerInput } from "../streamDispatcher";

export function memoryProposalHandler({ messageId, payload, context }: StreamHandlerInput, proposalId: string) {
  const { petChat, appendChatEvent, upsertProposalFromPayload } = context;
  if (payload) {
    upsertProposalFromPayload(proposalId, payload);
  }
  appendChatEvent(messageId, {
    label: "记忆确认项",
    detail: `已创建待确认长期记忆：${proposalId}`,
    tone: "success",
  });
  if (!petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: "正在整理记忆",
      message: "我正在根据你的输入整理长期记忆。",
      tone: "tool",
    });
    petChat.scheduleStreamWatchdog(
      "等待回复内容",
      "记忆确认项已处理，正在等待模型生成最终回复。",
      12000,
      () => petChat.failStream(messageId, "模型回复超时", "记忆确认项已处理，但模型长时间没有返回最终回复。"),
    );
  }
}
