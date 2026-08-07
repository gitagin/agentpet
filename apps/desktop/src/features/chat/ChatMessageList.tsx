import type { Ref } from "react";
import type {
  AgentAction,
  ChatMessage,
  ChatTraceAgentId,
  ChatTracePhase,
  ChatTraceStatus,
  TaskItem,
} from "../../types";
import { EmptyState } from "../../components/layout";
import { AssistantMessageContent } from "./AssistantMessageContent";
import { stripAssistantActionDirectivesFromMarkdown } from "./assistantActionDirectives";
import { ChatAgentActionSummary } from "./ChatAgentActionSummary";
import { ChatCitationSummary } from "./ChatCitationSummary";
import { formatMessageRole, formatRunStatus } from "./chatFormatters";

type ChatMessageListProps = {
  messages: ChatMessage[];
  revertingActionIds?: Set<string>;
  onRevertAgentAction?: (action: AgentAction) => void;
  onOpenTask?: (task?: TaskItem) => void;
  onOpenMemory?: () => void;
  onOpenWiki?: (path?: string) => void;
  onOpenReport?: (path?: string) => void;
  listRef?: Ref<HTMLDivElement>;
};

const NEGOTIATION_PHASE_LABELS: Record<ChatTracePhase, string> = {
  invoking: "调用",
  reviewing: "复核",
  revising: "修订",
  synthesizing: "合成",
  completed: "完成",
};

const NEGOTIATION_AGENT_LABELS: Record<ChatTraceAgentId, string> = {
  orchestrator: "协调器",
  retrieval_agent: "检索 Agent",
  synthesizer: "回复整理器",
};

const NEGOTIATION_STATUS_LABELS: Record<ChatTraceStatus, string> = {
  running: "进行中",
  fallback: "安全兜底",
  completed: "已完成",
};

type ProgressCard = {
  id: string;
  label: string;
  detail: string;
  state: "active" | "done" | "queued";
};

export function ChatMessageList({
  messages,
  revertingActionIds,
  onRevertAgentAction,
  onOpenTask,
  onOpenMemory,
  onOpenWiki,
  onOpenReport,
  listRef,
}: ChatMessageListProps) {
  const visibleMessages = messages.filter((message) => message.role !== "system");

  return (
    <div
      ref={listRef}
      className={`message-list ${visibleMessages.length > 0 ? "has-messages" : "is-empty"}`}
      aria-label="助手对话记录"
    >
      {visibleMessages.length > 0 ? (
        visibleMessages.map((message) => {
          const showMeta = message.status === "failed" || message.status === "cancelled";
          const displayContent =
            message.role === "assistant"
              ? stripAssistantActionDirectivesFromMarkdown(message.content)
              : message.content;
          const hasContent = displayContent.trim().length > 0;
          const isPending = message.status === "partial" && !hasContent;
          return (
            <article key={message.id} id={`message-${message.id}`} className={`message-row ${message.role}`}>
              {message.role === "assistant" ? <span className="message-avatar" aria-hidden="true">AI</span> : null}
              <div className={`message message-bubble ${message.role}`}>
              {showMeta ? (
                <div className="message-meta">
                  <strong>{formatMessageRole(message.role)}</strong>
                  {message.status ? <span>{formatRunStatus(message.status)}</span> : null}
                </div>
              ) : null}
              {hasContent && message.role === "assistant" ? (
                <AssistantMessageContent content={displayContent} />
              ) : (
                <p className={isPending ? "message-pending" : undefined}>
                  {hasContent ? displayContent : message.status === "partial" ? "正在整理回答..." : "没有收到可显示内容。"}
                </p>
              )}
              {message.role === "assistant" ? (
                <>
                  {isPending ? renderAssistantProgress(message) : null}
                  {renderAssistantArtifacts(
                    message,
                    revertingActionIds,
                    onRevertAgentAction,
                    onOpenTask,
                    onOpenMemory,
                    onOpenWiki,
                    onOpenReport,
                  )}
                  {renderAssistantTrace(message)}
                </>
              ) : null}
              </div>
              {message.role === "user" ? <span className="message-avatar" aria-hidden="true">ME</span> : null}
            </article>
          );
        })
      ) : (
        <EmptyState text="还没有对话。可以直接和桌宠聊一句，之后这里会显示最近聊天。" />
      )}
    </div>
  );
}

function renderAssistantProgress(message: ChatMessage) {
  const cards = buildProgressCards(message);
  if (cards.length === 0) {
    return null;
  }

  return (
    <section className="message-agent-actions" aria-label="聊天进度">
      <div className="message-agent-action-buckets">
        {cards.map((card) => (
          <article key={card.id} className={`message-agent-action-bucket ${progressBucketClass(card.state)}`}>
            <div className="message-agent-action-bucket-head">
              <span aria-hidden="true">{progressBucketIcon(card.state)}</span>
              <strong>{card.label}</strong>
            </div>
            <p>{card.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function progressBucketClass(state: ProgressCard["state"]): string {
  if (state === "done") {
    return "success";
  }
  if (state === "queued") {
    return "empty";
  }
  return "pending";
}

function progressBucketIcon(state: ProgressCard["state"]): string {
  if (state === "done") {
    return "OK";
  }
  if (state === "queued") {
    return "-";
  }
  return "...";
}

function buildProgressCards(message: ChatMessage): ProgressCard[] {
  const hasRetrieval =
    Boolean(message.retrieval_attempted) ||
    Boolean(message.retrieval_context_budget) ||
    Boolean(message.retrieval_scopes?.length) ||
    Boolean(message.citations?.length);
  const stage = message.progress_stage || (hasRetrieval ? "retrieving" : "understanding");
  const stageOrder = ["understanding", "retrieving", "verifying", "answering"] as const;
  const activeIndex = stageOrder.indexOf(stage);
  const artifactCount = countArtifacts(message);
  const descriptions = [
    "判断你的问题和目标。",
    hasRetrieval ? formatProgressScopes(message.retrieval_scopes) : "准备检索本地记录。",
    message.negotiation_steps?.length
      ? `正在进行有界核验，已完成 ${message.negotiation_steps.length} 步。`
      : "检查证据是否足够。",
    artifactCount > 0 ? `回答会附带 ${artifactCount} 条结果回执。` : "整理成可直接阅读的回答。",
  ];

  return ["理解问题", "查找本地记忆", "核验来源", "完成"].map((label, index) => ({
    id: stageOrder[index],
    label,
    detail: descriptions[index],
    state: index < activeIndex ? "done" : index === activeIndex ? "active" : "queued",
  }));
}

function countArtifacts(message: ChatMessage): number {
  return (
    (message.agent_actions?.length || 0) +
    (message.memory_receipts?.length || 0) +
    (message.task_actions?.length || 0) +
    (message.memory_proposals?.length || 0) +
    (message.wiki_proposals?.length || 0)
  );
}

function formatProgressScopes(scopes: string[] | undefined): string {
  if (!scopes?.length) {
    return "相关资料已找到。";
  }
  const scopeLabels: Record<string, string> = {
    personal_memory: "长期记忆",
    diary_objects: "结构化日记",
    daily_chat: "聊天日记",
    knowledge_base: "资料库",
    pending_memory: "待确认记忆",
  };
  return scopes
    .slice(0, 3)
    .map((scope) => scopeLabels[scope] || "本地资料")
    .join("、");
}

function renderAssistantArtifacts(
  message: ChatMessage,
  revertingActionIds?: Set<string>,
  onRevertAgentAction?: (action: AgentAction) => void,
  onOpenTask?: (task?: TaskItem) => void,
  onOpenMemory?: () => void,
  onOpenWiki?: (path?: string) => void,
  onOpenReport?: (path?: string) => void,
) {
  const hasArtifacts = Boolean(
    message.agent_actions?.length ||
      message.memory_receipts?.length ||
      message.task_actions?.length ||
      message.memory_proposals?.length ||
      message.wiki_proposals?.length,
  );

  if (!hasArtifacts) {
    return null;
  }

  return (
    <ChatAgentActionSummary
      actions={message.agent_actions || []}
      receipts={message.memory_receipts || []}
      tasks={message.task_actions || []}
      memoryProposals={message.memory_proposals || []}
      wikiProposals={message.wiki_proposals || []}
      showEmpty={false}
      revertingActionIds={revertingActionIds}
      onRevertAgentAction={onRevertAgentAction}
      onOpenTask={onOpenTask}
      onOpenMemory={onOpenMemory}
      onOpenWiki={onOpenWiki}
      onOpenReport={onOpenReport}
    />
  );
}

function renderAssistantTrace(message: ChatMessage) {
  const hasCitationTrace =
    (message.citations?.length || 0) > 0 || Boolean(message.retrieval_attempted && message.status !== "partial");
  const hasEvents = Boolean(message.events?.length);
  const hasNegotiation = Boolean(message.negotiation_steps?.length);
  const hasContinuity = Boolean(message.continuity_signal);

  if (!hasCitationTrace && !hasEvents && !hasNegotiation && !hasContinuity) {
    return null;
  }

  return (
    <details className="message-trace">
      <summary>{traceSummary(message)}</summary>
      <ChatCitationSummary message={message} />
      {hasEvents ? (
        <div className="message-events">
          {message.events!.slice(-4).map((toolEvent) => (
            <span
              key={toolEvent.id}
              className={toolEvent.tone === "error" ? "error" : toolEvent.tone === "success" ? "success" : undefined}
            >
              <strong>{toolEvent.label}</strong>
              {toolEvent.detail}
            </span>
          ))}
        </div>
      ) : null}
      {hasNegotiation ? renderNegotiationTrace(message) : null}
      {message.continuity_signal ? (
        <div className="continuity-presence-hint">
          <strong>{message.continuity_signal.title}</strong>
          <span>{message.continuity_signal.summary}</span>
          <small>{message.continuity_signal.display_hint}</small>
        </div>
      ) : null}
    </details>
  );
}

function traceSummary(message: ChatMessage): string {
  const parts = [
    message.citations?.length ? `${message.citations.length} 条引用` : "",
    message.events?.length ? `${message.events.length} 条工具事件` : "",
    message.negotiation_steps?.length ? `${message.negotiation_steps.length} 步协作` : "",
  ].filter(Boolean);
  return parts.length ? `来源与整理 · ${parts.join(" / ")}` : "来源与整理";
}

function renderNegotiationTrace(message: ChatMessage) {
  return (
    <details className="message-negotiation">
      <summary>
        协作过程 · {message.negotiation_steps!.length} 步
        {message.negotiation_done ? " · 已完成" : ""}
      </summary>
      <ol className="message-negotiation-list">
        {message.negotiation_steps!.map((step, index) => (
          <li key={`${message.id}-negotiation-${index}`}>
            <strong>
              {NEGOTIATION_AGENT_LABELS[step.agent_id]} · {NEGOTIATION_PHASE_LABELS[step.phase]} · {formatTraceRound(step.round)}
            </strong>
            <span>{step.safe_summary}</span>
            <small>
              {NEGOTIATION_STATUS_LABELS[step.status]}
              {step.duration_ms > 0 ? ` · ${step.duration_ms}ms` : ""}
            </small>
          </li>
        ))}
      </ol>
      {message.negotiation_done ? (
        <span className="message-negotiation-done">
          完成 {message.negotiation_done.counts.rounds} 轮，调用 {message.negotiation_done.counts.agents_invoked} 个子 Agent，耗时 {message.negotiation_done.duration_ms}ms
          {message.negotiation_done.reason_code === "negotiation_completed_with_fallback" ? "，已使用安全兜底" : ""}。
        </span>
      ) : null}
    </details>
  );
}

function formatTraceRound(round: number): string {
  return round > 0 ? `第 ${round} 轮` : "准备阶段";
}
