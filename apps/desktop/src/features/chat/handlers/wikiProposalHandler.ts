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
    label: "知识整理确认项",
    detail,
    tone: "info",
  });
  if (!petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: "收到知识整理确认项",
      message: detail,
      tone: "tool",
    });
    petChat.scheduleStreamWatchdog(
      "还在想",
      "知识整理确认项已展示，这次需要多等一会儿。",
      14000,
      () => petChat.failStream(messageId, "没有等到回复", "知识整理确认项已展示，但这次没有等到可显示的回复。"),
    );
  }
}
