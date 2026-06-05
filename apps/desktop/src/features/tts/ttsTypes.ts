export type TtsProviderId = "system" | "mock" | "custom-http" | (string & {});

export type TtsVoiceGender = "female" | "male" | "neutral" | "unknown";

export type TtsVoice = {
  id: string;
  provider: TtsProviderId;
  label: string;
  locale?: string;
  gender?: TtsVoiceGender;
  description?: string;
  metadata?: Record<string, string | number | boolean | null>;
};

export type TtsSettings = {
  enabled: boolean;
  autoPlayAssistantReply: boolean;
  autoPlayReminders: boolean;
  provider: TtsProviderId;
  voice: TtsVoice | null;
  speed: number;
  volume: number;
  cacheEnabled: boolean;
  nightQuietMode: boolean;
};

export type TtsSynthesisRequest = {
  requestId: string;
  text: string;
  provider: TtsProviderId;
  voice: TtsVoice | null;
  speed: number;
  volume?: number;
  cacheEnabled?: boolean;
};

export type TtsSynthesisResult =
  | {
      kind: "audio";
      requestId: string;
      provider: TtsProviderId;
      mimeType: string;
      audioUrl: string;
      durationMs?: number;
      cacheHit?: boolean;
    }
  | {
      kind: "system";
      requestId: string;
      provider: "system";
      text: string;
      voice: TtsVoice | null;
      speed: number;
      volume?: number;
    }
  | {
      kind: "mock";
      requestId: string;
      provider: "mock";
      durationMs?: number;
    };

export type TtsPlaybackItem = {
  id: string;
  messageId: string;
  pageIndex: number;
  pageCount: number;
  text: string;
  synthesis: TtsSynthesisRequest;
};

export type TtsPlaybackStatus = "idle" | "synthesizing" | "playing" | "paused" | "cancelled" | "failed";

export type TtsPlaybackErrorCode =
  | "disabled"
  | "provider_not_configured"
  | "credential_missing"
  | "authentication_failed"
  | "provider_failed"
  | "synthesis_timeout"
  | "provider_unreachable"
  | "rate_limited"
  | "unsupported_format"
  | "invalid_audio"
  | "playback_blocked"
  | "playback_failed"
  | "cancelled"
  | "unknown";

export type TtsPlaybackError = {
  code: TtsPlaybackErrorCode;
  message: string;
  provider?: TtsProviderId;
  itemId?: string;
  recoverable: boolean;
};

export type TtsPlaybackState = {
  status: TtsPlaybackStatus;
  currentItem: TtsPlaybackItem | null;
  queue: TtsPlaybackItem[];
  error: TtsPlaybackError | null;
  volume: number;
  updatedAt: string;
};
