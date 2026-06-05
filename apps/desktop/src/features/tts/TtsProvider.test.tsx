import { afterEach, describe, expect, it, vi } from "vitest";

import { createBackendTtsProvider } from "./backendTtsProvider";
import { createMockTtsProvider } from "./mockTtsProvider";
import { createSystemTtsProvider } from "./systemTtsProvider";
import { TtsProviderError } from "./ttsProvider";
import { ApiError } from "../../services/apiClient";
import type { ApiErrorBody } from "../../types";
import type { TtsSynthesisRequest, TtsVoice } from "./ttsTypes";

function request(overrides: Partial<TtsSynthesisRequest> = {}): TtsSynthesisRequest {
  return {
    requestId: "tts-request-1",
    text: "你好，今天先做一个短句播放验收。",
    provider: "system",
    voice: null,
    speed: 1,
    volume: 1,
    ...overrides,
  };
}

function fakeVoice(overrides: Partial<SpeechSynthesisVoice> = {}): SpeechSynthesisVoice {
  return {
    default: true,
    lang: "zh-CN",
    localService: true,
    name: "Microsoft Xiaoxiao",
    voiceURI: "system-voice-cn",
    ...overrides,
  } as SpeechSynthesisVoice;
}

function fakeUtterance(text: string): SpeechSynthesisUtterance {
  return {
    text,
    lang: "",
    pitch: 1,
    rate: 1,
    volume: 1,
    voice: null,
    onboundary: null,
    onend: null,
    onerror: null,
    onmark: null,
    onpause: null,
    onresume: null,
    onstart: null,
    addEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as SpeechSynthesisUtterance;
}

describe("TTS providers", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("synthesizes and plays one controlled mock playback", async () => {
    vi.useFakeTimers();
    const provider = createMockTtsProvider({ durationMs: 50 });
    const result = await provider.synthesize(request({ provider: "mock" }));

    expect(result).toEqual({
      kind: "mock",
      requestId: "tts-request-1",
      provider: "mock",
      durationMs: 50,
    });

    const playback = provider.play(result);
    await vi.advanceTimersByTimeAsync(50);

    await expect(playback).resolves.toMatchObject({
      provider: "mock",
      status: "played",
      result,
    });
  });

  it("cancels active mock playback through stop", async () => {
    vi.useFakeTimers();
    const provider = createMockTtsProvider({ durationMs: 1000 });
    const result = await provider.synthesize(request({ provider: "mock" }));
    const playback = provider.play(result);

    provider.stop("user_stopped");

    await expect(playback).resolves.toMatchObject({
      provider: "mock",
      status: "cancelled",
      reason: "user_stopped",
    });
    await vi.advanceTimersByTimeAsync(1000);
  });

  it("maps system voices and speaks one system utterance", async () => {
    const nativeVoice = fakeVoice();
    const spokenUtterances: SpeechSynthesisUtterance[] = [];
    const speechSynthesis: Pick<SpeechSynthesis, "cancel" | "getVoices" | "speak"> = {
      cancel: vi.fn(),
      getVoices: vi.fn(() => [nativeVoice]),
      speak: vi.fn((utterance: SpeechSynthesisUtterance) => {
        spokenUtterances.push(utterance);
        utterance.onend?.call(utterance, {} as SpeechSynthesisEvent);
      }),
    };
    const provider = createSystemTtsProvider({
      speechSynthesis,
      createUtterance: fakeUtterance,
    });
    const requestedVoice: TtsVoice = {
      id: "system-voice-cn",
      provider: "system",
      label: "Microsoft Xiaoxiao",
      locale: "zh-CN",
    };

    await expect(provider.getVoices?.()).resolves.toEqual([
      {
        id: "system-voice-cn",
        provider: "system",
        label: "Microsoft Xiaoxiao",
        locale: "zh-CN",
        gender: "unknown",
        metadata: {
          default: true,
          localService: true,
          voiceURI: "system-voice-cn",
        },
      },
    ]);

    const result = await provider.synthesize(
      request({
        voice: requestedVoice,
        speed: 1.25,
        volume: 0.8,
      }),
    );
    const playback = await provider.play(result, { volume: 0.4 });

    expect(playback.status).toBe("played");
    expect(speechSynthesis.cancel).toHaveBeenCalledTimes(1);
    expect(speechSynthesis.speak).toHaveBeenCalledTimes(1);
    const spokenUtterance = spokenUtterances[0];
    expect(spokenUtterance.text).toBe("你好，今天先做一个短句播放验收。");
    expect(spokenUtterance.rate).toBe(1.25);
    expect(spokenUtterance.volume).toBe(0.4);
    expect(spokenUtterance.voice).toBe(nativeVoice);
    expect(spokenUtterance.lang).toBe("zh-CN");
  });

  it("reports system provider availability without blocking text chat", async () => {
    const provider = createSystemTtsProvider({
      speechSynthesis: null,
    });

    await expect(provider.getVoices?.()).rejects.toBeInstanceOf(TtsProviderError);
    await expect(provider.getVoices?.()).rejects.toMatchObject({
      playbackError: {
        code: "provider_not_configured",
        provider: "system",
        recoverable: true,
      },
    });
  });

  it("synthesizes custom HTTP provider audio through the backend", async () => {
    const play = vi.fn(async function play(this: HTMLAudioElement) {
      this.onended?.({} as Event);
    });
    const pause = vi.fn();
    const revokeObjectUrl = vi.fn();
    const createObjectUrl = vi.fn(() => "blob:tts-audio");
    const api = {
      synthesizeTts: vi.fn(async () => ({
        provider: "custom-http",
        mime_type: "audio/mpeg",
        audio_base64: btoa("audio-bytes"),
        duration_ms: null,
        cache_hit: false,
      })),
    };
    const provider = createBackendTtsProvider({
      api: api as never,
      createObjectUrl,
      revokeObjectUrl,
      createAudio: (url) => ({
        src: url,
        volume: 1,
        onended: null,
        onerror: null,
        play,
        pause,
      } as unknown as HTMLAudioElement),
    });

    const result = await provider.synthesize(
      request({ provider: "custom-http", text: "hello", volume: 0.5, cacheEnabled: true }),
    );
    expect(api.synthesizeTts).toHaveBeenCalledWith(
      {
        text: "hello",
        provider: "custom-http",
        voice: null,
        speed: 1,
        volume: 0.5,
        cache_enabled: true,
      },
      undefined,
    );
    expect(result).toMatchObject({
      kind: "audio",
      provider: "custom-http",
      mimeType: "audio/mpeg",
      audioUrl: "blob:tts-audio",
    });

    await expect(provider.play(result, { volume: 0.4 })).resolves.toMatchObject({
      provider: "custom-http",
      status: "played",
    });
    expect(play).toHaveBeenCalledTimes(1);
    expect(pause).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:tts-audio");
  });

  it("maps backend TTS timeout errors into recoverable playback errors", async () => {
    const body: ApiErrorBody = {
      error: {
        code: "provider_timeout",
        message: "语音服务请求超时，请稍后重试。",
      },
    };
    const api = {
      synthesizeTts: vi.fn(async () => {
        throw new ApiError("语音服务请求超时，请稍后重试。", 504, body);
      }),
    };
    const provider = createBackendTtsProvider({ api: api as never });

    await expect(provider.synthesize(request({ provider: "custom-http" }))).rejects.toMatchObject({
      playbackError: {
        code: "synthesis_timeout",
        provider: "custom-http",
        recoverable: true,
      },
    });
  });

  it("rejects custom HTTP responses that are not playable audio", async () => {
    const api = {
      synthesizeTts: vi.fn(async () => ({
        provider: "custom-http",
        mime_type: "application/json",
        audio_base64: btoa("{}"),
        duration_ms: null,
        cache_hit: false,
      })),
    };
    const provider = createBackendTtsProvider({ api: api as never });

    await expect(provider.synthesize(request({ provider: "custom-http" }))).rejects.toMatchObject({
      playbackError: {
        code: "invalid_audio",
        provider: "custom-http",
        recoverable: true,
      },
    });
  });

  it("maps blocked audio playback without affecting synthesized text flow", async () => {
    const play = vi.fn(async () => {
      throw new Error("NotAllowedError");
    });
    const pause = vi.fn();
    const revokeObjectUrl = vi.fn();
    const api = {
      synthesizeTts: vi.fn(async () => ({
        provider: "custom-http",
        mime_type: "audio/mpeg",
        audio_base64: btoa("audio-bytes"),
        duration_ms: null,
        cache_hit: false,
      })),
    };
    const provider = createBackendTtsProvider({
      api: api as never,
      createObjectUrl: () => "blob:blocked-audio",
      revokeObjectUrl,
      createAudio: (url) => ({
        src: url,
        volume: 1,
        onended: null,
        onerror: null,
        play,
        pause,
      } as unknown as HTMLAudioElement),
    });
    const result = await provider.synthesize(request({ provider: "custom-http" }));

    await expect(provider.play(result)).rejects.toMatchObject({
      playbackError: {
        code: "playback_blocked",
        provider: "custom-http",
        recoverable: true,
      },
    });
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:blocked-audio");
  });
});
