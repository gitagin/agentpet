import type { Dispatch, SetStateAction } from "react";
import type {
  AgentAction,
  ChatContextBudget,
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
  upsertChatMemoryProposal: (messageId: string, proposalId: string, payload: Record<string, unknown>) => void;
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

  if (sseEvent.event === "reply_ready" || sseEvent.event === "done") {
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

  if (sseEvent.event === "context_budget") {
    contextBudgetHandler(input);
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
  let visibleReplyText: string | null = null;
  if (token) {
    petChat.appendAssistantReplyText(token);
    visibleReplyText = petChat.assistantReplyRef.current;
    if (visibleReplyText.trim().length > 0) {
      petChat.replyStartedRef.current = true;
      petChat.setReplyPagesFromText(visibleReplyText, { preserveCurrentPage: true });
    }
  } else if (citations?.length && !petChat.replyStartedRef.current) {
    petChat.scheduleStreamWatchdog(
      "正在整理",
      "资料多一点，我继续看。",
      14000,
      () => petChat.failStream(messageId, "没有等到回复", "这次没有等到可显示的回复，本轮已停止。"),
    );
  }
  setMessages((current) =>
    current.map((message) => {
      if (message.id !== messageId) {
        return message;
      }
      return {
        ...message,
        content: token ? (visibleReplyText ?? message.content) : message.content,
        citations: citations ? [...(message.citations || []), ...citations] : message.citations,
      };
    }),
  );
}

function contextBudgetHandler({ messageId, payload, context }: StreamHandlerInput) {
  const contextBudget = normalizeContextBudget(payload);
  if (!contextBudget) {
    return;
  }
  const budgetScopes = [
    ...(contextBudget.selected_scopes || []),
    ...Object.keys(contextBudget.source_counts || {}),
  ];
  context.setMessages((current) =>
    current.map((message) =>
      message.id === messageId
        ? {
            ...message,
            retrieval_attempted: true,
            retrieval_context_budget: contextBudget,
            retrieval_scopes: mergeScopes(message.retrieval_scopes, budgetScopes),
          }
        : message,
    ),
  );
}

function normalizeContextBudget(payload: Record<string, unknown> | null): ChatContextBudget | null {
  if (!payload || typeof payload.strategy !== "string") {
    return null;
  }
  const candidateCount = numberFromPayload(payload.candidate_count);
  const selectedCount = numberFromPayload(payload.selected_count);
  const itemBudget = numberFromPayload(payload.item_budget);
  const perScopeLimit = numberFromPayload(payload.per_scope_limit);
  const charBudget = numberFromPayload(payload.char_budget);
  const usedChars = numberFromPayload(payload.used_chars);
  if (
    candidateCount === null ||
    selectedCount === null ||
    itemBudget === null ||
    perScopeLimit === null ||
    charBudget === null ||
    usedChars === null
  ) {
    return null;
  }
  return {
    strategy: payload.strategy,
    candidate_count: candidateCount,
    selected_count: selectedCount,
    duplicate_drop_count: numberFromPayload(payload.duplicate_drop_count) ?? undefined,
    per_scope_drop_count: numberFromPayload(payload.per_scope_drop_count) ?? undefined,
    budget_drop_count: numberFromPayload(payload.budget_drop_count) ?? undefined,
    item_budget: itemBudget,
    per_scope_limit: perScopeLimit,
    char_budget: charBudget,
    used_chars: usedChars,
    source_counts: normalizeSourceCounts(payload.source_counts),
    selected_scopes: normalizeStringList(payload.selected_scopes),
  };
}

function numberFromPayload(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeSourceCounts(value: unknown): Record<string, number> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const counts: Record<string, number> = {};
  Object.entries(value as Record<string, unknown>).forEach(([key, count]) => {
    if (typeof count === "number" && Number.isFinite(count)) {
      counts[key] = count;
    }
  });
  return Object.keys(counts).length ? counts : undefined;
}

function normalizeStringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const strings = value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  return strings.length ? strings : undefined;
}

function mergeScopes(current: string[] | undefined, next: string[]): string[] {
  return Array.from(new Set([...(current || []), ...next]));
}
