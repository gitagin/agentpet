import type { TtsSynthesisRequest, TtsSynthesisResult } from "./ttsTypes";
import {
  assertTtsNotAborted,
  type TtsProvider,
  type TtsProviderPlaybackOptions,
  type TtsProviderPlaybackResult,
} from "./ttsProvider";

type MockTtsSynthesisResult = Extract<TtsSynthesisResult, { kind: "mock" }>;

type TimeoutHandle = ReturnType<typeof globalThis.setTimeout>;

export type MockTtsProviderOptions = {
  durationMs?: number;
  setTimeout?: (callback: () => void, delayMs: number) => TimeoutHandle;
  clearTimeout?: (handle: TimeoutHandle) => void;
};

type ActivePlayback = {
  handle: TimeoutHandle;
  resolve: (value: TtsProviderPlaybackResult<MockTtsSynthesisResult>) => void;
  result: MockTtsSynthesisResult;
  settled: boolean;
};

export function createMockTtsProvider(options: MockTtsProviderOptions = {}): TtsProvider<MockTtsSynthesisResult> {
  const durationMs = Math.max(0, options.durationMs ?? 120);
  const schedule = options.setTimeout ?? globalThis.setTimeout.bind(globalThis);
  const cancelTimer = options.clearTimeout ?? globalThis.clearTimeout.bind(globalThis);
  let active: ActivePlayback | null = null;

  const finishPlayback = (playback: ActivePlayback, status: "played" | "cancelled", reason?: string) => {
    if (active !== playback || playback.settled) {
      return;
    }
    playback.settled = true;
    cancelTimer(playback.handle);
    active = null;
    playback.resolve({
      provider: "mock",
      result: playback.result,
      status,
      reason,
    });
  };

  const finishActive = (status: "played" | "cancelled", reason?: string) => {
    const playback = active;
    if (!playback) {
      return;
    }
    finishPlayback(playback, status, reason);
  };

  return {
    id: "mock",

    async synthesize(request: TtsSynthesisRequest, signal?: AbortSignal): Promise<MockTtsSynthesisResult> {
      assertTtsNotAborted(signal, "mock");
      return {
        kind: "mock",
        requestId: request.requestId,
        provider: "mock",
        durationMs,
      };
    },

    play(
      result: MockTtsSynthesisResult,
      options?: TtsProviderPlaybackOptions,
    ): Promise<TtsProviderPlaybackResult<MockTtsSynthesisResult>> {
      assertTtsNotAborted(options?.signal, "mock");
      finishActive("cancelled", "replaced");

      return new Promise((resolve) => {
        let playback: ActivePlayback | null = null;
        const abort = () => {
          if (playback) {
            finishPlayback(playback, "cancelled", "aborted");
          }
        };
        const handle = schedule(() => {
          if (playback) {
            finishPlayback(playback, "played");
          }
        }, durationMs);
        playback = {
          handle,
          resolve,
          result,
          settled: false,
        };
        active = playback;
        options?.signal?.addEventListener("abort", abort, { once: true });
      });
    },

    stop(reason = "stopped"): void {
      finishActive("cancelled", reason);
    },
  };
}
