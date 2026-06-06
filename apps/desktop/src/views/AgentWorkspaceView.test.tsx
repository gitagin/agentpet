import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DesktopApi } from "../services/desktopApi";
import type { TaskItem } from "../types";
import AgentWorkspaceView from "./AgentWorkspaceView";

function task(overrides: Partial<TaskItem> = {}): TaskItem {
  return {
    task_id: "task-1",
    title: "规划发布",
    description: "交付任务工作区",
    status: "pending",
    due_at: "2026-06-06T10:00:00Z",
    remind_at: "2026-06-06T09:30:00Z",
    reminder_status: "scheduled",
    timezone: "Asia/Shanghai",
    timezone_label: "Asia/Shanghai",
    ...overrides,
  };
}

function createApi(tasks: TaskItem[] = []) {
  return {
    fetchCurrentTask: vi.fn().mockResolvedValue({ task: null }),
    listTasks: vi.fn().mockResolvedValue({ tasks }),
    listTodayTasks: vi.fn().mockResolvedValue({ tasks: [] }),
    fetchTaskSteps: vi.fn().mockResolvedValue({ steps: [] }),
    fetchTaskLogs: vi.fn().mockResolvedValue({ logs: [] }),
    approveTask: vi.fn(),
    rejectTask: vi.fn(),
    createTask: vi.fn().mockResolvedValue({
      task_id: "created-task",
      reminder_id: "reminder-1",
      status: "pending",
      metadata: {},
    }),
    completeTask: vi.fn().mockResolvedValue({ task_id: "task-1", status: "done" }),
    cancelTask: vi.fn().mockResolvedValue({ task_id: "task-1", status: "cancelled" }),
  } as unknown as DesktopApi;
}

async function flushInitialLoad() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("AgentWorkspaceView", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a direct task creation form and first-task empty state", async () => {
    const api = createApi();

    render(<AgentWorkspaceView api={api} />);

    await flushInitialLoad();

    expect(screen.getByRole("heading", { name: "创建任务" })).toBeInTheDocument();
    expect(screen.getByLabelText("任务创建表单")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建明天的提醒" }));
    expect(screen.getByLabelText("任务标题")).toHaveValue("检查发布清单");
    expect(screen.getByLabelText("说明")).toHaveValue("从任务工作区创建的快捷试用提醒。");
    expect(String((screen.getByLabelText("提醒时间") as HTMLInputElement).value)).toMatch(/T09:00$/);
    expect(screen.getByText("还没有任务。可以用上方表单创建第一个任务。")).toBeInTheDocument();
    expect(screen.getByText("暂无当前任务。")).toBeInTheDocument();
    expect(screen.getByText("空闲")).toBeInTheDocument();
    expect(screen.queryByLabelText(/聊天/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/聊天仍在这里/i)).not.toBeInTheDocument();
  });

  it("不打开聊天也能创建任务", async () => {
    const api = createApi();

    render(<AgentWorkspaceView api={api} />);

    await flushInitialLoad();
    fireEvent.change(screen.getByLabelText("任务标题"), { target: { value: "编写发布清单" } });
    fireEvent.change(screen.getByLabelText("说明"), { target: { value: "包含打包和 smoke 检查" } });
    fireEvent.change(screen.getByLabelText("截止时间"), { target: { value: "2026-06-06T10:00" } });
    fireEvent.change(screen.getByLabelText("提醒时间"), { target: { value: "2026-06-06T09:30" } });
    fireEvent.change(screen.getByLabelText("时区"), { target: { value: "Asia/Shanghai" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "创建任务" }));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(api.createTask).toHaveBeenCalledTimes(1);
    expect(api.createTask).toHaveBeenCalledWith(
      {
        title: "编写发布清单",
        description: "包含打包和 smoke 检查",
        due_at: "2026-06-06T10:00",
        remind_at: "2026-06-06T09:30",
        timezone: "Asia/Shanghai",
      },
    );
  });

  it("completes and cancels tasks from task cards", async () => {
    const api = createApi([
      task({ task_id: "task-1", title: "完成我" }),
      task({ task_id: "task-2", title: "取消我" }),
    ]);

    render(<AgentWorkspaceView api={api} />);

    await flushInitialLoad();

    const taskCards = screen.getByLabelText("任务卡片");
    const completeCard = within(taskCards).getByText("完成我").closest("article");
    const cancelCard = within(taskCards).getByText("取消我").closest("article");
    expect(completeCard).not.toBeNull();
    expect(cancelCard).not.toBeNull();

    await act(async () => {
      fireEvent.click(within(completeCard as HTMLElement).getByRole("button", { name: "完成" }));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(api.completeTask).toHaveBeenCalledWith("task-1");

    await act(async () => {
      fireEvent.click(within(cancelCard as HTMLElement).getByRole("button", { name: "取消" }));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(api.cancelTask).toHaveBeenCalledWith("task-2");
  });

  it("locates logs and steps for a task card", async () => {
    const scrollIntoView = vi.fn();
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    const api = createApi([task({ task_id: "task-1", title: "查看轨迹" })]);
    vi.mocked(api.fetchTaskSteps).mockResolvedValue({
      steps: [{ index: 1, tool_name: "task", status: "pending", duration_ms: 0 }],
    });
    vi.mocked(api.fetchTaskLogs).mockResolvedValue({
      logs: [{ timestamp: "2026-06-06T09:00:00Z", content: "任务已创建：查看轨迹" }],
    });

    try {
      render(<AgentWorkspaceView api={api} />);

      await flushInitialLoad();
      const card = within(screen.getByLabelText("任务卡片")).getByText("查看轨迹").closest("article");
      expect(card).not.toBeNull();
      await act(async () => {
        fireEvent.click(within(card as HTMLElement).getByRole("button", { name: "定位日志/步骤" }));
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(api.fetchTaskSteps).toHaveBeenCalledWith("task-1", undefined);
      expect(api.fetchTaskLogs).toHaveBeenCalledWith("task-1", undefined);
      expect(screen.getByText("任务已创建：查看轨迹")).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(16);
      });
      expect(scrollIntoView).toHaveBeenCalled();
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
    }
  });

  it("polls at a controlled 30 second interval and cleans up on unmount", async () => {
    const api = createApi();
    const { unmount } = render(<AgentWorkspaceView api={api} />);

    await flushInitialLoad();

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
