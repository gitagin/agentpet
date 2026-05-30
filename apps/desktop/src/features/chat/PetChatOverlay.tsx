import type { FormEvent, RefObject } from "react";
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
          onSubmit={onSubmit}
          onPointerDown={(event) => event.stopPropagation()}
          onPointerMove={(event) => event.stopPropagation()}
          onPointerUp={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
        >
          <input
            ref={inputRef}
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            placeholder={connected ? "和桌宠说点什么..." : "正在等待本地助手连接..."}
            disabled={!connected}
          />
          {streaming ? (
            <button type="button" className="danger" aria-label="停止回复" onClick={onStopStreaming}>
              停
            </button>
          ) : (
            <button type="submit" aria-label="发送消息" disabled={!input.trim() || !connected}>
              发
            </button>
          )}
          <button type="button" aria-label="关闭输入框" onClick={onInputClose}>
            ×
          </button>
        </form>
      ) : null}
    </>
  );
}
