import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import type { DesktopApi } from "../services/desktopApi";
import { describeError } from "../services/apiErrorMessages";
import type { TaskLogItem, TaskStepItem, TaskWorkspaceItem } from "../types";
import { BottomNav } from "./BottomNav";

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

const statusColors: Record<AgentTaskStatus, string> = {
  running: "var(--color-active)",
  approval: "var(--color-primary)",
  completed: "var(--color-success)",
  failed: "#d9534f",
};

const stepIcons: Record<AgentStepStatus, string> = {
  done: "✓",
  running: "⏳",
  failed: "✕",
  pending: "○",
};

const workspaceStyles: Record<string, CSSProperties> = {
  shell: {
    minHeight: "100vh",
    width: "100%",
    maxWidth: 420,
    margin: "0 auto",
    padding: "var(--space-md)",
    boxSizing: "border-box",
    display: "grid",
    gridTemplateRows: "56px auto minmax(0, 1fr) auto 160px auto",
    gap: "var(--space-md)",
    color: "var(--color-text)",
    background: "var(--bg-agent)",
    fontFamily: "var(--font-sans)",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 16px",
  },
  headerTitle: {
    minWidth: 0,
    display: "grid",
    gap: 2,
  },
  eyebrow: {
    margin: 0,
    color: "var(--color-text-soft)",
    fontSize: 12,
  },
  title: {
    margin: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    fontSize: 18,
  },
  card: {
    padding: 16,
    display: "grid",
    gap: "var(--space-sm)",
  },
  statusBadge: {
    borderRadius: 999,
    padding: "4px 10px",
    color: "white",
    fontSize: 12,
    fontWeight: 700,
    whiteSpace: "nowrap",
  },
  taskDescription: {
    margin: 0,
    color: "var(--color-text-soft)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  stepList: {
    minHeight: 0,
    overflowY: "auto",
    display: "grid",
    alignContent: "start",
    gap: "var(--space-sm)",
    paddingRight: 2,
  },
  stepItem: {
    display: "grid",
    gridTemplateColumns: "28px minmax(0, 1fr) auto auto",
    gap: "var(--space-sm)",
    alignItems: "center",
    padding: "10px 12px",
    borderRadius: 16,
    background: "rgba(255, 255, 255, 0.62)",
  },
  stepIndex: {
    color: "var(--color-text-soft)",
    fontSize: 12,
  },
  stepTool: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    fontWeight: 700,
  },
  stepDuration: {
    color: "var(--color-text-soft)",
    fontSize: 12,
  },
  approvalBar: {
    padding: 14,
    display: "grid",
    gap: "var(--space-sm)",
  },
  approvalText: {
    margin: 0,
    color: "var(--color-text-soft)",
    fontSize: 13,
  },
  buttonRow: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "var(--space-sm)",
  },
  rejectButton: {
    border: "1px solid #d9534f",
    borderRadius: 999,
    padding: "8px 14px",
    color: "#d9534f",
    background: "transparent",
    cursor: "pointer",
  },
  approveButton: {
    border: "none",
    borderRadius: 999,
    padding: "8px 14px",
    color: "white",
    background: "var(--color-success)",
    cursor: "pointer",
    fontWeight: 700,
  },
  logPanel: {
    height: 160,
    overflowY: "auto",
    padding: 12,
    borderRadius: 16,
    background: "rgba(0, 0, 0, 0.04)",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    boxSizing: "border-box",
  },
  logLine: {
    margin: "0 0 6px",
    color: "var(--color-text)",
  },
  logTime: {
    color: "var(--color-text-soft)",
    marginRight: 8,
  },
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

  const taskStatusColor = useMemo(
    () => statusColors[currentTask?.status || "running"],
    [currentTask?.status],
  );

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

  return (
    <main style={workspaceStyles.shell} aria-label="任务工作台">
      <header className="glass-card" style={workspaceStyles.header}>
        <div style={workspaceStyles.headerTitle}>
          <p style={workspaceStyles.eyebrow}>当前任务</p>
          <h1 style={workspaceStyles.title}>{title}</h1>
        </div>
        <span style={{ ...workspaceStyles.statusBadge, background: taskStatusColor }}>
          {statusLabel}
        </span>
      </header>

      <section className="glass-card" style={workspaceStyles.card} aria-label="当前任务详情">
        <strong>{title}</strong>
        <p style={workspaceStyles.taskDescription}>
          {error || currentTask?.description || (loading ? "正在从后端读取任务状态。" : "当前没有待展示的任务。")}
        </p>
        {currentTask ? (
          <span style={{ ...workspaceStyles.statusBadge, width: "fit-content", background: taskStatusColor }}>
            {statusLabels[currentTask.status]}
          </span>
        ) : null}
      </section>

      <section style={workspaceStyles.stepList} aria-label="工具步骤列表">
        {agentSteps.length > 0 ? (
          agentSteps.map((step) => (
            <article key={`${step.tool}-${step.index}`} className="glass-card" style={workspaceStyles.stepItem}>
              <span style={workspaceStyles.stepIndex}>{String(step.index).padStart(2, "0")}</span>
              <span style={workspaceStyles.stepTool}>{step.tool}</span>
              <span aria-label={step.status}>{stepIcons[step.status]}</span>
              <span style={workspaceStyles.stepDuration}>{step.duration}</span>
            </article>
          ))
        ) : (
          <article className="glass-card" style={workspaceStyles.card}>
            <p style={workspaceStyles.taskDescription}>{loading ? "正在加载执行步骤。" : "暂无执行步骤。"}</p>
          </article>
        )}
      </section>

      {currentTask?.needsApproval ? (
        <section className="glass-card" style={workspaceStyles.approvalBar} aria-label="审批操作栏">
          <p style={workspaceStyles.approvalText}>即将执行：{currentTask.pendingAction}</p>
          <div style={workspaceStyles.buttonRow}>
            <button
              type="button"
              style={workspaceStyles.rejectButton}
              disabled={actionBusy !== null}
              onClick={() => void actOnTask("reject")}
            >
              {actionBusy === "reject" ? "正在拒绝" : "拒绝"}
            </button>
            <button
              type="button"
              style={workspaceStyles.approveButton}
              disabled={actionBusy !== null}
              onClick={() => void actOnTask("approve")}
            >
              {actionBusy === "approve" ? "正在批准" : "批准"}
            </button>
          </div>
        </section>
      ) : null}

      <section style={workspaceStyles.logPanel} aria-label="执行日志">
        {executionLogs.length > 0 ? (
          executionLogs.map((log) => (
            <p key={`${log.time}-${log.content}`} style={workspaceStyles.logLine}>
              <span style={workspaceStyles.logTime}>{log.time}</span>
              {log.content}
            </p>
          ))
        ) : (
          <p style={workspaceStyles.logLine}>{loading ? "正在加载执行日志。" : "暂无执行日志。"}</p>
        )}
      </section>
      <BottomNav activeTab="任务" />
    </main>
  );
}
