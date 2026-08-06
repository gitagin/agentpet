import { petInputModes } from "../features/chat/petInputModes";
import { petHitboxStyle, petShortcutButtonStyles } from "../features/pet/petHitboxStyles";
import { PetWindow } from "../features/pet/PetWindow";
import { buildAppShellPresentation } from "./appShellPresentation";
import { useAppShellRuntime } from "./AppShellRuntimeContext";

export function PetRouteView() {
  const runtime = useAppShellRuntime();
  const presentation = buildAppShellPresentation(runtime);
  const hitboxDebug = new URLSearchParams(window.location.search).get("hitbox") === "1";

  return (
    <PetWindow
      shell={{
        ref: runtime.pet.window.shellRef,
        hitboxStyle: petHitboxStyle,
        hitboxDebug,
      }}
      stage={{
        dragging: runtime.pet.window.petDragging,
        dragDirection: runtime.pet.window.petDragDirection,
        view: presentation.petStage,
        canvasRef: runtime.app.petCanvasRef,
        ttsSpeaking: runtime.pet.tts.speaking,
        actionKeyOverride: presentation.petReplyActionKey,
        actionTriggerKey: presentation.petReplyActionTriggerKey,
        onBeginDrag: runtime.pet.window.beginPetDrag,
        onMoveDrag: runtime.pet.window.movePetDrag,
        onEndDrag: runtime.pet.window.endPetDrag,
      }}
      chat={{
        controller: runtime.pet.chat,
        inputMode: runtime.app.petInputMode,
        inputModes: petInputModes,
        connected: runtime.connection.hasConnection,
        streaming: runtime.app.streaming,
        onOpenInputMode: runtime.pet.window.openPetInputMode,
        onSendMessage: runtime.chat.sendPetMessage,
        onStopStreaming: runtime.chat.stopStreaming,
      }}
      shortcuts={{
        buttonStyles: petShortcutButtonStyles,
        visible: runtime.pet.window.petShortcutsVisible,
        motion: runtime.pet.window.petShortcutMotion,
        onToggle: runtime.pet.window.togglePetShortcuts,
        onCompleteEntryHint: runtime.pet.window.completePetEntryHint,
        onOpenStage: () => {
          const openStage = window.agentDesktop?.openStage?.();
          if (openStage) {
            void openStage.catch(() => undefined);
          }
        },
        onOpenShortcutStage: runtime.pet.window.openPetShortcutStage,
        onQuitApp: runtime.pet.window.quitAppFromShortcut,
        onFinishMotion: runtime.pet.window.finishPetShortcutMotion,
      }}
    />
  );
}
