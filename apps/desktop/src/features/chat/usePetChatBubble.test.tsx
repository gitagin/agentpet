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

const multiPageReply =
  "First I will keep this reply moving like spoken dialogue. Then I will continue with the next thought after a short pause. Finally I will wrap it up naturally.";

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

  it("plays only final reply pages through TTS", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.assistantReplyRef.current = multiPageReply;
      result.current.setReplyPagesFromText(multiPageReply);
    });

    expect(tts.play).not.toHaveBeenCalled();

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
    expect(result.current.bubble.message).not.toBe(firstItem.text);

    act(() => {
      result.current.handleTtsPlaybackStart(firstItem);
    });

    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      vi.advanceTimersByTime(getPetBubblePageDelay(firstItem.text));
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      result.current.handleTtsPlaybackEnd(firstItem, "played");
      vi.advanceTimersByTime(250);
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

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.message).toBe(firstItem.text);

    act(() => {
      result.current.handleTtsPlaybackEnd(firstItem, "cancelled");
      vi.advanceTimersByTime(getPetBubblePageDelay(firstItem.text) * 3);
    });

    expect(tts.play).toHaveBeenCalledTimes(1);
    expect(result.current.bubble.message).toBe(firstItem.text);
  });

  it("keeps streamed reply text out of the bubble until TTS playback starts", () => {
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
    expect(result.current.bubble.message).not.toBe(item.text);

    act(() => {
      result.current.handleTtsPlaybackStart(item);
    });

    expect(result.current.bubble.message).toBe(item.text);
  });

  it("stops current TTS when paging is paused and clears it on reset", () => {
    const tts = createTtsQueueMock();
    const { result } = renderPetChatBubbleHook(tts);

    act(() => {
      result.current.assistantReplyRef.current = multiPageReply;
      result.current.startReplyPaging("assistant-2");
      result.current.pausePaging();
    });

    expect(tts.stop).toHaveBeenCalledWith("user_paused_reading");

    act(() => {
      result.current.resetStreamState();
    });

    expect(tts.clear).toHaveBeenCalledWith("new_reply");
  });
});
