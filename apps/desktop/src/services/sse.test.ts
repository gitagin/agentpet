import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./apiClient";
import { fetchSseStream } from "./sse";

describe("fetchSseStream", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not attach renderer-owned authorization in browser fallback", async () => {
    const encoder = new TextEncoder();
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ value: encoder.encode("event: done\ndata: {}\n\n"), done: false })
        .mockResolvedValueOnce({ value: undefined, done: true }),
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => reader,
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    window.agentDesktop = undefined;

    await fetchSseStream(
      new ApiClient({ baseUrl: "http://127.0.0.1:8765" }),
      "/api/chat/runs/run-1/events",
      { onEvent: vi.fn() },
    );

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Accept")).toBe("text/event-stream");
    expect(headers.has("Authorization")).toBe(false);
  });
});
