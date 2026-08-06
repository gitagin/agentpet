import type { Dispatch, SetStateAction } from "react";
import type {
  AgentAction,
  ChatContextBudget,
  ChatContinuityProposal,
  ChatContinuitySignal,
  ChatMessage,
  ChatNegotiationDone,
  ChatNegotiationStep,
  ChatTraceAgentId,
  ChatTraceCounts,
  ChatTracePhase,
  ChatTraceReasonCode,
  ChatTraceSourceScope,
  ChatTraceStatus,
  ChatWikiProposal,
  ContinuityProposal,
  ContinuityProposalKind,
  TaskItem,
} from "../../types";
import type { SseEvent } from "../../services/sse";
import { isWikiProposalStreamEvent } from "../../services/chatWikiProposals";
import { PET_BUBBLE_ACTION_WATCHDOG_TIMEOUT_MS } from "./chatTiming";
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
  triggerPetTaskStage: () => void;
  onVisibleAssistantReply?: () => void;
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
            progress_stage: "verifying",
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
    current.map((message) => (
      message.id === messageId
        ? { ...message, progress_stage: "answering", negotiation_done: done }
        : message
    )),
  );
}

function normalizeNegotiationStep(payload: Record<string, unknown> | null): ChatNegotiationStep | null {
  if (!payload) {
    return null;
  }
  if (payload.contract_version === "agent-trace.v1") {
    const trace = normalizeVersionedTrace(payload);
    return trace?.phase === "completed" ? null : trace;
  }
  const phase = normalizeLegacyPhase(payload.action);
  if (!phase) {
    return null;
  }
  const reasonCode = legacyStepReasonCode(phase);
  return {
    contract_version: "agent-trace.v1",
    run_id: normalizeTraceRunId(payload.agent_run_id),
    branch_id: "foreground",
    stage_id: "negotiation",
    agent_id: normalizeTraceAgentId(payload.agent),
    phase,
    status: "running",
    round: nonNegativeInteger(payload.round),
    sequence: Math.max(1, nonNegativeInteger(payload.round) + 1),
    duration_ms: 0,
    reason_code: reasonCode,
    safe_summary: TRACE_SAFE_SUMMARIES[reasonCode],
    counts: emptyTraceCounts(),
    source_scope: "none",
  };
}

function normalizeNegotiationDone(payload: Record<string, unknown> | null): ChatNegotiationDone | null {
  if (!payload) {
    return null;
  }
  if (payload.contract_version === "agent-trace.v1") {
    const trace = normalizeVersionedTrace(payload);
    return trace?.phase === "completed" ? trace : null;
  }
  const rounds = nonNegativeInteger(payload.total_rounds);
  const fallback = payload.fallback === true;
  const reasonCode: ChatTraceReasonCode = fallback
    ? "negotiation_completed_with_fallback"
    : "negotiation_completed";
  return {
    contract_version: "agent-trace.v1",
    run_id: normalizeTraceRunId(payload.agent_run_id),
    branch_id: "foreground",
    stage_id: "negotiation",
    agent_id: "orchestrator",
    phase: "completed",
    status: "completed",
    round: rounds,
    sequence: Math.max(1, rounds + 1),
    duration_ms: nonNegativeInteger(payload.total_latency_ms),
    reason_code: reasonCode,
    safe_summary: TRACE_SAFE_SUMMARIES[reasonCode],
    counts: {
      agents_invoked: Array.isArray(payload.agents_invoked) ? payload.agents_invoked.length : 0,
      citations: 0,
      rounds,
    },
    source_scope: "none",
  };
}

const TRACE_AGENT_IDS: readonly ChatTraceAgentId[] = ["orchestrator", "retrieval_agent", "synthesizer"];
const TRACE_PHASES: readonly ChatTracePhase[] = ["invoking", "reviewing", "revising", "synthesizing", "completed"];
const TRACE_STATUSES: readonly ChatTraceStatus[] = ["running", "fallback", "completed"];
const TRACE_SOURCE_SCOPES: readonly ChatTraceSourceScope[] = [
  "none",
  "personal_memory",
  "diary_objects",
  "daily_chat",
  "knowledge_base",
  "pending_memory",
  "mixed",
];
const TRACE_SAFE_SUMMARIES: Record<ChatTraceReasonCode, string> = {
  additional_context_required: "需要补充本地证据，正在进行有界检索。",
  evidence_review: "正在核验已收集的本地证据。",
  evidence_revised: "已按核验结果调整处理步骤。",
  evidence_ready: "已有信息足够，正在合成回复。",
  max_rounds_reached: "已达到协商轮次上限，正在整理已有结果。",
  duplicate_agent_query: "已阻止重复检索，正在整理已有结果。",
  unsupported_agent_request: "已阻止不受支持的协作请求，正在整理已有结果。",
  invalid_agent_request: "未找到可用的协作步骤，正在整理已有结果。",
  orchestrator_model_unavailable: "协调能力暂不可用，正在基于本地证据完成回复。",
  orchestrator_timeout: "协调步骤超时，正在基于已有本地证据完成回复。",
  orchestrator_invalid_response: "协调结果无效，正在基于已有本地证据完成回复。",
  agent_timeout: "检索步骤超时，正在基于已有本地证据完成回复。",
  agent_invocation_failed: "检索步骤未完成，正在基于已有本地证据完成回复。",
  negotiation_fallback: "协作已安全停止，正在整理已有结果。",
  negotiation_completed: "协作已完成。",
  negotiation_completed_with_fallback: "协作已通过安全兜底完成。",
};

function normalizeVersionedTrace(payload: Record<string, unknown>): ChatNegotiationStep | null {
  if (
    payload.branch_id !== "foreground" ||
    payload.stage_id !== "negotiation" ||
    !isOneOf(payload.agent_id, TRACE_AGENT_IDS) ||
    !isOneOf(payload.phase, TRACE_PHASES) ||
    !isOneOf(payload.status, TRACE_STATUSES) ||
    !isTraceReasonCode(payload.reason_code) ||
    !isOneOf(payload.source_scope, TRACE_SOURCE_SCOPES) ||
    !isSafeTraceRunId(payload.run_id)
  ) {
    return null;
  }
  const counts = normalizeTraceCounts(payload.counts);
  if (!counts) {
    return null;
  }
  const reasonCode = payload.reason_code;
  return {
    contract_version: "agent-trace.v1",
    run_id: payload.run_id,
    branch_id: "foreground",
    stage_id: "negotiation",
    agent_id: payload.agent_id,
    phase: payload.phase,
    status: payload.status,
    round: nonNegativeInteger(payload.round),
    sequence: Math.max(1, nonNegativeInteger(payload.sequence)),
    duration_ms: nonNegativeInteger(payload.duration_ms),
    reason_code: reasonCode,
    safe_summary: TRACE_SAFE_SUMMARIES[reasonCode],
    counts,
    source_scope: payload.source_scope,
  };
}

function normalizeTraceCounts(value: unknown): ChatTraceCounts | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const counts = value as Record<string, unknown>;
  return {
    agents_invoked: nonNegativeInteger(counts.agents_invoked),
    citations: nonNegativeInteger(counts.citations),
    rounds: nonNegativeInteger(counts.rounds),
  };
}

function emptyTraceCounts(): ChatTraceCounts {
  return { agents_invoked: 0, citations: 0, rounds: 0 };
}

function normalizeLegacyPhase(value: unknown): Exclude<ChatTracePhase, "completed"> | null {
  return value === "invoking" || value === "reviewing" || value === "revising" || value === "synthesizing"
    ? value
    : null;
}

function legacyStepReasonCode(phase: Exclude<ChatTracePhase, "completed">): ChatTraceReasonCode {
  if (phase === "invoking") {
    return "additional_context_required";
  }
  if (phase === "reviewing") {
    return "evidence_review";
  }
  if (phase === "revising") {
    return "evidence_revised";
  }
  return "evidence_ready";
}

function normalizeTraceAgentId(value: unknown): ChatTraceAgentId {
  return isOneOf(value, TRACE_AGENT_IDS) ? value : "orchestrator";
}

function normalizeTraceRunId(value: unknown): string {
  return isSafeTraceRunId(value) ? value : "legacy-run";
}

function isSafeTraceRunId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
}

function isTraceReasonCode(value: unknown): value is ChatTraceReasonCode {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(TRACE_SAFE_SUMMARIES, value);
}

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === "string" && allowed.includes(value as T);
}

function nonNegativeInteger(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0;
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
  let hiddenActionHints: string[] | null = null;
  if (token) {
    petChat.appendAssistantReplyText(token);
    visibleReplyText = petChat.assistantReplyRef.current;
    hiddenActionHints = petChat.assistantHiddenReplyTextsRef.current;
    if (visibleReplyText.trim().length > 0) {
      const wasReplyStarted = petChat.replyStartedRef.current;
      petChat.replyStartedRef.current = true;
      if (!wasReplyStarted) {
        context.onVisibleAssistantReply?.();
      }
      petChat.setReplyPagesFromText(visibleReplyText, { preserveCurrentPage: true });
    }
  } else if (citations?.length && !petChat.replyStartedRef.current) {
    petChat.scheduleStreamWatchdog(
      "正在整理",
      "资料多一点，我继续看。",
      PET_BUBBLE_ACTION_WATCHDOG_TIMEOUT_MS,
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
        progress_stage: token
          ? "answering"
          : citations?.length
            ? "verifying"
            : message.progress_stage,
        content: token ? (visibleReplyText ?? message.content) : message.content,
        live2d_action_hints:
          hiddenActionHints && hiddenActionHints.length > 0 ? hiddenActionHints : message.live2d_action_hints,
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
