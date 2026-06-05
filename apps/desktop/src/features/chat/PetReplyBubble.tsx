import type { PetBubbleState } from "./chatTypes";

type PetReplyBubbleProps = {
  bubble: PetBubbleState;
  className?: string;
  onPreviousPage: () => void;
  onAdvancePage: () => void;
  onPausePaging: () => void;
  onResumePaging: () => void;
};

export function PetReplyBubble({
  bubble,
  className = "",
  onAdvancePage,
  onPausePaging,
  onResumePaging,
}: PetReplyBubbleProps) {
  if (!bubble.visible) {
    return null;
  }

  const hasBubbleTitle = Boolean(bubble.title.trim());
  const bubbleClass = [
    "pet-agent-bubble",
    className,
    bubble.tone,
    hasBubbleTitle ? "has-header" : "no-header",
    hasBubbleTitle ? "has-title" : "no-title",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={bubbleClass}
      role="status"
      aria-live="polite"
      onPointerDown={(event) => event.stopPropagation()}
      onPointerMove={(event) => event.stopPropagation()}
      onPointerUp={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onAdvancePage();
      }}
      onDoubleClick={(event) => event.stopPropagation()}
    >
      {hasBubbleTitle ? (
        <div className="pet-agent-bubble-header">
          <strong>{bubble.title}</strong>
        </div>
      ) : null}
      <div
        className="pet-agent-bubble-text"
        tabIndex={bubble.tone === "reply" ? 0 : undefined}
        onFocus={onPausePaging}
        onBlur={onResumePaging}
        onWheel={onPausePaging}
      >
        {bubble.message}
      </div>
    </div>
  );
}
