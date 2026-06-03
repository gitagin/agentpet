import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TaskItem } from "../../types";
import { TaskPanel } from "./TaskPanel";
import type { ReminderNotificationSummary } from "./taskReducer";

const idleReminder: ReminderNotificationSummary = {
  status: "idle",
  detail: "等待到期提醒触发。",
};

function task(overrides: Partial<TaskItem> = {}): TaskItem {
  return {
    task_id: "task-1",
    title: "测试任务",
    description: "描述",
    status: "pending",
    ...overrides,
  };
}

describe("TaskPanel", () => {
  it("shows an idle state when there are no tasks", () => {
    render(<TaskPanel tasks={[]} lastReminderNotification={idleReminder} onLocateTask={vi.fn()} />);

    expect(screen.getByText("空闲")).toBeInTheDocument();
    expect(screen.getByText("当前没有任务或提醒；通过聊天或表单创建后会出现在这里。")).toBeInTheDocument();
    expect(screen.queryByText("已就绪")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "定位" })).not.toBeInTheDocument();
  });

  it("shows a ready state and locate action when tasks exist", () => {
    const onLocateTask = vi.fn();
    render(<TaskPanel tasks={[task()]} lastReminderNotification={idleReminder} onLocateTask={onLocateTask} />);

    expect(screen.getByText("已就绪")).toBeInTheDocument();
    screen.getByRole("button", { name: "定位" }).click();
    expect(onLocateTask).toHaveBeenCalledWith("task-task-1");
  });
});
