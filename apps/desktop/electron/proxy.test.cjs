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
