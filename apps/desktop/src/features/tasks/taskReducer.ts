import type { TaskDraft, TaskItem } from "../../types";

export type ReminderNotificationSummary = {
  status: "idle" | "shown" | "duplicate" | "unsupported" | "failed" | "unknown";
  detail: string;
};

export type TaskState = {
  draft: TaskDraft;
  tasks: TaskItem[];
  loading: boolean;
  actionIds: Set<string>;
  lastReminderNotification: ReminderNotificationSummary;
};

export type TaskAction =
  | { type: "updateDraft"; patch: Partial<TaskDraft> }
  | { type: "resetDraft" }
  | { type: "setTasks"; tasks: TaskItem[] }
  | { type: "addTask"; task: TaskItem }
  | { type: "clearTasks" }
  | { type: "setLoading"; loading: boolean }
  | { type: "startTaskAction"; taskId: string }
  | { type: "finishTaskAction"; taskId: string }
  | { type: "updateTaskStatus"; taskId: string; status: string }
  | { type: "setReminderNotification"; summary: ReminderNotificationSummary };

export function createInitialTaskState(timezone: string): TaskState {
  return {
    draft: {
      title: "",
      description: "",
      due_at: "",
      remind_at: "",
      timezone,
    },
    tasks: [],
    loading: false,
    actionIds: new Set(),
    lastReminderNotification: {
      status: "idle",
      detail: "等待到期提醒触发。",
    },
  };
}

export function taskReducer(state: TaskState, action: TaskAction): TaskState {
  switch (action.type) {
    case "updateDraft":
      return { ...state, draft: { ...state.draft, ...action.patch } };
    case "resetDraft":
      return { ...state, draft: { ...state.draft, title: "", description: "", due_at: "", remind_at: "" } };
    case "setTasks":
      return { ...state, tasks: action.tasks };
    case "addTask":
      return { ...state, tasks: [action.task, ...state.tasks] };
    case "clearTasks":
      return { ...state, tasks: [] };
    case "setLoading":
      return { ...state, loading: action.loading };
    case "startTaskAction": {
      const next = new Set(state.actionIds);
      next.add(action.taskId);
      return { ...state, actionIds: next };
    }
    case "finishTaskAction": {
      const next = new Set(state.actionIds);
      next.delete(action.taskId);
      return { ...state, actionIds: next };
    }
    case "updateTaskStatus":
      return {
        ...state,
        tasks: state.tasks.map((task) => (task.task_id === action.taskId ? { ...task, status: action.status } : task)),
      };
    case "setReminderNotification":
      return { ...state, lastReminderNotification: action.summary };
    default:
      return state;
  }
}

export function formatReminderNotificationStatus(summary: ReminderNotificationSummary): string {
  const labels: Record<ReminderNotificationSummary["status"], string> = {
    idle: "未触发",
    shown: "已调用系统显示",
    duplicate: "已去重",
    unsupported: "不支持",
    failed: "失败",
    unknown: "结果未知",
  };
  return `${labels[summary.status]}，${summary.detail}`;
}

export function formatTaskStatus(status: string): string {
  if (status === "reviewed") {
    return "已审查";
  }
  if (status === "model_not_configured") {
    return "模型未配置";
  }
  const labels: Record<string, string> = {
    pending: "待处理",
    done: "已完成",
    cancelled: "已取消",
    failed: "失败，需处理",
    scheduled: "已安排",
    unscheduled: "未安排",
    completed: "已完成",
    indexed: "已索引",
    bound: "已绑定",
  };
  return labels[status] || status;
}

export function formatTimezoneForUser(value?: string | null): string {
  if (!value) {
    return "";
  }
  const normalized = value.trim();
  if (["Asia/Shanghai", "Asia/Beijing", "Beijing", "北京", "北京时间"].includes(normalized)) {
    return "北京时间";
  }
  return normalized;
}
