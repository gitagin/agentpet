import type { DesktopSseError } from "../types";
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

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

export async function fetchSseStream(
  client: ApiClient,
  pathOrUrl: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  if (window.agentDesktop?.startSseStream && window.agentDesktop.onSseChunk && window.agentDesktop.onSseEnd && window.agentDesktop.onSseError) {
    return fetchDesktopSseStream(pathOrUrl, handlers, signal);
  }

  const response = await fetch(client.toUrl(pathOrUrl), {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
    },
    signal,
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { error?: { message?: string } };
      message = body.error?.message || message;
    } catch {
      message = `${response.status} ${response.statusText}`;
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
    let chunk: Uint8Array;
    try {
      const result = await reader.read();
      if (result.done) {
        break;
      }
      chunk = result.value;
    } catch (error) {
      // 只有读取出错才算"连接中断"。事件处理里的异常必须原样抛出:把它也说成
      // 网络故障会让渲染层的 bug 无法定位。
      if (isAbortError(error) || error instanceof ApiError) {
        throw error;
      }
      throw new ApiError("流式连接意外中断。", 0);
    }

    buffer = emitSseChunk(buffer + decoder.decode(chunk, { stream: true }), handlers);
  }

  emitFinalSseChunk(buffer + decoder.decode(), handlers);
}

function fetchDesktopSseStream(
  pathOrUrl: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const streamId = createStreamId();
  let buffer = "";
  let opened = false;

  return new Promise((resolve, reject) => {
    const cleanupCallbacks: Array<() => void> = [];
    const cleanup = () => {
      for (const cleanupCallback of cleanupCallbacks) {
        cleanupCallback();
      }
      signal?.removeEventListener("abort", onAbort);
    };
    const finish = (callback: () => void) => {
      cleanup();
      callback();
    };
    const onAbort = () => {
      void window.agentDesktop?.cancelSseStream?.(streamId);
      finish(() => reject(new DOMException("操作已取消。", "AbortError")));
    };

    cleanupCallbacks.push(window.agentDesktop?.onSseChunk?.((incomingStreamId, chunk) => {
      if (incomingStreamId !== streamId) {
        return;
      }
      if (!opened) {
        opened = true;
        handlers.onOpen?.();
      }
      try {
        buffer = emitSseChunk(buffer + chunk, handlers);
      } catch (error) {
        // IPC 回调里抛出的异常不会回到这个 Promise:不在这里拒绝,调用方会一直等,
        // 而渲染层的真实错误彻底消失。
        finish(() => reject(error instanceof Error ? error : new Error(String(error))));
      }
    }) ?? (() => undefined));

    cleanupCallbacks.push(window.agentDesktop?.onSseEnd?.((incomingStreamId) => {
      if (incomingStreamId !== streamId) {
        return;
      }
      try {
        emitFinalSseChunk(buffer, handlers);
      } catch (error) {
        finish(() => reject(error instanceof Error ? error : new Error(String(error))));
        return;
      }
      finish(resolve);
    }) ?? (() => undefined));

    cleanupCallbacks.push(window.agentDesktop?.onSseError?.((incomingStreamId, error) => {
      if (incomingStreamId !== streamId) {
        return;
      }
      finish(() => reject(toSseApiError(error)));
    }) ?? (() => undefined));

    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });

    window.agentDesktop?.startSseStream?.(streamId, pathOrUrl).catch((error: unknown) => {
      finish(() => reject(error instanceof Error ? error : new Error(String(error))));
    });
  });
}

function emitSseChunk(buffer: string, handlers: StreamHandlers): string {
  const normalized = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const parts = normalized.split("\n\n");
  const nextBuffer = parts.pop() || "";

  for (const part of parts) {
    const event = parseSseEvent(part);
    if (event) {
      handlers.onEvent(event);
    }
  }

  return nextBuffer;
}

function emitFinalSseChunk(buffer: string, handlers: StreamHandlers): void {
  const finalEvent = parseSseEvent(buffer);
  if (finalEvent) {
    handlers.onEvent(finalEvent);
  }
}

function toSseApiError(error: DesktopSseError): ApiError {
  let message = error.message || `${error.status ?? 0} ${error.statusText ?? "实时回复流连接失败"}`;
  if (error.body) {
    try {
      const body = JSON.parse(error.body) as { error?: { message?: string } };
      message = body.error?.message || message;
    } catch {
      message = error.body || message;
    }
  }
  return new ApiError(message, error.status ?? 0);
}

function createStreamId(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `sse-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
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
