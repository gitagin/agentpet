import { formatTaskStatus, formatTimezoneForUser } from "../../tasks/taskReducer";
import type { StreamHandlerInput } from "../streamDispatcher";
import { PET_BUBBLE_ACTION_WATCHDOG_TIMEOUT_MS } from "../chatTiming";

export function taskHandler({ messageId, payload, context }: StreamHandlerInput, taskId: string) {
  const { petChat, addTaskFromChat, appendChatEvent, setMessages, triggerPetTaskStage } = context;
  const title = typeof payload?.title === "string" ? payload.title : "聊天创建的任务";
  const remindAt = typeof payload?.remind_at === "string" ? payload.remind_at : undefined;
  const timezone = typeof payload?.timezone === "string" ? payload.timezone : undefined;
  const timezoneLabel =
    typeof payload?.timezone_label === "string" ? payload.timezone_label : formatTimezoneForUser(timezone);
  const reminderStatus = typeof payload?.reminder_status === "string" ? payload.reminder_status : undefined;
  const task = {
    task_id: taskId,
    reminder_id: typeof payload?.reminder_id === "string" ? payload.reminder_id : undefined,
    title,
    status: typeof payload?.status === "string" ? payload.status : "pending",
    reminder_status: reminderStatus,
    remind_at: remindAt,
    timezone,
    timezone_label: timezoneLabel,
  };
  addTaskFromChat(task);
  setMessages((current) =>
    current.map((message) => {
      if (message.id !== messageId) {
        return message;
      }
      const existing = message.task_actions || [];
      return {
        ...message,
        task_actions: [...existing.filter((item) => item.task_id !== task.task_id), task],
      };
    }),
  );
  triggerPetTaskStage();
  appendChatEvent(messageId, {
    label: "任务",
    detail: `已创建任务：${title}${remindAt ? `；提醒时间 ${remindAt}` : ""}${timezoneLabel ? `；时区 ${timezoneLabel}` : ""}${reminderStatus ? `；提醒状态 ${formatTaskStatus(reminderStatus)}` : ""}`,
    tone: "success",
  });
  if (!petChat.replyStartedRef.current) {
    petChat.showBubble({
      title: "正在记录提醒",
      message: `${title}${remindAt ? ` · ${remindAt}` : ""}${timezoneLabel ? ` · ${timezoneLabel}` : ""}`,
      tone: "reminder",
    });
    petChat.scheduleStreamWatchdog(
      "还在想",
      "提醒已记录，这次需要多等一会儿。",
      PET_BUBBLE_ACTION_WATCHDOG_TIMEOUT_MS,
      () => petChat.failStream(messageId, "没有等到回复", "提醒已记录，但这次没有等到可显示的回复。"),
    );
  }
}
