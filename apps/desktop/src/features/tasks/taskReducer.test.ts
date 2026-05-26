import { describe, expect, it } from "vitest";

import type { TaskItem } from "../../types";
import { createInitialTaskState, formatReminderNotificationStatus, formatTaskStatus, taskReducer } from "./taskReducer";

function task(overrides: Partial<TaskItem> = {}): TaskItem {
  return {
    task_id: "task-1",
    title: "测试任务",
    description: "描述",
    status: "pending",
    ...overrides,
  };
}

describe("taskReducer", () => {
  it("creates the initial state with an empty draft and task list", () => {
    const state = createInitialTaskState("Asia/Shanghai");

    expect(state.draft).toEqual({ title: "", description: "", due_at: "", remind_at: "", timezone: "Asia/Shanghai" });
    expect(state.tasks).toEqual([]);
    expect(state.loading).toBe(false);
    expect(state.actionIds.size).toBe(0);
    expect(state.lastReminderNotification.status).toBe("idle");
  });

  it("updates and resets the task draft", () => {
    const updated = taskReducer(createInitialTaskState("Asia/Shanghai"), {
      type: "updateDraft",
      patch: { title: "买牛奶", description: "下班后", due_at: "2026-05-22T10:00:00+08:00" },
    });
    const reset = taskReducer(updated, { type: "resetDraft" });

    expect(updated.draft.title).toBe("买牛奶");
    expect(updated.draft.description).toBe("下班后");
    expect(reset.draft).toMatchObject({ title: "", description: "", due_at: "", remind_at: "" });
    expect(reset.draft.timezone).toBe("Asia/Shanghai");
  });

  it("sets, prepends, clears, and updates tasks", () => {
    const first = task({ task_id: "task-1", title: "旧任务" });
    const second = task({ task_id: "task-2", title: "新任务", status: "scheduled" });
    const withTasks = taskReducer(createInitialTaskState("Asia/Shanghai"), { type: "setTasks", tasks: [first] });
    const added = taskReducer(withTasks, { type: "addTask", task: second });
    const updated = taskReducer(added, { type: "updateTaskStatus", taskId: "task-1", status: "done" });
    const cleared = taskReducer(updated, { type: "clearTasks" });

    expect(added.tasks.map((item) => item.task_id)).toEqual(["task-2", "task-1"]);
    expect(updated.tasks.find((item) => item.task_id === "task-1")?.status).toBe("done");
    expect(cleared.tasks).toEqual([]);
  });

  it("tracks loading and in-flight task actions immutably", () => {
    const loading = taskReducer(createInitialTaskState("Asia/Shanghai"), { type: "setLoading", loading: true });
    const started = taskReducer(loading, { type: "startTaskAction", taskId: "task-1" });
    const finished = taskReducer(started, { type: "finishTaskAction", taskId: "task-1" });

    expect(loading.loading).toBe(true);
    expect(started.actionIds.has("task-1")).toBe(true);
    expect(loading.actionIds.has("task-1")).toBe(false);
    expect(finished.actionIds.has("task-1")).toBe(false);
  });

  it("stores and formats reminder notifications", () => {
    const state = taskReducer(createInitialTaskState("Asia/Shanghai"), {
      type: "setReminderNotification",
      summary: { status: "shown", detail: "任务已提醒。" },
    });

    expect(state.lastReminderNotification.detail).toBe("任务已提醒。");
    expect(formatReminderNotificationStatus(state.lastReminderNotification)).toBe("已送达，任务已提醒。");
  });

  it("formats known and unknown task statuses", () => {
    expect(formatTaskStatus("pending")).toBe("待处理");
    expect(formatTaskStatus("reviewed")).toBe("已审查");
    expect(formatTaskStatus("custom-status")).toBe("custom-status");
  });
});
