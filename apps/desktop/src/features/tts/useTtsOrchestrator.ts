import { useCallback, useEffect, useMemo, useRef } from "react";

import type { TtsPlaybackItem, TtsSettingsResponse } from "../../types";
import type { DesktopApi } from "../../services/desktopApi";
import type { DesktopWindowMode } from "../desktop/desktopWindowModes";
import {
  createBackendTtsProvider,
  createMockTtsProvider,
  createSystemTtsProvider,
  type TtsProviderPlaybackStatus,
  useTtsPlaybackQueue,
  useTtsWaitingCue,
} from ".";
import {
  formatTtsPlaybackErrorNotice,
  formatTtsProviderFallbackNotice,
  normalizeTtsVoiceGender,
} from "./ttsNotices";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type UseTtsOrchestratorOptions = {
  api: DesktopApi;
  settings: TtsSettingsResponse | null | undefined;
  windowMode: DesktopWindowMode;
  onNotice: (notice: Notice | null) => void;
};

type PetPlaybackHandlers = {
  onStart?: (item: TtsPlaybackItem) => void;
  onEnd?: (item: TtsPlaybackItem, status: TtsProviderPlaybackStatus) => void;
};

export function useTtsOrchestrator({
  api,
  settings,
  windowMode,
  onNotice,
}: UseTtsOrchestratorOptions) {
  const playbackStartRef = useRef<(item: TtsPlaybackItem) => void>(() => undefined);
  const playbackEndRef = useRef<(item: TtsPlaybackItem, status: TtsProviderPlaybackStatus) => void>(() => undefined);
  const previousWindowModeRef = useRef<DesktopWindowMode | null>(null);
  const lastErrorNoticeRef = useRef<string | null>(null);
  const lastFallbackNoticeRef = useRef<string | null>(null);

  const providers = useMemo(
    () => ({
      "custom-http": createBackendTtsProvider({ api }),
      "xiaomi-mimo": createBackendTtsProvider({ api, providerId: "xiaomi-mimo" }),
      mock: createMockTtsProvider(),
      system: createSystemTtsProvider(),
    }),
    [api],
  );
  const fallbackProvider = settings?.provider && settings.provider !== "system" ? "system" : null;
  const providerResetKey = [
    settings?.provider || "",
    settings?.updated_at || "",
    settings?.key_masked || "",
  ].join(":");

  const queue = useTtsPlaybackQueue({
    providers,
    fallbackProvider,
    onPlaybackStart: (item) => playbackStartRef.current(item),
    onPlaybackEnd: (item, status) => playbackEndRef.current(item, status),
    onProviderFallback: ({ error, fallbackProvider: nextFallbackProvider, provider }) => {
      const noticeKey = `${provider}:${nextFallbackProvider}:${error.code}`;
      if (lastFallbackNoticeRef.current === noticeKey) {
        return;
      }
      lastFallbackNoticeRef.current = noticeKey;
      onNotice({
        tone: "error",
        message: formatTtsProviderFallbackNotice(provider, nextFallbackProvider, error),
      });
    },
    providerResetKey,
  });

  const active = queue.state.status === "synthesizing" || queue.state.status === "playing";
  const speaking = queue.state.status === "playing";
  const enabled = Boolean(
    settings?.enabled &&
      settings.auto_play_assistant_reply &&
      settings.configured &&
      settings.status === "ready",
  );
  const voice = useMemo(() => {
    const selectedVoice = settings?.voice;
    return selectedVoice
      ? {
          id: selectedVoice.id,
          provider: selectedVoice.provider,
          label: selectedVoice.label,
          locale: selectedVoice.locale || undefined,
          gender: normalizeTtsVoiceGender(selectedVoice.gender),
          description: selectedVoice.description || undefined,
        }
      : null;
  }, [
    settings?.voice?.description,
    settings?.voice?.gender,
    settings?.voice?.id,
    settings?.voice?.label,
    settings?.voice?.locale,
    settings?.voice?.provider,
  ]);
  const provider = settings?.provider || "system";
  const speed = settings?.speed ?? 1;
  const volume = settings?.volume ?? 1;
  const cacheEnabled = Boolean(settings?.cache_enabled);
  const waitingCue = useTtsWaitingCue({
    enabled,
    providers,
    provider,
    fallbackProvider,
    voice,
    speed,
    cueSpeed: 0.82,
    volume,
  });

  const bindPetPlaybackHandlers = useCallback(({ onStart, onEnd }: PetPlaybackHandlers) => {
    playbackStartRef.current = onStart || (() => undefined);
    playbackEndRef.current = onEnd || (() => undefined);
  }, []);

  useEffect(() => {
    const error = queue.state.error;
    if (!error) {
      lastErrorNoticeRef.current = null;
      return;
    }
    const noticeKey = `${error.provider || "unknown"}:${error.itemId || "unknown"}:${error.code}:${error.message}`;
    if (lastErrorNoticeRef.current === noticeKey) {
      return;
    }
    lastErrorNoticeRef.current = noticeKey;
    onNotice({
      tone: "error",
      message: formatTtsPlaybackErrorNotice(error),
    });
  }, [
    onNotice,
    queue.state.error?.code,
    queue.state.error?.itemId,
    queue.state.error?.message,
    queue.state.error?.provider,
  ]);

  useEffect(() => {
    const previousMode = previousWindowModeRef.current;
    if (previousMode && previousMode !== windowMode && active) {
      queue.stop("window_mode_changed");
    }
    previousWindowModeRef.current = windowMode;
  }, [active, queue.stop, windowMode]);

  useEffect(() => {
    const stopIfActive = (reason: string) => {
      if (queue.state.status === "synthesizing" || queue.state.status === "playing") {
        queue.stop(reason);
      }
    };
    const handlePageHide = () => stopIfActive("window_hidden");
    const handleBeforeUnload = () => stopIfActive("window_unload");

    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [queue.state.status, queue.stop]);

  return {
    queue,
    waitingCue,
    active,
    speaking,
    enabled,
    provider,
    voice,
    speed,
    volume,
    cacheEnabled,
    bindPetPlaybackHandlers,
  };
}
