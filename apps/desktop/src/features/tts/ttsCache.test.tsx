import { describe, expect, it, vi } from "vitest";

import { createBackendTtsProvider } from "./backendTtsProvider";
import type { TtsSynthesisRequest } from "./ttsTypes";

function request(overrides: Partial<TtsSynthesisRequest> = {}): TtsSynthesisRequest {
  return {
    requestId: "tts-cache-request",
    text: "hello cache",
    provider: "custom-http",
    voice: null,
    speed: 1,
    volume: 0.8,
    cacheEnabled: true,
    ...overrides,
  };
}

describe("TTS cache request contract", () => {
  it("passes the cache flag to the backend and preserves cache hit status", async () => {
    const api = {
      synthesizeTts: vi.fn(async () => ({
        provider: "custom-http",
        mime_type: "audio/mpeg",
        audio_base64: btoa("cached-audio"),
        duration_ms: null,
        cache_hit: true,
      })),
    };
    const provider = createBackendTtsProvider({
      api: api as never,
      createObjectUrl: vi.fn(() => "blob:cached-audio"),
      revokeObjectUrl: vi.fn(),
      createAudio: vi.fn(),
    });

    const result = await provider.synthesize(request());

    expect(api.synthesizeTts).toHaveBeenCalledWith(
      {
        text: "hello cache",
        provider: "custom-http",
        voice: null,
        speed: 1,
        volume: 0.8,
        cache_enabled: true,
      },
      undefined,
    );
    expect(result.cacheHit).toBe(true);
  });
});
