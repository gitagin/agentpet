const { createProxyManager } = require("./proxy.js");

function createJsonResponse(body = {}, init = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status || 200,
    statusText: init.statusText || "OK",
    headers: {
      "content-type": "application/json",
      ...(init.headers || {}),
    },
  });
}

describe("Electron API proxy allowlist", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("allows listed routes and preserves auth:false for public health checks", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    const response = await proxy.proxyApiRequest("/api/health", {
      method: "GET",
      auth: false,
    });

    expect(response.status).toBe(200);
    expect(global.fetch).toHaveBeenCalledOnce();
    const [target, init] = global.fetch.mock.calls[0];
    expect(target.toString()).toBe("http://127.0.0.1:8765/api/health");
    expect(init.headers.has("Authorization")).toBe(false);
  });

  it("allows checkpoint listing and decisions while keeping adjacent routes denied", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await proxy.proxyApiRequest("/api/checkpoints/pending?thread_id=thread-1", { method: "GET" });
    await proxy.proxyApiRequest("/api/checkpoints/checkpoint-1/decision", { method: "POST", body: "{}" });

    expect(global.fetch).toHaveBeenCalledTimes(2);
    const [pendingTarget, pendingInit] = global.fetch.mock.calls[0];
    const [decisionTarget, decisionInit] = global.fetch.mock.calls[1];
    expect(pendingTarget.toString()).toBe("http://127.0.0.1:8765/api/checkpoints/pending?thread_id=thread-1");
    expect(pendingInit.headers.get("Authorization")).toBe("Bearer test-session-token");
    expect(decisionTarget.toString()).toBe("http://127.0.0.1:8765/api/checkpoints/checkpoint-1/decision");
    expect(decisionInit.headers.get("Authorization")).toBe("Bearer test-session-token");

    await expect(proxy.proxyApiRequest("/api/checkpoints/pending", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "POST",
        path: "/api/checkpoints/pending",
      },
    });
    await expect(proxy.proxyApiRequest("/api/checkpoints/checkpoint-1/decision/extra", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "POST",
        path: "/api/checkpoints/checkpoint-1/decision/extra",
      },
    });
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("allows only POST requests to the exact memory reset diagnostics route", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ status: "memory_reset" }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    const response = await proxy.proxyApiRequest("/api/diagnostics/reset-memory-state", {
      method: "POST",
      body: JSON.stringify({ confirmation: "RESET_AGENT_PET_MEMORY" }),
    });

    expect(response.status).toBe(200);
    expect(global.fetch).toHaveBeenCalledOnce();
    const [target, init] = global.fetch.mock.calls[0];
    expect(target.toString()).toBe("http://127.0.0.1:8765/api/diagnostics/reset-memory-state");
    expect(init.headers.get("Authorization")).toBe("Bearer test-session-token");

    await expect(proxy.proxyApiRequest("/api/diagnostics/reset-memory-state", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/diagnostics/reset-memory-state",
      },
    });
    await expect(proxy.proxyApiRequest("/api/diagnostics/reset-memory-state/extra", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "POST",
        path: "/api/diagnostics/reset-memory-state/extra",
      },
    });
    expect(global.fetch).toHaveBeenCalledOnce();
  });

  it("rejects unlisted /api routes before fetch", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await expect(proxy.proxyApiRequest("/api/admin/debug", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/admin/debug",
      },
    });
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("allows only GET requests to the exact daily chat history route", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ entries: [] }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await proxy.proxyApiRequest("/api/chat/daily-history?timezone=Asia%2FShanghai", { method: "GET" });

    expect(global.fetch).toHaveBeenCalledOnce();
    const [target, init] = global.fetch.mock.calls[0];
    expect(target.toString()).toBe("http://127.0.0.1:8765/api/chat/daily-history?timezone=Asia%2FShanghai");
    expect(init.headers.get("Authorization")).toBe("Bearer test-session-token");
    await expect(proxy.proxyApiRequest("/api/chat/daily-history", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "POST",
        path: "/api/chat/daily-history",
      },
    });
    await expect(proxy.proxyApiRequest("/api/chat/daily-history/export", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/chat/daily-history/export",
      },
    });
  });

  it("strips forbidden renderer headers before adding the main-process bearer token", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ run_id: "run-1" }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await proxy.proxyApiRequest("/api/chat", {
      method: "POST",
      headers: {
        Authorization: "Bearer renderer-token",
        Cookie: "session=renderer",
        Host: "evil.example",
        Origin: "https://evil.example",
        Referer: "https://evil.example/page",
        "Content-Type": "application/json",
      },
      body: "{}",
    });

    const [, init] = global.fetch.mock.calls[0];
    expect(init.headers.get("Authorization")).toBe("Bearer test-session-token");
    expect(init.headers.has("Cookie")).toBe(false);
    expect(init.headers.has("Host")).toBe(false);
    expect(init.headers.has("Origin")).toBe(false);
    expect(init.headers.has("Referer")).toBe(false);
    expect(init.headers.get("Content-Type")).toBe("application/json");
  });

  it("allows weekly memory review routes through the main-process proxy", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await proxy.proxyApiRequest("/api/memory/reviews/weekly?days=7", { method: "GET" });
    await proxy.proxyApiRequest("/api/memory/reviews/weekly/actions", { method: "POST", body: "{}" });

    expect(global.fetch).toHaveBeenCalledTimes(2);
    const [getTarget, getInit] = global.fetch.mock.calls[0];
    const [postTarget, postInit] = global.fetch.mock.calls[1];
    expect(getTarget.toString()).toBe("http://127.0.0.1:8765/api/memory/reviews/weekly?days=7");
    expect(getInit.headers.get("Authorization")).toBe("Bearer test-session-token");
    expect(postTarget.toString()).toBe("http://127.0.0.1:8765/api/memory/reviews/weekly/actions");
    expect(postInit.headers.get("Authorization")).toBe("Bearer test-session-token");
  });

  it("allows safe memory profile and receipt routes through the main-process proxy", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await proxy.proxyApiRequest("/api/memory/profile-projection", { method: "GET" });
    await proxy.proxyApiRequest("/api/memory/graph-projection", { method: "GET" });
    await proxy.proxyApiRequest("/api/memory/profile-projection/items/profile_abc123", { method: "GET" });
    await proxy.proxyApiRequest("/api/memory/profile-projection/items/profile_abc123/actions", { method: "POST", body: "{}" });
    await proxy.proxyApiRequest("/api/memory/receipts?agent_run_id=run-1", { method: "GET" });

    expect(global.fetch).toHaveBeenCalledTimes(5);
    for (const [, init] of global.fetch.mock.calls) {
      expect(init.headers.get("Authorization")).toBe("Bearer test-session-token");
    }
    await expect(proxy.proxyApiRequest("/api/memory/graph-projection", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "POST",
        path: "/api/memory/graph-projection",
      },
    });
    await expect(proxy.proxyApiRequest("/api/memory/profile-projection/items/profile_abc123/actions", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/memory/profile-projection/items/profile_abc123/actions",
      },
    });
    await expect(proxy.proxyApiRequest("/api/memory/profile-projection/items/profile_abc123/source", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/memory/profile-projection/items/profile_abc123/source",
      },
    });
    await expect(proxy.proxyApiRequest("/api/memory/profile-projection/export", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/memory/profile-projection/export",
      },
    });
    await expect(proxy.proxyApiRequest("/api/memory/profile-projection/items/candidate-raw-id", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/memory/profile-projection/items/candidate-raw-id",
      },
    });
    expect(global.fetch).toHaveBeenCalledTimes(5);
  });

  it("allows only the exact growth snapshot route", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await proxy.proxyApiRequest("/api/growth/snapshot", { method: "GET" });

    expect(global.fetch).toHaveBeenCalledOnce();
    const [target, init] = global.fetch.mock.calls[0];
    expect(target.toString()).toBe("http://127.0.0.1:8765/api/growth/snapshot");
    expect(init.headers.get("Authorization")).toBe("Bearer test-session-token");
    await expect(proxy.proxyApiRequest("/api/growth/snapshot", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "POST",
        path: "/api/growth/snapshot",
      },
    });
  });

  it("allows only the exact habit-loop trigger route", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ should_trigger: false }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await proxy.proxyApiRequest("/api/habit-loop/trigger", { method: "POST", body: "{}" });

    expect(global.fetch).toHaveBeenCalledOnce();
    const [target, init] = global.fetch.mock.calls[0];
    expect(target.toString()).toBe("http://127.0.0.1:8765/api/habit-loop/trigger");
    expect(init.headers.get("Authorization")).toBe("Bearer test-session-token");
    await expect(proxy.proxyApiRequest("/api/habit-loop/trigger", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/habit-loop/trigger",
      },
    });
    await expect(proxy.proxyApiRequest("/api/habit-loop/trigger/extra", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "POST",
        path: "/api/habit-loop/trigger/extra",
      },
    });
  });

  it("allows only the exact visible continuity snapshot route", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    await proxy.proxyApiRequest("/api/today/snapshot", { method: "GET" });

    expect(global.fetch).toHaveBeenCalledOnce();
    const [target, init] = global.fetch.mock.calls[0];
    expect(target.toString()).toBe("http://127.0.0.1:8765/api/today/snapshot");
    expect(init.headers.get("Authorization")).toBe("Bearer test-session-token");
    await expect(proxy.proxyApiRequest("/api/today/snapshot/export", { method: "GET" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "GET",
        path: "/api/today/snapshot/export",
      },
    });
    await expect(proxy.proxyApiRequest("/api/today/snapshot", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
      details: {
        method: "POST",
        path: "/api/today/snapshot",
      },
    });
  });

  it("allows every graph fact action including reject", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    // Regression guard: confirm/wrong/archive/sensitive-block were allowed but
    // the sibling reject route was missing from the allowlist regex, so the
    // renderer received renderer_api_route_not_allowed for it.
    for (const action of ["confirm", "reject", "wrong", "archive", "sensitive-block"]) {
      await proxy.proxyApiRequest(`/api/memory/graph/facts/fact-1/${action}`, { method: "POST", body: "{}" });
    }
    expect(global.fetch).toHaveBeenCalledTimes(5);

    await expect(proxy.proxyApiRequest("/api/memory/graph/facts/fact-1/purge", { method: "POST", body: "{}" })).rejects.toMatchObject({
      code: "renderer_api_route_not_allowed",
    });
  });

  it("allows the previously missing renderer-facing routes", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });

    const allowedCases = [
      ["GET", "/api/chat/runs/run-1/stream"],
      ["GET", "/api/chat/stream/run-1"],
      ["GET", "/api/checkpoints/checkpoint-1"],
      ["GET", "/api/diagnostics/negotiation-stats"],
      ["POST", "/api/memory/diary/search"],
      ["GET", "/api/memory/diary/diary-1"],
      ["POST", "/api/memory/feedback"],
      ["GET", "/api/memory/hygiene/preview"],
      ["POST", "/api/memory/hygiene/actions"],
      ["PUT", "/api/settings/embedding-key"],
      ["PUT", "/api/settings/embedding-config"],
      ["POST", "/api/settings/embedding-test"],
      ["GET", "/api/settings/agent-models"],
      ["PUT", "/api/settings/agent-models"],
      ["PUT", "/api/settings/agent-models/chat_agent/model-config"],
      ["PUT", "/api/settings/agent-models/chat_agent/model-key"],
      ["PUT", "/api/settings/agent-model-config"],
      ["PUT", "/api/settings/agent-model-key"],
      ["POST", "/api/settings/agent-model-test"],
      ["PATCH", "/api/tasks/task-1"],
      ["POST", "/api/vaults/bind"],
      ["GET", "/api/wiki/pages"],
      ["POST", "/api/wiki/pages"],
      ["GET", "/api/wiki/graph"],
      ["POST", "/api/wiki/import/preview"],
      ["POST", "/api/wiki/query-archives/lint"],
    ];
    for (const [method, path] of allowedCases) {
      const body = method === "GET" ? undefined : "{}";
      await proxy.proxyApiRequest(path, { method, body });
    }
    expect(global.fetch).toHaveBeenCalledTimes(allowedCases.length);

    const deniedCases = [
      ["DELETE", "/api/tasks/task-1"],
      ["GET", "/api/settings/embedding-key"],
      ["POST", "/api/wiki/graph"],
      ["DELETE", "/api/memory/diary/diary-1"],
      ["GET", "/api/vaults/bind"],
    ];
    for (const [method, path] of deniedCases) {
      await expect(proxy.proxyApiRequest(path, { method, body: method === "GET" ? undefined : "{}" })).rejects.toMatchObject({
        code: "renderer_api_route_not_allowed",
      });
    }
    expect(global.fetch).toHaveBeenCalledTimes(allowedCases.length);
  });

  it("allows only chat run event routes for SSE streams", async () => {
    global.fetch = vi.fn(async () => createJsonResponse({ ok: true }));
    const proxy = createProxyManager({
      baseUrl: "http://127.0.0.1:8765",
      sessionToken: "test-session-token",
    });
    const sender = {
      isDestroyed: vi.fn(() => false),
      send: vi.fn(),
    };

    await proxy.startSseStream(sender, "stream_12345678", "/api/admin/events");

    expect(global.fetch).not.toHaveBeenCalled();
    expect(sender.send).toHaveBeenCalledWith(
      "agent-pet:sse-error",
      "stream_12345678",
      expect.objectContaining({
        message: expect.stringContaining("Renderer API proxy route is not allowed"),
      }),
    );
  });
});
