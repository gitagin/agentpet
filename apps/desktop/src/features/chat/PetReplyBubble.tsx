import { ChevronLeft, ChevronRight, Square } from "lucide-react";
import type { PetBubbleState } from "./chatTypes";

type PetReplyBubbleProps = {
  bubble: PetBubbleState;
  className?: string;
  onPreviousPage: () => void;
  onAdvancePage: () => void;
  onPausePaging: () => void;
  onResumePaging: () => void;
  ttsActive?: boolean;
  onStopTts?: () => void;
};

export function PetReplyBubble({
  bubble,
  className = "",
  onPreviousPage,
  onAdvancePage,
  onPausePaging,
  onResumePaging,
  ttsActive = false,
  onStopTts,
}: PetReplyBubbleProps) {
  if (!bubble.visible) {
    return null;
  }

  const hasBubbleTitle = Boolean(bubble.title.trim());
  const hasBubblePagination = Boolean(bubble.continueHint);
  const hasTtsStop = ttsActive && bubble.tone === "reply";
  const hasBubbleControls = hasBubblePagination || hasTtsStop;
  const hasBubbleHeader = hasBubbleTitle || hasBubblePagination || hasTtsStop;
  const bubbleClass = [
    "pet-agent-bubble",
    className,
    bubble.tone,
    hasBubbleHeader ? "has-header" : "no-header",
    hasBubbleTitle ? "has-title" : "no-title",
    hasBubblePagination ? "has-pagination" : "",
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
      {hasBubbleHeader ? (
        <div className="pet-agent-bubble-header">
          {hasBubbleTitle ? <strong>{bubble.title}</strong> : null}
          {bubble.continueHint ? <span className="pet-agent-bubble-page">{bubble.continueHint}</span> : null}
          {hasBubbleControls ? (
            <div
              className="pet-agent-bubble-controls"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => event.stopPropagation()}
            >
              {hasTtsStop ? (
                <button
                  type="button"
                  className="pet-agent-bubble-page-button pet-agent-bubble-stop-button"
                  aria-label="停止朗读"
                  title="停止朗读"
                  onClick={(event) => {
                    event.stopPropagation();
                    onStopTts?.();
                  }}
                >
                  <Square size={11} fill="currentColor" aria-hidden="true" />
                </button>
              ) : null}
              {bubble.continueHint ? (
                <>
                  <button
                    type="button"
                    className="pet-agent-bubble-page-button"
                    aria-label="上一页回复"
                    title="上一页"
                    disabled={!bubble.canPageBackward}
                    onClick={(event) => {
                      event.stopPropagation();
                      onPreviousPage();
                    }}
                  >
                    <ChevronLeft size={12} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="pet-agent-bubble-page-button"
                    aria-label="下一页回复"
                    title="下一页"
                    disabled={!bubble.canPageForward}
                    onClick={(event) => {
                      event.stopPropagation();
                      onAdvancePage();
                    }}
                  >
                    <ChevronRight size={12} aria-hidden="true" />
                  </button>
                </>
              ) : null}
            </div>
          ) : null}
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
