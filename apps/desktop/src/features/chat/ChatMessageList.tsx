import type { ChatMessage } from "../../types";
import { EmptyState } from "../../components/layout";
import { formatCitationSourceLabel, formatMessageRole, formatRunStatus } from "./chatFormatters";

type ChatMessageListProps = {
  messages: ChatMessage[];
};

export function ChatMessageList({ messages }: ChatMessageListProps) {
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
            {message.citations?.length ? (
              <div className="message-events">
                {message.citations.slice(0, 4).map((citation) => (
                  <span key={`${message.id}-${citation.relative_path}-${citation.chunk_id || citation.note_id || citation.heading || ""}`}>
                    <strong>{formatCitationSourceLabel([citation])}</strong>
                    {citation.relative_path}
                  </span>
                ))}
              </div>
            ) : null}
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
