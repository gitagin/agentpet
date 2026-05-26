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

type UseTasksOptions = {
  api: DesktopApi;
  sidecarReady: boolean;
  onNotice: (notice: Notice | null) => void;
  onTaskStage: () => void;
};

export function useTasks({ api, sidecarReady, onNotice, onTaskStage }: UseTasksOptions) {
  const [state, dispatch] = useReducer(
    taskReducer,
    undefined,
    () => createInitialTaskState(formatTimezoneForUser(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC")),
  );
  const triggeredReminderNotificationIds = useRef<Set<string>>(new Set());
  const callbacks = useRef({ onNotice, onTaskStage });

  callbacks.current = { onNotice, onTaskStage };

  const notifyTriggeredReminders = useCallback(async (items: TaskItem[]) => {
    const notify = window.agentDesktop?.showReminderNotification;
    if (!notify) {
      if (items.some((task) => task.reminder_id?.trim() && task.reminder_status === "triggered")) {
        dispatch({
          type: "setReminderNotification",
          summary: {
            status: "unsupported",
            detail: "当前运行环境不支持系统通知。",
          },
        });
      }
      return;
    }

    for (const task of items) {
      const reminderId = task.reminder_id?.trim();
      if (!reminderId || task.reminder_status !== "triggered") {
        continue;
      }
      if (triggeredReminderNotificationIds.current.has(reminderId)) {
        continue;
      }
      triggeredReminderNotificationIds.current.add(reminderId);
      const result = await notify({
        reminder_id: reminderId,
        title: task.title || "桌面记忆助手提醒",
        body: task.description || task.source_text || task.remind_at || "提醒已到期。",
      });
      dispatch({
        type: "setReminderNotification",
        summary: {
          status: result.status,
          detail:
            result.status === "shown"
              ? `已发送提醒：${task.title || reminderId}`
              : result.reason || `提醒 ${reminderId} 返回 ${result.status}`,
        },
      });
      if (result.status === "unsupported" || result.status === "failed") {
        callbacks.current.onNotice({
          tone: "error",
          message: `系统通知未送达：${result.reason || result.status}`,
        });
      }
    }
  }, []);

  const loadTasks = useCallback(async (options: { silent?: boolean } = {}) => {
    if (!options.silent) {
      dispatch({ type: "setLoading", loading: true });
    }
    try {
      const response = await api.listTasks();
      dispatch({ type: "setTasks", tasks: response.tasks });
      void notifyTriggeredReminders(response.tasks);
    } catch (error) {
      if (!options.silent) {
        callbacks.current.onNotice({ tone: "error", message: describeError(error, "任务加载失败") });
      }
    } finally {
      if (!options.silent) {
        dispatch({ type: "setLoading", loading: false });
      }
    }
  }, [api, notifyTriggeredReminders]);

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
    if (!window.agentDesktop?.showReminderNotification || !sidecarReady) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void loadTasks({ silent: true });
    }, 15000);
    return () => window.clearInterval(intervalId);
  }, [loadTasks, sidecarReady]);

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
    taskActionIds: state.actionIds,
    taskDraft: state.draft,
    tasks: state.tasks,
    updateTaskDraft,
  };
}
