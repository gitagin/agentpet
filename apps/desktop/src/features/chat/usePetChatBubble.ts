import { useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ChatContinuitySignal, ChatMessage } from "../../types";
import { getPetBubblePageDelay, paginatePetBubbleReply } from "../../services/petBubblePagination";
import type { PetBubblePhase, PetBubbleState, PetBubbleTone } from "./chatTypes";
import { petStreamFinalTimeoutMs, petStreamFinalWatchdogDelayMs } from "./chatTypes";

type UsePetChatBubbleOptions = {
  messages: ChatMessage[];
  latestContinuitySignal: ChatContinuitySignal | null;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setNotice: (notice: { tone: "info" | "error" | "success"; message: string } | null) => void;
  abortStream: () => void;
};

export type PetChatBubbleController = ReturnType<typeof usePetChatBubble>;

export function usePetChatBubble({
  messages,
  latestContinuitySignal,
  setMessages,
  setNotice,
  abortStream,
}: UsePetChatBubbleOptions) {
  const [petInput, setPetInput] = useState("");
  const [petInputVisible, setPetInputVisible] = useState(false);
  const [petBubble, setPetBubble] = useState<PetBubbleState>({
    visible: false,
    title: "",
    message: "",
    tone: "thinking",
    phase: "idle",
  });
  const [petReplyText, setPetReplyText] = useState("");
  const petInputRef = useRef<HTMLInputElement | null>(null);
  const petReplyScrollRef = useRef<HTMLDivElement | null>(null);
  const assistantReplyRef = useRef("");
  const replyStartedRef = useRef(false);
  const replyCompleteRef = useRef(false);
  const replyAutoFollowRef = useRef(true);
  const userIsReadingRef = useRef(false);
  const hideTimerRef = useRef<number | null>(null);
  const pageTimerRef = useRef<number | null>(null);
  const streamWatchdogTimerRef = useRef<number | null>(null);
  const replyPagesRef = useRef<string[]>([]);
  const replyPageIndexRef = useRef(0);
  const replyPagingStartedRef = useRef(false);
  const latestContinuitySignalRef = useRef<ChatContinuitySignal | null>(null);
  const bubblePausedRef = useRef(false);
  const streamOpenedRef = useRef(false);
  const streamReceivedEventRef = useRef(false);
  const streamFailedRef = useRef(false);
  const streamStartedAtRef = useRef<number | null>(null);

  function clearHideTimer() {
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }

  function clearPageTimer() {
    if (pageTimerRef.current !== null) {
      window.clearTimeout(pageTimerRef.current);
      pageTimerRef.current = null;
    }
  }

  function clearStreamWatchdogTimer() {
    if (streamWatchdogTimerRef.current !== null) {
      window.clearTimeout(streamWatchdogTimerRef.current);
      streamWatchdogTimerRef.current = null;
    }
  }

  function hasStreamTerminalState() {
    return replyStartedRef.current || replyCompleteRef.current || streamFailedRef.current;
  }

  function showBubble(next: Omit<PetBubbleState, "visible" | "phase"> & { phase?: PetBubblePhase }) {
    clearHideTimer();
    const phase = next.phase || (next.tone === "reply" ? "speaking" : "thinking");
    setPetBubble({ ...next, phase, visible: true });
  }

  function showReaction(message: string, tone: Exclude<PetBubbleTone, "reply"> = "thinking", title = "") {
    if (replyStartedRef.current) {
      return;
    }
    showBubble({ title, message, tone, phase: tone === "error" ? "complete" : "thinking" });
  }

  function followReplyToBottom() {
    const element = petReplyScrollRef.current;
    if (!element || !replyAutoFollowRef.current || userIsReadingRef.current) {
      return;
    }
    window.requestAnimationFrame(() => {
      const nextElement = petReplyScrollRef.current;
      if (!nextElement || !replyAutoFollowRef.current || userIsReadingRef.current) {
        return;
      }
      nextElement.scrollTop = nextElement.scrollHeight;
    });
  }

  function showReply(text: string, phase: Extract<PetBubblePhase, "speaking" | "complete"> = "speaking") {
    clearHideTimer();
    setPetReplyText(text);
    setPetBubble({ visible: true, title: "", message: text, tone: "reply", phase });
    followReplyToBottom();
  }

  function scheduleStreamWatchdog(
    title: string,
    message: string,
    delayMs = 10000,
    onFinalTimeout?: () => void,
  ) {
    clearStreamWatchdogTimer();
    if (onFinalTimeout && !hasStreamTerminalState()) {
      const elapsedMs = streamStartedAtRef.current === null ? 0 : Date.now() - streamStartedAtRef.current;
      if (elapsedMs >= petStreamFinalTimeoutMs) {
        onFinalTimeout();
        return;
      }
    }
    streamWatchdogTimerRef.current = window.setTimeout(() => {
      streamWatchdogTimerRef.current = null;
      if (hasStreamTerminalState()) {
        return;
      }
      showBubble({ title, message, tone: "thinking" });
      if (!onFinalTimeout) {
        return;
      }

      const elapsedMs = streamStartedAtRef.current === null ? 0 : Date.now() - streamStartedAtRef.current;
      const remainingFinalMs = Math.max(0, petStreamFinalTimeoutMs - elapsedMs);
      const finalDelayMs = Math.min(petStreamFinalWatchdogDelayMs, remainingFinalMs);
      streamWatchdogTimerRef.current = window.setTimeout(() => {
        streamWatchdogTimerRef.current = null;
        if (hasStreamTerminalState()) {
          return;
        }
        onFinalTimeout();
      }, finalDelayMs);
    }, delayMs);
  }

  function markStreamEventReceived() {
    streamReceivedEventRef.current = true;
    clearStreamWatchdogTimer();
  }

  function latestContinuitySignalForMessage(messageId: string): ChatContinuitySignal | null {
    return (
      messages.find((message) => message.id === messageId)?.continuity_signal ||
      latestContinuitySignalRef.current ||
      latestContinuitySignal
    );
  }

  function scheduleHide(delayMs = 8000) {
    clearHideTimer();
    hideTimerRef.current = window.setTimeout(() => {
      if (userIsReadingRef.current || bubblePausedRef.current) {
        hideTimerRef.current = null;
        return;
      }
      setPetBubble((current) => ({ ...current, phase: "fading", visible: false }));
      hideTimerRef.current = null;
    }, delayMs);
  }

  function showContinuityPresenceBubble(signal: ChatContinuitySignal) {
    if (bubblePausedRef.current) {
      return;
    }
    showBubble({
      title: signal.title || "连续性在场",
      message: signal.display_hint ? `${signal.summary} ${signal.display_hint}` : signal.summary,
      tone: "tool",
      phase: "complete",
    });
    scheduleHide(signal.intensity === "high" ? 9000 : 7000);
  }

  function formatContinueHint(pageIndex: number, pageCount: number) {
    if (pageCount <= 1) {
      return undefined;
    }
    return `${pageIndex + 1}/${pageCount}`;
  }

  function renderPage(pageIndex: number, phase: Extract<PetBubblePhase, "speaking" | "complete"> = "speaking") {
    const pages = replyPagesRef.current;
    if (pages.length === 0) {
      return false;
    }
    const safeIndex = Math.max(0, Math.min(pageIndex, pages.length - 1));
    replyPageIndexRef.current = safeIndex;
    clearHideTimer();
    setPetBubble({
      visible: true,
      title: "",
      message: pages[safeIndex],
      tone: "reply",
      phase,
      continueHint: formatContinueHint(safeIndex, pages.length),
    });
    return true;
  }

  function setReplyPagesFromText(
    text: string,
    options: { preserveCurrentPage?: boolean; phase?: Extract<PetBubblePhase, "speaking" | "complete"> } = {},
  ) {
    const pages = paginatePetBubbleReply(text);
    replyPagesRef.current = pages;
    setPetReplyText(text);
    clearHideTimer();
    if (pages.length === 0) {
      setPetBubble({ visible: false, title: "", message: "", tone: "reply", phase: "idle" });
      return;
    }

    const nextIndex = options.preserveCurrentPage
      ? Math.min(replyPageIndexRef.current, pages.length - 1)
      : 0;
    renderPage(nextIndex, options.phase || "speaking");
  }

  function scheduleNextPage() {
    clearPageTimer();
    const pages = replyPagesRef.current;
    if (pages.length === 0 || bubblePausedRef.current) {
      return;
    }
    const currentIndex = replyPageIndexRef.current;
    if (currentIndex >= pages.length - 1) {
      scheduleHide(9000);
      return;
    }
    pageTimerRef.current = window.setTimeout(() => {
      if (bubblePausedRef.current) {
        pageTimerRef.current = null;
        return;
      }
      renderPage(currentIndex + 1, replyCompleteRef.current ? "complete" : "speaking");
      scheduleNextPage();
    }, getPetBubblePageDelay(pages[currentIndex]));
  }

  function startReplyPaging() {
    if (replyPagingStartedRef.current) {
      return;
    }
    clearStreamWatchdogTimer();
    clearPageTimer();
    replyPagingStartedRef.current = true;
    replyCompleteRef.current = true;
    const text = assistantReplyRef.current;
    const pages = paginatePetBubbleReply(text);
    replyPagesRef.current = pages;
    setPetReplyText(text);

    if (pages.length === 0) {
      showBubble({
        title: "",
        message: "我这次没有生成可显示的回复。",
        tone: "reply",
        phase: "complete",
      });
      scheduleHide(6000);
      return;
    }

    const safeIndex = Math.min(replyPageIndexRef.current, pages.length - 1);
    renderPage(safeIndex, "complete");
    scheduleNextPage();
  }

  function failStream(messageId: string, title: string, message: string) {
    if (hasStreamTerminalState()) {
      return;
    }

    streamFailedRef.current = true;
    replyCompleteRef.current = true;
    clearStreamWatchdogTimer();
    clearPageTimer();
    replyPagesRef.current = [];
    setPetReplyText("");
    showBubble({ title, message, tone: "error", phase: "complete" });
    scheduleHide(10000);
    setMessages((current) =>
      current.map((chatMessage) =>
        chatMessage.id === messageId && chatMessage.status === "partial"
          ? { ...chatMessage, status: "failed", content: chatMessage.content || message }
          : chatMessage,
      ),
    );
    setNotice({ tone: "error", message });
    abortStream();
  }

  function completeStreamWithoutReply(messageId: string) {
    if (hasStreamTerminalState()) {
      return;
    }

    const message = streamReceivedEventRef.current
      ? "回复流已经结束，但没有收到可显示的模型回复。"
      : "回复流已经结束，但没有收到任何事件。";
    failStream(messageId, "没有收到回复", message);
  }

  function advancePageManually() {
    const pages = replyPagesRef.current;
    if (pages.length <= 1 || petBubble.tone !== "reply") {
      return;
    }
    clearPageTimer();
    const nextIndex = Math.min(replyPageIndexRef.current + 1, pages.length - 1);
    renderPage(nextIndex, replyCompleteRef.current ? "complete" : "speaking");
    if (nextIndex >= pages.length - 1) {
      if (replyCompleteRef.current && !bubblePausedRef.current) {
        scheduleHide(9000);
      }
      return;
    }
    if (replyPagingStartedRef.current && !bubblePausedRef.current) {
      scheduleNextPage();
    }
  }

  function pausePaging() {
    bubblePausedRef.current = true;
    userIsReadingRef.current = true;
    clearPageTimer();
    clearHideTimer();
  }

  function resumePaging() {
    bubblePausedRef.current = false;
    userIsReadingRef.current = false;
    if (replyPagingStartedRef.current && petBubble.tone === "reply") {
      scheduleNextPage();
    }
  }

  function showInput() {
    setPetInputVisible(true);
    window.requestAnimationFrame(() => petInputRef.current?.focus());
  }

  function resetStreamState() {
    assistantReplyRef.current = "";
    replyStartedRef.current = false;
    replyCompleteRef.current = false;
    replyPagesRef.current = [];
    replyPageIndexRef.current = 0;
    replyPagingStartedRef.current = false;
    bubblePausedRef.current = false;
    streamOpenedRef.current = false;
    streamReceivedEventRef.current = false;
    streamFailedRef.current = false;
    streamStartedAtRef.current = Date.now();
    latestContinuitySignalRef.current = null;
    clearPageTimer();
    clearStreamWatchdogTimer();
    setPetReplyText("");
  }

  function finishStream() {
    clearStreamWatchdogTimer();
    streamStartedAtRef.current = null;
  }

  useEffect(() => {
    return () => {
      clearHideTimer();
      clearPageTimer();
      clearStreamWatchdogTimer();
    };
  }, []);

  return {
    assistantReplyRef,
    bubble: petBubble,
    input: petInput,
    inputRef: petInputRef,
    inputVisible: petInputVisible,
    latestContinuitySignalRef,
    replyCompleteRef,
    replyStartedRef,
    replyText: petReplyText,
    streamFailedRef,
    streamOpenedRef,
    streamReceivedEventRef,
    clearStreamWatchdogTimer,
    completeStreamWithoutReply,
    failStream,
    finishStream,
    markStreamEventReceived,
    resetStreamState,
    scheduleHide,
    scheduleStreamWatchdog,
    setInput: setPetInput,
    setInputVisible: setPetInputVisible,
    setReplyPagesFromText,
    showBubble,
    showContinuityPresenceBubble,
    showInput,
    showReaction,
    showReply,
    startReplyPaging,
    advancePageManually,
    pausePaging,
    resumePaging,
    latestContinuitySignalForMessage,
    replyPagesRef,
  };
}
