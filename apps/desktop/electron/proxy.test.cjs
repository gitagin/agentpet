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
