import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { detectDesktopWindowMode } from "./desktopWindowModes";
import { useDesktopWindowRouting } from "./useDesktopWindowRouting";

describe("useDesktopWindowRouting", () => {
  beforeEach(() => {
    window.location.hash = "";
    delete window.agentDesktop;
  });

  afterEach(() => {
    window.location.hash = "";
    delete window.agentDesktop;
  });

  it("keeps the explicit hash route when the desktop window mode IPC fails", async () => {
    const getWindowMode = vi.fn().mockRejectedValue(new Error("ipc unavailable"));
    window.location.hash = "#chat";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getWindowMode,
    };

    const { result } = renderHook(() =>
      useDesktopWindowRouting({ onControlTargetRequested: vi.fn() }),
    );

    await waitFor(() => expect(getWindowMode).toHaveBeenCalledTimes(1));

    expect(result.current.windowMode).toBe("chat");
    expect(result.current.desktopHostMode).toBe("chat");
  });

  it("falls back to the stage home route for unknown hashes", () => {
    window.location.hash = "#unknown-route";

    expect(detectDesktopWindowMode()).toBe("stage");
  });

  it("accepts control target focus requests on the stage home route", async () => {
    const onControlTargetRequested = vi.fn();
    const unsubscribe = vi.fn();
    const focusCallbackRef: { current?: (targetId: string) => void } = {};
    window.location.hash = "#stage";
    window.agentDesktop = {
      platform: "win32",
      versions: {},
      getWindowMode: vi.fn().mockResolvedValue("control"),
      onControlTargetRequested: vi.fn((callback) => {
        focusCallbackRef.current = callback;
        return unsubscribe;
      }),
    };

    renderHook(() =>
      useDesktopWindowRouting({ onControlTargetRequested }),
    );

    await waitFor(() => expect(window.agentDesktop?.onControlTargetRequested).toHaveBeenCalledTimes(1));

    focusCallbackRef.current?.("agent-activity-log");

    await waitFor(() => expect(onControlTargetRequested).toHaveBeenCalledWith("agent-activity-log"));
  });
});
