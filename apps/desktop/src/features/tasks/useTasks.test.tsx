import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DesktopApi } from "../../services/desktopApi";
import { useTasks, type UseTasksOptions } from "./useTasks";

const originalAgentDesktop = window.agentDesktop;

function apiWithTaskList(listTasks = vi.fn().mockResolvedValue({ tasks: [] })) {
  return {
    listTasks,
  } as unknown as DesktopApi;
}

function renderUseTasks({
  api = apiWithTaskList(),
  pollingEnabled = true,
  sidecarReady = true,
}: {
  api?: DesktopApi;
  pollingEnabled?: boolean;
  sidecarReady?: boolean;
} = {}) {
  return renderHook<ReturnType<typeof useTasks>, UseTasksOptions>((props) => useTasks(props), {
    initialProps: {
      api,
      pollingEnabled,
      sidecarReady,
      onNotice: vi.fn(),
      onTaskStage: vi.fn(),
    },
  });
}

describe("useTasks", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.agentDesktop = {
      ...(originalAgentDesktop || {}),
      platform: originalAgentDesktop?.platform || "win32",
      versions: originalAgentDesktop?.versions || {},
      showReminderNotification: vi.fn().mockResolvedValue({ status: "shown" }),
    };
  });

  afterEach(() => {
    vi.useRealTimers();
    window.agentDesktop = originalAgentDesktop;
  });

  it("does not poll when polling is disabled", async () => {
    const listTasks = vi.fn().mockResolvedValue({ tasks: [] });
    renderUseTasks({ api: apiWithTaskList(listTasks), pollingEnabled: false });

    await act(async () => {
      vi.advanceTimersByTime(45000);
    });

    expect(listTasks).not.toHaveBeenCalled();
  });

  it("polls through a single interval and cleans it up", async () => {
    const listTasks = vi.fn().mockResolvedValue({ tasks: [] });
    const { unmount } = renderUseTasks({ api: apiWithTaskList(listTasks), pollingEnabled: true });

    expect(listTasks).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(15000);
    });
    expect(listTasks).toHaveBeenCalledTimes(2);

    unmount();
    await act(async () => {
      vi.advanceTimersByTime(45000);
    });

    expect(listTasks).toHaveBeenCalledTimes(2);
  });

  it("waits for the sidecar before polling", async () => {
    const listTasks = vi.fn().mockResolvedValue({ tasks: [] });
    const { rerender } = renderUseTasks({ api: apiWithTaskList(listTasks), pollingEnabled: true, sidecarReady: false });

    expect(listTasks).not.toHaveBeenCalled();

    await act(async () => {
      rerender({
        api: apiWithTaskList(listTasks),
        pollingEnabled: true,
        sidecarReady: true,
        onNotice: vi.fn(),
        onTaskStage: vi.fn(),
      });
    });

    expect(listTasks).toHaveBeenCalledTimes(1);
  });
});
