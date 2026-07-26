// 幂等 GET 在后端启动窗口内的重试参数：12 次 x 250ms ≈ 3 秒，
// 与 sidecar 冷启动到可服务的常见耗时同数量级。
const CONNECTION_RETRY_ATTEMPTS = 12;
const CONNECTION_RETRY_DELAY_MS = 250;

function createProxyManager({ baseUrl, getBaseUrl, sessionToken }) {
  const activeSseStreams = new Map();
  // 只有 GET 可安全重试；HEAD 从未被 normalizeApiRequestOptions 放行，不再假装支持。
  const retryableMethods = new Set(["GET"]);
  const allowedProxyRoutes = createAllowedProxyRoutes();
  // 端口搜索可能在运行期切换后端 baseUrl，因此每次请求时解析而不是构造时固化。
  const resolveBaseUrl = () => (typeof getBaseUrl === "function" ? getBaseUrl() : baseUrl);

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function isConnectionRefused(error) {
    return error?.cause?.code === "ECONNREFUSED" || error?.code === "ECONNREFUSED";
  }

  function sidecarUnavailableResponse(error) {
    return {
      status: 503,
      statusText: "服务暂不可用",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        error: {
          code: "sidecar_starting",
          message: "本地后端正在启动，请稍候再试。",
          details: {
            original_error: error instanceof Error ? error.message : String(error),
          },
        },
      }),
    };
  }

  function resolveSidecarUrl(pathOrUrl) {
    if (typeof pathOrUrl !== "string") {
      throw new Error("接口路径必须是字符串。");
    }

    const trimmed = pathOrUrl.trim();
    if (!trimmed) {
      throw new Error("接口路径不能为空。");
    }

    const base = new URL(resolveBaseUrl());
    const target = trimmed.startsWith("http://") || trimmed.startsWith("https://")
      ? new URL(trimmed)
      : new URL(trimmed, base);

    if (target.origin !== base.origin) {
      throw new Error("只允许请求本地后端接口。");
    }
    if (!target.pathname.startsWith("/api/")) {
      throw new Error("只允许请求 /api 接口。");
    }

    return target;
  }

  function createAllowedProxyRoutes() {
    return [
      { methods: ["GET"], pattern: /^\/api\/health$/ },
      { methods: ["POST"], pattern: /^\/api\/chat$/ },
      { methods: ["GET"], pattern: /^\/api\/chat\/daily-history$/ },
      { methods: ["GET"], pattern: /^\/api\/chat\/runs\/[^/]+\/events$/ },
      { methods: ["GET"], pattern: /^\/api\/chat\/runs\/[^/]+\/stream$/ },
      { methods: ["GET"], pattern: /^\/api\/chat\/stream\/[^/]+$/ },
      { methods: ["GET"], pattern: /^\/api\/checkpoints\/pending$/ },
      { methods: ["GET"], pattern: /^\/api\/checkpoints\/[^/]+$/ },
      { methods: ["POST"], pattern: /^\/api\/checkpoints\/[^/]+\/decision$/ },
      { methods: ["GET"], pattern: /^\/api\/agent\/actions$/ },
      { methods: ["POST"], pattern: /^\/api\/agent\/actions\/[^/]+\/revert$/ },
      { methods: ["GET"], pattern: /^\/api\/growth\/snapshot$/ },
      { methods: ["POST"], pattern: /^\/api\/habit-loop\/trigger$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/search$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/profile-projection$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/graph-projection$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/profile-projection\/items\/profile_[A-Za-z0-9_-]+$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/profile-projection\/items\/profile_[A-Za-z0-9_-]+\/actions$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/receipts$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/local-assets$/ },
      { methods: ["GET", "POST"], pattern: /^\/api\/memory\/proposals$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/proposals\/[^/]+\/(confirm|reject)$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/graph\/facts$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/graph\/facts\/[^/]+\/(confirm|reject|wrong|archive|sensitive-block)$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/graph\/export-preview$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/diary\/search$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/diary\/[^/]+$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/feedback$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/hygiene\/preview$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/hygiene\/actions$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/companion\/consolidation\/runs$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/companion\/context-reports$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/reviews\/weekly$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/reviews\/weekly\/actions$/ },
      { methods: ["GET"], pattern: /^\/api\/memory\/retrospectives$/ },
      { methods: ["POST"], pattern: /^\/api\/memory\/retrospectives\/report$/ },
      { methods: ["GET"], pattern: /^\/api\/today\/snapshot$/ },
      { methods: ["GET"], pattern: /^\/api\/continuity\/state$/ },
      { methods: ["GET"], pattern: /^\/api\/continuity\/proposals$/ },
      { methods: ["POST"], pattern: /^\/api\/continuity\/proposals\/[^/]+\/(confirm|reject)$/ },
      { methods: ["GET", "POST"], pattern: /^\/api\/tasks$/ },
      { methods: ["GET"], pattern: /^\/api\/tasks\/today$/ },
      { methods: ["GET"], pattern: /^\/api\/tasks\/current$/ },
      { methods: ["GET"], pattern: /^\/api\/tasks\/[^/]+\/(steps|logs)$/ },
      { methods: ["PATCH"], pattern: /^\/api\/tasks\/[^/]+$/ },
      { methods: ["POST"], pattern: /^\/api\/tasks\/[^/]+\/(complete|cancel|approve|reject)$/ },
      { methods: ["GET"], pattern: /^\/api\/diagnostics\/export$/ },
      { methods: ["GET"], pattern: /^\/api\/diagnostics\/negotiation-stats$/ },
      { methods: ["POST"], pattern: /^\/api\/diagnostics\/reset-local-state$/ },
      { methods: ["POST"], pattern: /^\/api\/diagnostics\/reset-memory-state$/ },
      { methods: ["GET", "PATCH"], pattern: /^\/api\/settings$/ },
      { methods: ["GET", "PUT"], pattern: /^\/api\/settings\/automation$/ },
      { methods: ["GET", "PUT"], pattern: /^\/api\/settings\/tts$/ },
      { methods: ["PUT"], pattern: /^\/api\/settings\/tts-key$/ },
      { methods: ["PUT"], pattern: /^\/api\/settings\/model-key$/ },
      { methods: ["PUT"], pattern: /^\/api\/settings\/model-config$/ },
      { methods: ["GET"], pattern: /^\/api\/settings\/model-health$/ },
      { methods: ["POST"], pattern: /^\/api\/settings\/model-test$/ },
      { methods: ["PUT"], pattern: /^\/api\/settings\/embedding-key$/ },
      { methods: ["PUT"], pattern: /^\/api\/settings\/embedding-config$/ },
      { methods: ["POST"], pattern: /^\/api\/settings\/embedding-test$/ },
      { methods: ["GET", "PUT"], pattern: /^\/api\/settings\/agent-models$/ },
      { methods: ["PUT"], pattern: /^\/api\/settings\/agent-models\/[^/]+\/(config|key|model-config|model-key)$/ },
      { methods: ["PUT"], pattern: /^\/api\/settings\/agent-model-config$/ },
      { methods: ["PUT"], pattern: /^\/api\/settings\/agent-model-key$/ },
      { methods: ["POST"], pattern: /^\/api\/settings\/agent-model-test$/ },
      { methods: ["POST"], pattern: /^\/api\/tts\/synthesize$/ },
      { methods: ["DELETE"], pattern: /^\/api\/tts\/cache$/ },
      { methods: ["GET"], pattern: /^\/api\/vaults\/status$/ },
      { methods: ["POST"], pattern: /^\/api\/vaults\/init$/ },
      { methods: ["POST"], pattern: /^\/api\/vaults\/bind$/ },
      { methods: ["POST"], pattern: /^\/api\/vaults\/[^/]+\/index$/ },
      { methods: ["POST"], pattern: /^\/api\/wiki\/ingest\/(preview|apply|confirm|review)$/ },
      { methods: ["POST"], pattern: /^\/api\/wiki\/import\/preview$/ },
      { methods: ["GET"], pattern: /^\/api\/wiki\/(schema|index|log|graph)$/ },
      { methods: ["GET", "POST"], pattern: /^\/api\/wiki\/pages$/ },
      { methods: ["POST"], pattern: /^\/api\/wiki\/synthesize$/ },
      { methods: ["GET", "POST"], pattern: /^\/api\/wiki\/query-archives$/ },
      { methods: ["POST"], pattern: /^\/api\/wiki\/query-archives\/lint$/ },
      { methods: ["GET"], pattern: /^\/api\/wiki\/query-archives\/[^/]+$/ },
      { methods: ["POST"], pattern: /^\/api\/wiki\/lint$/ },
      { methods: ["POST"], pattern: /^\/api\/wiki\/diagnostics\/queue$/ },
    ].map((route) => ({
      methods: new Set(route.methods),
      pattern: route.pattern,
    }));
  }

  function createProxyRouteDeniedError(method, target) {
    const error = new Error(`Renderer API proxy route is not allowed: ${method} ${target.pathname}`);
    error.code = "renderer_api_route_not_allowed";
    error.details = {
      method,
      path: target.pathname,
    };
    return error;
  }

  function assertAllowedProxyRoute(method, target) {
    const allowed = allowedProxyRoutes.some((route) => route.methods.has(method) && route.pattern.test(target.pathname));
    if (!allowed) {
      throw createProxyRouteDeniedError(method, target);
    }
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
      throw new Error("不支持的接口请求方法。");
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
    assertAllowedProxyRoute(init.method, target);
    const attempts = retryableMethods.has(init.method) ? CONNECTION_RETRY_ATTEMPTS : 1;
    let lastError = null;

    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
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
      } catch (error) {
        if (!isConnectionRefused(error)) {
          throw error;
        }
        lastError = error;
        if (attempt < attempts - 1) {
          await delay(CONNECTION_RETRY_DELAY_MS);
        }
      }
    }

    return sidecarUnavailableResponse(lastError);
  }

  function sendSseEvent(sender, channel, streamId, payload) {
    if (sender.isDestroyed()) {
      return;
    }
    sender.send(channel, streamId, payload);
  }

  function attachSenderLifecycle(sender, streamId, controller) {
    // 窗口销毁时中止对应 SSE 流，避免 activeSseStreams 里挂着死流、
    // fetch 连接也一直吊着后端。
    if (typeof sender.once !== "function") {
      return () => {};
    }
    const onDestroyed = () => {
      controller.abort();
      activeSseStreams.delete(streamId);
    };
    sender.once("destroyed", onDestroyed);
    return () => {
      sender.removeListener?.("destroyed", onDestroyed);
    };
  }

  async function startSseStream(sender, streamId, pathOrUrl) {
    if (typeof streamId !== "string" || !/^[A-Za-z0-9_-]{8,80}$/.test(streamId)) {
      throw new Error("实时回复流 ID 无效。");
    }
    if (activeSseStreams.has(streamId)) {
      throw new Error("实时回复流已存在。");
    }

    const controller = new AbortController();
    activeSseStreams.set(streamId, { controller, sender });
    const detachSenderLifecycle = attachSenderLifecycle(sender, streamId, controller);

    try {
      const target = resolveSidecarUrl(pathOrUrl);
      assertAllowedProxyRoute("GET", target);
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
      detachSenderLifecycle();
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
    assertAllowedProxyRoute,
  };
}

module.exports = {
  createProxyManager,
};
