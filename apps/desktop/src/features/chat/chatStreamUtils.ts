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
  if (sseEvent.data.trim() === "[DONE]") {
    return "";
  }
  if (payload) {
    const choiceText = extractChoiceText(payload.choices);
    if (choiceText) {
      return choiceText;
    }
    for (const key of ["text", "token", "content", "message", "data", "reply", "answer", "delta"]) {
      const text = coercePayloadText(payload[key]);
      if (text) {
        return text;
      }
    }
  }
  if ((sseEvent.event === "token" || sseEvent.event === "message") && !payload) {
    return sseEvent.data;
  }
  return "";
}

function extractChoiceText(value: unknown): string {
  if (!Array.isArray(value)) {
    return "";
  }
  for (const choice of value) {
    if (!choice || typeof choice !== "object") {
      continue;
    }
    const record = choice as Record<string, unknown>;
    const text =
      coercePayloadText(record.delta) ||
      coercePayloadText(record.message) ||
      coercePayloadText(record.text) ||
      coercePayloadText(record.content);
    if (text) {
      return text;
    }
  }
  return "";
}

function coercePayloadText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(coercePayloadText).join("");
  }
  if (!value || typeof value !== "object") {
    return "";
  }
  const record = value as Record<string, unknown>;
  return (
    coercePayloadText(record.content) ||
    coercePayloadText(record.text) ||
    coercePayloadText(record.value) ||
    coercePayloadText(record.message)
  );
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
