// 幂等 GET 在后端启动窗口内的重试参数：12 次 x 250ms ≈ 3 秒，
// 与 sidecar 冷启动到可服务的常见耗时同数量级。
const CONNECTION_RETRY_ATTEMPTS = 12;
const CONNECTION_RETRY_DELAY_MS = 250;
const proxyRouteArtifact = require("./proxy-routes.generated.json");
const GENERATED_PROXY_METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function compileOpenApiPath(pathTemplate) {
  if (typeof pathTemplate !== "string" || !pathTemplate.startsWith("/api/")) {
    throw new Error(`Invalid generated renderer proxy path: ${String(pathTemplate)}`);
  }
  const pattern = pathTemplate
    .split("/")
    .map((segment) => (/^\{[^/{}]+\}$/.test(segment) ? "[^/]+" : escapeRegex(segment)))
    .join("/");
  return new RegExp(`^${pattern}$`);
}

function createAllowedProxyRoutes(artifact = proxyRouteArtifact) {
  if (artifact?.schemaVersion !== 1 || !Array.isArray(artifact.routes)) {
    throw new Error("Generated renderer proxy routes use an unsupported schema.");
  }
  return artifact.routes.map((route) => {
    if (
      !Array.isArray(route.methods) ||
      route.methods.length === 0 ||
      route.methods.some((method) => !GENERATED_PROXY_METHODS.has(method))
    ) {
      throw new Error(`Generated renderer proxy route has invalid methods: ${String(route.path)}`);
    }
    return {
      methods: new Set(route.methods),
      pattern: compileOpenApiPath(route.path),
    };
  });
}

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

  async function requestApi(pathOrUrl, options, { enforceRendererRoute }) {
    const target = resolveSidecarUrl(pathOrUrl);
    const init = normalizeApiRequestOptions(options);
    if (enforceRendererRoute) {
      assertAllowedProxyRoute(init.method, target);
    }
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

  async function proxyApiRequest(pathOrUrl, options) {
    return requestApi(pathOrUrl, options, { enforceRendererRoute: true });
  }

  async function requestInternalApi(pathOrUrl, options) {
    return requestApi(pathOrUrl, options, { enforceRendererRoute: false });
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

      // sender 可能在 fetch resolve 与 reader.read() 注册 abort 监听之间销毁。
      // 此时 signal 已经 aborted，继续 read 会让某些流实现永久等待。
      if (controller.signal.aborted) {
        return;
      }

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
    requestInternalApi,
    startSseStream,
    cancelSseStream,
    assertAllowedProxyRoute,
  };
}

module.exports = {
  compileOpenApiPath,
  createProxyManager,
};
