import type { ChatMessage, Citation } from "../../types";
import { formatCitationRetrievalMode, formatCitationSourceScope } from "./chatFormatters";

type ChatCitationSummaryProps = {
  message: ChatMessage;
};

const MAX_VISIBLE_CITATIONS = 6;
const MAX_SNIPPET_CHARS = 180;

export function ChatCitationSummary({ message }: ChatCitationSummaryProps) {
  const citations = message.citations || [];
  const shouldShow =
    message.role === "assistant" &&
    (citations.length > 0 || Boolean(message.retrieval_attempted && message.status !== "partial"));

  if (!shouldShow) {
    return null;
  }

  const visibleCitations = citations.slice(0, MAX_VISIBLE_CITATIONS);
  const hiddenCount = Math.max(0, citations.length - visibleCitations.length);
  const hasCitations = citations.length > 0;
  const retrievalFailed = message.status === "failed";

  return (
    <section className={`message-citations${hasCitations ? "" : " empty"}`} aria-label="回答引用说明">
      <div className="message-citations-head">
        <strong>为什么这样回答</strong>
        <small>{hasCitations ? `${citations.length} 条引用` : "没有可展示引用"}</small>
      </div>
      {hasCitations ? (
        <>
          <ol className="message-citation-list">
            {visibleCitations.map((citation, index) => {
              const sourceScope = formatCitationSourceScope(citation.source_scope);
              const retrievalMode = formatCitationRetrievalMode(citation.retrieval_mode);
              return (
                <li key={citationKey(message.id, citation, index)} className="message-citation-item">
                <div className="message-citation-path">
                  <strong>引用文件</strong>
                  <code>{citation.relative_path}</code>
                </div>
                <div className="message-citation-meta">
                  {sourceScope ? <span>来源：{sourceScope}</span> : null}
                  {retrievalMode ? <span>检索方式：{retrievalMode}</span> : null}
                  {citation.heading ? <span>标题：{citation.heading}</span> : null}
                </div>
                <p>{formatCitationSnippet(citation.snippet)}</p>
                </li>
              );
            })}
          </ol>
          {hiddenCount > 0 ? <small className="message-citation-more">还有 {hiddenCount} 条引用未展开。</small> : null}
        </>
      ) : (
        <p className="message-citation-empty">
          {retrievalFailed
            ? "这轮检索或回答没有完成，因此没有可追溯的引用。"
            : "这轮检索没有返回可展示引用，回答里没有附带本地来源。"}
        </p>
      )}
      {!hasCitations || retrievalFailed ? (
        <p className="message-citation-hint">可以检查是否已绑定 Vault、重建索引，或换用更具体的关键词后再问。</p>
      ) : null}
    </section>
  );
}

function citationKey(messageId: string, citation: Citation, index: number): string {
  return `${messageId}-${citation.relative_path}-${citation.chunk_id || citation.note_id || citation.heading || index}`;
}

function formatCitationSnippet(snippet: Citation["snippet"]): string {
  const normalized = snippet?.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "这条引用没有可展示片段，仅展示来源路径。";
  }
  const chars = Array.from(normalized);
  if (chars.length <= MAX_SNIPPET_CHARS) {
    return normalized;
  }
  return `${chars.slice(0, MAX_SNIPPET_CHARS).join("")}...`;
}
