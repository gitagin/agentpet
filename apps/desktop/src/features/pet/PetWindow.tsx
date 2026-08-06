import { AlarmClockPlus, BookOpen, MessageSquareText, Settings, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { AnimationEventHandler, CSSProperties, FormEvent, PointerEvent, PointerEventHandler, RefObject } from "react";
import { PetChatOverlay } from "../chat/PetChatOverlay";
import type { PetChatBubbleController } from "../chat/usePetChatBubble";
import type { PetInputMode, PetInputModeOption } from "../chat/petInputModes";
import { SpritePetStage } from "./SpritePetStage";
import type { PetStageView } from "./petStageState";
import type { SpritePetDragDirection } from "./spritePetState";

type PetShortcutMotion = "idle" | "opening" | "closing";

// AGENT_PET_DEBUG_HITBOX=1 的对齐核验角标：实时显示当前显示器缩放
// （devicePixelRatio）与视口尺寸，跨屏拖动或改缩放时自动刷新，
// 供 100%/125%/150%/200% 四档命中框对齐人工验收用。
function useDevicePixelRatio(enabled: boolean): number {
  const [devicePixelRatio, setDevicePixelRatio] = useState(() => window.devicePixelRatio);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const media = window.matchMedia(`(resolution: ${devicePixelRatio}dppx)`);
    const update = () => setDevicePixelRatio(window.devicePixelRatio);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [enabled, devicePixelRatio]);

  return devicePixelRatio;
}

export type PetWindowProps = {
  shell: {
    ref: RefObject<HTMLElement>;
    hitboxStyle: CSSProperties;
    hitboxDebug: boolean;
  };
  stage: {
    dragging: boolean;
    dragDirection: SpritePetDragDirection;
    view: PetStageView;
    canvasRef: RefObject<HTMLCanvasElement>;
    ttsSpeaking: boolean;
    actionKeyOverride: string | null;
    actionTriggerKey: string | null;
    onBeginDrag: PointerEventHandler<HTMLElement>;
    onMoveDrag: PointerEventHandler<HTMLElement>;
    onEndDrag: (event?: PointerEvent<HTMLElement>) => void;
  };
  chat: {
    controller: PetChatBubbleController;
    inputMode: PetInputMode;
    inputModes: PetInputModeOption[];
    connected: boolean;
    streaming: boolean;
    onOpenInputMode: (mode: PetInputMode) => void;
    onSendMessage: (event: FormEvent) => void;
    onStopStreaming: () => void;
  };
  shortcuts: {
    buttonStyles: CSSProperties[];
    visible: boolean;
    motion: PetShortcutMotion;
    onToggle: () => void;
    onCompleteEntryHint: () => void;
    onOpenStage: () => void;
    onOpenShortcutStage: (mode: "memory" | "settings") => void;
    onQuitApp: () => void;
    onFinishMotion: AnimationEventHandler<HTMLElement>;
  };
};

export function PetWindow({
  shell,
  stage,
  chat,
  shortcuts,
}: PetWindowProps) {
  const { ref: shellRef, hitboxStyle, hitboxDebug } = shell;
  const {
    dragging: petDragging,
    dragDirection: petDragDirection,
    view: petStage,
    canvasRef: petCanvasRef,
    ttsSpeaking,
    actionKeyOverride,
    actionTriggerKey,
    onBeginDrag: onBeginPetDrag,
    onMoveDrag: onMovePetDrag,
    onEndDrag: onEndPetDrag,
  } = stage;
  const {
    controller: petChat,
    inputMode: petInputMode,
    inputModes: petInputModes,
    connected,
    streaming,
    onOpenInputMode: onOpenPetInputMode,
    onSendMessage: onSendPetMessage,
    onStopStreaming,
  } = chat;
  const {
    buttonStyles: shortcutButtonStyles,
    visible: petShortcutsVisible,
    motion: petShortcutMotion,
    onToggle: onTogglePetShortcuts,
    onCompleteEntryHint: onCompletePetEntryHint,
    onOpenStage,
    onOpenShortcutStage: onOpenPetShortcutStage,
    onQuitApp,
    onFinishMotion: onFinishPetShortcutMotion,
  } = shortcuts;
  const petShortcutsInteractive = petShortcutsVisible && petShortcutMotion !== "closing";
  const petShortcutsRendered = petShortcutsVisible || petShortcutMotion === "closing";
  const debugDevicePixelRatio = useDevicePixelRatio(hitboxDebug);

  return (
    <main
      className={[
        "pet-shell",
        hitboxDebug ? "pet-debug-hitbox" : "",
        petChat.bubble.visible ? "pet-bubble-visible" : "",
        petDragging ? "pet-dragging" : "",
      ].filter(Boolean).join(" ")}
      ref={shellRef}
      style={hitboxStyle}
      aria-label="Agent Pet 桌宠"
      onDragStart={(event) => event.preventDefault()}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => event.preventDefault()}
    >
      {hitboxDebug ? (
        <div
          style={{
            position: "absolute",
            top: 4,
            left: 4,
            zIndex: 40,
            padding: "2px 6px",
            borderRadius: 4,
            background: "rgba(0, 0, 0, 0.72)",
            color: "#9dff9d",
            font: "10px/1.5 monospace",
            pointerEvents: "none",
            whiteSpace: "pre",
          }}
        >
          {`dpr ${debugDevicePixelRatio}\n${window.innerWidth}x${window.innerHeight} css-px`}
        </div>
      ) : null}
      <SpritePetStage
        stage={petStage}
        canvasRef={petCanvasRef}
        connected={connected}
        streaming={streaming}
        speaking={ttsSpeaking}
        inputVisible={petChat.inputVisible}
        shortcutVisible={petShortcutsVisible}
        dragging={petDragging}
        dragDirection={petDragDirection}
        actionKeyOverride={actionKeyOverride}
        actionTriggerKey={actionTriggerKey}
        petInteractions={{
          onPointerDown: onBeginPetDrag,
          onPointerMove: onMovePetDrag,
          onPointerUp: onEndPetDrag,
          onPointerCancel: onEndPetDrag,
          onLostPointerCapture: onEndPetDrag,
          onContextMenu: (event) => {
            event.preventDefault();
            onEndPetDrag();
            onTogglePetShortcuts();
          },
          onBubbleContextMenu: (event) => {
            event.preventDefault();
            onEndPetDrag();
          },
          onDoubleClick: () => {
            onCompletePetEntryHint();
            onEndPetDrag();
            onOpenStage();
          },
        }}
      />
      <PetChatOverlay
        bubble={petChat.bubble}
        input={petChat.input}
        inputVisible={petChat.inputVisible}
        inputRef={petChat.inputRef}
        mode={petInputMode}
        modes={petInputModes}
        connected={connected}
        streaming={streaming}
        onPreviousPage={petChat.retreatPageManually}
        onAdvancePage={petChat.advancePageManually}
        onPausePaging={petChat.pausePaging}
        onResumePaging={petChat.resumePaging}
        onInputChange={petChat.setInput}
        onModeChange={onOpenPetInputMode}
        onInputClose={() => petChat.setInputVisible(false)}
        onSubmit={onSendPetMessage}
        onStopStreaming={onStopStreaming}
      />
      <nav
        className={`pet-shortcut-bar${petShortcutsRendered ? " is-visible" : ""}`}
        data-shortcut-motion={petShortcutMotion}
        aria-label="桌宠快捷操作"
        aria-hidden={!petShortcutsInteractive}
        onContextMenu={(event) => event.preventDefault()}
        onAnimationEnd={onFinishPetShortcutMotion}
      >
        <button type="button" className="pet-shortcut-button primary" style={shortcutButtonStyles[0]} tabIndex={petShortcutsInteractive ? 0 : -1} aria-label="继续聊" title="继续聊" onClick={() => onOpenPetInputMode("chat")}>
          <MessageSquareText className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
        </button>
        <button type="button" className="pet-shortcut-button primary" style={shortcutButtonStyles[1]} tabIndex={petShortcutsInteractive ? 0 : -1} aria-label="建提醒" title="建提醒" onClick={() => onOpenPetInputMode("task")}>
          <AlarmClockPlus className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
        </button>
        <button type="button" className="pet-shortcut-button" style={shortcutButtonStyles[2]} tabIndex={petShortcutsInteractive ? 0 : -1} aria-label="打开记忆" title="打开记忆" onClick={() => onOpenPetShortcutStage("memory")}>
          <BookOpen className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
        </button>
        <button type="button" className="pet-shortcut-button" style={shortcutButtonStyles[3]} tabIndex={petShortcutsInteractive ? 0 : -1} aria-label="打开设置" title="打开设置" onClick={() => onOpenPetShortcutStage("settings")}>
          <Settings className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
        </button>
        <button type="button" className="pet-shortcut-button danger pet-shortcut-danger" style={shortcutButtonStyles[4]} data-shortcut-final="true" tabIndex={petShortcutsInteractive ? 0 : -1} aria-label="退出 Agent Pet" title="退出 Agent Pet" onClick={onQuitApp}>
          <X className="pet-shortcut-icon" size={17} strokeWidth={2.5} aria-hidden="true" />
        </button>
      </nav>
    </main>
  );
}
