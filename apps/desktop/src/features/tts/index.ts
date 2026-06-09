export type {
  TtsPlaybackError,
  TtsPlaybackErrorCode,
  TtsPlaybackItem,
  TtsPlaybackState,
  TtsPlaybackStatus,
  TtsProviderId,
  TtsSettings,
  TtsSynthesisRequest,
  TtsSynthesisResult,
  TtsVoice,
  TtsVoiceGender,
} from "./ttsTypes";

export {
  assertTtsNotAborted,
  clampTtsSpeed,
  clampTtsVolume,
  createTtsProviderError,
  createUnsupportedTtsResultError,
  TtsProviderError,
} from "./ttsProvider";
export type {
  TtsProvider,
  TtsProviderPlaybackOptions,
  TtsProviderPlaybackResult,
  TtsProviderPlaybackStatus,
} from "./ttsProvider";

export { createMockTtsProvider } from "./mockTtsProvider";
export type { MockTtsProviderOptions } from "./mockTtsProvider";

export { createSystemTtsProvider } from "./systemTtsProvider";
export type { SystemTtsProviderDependencies } from "./systemTtsProvider";

export { createBackendTtsProvider } from "./backendTtsProvider";
export type { BackendTtsProviderOptions } from "./backendTtsProvider";

export { useTtsPlaybackQueue } from "./useTtsPlaybackQueue";
export type {
  TtsPlaybackQueueController,
  TtsProviderRegistry,
  UseTtsPlaybackQueueOptions,
} from "./useTtsPlaybackQueue";

export { useTtsWaitingCue } from "./useTtsWaitingCue";
export type { TtsWaitingCueController, UseTtsWaitingCueOptions } from "./useTtsWaitingCue";
