function createProxyManager({ baseUrl, sessionToken }) {
  const activeSseStreams = new Map();

  function resolveSidecarUrl(pathOrUrl) {
    if (typeof pathOrUrl !== "string") {
      throw new Error("API path must be a string.");
    }

    const trimmed = pathOrUrl.trim();
    if (!trimmed) {
      throw new Error("API path is required.");
    }

    const base = new URL(baseUrl);
    const target = trimmed.startsWith("http://") || trimmed.startsWith("https://")
      ? new URL(trimmed)
      : new URL(trimmed, base);

    if (target.origin !== base.origin) {
      throw new Error("Only sidecar API requests are allowed.");
    }
    if (!target.pathname.startsWith("/api/")) {
      throw new Error("Only /api requests are allowed.");
    }

    return target;
  }

  function sanitizeRendererHeaders(headers) {
    const sanitized = new Headers();
    if (!headers || typeof headers !== "object") {
      return sanitized;
    }

    const forbidden = new Set(["authorization", "cookie", "host", "origin", "referer"]);
    for (const [key, value] of Object.entries(headers)) {
      const normalizedKey = key.toLowerCase();
      if (forbidden.has(normalizedKey) || value == null) {
        continue;
      }
      if (Array.isArray(value)) {
        sanitized.set(key, value.join(", "));
        continue;
      }
      sanitized.set(key, String(value));
    }

    return sanitized;
  }

  function normalizeApiRequestOptions(options) {
    const method = typeof options?.method === "string" ? options.method.toUpperCase() : "GET";
    const allowedMethods = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);
    if (!allowedMethods.has(method)) {
      throw new Error("Unsupported API request method.");
    }

    const headers = sanitizeRendererHeaders(options?.headers);
    if (options?.auth !== false) {
      headers.set("Authorization", `Bearer ${sessionToken}`);
    }

    return {
      method,
      headers,
      body: typeof options?.body === "string" ? options.body : undefined,
    };
  }

  async function proxyApiRequest(pathOrUrl, options) {
    const target = resolveSidecarUrl(pathOrUrl);
    const init = normalizeApiRequestOptions(options);
    const response = await fetch(target, init);
    const body = await response.text();
    const headers = {};
    response.headers.forEach((value, key) => {
      headers[key] = value;
    });

    return {
      status: response.status,
      statusText: response.statusText,
      headers,
      body,
    };
  }

  function sendSseEvent(sender, channel, streamId, payload) {
    if (sender.isDestroyed()) {
      return;
    }
    sender.send(channel, streamId, payload);
  }

  async function startSseStream(sender, streamId, pathOrUrl) {
    if (typeof streamId !== "string" || !/^[A-Za-z0-9_-]{8,80}$/.test(streamId)) {
      throw new Error("Invalid SSE stream id.");
    }
    if (activeSseStreams.has(streamId)) {
      throw new Error("SSE stream already exists.");
    }

    const controller = new AbortController();
    activeSseStreams.set(streamId, { controller, sender });

    try {
      const target = resolveSidecarUrl(pathOrUrl);
      const response = await fetch(target, {
        method: "GET",
        headers: {
          Accept: "text/event-stream",
          Authorization: `Bearer ${sessionToken}`,
        },
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        const errorBody = await response.text();
        sendSseEvent(sender, "agent-pet:sse-error", streamId, {
          status: response.status,
          statusText: response.statusText,
          body: errorBody,
        });
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        sendSseEvent(sender, "agent-pet:sse-chunk", streamId, decoder.decode(value, { stream: true }));
      }
      const trailing = decoder.decode();
      if (trailing) {
        sendSseEvent(sender, "agent-pet:sse-chunk", streamId, trailing);
      }
      sendSseEvent(sender, "agent-pet:sse-end", streamId, null);
    } catch (error) {
      if (!controller.signal.aborted) {
        sendSseEvent(sender, "agent-pet:sse-error", streamId, {
          message: error instanceof Error ? error.message : String(error),
        });
      }
    } finally {
      activeSseStreams.delete(streamId);
    }
  }

  function cancelSseStream(streamId) {
    const active = activeSseStreams.get(streamId);
    active?.controller.abort();
    activeSseStreams.delete(streamId);
  }

  return {
    proxyApiRequest,
    startSseStream,
    cancelSseStream,
  };
}

module.exports = {
  createProxyManager,
};
