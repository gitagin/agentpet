import type { StreamHandlerInput } from "../streamDispatcher";

export function continuitySignalHandler({ messageId, payload, context }: StreamHandlerInput) {
  const {
    petChat,
    appendChatEvent,
    normalizeContinuitySignal,
    setLatestContinuitySignal,
    upsertChatContinuitySignal,
  } = context;
  const signal = normalizeContinuitySignal(payload);
  if (signal) {
    petChat.latestContinuitySignalRef.current = signal;
    setLatestContinuitySignal(signal);
    upsertChatContinuitySignal(messageId, signal);
  }
  appendChatEvent(messageId, {
    label: "连续性在场",
    detail: signal ? `${signal.title}：${signal.summary}` : "已收到运行时连续性提示。",
    tone: "success",
  });
}

export function continuityProposalHandler({ messageId, payload, context }: StreamHandlerInput) {
  const {
    petChat,
    appendChatEvent,
    normalizeContinuityProposal,
    upsertChatContinuityProposal,
    upsertContinuityProposal,
    formatContinuityKind,
  } = context;
  const proposal = normalizeContinuityProposal(payload);
  if (proposal) {
    upsertContinuityProposal(proposal);
    upsertChatContinuityProposal(messageId, proposal);
  }
  appendChatEvent(messageId, {
    label: "连续性确认项",
    detail: proposal
      ? `${formatContinuityKind(proposal.kind)}：${proposal.summary}`
      : "收到一条待确认的连续性整理。",
    tone: "info",
  });
  if (!petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: "收到连续性确认项",
      message: proposal ? `${formatContinuityKind(proposal.kind)}：${proposal.summary}` : "有新的连续性整理需要确认。",
      tone: "tool",
    });
    petChat.scheduleStreamWatchdog(
      "还在想",
      "连续性确认项已展示，这次需要多等一会儿。",
      14000,
      () => petChat.failStream(messageId, "没有等到回复", "连续性确认项已展示，但这次没有等到可显示的回复。"),
    );
  }
}
