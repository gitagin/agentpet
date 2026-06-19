import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TtsPlaybackItem, TtsSynthesisRequest, TtsSynthesisResult } from "./ttsTypes";
import {
  createTtsProviderError,
  type TtsProvider,
  type TtsProviderPlaybackOptions,
  type TtsProviderPlaybackResult,
} from "./ttsProvider";
import { useTtsPlaybackQueue } from "./useTtsPlaybackQueue";

type ControlledPlayback = {
  result: TtsSynthesisResult;
  resolve: (value: TtsProviderPlaybackResult) => void;
  settled: boolean;
};

function playbackItem(
  id: string,
  overrides: Partial<Pick<TtsPlaybackItem, "messageId" | "pageIndex" | "pageCount" | "text">> = {},
): TtsPlaybackItem {
  const text = overrides.text ?? `reply page ${id}`;
  return {
    id,
    messageId: overrides.messageId ?? "message-1",
    pageIndex: overrides.pageIndex ?? 0,
    pageCount: overrides.pageCount ?? 1,
    text,
    synthesis: {
      requestId: `request-${id}`,
      text,
      provider: "mock",
      voice: null,
      speed: 1,
      volume: 1,
    },
  };
}

function createControlledProvider(failRequestIds: string[] = []) {
  const activePlaybacks: ControlledPlayback[] = [];
  const failedRequests = new Set(failRequestIds);

  function settle(playback: ControlledPlayback, status: "played" | "cancelled", reason?: string) {
    if (playback.settled) {
      return;
    }
    playback.settled = true;
    playback.resolve({
      provider: "mock",
      result: playback.result,
      status,
      reason,
    });
  }

  const synthesize = vi.fn(
    async (request: TtsSynthesisRequest, signal?: AbortSignal): Promise<TtsSynthesisResult> => {
      if (signal?.aborted) {
        throw createTtsProviderError("mock", "cancelled", "cancelled");
      }
      if (failedRequests.has(request.requestId)) {
        throw createTtsProviderError("mock", "provider_failed", "synthesis failed");
      }
      return {
        kind: "mock",
        requestId: request.requestId,
        provider: "mock",
        durationMs: 100,
      };
    },
  );
  const play = vi.fn(
    (result: TtsSynthesisResult, options?: TtsProviderPlaybackOptions): Promise<TtsProviderPlaybackResult> =>
      new Promise((resolve) => {
        const playback: ControlledPlayback = {
          result,
          resolve,
          settled: false,
        };
        activePlaybacks.push(playback);
        options?.signal?.addEventListener("abort", () => settle(playback, "cancelled", "aborted"), { once: true });
      }),
  );
  const stop = vi.fn((reason = "stopped") => {
    const playback = activePlaybacks.find((item) => !item.settled);
    if (playback) {
      settle(playback, "cancelled", reason);
    }
  });
  const provider: TtsProvider<TtsSynthesisResult> = {
    id: "mock",
    synthesize,
    play,
    stop,
  };

  return {
    activePlaybacks,
    provider,
    play,
    stop,
    synthesize,
    completeNext: () => {
      const playback = activePlaybacks.find((item) => !item.settled);
      if (!playback) {
        throw new Error("No active playback to complete.");
      }
      settle(playback, "played");
    },
  };
}

function createProviderThatFailsFirstRequest(requestId: string) {
  const controlled = createControlledProvider();
  let failed = false;
  controlled.synthesize.mockImplementation(
    async (request: TtsSynthesisRequest, signal?: AbortSignal): Promise<TtsSynthesisResult> => {
      if (signal?.aborted) {
        throw createTtsProviderError("mock", "cancelled", "cancelled");
      }
      if (request.requestId === requestId && !failed) {
        failed = true;
        throw createTtsProviderError("mock", "provider_failed", "transient synthesis failed");
      }
      return {
        kind: "mock",
        requestId: request.requestId,
        provider: "mock",
        durationMs: 100,
      };
    },
  );
  return controlled;
}

function createDeferredSynthesisProvider() {
  const requests: Array<{
    request: TtsSynthesisRequest;
    resolve: (result: TtsSynthesisResult) => void;
  }> = [];
  const synthesize = vi.fn(
    (request: TtsSynthesisRequest, signal?: AbortSignal): Promise<TtsSynthesisResult> =>
      new Promise((resolve, reject) => {
        if (signal?.aborted) {
          reject(createTtsProviderError("mock", "cancelled", "cancelled"));
          return;
        }
        signal?.addEventListener(
          "abort",
          () => reject(createTtsProviderError("mock", "cancelled", "cancelled")),
          { once: true },
        );
        requests.push({ request, resolve });
      }),
  );
  const play = vi.fn(
    (result: TtsSynthesisResult): Promise<TtsProviderPlaybackResult> =>
      Promise.resolve({
        provider: "mock",
        result,
        status: "played",
      }),
  );
  const provider: TtsProvider<TtsSynthesisResult> = {
    id: "mock",
    synthesize,
    play,
    stop: vi.fn(),
  };

  return {
    provider,
    requests,
    synthesize,
    resolveRequest(index: number) {
      const request = requests[index]?.request;
      if (!request) {
        throw new Error(`No synthesis request at index ${index}.`);
      }
      requests[index].resolve({
        kind: "mock",
        requestId: request.requestId,
        provider: "mock",
        durationMs: 100,
      });
    },
  };
}

function renderQueue(
  provider: TtsProvider<TtsSynthesisResult>,
  options: {
    onPlaybackStart?: (item: TtsPlaybackItem) => void;
    onPlaybackEnd?: (item: TtsPlaybackItem, status: TtsProviderPlaybackResult["status"]) => void;
  } = {},
) {
  return renderHook(() =>
    useTtsPlaybackQueue({
      providers: { mock: provider },
      initialVolume: 0.5,
      now: () => "2026-06-04T00:00:00.000Z",
      onPlaybackStart: options.onPlaybackStart,
      onPlaybackEnd: options.onPlaybackEnd,
    }),
  );
}

function createImmediateProvider(providerId: string, failCode?: "authentication_failed" | "provider_failed") {
  const synthesize = vi.fn(async (request: TtsSynthesisRequest): Promise<TtsSynthesisResult> => {
    if (failCode) {
      throw createTtsProviderError(providerId, failCode, failCode === "authentication_failed" ? "Invalid API Key" : "failed");
    }
    return {
      kind: "mock",
      requestId: request.requestId,
      provider: "mock",
      durationMs: 100,
    };
  });
  const play = vi.fn(
    async (result: TtsSynthesisResult): Promise<TtsProviderPlaybackResult> => ({
      provider: providerId,
      result,
      status: "played",
    }),
  );
  const provider: TtsProvider<TtsSynthesisResult> = {
    id: providerId,
    synthesize,
    play,
    stop: vi.fn(),
  };
  return { play, provider, synthesize };
}

function playbackItemForProvider(id: string, provider: string): TtsPlaybackItem {
  const item = playbackItem(id);
  return {
    ...item,
    synthesis: {
      ...item.synthesis,
      provider,
      requestId: `request-${provider}-${id}`,
    },
  };
}

async function finishCurrentPlayback(complete: () => void) {
  await act(async () => {
    complete();
    await Promise.resolve();
  });
}

describe("useTtsPlaybackQueue", () => {
  it("plays enqueued items one at a time and ignores duplicate items", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);
    const first = playbackItem("page-1");
    const second = playbackItem("page-2", { pageIndex: 1, pageCount: 2 });

    act(() => {
      result.current.enqueue(first);
      result.current.enqueue(second);
      result.current.enqueue(first);
    });

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("page-1"));
    expect(result.current.state.queue.map((item) => item.id)).toEqual(["page-2"]);
    expect(controlled.play).toHaveBeenCalledTimes(1);

    await finishCurrentPlayback(controlled.completeNext);

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("page-2"));
    expect(result.current.state.queue).toEqual([]);
    expect(controlled.play).toHaveBeenCalledTimes(2);

    await finishCurrentPlayback(controlled.completeNext);

    await waitFor(() => expect(result.current.state.status).toBe("idle"));
    expect(result.current.state.currentItem).toBeNull();
    expect(result.current.state.queue).toEqual([]);
  });

  it("replaces stale page audio when play is called directly", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);
    const currentPage = playbackItem("page-1", { pageIndex: 0, pageCount: 3 });
    const stalePage = playbackItem("page-2", { pageIndex: 1, pageCount: 3 });
    const targetPage = playbackItem("page-3", { pageIndex: 2, pageCount: 3 });

    act(() => {
      result.current.enqueue(currentPage);
      result.current.enqueue(stalePage);
    });
    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("page-1"));

    act(() => {
      result.current.play(targetPage);
    });

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("page-3"));
    expect(result.current.state.queue).toEqual([]);
    expect(controlled.stop).toHaveBeenCalledWith("replaced");
    expect(controlled.synthesize.mock.calls.map(([request]) => request.requestId)).toEqual([
      "request-page-1",
      "request-page-2",
      "request-page-3",
    ]);
  });

  it("prefetches queued synthesis without interrupting current playback", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);
    const first = playbackItem("page-1");
    const second = playbackItem("page-2");

    act(() => {
      result.current.enqueue(first);
    });
    await waitFor(() => expect(controlled.play).toHaveBeenCalledTimes(1));

    act(() => {
      result.current.enqueue(second);
    });

    expect(controlled.synthesize.mock.calls.map(([request]) => request.requestId)).toEqual([
      "request-page-1",
      "request-page-2",
    ]);
    expect(controlled.play).toHaveBeenCalledTimes(1);

    await finishCurrentPlayback(controlled.completeNext);

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("page-2"));
    expect(controlled.synthesize).toHaveBeenCalledTimes(2);
    expect(controlled.play).toHaveBeenCalledTimes(2);
  });

  it("prefetches synthesis without adding the item to the playback queue", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);
    const item = playbackItem("page-prefetch");

    act(() => {
      result.current.prefetch(item);
    });

    expect(result.current.state.status).toBe("idle");
    expect(result.current.state.currentItem).toBeNull();
    expect(result.current.state.queue).toEqual([]);
    expect(controlled.synthesize).toHaveBeenCalledTimes(1);
    expect(controlled.play).not.toHaveBeenCalled();
  });

  it("prefetches many pages with a bounded concurrent synthesis pool", async () => {
    const controlled = createDeferredSynthesisProvider();
    const { result } = renderQueue(controlled.provider);
    const items = Array.from({ length: 5 }, (_, index) => playbackItem(`page-${index + 1}`));

    act(() => {
      result.current.prefetchMany(items);
    });

    expect(controlled.synthesize.mock.calls.map(([request]) => request.requestId)).toEqual([
      "request-page-1",
      "request-page-2",
      "request-page-3",
    ]);

    await act(async () => {
      controlled.resolveRequest(0);
      await Promise.resolve();
    });

    await waitFor(() => expect(controlled.synthesize).toHaveBeenCalledTimes(4));
    expect(controlled.synthesize.mock.calls[3][0].requestId).toBe("request-page-4");

    await act(async () => {
      controlled.resolveRequest(1);
      await Promise.resolve();
    });

    await waitFor(() => expect(controlled.synthesize).toHaveBeenCalledTimes(5));
    expect(controlled.synthesize.mock.calls[4][0].requestId).toBe("request-page-5");
  });

  it("reuses same-message prefetched synthesis when the page is later enqueued", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);
    const first = playbackItem("page-1", { pageIndex: 0, pageCount: 2 });
    const second = playbackItem("page-2", { pageIndex: 1, pageCount: 2 });

    act(() => {
      result.current.prefetch(second);
      result.current.play(first);
    });

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("page-1"));
    expect(controlled.synthesize.mock.calls.map(([request]) => request.requestId)).toEqual([
      "request-page-2",
      "request-page-1",
    ]);

    act(() => {
      result.current.enqueue(second);
    });

    await finishCurrentPlayback(controlled.completeNext);

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("page-2"));
    expect(controlled.synthesize.mock.calls.map(([request]) => request.requestId)).toEqual([
      "request-page-2",
      "request-page-1",
    ]);
    expect(controlled.play).toHaveBeenCalledTimes(2);
  });

  it("retries synthesis when a prefetched page failed before playback", async () => {
    const controlled = createProviderThatFailsFirstRequest("request-page-1");
    const { result } = renderQueue(controlled.provider);
    const item = playbackItem("page-1");

    act(() => {
      result.current.prefetch(item);
    });

    expect(controlled.synthesize).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.play(item);
    });

    await waitFor(() => expect(result.current.state.status).toBe("playing"));
    expect(controlled.synthesize).toHaveBeenCalledTimes(2);
    expect(controlled.play).toHaveBeenCalledTimes(1);
  });

  it("clears prefetched synthesis from old messages when direct playback starts", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);
    const stale = playbackItem("stale-page", { messageId: "old-message" });
    const current = playbackItem("current-page", { messageId: "new-message" });

    act(() => {
      result.current.prefetch(stale);
      result.current.play(current);
      result.current.enqueue(stale);
    });

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("current-page"));
    await finishCurrentPlayback(controlled.completeNext);
    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("stale-page"));
    expect(controlled.synthesize.mock.calls.map(([request]) => request.requestId)).toEqual([
      "request-stale-page",
      "request-current-page",
      "request-stale-page",
    ]);
  });

  it("notifies after provider playback has been requested", async () => {
    const controlled = createControlledProvider();
    const onPlaybackStart = vi.fn();
    const { result } = renderQueue(controlled.provider, { onPlaybackStart });
    const item = playbackItem("page-1");

    act(() => {
      result.current.play(item);
    });

    await waitFor(() => expect(onPlaybackStart).toHaveBeenCalledWith(item));
    expect(controlled.play).toHaveBeenCalledTimes(1);
  });

  it("notifies when provider playback finishes", async () => {
    const controlled = createControlledProvider();
    const onPlaybackEnd = vi.fn();
    const { result } = renderQueue(controlled.provider, { onPlaybackEnd });
    const item = playbackItem("page-1");

    act(() => {
      result.current.play(item);
    });
    await waitFor(() => expect(controlled.play).toHaveBeenCalledTimes(1));

    await finishCurrentPlayback(controlled.completeNext);

    await waitFor(() => expect(onPlaybackEnd).toHaveBeenCalledWith(item, "played"));
    expect(result.current.state.status).toBe("idle");
  });

  it("clears queued audio and stops the active provider", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);

    act(() => {
      result.current.enqueue(playbackItem("page-1"));
      result.current.enqueue(playbackItem("page-2"));
    });
    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("page-1"));

    act(() => {
      result.current.clear("voice_disabled");
    });

    await waitFor(() => expect(result.current.state.status).toBe("idle"));
    expect(result.current.state.currentItem).toBeNull();
    expect(result.current.state.queue).toEqual([]);
    expect(controlled.stop).toHaveBeenCalledWith("voice_disabled");
    expect(controlled.synthesize.mock.calls.map(([request]) => request.requestId)).toEqual([
      "request-page-1",
      "request-page-2",
    ]);
  });

  it("cancels a message without leaving old page audio behind", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);
    const messagePage = playbackItem("message-a-1", { messageId: "message-a", pageIndex: 0, pageCount: 2 });
    const staleMessagePage = playbackItem("message-a-2", { messageId: "message-a", pageIndex: 1, pageCount: 2 });
    const nextMessagePage = playbackItem("message-b-1", { messageId: "message-b" });

    act(() => {
      result.current.enqueue(messagePage);
      result.current.enqueue(staleMessagePage);
      result.current.enqueue(nextMessagePage);
    });
    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("message-a-1"));

    act(() => {
      result.current.cancelMessage("message-a");
    });

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("message-b-1"));
    expect(result.current.state.queue).toEqual([]);
    expect(controlled.stop).toHaveBeenCalledWith("message_cancelled");
    expect(controlled.synthesize.mock.calls.map(([request]) => request.requestId)).toEqual([
      "request-message-a-1",
      "request-message-a-2",
      "request-message-b-1",
    ]);
  });

  it("keeps the text flow alive when a provider fails", async () => {
    const controlled = createControlledProvider(["request-failed-page"]);
    const { result } = renderQueue(controlled.provider);
    const failedPage = playbackItem("failed-page");
    const nextPage = playbackItem("next-page");

    act(() => {
      result.current.enqueue(failedPage);
      result.current.enqueue(nextPage);
    });

    await waitFor(() => expect(result.current.state.currentItem?.id).toBe("next-page"));
    expect(result.current.state.error).toMatchObject({
      code: "provider_failed",
      itemId: "failed-page",
      recoverable: true,
    });
    expect(controlled.play).toHaveBeenCalledTimes(1);

    await finishCurrentPlayback(controlled.completeNext);

    await waitFor(() => expect(result.current.state.status).toBe("idle"));
    expect(result.current.state.error).toBeNull();
  });

  it("drops queued pages for the same provider after an authentication failure", async () => {
    const controlled = createControlledProvider();
    controlled.synthesize.mockImplementation(async (request: TtsSynthesisRequest): Promise<TtsSynthesisResult> => {
      if (request.requestId === "request-page-1") {
        throw createTtsProviderError("mock", "authentication_failed", "Invalid API Key");
      }
      return {
        kind: "mock",
        requestId: request.requestId,
        provider: "mock",
        durationMs: 100,
      };
    });
    const { result } = renderQueue(controlled.provider);

    act(() => {
      result.current.enqueue(playbackItem("page-1"));
      result.current.enqueue(playbackItem("page-2"));
    });

    await waitFor(() => expect(result.current.state.status).toBe("failed"));
    expect(result.current.state.error).toMatchObject({
      code: "authentication_failed",
      itemId: "page-1",
      provider: "mock",
    });
    expect(result.current.state.queue).toEqual([]);
    expect(controlled.play).not.toHaveBeenCalled();
  });

  it("falls back to the configured fallback provider after cloud authentication fails", async () => {
    const cloud = createImmediateProvider("xiaomi-mimo", "authentication_failed");
    const system = createImmediateProvider("system");
    const onProviderFallback = vi.fn();
    const { result } = renderHook(() =>
      useTtsPlaybackQueue({
        providers: {
          "xiaomi-mimo": cloud.provider,
          system: system.provider,
        },
        fallbackProvider: "system",
        now: () => "2026-06-04T00:00:00.000Z",
        onProviderFallback,
      }),
    );

    act(() => {
      result.current.enqueue(playbackItemForProvider("page-1", "xiaomi-mimo"));
    });

    await waitFor(() => expect(system.play).toHaveBeenCalledTimes(1));
    expect(cloud.synthesize).toHaveBeenCalledTimes(1);
    expect(system.synthesize).toHaveBeenCalledTimes(1);
    expect(system.synthesize).toHaveBeenCalledWith(
      expect.objectContaining({ provider: "system", voice: null }),
      expect.any(AbortSignal),
    );
    expect(onProviderFallback).toHaveBeenCalledWith(
      expect.objectContaining({
        fallbackProvider: "system",
        provider: "xiaomi-mimo",
        error: expect.objectContaining({ code: "authentication_failed" }),
      }),
    );

    act(() => {
      result.current.enqueue(playbackItemForProvider("page-2", "xiaomi-mimo"));
    });

    await waitFor(() => expect(system.play).toHaveBeenCalledTimes(2));
    expect(cloud.synthesize).toHaveBeenCalledTimes(1);
    expect(system.synthesize).toHaveBeenCalledTimes(2);
  });

  it("clears same-provider queued pages when prefetch detects an authentication failure", async () => {
    const controlled = createControlledProvider();
    controlled.synthesize.mockImplementation(async (request: TtsSynthesisRequest): Promise<TtsSynthesisResult> => {
      if (request.requestId === "request-page-2") {
        throw createTtsProviderError("mock", "authentication_failed", "Invalid API Key");
      }
      return {
        kind: "mock",
        requestId: request.requestId,
        provider: "mock",
        durationMs: 100,
      };
    });
    const { result } = renderQueue(controlled.provider);

    act(() => {
      result.current.enqueue(playbackItem("page-1"));
    });
    await waitFor(() => expect(controlled.play).toHaveBeenCalledTimes(1));

    act(() => {
      result.current.enqueue(playbackItem("page-2"));
    });

    await waitFor(() => expect(result.current.state.error?.code).toBe("authentication_failed"));
    expect(result.current.state.queue).toEqual([]);

    await finishCurrentPlayback(controlled.completeNext);

    await waitFor(() => expect(result.current.state.status).toBe("idle"));
    expect(controlled.play).toHaveBeenCalledTimes(1);
  });

  it("clamps volume before passing it to the provider", async () => {
    const controlled = createControlledProvider();
    const { result } = renderQueue(controlled.provider);

    act(() => {
      result.current.setVolume(2);
      result.current.enqueue(playbackItem("page-1"));
    });

    await waitFor(() => expect(controlled.play).toHaveBeenCalledTimes(1));
    expect(result.current.state.volume).toBe(1);
    expect(controlled.play.mock.calls[0][1]?.volume).toBe(1);
  });
});
