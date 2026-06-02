import { BookOpen, CalendarCheck, ListPlus, MessageCircle, NotebookPen, Send, Square, X } from "lucide-react";
import type { FormEvent, RefObject } from "react";
import type { PetBubbleState } from "./chatTypes";
import type { PetInputMode, PetInputModeOption } from "./petInputModes";

type PetChatOverlayProps = {
  bubble: PetBubbleState;
  input: string;
  inputVisible: boolean;
  inputRef: RefObject<HTMLInputElement>;
  mode: PetInputMode;
  modes: PetInputModeOption[];
  connected: boolean;
  streaming: boolean;
  onAdvancePage: () => void;
  onPausePaging: () => void;
  onResumePaging: () => void;
  onInputChange: (value: string) => void;
  onModeChange: (mode: PetInputMode) => void;
  onInputClose: () => void;
  onSubmit: (event: FormEvent) => void;
  onStopStreaming: () => void;
};

function renderPetInputModeIcon(mode: PetInputMode) {
  const iconProps = { size: 12, strokeWidth: 2.4, "aria-hidden": true };
  switch (mode) {
    case "chat":
      return <MessageCircle {...iconProps} />;
    case "note":
      return <NotebookPen {...iconProps} />;
    case "task":
      return <ListPlus {...iconProps} />;
    case "wiki":
      return <BookOpen {...iconProps} />;
    case "review":
      return <CalendarCheck {...iconProps} />;
  }
}

export function PetChatOverlay({
  bubble,
  input,
  inputVisible,
  inputRef,
  mode,
  modes,
  connected,
  streaming,
  onAdvancePage,
  onPausePaging,
  onResumePaging,
  onInputChange,
  onModeChange,
  onInputClose,
  onSubmit,
  onStopStreaming,
}: PetChatOverlayProps) {
  const activeMode = modes.find((option) => option.id === mode) ?? modes[0];

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
          <div className="pet-input-mode-switch" role="tablist" aria-label="桌宠输入模式">
            {modes.map((option) => (
              <button
                key={option.id}
                type="button"
                className={option.id === mode ? "is-active" : ""}
                role="tab"
                aria-selected={option.id === mode}
                aria-label={option.ariaLabel}
                title={option.label}
                onClick={() => onModeChange(option.id)}
              >
                {renderPetInputModeIcon(option.id)}
              </button>
            ))}
          </div>
          <div className="pet-input-row">
            <input
              ref={inputRef}
              value={input}
              onChange={(event) => onInputChange(event.target.value)}
              placeholder={connected ? activeMode.placeholder : "正在等待本地助手连接..."}
              disabled={!connected}
            />
            {streaming ? (
              <button type="button" className="danger" aria-label="停止回复" onClick={onStopStreaming}>
                <Square size={12} fill="currentColor" aria-hidden="true" />
              </button>
            ) : (
              <button
                type="submit"
                aria-label={mode === "review" && !input.trim() ? "发送今日复盘请求" : "发送消息"}
                disabled={(mode !== "review" && !input.trim()) || !connected}
              >
                <Send size={13} aria-hidden="true" />
              </button>
            )}
            <button type="button" aria-label="关闭输入框" onClick={onInputClose}>
              <X size={13} aria-hidden="true" />
            </button>
          </div>
        </form>
      ) : null}
    </>
  );
}
