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
  return (
    <div className="message-list" aria-label="Agent 对话记录">
      {messages.length > 0 ? (
        messages.map((message) => (
          <article key={message.id} className={`message ${message.role}`}>
            <div className="message-meta">
              <strong>{formatMessageRole(message.role)}</strong>
              {message.status ? <span>{formatRunStatus(message.status)}</span> : null}
            </div>
            <p>{message.content || (message.status === "partial" ? "Agent 正在生成回复..." : "无内容")}</p>
            <ChatCitationSummary message={message} />
            {message.events?.length ? (
              <div className="message-events">
                {message.events.slice(-4).map((toolEvent) => (
                  <span key={toolEvent.id} className={toolEvent.tone === "error" ? "error" : undefined}>
                    <strong>{toolEvent.label}</strong>
                    {toolEvent.detail}
                  </span>
                ))}
              </div>
            ) : null}
            {message.role === "assistant" &&
            (message.status === "completed" || message.agent_actions?.length || message.task_actions?.length) ? (
              <ChatAgentActionSummary
                actions={message.agent_actions || []}
                tasks={message.task_actions || []}
                showEmpty={message.status === "completed"}
                revertingActionIds={revertingActionIds}
                onRevertAgentAction={onRevertAgentAction}
                onOpenMemory={onOpenMemory}
              />
            ) : null}
            {message.negotiation_steps?.length ? (
              <details className="message-negotiation">
                <summary>
                  思考过程 · 已思考 {message.negotiation_steps.length} 步
                  {message.negotiation_done ? ` · ${formatConfidence(message.negotiation_done.final_confidence)}` : ""}
                </summary>
                <ol className="message-negotiation-list">
                  {message.negotiation_steps.map((step, index) => (
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
            ) : null}
            {message.continuity_signal ? (
              <div className="continuity-presence-hint">
                <strong>{message.continuity_signal.title}</strong>
                <span>{message.continuity_signal.summary}</span>
                <small>{message.continuity_signal.display_hint}</small>
              </div>
            ) : null}
          </article>
        ))
      ) : (
        <EmptyState text="还没有对话。先绑定 Obsidian/Markdown 资料库，然后和桌宠聊一句。" />
      )}
    </div>
  );
}
