import { useEffect, type FormEvent } from "react";
import { buildPetInputIntentMessage } from "../features/chat/petInputModes";
import { applyStreamEvent } from "../features/chat/streamDispatcher";
import {
  CHAT_STREAM_WATCHDOG_TIMEOUT_MS,
  PET_BUBBLE_ERROR_HIDE_DELAY_MS,
  PET_BUBBLE_STOPPED_HIDE_DELAY_MS,
} from "../features/chat/chatTiming";
import { normalizeMemoryProposalPayload } from "../features/memory/memoryUtils";
import type { useWiki } from "../features/wiki/useWiki";
import {
  formatContinuityKind,
  normalizeContinuityProposal,
  normalizeContinuitySignal,
} from "../features/continuity/continuityFormatters";
import { describeError } from "../services/apiErrorMessages";
import { fetchSseStream } from "../services/sse";
import type { ChatMessage } from "../types";
import { useLatestCallback } from "../hooks/useLatestCallback";
import type { AppState } from "./useAppState";
import type { ConnectionSettingsDomain } from "./useConnectionSettingsDomain";
import type { AgentActivityDomain } from "./useAgentActivityDomain";
import type { TaskDomain } from "./useTaskDomain";
import type { MemoryDomain } from "./useMemoryDomain";
import type { ContinuityDomain } from "./useContinuityDomain";
import type { ReflectionDomain } from "./useReflectionDomain";
import type { PetDomain } from "./usePetDomain";
import {
  chatMessageFromDailyHistory,
  displayTextForInputMode,
  resolveDailyHistoryTimeZone,
} from "./appShellUtils";
import type { SendChatTextOptions } from "./types";

type WikiDomain = ReturnType<typeof useWiki>;

type UseChatStreamingDomainOptions = {
  app: AppState;
  connection: ConnectionSettingsDomain;
  activity: AgentActivityDomain;
  tasks: TaskDomain;
  memory: MemoryDomain;
  continuity: ContinuityDomain;
  reflection: ReflectionDomain;
  wiki: WikiDomain;
  pet: PetDomain;
};

export function useChatStreamingDomain({
  app,
  connection,
  activity,
  tasks,
  memory,
  continuity,
  reflection,
  wiki,
  pet,
}: UseChatStreamingDomainOptions) {
  const api = connection.connection.api;
  const client = connection.connection.client;

  function appendChatEvent(
    messageId: string,
    event: { label: string; detail: string; tone?: "info" | "success" | "error" },
  ) {
    app.setMessages((current) => current.map((message) =>
      message.id === messageId
        ? {
            ...message,
            events: [
              ...(message.events || []),
              { id: crypto.randomUUID(), label: event.label, detail: event.detail, tone: event.tone },
            ],
          }
        : message,
    ));
  }

  function upsertChatMemoryProposal(messageId: string, proposalId: string, payload: Record<string, unknown>) {
    const proposal = normalizeMemoryProposalPayload(proposalId, payload);
    app.setMessages((current) => current.map((message) => {
      if (message.id !== messageId) {
        return message;
      }
      const proposals = message.memory_proposals || [];
      return {
        ...message,
        memory_proposals: [
          proposal,
          ...proposals.filter((item) => item.proposal_id !== proposal.proposal_id),
        ],
      };
    }));
  }

  async function sendChatText(
    rawText: string,
    clearInput: () => void,
    options: SendChatTextOptions = {},
  ): Promise<boolean> {
    const text = rawText.trim();
    if (!text || app.streamingRef.current) {
      return false;
    }
    pet.tts.waitingCue.stop("new_request");
    app.streamAbortRef.current?.abort();
    const requestId = crypto.randomUUID();
    app.activeChatRequestIdRef.current = requestId;
    const displayText = options.displayText?.trim() || text;
    if (activity.status !== "loading") {
      void activity.load({ silent: true });
    }

    const assistantId = crypto.randomUUID();
    const nextMessages: ChatMessage[] = [
      { id: crypto.randomUUID(), role: "user", content: displayText, status: "completed" },
      { id: assistantId, role: "assistant", content: "", status: "partial", citations: [] },
    ];
    app.setMessages((current) => [...current, ...nextMessages]);
    clearInput();
    pet.chat.setInputVisible(false);
    app.streamingRef.current = true;
    app.setStreaming(true);
    app.setNotice(null);
    pet.chat.resetStreamState(assistantId);
    const scheduleReplyWatchdog = () => pet.chat.scheduleStreamWatchdog(
      "正在整理",
      "资料多一点，我继续看。",
      CHAT_STREAM_WATCHDOG_TIMEOUT_MS,
      () => pet.chat.failStream(assistantId, "没有等到回复", "这次没有等到可显示的回复，本轮已停止。"),
    );
    pet.chat.showBubble({ title: "", message: pet.tts.waitingCue.start(), tone: "thinking" });
    scheduleReplyWatchdog();

    const abort = new AbortController();
    app.streamAbortRef.current = abort;
    const isCurrentRequest = () => app.activeChatRequestIdRef.current === requestId;

    try {
      const accepted = await api.startChat({
        conversation_id: app.conversationIdRef.current,
        message: text,
      }, abort.signal);
      if (!isCurrentRequest()) {
        return false;
      }
      app.conversationIdRef.current = accepted.conversation_id;
      app.setConversationId(accepted.conversation_id);
      app.setMessages((current) => current.map((message) =>
        message.id === assistantId ? { ...message, agent_run_id: accepted.agent_run_id } : message,
      ));
      scheduleReplyWatchdog();

      await fetchSseStream(client, accepted.stream_url, {
        onOpen: () => {
          pet.chat.streamOpenedRef.current = true;
          pet.chat.clearStreamWatchdogTimer();
          if (!pet.chat.replyStartedRef.current && !pet.chat.streamReceivedEventRef.current) {
            scheduleReplyWatchdog();
          }
        },
        onEvent: (sseEvent) => {
          if (!isCurrentRequest()) {
            return;
          }
          applyStreamEvent(assistantId, sseEvent, {
            petChat: pet.chat,
            setMessages: app.setMessages,
            appendChatEvent,
            upsertAgentAction: activity.upsert,
            setLatestContinuitySignal: continuity.setLatestSignal,
            upsertChatContinuitySignal: continuity.upsertChatSignal,
            normalizeContinuitySignal,
            upsertContinuityProposal: continuity.upsertProposal,
            upsertChatContinuityProposal: continuity.upsertChatProposal,
            normalizeContinuityProposal,
            formatContinuityKind,
            upsertProposalFromPayload: memory.upsertProposalFromPayload,
            upsertChatMemoryProposal,
            upsertChatWikiProposal: wiki.upsertChatWikiProposal,
            addTaskFromChat: tasks.controller.addTaskFromChat,
            triggerPetTaskStage: tasks.triggerPetTaskStage,
            onVisibleAssistantReply: () => pet.tts.waitingCue.stop("assistant_visible_reply"),
          });
          if (sseEvent.event === "reply_ready") {
            app.streamingRef.current = false;
            app.setStreaming(false);
            void activity.load({ silent: true });
            // 回复刚结束,后台反思任务才刚被调度;这里拉一次是为了覆盖它已经跑完的
            // 情况,任务晚一步完成则由 useReflectionDomain 的轮询兜住。
            void reflection.load({ silent: true });
            void activity.loadMemoryReceipts(assistantId, accepted.agent_run_id, abort.signal);
          }
        },
      }, abort.signal);
      if (!isCurrentRequest()) {
        return false;
      }
      pet.chat.clearStreamWatchdogTimer();
      if (pet.chat.streamFailedRef.current) {
        return false;
      }
      if (pet.chat.replyStartedRef.current) {
        app.setMessages((current) => current.map((message) =>
          message.id === assistantId && message.status === "partial"
            ? { ...message, status: "completed" }
            : message,
        ));
        pet.chat.startReplyPaging(assistantId);
        void activity.loadMemoryReceipts(assistantId, accepted.agent_run_id, abort.signal);
      } else {
        pet.chat.completeStreamWithoutReply(assistantId);
      }
      return !pet.chat.streamFailedRef.current;
    } catch (error) {
      if (!isCurrentRequest()) {
        return false;
      }
      pet.chat.clearStreamWatchdogTimer();
      pet.tts.waitingCue.stop("send_failed");
      if (pet.chat.streamFailedRef.current) {
        // 终局已经有人接手:用户点了停止,或者看门狗已把它判成失败。这里再改状态
        // 会把"超时失败"写成"用户取消",并抹掉 hasStreamTerminalState 的兜底
        // (排队中的超时回调还会再弹一次错误气泡)。
        return false;
      }
      pet.chat.streamFailedRef.current = true;
      const failureMessage = describeError(error, "消息发送失败");
      app.setMessages((current) => current.map((message) =>
        message.id === assistantId
          ? { ...message, status: "failed", content: message.content || failureMessage }
          : message,
      ));
      pet.chat.showBubble({ title: "交互失败", message: failureMessage, tone: "error" });
      pet.chat.scheduleHide(PET_BUBBLE_ERROR_HIDE_DELAY_MS);
      app.setNotice({ tone: "error", message: failureMessage });
      return false;
    } finally {
      if (app.activeChatRequestIdRef.current === requestId) {
        pet.chat.clearStreamWatchdogTimer();
        app.streamingRef.current = false;
        app.setStreaming(false);
        app.streamAbortRef.current = null;
        app.activeChatRequestIdRef.current = null;
        pet.chat.finishStream();
      }
    }
  }

  async function loadDailyHistory(options: { signal?: AbortSignal } = {}) {
    try {
      const response = await api.getDailyChatHistory({ timezone: resolveDailyHistoryTimeZone() }, options.signal);
      if (options.signal?.aborted || app.streamingRef.current || app.messagesRef.current.length > 0) {
        return;
      }
      if (response.conversation_id) {
        app.conversationIdRef.current = response.conversation_id;
        app.setConversationId(response.conversation_id);
      }
      const restored = response.messages
        .map(chatMessageFromDailyHistory)
        .filter((message): message is ChatMessage => message !== null);
      if (restored.length > 0) {
        app.setMessages(restored);
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
    }
  }

  async function sendPetMessage(event: FormEvent) {
    event.preventDefault();
    await sendChatText(
      buildPetInputIntentMessage(app.petInputMode, pet.chat.input),
      () => pet.chat.setInput(""),
      { displayText: displayTextForInputMode(app.petInputMode, pet.chat.input) },
    );
  }

  function stopStreaming() {
    pet.chat.clearStreamWatchdogTimer();
    pet.tts.waitingCue.stop("stream_stopped");
    pet.chat.streamFailedRef.current = true;
    app.streamAbortRef.current?.abort();
    app.setStreaming(false);
    pet.chat.showBubble({ title: "已停止", message: "本次回复已停止生成。", tone: "error" });
    pet.chat.scheduleHide(PET_BUBBLE_STOPPED_HIDE_DELAY_MS);
    app.setMessages((current) => current.map((message) =>
      message.status === "partial" ? { ...message, status: "cancelled" } : message,
    ));
  }

  const loadDailyHistoryEvent = useLatestCallback(loadDailyHistory);
  useEffect(() => {
    if (!connection.sidecarConnected && connection.connection.health?.status !== "ok") {
      return;
    }
    const abort = new AbortController();
    void loadDailyHistoryEvent({ signal: abort.signal });
    return () => abort.abort();
  }, [
    connection.connection.health?.status,
    connection.connection.sidecarStatus?.updatedAt,
    connection.sidecarConnected,
    loadDailyHistoryEvent,
  ]);

  return { sendChatText, sendPetMessage, stopStreaming };
}

export type ChatStreamingDomain = ReturnType<typeof useChatStreamingDomain>;
