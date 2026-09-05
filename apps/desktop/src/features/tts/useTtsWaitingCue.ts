import { useCallback, useEffect, useMemo, useRef } from "react";

import type { TtsProviderId, TtsSynthesisResult, TtsVoice } from "./ttsTypes";
import { clampTtsVolume, type TtsProvider } from "./ttsProvider";
import {
  buildSynthesisRequest,
  synthesisCacheKey,
  useTtsProviderFallback,
  type TtsProviderRegistry,
} from "./ttsFallback";

const defaultWaitingCuePrompts = [
  "\u6211\u60f3\u4e00\u4e0b\u3002",
  "\u55ef\uff0c\u6211\u770b\u770b\u3002",
  "\u7b49\u6211\u6574\u7406\u4e00\u4e0b\u3002",
  "\u8fd9\u4e2a\u6211\u6765\u60f3\u60f3\u3002",
];
const waitingCuePlaybackGraceMs = 1200;
const waitingCueMinimumPlaybackWatchdogMs = 2500;
const waitingCueFallbackPlaybackWatchdogMs = 5000;
const waitingCueMaximumPlaybackWatchdogMs = 6000;
const defaultWaitingCueSpeed = 0.82;

type CachedWaitingCue = {
  controller: AbortController;
  key: string;
  provider: TtsProvider<TtsSynthesisResult>;
  promise: Promise<TtsSynthesisResult>;
  result: TtsSynthesisResult | null;
  used: boolean;
};

type ActiveWaitingCue = {
  abortController: AbortController;
  provider: TtsProvider<TtsSynthesisResult>;
  runId: number;
  timerId: number | null;
};

export type UseTtsWaitingCueOptions = {
  enabled: boolean;
  providers: TtsProviderRegistry;
  provider: TtsProviderId;
  fallbackProvider?: TtsProviderId | null;
  voice: TtsVoice | null;
  speed: number;
  volume: number;
  cueSpeed?: number;
  prompts?: string[];
};

export type TtsWaitingCueController = {
  start: () => string;
  stop: (reason?: string) => void;
  prefetch: () => void;
};

export function useTtsWaitingCue({
  enabled,
  providers,
  provider,
  fallbackProvider = null,
  voice,
  speed,
  volume,
  cueSpeed = defaultWaitingCueSpeed,
  prompts = defaultWaitingCuePrompts,
}: UseTtsWaitingCueOptions): TtsWaitingCueController {
  const promptList = useMemo(() => prompts.map((prompt) => prompt.trim()).filter(Boolean), [prompts]);
  const nextPromptIndexRef = useRef(0);
  const cacheRef = useRef<Map<string, CachedWaitingCue>>(new Map());
  const activeRef = useRef<ActiveWaitingCue | null>(null);
  const runIdRef = useRef(0);
  const optionsRef = useRef({
    enabled,
    providers,
    provider,
    fallbackProvider,
    voice,
    speed,
    volume,
    cueSpeed,
    promptList,
  });

  useEffect(() => {
    optionsRef.current = {
      enabled,
      providers,
      provider,
      fallbackProvider,
      voice,
      speed,
      volume,
      cueSpeed,
      promptList,
    };
  }, [cueSpeed, enabled, fallbackProvider, providers, provider, promptList, speed, voice, volume]);

  const providerResetKey = useMemo(() => [provider, voice] as const, [provider, voice]);
  const { resolveProviderId, synthesizeWithFallback } = useTtsProviderFallback({
    providers,
    fallbackProvider,
    resetKey: providerResetKey,
  });

  const disposeCue = useCallback((cue: CachedWaitingCue) => {
    cue.controller.abort();
    void cue.promise
      .then((result) => {
        if (!cue.used) {
          cue.provider.dispose?.(result);
        }
      })
      .catch(() => undefined);
  }, []);

  const stop = useCallback((reason = "stopped") => {
    runIdRef.current += 1;
    const active = activeRef.current;
    if (!active) {
      return;
    }
    activeRef.current = null;
    if (active.timerId !== null) {
      window.clearTimeout(active.timerId);
    }
    active.abortController.abort();
    active.provider.stop?.(reason);
  }, []);

  const providerIdForPrompt = useCallback(
    () => resolveProviderId(optionsRef.current.provider),
    [resolveProviderId],
  );

  const cacheKeyForPrompt = useCallback((prompt: string, providerId: TtsProviderId) => {
    const { voice: selectedVoice, cueSpeed: selectedCueSpeed, volume: selectedVolume } = optionsRef.current;
    return synthesisCacheKey({
      text: prompt,
      provider: providerId,
      voice: selectedVoice,
      speed: selectedCueSpeed,
      volume: selectedVolume,
      cacheEnabled: true,
    });
  }, []);

  const synthesizePrompt = useCallback(
    async (
      prompt: string,
      providerId: TtsProviderId,
      signal: AbortSignal,
      onResolvedProvider?: (provider: TtsProvider<TtsSynthesisResult>) => void,
    ) => {
      return synthesizeWithFallback({
        providerId,
        signal,
        buildRequest: (requestProviderId) => {
          const { voice: selectedVoice, cueSpeed: selectedCueSpeed, volume: selectedVolume } = optionsRef.current;
          return buildSynthesisRequest(
            {
              requestId: `waiting-cue:${requestProviderId}:${prompt}`,
              speed: selectedCueSpeed,
              volume: selectedVolume,
              cacheEnabled: true,
            },
            prompt,
            requestProviderId,
            selectedVoice,
          );
        },
        onResolvedProvider,
      });
    },
    [synthesizeWithFallback],
  );

  const ensureCachedPrompt = useCallback(
    (prompt: string) => {
      const { enabled: isEnabled, providers: registry } = optionsRef.current;
      if (!isEnabled) {
        return null;
      }
      const providerId = providerIdForPrompt();
      const cueProvider = registry[providerId];
      if (!cueProvider) {
        return null;
      }
      const key = cacheKeyForPrompt(prompt, providerId);
      const existing = cacheRef.current.get(key);
      if (existing) {
        return existing;
      }
      const controller = new AbortController();
      let cue: CachedWaitingCue;
      const promise = synthesizePrompt(prompt, providerId, controller.signal, (resolvedProvider) => {
        cue.provider = resolvedProvider;
      });
      cue = {
        controller,
        key,
        provider: cueProvider,
        promise,
        result: null,
        used: false,
      };
      cacheRef.current.set(key, cue);
      void promise.then((result) => {
        cue.result = result;
      }).catch(() => undefined);
      void promise.catch(() => {
        if (cacheRef.current.get(key) === cue) {
          cacheRef.current.delete(key);
        }
      });
      return cue;
    },
    [cacheKeyForPrompt, providerIdForPrompt, synthesizePrompt],
  );

  const prefetch = useCallback(() => {
    const { enabled: isEnabled, promptList: currentPrompts } = optionsRef.current;
    if (!isEnabled) {
      return;
    }
    currentPrompts.forEach((prompt) => ensureCachedPrompt(prompt));
  }, [ensureCachedPrompt]);

  const cleanupActive = useCallback((runId: number) => {
    const active = activeRef.current;
    if (!active || active.runId !== runId) {
      return;
    }
    if (active.timerId !== null) {
      window.clearTimeout(active.timerId);
    }
    activeRef.current = null;
  }, []);

  const replenishPrompt = useCallback(
    (prompt: string) => {
      window.setTimeout(() => {
        ensureCachedPrompt(prompt);
      }, 0);
    },
    [ensureCachedPrompt],
  );

  const playbackWatchdogMsForResult = useCallback((result: TtsSynthesisResult) => {
    const durationMs = "durationMs" in result ? result.durationMs : undefined;
    if (typeof durationMs !== "number" || !Number.isFinite(durationMs) || durationMs <= 0) {
      return waitingCueFallbackPlaybackWatchdogMs;
    }
    return Math.min(
      waitingCueMaximumPlaybackWatchdogMs,
      Math.max(waitingCueMinimumPlaybackWatchdogMs, Math.ceil(durationMs + waitingCuePlaybackGraceMs)),
    );
  }, []);

  const playCachedCue = useCallback(
    (cue: CachedWaitingCue, prompt: string, result: TtsSynthesisResult, runId: number) => {
      if (runIdRef.current !== runId || cue.controller.signal.aborted) {
        return;
      }
      cacheRef.current.delete(cue.key);
      cue.used = true;
      const abortController = new AbortController();
      activeRef.current = {
        abortController,
        provider: cue.provider,
        runId,
        timerId: null,
      };
      const playback = cue.provider.play(result, {
        signal: abortController.signal,
        volume: clampTtsVolume(optionsRef.current.volume),
      });
      const active = activeRef.current;
      if (active?.runId === runId) {
        active.timerId = window.setTimeout(() => stop("watchdog_timeout"), playbackWatchdogMsForResult(result));
      }
      void playback
        .catch(() => undefined)
        .finally(() => {
          cleanupActive(runId);
          replenishPrompt(prompt);
        });
    },
    [cleanupActive, playbackWatchdogMsForResult, replenishPrompt, stop],
  );

  const start = useCallback(() => {
    const currentPrompts = optionsRef.current.promptList;
    const prompt = currentPrompts[nextPromptIndexRef.current % currentPrompts.length] || defaultWaitingCuePrompts[0];
    nextPromptIndexRef.current = (nextPromptIndexRef.current + 1) % Math.max(1, currentPrompts.length);
    stop("replaced");
    const cue = ensureCachedPrompt(prompt);
    if (!cue) {
      return prompt;
    }
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    if (cue.result) {
      playCachedCue(cue, prompt, cue.result, runId);
      return prompt;
    }
    void cue.promise
      .then((result) => {
        playCachedCue(cue, prompt, result, runId);
      })
      .catch(() => undefined);
    return prompt;
  }, [ensureCachedPrompt, playCachedCue, stop]);

  useEffect(() => {
    stop("config_changed");
    cacheRef.current.forEach(disposeCue);
    cacheRef.current.clear();
    prefetch();
  }, [cueSpeed, disposeCue, enabled, fallbackProvider, prefetch, provider, promptList, speed, stop, voice, volume]);

  useEffect(() => {
    const cache = cacheRef.current;
    return () => {
      stop("unmount");
      cache.forEach(disposeCue);
      cache.clear();
    };
  }, [disposeCue, stop]);

  return {
    start,
    stop,
    prefetch,
  };
}
