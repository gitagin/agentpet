import type { AgentAction, ChatMessage, ChatNegotiationAction } from "../../types";
import { EmptyState } from "../../components/layout";
import { ChatAgentActionSummary } from "./ChatAgentActionSummary";
import { ChatCitationSummary } from "./ChatCitationSummary";
import { formatMessageRole, formatRunStatus } from "./chatFormatters";

type ChatMessageListProps = {
  messages: ChatMessage[];
  revertingActionIds?: Set<string>;
  onRevertAgentAction?: (action: AgentAction) => void;
  onOpenMemory?: () => void;
};

const NEGOTIATION_ACTION_LABELS: Record<ChatNegotiationAction, string> = {
  invoking: "调用",
  reviewing: "复核",
  revising: "修订",
  synthesizing: "合成",
};

function formatConfidence(confidence: number | undefined): string {
  if (typeof confidence !== "number" || Number.isNaN(confidence)) {
    return "置信度未知";
  }
  return `置信度 ${Math.round(Math.max(0, Math.min(1, confidence)) * 100)}%`;
}

export function ChatMessageList({
  messages,
  revertingActionIds,
  onRevertAgentAction,
  onOpenMemory,
}: ChatMessageListProps) {
  const visibleMessages = messages.filter((message) => message.role !== "system");

  return (
    <div className="message-list" aria-label="Agent 对话记录">
      {visibleMessages.length > 0 ? (
        visibleMessages.map((message) => {
          const showMeta = message.status === "failed" || message.status === "cancelled";
          const isPending = message.status === "partial" && !message.content;
          return (
            <article key={message.id} className={`message ${message.role}`}>
              {showMeta ? (
                <div className="message-meta">
                  <strong>{formatMessageRole(message.role)}</strong>
                  {message.status ? <span>{formatRunStatus(message.status)}</span> : null}
                </div>
              ) : null}
              <p className={isPending ? "message-pending" : undefined}>
                {message.content || (message.status === "partial" ? "正在想..." : "没有收到可显示内容。")}
              </p>
              {message.role === "assistant"
                ? renderAssistantTrace(message, revertingActionIds, onRevertAgentAction, onOpenMemory)
                : null}
            </article>
          );
        })
      ) : (
        <EmptyState text="还没有对话。可以直接和桌宠聊一句，之后这里会显示最近聊天。" />
      )}
    </div>
  );
}

function renderAssistantTrace(
  message: ChatMessage,
  revertingActionIds?: Set<string>,
  onRevertAgentAction?: (action: AgentAction) => void,
  onOpenMemory?: () => void,
) {
  const hasCitationTrace =
    (message.citations?.length || 0) > 0 || Boolean(message.retrieval_attempted && message.status !== "partial");
  const hasEvents = Boolean(message.events?.length);
  const hasActions = Boolean(message.agent_actions?.length || message.task_actions?.length);
  const hasNegotiation = Boolean(message.negotiation_steps?.length);
  const hasContinuity = Boolean(message.continuity_signal);

  if (!hasCitationTrace && !hasEvents && !hasActions && !hasNegotiation && !hasContinuity) {
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
      {hasActions ? (
        <ChatAgentActionSummary
          actions={message.agent_actions || []}
          tasks={message.task_actions || []}
          showEmpty={false}
          revertingActionIds={revertingActionIds}
          onRevertAgentAction={onRevertAgentAction}
          onOpenMemory={onOpenMemory}
        />
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
    message.agent_actions?.length ? `${message.agent_actions.length} 条整理` : "",
    message.task_actions?.length ? `${message.task_actions.length} 个任务` : "",
  ].filter(Boolean);
  return parts.length ? `来源与整理 · ${parts.join(" / ")}` : "来源与整理";
}

function renderNegotiationTrace(message: ChatMessage) {
  return (
    <details className="message-negotiation">
      <summary>
        协作过程 · {message.negotiation_steps!.length} 步
        {message.negotiation_done ? ` · ${formatConfidence(message.negotiation_done.final_confidence)}` : ""}
      </summary>
      <ol className="message-negotiation-list">
        {message.negotiation_steps!.map((step, index) => (
          <li key={`${message.id}-negotiation-${index}`}>
            <strong>
              {step.agent} · {NEGOTIATION_ACTION_LABELS[step.action]} · 第 {step.round + 1} 轮
            </strong>
            <span>{step.message || step.reasoning || "正在整理协商上下文。"}</span>
            {step.reasoning && step.reasoning !== step.message ? <small>{step.reasoning}</small> : null}
            <small>{formatConfidence(step.confidence)}</small>
          </li>
        ))}
      </ol>
      {message.negotiation_done ? (
        <span className="message-negotiation-done">
          调用 {message.negotiation_done.agents_invoked.length} 个子 Agent，耗时 {message.negotiation_done.total_latency_ms}ms
          {message.negotiation_done.fallback ? "，已使用轮次上限兜底" : ""}。
        </span>
      ) : null}
    </details>
  );
}
