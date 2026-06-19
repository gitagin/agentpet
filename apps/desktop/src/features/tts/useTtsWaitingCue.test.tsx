import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TtsSynthesisRequest, TtsSynthesisResult } from "./ttsTypes";
import { createTtsProviderError, type TtsProvider, type TtsProviderPlaybackOptions, type TtsProviderPlaybackResult } from "./ttsProvider";
import { useTtsWaitingCue } from "./useTtsWaitingCue";

function createControlledProvider() {
  const synthesize = vi.fn(async (request: TtsSynthesisRequest): Promise<TtsSynthesisResult> => ({
    kind: "mock",
    requestId: request.requestId,
    provider: "mock",
    durationMs: 100,
  }));
  const play = vi.fn(
    (result: TtsSynthesisResult, options?: TtsProviderPlaybackOptions): Promise<TtsProviderPlaybackResult> =>
      new Promise((resolve) => {
        options?.signal?.addEventListener(
          "abort",
          () =>
            resolve({
              provider: "mock",
              result,
              status: "cancelled",
              reason: "aborted",
            }),
          { once: true },
        );
      }),
  );
  const stop = vi.fn();
  const provider: TtsProvider<TtsSynthesisResult> = {
    id: "mock",
    synthesize,
    play,
    stop,
  };
  return { play, provider, stop, synthesize };
}

function createDeferredProvider() {
  const requests: Array<{
    request: TtsSynthesisRequest;
    resolve: (result: TtsSynthesisResult) => void;
  }> = [];
  const synthesize = vi.fn(
    (request: TtsSynthesisRequest): Promise<TtsSynthesisResult> =>
      new Promise((resolve) => {
        requests.push({ request, resolve });
      }),
  );
  const play = vi.fn(
    async (result: TtsSynthesisResult): Promise<TtsProviderPlaybackResult> => ({
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
    play,
    provider,
    requests,
    resolveRequest(index: number) {
      const request = requests[index]?.request;
      if (!request) {
        throw new Error(`No request at index ${index}.`);
      }
      requests[index].resolve({
        kind: "mock",
        requestId: request.requestId,
        provider: "mock",
        durationMs: 100,
      });
    },
    synthesize,
  };
}

describe("useTtsWaitingCue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("prefetches short waiting cues without cutting them off at 800ms", async () => {
    const controlled = createControlledProvider();
    const { result } = renderHook(() =>
      useTtsWaitingCue({
        enabled: true,
        providers: { mock: controlled.provider },
        provider: "mock",
        voice: null,
        speed: 1,
        volume: 0.6,
      }),
    );

    expect(controlled.synthesize).toHaveBeenCalledTimes(4);
    expect(controlled.synthesize).toHaveBeenCalledWith(
      expect.objectContaining({
        speed: 0.82,
        text: "\u6211\u60f3\u4e00\u4e0b\u3002",
      }),
      expect.any(AbortSignal),
    );

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      expect(result.current.start()).toBe("\u6211\u60f3\u4e00\u4e0b\u3002");
    });

    expect(controlled.play).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(799);
    });

    expect(controlled.stop).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1701);
    });

    expect(controlled.stop).toHaveBeenCalledWith("watchdog_timeout");
  });

  it("cycles prompt text and cancels pending playback before synthesis resolves", async () => {
    const controlled = createDeferredProvider();
    const { result } = renderHook(() =>
      useTtsWaitingCue({
        enabled: true,
        providers: { mock: controlled.provider },
        provider: "mock",
        voice: null,
        speed: 1,
        volume: 1,
      }),
    );

    expect(controlled.synthesize).toHaveBeenCalledTimes(4);

    act(() => {
      expect(result.current.start()).toBe("\u6211\u60f3\u4e00\u4e0b\u3002");
      result.current.stop("reply_started");
      expect(result.current.start()).toBe("\u55ef\uff0c\u6211\u770b\u770b\u3002");
      result.current.stop("reply_started");
    });

    await act(async () => {
      controlled.resolveRequest(0);
      controlled.resolveRequest(1);
      await Promise.resolve();
    });

    expect(controlled.play).not.toHaveBeenCalled();
  });

  it("can use a slower cue speed without changing the normal reply speed input", () => {
    const controlled = createControlledProvider();
    renderHook(() =>
      useTtsWaitingCue({
        enabled: true,
        providers: { mock: controlled.provider },
        provider: "mock",
        voice: null,
        speed: 1,
        cueSpeed: 0.7,
        volume: 1,
      }),
    );

    expect(controlled.synthesize).toHaveBeenCalledWith(
      expect.objectContaining({
        speed: 0.7,
        text: "\u6211\u60f3\u4e00\u4e0b\u3002",
      }),
      expect.any(AbortSignal),
    );
  });

  it("falls back to system TTS when the configured waiting cue provider has an invalid key", async () => {
    const cloud = createControlledProvider();
    cloud.synthesize.mockRejectedValue(createTtsProviderError("xiaomi-mimo", "authentication_failed", "Invalid API Key"));
    const system = createControlledProvider();

    const { result } = renderHook(() =>
      useTtsWaitingCue({
        enabled: true,
        providers: { "xiaomi-mimo": cloud.provider, system: system.provider },
        provider: "xiaomi-mimo",
        fallbackProvider: "system",
        voice: { id: "Chloe", provider: "xiaomi-mimo", label: "Chloe" },
        speed: 1,
        volume: 0.6,
        prompts: ["等我一下。"],
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      expect(result.current.start()).toBe("等我一下。");
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(cloud.synthesize).toHaveBeenCalledTimes(1);
    expect(system.synthesize).toHaveBeenCalledWith(
      expect.objectContaining({ provider: "system", voice: null, text: "等我一下。" }),
      expect.any(AbortSignal),
    );
    expect(system.play).toHaveBeenCalledTimes(1);
  });
});
