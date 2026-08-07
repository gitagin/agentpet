import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function AssistantMessageContent({ content }: { content: string }) {
  return (
    <div className="message-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        disallowedElements={["img"]}
        unwrapDisallowed
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
