import type { TtsSynthesisRequest, TtsSynthesisResult, TtsVoice } from "./ttsTypes";
import {
  assertTtsNotAborted,
  clampTtsSpeed,
  clampTtsVolume,
  createTtsProviderError,
  type TtsProvider,
  type TtsProviderPlaybackOptions,
  type TtsProviderPlaybackResult,
} from "./ttsProvider";

type SystemTtsSynthesisResult = Extract<TtsSynthesisResult, { kind: "system" }>;

export type SystemTtsProviderDependencies = {
  speechSynthesis?: Pick<SpeechSynthesis, "cancel" | "getVoices" | "speak"> | null;
  createUtterance?: (text: string) => SpeechSynthesisUtterance;
};

type ActivePlayback = {
  utterance: SpeechSynthesisUtterance;
  resolve: (value: TtsProviderPlaybackResult<SystemTtsSynthesisResult>) => void;
  reject: (error: Error) => void;
  result: SystemTtsSynthesisResult;
  settled: boolean;
};

export function createSystemTtsProvider(
  dependencies: SystemTtsProviderDependencies = {},
): TtsProvider<SystemTtsSynthesisResult> {
  let active: ActivePlayback | null = null;

  const resolveDependency = () => {
    const speechSynthesis = dependencies.speechSynthesis ?? globalThis.speechSynthesis ?? null;
    const createUtterance =
      dependencies.createUtterance ??
      (typeof globalThis.SpeechSynthesisUtterance === "function"
        ? (text: string) => new globalThis.SpeechSynthesisUtterance(text)
        : null);
    if (!speechSynthesis || !createUtterance) {
      throw createTtsProviderError("system", "provider_not_configured", "System TTS is not available.");
    }
    return { speechSynthesis, createUtterance };
  };

  const settlePlayback = (playback: ActivePlayback, status: "played" | "cancelled", reason?: string) => {
    if (active !== playback || playback.settled) {
      return;
    }
    playback.settled = true;
    active = null;
    playback.resolve({
      provider: "system",
      result: playback.result,
      status,
      reason,
    });
  };

  const settleActive = (status: "played" | "cancelled", reason?: string) => {
    const playback = active;
    if (!playback) {
      return;
    }
    settlePlayback(playback, status, reason);
  };

  return {
    id: "system",

    async synthesize(request: TtsSynthesisRequest, signal?: AbortSignal): Promise<SystemTtsSynthesisResult> {
      assertTtsNotAborted(signal, "system");
      return {
        kind: "system",
        requestId: request.requestId,
        provider: "system",
        text: request.text,
        voice: request.voice,
        speed: clampTtsSpeed(request.speed),
        volume: clampTtsVolume(request.volume),
      };
    },

    async getVoices(): Promise<TtsVoice[]> {
      const { speechSynthesis } = resolveDependency();
      return speechSynthesis.getVoices().map(systemVoiceToTtsVoice);
    },

    play(
      result: SystemTtsSynthesisResult,
      options?: TtsProviderPlaybackOptions,
    ): Promise<TtsProviderPlaybackResult<SystemTtsSynthesisResult>> {
      assertTtsNotAborted(options?.signal, "system");
      const { speechSynthesis, createUtterance } = resolveDependency();
      if (!result.text.trim()) {
        return Promise.resolve({
          provider: "system",
          result,
          status: "played",
        });
      }

      speechSynthesis.cancel();
      settleActive("cancelled", "replaced");

      return new Promise((resolve, reject) => {
        const utterance = createUtterance(result.text);
        const voices = speechSynthesis.getVoices();
        const selectedVoice = findNativeVoice(voices, result.voice);
        utterance.rate = clampTtsSpeed(result.speed);
        utterance.volume = clampTtsVolume(options?.volume, clampTtsVolume(result.volume));
        if (selectedVoice) {
          utterance.voice = selectedVoice;
          utterance.lang = selectedVoice.lang;
        } else if (result.voice?.locale) {
          utterance.lang = result.voice.locale;
        }

        const playback: ActivePlayback = {
          utterance,
          resolve,
          reject,
          result,
          settled: false,
        };
        active = playback;
        utterance.onend = () => settlePlayback(playback, "played");
        utterance.onerror = () => {
          if (active !== playback || playback.settled) {
            return;
          }
          playback.settled = true;
          active = null;
          playback.reject(createTtsProviderError("system", "playback_failed", "System TTS playback failed."));
        };

        options?.signal?.addEventListener(
          "abort",
          () => {
            speechSynthesis.cancel();
            settlePlayback(playback, "cancelled", "aborted");
          },
          { once: true },
        );
        speechSynthesis.speak(utterance);
      });
    },

    stop(reason = "stopped"): void {
      const playback = active;
      if (!playback) {
        return;
      }
      resolveDependency().speechSynthesis.cancel();
      settleActive("cancelled", reason);
    },
  };
}

function systemVoiceToTtsVoice(voice: SpeechSynthesisVoice): TtsVoice {
  return {
    id: voice.voiceURI || voice.name,
    provider: "system",
    label: voice.name,
    locale: voice.lang || undefined,
    gender: "unknown",
    metadata: {
      default: voice.default,
      localService: voice.localService,
      voiceURI: voice.voiceURI,
    },
  };
}

function findNativeVoice(voices: SpeechSynthesisVoice[], requestedVoice: TtsVoice | null): SpeechSynthesisVoice | null {
  if (!requestedVoice) {
    return null;
  }
  return (
    voices.find((voice) => voice.voiceURI === requestedVoice.id) ??
    voices.find((voice) => voice.name === requestedVoice.id) ??
    voices.find((voice) => voice.name === requestedVoice.label) ??
    null
  );
}
