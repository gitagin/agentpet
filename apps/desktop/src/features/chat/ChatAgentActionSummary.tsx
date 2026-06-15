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
import type { AgentAction, ChatWikiProposal, MemoryProposal, TaskItem } from "../../types";
import {
  buildAgentOutcomeActivities,
  canRevertAgentAction,
  classifyAgentActionArtifact,
  type AgentOutcomeActivity,
  getAgentActionDisplayFields,
} from "../../services/agentActivity";
import { formatProposalStatus } from "../memory/memoryUtils";
import { formatTaskStatus } from "../tasks/taskReducer";

type ChatAgentActionSummaryProps = {
  actions: AgentAction[];
  tasks?: TaskItem[];
  memoryProposals?: MemoryProposal[];
  wikiProposals?: ChatWikiProposal[];
  showEmpty?: boolean;
  revertingActionIds?: Set<string>;
  onRevertAgentAction?: (action: AgentAction) => void;
  onOpenTask?: (task?: TaskItem) => void;
  onOpenMemory?: () => void;
  onOpenWiki?: (path?: string) => void;
  onOpenReport?: (path?: string) => void;
};

type ArtifactKind = "task" | "memory" | "wiki" | "review";
type ArtifactTone = "success" | "pending" | "failed" | "reverted";

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
  showEmpty = false,
  revertingActionIds,
  onRevertAgentAction,
  onOpenTask,
  onOpenMemory,
  onOpenWiki,
  onOpenReport,
}: ChatAgentActionSummaryProps) {
  const artifacts = buildArtifactCards(actions, tasks, memoryProposals, wikiProposals);
  const teamActivities = buildAgentOutcomeActivities(actions, tasks, memoryProposals, wikiProposals);
  if (artifacts.length === 0 && !showEmpty) {
    return null;
  }

  const pendingCount = artifacts.filter((artifact) => artifact.tone === "pending").length;
  const failedCount = artifacts.filter((artifact) => artifact.tone === "failed").length;

  return (
    <section className="message-agent-actions chat-artifacts" aria-label="聊天整理结果">
      <div className="message-agent-actions-head">
        <div>
          <strong>整理结果</strong>
          <span>
            {artifacts.length > 0 ? `${artifacts.length} 个结果` : "没有整理结果"}
            {pendingCount > 0 ? ` / ${pendingCount} 个待确认` : ""}
            {failedCount > 0 ? ` / ${failedCount} 个失败` : ""}
          </span>
        </div>
      </div>
      {artifacts.length === 0 ? (
        <p className="message-agent-action-empty-reason">
          本轮没有创建任务、记忆、知识页或复盘报告。
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
        <strong>自动整理活动</strong>
        <span>{activities.length} 个结果支持区域</span>
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
      {artifact.path ? <code>{artifact.path}</code> : null}
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
            title={`撤销 ${artifact.title}`}
          >
            {reverting ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />}
            撤销
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
): ArtifactCard[] {
  const cards: ArtifactCard[] = [];

  tasks.forEach((task) => {
    cards.push({
      id: `task-${task.task_id}`,
      kind: "task",
      tone: task.status === "failed" ? "failed" : "success",
      eyebrow: "已创建任务",
      title: task.title,
      summary: task.remind_at ? `提醒：${task.remind_at}` : "已从本轮聊天创建。",
      meta: [formatTaskStatus(task.status), task.timezone_label || task.timezone || ""].filter(Boolean),
      task,
    });
  });

  memoryProposals.forEach((proposal) => {
    cards.push({
      id: `memory-proposal-${proposal.proposal_id}`,
      kind: "memory",
      tone: proposal.status === "failed" ? "failed" : proposal.status === "pending" ? "pending" : "success",
      eyebrow: proposal.status === "pending" ? "记忆待确认" : "已写入记忆",
      title: proposal.target_path || "长期记忆",
      summary: proposal.content || proposal.preview_markdown || "有一条记忆候选正在等待复核。",
      meta: [formatProposalStatus(proposal.status), proposal.type].filter(Boolean),
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
        eyebrow: proposal.state === "applied" ? "已写入知识页" : "知识页待确认",
        title: proposal.title || path || "知识页",
        summary: proposal.review_summary || proposal.summary || proposal.error || "有一条知识页更新正在等待复核。",
        meta: [formatWikiProposalState(proposal.state), proposal.proposal_type].filter(Boolean),
        path,
      });
    });

  actions.forEach((action) => {
    const kind = classifyAgentActionArtifact(action);
    if (!kind) {
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
      title: display.actionName,
      summary: display.summary,
      meta: [display.statusLabel, display.riskTierLabel].filter(Boolean),
      path,
      action,
    });
  });

  return cards;
}

function primaryArtifactAction(
  artifact: ArtifactCard,
  onOpenTask?: (task?: TaskItem) => void,
  onOpenMemory?: () => void,
  onOpenWiki?: (path?: string) => void,
  onOpenReport?: (path?: string) => void,
): { label: string; onClick: () => void } | null {
  if (artifact.kind === "task" && onOpenTask) {
    return { label: "打开任务", onClick: () => onOpenTask(artifact.task) };
  }
  if (artifact.kind === "memory" && onOpenMemory) {
    return { label: "打开记忆", onClick: onOpenMemory };
  }
  if (artifact.kind === "wiki" && onOpenWiki) {
    return { label: "打开知识页", onClick: () => onOpenWiki(artifact.path) };
  }
  if (artifact.kind === "review" && onOpenReport) {
    return { label: "打开报告", onClick: () => onOpenReport(artifact.path) };
  }
  return null;
}

function actionEyebrow(action: AgentAction, kind: ArtifactKind): string {
  if (kind === "task") {
    return "已创建任务";
  }
  if (kind === "review") {
    return "已生成复盘";
  }
  if (kind === "memory") {
    return action.decision === "ask" || action.status === "pending" ? "记忆待确认" : "已写入记忆";
  }
  return action.decision === "ask" || action.status === "pending" ? "知识页待确认" : "已写入知识页";
}

function actionTone(action: AgentAction): ArtifactTone {
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
  return <CheckCircle2 size={17} />;
}
