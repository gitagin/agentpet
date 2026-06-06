import type {
  TtsPlaybackError,
  TtsPlaybackErrorCode,
  TtsProviderId,
  TtsSynthesisRequest,
  TtsSynthesisResult,
  TtsVoice,
} from "./ttsTypes";

export type TtsProviderPlaybackStatus = "played" | "cancelled";

export type TtsProviderPlaybackOptions = {
  signal?: AbortSignal;
  volume?: number;
};

export type TtsProviderPlaybackResult<TResult extends TtsSynthesisResult = TtsSynthesisResult> = {
  provider: TtsProviderId;
  result: TResult;
  status: TtsProviderPlaybackStatus;
  reason?: string;
};

export interface TtsProvider<TResult extends TtsSynthesisResult = TtsSynthesisResult> {
  id: TtsProviderId;
  synthesize(request: TtsSynthesisRequest, signal?: AbortSignal): Promise<TResult>;
  play(result: TResult, options?: TtsProviderPlaybackOptions): Promise<TtsProviderPlaybackResult<TResult>>;
  stop(reason?: string): void;
  getVoices?(): Promise<TtsVoice[]>;
}

export class TtsProviderError extends Error {
  playbackError: TtsPlaybackError;

  constructor(playbackError: TtsPlaybackError) {
    super(playbackError.message);
    this.name = "TtsProviderError";
    this.playbackError = playbackError;
    Object.setPrototypeOf(this, TtsProviderError.prototype);
  }
}

export function createTtsProviderError(
  provider: TtsProviderId,
  code: TtsPlaybackErrorCode,
  message: string,
  recoverable = true,
): TtsProviderError {
  return new TtsProviderError({
    code,
    message,
    provider,
    recoverable,
  });
}

export function clampTtsVolume(volume: number | undefined, fallback = 1): number {
  return clampFinite(volume, fallback, 0, 1);
}

export function clampTtsSpeed(speed: number | undefined, fallback = 1): number {
  return clampFinite(speed, fallback, 0.5, 2);
}

export function assertTtsNotAborted(signal: AbortSignal | undefined, provider: TtsProviderId): void {
  if (signal?.aborted) {
    throw createTtsProviderError(provider, "cancelled", "TTS 播放请求已取消。");
  }
}

export function createUnsupportedTtsResultError(
  provider: TtsProviderId,
  result: TtsSynthesisResult,
): TtsProviderError {
  return createTtsProviderError(
    provider,
    "invalid_audio",
    `TTS 服务 ${provider} 无法播放 ${result.kind} 类型的合成结果。`,
  );
}

function clampFinite(value: number | undefined, fallback: number, min: number, max: number): number {
  const candidate = typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.min(max, Math.max(min, candidate));
}
