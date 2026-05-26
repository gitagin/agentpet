import {
  formatWikiProposalEventDetail,
  normalizeChatWikiProposal,
} from "../../../services/chatWikiProposals";
import type { StreamHandlerInput } from "../streamDispatcher";

export function wikiProposalHandler({ messageId, sseEvent, payload, context }: StreamHandlerInput) {
  const { petChat, appendChatEvent, upsertChatWikiProposal } = context;
  const detail = formatWikiProposalEventDetail(sseEvent.event, payload, sseEvent.data);
  const proposal = normalizeChatWikiProposal(payload);
  if (proposal) {
    upsertChatWikiProposal(messageId, proposal);
  }
  appendChatEvent(messageId, {
    label: "Vault 维护确认项",
    detail,
    tone: "info",
  });
  if (!petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: "收到 Vault 维护确认项",
      message: detail,
      tone: "tool",
    });
    petChat.scheduleStreamWatchdog(
      "等待回复内容",
      "Vault 维护确认项已展示，正在等待模型生成最终回复。",
      12000,
      () => petChat.failStream(messageId, "模型回复超时", "Vault 维护确认项已展示，但模型长时间没有返回最终回复。"),
    );
  }
}
