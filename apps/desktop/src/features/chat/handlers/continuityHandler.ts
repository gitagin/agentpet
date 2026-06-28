import type { StreamHandlerInput } from "../streamDispatcher";

function formatContinueTopicKind(kind: string) {
  return kind === "open_thread" ? "下次接着聊" : "陪伴状态";
}

function formatContinueTopicSummary(kind: string, summary: string) {
  return kind === "open_thread" ? `要让我下次记得继续这个话题吗：${summary}` : summary;
}

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
    label: "下次接着聊",
    detail: signal ? `${formatContinueTopicKind(signal.kind)}：${signal.summary}` : "已收到可继续的话题提示。",
    tone: "success",
  });
}

export function continuityProposalHandler({ messageId, payload, context }: StreamHandlerInput) {
  const {
    appendChatEvent,
    normalizeContinuityProposal,
    upsertChatContinuityProposal,
    upsertContinuityProposal,
  } = context;
  const proposal = normalizeContinuityProposal(payload);
  if (proposal) {
    upsertContinuityProposal(proposal);
    upsertChatContinuityProposal(messageId, proposal);
  }
  appendChatEvent(messageId, {
    label: "下次接着聊",
    detail: proposal
      ? formatContinueTopicSummary(proposal.kind, proposal.summary)
      : "有个话题可以保存为下次继续聊。",
    tone: "info",
  });
}
