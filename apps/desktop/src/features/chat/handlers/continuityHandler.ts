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
      "等待回复内容",
      "连续性确认项已展示，正在等待模型生成最终回复。",
      12000,
      () => petChat.failStream(messageId, "模型回复超时", "连续性确认项已展示，但模型长时间没有返回最终回复。"),
    );
  }
}
