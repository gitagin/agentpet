import type { DesktopApi } from "../../services/desktopApi";
import { ApiError } from "../../services/apiClient";
import type { TtsSynthesisApiResponse } from "../../types";
import type { TtsPlaybackErrorCode, TtsSynthesisRequest, TtsSynthesisResult } from "./ttsTypes";
import {
  assertTtsNotAborted,
  clampTtsSpeed,
  clampTtsVolume,
  createTtsProviderError,
  type TtsProvider,
  type TtsProviderPlaybackOptions,
  type TtsProviderPlaybackResult,
} from "./ttsProvider";

type AudioTtsSynthesisResult = Extract<TtsSynthesisResult, { kind: "audio" }>;

type ActivePlayback = {
  audio: HTMLAudioElement;
  objectUrl: string;
  result: AudioTtsSynthesisResult;
  resolve: (value: TtsProviderPlaybackResult<AudioTtsSynthesisResult>) => void;
  reject: (error: Error) => void;
  settled: boolean;
};

export type BackendTtsProviderOptions = {
  api: DesktopApi;
  providerId?: string;
  createAudio?: (url: string) => HTMLAudioElement;
  createObjectUrl?: (blob: Blob) => string;
  revokeObjectUrl?: (url: string) => void;
};

export function createBackendTtsProvider({
  api,
  providerId = "custom-http",
  createAudio = (url) => new Audio(url),
  createObjectUrl = (blob) => URL.createObjectURL(blob),
  revokeObjectUrl = (url) => URL.revokeObjectURL(url),
}: BackendTtsProviderOptions): TtsProvider<AudioTtsSynthesisResult> {
  let active: ActivePlayback | null = null;

  const finishPlayback = (playback: ActivePlayback, status: "played" | "cancelled", reason?: string) => {
    if (active !== playback || playback.settled) {
      return;
    }
    playback.settled = true;
    active = null;
    playback.audio.pause();
    revokeObjectUrl(playback.objectUrl);
    playback.resolve({
      provider: providerId,
      result: playback.result,
      status,
      reason,
    });
  };

  const cancelActive = (reason: string) => {
    const playback = active;
    if (!playback) {
      return;
    }
    finishPlayback(playback, "cancelled", reason);
  };

  return {
    id: providerId,

    async synthesize(request: TtsSynthesisRequest, signal?: AbortSignal): Promise<AudioTtsSynthesisResult> {
      assertTtsNotAborted(signal, providerId);
      let response: TtsSynthesisApiResponse;
      try {
        response = await api.synthesizeTts(
          {
            text: request.text,
            provider: providerId,
            voice: request.voice
              ? {
                  id: request.voice.id,
                  provider: request.voice.provider,
                  label: request.voice.label,
                  locale: request.voice.locale || null,
                  gender: request.voice.gender || null,
                  description: request.voice.description || null,
                }
              : null,
            speed: clampTtsSpeed(request.speed),
            volume: clampTtsVolume(request.volume),
            cache_enabled: request.cacheEnabled,
          },
          signal,
        );
      } catch (error) {
        throw mapBackendTtsError(error, providerId);
      }
      assertTtsNotAborted(signal, providerId);
      const blob = responseToBlob(response);
      const audioUrl = createObjectUrl(blob);
      return {
        kind: "audio",
        requestId: request.requestId,
        provider: providerId,
        mimeType: response.mime_type,
        audioUrl,
        durationMs: response.duration_ms ?? undefined,
        cacheHit: response.cache_hit,
      };
    },

    play(
      result: AudioTtsSynthesisResult,
      options?: TtsProviderPlaybackOptions,
    ): Promise<TtsProviderPlaybackResult<AudioTtsSynthesisResult>> {
      assertTtsNotAborted(options?.signal, providerId);
      cancelActive("replaced");
      const audio = createAudio(result.audioUrl);
      audio.volume = clampTtsVolume(options?.volume);

      return new Promise((resolve, reject) => {
        const playback: ActivePlayback = {
          audio,
          objectUrl: result.audioUrl,
          result,
          resolve,
          reject,
          settled: false,
        };
        active = playback;
        const cleanupAndReject = (error: Error) => {
          if (active !== playback || playback.settled) {
            return;
          }
          playback.settled = true;
          active = null;
          revokeObjectUrl(playback.objectUrl);
          reject(error);
        };
        audio.onended = () => finishPlayback(playback, "played");
        audio.onerror = () =>
          cleanupAndReject(createTtsProviderError(providerId, "playback_failed", "TTS audio playback failed."));
        options?.signal?.addEventListener(
          "abort",
          () => finishPlayback(playback, "cancelled", "aborted"),
          { once: true },
        );
        void audio.play().catch((error: unknown) => {
          cleanupAndReject(
            createTtsProviderError(
              providerId,
              "playback_blocked",
              error instanceof Error ? error.message : "TTS audio playback was blocked.",
            ),
          );
        });
      });
    },

    stop(reason = "stopped"): void {
      cancelActive(reason);
    },
  };
}

function responseToBlob(response: TtsSynthesisApiResponse): Blob {
  if (!response.mime_type.toLowerCase().startsWith("audio/")) {
    throw createTtsProviderError(
      response.provider || "custom-http",
      "invalid_audio",
      "TTS provider returned a non-audio response.",
    );
  }
  const audioBuffer = base64ToArrayBuffer(response.audio_base64, response.provider || "custom-http");
  if (audioBuffer.byteLength === 0) {
    throw createTtsProviderError(
      response.provider || "custom-http",
      "invalid_audio",
      "TTS provider returned empty audio.",
    );
  }
  return new Blob([audioBuffer], { type: response.mime_type });
}

function base64ToArrayBuffer(value: string, providerId: string): ArrayBuffer {
  let binary = "";
  try {
    binary = atob(value);
  } catch {
    throw createTtsProviderError(providerId, "invalid_audio", "TTS provider returned invalid audio data.");
  }
  const buffer = new ArrayBuffer(binary.length);
  const bytes = new Uint8Array(buffer);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return buffer;
}

function mapBackendTtsError(error: unknown, providerId: string) {
  if (error instanceof ApiError) {
    const code = mapBackendTtsErrorCode(error.code, error.status);
    return createTtsProviderError(providerId, code, error.message || fallbackTtsErrorMessage(code));
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return createTtsProviderError(providerId, "cancelled", "TTS playback request was cancelled.");
  }
  return createTtsProviderError(
    providerId,
    "provider_failed",
    error instanceof Error ? error.message : fallbackTtsErrorMessage("provider_failed"),
  );
}

function mapBackendTtsErrorCode(code: string | undefined, status: number): TtsPlaybackErrorCode {
  switch (code) {
    case "disabled":
      return "disabled";
    case "provider_not_configured":
    case "provider_mismatch":
    case "local_provider":
      return "provider_not_configured";
    case "credential_missing":
      return "credential_missing";
    case "authentication_failed":
      return "authentication_failed";
    case "provider_timeout":
      return "synthesis_timeout";
    case "provider_unreachable":
      return "provider_unreachable";
    case "rate_limited":
      return "rate_limited";
    case "unsupported_format":
      return "unsupported_format";
    case "invalid_audio":
      return "invalid_audio";
    case "provider_failed":
      return "provider_failed";
    default:
      if (status === 401 || status === 403) {
        return "authentication_failed";
      }
      if (status === 408 || status === 504) {
        return "synthesis_timeout";
      }
      if (status === 429) {
        return "rate_limited";
      }
      return "provider_failed";
  }
}

function fallbackTtsErrorMessage(code: TtsPlaybackErrorCode): string {
  switch (code) {
    case "disabled":
      return "TTS playback is disabled.";
    case "provider_not_configured":
      return "TTS provider is not configured.";
    case "credential_missing":
      return "TTS provider key is missing.";
    case "authentication_failed":
      return "TTS provider authentication failed.";
    case "synthesis_timeout":
      return "TTS provider request timed out.";
    case "provider_unreachable":
      return "TTS provider is unreachable.";
    case "rate_limited":
      return "TTS provider is rate limited.";
    case "unsupported_format":
      return "TTS audio format is not supported.";
    case "invalid_audio":
      return "TTS provider returned invalid audio.";
    case "playback_blocked":
      return "TTS audio playback was blocked.";
    case "playback_failed":
      return "TTS audio playback failed.";
    case "cancelled":
      return "TTS playback request was cancelled.";
    default:
      return "TTS provider failed.";
  }
}
