import {
  BookOpenText,
  Brain,
  CheckCircle2,
  CircleAlert,
  ClipboardList,
  FileText,
  Loader2,
  RotateCcw,
} from "lucide-react";
import type { AgentAction, ChatWikiProposal, MemoryProposal, MemoryReceiptItem, TaskItem } from "../../types";
import {
  buildAgentOutcomeActivities,
  canRevertAgentAction,
  classifyAgentActionArtifact,
  type AgentOutcomeActivity,
  getAgentActionDisplayFields,
  isSkippedAgentAction,
} from "../../services/agentActivity";
import { memoryTypeLabels } from "../memory/memoryConstants";
import { formatProposalStatus } from "../memory/memoryUtils";
import { formatTaskStatus } from "../tasks/taskReducer";

type ChatAgentActionSummaryProps = {
  actions: AgentAction[];
  tasks?: TaskItem[];
  memoryProposals?: MemoryProposal[];
  wikiProposals?: ChatWikiProposal[];
  receipts?: MemoryReceiptItem[];
  showEmpty?: boolean;
  revertingActionIds?: Set<string>;
  onRevertAgentAction?: (action: AgentAction) => void;
  onOpenTask?: (task?: TaskItem) => void;
  onOpenMemory?: () => void;
  onOpenWiki?: (path?: string) => void;
  onOpenReport?: (path?: string) => void;
};

type ArtifactKind = "task" | "memory" | "wiki" | "review" | "skip";
type ArtifactTone = "success" | "pending" | "failed" | "reverted" | "skipped";

type ArtifactCard = {
  id: string;
  kind: ArtifactKind;
  tone: ArtifactTone;
  eyebrow: string;
  title: string;
  summary: string;
  meta: string[];
  path?: string;
  action?: AgentAction;
  task?: TaskItem;
};

export function ChatAgentActionSummary({
  actions,
  tasks = [],
  memoryProposals = [],
  wikiProposals = [],
  receipts = [],
  showEmpty = false,
  revertingActionIds,
  onRevertAgentAction,
  onOpenTask,
  onOpenMemory,
  onOpenWiki,
  onOpenReport,
}: ChatAgentActionSummaryProps) {
  const artifacts = buildArtifactCards(actions, tasks, memoryProposals, wikiProposals, receipts);
  const teamActivities = buildAgentOutcomeActivities(actions, tasks, memoryProposals, wikiProposals);
  if (artifacts.length === 0 && !showEmpty) {
    return null;
  }

  const pendingCount = artifacts.filter((artifact) => artifact.tone === "pending").length;
  const failedCount = artifacts.filter((artifact) => artifact.tone === "failed").length;
  const skippedCount = artifacts.filter((artifact) => artifact.tone === "skipped").length;

  return (
    <section className="message-agent-actions chat-artifacts" aria-label="聊天整理结果">
      <div className="message-agent-actions-head">
        <div>
          <strong>这次我做了什么</strong>
          <span>
            {artifacts.length > 0 ? `${artifacts.length} 条回执` : "没有新回执"}
            {pendingCount > 0 ? ` / ${pendingCount} 条待确认` : ""}
            {failedCount > 0 ? ` / ${failedCount} 条未完成` : ""}
            {skippedCount > 0 ? ` / ${skippedCount} 条已跳过` : ""}
          </span>
        </div>
      </div>
      {artifacts.length === 0 ? (
        <p className="message-agent-action-empty-reason">
          这轮没有产生新的记忆、任务或资料整理。
        </p>
      ) : (
        <>
          <div className="chat-artifact-grid">
            {artifacts.map((artifact) => (
              <ArtifactResultCard
                key={artifact.id}
                artifact={artifact}
                reverting={Boolean(artifact.action && revertingActionIds?.has(artifact.action.action_id))}
                onRevertAgentAction={onRevertAgentAction}
                onOpenTask={onOpenTask}
                onOpenMemory={onOpenMemory}
                onOpenWiki={onOpenWiki}
                onOpenReport={onOpenReport}
              />
            ))}
          </div>
          <AiTeamActivity activities={teamActivities} />
        </>
      )}
    </section>
  );
}

function AiTeamActivity({ activities }: { activities: AgentOutcomeActivity[] }) {
  if (activities.length === 0) {
    return null;
  }

  return (
    <details className="ai-team-activity">
      <summary>
        <strong>整理明细</strong>
        <span>{activities.length} 类后台整理</span>
      </summary>
      <div className="ai-team-activity-list">
        {activities.map((activity) => (
          <article key={activity.key}>
            <strong>{activity.label}</strong>
            <span>{activity.description}</span>
            <small>{activity.detail}</small>
          </article>
        ))}
      </div>
    </details>
  );
}

function ArtifactResultCard({
  artifact,
  reverting,
  onRevertAgentAction,
  onOpenTask,
  onOpenMemory,
  onOpenWiki,
  onOpenReport,
}: {
  artifact: ArtifactCard;
  reverting: boolean;
  onRevertAgentAction?: (action: AgentAction) => void;
  onOpenTask?: (task?: TaskItem) => void;
  onOpenMemory?: () => void;
  onOpenWiki?: (path?: string) => void;
  onOpenReport?: (path?: string) => void;
}) {
  const canRevert = artifact.action ? canRevertAgentAction(artifact.action) : false;
  const primary = primaryArtifactAction(artifact, onOpenTask, onOpenMemory, onOpenWiki, onOpenReport);

  return (
    <article
      className={`chat-artifact-card ${artifact.kind} ${artifact.tone}`}
      aria-label={`${artifact.eyebrow}: ${artifact.title}`}
      data-artifact-kind={artifact.kind}
    >
      <div className="chat-artifact-card-head">
        {artifactIcon(artifact.kind, artifact.tone)}
        <div>
          <span>{artifact.eyebrow}</span>
          <strong>{artifact.title}</strong>
        </div>
      </div>
      <p>{artifact.summary}</p>
      <div className="chat-artifact-meta">
        {artifact.meta.map((item) => (
          <small key={item}>{item}</small>
        ))}
      </div>
      <div className="chat-artifact-actions">
        {primary ? (
          <button type="button" onClick={primary.onClick}>
            {primary.label}
          </button>
        ) : null}
        {canRevert && artifact.action && onRevertAgentAction ? (
          <button
            type="button"
            className="secondary"
            onClick={() => onRevertAgentAction(artifact.action!)}
            disabled={reverting}
            title={`撤回 ${artifact.title}`}
          >
            {reverting ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
            撤回
          </button>
        ) : null}
      </div>
    </article>
  );
}

function buildArtifactCards(
  actions: AgentAction[],
  tasks: TaskItem[],
  memoryProposals: MemoryProposal[],
  wikiProposals: ChatWikiProposal[],
  receipts: MemoryReceiptItem[],
): ArtifactCard[] {
  const cards: ArtifactCard[] = [];

  receipts.forEach((receipt) => {
    const kind: ArtifactKind = receipt.kind === "skipped" ? "skip" : "memory";
    cards.push({
      id: `memory-receipt-${receipt.id}`,
      kind,
      tone: receiptTone(receipt),
      eyebrow: receiptEyebrow(receipt),
      title: userSafeText(receipt.title, "记忆回执"),
      summary: userSafeText(
        [receipt.detail, receipt.safety_note].filter(Boolean).join(" "),
        "我已经整理了这轮聊天的记忆状态。",
      ),
      meta: receiptMeta(receipt),
    });
  });

  tasks.forEach((task) => {
    const taskFailed = task.status === "failed";
    cards.push({
      id: `task-${task.task_id}`,
      kind: "task",
      tone: taskFailed ? "failed" : "success",
      eyebrow: taskFailed ? "任务未创建" : "已创建任务",
      title: task.title,
      summary: taskFailed
        ? "这条任务没有创建成功，暂时不会提醒你。"
        : task.remind_at
          ? `我会按这个时间提醒你：${task.remind_at}`
          : "已从这轮聊天里记下一件待办。",
      meta: ["低风险", formatTaskStatus(task.status), taskFailed ? "未保存" : "", task.timezone_label || task.timezone || ""].filter(Boolean),
      task,
    });
  });

  memoryProposals.forEach((proposal) => {
    cards.push({
      id: `memory-proposal-${proposal.proposal_id}`,
      kind: "memory",
      tone: proposal.status === "failed" ? "failed" : proposal.status === "pending" ? "pending" : "success",
      eyebrow: proposal.status === "pending" ? "等你确认" : proposal.status === "failed" ? "记忆未保存" : "已记住",
      title: memoryTypeLabels[proposal.type] || "长期记忆",
      summary:
        proposal.status === "pending"
          ? userSafeText(proposal.content || proposal.preview_markdown, "这条记忆需要你确认后才会保存。")
          : proposal.status === "failed"
            ? "这条记忆没有保存成功，暂时不会影响之后的聊天。"
            : userSafeText(proposal.content || proposal.preview_markdown, "已写入长期记忆，之后聊天会参考。"),
      meta: [formatProposalStatus(proposal.status), proposal.status === "pending" ? "未写入" : "可查看"].filter(Boolean),
      path: proposal.target_path,
    });
  });

  wikiProposals
    .filter((proposal) => proposal.state !== "rejected")
    .forEach((proposal) => {
      const path = firstPath(proposal.target_paths, proposal.selected_targets, proposal.recommended_targets);
      cards.push({
        id: `wiki-proposal-${proposal.id}`,
        kind: "wiki",
        tone: proposal.state === "failed" ? "failed" : proposal.state === "applied" ? "success" : "pending",
        eyebrow: proposal.state === "applied" ? "已整理资料" : proposal.state === "failed" ? "资料未保存" : "等你确认",
        title: userSafeText(proposal.title, "资料整理"),
        summary:
          proposal.state === "failed"
            ? userSafeText(proposal.error || proposal.review_summary || proposal.summary, "这次资料整理没有保存成功。")
            : proposal.state === "applied"
              ? userSafeText(proposal.review_summary || proposal.summary, "已把可复用内容整理成资料页。")
              : userSafeText(proposal.review_summary || proposal.summary, "需要你确认后才会写入资料页。"),
        meta: [formatWikiProposalState(proposal.state), proposal.state === "applied" ? "可查看" : "未写入"].filter(Boolean),
        path,
      });
    });

  actions.forEach((action) => {
    const skipped = isSkippedAgentAction(action);
    const kind: ArtifactKind | null = skipped ? "skip" : classifyAgentActionArtifact(action);
    if (!kind) {
      return;
    }
    if (isReceiptCoveredAction(action, kind, receipts)) {
      return;
    }
    if (kind === "task" && tasks.length > 0) {
      return;
    }

    const display = getAgentActionDisplayFields(action);
    const path = firstPath(action.target_paths);
    cards.push({
      id: `agent-action-${action.action_id}`,
      kind,
      tone: actionTone(action),
      eyebrow: actionEyebrow(action, kind),
      title: actionTitle(action, kind, display),
      summary: actionSummary(action, kind, display),
      meta: actionMeta(action, kind, display),
      path,
      action,
    });
  });

  return cards;
}

function receiptTone(receipt: MemoryReceiptItem): ArtifactTone {
  if (receipt.kind === "needs_confirmation") {
    return "pending";
  }
  if (receipt.kind === "filtered" || receipt.kind === "skipped") {
    return "skipped";
  }
  if (receipt.kind === "forgotten") {
    return "reverted";
  }
  return "success";
}

function receiptEyebrow(receipt: MemoryReceiptItem): string {
  const labels: Record<string, string> = {
    remembered: "已记住",
    skipped: "未保存",
    needs_confirmation: "需要确认",
    updated: "已更新",
    forgotten: "已忘记",
    filtered: "已过滤",
    used_for_answer: "本次参考",
  };
  return labels[receipt.kind] || "记忆回执";
}

function receiptMeta(receipt: MemoryReceiptItem): string[] {
  const meta = ["本机记忆回执"];
  if (receipt.safety_note) {
    meta.push(receipt.safety_note);
  }
  if (receipt.action_label) {
    meta.push(receipt.action_label);
  }
  return meta.map((item) => userSafeText(item, "安全摘要"));
}

function isReceiptCoveredAction(action: AgentAction, kind: ArtifactKind, receipts: MemoryReceiptItem[]): boolean {
  if (receipts.length === 0) {
    return false;
  }
  const actionType = action.action_type.toLocaleLowerCase();
  const memoryLike =
    kind === "memory" || actionType.startsWith("memory.") || actionType.startsWith("continuity.") || actionType.includes("memory");
  if (!memoryLike && kind !== "skip") {
    return false;
  }
  const tone = actionTone(action);
  if (tone === "failed" || tone === "pending" || tone === "reverted") {
    return false;
  }
  const receiptKinds = new Set(receipts.map((receipt) => receipt.kind));
  if (kind === "skip" || isSkippedAgentAction(action)) {
    return receiptKinds.has("skipped");
  }
  return ["remembered", "updated", "forgotten", "filtered"].some((receiptKind) => receiptKinds.has(receiptKind));
}

function primaryArtifactAction(
  artifact: ArtifactCard,
  onOpenTask?: (task?: TaskItem) => void,
  onOpenMemory?: () => void,
  onOpenWiki?: (path?: string) => void,
  onOpenReport?: (path?: string) => void,
): { label: string; onClick: () => void } | null {
  if (artifact.kind === "task" && onOpenTask) {
    return { label: "查看任务", onClick: () => onOpenTask(artifact.task) };
  }
  if (artifact.kind === "memory" && onOpenMemory) {
    return { label: "查看记忆", onClick: onOpenMemory };
  }
  if (artifact.kind === "wiki" && onOpenWiki) {
    return { label: "查看资料页", onClick: () => onOpenWiki(artifact.path) };
  }
  if (artifact.kind === "review" && onOpenReport) {
    return { label: "查看报告", onClick: () => onOpenReport(artifact.path) };
  }
  return null;
}

function actionEyebrow(action: AgentAction, kind: ArtifactKind): string {
  if (kind === "skip") {
    return "已安全跳过";
  }
  if (kind === "task") {
    return action.status === "failed" || action.error ? "任务未创建" : "已创建任务";
  }
  if (kind === "review") {
    return action.status === "failed" || action.error ? "复盘未生成" : "已生成复盘";
  }
  if (kind === "memory") {
    if (action.status === "failed" || action.error) {
      return "记忆未保存";
    }
    if (action.status === "reverted") {
      return "记忆已撤回";
    }
    return action.decision === "ask" || action.status === "pending" ? "等你确认" : "已记住";
  }
  if (action.status === "failed" || action.error) {
    return "资料未保存";
  }
  if (action.status === "reverted") {
    return "整理已撤回";
  }
  return action.decision === "ask" || action.status === "pending" ? "等你确认" : "已整理资料";
}

function actionTone(action: AgentAction): ArtifactTone {
  if (isSkippedAgentAction(action)) {
    return "skipped";
  }
  if (action.status === "failed" || Boolean(action.error)) {
    return "failed";
  }
  if (action.status === "reverted") {
    return "reverted";
  }
  if (action.decision === "ask" || action.status === "pending" || action.status === "applying") {
    return "pending";
  }
  return "success";
}

function actionTitle(action: AgentAction, kind: ArtifactKind, display: ReturnType<typeof getAgentActionDisplayFields>): string {
  const actionType = action.action_type.toLocaleLowerCase();
  if (kind === "skip") {
    return userSafeText(display.actionName, "已跳过自动整理");
  }
  if (kind === "task") {
    return userSafeText(action.title, "任务");
  }
  if (kind === "review") {
    return userSafeText(action.title, "复盘报告");
  }
  if (actionType === "chat.daily_archive") {
    return "聊天日记";
  }
  if (actionType === "diary.structured_memory") {
    return "聊天重点";
  }
  if (actionType.startsWith("continuity.")) {
    return "陪伴状态";
  }
  if (actionType.startsWith("memory.")) {
    return userSafeText(action.title, "长期记忆");
  }
  if (actionType.startsWith("wiki.")) {
    return userSafeText(action.title, display.actionTypeLabel.includes("/") ? "资料整理" : display.actionTypeLabel);
  }
  return userSafeText(action.title || display.actionName, "整理结果");
}

function actionSummary(action: AgentAction, kind: ArtifactKind, display: ReturnType<typeof getAgentActionDisplayFields>): string {
  const actionType = action.action_type.toLocaleLowerCase();
  if (action.status === "failed" || action.error) {
    return userSafeText(action.error || display.summary, "这次整理没有完成，暂时没有保存新内容。");
  }
  if (kind === "skip") {
    return display.summary;
  }
  if (action.status === "reverted") {
    return "已撤回，这次整理不会再作为当前结果使用。";
  }
  if (action.decision === "ask" || action.status === "pending") {
    return "需要你确认后才会真正写入。";
  }
  if (actionType === "chat.daily_archive") {
    return "已把这轮聊天保存到本机日记，之后可以用来接上上下文。";
  }
  if (actionType === "diary.structured_memory") {
    return "已把这轮聊天提炼成可检索的日记线索。";
  }
  if (actionType.startsWith("continuity.")) {
    return "已更新陪伴状态，之后会用来接上关系、情绪或未完话题。";
  }
  if (actionType.startsWith("memory.long_term")) {
    return "已更新长期记忆，之后聊天会参考。";
  }
  if (actionType.startsWith("wiki.")) {
    return kind === "review" ? "已生成复盘报告，可在回顾里查看。" : "已把可复用内容整理成资料页。";
  }
  return userSafeText(display.summary, "已完成这次整理。");
}

function actionMeta(
  action: AgentAction,
  kind: ArtifactKind,
  display: ReturnType<typeof getAgentActionDisplayFields>,
): string[] {
  const meta = [display.statusLabel, display.riskTierLabel, display.decisionLabel];
  if (kind === "skip") {
    meta.push("没有写入", "无需撤回");
  } else if (action.status === "failed" || action.error) {
    meta.push("未保存");
  } else if (action.decision === "ask" || action.status === "pending") {
    meta.push("未写入");
  } else if (canRevertAgentAction(action)) {
    meta.push("可撤回");
  } else if (action.reversible) {
    meta.push("当前不可撤回");
  } else {
    meta.push("不可撤回");
  }
  return Array.from(new Set(meta.filter(Boolean)));
}

function userSafeText(value: string | undefined | null, fallback: string): string {
  const text = value?.trim();
  if (!text) {
    return fallback;
  }
  const internalPattern =
    /receipt:used:[^\s]+|\b(agent_actions?|agent_run_id|memory_candidates?|lifecycle_status|related_memory_id|source_text|source_excerpt|agent|proposal|vault|wiki|fts|vector|sidecar|runtime|authorization|token|skipped|saveable|confirmation-only|automation_disabled)\b|[A-Za-z]:\\|\.md\b|[\\/]/i;
  return internalPattern.test(text) ? fallback : text;
}

function firstPath(...groups: Array<string[] | undefined>): string | undefined {
  for (const group of groups) {
    const value = group?.find((item) => item.trim().length > 0);
    if (value) {
      return value;
    }
  }
  return undefined;
}

function formatWikiProposalState(state: ChatWikiProposal["state"]): string {
  const labels: Record<ChatWikiProposal["state"], string> = {
    pending: "待确认",
    confirmed: "已确认",
    rejected: "已拒绝",
    applying: "写入中",
    applied: "已写入",
    failed: "失败",
  };
  return labels[state] || state;
}

function artifactIcon(kind: ArtifactKind, tone: ArtifactTone) {
  if (tone === "failed") {
    return <CircleAlert size={17} />;
  }
  if (kind === "task") {
    return <ClipboardList size={17} />;
  }
  if (kind === "memory") {
    return <Brain size={17} />;
  }
  if (kind === "wiki") {
    return <BookOpenText size={17} />;
  }
  if (kind === "review") {
    return <FileText size={17} />;
  }
  if (kind === "skip") {
    return <CheckCircle2 size={17} />;
  }
  return <CheckCircle2 size={17} />;
}
