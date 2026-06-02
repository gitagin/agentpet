import { CheckCircle2, CircleAlert, Clock3, Loader2, RotateCcw, SkipForward } from "lucide-react";
import type { AgentAction, TaskItem } from "../../types";
import {
  canRevertAgentAction,
  getAgentActionDisplayFields,
} from "../../services/agentActivity";
import { formatTaskStatus } from "../tasks/taskReducer";

type ChatAgentActionSummaryProps = {
  actions: AgentAction[];
  tasks?: TaskItem[];
  showEmpty?: boolean;
  revertingActionIds?: Set<string>;
  onRevertAgentAction?: (action: AgentAction) => void;
  onOpenMemory?: () => void;
};

type SummaryBucketKey =
  | "chat_diary"
  | "structured_diary"
  | "long_term_memory"
  | "wiki_summary"
  | "tasks"
  | "skipped";

type SummaryBucket = {
  key: SummaryBucketKey;
  label: string;
  emptyText: string;
  actions: AgentAction[];
  tasks: TaskItem[];
};

const bucketDefinitions: Array<Omit<SummaryBucket, "actions" | "tasks">> = [
  {
    key: "chat_diary",
    label: "写入日记",
    emptyText: "本轮没有聊天日记写入事件。",
  },
  {
    key: "structured_diary",
    label: "结构化记忆",
    emptyText: "本轮没有结构化日记事件。",
  },
  {
    key: "long_term_memory",
    label: "长期记忆",
    emptyText: "本轮没有长期记忆写入事件。",
  },
  {
    key: "wiki_summary",
    label: "Wiki 摘要",
    emptyText: "本轮没有 Wiki 摘要写入事件。",
  },
  {
    key: "tasks",
    label: "任务/提醒",
    emptyText: "本轮没有任务或提醒事件。",
  },
  {
    key: "skipped",
    label: "已跳过",
    emptyText: "本轮没有跳过记录。",
  },
];

function isPendingConfirmation(action: AgentAction): boolean {
  return action.decision === "ask" && action.status !== "completed" && action.status !== "reverted";
}

export function ChatAgentActionSummary({
  actions,
  tasks = [],
  showEmpty = false,
  revertingActionIds,
  onRevertAgentAction,
  onOpenMemory,
}: ChatAgentActionSummaryProps) {
  const hasResults = actions.length > 0 || tasks.length > 0;
  if (!hasResults && !showEmpty) {
    return null;
  }

  const buckets = buildSummaryBuckets(actions, tasks);
  const pendingCount = actions.filter(isPendingConfirmation).length;
  const failedCount = actions.filter((action) => action.status === "failed" || Boolean(action.error)).length;
  const skippedCount = actions.filter((action) => classifyAction(action) === "skipped").length;
  const completedCount = actions.filter((action) => action.status === "completed").length + tasks.length;

  return (
    <section className="message-agent-actions" aria-label="本轮整理结果">
      <div className="message-agent-actions-head">
        <div>
          <strong>本轮整理结果</strong>
          <span>
            {completedCount > 0 ? `${completedCount} 项已整理` : "未产生可保存内容"}
            {skippedCount > 0 ? ` / ${skippedCount} 项已跳过` : ""}
            {pendingCount > 0 ? ` / ${pendingCount} 项需要确认` : ""}
            {failedCount > 0 ? ` / ${failedCount} 项失败` : ""}
          </span>
        </div>
        {onOpenMemory ? (
          <button type="button" className="secondary" onClick={onOpenMemory}>
            查看活动
          </button>
        ) : null}
      </div>
      {!hasResults ? (
        <p className="message-agent-action-empty-reason">
          未产生可保存内容。本轮没有收到可追踪的自动整理活动或任务事件。
        </p>
      ) : null}

      <div className="message-agent-action-buckets">
        {buckets.map((bucket) => (
          <SummaryBucketCard
            key={bucket.key}
            bucket={bucket}
            revertingActionIds={revertingActionIds}
            onRevertAgentAction={onRevertAgentAction}
          />
        ))}
      </div>
    </section>
  );
}

function SummaryBucketCard({
  bucket,
  revertingActionIds,
  onRevertAgentAction,
}: {
  bucket: SummaryBucket;
  revertingActionIds?: Set<string>;
  onRevertAgentAction?: (action: AgentAction) => void;
}) {
  const hasEntries = bucket.actions.length > 0 || bucket.tasks.length > 0;
  const tone = bucketTone(bucket);
  return (
    <article className={`message-agent-action-bucket ${tone}`}>
      <div className="message-agent-action-bucket-head">
        {bucketIcon(tone)}
        <strong>{bucket.label}</strong>
        <span>{hasEntries ? bucket.actions.length + bucket.tasks.length : 0}</span>
      </div>
      {hasEntries ? (
        <div className="message-agent-action-list">
          {bucket.actions.map((action) => (
            <ActionResultRow
              key={action.action_id}
              action={action}
              reverting={Boolean(revertingActionIds?.has(action.action_id))}
              onRevertAgentAction={onRevertAgentAction}
            />
          ))}
          {bucket.tasks.map((task) => (
            <TaskResultRow key={task.task_id} task={task} />
          ))}
        </div>
      ) : (
        <p>{bucket.emptyText}</p>
      )}
    </article>
  );
}

function ActionResultRow({
  action,
  reverting,
  onRevertAgentAction,
}: {
  action: AgentAction;
  reverting: boolean;
  onRevertAgentAction?: (action: AgentAction) => void;
}) {
  const display = getAgentActionDisplayFields(action);
  const canRevert = canRevertAgentAction(action);
  const pending = isPendingConfirmation(action);
  return (
    <div className={`message-agent-action ${pending ? "pending" : action.status}`}>
      <div>
        <strong>{display.actionName}</strong>
        <small>
          {display.riskTierLabel} / {display.statusLabel}
        </small>
      </div>
      <p>{display.summary}</p>
      <small>目标：{display.targetPathLabel}</small>
      {action.metadata?.skipped_reason ? <small>原因：{String(action.metadata.skipped_reason)}</small> : null}
      {action.error ? <small className="error">错误：{action.error}</small> : null}
      {pending ? <small className="error">需要确认后才会执行，请在整理页处理。</small> : null}
      {canRevert && onRevertAgentAction ? (
        <button
          type="button"
          className="secondary"
          onClick={() => onRevertAgentAction(action)}
          disabled={reverting}
          title={`撤销 ${display.actionName}`}
        >
          {reverting ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
          撤销
        </button>
      ) : null}
    </div>
  );
}

function TaskResultRow({ task }: { task: TaskItem }) {
  return (
    <div className="message-agent-action completed">
      <div>
        <strong>{task.title}</strong>
        <small>{formatTaskStatus(task.status)}</small>
      </div>
      {task.remind_at ? <small>提醒：{task.remind_at}</small> : null}
      {task.timezone_label || task.timezone ? <small>时区：{task.timezone_label || task.timezone}</small> : null}
    </div>
  );
}

function buildSummaryBuckets(actions: AgentAction[], tasks: TaskItem[]): SummaryBucket[] {
  const buckets = bucketDefinitions.map((definition) => ({
    ...definition,
    actions: [] as AgentAction[],
    tasks: [] as TaskItem[],
  }));
  const byKey = new Map(buckets.map((bucket) => [bucket.key, bucket]));
  for (const action of actions) {
    byKey.get(classifyAction(action))?.actions.push(action);
  }
  byKey.get("tasks")?.tasks.push(...tasks);
  return buckets;
}

function classifyAction(action: AgentAction): SummaryBucketKey {
  const actionType = action.action_type.toLocaleLowerCase();
  if (action.status === "skipped" || actionType.endsWith(".skip") || actionType.includes(".skip.")) {
    return "skipped";
  }
  if (actionType === "chat.daily_archive") {
    return "chat_diary";
  }
  if (actionType === "diary.structured_memory") {
    return "structured_diary";
  }
  if (actionType.startsWith("memory.long_term") || actionType.startsWith("continuity.")) {
    return "long_term_memory";
  }
  if (actionType.startsWith("wiki.")) {
    return "wiki_summary";
  }
  if (actionType.startsWith("task.")) {
    return "tasks";
  }
  return "skipped";
}

function bucketTone(bucket: SummaryBucket): "empty" | "success" | "pending" | "failed" | "skipped" {
  if (bucket.actions.some((action) => action.status === "failed" || Boolean(action.error))) {
    return "failed";
  }
  if (bucket.actions.some(isPendingConfirmation)) {
    return "pending";
  }
  if (bucket.key === "skipped" && bucket.actions.length > 0) {
    return "skipped";
  }
  if (bucket.actions.length > 0 || bucket.tasks.length > 0) {
    return "success";
  }
  return "empty";
}

function bucketIcon(tone: "empty" | "success" | "pending" | "failed" | "skipped") {
  if (tone === "success") {
    return <CheckCircle2 size={15} />;
  }
  if (tone === "pending") {
    return <Clock3 size={15} />;
  }
  if (tone === "failed") {
    return <CircleAlert size={15} />;
  }
  if (tone === "skipped") {
    return <SkipForward size={15} />;
  }
  return <Clock3 size={15} />;
}
