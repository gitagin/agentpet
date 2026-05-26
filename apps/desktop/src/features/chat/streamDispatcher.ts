import type { Dispatch, SetStateAction } from "react";
import type {
  AgentAction,
  ChatContinuityProposal,
  ChatContinuitySignal,
  ChatMessage,
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
