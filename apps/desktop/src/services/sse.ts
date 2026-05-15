import { ApiError, ApiClient } from "./apiClient";

export type SseEvent = {
  event: string;
  data: string;
  id?: string;
  retry?: number;
};

export type StreamHandlers = {
  onEvent: (event: SseEvent) => void;
  onOpen?: () => void;
};

export async function fetchSseStream(
  client: ApiClient,
  pathOrUrl: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = client.getSessionToken();
  if (!token) {
    throw new ApiError("流式响应需要会话令牌。", 401);
  }

  const response = await fetch(client.toUrl(pathOrUrl), {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
      Authorization: `Bearer ${token}`,
    },
    signal,
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { error?: { message?: string } };
      message = body.error?.message || message;
    } catch {
      // 流式端点在早期失败时可能返回纯文本。
    }
    throw new ApiError(message, response.status);
  }

  if (!response.body) {
    throw new ApiError("流式响应没有可读取的内容。", 0);
  }

  handlers.onOpen?.();

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const normalized = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const parts = normalized.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const event = parseSseEvent(part);
      if (event) {
        handlers.onEvent(event);
      }
    }
  }

  buffer += decoder.decode();
  const finalEvent = parseSseEvent(buffer);
  if (finalEvent) {
    handlers.onEvent(finalEvent);
  }
}

function parseSseEvent(raw: string): SseEvent | null {
  const event: SseEvent = {
    event: "message",
    data: "",
  };
  const dataLines: string[] = [];

  for (const line of raw.split("\n")) {
    if (!line || line.startsWith(":")) {
      continue;
    }

    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");

    if (field === "event") {
      event.event = value || "message";
    } else if (field === "data") {
      dataLines.push(value);
    } else if (field === "id") {
      event.id = value;
    } else if (field === "retry") {
      const retry = Number(value);
      if (Number.isFinite(retry)) {
        event.retry = retry;
      }
    }
  }

  event.data = dataLines.join("\n");
  if (!event.data && event.event === "message" && !event.id) {
    return null;
  }

  return event;
}
