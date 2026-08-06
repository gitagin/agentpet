import {
  formatWikiProposalEventDetail,
  normalizeChatWikiProposal,
} from "../../../services/chatWikiProposals";
import type { StreamHandlerInput } from "../streamDispatcher";
import { PET_BUBBLE_ACTION_WATCHDOG_TIMEOUT_MS } from "../chatTiming";

export function wikiProposalHandler({ messageId, sseEvent, payload, context }: StreamHandlerInput) {
  const { petChat, appendChatEvent, upsertChatWikiProposal } = context;
  const detail = formatWikiProposalEventDetail(sseEvent.event, payload, sseEvent.data);
  const proposal = normalizeChatWikiProposal(payload);
  if (proposal) {
    upsertChatWikiProposal(messageId, proposal);
  }
  appendChatEvent(messageId, {
    label: "资料整理确认",
    detail,
    tone: "info",
  });
  if (!petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: "收到资料整理确认",
      message: detail,
      tone: "tool",
    });
    petChat.scheduleStreamWatchdog(
      "还在想",
      "资料整理确认已展示，这次需要多等一会儿。",
      PET_BUBBLE_ACTION_WATCHDOG_TIMEOUT_MS,
      () => petChat.failStream(messageId, "没有等到回复", "资料整理确认已展示，但这次没有等到可显示的回复。"),
    );
  }
}
