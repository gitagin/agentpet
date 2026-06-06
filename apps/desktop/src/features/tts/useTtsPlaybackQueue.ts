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
  initialVolume?: number;
  now?: () => string;
  onPlaybackStart?: (item: TtsPlaybackItem) => void;
  onPlaybackEnd?: (item: TtsPlaybackItem, status: TtsProviderPlaybackStatus) => void;
};

export type TtsPlaybackQueueController = {
  state: TtsPlaybackState;
  enqueue: (item: TtsPlaybackItem) => void;
  play: (item: TtsPlaybackItem) => void;
  stop: (reason?: string) => void;
  cancelMessage: (messageId: string) => void;
  clear: (reason?: string) => void;
  setVolume: (volume: number) => void;
};

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

export function useTtsPlaybackQueue({
  providers,
  initialVolume = 1,
  now = currentIsoTime,
  onPlaybackStart,
  onPlaybackEnd,
}: UseTtsPlaybackQueueOptions): TtsPlaybackQueueController {
  const providersRef = useRef(providers);
  const nowRef = useRef(now);
  const onPlaybackStartRef = useRef(onPlaybackStart);
  const onPlaybackEndRef = useRef(onPlaybackEnd);
  const queueRef = useRef<TtsPlaybackItem[]>([]);
  const currentItemRef = useRef<TtsPlaybackItem | null>(null);
  const statusRef = useRef<TtsPlaybackStatus>("idle");
  const errorRef = useRef<TtsPlaybackError | null>(null);
  const volumeRef = useRef(clampTtsVolume(initialVolume));
  const activeRunIdRef = useRef(0);
  const activeAbortControllerRef = useRef<AbortController | null>(null);
  const activeProviderRef = useRef<TtsProvider<TtsSynthesisResult> | null>(null);
  const startNextRef = useRef<() => void>(() => undefined);
  const [state, setState] = useState<TtsPlaybackState>(() =>
    createPlaybackState("idle", null, [], null, clampTtsVolume(initialVolume), now),
  );

  useEffect(() => {
    providersRef.current = providers;
  }, [providers]);

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
    const provider = providersRef.current[item.synthesis.provider];
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
      publish();
      startNextRef.current();
      return;
    }

    const abortController = new AbortController();
    activeAbortControllerRef.current = abortController;
    activeProviderRef.current = provider;
    publish();

    void (async () => {
      try {
        const synthesis = await provider.synthesize(
          {
            ...item.synthesis,
            text: item.text,
          },
          abortController.signal,
        );
        if (activeRunIdRef.current !== runId || abortController.signal.aborted) {
          return;
        }

        statusRef.current = "playing";
        publish();
        const playbackPromise = provider.play(synthesis, {
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
        errorRef.current = playbackErrorFromUnknown(error, item.synthesis.provider, item.id);
        publish();
        startNextRef.current();
      }
    })();
  }, [publish]);

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
    publish();
    if (!currentItemRef.current) {
      startNextRef.current();
    }
  }, [publish]);

  const play = useCallback((item: TtsPlaybackItem) => {
    if (!hasPlayableText(item)) {
      stopActivePlayback("blank_item", "cancelled");
      return;
    }
    if (currentItemRef.current?.id === item.id) {
      return;
    }
    queueRef.current = [];
    if (currentItemRef.current || activeProviderRef.current || activeAbortControllerRef.current) {
      stopActivePlayback("replaced", "cancelled");
    }
    startPlayback(item);
  }, [startPlayback, stopActivePlayback]);

  const stop = useCallback((reason = "stopped") => {
    stopActivePlayback(reason, "cancelled");
  }, [stopActivePlayback]);

  const cancelMessage = useCallback((messageId: string) => {
    queueRef.current = queueRef.current.filter((item) => item.messageId !== messageId);
    if (currentItemRef.current?.messageId === messageId) {
      stopActivePlayback("message_cancelled", "cancelled");
      startNextRef.current();
      return;
    }
    publish();
    if (!currentItemRef.current) {
      startNextRef.current();
    }
  }, [publish, stopActivePlayback]);

  const clear = useCallback((reason = "cleared") => {
    queueRef.current = [];
    if (currentItemRef.current || activeProviderRef.current || activeAbortControllerRef.current) {
      stopActivePlayback(reason, "idle");
      return;
    }
    statusRef.current = "idle";
    errorRef.current = null;
    publish();
  }, [publish, stopActivePlayback]);

  const setVolume = useCallback((volume: number) => {
    volumeRef.current = clampTtsVolume(volume);
    publish();
  }, [publish]);

  useEffect(() => {
    return () => {
      activeRunIdRef.current += 1;
      activeAbortControllerRef.current?.abort();
      activeProviderRef.current?.stop("unmount");
      activeAbortControllerRef.current = null;
      activeProviderRef.current = null;
    };
  }, []);

  return {
    state,
    enqueue,
    play,
    stop,
    cancelMessage,
    clear,
    setVolume,
  };
}
