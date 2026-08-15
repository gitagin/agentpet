import { BellRing } from "lucide-react";
import type { TaskItem } from "../../types";
import { formatReminderNotificationStatus, type ReminderNotificationSummary } from "./taskReducer";

type TaskPanelProps = {
  tasks: TaskItem[];
  lastReminderNotification: ReminderNotificationSummary;
  onLocateTask: (targetId: string) => void;
  onRetryReminder: (taskId: string) => void;
};

export function TaskPanel({ tasks, lastReminderNotification, onLocateTask, onRetryReminder }: TaskPanelProps) {
  const hasTaskCreated = tasks.length > 0;
  const latestTask = tasks[0];
  const triggeredTasks = tasks.filter((task) => task.reminder_status === "triggered" && task.reminder_id);
  const triggeredReminderCount = triggeredTasks.length;
  const status = triggeredReminderCount > 0 ? "blocked" : hasTaskCreated ? "done" : "idle";
  const targetId = latestTask ? `task-${latestTask.task_id}` : undefined;

  return (
    <article className={`workflow-card ${status}`}>
      <span className="workflow-state">{formatWorkflowStatus(status)}</span>
      <strong>任务 / 提醒</strong>
      <p>
        {hasTaskCreated
          ? triggeredReminderCount > 0
            ? `${tasks.length} 条任务；${triggeredReminderCount} 条提醒待处理。通知只在你手动再次显示时调用。`
            : `${tasks.length} 条任务；通知：${formatReminderNotificationStatus(lastReminderNotification)}`
          : "当前没有任务或提醒；通过聊天或表单创建后会出现在这里。"}
      </p>
      {targetId ? (
        <button type="button" className="secondary" onClick={() => onLocateTask(targetId)}>
          定位
        </button>
      ) : null}
      {triggeredTasks.map((task) => (
        <button key={task.task_id} type="button" className="secondary" onClick={() => onRetryReminder(task.task_id)}>
          <BellRing size={15} />再次显示提醒
        </button>
      ))}
    </article>
  );
}

function formatWorkflowStatus(status: "done" | "active" | "idle" | "blocked"): string {
  const labels: Record<typeof status, string> = {
    done: "已就绪",
    active: "进行中",
    idle: "空闲",
    blocked: "待处理",
  };
  return labels[status];
}
