import { formatTaskStatus, formatTimezoneForUser } from "../../tasks/taskReducer";
import type { StreamHandlerInput } from "../streamDispatcher";

export function taskHandler({ messageId, payload, context }: StreamHandlerInput, taskId: string) {
  const { petChat, addTaskFromChat, appendChatEvent, triggerLive2DTaskStage } = context;
  const title = typeof payload?.title === "string" ? payload.title : "聊天创建的任务";
  const remindAt = typeof payload?.remind_at === "string" ? payload.remind_at : undefined;
  const timezone = typeof payload?.timezone === "string" ? payload.timezone : undefined;
  const timezoneLabel =
    typeof payload?.timezone_label === "string" ? payload.timezone_label : formatTimezoneForUser(timezone);
  const reminderStatus = typeof payload?.reminder_status === "string" ? payload.reminder_status : undefined;
  addTaskFromChat({
    task_id: taskId,
    reminder_id: typeof payload?.reminder_id === "string" ? payload.reminder_id : undefined,
    title,
    status: typeof payload?.status === "string" ? payload.status : "pending",
    reminder_status: reminderStatus,
    remind_at: remindAt,
    timezone,
    timezone_label: timezoneLabel,
  });
  triggerLive2DTaskStage();
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
      "等待回复内容",
      "提醒已记录，正在等待模型生成最终回复。",
      12000,
      () => petChat.failStream(messageId, "模型回复超时", "提醒已记录，但模型长时间没有返回最终回复。"),
    );
  }
}
