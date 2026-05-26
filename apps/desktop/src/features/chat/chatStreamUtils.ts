import type { Citation } from "../../types";
import type { SseEvent } from "../../services/sse";

export function parseJson(data: string): Record<string, unknown> | null {
  if (!data) {
    return null;
  }
  try {
    return JSON.parse(data) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function extractSseText(sseEvent: SseEvent, payload: Record<string, unknown> | null): string {
  if (payload) {
    for (const key of ["text", "token", "content", "message", "data"]) {
      const value = payload[key];
      if (typeof value === "string" && value) {
        return value;
      }
    }
  }
  if ((sseEvent.event === "token" || sseEvent.event === "message") && !payload) {
    return sseEvent.data;
  }
  return "";
}

export function pickPayloadString(payload: Record<string, unknown> | null, keys: string[]): string | null {
  if (!payload) {
    return null;
  }
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

export function isCitationPayload(value: unknown): value is Citation {
  return Boolean(
    value &&
      typeof value === "object" &&
      "relative_path" in value &&
      typeof (value as { relative_path?: unknown }).relative_path === "string",
  );
}
