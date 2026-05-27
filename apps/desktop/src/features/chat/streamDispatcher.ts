import type { Dispatch, SetStateAction } from "react";
import type {
  AgentAction,
  ChatContinuityProposal,
  ChatContinuitySignal,
  ChatMessage,
  ChatNegotiationAction,
  ChatNegotiationDone,
  ChatNegotiationStep,
  ChatWikiProposal,
  ContinuityProposal,
  ContinuityProposalKind,
  TaskItem,
} from "../../types";
import type { SseEvent } from "../../services/sse";
import { isWikiProposalStreamEvent } from "../../services/chatWikiProposals";
import { extractSseText, isCitationPayload, parseJson } from "./chatStreamUtils";
import type { PetChatBubbleController } from "./usePetChatBubble";
import { agentActionHandler } from "./handlers/agentActionHandler";
import { continuityProposalHandler, continuitySignalHandler } from "./handlers/continuityHandler";
import { doneHandler } from "./handlers/doneHandler";
import { errorHandler } from "./handlers/errorHandler";
import { memoryProposalHandler } from "./handlers/memoryProposalHandler";
import { statusHandler } from "./handlers/statusHandler";
import { taskHandler } from "./handlers/taskHandler";
import { wikiProposalHandler } from "./handlers/wikiProposalHandler";

export type StreamDispatcherContext = {
  petChat: PetChatBubbleController;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  appendChatEvent: (
    messageId: string,
    event: { label: string; detail: string; tone?: "info" | "success" | "error" },
  ) => void;
  upsertAgentAction: (action: AgentAction) => void;
  setLatestContinuitySignal: Dispatch<SetStateAction<ChatContinuitySignal | null>>;
  upsertChatContinuitySignal: (messageId: string, signal: ChatContinuitySignal) => void;
  normalizeContinuitySignal: (payload: Record<string, unknown> | null) => ChatContinuitySignal | null;
  upsertContinuityProposal: (proposal: ContinuityProposal) => void;
  upsertChatContinuityProposal: (messageId: string, proposal: ChatContinuityProposal) => void;
  normalizeContinuityProposal: (payload: Record<string, unknown> | null) => ContinuityProposal | null;
  formatContinuityKind: (kind: ContinuityProposalKind | string) => string;
  upsertProposalFromPayload: (proposalId: string, payload: Record<string, unknown>) => void;
  upsertChatWikiProposal: (messageId: string, proposal: ChatWikiProposal) => void;
  addTaskFromChat: (task: TaskItem) => void;
  triggerLive2DTaskStage: () => void;
};

export type StreamHandlerInput = {
  messageId: string;
  sseEvent: SseEvent;
  payload: Record<string, unknown> | null;
  context: StreamDispatcherContext;
};

export function applyStreamEvent(messageId: string, sseEvent: SseEvent, context: StreamDispatcherContext) {
  context.petChat.markStreamEventReceived();
  const payload = parseJson(sseEvent.data);
  const input = { messageId, sseEvent, payload, context };

  if (sseEvent.event === "done") {
    doneHandler(input);
    return;
  }

  if (sseEvent.event === "error") {
    errorHandler(input);
    return;
  }

  if (sseEvent.event === "status") {
    statusHandler(input);
    return;
  }

  if (sseEvent.event === "agent_action") {
    agentActionHandler(input);
    return;
  }

  if (sseEvent.event === "negotiation_step") {
    negotiationStepHandler(input);
    return;
  }

  if (sseEvent.event === "negotiation_done") {
    negotiationDoneHandler(input);
    return;
  }

  if (sseEvent.event === "continuity_signal") {
    continuitySignalHandler(input);
    return;
  }

  const proposalId = payload?.proposal_id;
  if (sseEvent.event === "continuity_proposal") {
    continuityProposalHandler(input);
    return;
  }

  if (sseEvent.event === "memory_proposal" && typeof proposalId === "string") {
    memoryProposalHandler(input, proposalId);
    return;
  }

  if (isWikiProposalStreamEvent(sseEvent.event)) {
    wikiProposalHandler(input);
    return;
  }

  const taskId = payload?.task_id;
  if (sseEvent.event === "task" && typeof taskId === "string") {
    taskHandler(input, taskId);
    return;
  }

  applyTextOrCitationEvent(input);
}

function negotiationStepHandler({ messageId, payload, context }: StreamHandlerInput) {
  const step = normalizeNegotiationStep(payload);
  if (!step) {
    return;
  }
  context.setMessages((current) =>
    current.map((message) =>
      message.id === messageId
        ? {
            ...message,
            negotiation_steps: [...(message.negotiation_steps || []), step],
          }
        : message,
    ),
  );
}

function negotiationDoneHandler({ messageId, payload, context }: StreamHandlerInput) {
  const done = normalizeNegotiationDone(payload);
  if (!done) {
    return;
  }
  context.setMessages((current) =>
    current.map((message) => (message.id === messageId ? { ...message, negotiation_done: done } : message)),
  );
}

function normalizeNegotiationStep(payload: Record<string, unknown> | null): ChatNegotiationStep | null {
  if (!payload) {
    return null;
  }
  const action = payload.action;
  if (!isNegotiationAction(action)) {
    return null;
  }
  return {
    round: typeof payload.round === "number" ? payload.round : 0,
    agent: typeof payload.agent === "string" ? payload.agent : "orchestrator",
    action,
    reasoning: typeof payload.reasoning === "string" ? payload.reasoning : "",
    confidence: typeof payload.confidence === "number" ? payload.confidence : 0,
    message: typeof payload.message === "string" ? payload.message : "",
  };
}

function normalizeNegotiationDone(payload: Record<string, unknown> | null): ChatNegotiationDone | null {
  if (!payload) {
    return null;
  }
  return {
    total_rounds: typeof payload.total_rounds === "number" ? payload.total_rounds : 0,
    agents_invoked: Array.isArray(payload.agents_invoked)
      ? payload.agents_invoked.filter((agent): agent is string => typeof agent === "string")
      : [],
    total_latency_ms: typeof payload.total_latency_ms === "number" ? payload.total_latency_ms : 0,
    final_confidence: typeof payload.final_confidence === "number" ? payload.final_confidence : 0,
    fallback: payload.fallback === true,
  };
}

function isNegotiationAction(action: unknown): action is ChatNegotiationAction {
  return action === "invoking" || action === "reviewing" || action === "revising" || action === "synthesizing";
}

function applyTextOrCitationEvent({ messageId, sseEvent, payload, context }: StreamHandlerInput) {
  const { petChat, setMessages } = context;
  const token = extractSseText(sseEvent, payload);
  const citation =
    sseEvent.event === "citation" && isCitationPayload(payload?.citation) ? payload.citation : undefined;
  const citations = Array.isArray(payload?.citations)
    ? payload.citations.filter(isCitationPayload)
    : citation
      ? [citation]
      : undefined;
  if (token) {
    petChat.replyStartedRef.current = true;
    petChat.assistantReplyRef.current = `${petChat.assistantReplyRef.current}${token}`;
    petChat.setReplyPagesFromText(petChat.assistantReplyRef.current, { preserveCurrentPage: true });
  } else if (citations?.length && !petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: "找到记忆线索",
      message: citations[0]?.relative_path ? `参考：${citations[0].relative_path}` : "我正在引用本地记忆回答。",
      tone: "tool",
    });
    petChat.scheduleStreamWatchdog(
      "等待回复内容",
      "已经找到参考内容，正在等待模型生成最终回复。",
      12000,
      () => petChat.failStream(messageId, "模型回复超时", "已经找到参考内容，但模型长时间没有返回最终回复。"),
    );
  }
  setMessages((current) =>
    current.map((message) => {
      if (message.id !== messageId) {
        return message;
      }
      return {
        ...message,
        content: token ? `${message.content}${token}` : message.content,
        citations: citations ? [...(message.citations || []), ...citations] : message.citations,
      };
    }),
  );
}
