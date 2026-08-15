import type { FormEvent } from "react";
import { useCallback, useEffect, useReducer, useRef } from "react";
import type { TaskDraft, TaskItem } from "../../types";
import { describeError } from "../../services/apiErrorMessages";
import type { DesktopApi } from "../../services/desktopApi";
import {
  createInitialTaskState,
  formatTaskStatus,
  formatTimezoneForUser,
  taskReducer,
  type ReminderNotificationSummary,
} from "./taskReducer";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

export type UseTasksOptions = {
  api: DesktopApi;
  pollingEnabled: boolean;
  sidecarReady: boolean;
  onNotice: (notice: Notice | null) => void;
  onTaskStage: () => void;
};

export function useTasks({ api, pollingEnabled, sidecarReady, onNotice, onTaskStage }: UseTasksOptions) {
  const [state, dispatch] = useReducer(
    taskReducer,
    undefined,
    () => createInitialTaskState(formatTimezoneForUser(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC")),
  );
  const callbacks = useRef({ onNotice, onTaskStage });

  callbacks.current = { onNotice, onTaskStage };

  const dispatchManualReminder = useCallback(async (task: TaskItem) => {
    const notify = window.agentDesktop?.showReminderNotification;
    const reminderId = task.reminder_id?.trim();
    const triggerAt = task.remind_at || task.triggered_at || "";
    if (!reminderId || task.reminder_status !== "triggered" || !triggerAt) {
      return;
    }
    if (!notify) {
      dispatch({ type: "setReminderNotification", summary: { status: "unsupported", detail: "当前运行环境不支持系统通知。" } });
      return;
    }
    try {
      const result = await notify({
        reminder_id: reminderId,
        trigger_at: triggerAt,
        dispatch_kind: "manual",
        title: task.title || "Agent Pet 提醒",
        body: task.description || "提醒已到期。",
      });
      dispatch({
        type: "setReminderNotification",
        summary: {
          status: result.status,
          detail:
            result.status === "shown"
              ? `已调用系统显示：${task.title || reminderId}`
              : result.reason || `提醒 ${reminderId} 返回 ${result.status}`,
        },
      });
      if (result.status !== "shown") {
        callbacks.current.onNotice({
          tone: "error",
          message: `系统通知结果未确认，任务仍会保留：${result.reason || result.status}`,
        });
      }
    } catch (error) {
      dispatch({ type: "setReminderNotification", summary: { status: "unknown", detail: "手动提醒调用结果未知。" } });
      callbacks.current.onNotice({ tone: "error", message: "手动提醒调用结果未知，任务仍会保留。" });
    }
  }, []);

  const loadTasks = useCallback(async (options: { silent?: boolean } = {}) => {
    if (!options.silent) {
      dispatch({ type: "setLoading", loading: true });
    }
    try {
      const response = await api.listTasks();
      dispatch({ type: "setTasks", tasks: response.tasks });
    } catch (error) {
      if (!options.silent) {
        callbacks.current.onNotice({ tone: "error", message: describeError(error, "任务加载失败") });
      }
    } finally {
      if (!options.silent) {
        dispatch({ type: "setLoading", loading: false });
      }
    }
  }, [api]);

  const createTask = useCallback(async (event: FormEvent) => {
    event.preventDefault();
    if (!state.draft.title.trim()) {
      return;
    }

    callbacks.current.onNotice(null);
    try {
      const response = await api.createTask({
        ...state.draft,
        due_at: state.draft.due_at || null,
        remind_at: state.draft.remind_at || null,
      });
      callbacks.current.onNotice({
        tone: "success",
        message: `任务 ${response.task_id} 已保存，状态：${formatTaskStatus(response.status)}。`,
      });
      callbacks.current.onTaskStage();
      dispatch({ type: "resetDraft" });
      void loadTasks();
    } catch (error) {
      callbacks.current.onNotice({ tone: "error", message: describeError(error, "任务创建失败") });
    }
  }, [api, loadTasks, state.draft]);

  const actOnTask = useCallback(async (taskId: string, action: "complete" | "cancel") => {
    dispatch({ type: "startTaskAction", taskId });
    callbacks.current.onNotice(null);
    try {
      const response = action === "complete" ? await api.completeTask(taskId) : await api.cancelTask(taskId);
      dispatch({ type: "updateTaskStatus", taskId, status: response.status });
      callbacks.current.onNotice({
        tone: "success",
        message: `任务 ${response.task_id} 已标记为 ${formatTaskStatus(response.status)}。`,
      });
      callbacks.current.onTaskStage();
      void loadTasks();
    } catch (error) {
      callbacks.current.onNotice({ tone: "error", message: describeError(error, "任务操作失败") });
    } finally {
      dispatch({ type: "finishTaskAction", taskId });
    }
  }, [api, loadTasks]);

  useEffect(() => {
    if (!pollingEnabled || !sidecarReady) {
      return;
    }

    void loadTasks({ silent: true });
    const intervalId = window.setInterval(() => {
      void loadTasks({ silent: true });
    }, 15000);
    return () => window.clearInterval(intervalId);
  }, [loadTasks, pollingEnabled, sidecarReady]);

  const updateTaskDraft = useCallback((patch: Partial<TaskDraft>) => {
    dispatch({ type: "updateDraft", patch });
  }, []);

  const addTaskFromChat = useCallback((task: TaskItem) => {
    dispatch({ type: "addTask", task });
  }, []);

  const clearTasks = useCallback(() => {
    dispatch({ type: "clearTasks" });
  }, []);

  return {
    actOnTask,
    addTaskFromChat,
    clearTasks,
    createTask,
    lastReminderNotification: state.lastReminderNotification as ReminderNotificationSummary,
    loadingTasks: state.loading,
    loadTasks,
    retryReminder: (taskId: string) => {
      const task = state.tasks.find((item) => item.task_id === taskId);
      if (task) {
        void dispatchManualReminder(task);
      }
    },
    taskActionIds: state.actionIds,
    taskDraft: state.draft,
    tasks: state.tasks,
    updateTaskDraft,
  };
}
