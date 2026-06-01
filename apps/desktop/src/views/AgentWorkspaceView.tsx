import { BellRing, CalendarDays, Check, CircleAlert, ListChecks, Loader2, MessageSquareText, ShieldCheck, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel } from "../components/layout";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import type { TaskItem, TaskLogItem, TaskStepItem, TaskWorkspaceItem } from "../types";
import { formatTaskStatus } from "../features/tasks/taskReducer";
import { FeatureWindowShell } from "./FeatureWindowShell";

type AgentTaskStatus = "running" | "approval" | "completed" | "failed";
type AgentStepStatus = "done" | "running" | "failed" | "pending";

type WorkspaceTask = {
  id: string;
  name: string;
  description: string;
  status: AgentTaskStatus;
  needsApproval: boolean;
  pendingAction: string;
};

type AgentStep = {
  index: number;
  tool: string;
  status: AgentStepStatus;
  duration: string;
};

type ExecutionLog = {
  time: string;
  content: string;
};

type AgentWorkspaceViewProps = {
  api: DesktopApi;
};

const statusLabels: Record<AgentTaskStatus, string> = {
  running: "进行中",
  approval: "等待审批",
  completed: "完成",
  failed: "失败",
};

const stepStatusLabels: Record<AgentStepStatus, string> = {
  done: "已完成",
  running: "执行中",
  failed: "失败",
  pending: "等待中",
};

const pollIntervalMs = 5000;

function mapTaskStatus(task: TaskWorkspaceItem): AgentTaskStatus {
  if (task.needs_approval) {
    return "approval";
  }
  if (task.status === "done") {
    return "completed";
  }
  if (task.status === "cancelled") {
    return "failed";
  }
  return "running";
}

function mapStepStatus(status: string): AgentStepStatus {
  if (status === "done" || status === "completed") {
    return "done";
  }
  if (status === "running" || status === "failed" || status === "pending") {
    return status;
  }
  if (status === "cancelled") {
    return "failed";
  }
  return "pending";
}

function formatDuration(durationMs: number): string {
  if (!Number.isFinite(durationMs) || durationMs <= 0) {
    return "--";
  }
  return `${(durationMs / 1000).toFixed(1)}s`;
}

function formatLogTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function toWorkspaceTask(task: TaskWorkspaceItem): WorkspaceTask {
  return {
    id: task.task_id,
    name: task.title,
    description: task.description || task.source_text || task.due_at || "暂无任务说明。",
    status: mapTaskStatus(task),
    needsApproval: task.needs_approval,
    pendingAction: task.approval_action || "等待人工确认",
  };
}

function toAgentStep(step: TaskStepItem): AgentStep {
  return {
    index: step.index,
    tool: step.tool_name,
    status: mapStepStatus(step.status),
    duration: formatDuration(step.duration_ms),
  };
}

function toExecutionLog(log: TaskLogItem): ExecutionLog {
  return {
    time: formatLogTime(log.timestamp),
    content: log.content,
  };
}

function renderStepStatus(status: AgentStepStatus) {
  const label = stepStatusLabels[status];
  return (
    <span className={`task-step-status ${status}`} aria-label={label} title={label}>
      {status === "done" ? <Check size={14} /> : null}
      {status === "running" ? <Loader2 className="spin" size={14} /> : null}
      {status === "failed" ? <X size={14} /> : null}
      {status === "pending" ? <span aria-hidden="true" className="task-step-pending-dot" /> : null}
    </span>
  );
}

function dateValue(value?: string | null): number {
  if (!value) {
    return 0;
  }
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function formatTaskDateTime(value?: string | null): string {
  const time = dateValue(value);
  if (!time) {
    return "无时间";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(time));
}

function localDateKey(value: string | null | undefined, timezone: string): string {
  const time = dateValue(value);
  if (!time) {
    return "";
  }
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(time));
}

function mergeTodayTasks(todayTasks: TaskItem[], allTasks: TaskItem[], timezone: string): TaskItem[] {
  const todayKey = localDateKey(new Date().toISOString(), timezone);
  const byId = new Map<string, TaskItem>();
  todayTasks.forEach((task) => byId.set(task.task_id, task));
  allTasks.forEach((task) => {
    if (localDateKey(task.due_at, timezone) === todayKey || localDateKey(task.remind_at, timezone) === todayKey) {
      byId.set(task.task_id, task);
    }
  });
  return Array.from(byId.values()).sort(
    (left, right) => (dateValue(left.due_at) || dateValue(left.remind_at)) - (dateValue(right.due_at) || dateValue(right.remind_at)),
  );
}

function upcomingReminderTasks(tasks: TaskItem[]): TaskItem[] {
  const now = Date.now();
  return tasks
    .filter((task) => task.reminder_status === "scheduled" && dateValue(task.remind_at) >= now)
    .sort((left, right) => dateValue(left.remind_at) - dateValue(right.remind_at))
    .slice(0, 5);
}

function triggeredReminderTasks(tasks: TaskItem[]): TaskItem[] {
  return tasks
    .filter((task) => task.reminder_status === "triggered")
    .sort((left, right) => (dateValue(right.triggered_at) || dateValue(right.remind_at)) - (dateValue(left.triggered_at) || dateValue(left.remind_at)))
    .slice(0, 5);
}

function reminderProblemTasks(tasks: TaskItem[]): TaskItem[] {
  return tasks
    .filter((task) => task.reminder_status === "unscheduled" || task.reminder_status === "failed")
    .sort((left, right) => dateValue(left.remind_at) - dateValue(right.remind_at))
    .slice(0, 5);
}

function formatReminderStatus(status?: string | null): string {
  const labels: Record<string, string> = {
    scheduled: "已安排",
    triggered: "已触发",
    unscheduled: "未安排",
    failed: "失败",
    cancelled: "已取消",
  };
  return status ? labels[status] || status : "无提醒";
}

function TaskDigestCard({ task, tone = "normal" }: { task: TaskItem; tone?: "normal" | "warning" | "success" }) {
  const primaryTime = task.due_at || task.remind_at;
  return (
    <article id={`task-${task.task_id}`} className={`task-digest-card ${tone}`}>
      <div className="task-digest-head">
        <strong>{task.title}</strong>
        <span>{formatTaskStatus(task.status)}</span>
      </div>
      {task.description || task.source_text ? <p>{task.description || task.source_text}</p> : null}
      <div className="task-digest-meta">
        <small>时间：{formatTaskDateTime(primaryTime)}</small>
        {task.remind_at ? <small>提醒：{formatTaskDateTime(task.remind_at)} / {formatReminderStatus(task.reminder_status)}</small> : null}
        {task.triggered_at ? <small>触发：{formatTaskDateTime(task.triggered_at)}</small> : null}
        {task.timezone_label || task.timezone ? <small>时区：{task.timezone_label || task.timezone}</small> : null}
      </div>
    </article>
  );
}

export default function AgentWorkspaceView({ api }: AgentWorkspaceViewProps) {
  const [currentTask, setCurrentTask] = useState<WorkspaceTask | null>(null);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [todayTasks, setTodayTasks] = useState<TaskItem[]>([]);
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionBusy, setActionBusy] = useState<"approve" | "reject" | null>(null);
  const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  const loadWorkspace = useCallback(
    async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
      if (!options.silent) {
        setLoading(true);
      }
      setError("");
      try {
        const [current, allTasks, today] = await Promise.all([
          api.fetchCurrentTask(options.signal),
          api.listTasks(options.signal),
          api.listTodayTasks(localTimezone, options.signal),
        ]);
        setTasks(allTasks.tasks);
        setTodayTasks(today.tasks);
        if (!current.task) {
          setCurrentTask(null);
          setAgentSteps([]);
          setExecutionLogs([]);
          return;
        }
        const [steps, logs] = await Promise.all([
          api.fetchTaskSteps(current.task.task_id, options.signal),
          api.fetchTaskLogs(current.task.task_id, options.signal),
        ]);
        setCurrentTask(toWorkspaceTask(current.task));
        setAgentSteps(steps.steps.map(toAgentStep));
        setExecutionLogs(logs.logs.map(toExecutionLog));
      } catch (requestError) {
        if (requestError instanceof DOMException && requestError.name === "AbortError") {
          return;
        }
        setError(describeError(requestError, "任务加载失败"));
      } finally {
        if (!options.silent) {
          setLoading(false);
        }
      }
    },
    [api, localTimezone],
  );

  useEffect(() => {
    const abort = new AbortController();
    void loadWorkspace({ signal: abort.signal });
    const timer = window.setInterval(() => {
      void loadWorkspace({ silent: true });
    }, pollIntervalMs);
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, [loadWorkspace]);

  async function actOnTask(action: "approve" | "reject") {
    if (!currentTask) {
      return;
    }
    setActionBusy(action);
    setError("");
    try {
      if (action === "approve") {
        await api.approveTask(currentTask.id);
      } else {
        await api.rejectTask(currentTask.id);
      }
      await loadWorkspace({ silent: true });
    } catch (requestError) {
      setError(describeError(requestError, action === "approve" ? "任务批准失败" : "任务拒绝失败"));
    } finally {
      setActionBusy(null);
    }
  }

  const title = loading && !currentTask ? "正在加载任务" : currentTask?.name || "暂无当前任务";
  const statusLabel = currentTask ? statusLabels[currentTask.status] : loading ? "进行中" : "完成";
  const statusTone = currentTask?.status || (loading ? "running" : "completed");
  const description = currentTask?.description || (loading ? "正在从后端读取任务状态。" : "当前没有待展示的任务。");
  const mergedTodayTasks = mergeTodayTasks(todayTasks, tasks, localTimezone);
  const upcomingReminders = upcomingReminderTasks(tasks);
  const triggeredReminders = triggeredReminderTasks(tasks);
  const reminderProblems = reminderProblemTasks(tasks);

  return (
    <FeatureWindowShell
      eyebrow="本地执行"
      title="任务"
      description="查看当前任务、执行步骤、审批动作和运行日志。"
      activeTab="任务"
    >
      <div className="task-workspace-grid" aria-label="任务工作台">
        <Panel icon={<ListChecks size={18} />} title="当前任务" className="feature-window-panel task-current-panel">
          <div className="task-current-header">
            <div className="section-heading">
              <strong>{title}</strong>
              <span>{error || description}</span>
            </div>
            <span className={`task-status-badge ${statusTone}`}>{statusLabel}</span>
          </div>
          {error ? <p className="field-note error">{error}</p> : null}
          {currentTask ? (
            <dl className="details task-details">
              <div>
                <dt>状态</dt>
                <dd>{statusLabels[currentTask.status]}</dd>
              </div>
              <div>
                <dt>审批</dt>
                <dd>{currentTask.needsApproval ? currentTask.pendingAction : "无需人工确认"}</dd>
              </div>
            </dl>
          ) : (
            <EmptyState text={loading ? "正在加载当前任务。" : "暂无当前任务。"} />
          )}
        </Panel>

        {currentTask?.needsApproval ? (
          <Panel icon={<ShieldCheck size={18} />} title="审批操作" className="feature-window-panel task-approval-panel">
            <p className="field-note">即将执行：{currentTask.pendingAction}</p>
            <div className="button-row task-button-row">
              <button
                type="button"
                className="secondary"
                disabled={actionBusy !== null}
                onClick={() => void actOnTask("reject")}
              >
                {actionBusy === "reject" ? <Loader2 className="spin" size={16} /> : <X size={16} />}
                {actionBusy === "reject" ? "正在拒绝" : "拒绝"}
              </button>
              <button
                type="button"
                disabled={actionBusy !== null}
                onClick={() => void actOnTask("approve")}
              >
                {actionBusy === "approve" ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
                {actionBusy === "approve" ? "正在批准" : "批准"}
              </button>
            </div>
          </Panel>
        ) : null}

        <Panel icon={<CalendarDays size={18} />} title="今天任务" className="feature-window-panel task-daily-panel">
          <div className="task-digest-list" aria-label="今天任务列表">
            {mergedTodayTasks.length > 0 ? (
              mergedTodayTasks.map((task) => <TaskDigestCard key={`today-${task.task_id}`} task={task} />)
            ) : (
              <EmptyState text={loading ? "正在加载今天任务。" : "今天没有到期任务或提醒。"} />
            )}
          </div>
        </Panel>

        <Panel icon={<BellRing size={18} />} title="即将提醒" className="feature-window-panel task-reminder-panel">
          <div className="task-digest-list" aria-label="即将提醒列表">
            {upcomingReminders.length > 0 ? (
              upcomingReminders.map((task) => <TaskDigestCard key={`upcoming-${task.task_id}`} task={task} />)
            ) : (
              <EmptyState text={loading ? "正在加载即将提醒。" : "暂无已安排的即将提醒。"} />
            )}
          </div>
        </Panel>

        <Panel icon={<Check size={18} />} title="已触发提醒" className="feature-window-panel task-triggered-panel">
          <div className="task-digest-list" aria-label="已触发提醒状态">
            {triggeredReminders.length > 0 ? (
              triggeredReminders.map((task) => (
                <TaskDigestCard key={`triggered-${task.task_id}`} task={task} tone="success" />
              ))
            ) : (
              <EmptyState text={loading ? "正在加载已触发提醒。" : "还没有已触发提醒。"} />
            )}
          </div>
        </Panel>

        <Panel icon={<CircleAlert size={18} />} title="需要处理" className="feature-window-panel task-reminder-alert-panel">
          <div className="task-reminder-alert">
            <strong>
              {reminderProblems.length > 0
                ? `${reminderProblems.length} 条提醒未安排或失败`
                : "没有未调度或失败提醒"}
            </strong>
            <span>
              {reminderProblems.length > 0
                ? "这些任务仍保留在本地列表中，但提醒未进入可靠调度。"
                : "调度器当前没有报告需要人工处理的提醒。"}
            </span>
          </div>
          <div className="task-digest-list" aria-label="未调度或失败提醒">
            {reminderProblems.length > 0 ? (
              reminderProblems.map((task) => (
                <TaskDigestCard key={`problem-${task.task_id}`} task={task} tone="warning" />
              ))
            ) : null}
          </div>
        </Panel>

        <Panel icon={<ListChecks size={18} />} title="执行步骤" className="feature-window-panel task-steps-panel">
          <div className="task-step-list" aria-label="工具步骤列表">
            {agentSteps.length > 0 ? (
              agentSteps.map((step) => (
                <article key={`${step.tool}-${step.index}`} className="task-step-row">
                  <span className="task-step-index">{String(step.index).padStart(2, "0")}</span>
                  <strong>{step.tool}</strong>
                  {renderStepStatus(step.status)}
                  <span className="task-step-duration">{step.duration}</span>
                </article>
              ))
            ) : (
              <EmptyState text={loading ? "正在加载执行步骤。" : "暂无执行步骤。"} />
            )}
          </div>
        </Panel>

        <Panel icon={<MessageSquareText size={18} />} title="执行日志" className="feature-window-panel task-log-panel">
          <div className="task-log-list" aria-label="执行日志">
            {executionLogs.length > 0 ? (
              executionLogs.map((log) => (
                <p key={`${log.time}-${log.content}`} className="task-log-line">
                  <span>{log.time}</span>
                  {log.content}
                </p>
              ))
            ) : (
              <EmptyState text={loading ? "正在加载执行日志。" : "暂无执行日志。"} />
            )}
          </div>
        </Panel>
      </div>
    </FeatureWindowShell>
  );
}
