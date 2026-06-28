import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
});
