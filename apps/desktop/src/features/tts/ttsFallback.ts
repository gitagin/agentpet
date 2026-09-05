/**
 * Shared TTS provider-selection and fallback logic.
 *
 * `useTtsPlaybackQueue` and `useTtsWaitingCue` used to carry two parallel
 * copies of the same "pick a provider, fall back on configuration failures,
 * key the synthesis cache" machinery.  The pure helpers live here as plain
 * functions; the per-hook state lives in `useTtsProviderFallback`.
 */
import { useCallback, useEffect, useRef } from "react";

import type { TtsProviderId, TtsSynthesisRequest, TtsSynthesisResult, TtsVoice } from "./ttsTypes";
import { TtsProviderError, type TtsProvider } from "./ttsProvider";

export type TtsProviderRegistry = Readonly<Record<string, TtsProvider<TtsSynthesisResult> | undefined>>;

/** Error codes that mean "this provider cannot work, try the fallback". */
const CONFIGURATION_ERROR_CODES = new Set(["authentication_failed", "credential_missing", "provider_not_configured"]);

export function isConfigurationErrorCode(code: string | undefined): boolean {
  return code !== undefined && CONFIGURATION_ERROR_CODES.has(code);
}

export function isConfigurationError(error: unknown): boolean {
  return error instanceof TtsProviderError && isConfigurationErrorCode(error.playbackError.code);
}

export type SynthesisCacheKeyInput = {
  text: string;
  provider: TtsProviderId;
  voice: TtsVoice | null | undefined;
  speed: number;
  volume: number | null | undefined;
  cacheEnabled: boolean | null | undefined;
};

export function synthesisCacheKey(input: SynthesisCacheKeyInput): string {
  const voice = input.voice?.provider === input.provider ? input.voice : null;
  return JSON.stringify({
    text: input.text,
    provider: input.provider,
    voice: voice?.id ?? null,
    speed: input.speed,
    volume: input.volume ?? null,
    cacheEnabled: input.cacheEnabled ?? null,
  });
}

export function buildSynthesisRequest(
  base: Omit<TtsSynthesisRequest, "text" | "provider" | "voice">,
  text: string,
  providerId: TtsProviderId,
  voice: TtsVoice | null,
): TtsSynthesisRequest {
  return {
    ...base,
    text,
    provider: providerId,
    voice: voice?.provider === providerId ? voice : null,
  };
}

export type UseTtsProviderFallbackOptions = {
  providers: TtsProviderRegistry;
  fallbackProvider?: TtsProviderId | null;
  /** When this value changes, remembered "unavailable" providers are forgotten. */
  resetKey?: unknown;
};

export type SynthesizeWithFallbackParams = {
  providerId: TtsProviderId;
  signal?: AbortSignal;
  buildRequest: (providerId: TtsProviderId) => TtsSynthesisRequest;
  onResolvedProvider?: (provider: TtsProvider<TtsSynthesisResult>, providerId: TtsProviderId) => void;
  onFallback?: (from: TtsProviderId, to: TtsProviderId, error: unknown) => void;
};

export function useTtsProviderFallback({ providers, fallbackProvider = null, resetKey }: UseTtsProviderFallbackOptions) {
  const providersRef = useRef(providers);
  const fallbackProviderRef = useRef<TtsProviderId | null>(fallbackProvider);
  const unavailableProvidersRef = useRef<Set<TtsProviderId>>(new Set());

  useEffect(() => {
    providersRef.current = providers;
  }, [providers]);

  useEffect(() => {
    fallbackProviderRef.current = fallbackProvider;
  }, [fallbackProvider]);

  useEffect(() => {
    unavailableProvidersRef.current.clear();
  }, [fallbackProvider, resetKey]);

  const fallbackProviderFor = useCallback((providerId: TtsProviderId) => {
    const candidate = fallbackProviderRef.current;
    if (!candidate || candidate === providerId || !providersRef.current[candidate]) {
      return null;
    }
    return candidate;
  }, []);

  const resolveProviderId = useCallback(
    (providerId: TtsProviderId) => {
      const fallbackProviderId = fallbackProviderFor(providerId);
      return (!providersRef.current[providerId] || unavailableProvidersRef.current.has(providerId)) && fallbackProviderId
        ? fallbackProviderId
        : providerId;
    },
    [fallbackProviderFor],
  );

  const resolveProvider = useCallback(
    (providerId: TtsProviderId): { provider: TtsProvider<TtsSynthesisResult>; providerId: TtsProviderId } | null => {
      const resolvedId = resolveProviderId(providerId);
      const provider = providersRef.current[resolvedId];
      return provider ? { provider, providerId: resolvedId } : null;
    },
    [resolveProviderId],
  );

  const synthesizeWithFallback = useCallback(
    async ({ providerId, signal, buildRequest, onResolvedProvider, onFallback }: SynthesizeWithFallbackParams) => {
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
        return await provider.synthesize(buildRequest(providerId), signal);
      } catch (error) {
        const fallbackProviderId = fallbackProviderFor(providerId);
        if (!isConfigurationError(error) || !fallbackProviderId || signal?.aborted) {
          throw error;
        }
        const fallback = providersRef.current[fallbackProviderId];
        if (!fallback) {
          throw error;
        }
        unavailableProvidersRef.current.add(providerId);
        onFallback?.(providerId, fallbackProviderId, error);
        onResolvedProvider?.(fallback, fallbackProviderId);
        return fallback.synthesize(buildRequest(fallbackProviderId), signal);
      }
    },
    [fallbackProviderFor],
  );

  return {
    fallbackProviderFor,
    resolveProvider,
    resolveProviderId,
    synthesizeWithFallback,
  };
}
