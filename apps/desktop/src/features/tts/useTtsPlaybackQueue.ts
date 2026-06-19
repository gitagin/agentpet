import { useCallback, useEffect, useRef, useState } from "react";

import type {
  TtsPlaybackError,
  TtsPlaybackItem,
  TtsPlaybackState,
  TtsPlaybackStatus,
  TtsProviderId,
  TtsSynthesisResult,
} from "./ttsTypes";
import { clampTtsVolume, TtsProviderError, type TtsProvider } from "./ttsProvider";
import type { TtsProviderPlaybackStatus } from "./ttsProvider";

export type TtsProviderRegistry = Readonly<Record<string, TtsProvider<TtsSynthesisResult> | undefined>>;

export type UseTtsPlaybackQueueOptions = {
  providers: TtsProviderRegistry;
  fallbackProvider?: TtsProviderId | null;
  initialVolume?: number;
  now?: () => string;
  onPlaybackStart?: (item: TtsPlaybackItem) => void;
  onPlaybackEnd?: (item: TtsPlaybackItem, status: TtsProviderPlaybackStatus) => void;
  onProviderFallback?: (event: {
    error: TtsPlaybackError;
    fallbackProvider: TtsProviderId;
    item: TtsPlaybackItem;
    provider: TtsProviderId;
  }) => void;
  providerResetKey?: string | null;
};

export type TtsPlaybackQueueController = {
  state: TtsPlaybackState;
  enqueue: (item: TtsPlaybackItem) => void;
  prefetch: (item: TtsPlaybackItem) => void;
  prefetchMany: (items: TtsPlaybackItem[]) => void;
  play: (item: TtsPlaybackItem) => void;
  stop: (reason?: string) => void;
  cancelMessage: (messageId: string) => void;
  clear: (reason?: string) => void;
  setVolume: (volume: number) => void;
};

type PrefetchedSynthesis = {
  controller: AbortController;
  item: TtsPlaybackItem;
  key: string;
  promise: Promise<TtsSynthesisResult>;
  provider: TtsProvider<TtsSynthesisResult>;
  used: boolean;
};

const maxConcurrentPrefetches = 3;

function currentIsoTime() {
  return new Date().toISOString();
}

function createPlaybackState(
  status: TtsPlaybackStatus,
  currentItem: TtsPlaybackItem | null,
  queue: TtsPlaybackItem[],
  error: TtsPlaybackError | null,
  volume: number,
  now: () => string,
): TtsPlaybackState {
  return {
    status,
    currentItem,
    queue,
    error,
    volume,
    updatedAt: now(),
  };
}

function hasPlayableText(item: TtsPlaybackItem) {
  return item.text.trim().length > 0 && item.synthesis.text.trim().length > 0;
}

function itemAlreadyScheduled(
  item: TtsPlaybackItem,
  currentItem: TtsPlaybackItem | null,
  queue: TtsPlaybackItem[],
) {
  return currentItem?.id === item.id || queue.some((queuedItem) => queuedItem.id === item.id);
}

function synthesisKeyForItem(item: TtsPlaybackItem, providerId = item.synthesis.provider) {
  const voice = item.synthesis.voice?.provider === providerId ? item.synthesis.voice : null;
  return JSON.stringify({
    text: item.text,
    provider: providerId,
    voice: voice?.id ?? null,
    speed: item.synthesis.speed,
    volume: item.synthesis.volume ?? null,
    cacheEnabled: item.synthesis.cacheEnabled ?? null,
  });
}

function synthesisRequestForProvider(item: TtsPlaybackItem, providerId: TtsProviderId) {
  return {
    ...item.synthesis,
    text: item.text,
    provider: providerId,
    voice: item.synthesis.voice?.provider === providerId ? item.synthesis.voice : null,
  };
}

function playbackErrorFromUnknown(
  error: unknown,
  provider: TtsProviderId,
  itemId: string,
): TtsPlaybackError {
  if (error instanceof TtsProviderError) {
    return {
      ...error.playbackError,
      provider: error.playbackError.provider ?? provider,
      itemId: error.playbackError.itemId ?? itemId,
    };
  }
  return {
    code: "provider_failed",
    message: error instanceof Error ? error.message : "TTS 服务调用失败。",
    provider,
    itemId,
    recoverable: true,
  };
}

function isProviderConfigurationFailure(error: TtsPlaybackError): boolean {
  return error.code === "authentication_failed" ||
    error.code === "credential_missing" ||
    error.code === "provider_not_configured";
}

export function useTtsPlaybackQueue({
  providers,
  fallbackProvider = null,
  initialVolume = 1,
  now = currentIsoTime,
  onPlaybackStart,
  onPlaybackEnd,
  onProviderFallback,
  providerResetKey = null,
}: UseTtsPlaybackQueueOptions): TtsPlaybackQueueController {
  const providersRef = useRef(providers);
  const fallbackProviderRef = useRef<TtsProviderId | null>(fallbackProvider);
  const nowRef = useRef(now);
  const onPlaybackStartRef = useRef(onPlaybackStart);
  const onPlaybackEndRef = useRef(onPlaybackEnd);
  const onProviderFallbackRef = useRef(onProviderFallback);
  const queueRef = useRef<TtsPlaybackItem[]>([]);
  const currentItemRef = useRef<TtsPlaybackItem | null>(null);
  const statusRef = useRef<TtsPlaybackStatus>("idle");
  const errorRef = useRef<TtsPlaybackError | null>(null);
  const volumeRef = useRef(clampTtsVolume(initialVolume));
  const activeRunIdRef = useRef(0);
  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const activeProviderRef = useRef<TtsProvider<TtsSynthesisResult> | null>(null);
  const prefetchedSynthesisRef = useRef<Map<string, PrefetchedSynthesis>>(new Map());
  const pendingPrefetchQueueRef = useRef<TtsPlaybackItem[]>([]);
  const activePrefetchCountRef = useRef(0);
  const unavailableProvidersRef = useRef<Set<TtsProviderId>>(new Set());
  const startNextRef = useRef<() => void>(() => undefined);
  const pumpPrefetchRef = useRef<() => void>(() => undefined);
  const [state, setState] = useState<TtsPlaybackState>(() =>
    createPlaybackState("idle", null, [], null, clampTtsVolume(initialVolume), now),
  );

  useEffect(() => {
    providersRef.current = providers;
  }, [providers]);

  useEffect(() => {
    fallbackProviderRef.current = fallbackProvider;
  }, [fallbackProvider]);

  useEffect(() => {
    onProviderFallbackRef.current = onProviderFallback;
  }, [onProviderFallback]);

  useEffect(() => {
    unavailableProvidersRef.current.clear();
  }, [fallbackProvider, providerResetKey]);

  useEffect(() => {
    nowRef.current = now;
  }, [now]);

  useEffect(() => {
    onPlaybackStartRef.current = onPlaybackStart;
  }, [onPlaybackStart]);

  useEffect(() => {
    onPlaybackEndRef.current = onPlaybackEnd;
  }, [onPlaybackEnd]);

  const publish = useCallback(() => {
    setState(
      createPlaybackState(
        statusRef.current,
        currentItemRef.current,
        [...queueRef.current],
        errorRef.current,
        volumeRef.current,
        nowRef.current,
      ),
    );
  }, []);

  const disposePrefetchedResult = useCallback(
    (entry: PrefetchedSynthesis) => {
      void entry.promise.then((result) => {
        if (!entry.used) {
          entry.provider.dispose?.(result);
        }
      }).catch(() => undefined);
    },
    [],
  );

  const clearPrefetchedItems = useCallback((predicate?: (item: TtsPlaybackItem) => boolean) => {
    pendingPrefetchQueueRef.current = predicate
      ? pendingPrefetchQueueRef.current.filter((item) => !predicate(item))
      : [];
    Array.from(prefetchedSynthesisRef.current.entries()).forEach(([itemId, entry]) => {
      if (!predicate || predicate(entry.item)) {
        prefetchedSynthesisRef.current.delete(itemId);
        entry.controller.abort();
        disposePrefetchedResult(entry);
      }
    });
  }, [disposePrefetchedResult]);

  const clearProviderWork = useCallback((provider: TtsProviderId) => {
    queueRef.current = queueRef.current.filter((item) => item.synthesis.provider !== provider);
    pendingPrefetchQueueRef.current = pendingPrefetchQueueRef.current.filter((item) => item.synthesis.provider !== provider);
    clearPrefetchedItems((item) => item.synthesis.provider === provider);
  }, [clearPrefetchedItems]);

  const fallbackProviderFor = useCallback((providerId: TtsProviderId) => {
    const candidate = fallbackProviderRef.current;
    if (!candidate || candidate === providerId || !providersRef.current[candidate]) {
      return null;
    }
    return candidate;
  }, []);

  const resolveProviderForItem = useCallback((item: TtsPlaybackItem) => {
    const primaryProviderId = item.synthesis.provider;
    const fallbackProviderId = fallbackProviderFor(primaryProviderId);
    const providerId =
      (!providersRef.current[primaryProviderId] || unavailableProvidersRef.current.has(primaryProviderId)) &&
      fallbackProviderId
        ? fallbackProviderId
        : primaryProviderId;
    const provider = providersRef.current[providerId];
    return provider ? { provider, providerId } : null;
  }, [fallbackProviderFor]);

  const synthesizeWithFallback = useCallback(
    async (
      item: TtsPlaybackItem,
      providerId: TtsProviderId,
      signal: AbortSignal | undefined,
      onResolvedProvider?: (provider: TtsProvider<TtsSynthesisResult>, providerId: TtsProviderId) => void,
    ) => {
      const provider = providersRef.current[providerId];
      if (!provider) {
        throw new TtsProviderError({
          code: "provider_not_configured",
          message: `TTS 服务 ${providerId} 尚未配置。`,
          provider: providerId,
          recoverable: true,
        });
      }

      try {
        return await provider.synthesize(synthesisRequestForProvider(item, providerId), signal);
      } catch (error) {
        const playbackError = playbackErrorFromUnknown(error, providerId, item.id);
        const fallbackProviderId = fallbackProviderFor(providerId);
        if (!isProviderConfigurationFailure(playbackError) || !fallbackProviderId || signal?.aborted) {
          throw error;
        }
        const fallback = providersRef.current[fallbackProviderId];
        if (!fallback) {
          throw error;
        }
        unavailableProvidersRef.current.add(providerId);
        onProviderFallbackRef.current?.({
          error: playbackError,
          fallbackProvider: fallbackProviderId,
          item,
          provider: providerId,
        });
        onResolvedProvider?.(fallback, fallbackProviderId);
        return fallback.synthesize(synthesisRequestForProvider(item, fallbackProviderId), signal);
      }
    },
    [fallbackProviderFor],
  );

  const startPrefetch = useCallback((item: TtsPlaybackItem) => {
    const resolved = resolveProviderForItem(item);
    if (!resolved) {
      return;
    }
    const key = synthesisKeyForItem(item, resolved.providerId);
    const controller = new AbortController();
    let entry: PrefetchedSynthesis;
    const promise = synthesizeWithFallback(item, resolved.providerId, controller.signal, (provider) => {
      entry.provider = provider;
    });
    activePrefetchCountRef.current += 1;
    entry = {
      controller,
      item,
      key,
      promise,
      provider: resolved.provider,
      used: false,
    };
    prefetchedSynthesisRef.current.set(item.id, entry);
    void promise.catch((error) => {
      const playbackError = playbackErrorFromUnknown(error, item.synthesis.provider, item.id);
      if (isProviderConfigurationFailure(playbackError)) {
        errorRef.current = playbackError;
        clearProviderWork(item.synthesis.provider);
        clearProviderWork(playbackError.provider || item.synthesis.provider);
        publish();
      }
    });
    void promise.finally(() => {
      activePrefetchCountRef.current = Math.max(0, activePrefetchCountRef.current - 1);
      pumpPrefetchRef.current();
    }).catch(() => undefined);
  }, [clearProviderWork, publish, resolveProviderForItem, synthesizeWithFallback]);

  const pumpPrefetchQueue = useCallback(() => {
    while (activePrefetchCountRef.current < maxConcurrentPrefetches && pendingPrefetchQueueRef.current.length > 0) {
      const item = pendingPrefetchQueueRef.current.shift();
      if (!item || !hasPlayableText(item)) {
        continue;
      }
      const provider = providersRef.current[item.synthesis.provider];
      if (!provider) {
        continue;
      }
      const existing = prefetchedSynthesisRef.current.get(item.id);
      if (existing && existing.key === synthesisKeyForItem(item)) {
        continue;
      }
      startPrefetch(item);
    }
  }, [startPrefetch]);

  useEffect(() => {
    pumpPrefetchRef.current = pumpPrefetchQueue;
  }, [pumpPrefetchQueue]);

  const prefetchQueuedItem = useCallback((item: TtsPlaybackItem) => {
    if (!hasPlayableText(item)) {
      return;
    }
    const key = synthesisKeyForItem(item);
    const existing = prefetchedSynthesisRef.current.get(item.id);
    if (existing) {
      if (existing.key === key) {
        return;
      }
      prefetchedSynthesisRef.current.delete(item.id);
      existing.controller.abort();
      disposePrefetchedResult(existing);
    }
    const pendingIndex = pendingPrefetchQueueRef.current.findIndex((pendingItem) => pendingItem.id === item.id);
    if (pendingIndex !== -1) {
      const pendingItem = pendingPrefetchQueueRef.current[pendingIndex];
      if (synthesisKeyForItem(pendingItem) === key) {
        return;
      }
      pendingPrefetchQueueRef.current.splice(pendingIndex, 1);
    }
    if (!providersRef.current[item.synthesis.provider]) {
      return;
    }
    pendingPrefetchQueueRef.current.push(item);
    pumpPrefetchRef.current();
  }, [disposePrefetchedResult]);

  const stopActivePlayback = useCallback((reason: string, status: TtsPlaybackStatus) => {
    activeRunIdRef.current += 1;
    activeAbortControllerRef.current?.abort();
    activeProviderRef.current?.stop(reason);
    activeAbortControllerRef.current = null;
    activeProviderRef.current = null;
    currentItemRef.current = null;
    statusRef.current = status;
    errorRef.current = null;
    publish();
  }, [publish]);

  const startPlayback = useCallback((item: TtsPlaybackItem) => {
    const resolved = resolveProviderForItem(item);
    const provider = resolved?.provider;
    const providerId = resolved?.providerId ?? item.synthesis.provider;
    const runId = activeRunIdRef.current + 1;
    activeRunIdRef.current = runId;
    currentItemRef.current = item;
    statusRef.current = "synthesizing";

    if (!provider) {
      activeAbortControllerRef.current = null;
      activeProviderRef.current = null;
      currentItemRef.current = null;
      statusRef.current = "failed";
      errorRef.current = {
        code: "provider_not_configured",
        message: `TTS 服务 ${item.synthesis.provider} 尚未配置。`,
        provider: item.synthesis.provider,
        itemId: item.id,
        recoverable: true,
      };
      clearProviderWork(item.synthesis.provider);
      publish();
      if (queueRef.current.length > 0) {
        startNextRef.current();
      }
      return;
    }

    pendingPrefetchQueueRef.current = pendingPrefetchQueueRef.current.filter(
      (pendingItem) => pendingItem.id !== item.id,
    );
    const prefetchedCandidate = prefetchedSynthesisRef.current.get(item.id);
    const prefetched =
      prefetchedCandidate && prefetchedCandidate.key === synthesisKeyForItem(item, providerId)
        ? prefetchedCandidate
        : null;
    if (prefetchedCandidate && !prefetched) {
      prefetchedSynthesisRef.current.delete(item.id);
      prefetchedCandidate.controller.abort();
      disposePrefetchedResult(prefetchedCandidate);
    }
    if (prefetched) {
      prefetchedSynthesisRef.current.delete(item.id);
      prefetched.used = true;
    }
    let playbackProvider = prefetched?.provider ?? provider;
    const abortController = prefetched?.controller ?? new AbortController();
    activeAbortControllerRef.current = abortController;
    activeProviderRef.current = playbackProvider;
    publish();

    void (async () => {
      try {
        let synthesis: TtsSynthesisResult;
        try {
          synthesis = prefetched
            ? await prefetched.promise
            : await synthesizeWithFallback(item, providerId, abortController.signal, (nextProvider) => {
                playbackProvider = nextProvider;
                activeProviderRef.current = nextProvider;
              });
        } catch (error) {
          if (!prefetched) {
            throw error;
          }
          if (activeRunIdRef.current !== runId || abortController.signal.aborted) {
            return;
          }
          synthesis = await synthesizeWithFallback(item, providerId, abortController.signal, (nextProvider) => {
            playbackProvider = nextProvider;
            activeProviderRef.current = nextProvider;
          });
        }
        if (activeRunIdRef.current !== runId || abortController.signal.aborted) {
          playbackProvider.dispose?.(synthesis);
          return;
        }

        statusRef.current = "playing";
        publish();
        const playbackPromise = playbackProvider.play(synthesis, {
          signal: abortController.signal,
          volume: volumeRef.current,
        });
        onPlaybackStartRef.current?.(item);
        const playback = await playbackPromise;
        if (activeRunIdRef.current !== runId || abortController.signal.aborted) {
          return;
        }

        activeAbortControllerRef.current = null;
        activeProviderRef.current = null;
        currentItemRef.current = null;
        statusRef.current = playback.status === "cancelled" ? "cancelled" : "idle";
        errorRef.current = null;
        publish();
        onPlaybackEndRef.current?.(item, playback.status);

        if (playback.status === "played") {
          startNextRef.current();
        }
      } catch (error) {
        if (activeRunIdRef.current !== runId || abortController.signal.aborted) {
          return;
        }
        activeAbortControllerRef.current = null;
        activeProviderRef.current = null;
        currentItemRef.current = null;
        statusRef.current = "failed";
        const playbackError = playbackErrorFromUnknown(error, item.synthesis.provider, item.id);
        errorRef.current = playbackError;
        if (isProviderConfigurationFailure(playbackError)) {
          clearProviderWork(item.synthesis.provider);
          clearProviderWork(playbackError.provider || item.synthesis.provider);
        }
        publish();
        if (queueRef.current.length > 0) {
          startNextRef.current();
        }
      }
    })();
  }, [clearProviderWork, publish, resolveProviderForItem, synthesizeWithFallback]);

  const startNext = useCallback(() => {
    if (currentItemRef.current) {
      return;
    }
    const nextItem = queueRef.current.shift();
    if (!nextItem) {
      publish();
      return;
    }
    startPlayback(nextItem);
  }, [publish, startPlayback]);

  useEffect(() => {
    startNextRef.current = startNext;
  }, [startNext]);

  const enqueue = useCallback((item: TtsPlaybackItem) => {
    if (!hasPlayableText(item) || itemAlreadyScheduled(item, currentItemRef.current, queueRef.current)) {
      return;
    }
    queueRef.current = [...queueRef.current, item];
    if (currentItemRef.current) {
      prefetchQueuedItem(item);
    }
    publish();
    if (!currentItemRef.current) {
      startNextRef.current();
    }
  }, [prefetchQueuedItem, publish]);

  const prefetch = useCallback((item: TtsPlaybackItem) => {
    if (currentItemRef.current?.id === item.id || itemAlreadyScheduled(item, currentItemRef.current, queueRef.current)) {
      return;
    }
    prefetchQueuedItem(item);
  }, [prefetchQueuedItem]);

  const prefetchMany = useCallback((items: TtsPlaybackItem[]) => {
    for (const item of items) {
      if (currentItemRef.current?.id === item.id || itemAlreadyScheduled(item, currentItemRef.current, queueRef.current)) {
        continue;
      }
      prefetchQueuedItem(item);
    }
  }, [prefetchQueuedItem]);

  const play = useCallback((item: TtsPlaybackItem) => {
    if (!hasPlayableText(item)) {
      stopActivePlayback("blank_item", "cancelled");
      return;
    }
    if (currentItemRef.current?.id === item.id) {
      return;
    }
    clearPrefetchedItems((prefetchedItem) => prefetchedItem.messageId !== item.messageId);
    queueRef.current = [];
    if (currentItemRef.current || activeProviderRef.current || activeAbortControllerRef.current) {
      stopActivePlayback("replaced", "cancelled");
    }
    startPlayback(item);
  }, [clearPrefetchedItems, startPlayback, stopActivePlayback]);

  const stop = useCallback((reason = "stopped") => {
    stopActivePlayback(reason, "cancelled");
  }, [stopActivePlayback]);

  const cancelMessage = useCallback((messageId: string) => {
    queueRef.current = queueRef.current.filter((item) => item.messageId !== messageId);
    clearPrefetchedItems((item) => item.messageId === messageId);
    if (currentItemRef.current?.messageId === messageId) {
      stopActivePlayback("message_cancelled", "cancelled");
      startNextRef.current();
      return;
    }
    publish();
    if (!currentItemRef.current) {
      startNextRef.current();
    }
  }, [clearPrefetchedItems, publish, stopActivePlayback]);

  const clear = useCallback((reason = "cleared") => {
    queueRef.current = [];
    clearPrefetchedItems();
    if (currentItemRef.current || activeProviderRef.current || activeAbortControllerRef.current) {
      stopActivePlayback(reason, "idle");
      return;
    }
    statusRef.current = "idle";
    errorRef.current = null;
    publish();
  }, [clearPrefetchedItems, publish, stopActivePlayback]);

  const setVolume = useCallback((volume: number) => {
    volumeRef.current = clampTtsVolume(volume);
    publish();
  }, [publish]);

  useEffect(() => {
    return () => {
      activeRunIdRef.current += 1;
      activeAbortControllerRef.current?.abort();
      activeProviderRef.current?.stop("unmount");
      clearPrefetchedItems();
      activeAbortControllerRef.current = null;
      activeProviderRef.current = null;
    };
  }, [clearPrefetchedItems]);

  return {
    state,
    enqueue,
    prefetch,
    prefetchMany,
    play,
    stop,
    cancelMessage,
    clear,
    setVolume,
  };
}
