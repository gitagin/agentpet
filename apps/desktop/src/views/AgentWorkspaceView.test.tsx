import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DesktopApi } from "../services/desktopApi";
import AgentWorkspaceView from "./AgentWorkspaceView";

function createApi() {
  return {
    fetchCurrentTask: vi.fn().mockResolvedValue({ task: null }),
    listTasks: vi.fn().mockResolvedValue({ tasks: [] }),
    listTodayTasks: vi.fn().mockResolvedValue({ tasks: [] }),
    fetchTaskSteps: vi.fn().mockResolvedValue({ steps: [] }),
    fetchTaskLogs: vi.fn().mockResolvedValue({ logs: [] }),
    approveTask: vi.fn(),
    rejectTask: vi.fn(),
  } as unknown as DesktopApi;
}

describe("AgentWorkspaceView", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows idle instead of completed when there is no current task", async () => {
    const api = createApi();

    render(<AgentWorkspaceView api={api} />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("暂无当前任务")).toBeInTheDocument();
    expect(screen.getByText("空闲")).toBeInTheDocument();
    expect(screen.queryByText("完成")).not.toBeInTheDocument();
  });

  it("polls at a controlled 30 second interval and cleans up on unmount", async () => {
    const api = createApi();
    const { unmount } = render(<AgentWorkspaceView api={api} />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(api.fetchCurrentTask).toHaveBeenCalledTimes(1);
    expect(api.listTasks).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(29999);
    });
    expect(api.fetchCurrentTask).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(api.fetchCurrentTask).toHaveBeenCalledTimes(2);
    expect(api.listTasks).toHaveBeenCalledTimes(2);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(90000);
    });
    expect(api.fetchCurrentTask).toHaveBeenCalledTimes(2);
    expect(api.listTasks).toHaveBeenCalledTimes(2);
  });
});
