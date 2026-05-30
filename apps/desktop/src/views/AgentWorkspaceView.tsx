import { Check, ListChecks, Loader2, MessageSquareText, ShieldCheck, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { EmptyState, Panel } from "../components/layout";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import type { TaskLogItem, TaskStepItem, TaskWorkspaceItem } from "../types";
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

export default function AgentWorkspaceView({ api }: AgentWorkspaceViewProps) {
  const [currentTask, setCurrentTask] = useState<WorkspaceTask | null>(null);
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);
  const [executionLogs, setExecutionLogs] = useState<ExecutionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionBusy, setActionBusy] = useState<"approve" | "reject" | null>(null);

  const loadWorkspace = useCallback(
    async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
      if (!options.silent) {
        setLoading(true);
      }
      setError("");
      try {
        const current = await api.fetchCurrentTask(options.signal);
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
    [api],
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
