import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Dispatch, SetStateAction } from "react";
import type { ChatMessage, TtsPlaybackItem } from "../../types";
import { getPetBubblePageDelay } from "../../services/petBubblePagination";
import { usePetChatBubble } from "./usePetChatBubble";
import type { TtsPlaybackQueueController } from "../tts";

function createTtsQueueMock(): TtsPlaybackQueueController {
  const queue: TtsPlaybackQueueController = {
    state: {
      status: "idle",
      currentItem: null,
      queue: [],
      error: null,
      volume: 1,
      updatedAt: "2026-06-04T00:00:00.000Z",
    },
    enqueue: vi.fn(),
    prefetch: vi.fn(),
    prefetchMany: vi.fn(),
    play: vi.fn(),
    stop: vi.fn(),
    cancelMessage: vi.fn(),
    clear: vi.fn(),
    setVolume: vi.fn(),
  };
  return queue;
}

function renderPetChatBubbleHook(tts?: TtsPlaybackQueueController | null) {
  return renderHook(() =>
    usePetChatBubble({
      messages: [],
      latestContinuitySignal: null,
      setMessages: vi.fn() as Dispatch<SetStateAction<ChatMessage[]>>,
      setNotice: vi.fn(),
      abortStream: vi.fn(),
      tts: tts
        ? {
            enabled: true,
            queue: tts,
            provider: "mock",
            voice: null,
            speed: 1.2,
            volume: 0.6,
            cacheEnabled: true,
          }
        : null,
    }),
  );
}

function renderPetChatBubbleHookWithTtsEnabled(
  initial: { queue: TtsPlaybackQueueController | null; enabled: boolean },
) {
  return renderHook(
    ({ queue, enabled }: { queue: TtsPlaybackQueueController | null; enabled: boolean }) =>
      usePetChatBubble({
        messages: [],
        latestContinuitySignal: null,
        setMessages: vi.fn() as Dispatch<SetStateAction<ChatMessage[]>>,
        setNotice: vi.fn(),
        abortStream: vi.fn(),
        tts: queue
          ? {
              enabled,
              queue,
              provider: "mock",
              voice: null,
              speed: 1.2,
              volume: 0.6,
              cacheEnabled: true,
            }
          : null,
      }),
    { initialProps: initial },
  );
}

const multiPageReply =
  "First I will keep this reply moving like spoken dialogue. Then I will continue with the next thought after a short pause. Finally I will wrap it up naturally.";
const twoPageReply =
  "First I will keep this reply moving like spoken dialogue. Then I will wrap it up naturally.";
const longMultiPageReply = [
  "First I will open the story with a calm scene, so the first page has enough detail to stand on its own.",
  "Then the character notices a small clue on the table, and the next thought should already be ready to speak.",
  "After that the room changes, the wind rises, and the page should turn only when the current voice has finished.",
  "Finally the ending lands softly, with no long silent gap between one spoken piece and the next.",
].join(" ");

describe("usePetChatBubble", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("auto-advances multi-page replies like speech playback", () => {
    const { result } = renderPetChatBubbleHook();
    const longReply =
      "你好，我会先陪你把今天的想法慢慢摊开。然后我们可以一起挑出最重要的线索和下一步。你不用急，想到哪里就先说到哪里。最后我会把能沉淀的内容整理成清楚的小结。";

    act(() => {
      result.current.assistantReplyRef.current = longReply;
      result.current.startReplyPaging();
    });

    const firstPage = result.current.bubble.message;
    expect(result.current.replyText).toBe(longReply);
    expect(result.current.bubble.continueHint).toMatch(/^1\/\d+$/);
    expect(result.current.bubble.canPageBackward).toBe(false);
    expect(result.current.bubble.canPageForward).toBe(true);

    act(() => {
      vi.advanceTimersByTime(getPetBubblePageDelay(firstPage));
    });

    expect(result.current.bubble.message).not.toBe(firstPage);
    expect(result.current.bubble.canPageBackward).toBe(true);

    act(() => {
      result.current.retreatPageManually();
    });

    expect(result.current.bubble.message).toBe(firstPage);
    expect(result.current.bubble.canPageBackward).toBe(false);
  });

  it("pauses automatic paging while the user is reading", () => {
    const { result } = renderPetChatBubbleHook();

    act(() => {
      result.current.assistantReplyRef.current = multiPageReply;
      result.current.startReplyPaging();
    });

    const firstPage = result.current.bubble.message;

    act(() => {
      result.current.pausePaging();
      vi.advanceTimersByTime(getPetBubblePageDelay(firstPage) * 2);
    });

    expect(result.current.bubble.message).toBe(firstPage);

    act(() => {
      result.current.resumePaging();
      vi.advanceTimersByTime(getPetBubblePageDelay(firstPage));
    });

    expect(result.current.bubble.message).not.toBe(firstPage);
  });

  it("keeps short replies on a single page and hides them after the read delay", () => {
    const { result } = renderPetChatBubbleHook();

    act(() => {
      result.current.assistantReplyRef.current = "你好呀，我在。";
      result.current.startReplyPaging();
    });

    expect(result.current.bubble.message).toBe("你好呀，我在。");
    expect(result.current.bubble.continueHint).toBeUndefined();
    expect(result.current.bubble.visible).toBe(true);

    act(() => {
      vi.advanceTimersByTime(9000);
    });

    expect(result.current.bubble.visible).toBe(false);
    expect(result.current.bubble.phase).toBe("fading");
  });

  it("starts stable streamed reply pages through TTS and shows text on playback start", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.resetStreamState("assistant-1");
      result.current.assistantReplyRef.current = multiPageReply;
      result.current.setReplyPagesFromText(multiPageReply);
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.tone).toBe("thinking");

    act(() => {
      result.current.startReplyPaging("assistant-1");
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    const firstItem = vi.mocked(tts.play).mock.calls[0][0] as TtsPlaybackItem;
    expect(firstItem).toMatchObject({
      id: "tts:assistant-1:0",
      messageId: "assistant-1",
      pageIndex: 0,
      synthesis: {
        requestId: "tts:assistant-1:0",
        provider: "mock",
        speed: 1.2,
        volume: 0.6,
        cacheEnabled: true,
      },
    });
    expect(result.current.bubble.tone).toBe("thinking");
    expect(tts.enqueue).not.toHaveBeenCalled();

    act(() => {
      result.current.handleTtsPlaybackStart(firstItem);
    });

    expect(result.current.bubble.message).toBe(firstItem.text);
    expect(tts.enqueue).not.toHaveBeenCalled();
    expect(tts.prefetchMany).toHaveBeenCalled();
    const prefetchedPageIndexes = vi.mocked(tts.prefetchMany).mock.calls.flatMap(([items]) =>
      items.map((item) => item.pageIndex),
    );
    expect(prefetchedPageIndexes).toContain(1);

    act(() => {
      vi.advanceTimersByTime(getPetBubblePageDelay(firstItem.text));
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      result.current.handleTtsPlaybackEnd(firstItem, "played");
      vi.advanceTimersByTime(299);
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(tts.play).toHaveBeenCalledTimes(2);
    const secondItem = vi.mocked(tts.play).mock.calls[1][0] as TtsPlaybackItem;
    expect(secondItem.messageId).toBe("assistant-1");
    expect(secondItem.pageIndex).toBe(1);
    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      result.current.handleTtsPlaybackStart(secondItem);
    });

    expect(secondItem.text).toBe(result.current.bubble.message);
  });

  it("prefetches all remaining TTS pages when a long final reply starts", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.assistantReplyRef.current = longMultiPageReply;
      result.current.startReplyPaging("assistant-lookahead");
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    const prefetchedPageIndexes = vi.mocked(tts.prefetchMany).mock.calls.flatMap(([items]) =>
      items.map((item) => item.pageIndex),
    );
    expect(prefetchedPageIndexes).toEqual(
      Array.from({ length: result.current.replyPagesRef.current.length - 1 }, (_, index) => index + 1),
    );
  });

  it("starts and prefetches stable TTS pages while a long reply is still streaming", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.resetStreamState("assistant-streaming");
      result.current.assistantReplyRef.current = longMultiPageReply;
      result.current.setReplyPagesFromText(longMultiPageReply);
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(tts.enqueue).not.toHaveBeenCalled();
    expect(tts.prefetchMany).toHaveBeenCalled();
    expect(result.current.bubble.tone).toBe("thinking");
    const firstPlaybackItem = vi.mocked(tts.play).mock.calls[0][0] as TtsPlaybackItem;
    expect(firstPlaybackItem).toMatchObject({
      id: "tts:assistant-streaming:0",
      messageId: "assistant-streaming",
      pageIndex: 0,
    });

    act(() => {
      result.current.handleTtsPlaybackStart(firstPlaybackItem);
    });

    expect(result.current.bubble.tone).toBe("reply");
    expect(result.current.bubble.message).toBe(firstPlaybackItem.text);
  });

  it("shows streamed reply text in the bubble before the final reply is ready", () => {
    const { result } = renderPetChatBubbleHook();

    act(() => {
      result.current.showBubble({
        title: "",
        message: "我先看一下。",
        tone: "thinking",
      });
      result.current.assistantReplyRef.current = "Streaming answer text.";
      result.current.setReplyPagesFromText(result.current.assistantReplyRef.current);
    });

    expect(result.current.replyText).toBe("Streaming answer text.");
    expect(result.current.bubble.tone).toBe("reply");
    expect(result.current.bubble.message).toBe("Streaming answer text.");

    act(() => {
      result.current.startReplyPaging("assistant-final");
    });

    expect(result.current.bubble.tone).toBe("reply");
    expect(result.current.bubble.message).toBe("Streaming answer text.");
  });

  it("waits for TTS playback to finish before turning the page", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.assistantReplyRef.current = multiPageReply;
      result.current.startReplyPaging("assistant-no-cutoff");
    });

    const firstItem = vi.mocked(tts.play).mock.calls[0][0] as TtsPlaybackItem;

    act(() => {
      result.current.handleTtsPlaybackStart(firstItem);
      vi.advanceTimersByTime(getPetBubblePageDelay(firstItem.text) * 3);
    });

    expect(tts.enqueue).not.toHaveBeenCalled();
    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      result.current.handleTtsPlaybackEnd(firstItem, "cancelled");
      vi.advanceTimersByTime(getPetBubblePageDelay(firstItem.text) * 3);
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.message).toBe(firstItem.text);
  });

  it("does not show the next TTS page until its playback starts", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.assistantReplyRef.current = twoPageReply;
      result.current.startReplyPaging("assistant-catchup");
    });

    const firstItem = vi.mocked(tts.play).mock.calls[0][0] as TtsPlaybackItem;

    act(() => {
      result.current.handleTtsPlaybackStart(firstItem);
    });

    act(() => {
      result.current.handleTtsPlaybackEnd(firstItem, "played");
      vi.advanceTimersByTime(299);
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(tts.play).toHaveBeenCalledTimes(2);
    const secondItem = vi.mocked(tts.play).mock.calls[1][0] as TtsPlaybackItem;
    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      result.current.handleTtsPlaybackStart(secondItem);
    });

    expect(result.current.bubble.message).toBe(secondItem.text);

    act(() => {
      result.current.handleTtsPlaybackEnd(secondItem, "played");
      vi.advanceTimersByTime(0);
    });

    expect(result.current.bubble.visible).toBe(false);
    expect(result.current.bubble.phase).toBe("fading");
  });

  it("waits to show the final TTS reply page until voice playback starts", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.assistantReplyRef.current = "The text is ready before the voice.";
      result.current.setReplyPagesFromText(result.current.assistantReplyRef.current);
    });

    expect(result.current.replyText).toBe("The text is ready before the voice.");
    expect(result.current.bubble.tone).toBe("thinking");

    act(() => {
      result.current.startReplyPaging("assistant-sync");
    });

    const item = vi.mocked(tts.play).mock.calls[0][0] as TtsPlaybackItem;
    expect(result.current.bubble.tone).toBe("thinking");

    act(() => {
      result.current.handleTtsPlaybackStart(item);
    });

    expect(result.current.bubble.message).toBe(item.text);
  });

  it("starts TTS for an already visible reply when voice becomes ready late", () => {
    const tts = createTtsQueueMock();
    const { result, rerender } = renderPetChatBubbleHookWithTtsEnabled({
      queue: tts,
      enabled: false,
    });

    act(() => {
      result.current.assistantReplyRef.current = "The reply was visible before voice became ready.";
      result.current.startReplyPaging("assistant-late-tts");
    });

    expect(result.current.bubble.message).toBe("The reply was visible before voice became ready.");
    expect(tts.play).not.toHaveBeenCalled();

    act(() => {
      rerender({ queue: tts, enabled: true });
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    const item = vi.mocked(tts.play).mock.calls[0][0] as TtsPlaybackItem;
    expect(item).toMatchObject({
      id: "tts:assistant-late-tts:0",
      messageId: "assistant-late-tts",
      pageIndex: 0,
    });
    expect(result.current.bubble.message).toBe(item.text);
  });

  it("hides the final TTS page as soon as playback finishes", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.assistantReplyRef.current = "The last page should close after voice.";
      result.current.startReplyPaging("assistant-final-tts");
    });

    const item = vi.mocked(tts.play).mock.calls[0][0] as TtsPlaybackItem;

    act(() => {
      result.current.handleTtsPlaybackStart(item);
      result.current.handleTtsPlaybackEnd(item, "played");
      vi.advanceTimersByTime(0);
    });

    expect(result.current.bubble.visible).toBe(false);
    expect(result.current.bubble.phase).toBe("fading");
  });

  it("clears current and queued TTS when paging is paused and clears it on reset", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.assistantReplyRef.current = multiPageReply;
      result.current.startReplyPaging("assistant-2");
      result.current.pausePaging();
    });

    expect(tts.clear).toHaveBeenCalledWith("user_paused_reading");

    act(() => {
      result.current.resetStreamState();
    });

    expect(tts.clear).toHaveBeenCalledWith("new_reply");
  });
});
