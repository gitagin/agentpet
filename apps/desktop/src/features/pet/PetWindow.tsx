import { AlarmClockPlus, BookOpen, MessageSquareText, NotebookPen, Settings, VolumeX } from "lucide-react";
import type { AnimationEventHandler, CSSProperties, FormEvent, PointerEvent, PointerEventHandler, RefObject } from "react";
import type { Live2DStageView } from "../../components/Live2DStage";
import { Live2DStage } from "../../components/Live2DStage";
import type { Live2DAssetInfo, Live2DRuntimeBoundary } from "../../services/live2dRuntime";
import { PetChatOverlay } from "../chat/PetChatOverlay";
import type { PetChatBubbleController } from "../chat/usePetChatBubble";
import type { PetInputMode, PetInputModeOption } from "../chat/petInputModes";

type PetShortcutMotion = "idle" | "opening" | "closing";

type PetDragSnapshot = {
  url: string;
  style: CSSProperties;
} | null;

export type PetWindowProps = {
  shellRef: RefObject<HTMLElement>;
  hitboxStyle: CSSProperties;
  shortcutButtonStyles: CSSProperties[];
  hitboxDebug: boolean;
  petChat: PetChatBubbleController;
  petDragging: boolean;
  petDragSnapshot: PetDragSnapshot;
  showPetEntryHint: boolean;
  live2dStage: Live2DStageView;
  live2dAsset: Live2DAssetInfo;
  live2dRuntime: Live2DRuntimeBoundary;
  live2dCanvasRef: RefObject<HTMLCanvasElement>;
  ttsSpeaking: boolean;
  ttsActive: boolean;
  live2dActionKeyOverride: string | null;
  live2dActionTriggerKey: string | null;
  petInputMode: PetInputMode;
  petInputModes: PetInputModeOption[];
  connected: boolean;
  streaming: boolean;
  petShortcutsVisible: boolean;
  petShortcutMotion: PetShortcutMotion;
  onBeginPetDrag: PointerEventHandler<HTMLElement>;
  onMovePetDrag: PointerEventHandler<HTMLElement>;
  onEndPetDrag: (event?: PointerEvent<HTMLElement>) => void;
  onTogglePetShortcuts: () => void;
  onCompletePetEntryHint: () => void;
  onOpenStage: () => void;
  onOpenPetInputMode: (mode: PetInputMode) => void;
  onOpenPetShortcutStage: (mode: "memory" | "settings") => void;
  onSendPetMessage: (event: FormEvent) => void;
  onStopStreaming: () => void;
  onStopTtsFromPetShortcut: () => void;
  onFinishPetShortcutMotion: AnimationEventHandler<HTMLElement>;
};

export function PetWindow({
  shellRef,
  hitboxStyle,
  shortcutButtonStyles,
  hitboxDebug,
  petChat,
  petDragging,
  petDragSnapshot,
  showPetEntryHint,
  live2dStage,
  live2dAsset,
  live2dRuntime,
  live2dCanvasRef,
  ttsSpeaking,
  ttsActive,
  live2dActionKeyOverride,
  live2dActionTriggerKey,
  petInputMode,
  petInputModes,
  connected,
  streaming,
  petShortcutsVisible,
  petShortcutMotion,
  onBeginPetDrag,
  onMovePetDrag,
  onEndPetDrag,
  onTogglePetShortcuts,
  onCompletePetEntryHint,
  onOpenStage,
  onOpenPetInputMode,
  onOpenPetShortcutStage,
  onSendPetMessage,
  onStopStreaming,
  onStopTtsFromPetShortcut,
  onFinishPetShortcutMotion,
}: PetWindowProps) {
  return (
    <main
      className={[
        "pet-shell",
        hitboxDebug ? "pet-debug-hitbox" : "",
        petChat.bubble.visible ? "pet-bubble-visible" : "",
        petDragging ? "pet-dragging" : "",
        petDragSnapshot ? "pet-drag-snapshot-ready" : "",
      ].filter(Boolean).join(" ")}
      ref={shellRef}
      style={hitboxStyle}
      aria-label="桌面记忆助手桌宠"
      onDragStart={(event) => event.preventDefault()}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => event.preventDefault()}
    >
      <Live2DStage
        key={`pet-${live2dAsset.modelId}`}
        stage={live2dStage}
        asset={live2dAsset}
        runtime={live2dRuntime}
        canvasRef={live2dCanvasRef}
        variant="pet"
        speaking={ttsSpeaking}
        actionKeyOverride={live2dActionKeyOverride}
        actionTriggerKey={live2dActionTriggerKey}
        suppressCanvasLayoutWarning={petDragging && Boolean(petDragSnapshot)}
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
      {petDragSnapshot ? (
        <img
          className="pet-drag-frame-cache"
          src={petDragSnapshot.url}
          style={petDragSnapshot.style}
          alt=""
          aria-hidden="true"
          draggable={false}
        />
      ) : null}
      {showPetEntryHint ? (
        <div className="pet-entry-hint" aria-label="桌宠入口提示">
          右键我快速行动
        </div>
      ) : null}
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
        className={`pet-shortcut-bar${petShortcutsVisible ? " is-visible" : ""}`}
        data-shortcut-motion={petShortcutMotion}
        aria-label="桌宠快捷操作"
        aria-hidden={!petShortcutsVisible}
        onContextMenu={(event) => event.preventDefault()}
        onAnimationEnd={onFinishPetShortcutMotion}
      >
        <button type="button" className="pet-shortcut-button primary" style={shortcutButtonStyles[0]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="继续聊" title="继续聊" onClick={() => onOpenPetInputMode("chat")}>
          <MessageSquareText className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
        </button>
        <button type="button" className="pet-shortcut-button primary" style={shortcutButtonStyles[1]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="记一条" title="记一条" onClick={() => onOpenPetInputMode("note")}>
          <NotebookPen className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
        </button>
        <button type="button" className="pet-shortcut-button primary" style={shortcutButtonStyles[2]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="建提醒" title="建提醒" onClick={() => onOpenPetInputMode("task")}>
          <AlarmClockPlus className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
        </button>
        <button type="button" className="pet-shortcut-button" style={shortcutButtonStyles[3]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="打开记忆" title="打开记忆" onClick={() => onOpenPetShortcutStage("memory")}>
          <BookOpen className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
        </button>
        {ttsActive ? (
          <button type="button" className="pet-shortcut-button voice" style={shortcutButtonStyles[4]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="暂停朗读" title="暂停朗读" onClick={onStopTtsFromPetShortcut}>
            <VolumeX className="pet-shortcut-icon" size={17} strokeWidth={2.4} aria-hidden="true" />
          </button>
        ) : (
          <button type="button" className="pet-shortcut-button" style={shortcutButtonStyles[4]} tabIndex={petShortcutsVisible ? 0 : -1} aria-label="打开设置" title="打开设置" onClick={() => onOpenPetShortcutStage("settings")}>
            <Settings className="pet-shortcut-icon" size={17} strokeWidth={2.3} aria-hidden="true" />
          </button>
        )}
      </nav>
    </main>
  );
}
