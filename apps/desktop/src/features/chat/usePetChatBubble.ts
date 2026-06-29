import { useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ChatContinuitySignal, ChatMessage, TtsPlaybackItem, TtsPlaybackState, TtsProviderId, TtsVoice } from "../../types";
import { getPetBubblePageDelay, paginatePetBubbleReply, segmentPetBubbleText } from "../../services/petBubblePagination";
import type { PetBubblePhase, PetBubbleState, PetBubbleTone } from "./chatTypes";
import { petStreamFinalTimeoutMs } from "./chatTypes";
import {
  createAssistantReplyTextFilter,
  filterAssistantReplyText,
  normalizeVisibleAssistantReplyText,
  stripAssistantHiddenReplyText,
} from "./assistantReplyVisibility";
import type { TtsPlaybackQueueController } from "../tts";
import type { TtsProviderPlaybackStatus } from "../tts";

type PetChatTtsOptions = {
  enabled: boolean;
  queue: TtsPlaybackQueueController;
  provider: TtsProviderId;
  voice: TtsVoice | null;
  speed: number;
  volume: number;
  cacheEnabled: boolean;
  playbackState?: TtsPlaybackState;
};

type UsePetChatBubbleOptions = {
  messages: ChatMessage[];
  latestContinuitySignal: ChatContinuitySignal | null;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setNotice: (notice: { tone: "info" | "error" | "success"; message: string } | null) => void;
  abortStream: () => void;
  tts?: PetChatTtsOptions | null;
};

export type PetChatBubbleController = ReturnType<typeof usePetChatBubble>;

type RenderPageResult = "visible" | "pending" | false;

const ttsNextPagePlaybackDelayMs = 300;
const ambientBubbleMaxGraphemes = 28;

function normalizeAmbientBubbleText(text: string) {
  return text
    .replace(/[|｜]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function truncatePetBubbleGraphemes(text: string, maxGraphemes = ambientBubbleMaxGraphemes) {
  const graphemes = segmentPetBubbleText(text);
  if (graphemes.length <= maxGraphemes) {
    return text;
  }
  return `${graphemes.slice(0, maxGraphemes).join("").trimEnd()}…`;
}

function compactAmbientBubbleMessage(text: string, maxGraphemes = ambientBubbleMaxGraphemes) {
  const normalized = normalizeAmbientBubbleText(text);
  if (!normalized) {
    return "";
  }
  const firstPage = paginatePetBubbleReply(normalized)[0] || normalized;
  return truncatePetBubbleGraphemes(firstPage.replace(/[，,、；;：:\s]+$/u, ""), maxGraphemes);
}

function continuityPresenceMessage(signal: ChatContinuitySignal) {
  const summary = compactAmbientBubbleMessage(signal.summary, 24);
  if (summary) {
    return `下次可以接着聊：${summary}`;
  }
  return compactAmbientBubbleMessage(signal.display_hint, 28) || "刚才那个话题，下次也能接上。";
}

function continuityPresenceTitle(signal: ChatContinuitySignal) {
  if (signal.kind === "open_thread") {
    return "下次接着聊";
  }
  return signal.title || "陪伴状态已更新";
}

export function usePetChatBubble({
  messages,
  latestContinuitySignal,
  setMessages,
  setNotice,
  abortStream,
  tts = null,
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
  const assistantHiddenReplyTextsRef = useRef<string[]>([]);
  const assistantReplyFilterRef = useRef(createAssistantReplyTextFilter());
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
  const replyMessageIdRef = useRef<string | null>(null);
  const ttsRef = useRef<PetChatTtsOptions | null>(tts);
  const ttsEnabledRef = useRef(Boolean(tts?.enabled));
  const pendingTtsDisplayRef = useRef<{ itemId: string; pageIndex: number; phase: Extract<PetBubblePhase, "speaking" | "complete">; fallbackOnIdle?: boolean } | null>(null);
  const pendingTtsAutoAdvanceRef = useRef(false);
  const pendingTtsHideDelayRef = useRef<number | null>(null);
  const pendingTtsFallbackTimerRef = useRef<number | null>(null);
  const visibleTtsPageRef = useRef<{ itemId: string; pageIndex: number; autoAdvance: boolean; hideDelay: number | null } | null>(null);

  useEffect(() => {
    const wasEnabled = ttsEnabledRef.current;
    const isEnabled = Boolean(tts?.enabled);
    ttsRef.current = tts;
    ttsEnabledRef.current = isEnabled;
    if (!wasEnabled && isEnabled && startTtsForVisibleReplyPageAfterEnable()) {
      return;
    }
    if (wasEnabled && !isEnabled) {
      const visibleTtsPage = visibleTtsPageRef.current;
      visibleTtsPageRef.current = null;
      tts?.queue.clear("tts_disabled");
      if (showPendingTtsPageNow()) {
        return;
      }
      if (visibleTtsPage?.autoAdvance) {
        scheduleAutoAdvancePage();
      } else if (visibleTtsPage?.hideDelay !== null && visibleTtsPage?.hideDelay !== undefined) {
        scheduleHide(visibleTtsPage.hideDelay);
      }
    }
  }, [tts]);

  useEffect(() => {
    resolvePendingTtsDisplay(tts?.playbackState);
  }, [
    tts?.playbackState?.currentItem?.id,
    tts?.playbackState?.error?.itemId,
    tts?.playbackState?.status,
    tts?.playbackState?.updatedAt,
  ]);

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

  function clearPendingTtsFallbackTimer() {
    if (pendingTtsFallbackTimerRef.current !== null) {
      window.clearTimeout(pendingTtsFallbackTimerRef.current);
      pendingTtsFallbackTimerRef.current = null;
    }
  }

  function clearPendingTtsDisplay() {
    pendingTtsDisplayRef.current = null;
    pendingTtsAutoAdvanceRef.current = false;
    pendingTtsHideDelayRef.current = null;
    visibleTtsPageRef.current = null;
    clearPendingTtsFallbackTimer();
  }

  function hasStreamTerminalState() {
    return replyStartedRef.current || replyCompleteRef.current || streamFailedRef.current;
  }

  function showBubble(next: Omit<PetBubbleState, "visible" | "phase"> & { phase?: PetBubblePhase }) {
    clearHideTimer();
    const phase = next.phase || (next.tone === "reply" ? "speaking" : "thinking");
    const message = next.tone === "reply" ? next.message : compactAmbientBubbleMessage(next.message);
    setPetBubble({ ...next, message, phase, visible: true });
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
    const visibleText = stripAssistantHiddenReplyText(text);
    setPetReplyText(visibleText);
    setPetBubble({ visible: true, title: "", message: visibleText, tone: "reply", phase });
    followReplyToBottom();
  }

  function appendAssistantReplyText(text: string): string {
    const visibleText = assistantReplyFilterRef.current.append(text);
    const hiddenTexts = assistantReplyFilterRef.current.takeHiddenTexts();
    if (hiddenTexts.length > 0) {
      assistantHiddenReplyTextsRef.current = [...assistantHiddenReplyTextsRef.current, ...hiddenTexts];
    }
    if (!visibleText) {
      return "";
    }
    assistantReplyRef.current = normalizeVisibleAssistantReplyText(`${assistantReplyRef.current}${visibleText}`);
    return visibleText;
  }

  function setAssistantReplyText(text: string): string {
    assistantReplyFilterRef.current.reset();
    const { visibleText, hiddenTexts } = filterAssistantReplyText(text);
    assistantReplyRef.current = visibleText;
    assistantHiddenReplyTextsRef.current = hiddenTexts;
    return assistantReplyRef.current;
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
      const finalDelayMs = Math.max(0, petStreamFinalTimeoutMs - elapsedMs);
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
      title: continuityPresenceTitle(signal),
      message: continuityPresenceMessage(signal),
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

  function ttsItemForReplyPage(pageIndex: number): TtsPlaybackItem | null {
    const config = ttsRef.current;
    const pages = replyPagesRef.current;
    const text = pages[pageIndex] || "";
    if (!config?.enabled || !text.trim()) {
      return null;
    }
    const messageId = replyMessageIdRef.current || "pet-reply";
    return {
      id: `tts:${messageId}:${pageIndex}`,
      messageId,
      pageIndex,
      pageCount: pages.length,
      text,
      synthesis: {
        requestId: `tts:${messageId}:${pageIndex}`,
        text,
        provider: config.provider,
        voice: config.voice,
        speed: config.speed,
        volume: config.volume,
        cacheEnabled: config.cacheEnabled,
      },
    };
  }

  function stableTtsPageCount() {
    const pages = replyPagesRef.current;
    return replyCompleteRef.current ? pages.length : Math.max(0, pages.length - 1);
  }

  function isReplyPageStableForTts(pageIndex: number) {
    return pageIndex >= 0 && pageIndex < stableTtsPageCount();
  }

  function shouldAutoAdvanceTtsFromPage(pageIndex: number) {
    const nextIndex = pageIndex + 1;
    return nextIndex < replyPagesRef.current.length && isReplyPageStableForTts(nextIndex);
  }

  function setPendingTtsPageTiming(pageIndex: number) {
    pendingTtsAutoAdvanceRef.current = shouldAutoAdvanceTtsFromPage(pageIndex);
    pendingTtsHideDelayRef.current =
      replyCompleteRef.current && pageIndex >= replyPagesRef.current.length - 1 ? 9000 : null;
  }

  function prefetchTtsPagesFrom(pageIndex: number, lookahead = Number.POSITIVE_INFINITY) {
    const config = ttsRef.current;
    if (!config?.enabled || lookahead <= 0) {
      return;
    }
    const startIndex = Math.max(0, pageIndex);
    const endIndex = Math.min(stableTtsPageCount(), startIndex + lookahead);
    const items: TtsPlaybackItem[] = [];
    for (let index = startIndex; index < endIndex; index += 1) {
      const item = ttsItemForReplyPage(index);
      if (item) {
        items.push(item);
      }
    }
    if (items.length === 0) {
      return;
    }
    if (config.queue.prefetchMany) {
      config.queue.prefetchMany(items);
      return;
    }
    items.forEach((item) => config.queue.prefetch(item));
  }

  function prefetchStableTtsPagesDuringStream() {
    if (replyCompleteRef.current || replyPagingStartedRef.current || bubblePausedRef.current) {
      return;
    }
    const stablePageCount = Math.max(0, replyPagesRef.current.length - 1);
    if (stablePageCount <= 0) {
      return;
    }
    prefetchTtsPagesFrom(0, stablePageCount);
  }

  function startOrAdvanceStableTtsDuringStream(
    phase: Extract<PetBubblePhase, "speaking" | "complete"> = "speaking",
  ) {
    if (!ttsRef.current?.enabled || replyCompleteRef.current || bubblePausedRef.current) {
      return false;
    }
    const stableCount = stableTtsPageCount();
    if (stableCount <= 0) {
      return false;
    }
    if (pendingTtsDisplayRef.current) {
      prefetchTtsPagesFrom(replyPageIndexRef.current + 1);
      return true;
    }
    if (visibleTtsPageRef.current) {
      prepareNextTtsPageFromVisible(visibleTtsPageRef.current);
      return true;
    }

    const nextIndex = petBubble.tone === "reply" ? Math.min(replyPageIndexRef.current + 1, stableCount - 1) : 0;
    const renderResult = renderPage(nextIndex, phase, { playTts: true });
    if (renderResult !== "pending") {
      return false;
    }
    setPendingTtsPageTiming(nextIndex);
    return true;
  }

  function clearReplyTts(reason: string) {
    ttsRef.current?.queue.clear(reason);
  }

  function bubbleForReplyPage(
    pageIndex: number,
    phase: Extract<PetBubblePhase, "speaking" | "complete">,
  ): PetBubbleState {
    const pages = replyPagesRef.current;
    return {
      visible: true,
      title: "",
      message: pages[pageIndex] || "",
      tone: "reply",
      phase,
      continueHint: formatContinueHint(pageIndex, pages.length),
      canPageBackward: pages.length > 1 && pageIndex > 0,
      canPageForward: pages.length > 1 && pageIndex < pages.length - 1,
    };
  }

  function showReplyPage(
    pageIndex: number,
    phase: Extract<PetBubblePhase, "speaking" | "complete">,
  ) {
    clearHideTimer();
    setPetBubble(bubbleForReplyPage(pageIndex, phase));
  }

  function finishDisplayedPageTiming() {
    if (visibleTtsPageRef.current) {
      pendingTtsHideDelayRef.current = null;
      pendingTtsAutoAdvanceRef.current = false;
      return;
    }
    const pendingHideDelay = pendingTtsHideDelayRef.current;
    const shouldAutoAdvance = pendingTtsAutoAdvanceRef.current;
    pendingTtsHideDelayRef.current = null;
    pendingTtsAutoAdvanceRef.current = false;
    if (pendingHideDelay !== null) {
      scheduleHide(pendingHideDelay);
    }
    if (shouldAutoAdvance) {
      scheduleAutoAdvancePage();
    }
  }

  function showPendingTtsPageNow(options: { syncToPlayback?: boolean } = {}) {
    const pending = pendingTtsDisplayRef.current;
    if (!pending) {
      return false;
    }
    const pendingHideDelay = pendingTtsHideDelayRef.current;
    const shouldAutoAdvance = pendingTtsAutoAdvanceRef.current;
    pendingTtsDisplayRef.current = null;
    clearPendingTtsFallbackTimer();
    replyPageIndexRef.current = pending.pageIndex;
    showReplyPage(pending.pageIndex, pending.phase);
    if (options.syncToPlayback) {
      pendingTtsHideDelayRef.current = null;
      pendingTtsAutoAdvanceRef.current = false;
      visibleTtsPageRef.current = {
        itemId: pending.itemId,
        pageIndex: pending.pageIndex,
        autoAdvance: shouldAutoAdvance,
        hideDelay: pendingHideDelay,
      };
      prepareNextTtsPageFromVisible(visibleTtsPageRef.current);
      return true;
    }
    visibleTtsPageRef.current = null;
    finishDisplayedPageTiming();
    return true;
  }

  function resolvePendingTtsDisplay(state: TtsPlaybackState | undefined) {
    const pending = pendingTtsDisplayRef.current;
    if (!pending || !state) {
      return;
    }
    const isCurrentItem = state.currentItem?.id === pending.itemId;
    if (state.status === "playing" && isCurrentItem) {
      showPendingTtsPageNow({ syncToPlayback: true });
      return;
    }
    if (
      state.status === "failed" ||
      state.status === "cancelled" ||
      (state.status === "idle" && !isCurrentItem && pending.fallbackOnIdle !== false) ||
      state.error?.itemId === pending.itemId
    ) {
      showPendingTtsPageNow();
    }
  }

  function handleTtsPlaybackStart(item: TtsPlaybackItem) {
    const pending = pendingTtsDisplayRef.current;
    if (pending?.itemId === item.id) {
      showPendingTtsPageNow({ syncToPlayback: true });
      return;
    }
    const messageId = replyMessageIdRef.current || "pet-reply";
    if (
      !visibleTtsPageRef.current &&
      item.messageId === messageId &&
      item.pageIndex === replyPageIndexRef.current
    ) {
      clearPageTimer();
      clearHideTimer();
      visibleTtsPageRef.current = {
        itemId: item.id,
        pageIndex: item.pageIndex,
        autoAdvance: shouldAutoAdvanceTtsFromPage(item.pageIndex),
        hideDelay: replyCompleteRef.current && item.pageIndex >= replyPagesRef.current.length - 1 ? 9000 : null,
      };
      prepareNextTtsPageFromVisible(visibleTtsPageRef.current);
    }
  }

  function handleTtsPlaybackEnd(item: TtsPlaybackItem, status: TtsProviderPlaybackStatus) {
    const visible = visibleTtsPageRef.current;
    if (!visible || visible.itemId !== item.id) {
      return;
    }
    visibleTtsPageRef.current = null;
    if (status !== "played") {
      pendingTtsDisplayRef.current = null;
      pendingTtsAutoAdvanceRef.current = false;
      pendingTtsHideDelayRef.current = null;
      clearPendingTtsFallbackTimer();
      if (visible.hideDelay !== null) {
        scheduleHide(visible.hideDelay);
      }
      return;
    }
    if (visible.autoAdvance) {
      if (pendingTtsDisplayRef.current) {
        return;
      }
      clearPageTimer();
      pageTimerRef.current = window.setTimeout(() => {
        pageTimerRef.current = null;
        advanceToNextPageFromAuto();
      }, ttsNextPagePlaybackDelayMs);
      return;
    }
    if (visible.hideDelay !== null) {
      scheduleHide(0);
    }
  }

  function renderPage(
    pageIndex: number,
    phase: Extract<PetBubblePhase, "speaking" | "complete"> = "speaking",
    options: { playTts?: boolean } = {},
  ): RenderPageResult {
    const pages = replyPagesRef.current;
    if (pages.length === 0) {
      return false;
    }
    const safeIndex = Math.max(0, Math.min(pageIndex, pages.length - 1));
    replyPageIndexRef.current = safeIndex;
    pendingTtsDisplayRef.current = null;
    pendingTtsAutoAdvanceRef.current = false;
    pendingTtsHideDelayRef.current = null;
    visibleTtsPageRef.current = null;
    clearPendingTtsFallbackTimer();
    if (options.playTts) {
      const item = ttsItemForReplyPage(safeIndex);
      if (item && ttsRef.current?.enabled) {
        pendingTtsDisplayRef.current = { itemId: item.id, pageIndex: safeIndex, phase, fallbackOnIdle: true };
        ttsRef.current.queue.play(item);
        prefetchTtsPagesFrom(safeIndex + 1);
        return "pending";
      }
    }
    showReplyPage(safeIndex, phase);
    return "visible";
  }

  function startTtsForVisibleReplyPageAfterEnable() {
    if (
      !replyCompleteRef.current ||
      replyPagesRef.current.length === 0 ||
      petBubble.tone !== "reply" ||
      petBubble.phase === "fading" ||
      bubblePausedRef.current
    ) {
      return false;
    }
    const pageIndex = Math.min(replyPageIndexRef.current, replyPagesRef.current.length - 1);
    const phase = petBubble.phase === "complete" ? "complete" : "speaking";
    const renderResult = renderPage(pageIndex, phase, {
      playTts: true,
    });
    if (renderResult !== "pending") {
      return false;
    }
    setPendingTtsPageTiming(pageIndex);
    return true;
  }

  function prepareNextTtsPageFromVisible(
    visible: { itemId: string; pageIndex: number; autoAdvance: boolean; hideDelay: number | null } | null,
  ) {
    if (!visible?.autoAdvance || bubblePausedRef.current) {
      return;
    }
    const pages = replyPagesRef.current;
    const nextIndex = visible.pageIndex + 1;
    if (nextIndex >= pages.length) {
      return;
    }
    if (!isReplyPageStableForTts(nextIndex)) {
      return;
    }
    prefetchTtsPagesFrom(nextIndex);
  }

  function advanceToNextPageFromAuto() {
    if (bubblePausedRef.current) {
      return;
    }
    const latestPages = replyPagesRef.current;
    if (latestPages.length <= 1 || replyPageIndexRef.current >= latestPages.length - 1) {
      if (replyCompleteRef.current) {
        scheduleHide(9000);
      }
      return;
    }
    const nextIndex = Math.min(replyPageIndexRef.current + 1, latestPages.length - 1);
    if (ttsRef.current?.enabled && !isReplyPageStableForTts(nextIndex)) {
      return;
    }
    const renderResult = renderPage(nextIndex, replyCompleteRef.current ? "complete" : "speaking", { playTts: true });
    if (renderResult === "pending") {
      setPendingTtsPageTiming(nextIndex);
      return;
    }
    scheduleAutoAdvancePage();
  }

  function scheduleAutoAdvancePage() {
    clearPageTimer();
    const pages = replyPagesRef.current;
    const pageIndex = replyPageIndexRef.current;
    if (bubblePausedRef.current || pages.length <= 1) {
      return;
    }
    if (pageIndex >= pages.length - 1) {
      if (replyCompleteRef.current) {
        scheduleHide(9000);
      }
      return;
    }
    if (visibleTtsPageRef.current?.autoAdvance && visibleTtsPageRef.current.pageIndex === pageIndex) {
      return;
    }

    pageTimerRef.current = window.setTimeout(() => {
      pageTimerRef.current = null;
      advanceToNextPageFromAuto();
    }, getPetBubblePageDelay(pages[pageIndex]));
  }

  function setReplyPagesFromText(
    text: string,
    options: {
      preserveCurrentPage?: boolean;
      phase?: Extract<PetBubblePhase, "speaking" | "complete">;
      renderDuringStream?: boolean;
    } = {},
  ) {
    const pages = paginatePetBubbleReply(text);
    replyPagesRef.current = pages;
    setPetReplyText(text);
    if (!replyCompleteRef.current && !options.renderDuringStream) {
      prefetchStableTtsPagesDuringStream();
    }
    clearHideTimer();
    if (pages.length === 0) {
      setPetBubble({ visible: false, title: "", message: "", tone: "reply", phase: "idle" });
      return;
    }
    if (ttsRef.current?.enabled && !replyCompleteRef.current) {
      startOrAdvanceStableTtsDuringStream(options.phase || "speaking");
      return;
    }

    const nextIndex = options.preserveCurrentPage
      ? Math.min(replyPageIndexRef.current, pages.length - 1)
      : 0;
    renderPage(nextIndex, options.phase || "speaking");
  }

  function startReplyPaging(messageId?: string) {
    if (replyPagingStartedRef.current) {
      return;
    }
    if (messageId) {
      replyMessageIdRef.current = messageId;
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
      clearReplyTts("empty_reply");
      scheduleHide(6000);
      return;
    }

    const safeIndex = Math.min(replyPageIndexRef.current, pages.length - 1);
    if (ttsRef.current?.enabled) {
      const pending = pendingTtsDisplayRef.current;
      const visible = visibleTtsPageRef.current;
      if (pending?.pageIndex === safeIndex) {
        pendingTtsAutoAdvanceRef.current = shouldAutoAdvanceTtsFromPage(safeIndex);
        pendingTtsHideDelayRef.current = safeIndex >= pages.length - 1 ? 9000 : null;
        prefetchTtsPagesFrom(safeIndex + 1);
        return;
      }
      if (visible?.pageIndex === safeIndex) {
        visible.autoAdvance = shouldAutoAdvanceTtsFromPage(safeIndex);
        visible.hideDelay = safeIndex >= pages.length - 1 ? 9000 : null;
        prepareNextTtsPageFromVisible(visible);
        return;
      }
      if (petBubble.tone === "reply" && safeIndex < pages.length - 1) {
        const nextIndex = safeIndex + 1;
        const nextRenderResult = renderPage(nextIndex, "complete", { playTts: true });
        if (nextRenderResult === "pending") {
          setPendingTtsPageTiming(nextIndex);
          return;
        }
      }
    }
    const renderResult = renderPage(safeIndex, "complete", { playTts: true });
    if (pages.length === 1) {
      if (renderResult === "pending") {
        pendingTtsHideDelayRef.current = 9000;
      } else {
        scheduleHide(9000);
      }
    } else {
      if (renderResult === "pending") {
        setPendingTtsPageTiming(safeIndex);
      } else {
        scheduleAutoAdvancePage();
      }
    }
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
    clearPendingTtsDisplay();
    clearReplyTts("stream_failed");
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
      ? "这次没有收到可显示的回复。"
      : "这次没有收到回复。";
    failStream(messageId, "没有收到回复", message);
  }

  function advancePageManually() {
    const pages = replyPagesRef.current;
    if (pages.length <= 1 || petBubble.tone !== "reply") {
      return;
    }
    clearPageTimer();
    const nextIndex = Math.min(replyPageIndexRef.current + 1, pages.length - 1);
    const renderResult = renderPage(nextIndex, replyCompleteRef.current ? "complete" : "speaking", { playTts: true });
    if (nextIndex >= pages.length - 1) {
      if (replyCompleteRef.current && !bubblePausedRef.current) {
        if (renderResult === "pending") {
          pendingTtsHideDelayRef.current = 9000;
        } else {
          scheduleHide(9000);
        }
      }
      return;
    }
    if (renderResult === "pending") {
      pendingTtsAutoAdvanceRef.current = shouldAutoAdvanceTtsFromPage(nextIndex);
    } else {
      scheduleAutoAdvancePage();
    }
  }

  function retreatPageManually() {
    const pages = replyPagesRef.current;
    if (pages.length <= 1 || petBubble.tone !== "reply") {
      return;
    }
    clearPageTimer();
    const previousIndex = Math.max(replyPageIndexRef.current - 1, 0);
    const renderResult = renderPage(previousIndex, replyCompleteRef.current ? "complete" : "speaking", { playTts: true });
    if (renderResult === "pending") {
      pendingTtsAutoAdvanceRef.current = shouldAutoAdvanceTtsFromPage(previousIndex);
    } else {
      scheduleAutoAdvancePage();
    }
  }

  function pausePaging() {
    bubblePausedRef.current = true;
    userIsReadingRef.current = true;
    clearPageTimer();
    clearHideTimer();
    clearPendingTtsDisplay();
    clearReplyTts("user_paused_reading");
  }

  function resumePaging() {
    bubblePausedRef.current = false;
    userIsReadingRef.current = false;
    const pages = replyPagesRef.current;
    if (replyCompleteRef.current && petBubble.tone === "reply" && replyPageIndexRef.current >= pages.length - 1) {
      scheduleHide(9000);
      return;
    }
    if (petBubble.tone === "reply") {
      scheduleAutoAdvancePage();
    }
  }

  function showInput() {
    setPetInputVisible(true);
    window.requestAnimationFrame(() => petInputRef.current?.focus());
  }

  function resetStreamState(messageId?: string) {
    assistantReplyRef.current = "";
    assistantHiddenReplyTextsRef.current = [];
    assistantReplyFilterRef.current.reset();
    replyStartedRef.current = false;
    replyCompleteRef.current = false;
    replyPagesRef.current = [];
    replyPageIndexRef.current = 0;
    replyMessageIdRef.current = messageId || null;
    replyPagingStartedRef.current = false;
    bubblePausedRef.current = false;
    streamOpenedRef.current = false;
    streamReceivedEventRef.current = false;
    streamFailedRef.current = false;
    streamStartedAtRef.current = Date.now();
    latestContinuitySignalRef.current = null;
    clearPageTimer();
    clearStreamWatchdogTimer();
    clearPendingTtsDisplay();
    clearReplyTts("new_reply");
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
      clearPendingTtsDisplay();
    };
  }, []);

  return {
    assistantReplyRef,
    assistantHiddenReplyTextsRef,
    appendAssistantReplyText,
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
    handleTtsPlaybackStart,
    handleTtsPlaybackEnd,
    markStreamEventReceived,
    resetStreamState,
    scheduleHide,
    scheduleStreamWatchdog,
    setInput: setPetInput,
    setAssistantReplyText,
    setInputVisible: setPetInputVisible,
    setReplyPagesFromText,
    showBubble,
    showContinuityPresenceBubble,
    showInput,
    showReaction,
    showReply,
    startReplyPaging,
    advancePageManually,
    retreatPageManually,
    pausePaging,
    resumePaging,
    latestContinuitySignalForMessage,
    replyPagesRef,
  };
}
