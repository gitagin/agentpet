import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Dispatch, SetStateAction } from "react";
import type { ChatMessage } from "../../types";
import { getPetBubblePageDelay } from "../../services/petBubblePagination";
import { usePetChatBubble } from "./usePetChatBubble";

function renderPetChatBubbleHook() {
  return renderHook(() =>
    usePetChatBubble({
      messages: [],
      latestContinuitySignal: null,
      setMessages: vi.fn() as Dispatch<SetStateAction<ChatMessage[]>>,
      setNotice: vi.fn(),
      abortStream: vi.fn(),
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
});
