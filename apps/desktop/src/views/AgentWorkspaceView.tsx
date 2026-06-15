import {
  BellRing,
  CalendarDays,
  Check,
  CircleAlert,
  ClipboardList,
  ListChecks,
  Loader2,
  LocateFixed,
  MessageSquareText,
  PlusCircle,
  ShieldCheck,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { EmptyState, Panel } from "../components/layout";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import type { TaskItem, TaskLogItem, TaskStepItem, TaskWorkspaceItem } from "../types";
import { formatTaskStatus } from "../features/tasks/taskReducer";
import { useTasks } from "../features/tasks/useTasks";
import { FeatureWindowShell } from "./FeatureWindowShell";

type AgentTaskStatus = "idle" | "running" | "approval" | "completed" | "cancelled" | "failed";
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

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type AgentWorkspaceViewProps = {
  api: DesktopApi;
};

const statusLabels: Record<AgentTaskStatus, string> = {
  idle: "空闲",
  running: "运行中",
  approval: "需要确认",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
};

const stepStatusLabels: Record<AgentStepStatus, string> = {
  done: "已完成",
  running: "运行中",
  failed: "失败",
  pending: "等待中",
};

const pollIntervalMs = 30000;

function mapTaskStatus(task: TaskWorkspaceItem): AgentTaskStatus {
  if (task.needs_approval) {
    return "approval";
  }
  if (task.status === "done" || task.status === "completed") {
    return "completed";
  }
  if (task.status === "cancelled") {
    return "cancelled";
  }
  if (task.status === "failed") {
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
    pendingAction: task.approval_action || "等待确认",
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

function formatDateTimeLocal(value: Date): string {
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

function tomorrowMorningLocal(): string {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  return formatDateTimeLocal(date);
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

function isTaskClosed(task: TaskItem): boolean {
  return task.status === "done" || task.status === "completed" || task.status === "cancelled";
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

function TaskManagementCard({
  task,
  busy,
  onComplete,
  onCancel,
  onLocate,
}: {
  task: TaskItem;
  busy: boolean;
  onComplete: () => void;
  onCancel: () => void;
  onLocate: () => void;
}) {
  const closed = isTaskClosed(task);
  return (
    <article id={`task-card-${task.task_id}`} className={`task-management-card ${task.status}`}>
      <div className="task-management-main">
        <div className="task-digest-head">
          <strong>{task.title}</strong>
          <span>{formatTaskStatus(task.status)}</span>
        </div>
        {task.description || task.source_text ? <p>{task.description || task.source_text}</p> : null}
        <div className="task-digest-meta">
          {task.due_at ? <small>截止：{formatTaskDateTime(task.due_at)}</small> : null}
          {task.remind_at ? <small>提醒：{formatTaskDateTime(task.remind_at)} / {formatReminderStatus(task.reminder_status)}</small> : null}
          {task.timezone_label || task.timezone ? <small>时区：{task.timezone_label || task.timezone}</small> : null}
          {!task.due_at && !task.remind_at ? <small>未设置截止时间或提醒。</small> : null}
        </div>
      </div>
      <div className="task-management-actions">
        <button type="button" className="secondary" onClick={onComplete} disabled={busy || closed}>
          {busy ? <Loader2 className="spin" size={15} /> : <Check size={15} />}
          完成
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={busy || closed}>
          {busy ? <Loader2 className="spin" size={15} /> : <X size={15} />}
          取消
        </button>
        <button type="button" className="secondary" onClick={onLocate}>
          <LocateFixed size={15} />
          定位日志/步骤
        </button>
      </div>
    </article>
  );
}

export default function AgentWorkspaceView({ api }: AgentWorkspaceViewProps) {
  const [currentTask, setCurrentTask] = useState<WorkspaceTask | null>(null);
  const [todayTasks, setTodayTasks] = useState<TaskItem[]>([]);
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([]);
  const [traceTask, setTraceTask] = useState<{ id: string; title: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [traceLoading, setTraceLoading] = useState(false);
  const [error, setError] = useState("");
  const [taskNotice, setTaskNotice] = useState<Notice | null>(null);
  const [approvalBusy, setApprovalBusy] = useState<"approve" | "reject" | null>(null);
  const [creatingTask, setCreatingTask] = useState(false);
  const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  const loadTaskTrace = useCallback(
    async (taskId: string, title: string, options: { silent?: boolean; signal?: AbortSignal } = {}) => {
      if (!options.silent) {
        setTraceLoading(true);
      }
      setError("");
      try {
        const [steps, logs] = await Promise.all([
          api.fetchTaskSteps(taskId, options.signal),
          api.fetchTaskLogs(taskId, options.signal),
        ]);
        setTraceTask({ id: taskId, title });
        setAgentSteps(steps.steps.map(toAgentStep));
        setExecutionLogs(logs.logs.map(toExecutionLog));
      } catch (requestError) {
        if (requestError instanceof DOMException && requestError.name === "AbortError") {
          return;
        }
        setError(describeError(requestError, "任务日志和步骤加载失败"));
      } finally {
        if (!options.silent) {
          setTraceLoading(false);
        }
      }
    },
    [api],
  );

  const loadWorkspace = useCallback(
    async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
      if (!options.silent) {
        setLoading(true);
      }
      setError("");
      try {
        const [current, today] = await Promise.all([
          api.fetchCurrentTask(options.signal),
          api.listTodayTasks(localTimezone, options.signal),
        ]);
        setTodayTasks(today.tasks);
        if (!current.task) {
          setCurrentTask(null);
          setTraceTask(null);
          setAgentSteps([]);
          setExecutionLogs([]);
          return;
        }
        const workspaceTask = toWorkspaceTask(current.task);
        setCurrentTask(workspaceTask);
        await loadTaskTrace(workspaceTask.id, workspaceTask.name, { silent: true, signal: options.signal });
      } catch (requestError) {
        if (requestError instanceof DOMException && requestError.name === "AbortError") {
          return;
        }
        setError(describeError(requestError, "任务工作区加载失败"));
      } finally {
        if (!options.silent) {
          setLoading(false);
        }
      }
    },
    [api, loadTaskTrace, localTimezone],
  );

  const {
    actOnTask,
    createTask,
    loadTasks,
    loadingTasks,
    taskActionIds,
    taskDraft,
    tasks,
    updateTaskDraft,
  } = useTasks({
    api,
    pollingEnabled: false,
    sidecarReady: true,
    onNotice: setTaskNotice,
    onTaskStage: () => void loadWorkspace({ silent: true }),
  });

  const refreshTaskPage = useCallback(
    async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
      await Promise.all([loadWorkspace(options), loadTasks({ silent: options.silent })]);
    },
    [loadTasks, loadWorkspace],
  );

  useEffect(() => {
    const abort = new AbortController();
    void refreshTaskPage({ signal: abort.signal });
    const timer = window.setInterval(() => {
      void refreshTaskPage({ silent: true, signal: abort.signal });
    }, pollIntervalMs);
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, [refreshTaskPage]);

  async function handleCreateTask(event: FormEvent) {
    setCreatingTask(true);
    await createTask(event);
    await refreshTaskPage({ silent: true });
    setCreatingTask(false);
  }

  async function handleTaskAction(taskId: string, action: "complete" | "cancel") {
    await actOnTask(taskId, action);
    await refreshTaskPage({ silent: true });
  }

  async function locateTaskLogs(task: TaskItem) {
    await loadTaskTrace(task.task_id, task.title);
    window.requestAnimationFrame(() => {
      document.getElementById("task-steps-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function fillTomorrowReminderTrial() {
    const remindAt = tomorrowMorningLocal();
    updateTaskDraft({
      title: "检查发布清单",
      description: "从任务工作区创建的快捷试用提醒。",
      due_at: remindAt,
      remind_at: remindAt,
      timezone: localTimezone,
    });
  }

  async function actOnApproval(action: "approve" | "reject") {
    if (!currentTask) {
      return;
    }
    setApprovalBusy(action);
    setError("");
    try {
      if (action === "approve") {
        await api.approveTask(currentTask.id);
      } else {
        await api.rejectTask(currentTask.id);
      }
      await refreshTaskPage({ silent: true });
    } catch (requestError) {
      setError(describeError(requestError, action === "approve" ? "任务确认失败" : "任务拒绝失败"));
    } finally {
      setApprovalBusy(null);
    }
  }

  const title = loading && !currentTask ? "正在加载当前任务" : currentTask?.name || "暂无当前任务";
  const statusLabel = currentTask ? statusLabels[currentTask.status] : loading ? statusLabels.running : statusLabels.idle;
  const statusTone = currentTask?.status || (loading ? "running" : "idle");
  const description = currentTask?.description || (loading ? "正在从本地 sidecar 读取任务状态。" : "当前没有正在运行的任务。");
  const mergedTodayTasks = mergeTodayTasks(todayTasks, tasks, localTimezone);
  const upcomingReminders = upcomingReminderTasks(tasks);
  const triggeredReminders = triggeredReminderTasks(tasks);
  const reminderProblems = reminderProblemTasks(tasks);

  return (
    <FeatureWindowShell
      eyebrow="本地执行"
      title="任务"
      description="直接创建提醒、管理任务卡片，并保留执行步骤和日志作为辅助细节。"
      activeTab="今日"
    >
      <div className="task-workspace-grid" aria-label="任务工作区">
        <Panel icon={<PlusCircle size={18} />} title="创建任务" className="feature-window-panel task-create-panel">
          <div className="guided-trial-actions" aria-label="任务快捷示例">
            <button type="button" className="secondary" onClick={fillTomorrowReminderTrial} disabled={creatingTask}>
              <BellRing size={16} />
              创建明天的提醒
            </button>
          </div>
          <form className="task-create-form" aria-label="任务创建表单" onSubmit={(event) => void handleCreateTask(event)}>
            <label>
              <span>任务标题</span>
              <input
                value={taskDraft.title}
                onChange={(event) => updateTaskDraft({ title: event.target.value })}
                placeholder="支付账单、回电话、检查笔记..."
                disabled={creatingTask}
                required
              />
            </label>
            <label>
              <span>说明</span>
              <textarea
                rows={3}
                value={taskDraft.description}
                onChange={(event) => updateTaskDraft({ description: event.target.value })}
                placeholder="补充背景、预期结果，或希望助手记住的内容。"
                disabled={creatingTask}
              />
            </label>
            <div className="task-create-time-grid">
              <label>
                <span>截止时间</span>
                <input
                  type="datetime-local"
                  value={taskDraft.due_at || ""}
                  onChange={(event) => updateTaskDraft({ due_at: event.target.value })}
                  disabled={creatingTask}
                />
              </label>
              <label>
                <span>提醒时间</span>
                <input
                  type="datetime-local"
                  value={taskDraft.remind_at || ""}
                  onChange={(event) => updateTaskDraft({ remind_at: event.target.value })}
                  disabled={creatingTask}
                />
              </label>
              <label>
                <span>时区</span>
                <input
                  value={taskDraft.timezone}
                  onChange={(event) => updateTaskDraft({ timezone: event.target.value })}
                  placeholder="Asia/Shanghai"
                  disabled={creatingTask}
                />
              </label>
            </div>
            {taskNotice ? <p className={`field-note ${taskNotice.tone === "error" ? "error" : ""}`}>{taskNotice.message}</p> : null}
            <div className="button-row task-button-row">
              <button type="submit" disabled={creatingTask || !taskDraft.title.trim()}>
                {creatingTask ? <Loader2 className="spin" size={16} /> : <PlusCircle size={16} />}
                {creatingTask ? "正在创建" : "创建任务"}
              </button>
              <button type="button" className="secondary" onClick={() => void refreshTaskPage()} disabled={loading || loadingTasks}>
                {loading || loadingTasks ? <Loader2 className="spin" size={16} /> : <ClipboardList size={16} />}
                刷新任务
              </button>
            </div>
          </form>
        </Panel>

        <Panel icon={<ClipboardList size={18} />} title="管理任务" className="feature-window-panel task-list-panel">
          <div className="task-management-list" aria-label="任务卡片">
            {tasks.length > 0 ? (
              tasks.map((task) => (
                <TaskManagementCard
                  key={task.task_id}
                  task={task}
                  busy={taskActionIds.has(task.task_id)}
                  onComplete={() => void handleTaskAction(task.task_id, "complete")}
                  onCancel={() => void handleTaskAction(task.task_id, "cancel")}
                  onLocate={() => void locateTaskLogs(task)}
                />
              ))
            ) : loadingTasks ? (
              <EmptyState text="正在加载任务卡片。" />
            ) : (
              <EmptyState text="还没有任务。可以用上方表单创建第一个任务。" />
            )}
          </div>
        </Panel>

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
                <dt>确认</dt>
                <dd>{currentTask.needsApproval ? currentTask.pendingAction : "无需确认"}</dd>
              </div>
            </dl>
          ) : (
            <EmptyState text={loading ? "正在加载当前任务。" : "暂无当前任务。"} />
          )}
        </Panel>

        {currentTask?.needsApproval ? (
          <Panel icon={<ShieldCheck size={18} />} title="确认操作" className="feature-window-panel task-approval-panel">
            <p className="field-note">待确认操作：{currentTask.pendingAction}</p>
            <div className="button-row task-button-row">
              <button
                type="button"
                className="secondary"
                disabled={approvalBusy !== null}
                onClick={() => void actOnApproval("reject")}
              >
                {approvalBusy === "reject" ? <Loader2 className="spin" size={16} /> : <X size={16} />}
                {approvalBusy === "reject" ? "正在拒绝" : "拒绝"}
              </button>
              <button
                type="button"
                disabled={approvalBusy !== null}
                onClick={() => void actOnApproval("approve")}
              >
                {approvalBusy === "approve" ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
                {approvalBusy === "approve" ? "正在确认" : "确认"}
              </button>
            </div>
          </Panel>
        ) : null}

        <Panel icon={<CalendarDays size={18} />} title="今天" className="feature-window-panel task-daily-panel">
          <div className="task-digest-list" aria-label="今日任务列表">
            {mergedTodayTasks.length > 0 ? (
              mergedTodayTasks.map((task) => <TaskDigestCard key={`today-${task.task_id}`} task={task} />)
            ) : (
              <EmptyState text={loading || loadingTasks ? "正在加载今天的任务。" : "今天没有到期任务或提醒。"} />
            )}
          </div>
        </Panel>

        <Panel icon={<BellRing size={18} />} title="即将提醒" className="feature-window-panel task-reminder-panel">
          <div className="task-digest-list" aria-label="即将提醒列表">
            {upcomingReminders.length > 0 ? (
              upcomingReminders.map((task) => <TaskDigestCard key={`upcoming-${task.task_id}`} task={task} />)
            ) : (
              <EmptyState text={loadingTasks ? "正在加载即将提醒。" : "没有已安排的即将提醒。"} />
            )}
          </div>
        </Panel>

        <Panel icon={<Check size={18} />} title="已触发提醒" className="feature-window-panel task-triggered-panel">
          <div className="task-digest-list" aria-label="已触发提醒列表">
            {triggeredReminders.length > 0 ? (
              triggeredReminders.map((task) => (
                <TaskDigestCard key={`triggered-${task.task_id}`} task={task} tone="success" />
              ))
            ) : (
              <EmptyState text={loadingTasks ? "正在加载已触发提醒。" : "还没有已触发提醒。"} />
            )}
          </div>
        </Panel>

        <Panel icon={<CircleAlert size={18} />} title="需要关注" className="feature-window-panel task-reminder-alert-panel">
          <div className="task-reminder-alert">
            <strong>
              {reminderProblems.length > 0
                ? `${reminderProblems.length} 条提醒未安排或失败`
                : "没有未安排或失败的提醒"}
            </strong>
            <span>
              {reminderProblems.length > 0
                ? "这些任务仍保留在本地列表中，但提醒没有进入可靠调度。"
                : "提醒调度器当前没有需要手动处理的问题。"}
            </span>
          </div>
          <div className="task-digest-list" aria-label="未安排或失败的提醒">
            {reminderProblems.length > 0 ? (
              reminderProblems.map((task) => (
                <TaskDigestCard key={`problem-${task.task_id}`} task={task} tone="warning" />
              ))
            ) : null}
          </div>
        </Panel>

        <Panel id="task-steps-panel" icon={<ListChecks size={18} />} title="执行步骤" className="feature-window-panel task-steps-panel">
          <div className="section-heading compact">
            <strong>{traceTask ? traceTask.title : "未选择任务"}</strong>
            <span>{traceLoading ? "正在加载任务步骤和日志。" : "在任务卡片中点击“定位日志/步骤”即可查看轨迹。"}</span>
          </div>
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
            ) : traceLoading ? (
              <EmptyState text="正在加载执行步骤。" />
            ) : (
              <EmptyState text="未选择执行步骤。" />
            )}
          </div>
        </Panel>

        <Panel id="task-log-panel" icon={<MessageSquareText size={18} />} title="执行日志" className="feature-window-panel task-log-panel">
          <div className="task-log-list" aria-label="执行日志">
            {executionLogs.length > 0 ? (
              executionLogs.map((log) => (
                <p key={`${log.time}-${log.content}`} className="task-log-line">
                  <span>{log.time}</span>
                  {log.content}
                </p>
              ))
            ) : traceLoading ? (
              <EmptyState text="正在加载执行日志。" />
            ) : (
              <EmptyState text="未选择执行日志。" />
            )}
          </div>
        </Panel>
      </div>
    </FeatureWindowShell>
  );
}
