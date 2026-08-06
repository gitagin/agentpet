import type { StreamHandlerInput } from "../streamDispatcher";
import { PET_BUBBLE_ACTION_WATCHDOG_TIMEOUT_MS } from "../chatTiming";

export function memoryProposalHandler({ messageId, payload, context }: StreamHandlerInput, proposalId: string) {
  const { petChat, appendChatEvent, upsertChatMemoryProposal, upsertProposalFromPayload } = context;
  if (payload) {
    upsertProposalFromPayload(proposalId, payload);
    upsertChatMemoryProposal(messageId, proposalId, payload);
  }
  appendChatEvent(messageId, {
    label: "记忆确认项",
    detail: "已整理一条待确认长期记忆。",
    tone: "success",
  });
  if (!petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: "正在整理记忆",
      message: "我正在根据你的输入整理长期记忆。",
      tone: "tool",
    });
    petChat.scheduleStreamWatchdog(
      "还在想",
      "记忆确认项已处理，这次需要多等一会儿。",
      PET_BUBBLE_ACTION_WATCHDOG_TIMEOUT_MS,
      () => petChat.failStream(messageId, "没有等到回复", "记忆确认项已处理，但这次没有等到可显示的回复。"),
    );
  }
}
