import type { FormEvent, RefObject } from "react";
import { Send, X } from "lucide-react";
import type { PetBubbleState } from "./chatTypes";

type PetChatOverlayProps = {
  bubble: PetBubbleState;
  input: string;
  inputVisible: boolean;
  inputRef: RefObject<HTMLInputElement>;
  connected: boolean;
  streaming: boolean;
  onAdvancePage: () => void;
  onPausePaging: () => void;
  onResumePaging: () => void;
  onInputChange: (value: string) => void;
  onInputClose: () => void;
  onSubmit: (event: FormEvent) => void;
  onStopStreaming: () => void;
};

export function PetChatOverlay({
  bubble,
  input,
  inputVisible,
  inputRef,
  connected,
  streaming,
  onAdvancePage,
  onPausePaging,
  onResumePaging,
  onInputChange,
  onInputClose,
  onSubmit,
  onStopStreaming,
}: PetChatOverlayProps) {
  return (
    <>
      {bubble.visible ? (
        <div
          className={`pet-agent-bubble ${bubble.tone}`}
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
          <strong>
            {bubble.title}
            {bubble.continueHint ? <span className="pet-agent-bubble-page">{bubble.continueHint}</span> : null}
          </strong>
          <div
            className="pet-agent-bubble-text"
            tabIndex={bubble.tone === "reply" ? 0 : undefined}
            onPointerEnter={onPausePaging}
            onPointerLeave={onResumePaging}
            onFocus={onPausePaging}
            onBlur={onResumePaging}
            onWheel={onPausePaging}
          >
            {bubble.message}
          </div>
        </div>
      ) : null}
      {inputVisible ? (
        <form
          className="pet-input-dock"
          aria-label="桌宠输入框"
          onSubmit={onSubmit}
          onPointerDown={(event) => event.stopPropagation()}
          onPointerMove={(event) => event.stopPropagation()}
          onPointerUp={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
        >
          <input
            ref={inputRef}
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder={connected ? "和桌宠聊天..." : "等待本地后端连接..."}
            disabled={streaming}
            onKeyDown={(event) => {
              if (event.key === "Escape" && !streaming) {
                onInputClose();
              }
            }}
          />
          {streaming ? (
            <button type="button" className="danger" onClick={onStopStreaming} title="停止生成">
              <X size={14} />
            </button>
          ) : (
            <button type="submit" title="发送给桌宠" disabled={!input.trim()}>
              <Send size={14} />
            </button>
          )}
        </form>
      ) : null}
    </>
  );
}
