import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import type { AnimationEvent, PointerEvent } from "react";
import type { PetChatBubbleController } from "../chat/usePetChatBubble";
import { normalizePetInputMode, type PetInputMode } from "../chat/petInputModes";
import type { DesktopStageRouteMode, DesktopWindowMode } from "../desktop/desktopWindowModes";
import { readRendererUiState, writeRendererUiState } from "../../services/rendererUiState";
import type { SpritePetDragDirection } from "./spritePetState";

type PetShortcutMotion = "idle" | "opening" | "closing";
type PetEntryHintStatus = "unknown" | "pending" | "completed";

type PetDragState = {
  pointerId: number;
  startX: number;
  startY: number;
  dragging: boolean;
  target: HTMLElement | null;
};

type UsePetWindowControllerOptions = {
  windowMode: DesktopWindowMode;
  petChat: PetChatBubbleController;
  onPetInputModeChange: (mode: PetInputMode) => void;
};

export const petEntryHintStorageKey = "agent-pet.pet-entry-hint";
const petEntryHintCompletedValue = "completed:v1";

export function usePetWindowController({
  windowMode,
  petChat,
  onPetInputModeChange,
}: UsePetWindowControllerOptions) {
  const [petShortcutsVisible, setPetShortcutsVisible] = useState(false);
  const [petShortcutMotion, setPetShortcutMotion] = useState<PetShortcutMotion>("idle");
  const [petDragging, setPetDragging] = useState(false);
  const [petDragDirection, setPetDragDirection] = useState<SpritePetDragDirection>("none");
  const [petEntryHintStatus, setPetEntryHintStatus] = useState<PetEntryHintStatus>("unknown");
  const petShellRef = useRef<HTMLElement | null>(null);
  const petShortcutMotionTimerRef = useRef<number | null>(null);
  const petDragRef = useRef<PetDragState | null>(null);
  const openPetInputModeRef = useRef<(mode: PetInputMode) => void>(() => undefined);

  function clearPetShortcutMotionTimer() {
    if (petShortcutMotionTimerRef.current !== null) {
      window.clearTimeout(petShortcutMotionTimerRef.current);
      petShortcutMotionTimerRef.current = null;
    }
  }

  function settlePetShortcutMotion() {
    clearPetShortcutMotionTimer();
    setPetShortcutMotion("idle");
  }

  function setPetShortcutMotionWithFallback(nextMotion: PetShortcutMotion) {
    clearPetShortcutMotionTimer();
    setPetShortcutMotion(nextMotion);
    if (nextMotion === "idle") {
      return;
    }
    petShortcutMotionTimerRef.current = window.setTimeout(() => {
      petShortcutMotionTimerRef.current = null;
      if (nextMotion === "closing") {
        setPetShortcutsVisible(false);
      }
      setPetShortcutMotion("idle");
    }, nextMotion === "opening" ? 360 : 340);
  }

  function finishPetDragVisualState() {
    setPetDragging(false);
    setPetDragDirection("none");
  }

  function completePetEntryHint() {
    if (petEntryHintStatus === "completed") {
      return;
    }
    void writeRendererUiState(petEntryHintStorageKey, petEntryHintCompletedValue);
    setPetEntryHintStatus("completed");
  }

  function beginPetDrag(event: PointerEvent<HTMLElement>) {
    if (windowMode !== "pet" || event.button !== 0) {
      return;
    }
    if (!window.agentDesktop?.beginPetWindowDrag || !window.agentDesktop.activatePetWindowDrag) {
      return;
    }
    event.preventDefault();
    petDragRef.current = {
      pointerId: event.pointerId,
      startX: event.screenX,
      startY: event.screenY,
      dragging: false,
      target: event.currentTarget,
    };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      petDragRef.current = null;
      finishPetDragVisualState();
      window.agentDesktop?.endPetWindowDrag?.();
      return;
    }
    flushSync(() => {
      setPetDragging(true);
    });
    window.agentDesktop.beginPetWindowDrag();
  }

  function movePetDrag(event: PointerEvent<HTMLElement>) {
    const dragState = petDragRef.current;
    if (windowMode !== "pet" || !dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    const movedX = event.screenX - dragState.startX;
    const movedY = event.screenY - dragState.startY;
    if (Math.abs(movedX) >= 2) {
      setPetDragDirection(movedX < 0 ? "left" : "right");
    }
    if (!dragState.dragging && Math.hypot(movedX, movedY) < 6) {
      return;
    }

    if (!dragState.dragging) {
      dragState.dragging = true;
      window.agentDesktop?.activatePetWindowDrag?.();
    }
  }

  function endPetDrag(event?: PointerEvent<HTMLElement>) {
    try {
      if (event && petDragRef.current?.pointerId === event.pointerId && event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      window.agentDesktop?.endPetWindowDrag?.();
    } catch {
      // 即使释放 pointer capture 或 IPC 失败，也不能让拖动状态残留。
    } finally {
      petDragRef.current = null;
      finishPetDragVisualState();
    }
  }

  function openPetInputMode(mode: PetInputMode) {
    completePetEntryHint();
    onPetInputModeChange(mode);
    setPetShortcutsVisible(false);
    settlePetShortcutMotion();
    petChat.showInput();
  }
  openPetInputModeRef.current = openPetInputMode;

  function closePetShortcutMenu() {
    completePetEntryHint();
    setPetShortcutsVisible(false);
    settlePetShortcutMotion();
    petChat.setInputVisible(false);
  }

  function quitAppFromShortcut() {
    closePetShortcutMenu();
    const quitApp = window.agentDesktop?.quitApp?.();
    if (quitApp) {
      void quitApp.catch(() => undefined);
    }
  }

  function openPetShortcutStage(mode: DesktopStageRouteMode) {
    closePetShortcutMenu();
    const openStage = window.agentDesktop?.openStage?.(mode);
    if (openStage) {
      void openStage.catch(() => undefined);
    }
  }

  function togglePetShortcuts() {
    completePetEntryHint();
    setPetShortcutsVisible((visible) => {
      if (!visible) {
        petChat.setInputVisible(false);
        setPetShortcutMotionWithFallback("opening");
        return true;
      }
      setPetShortcutMotionWithFallback("closing");
      return true;
    });
  }

  function finishPetShortcutMotion(event: AnimationEvent<HTMLElement>) {
    if ((event.target as HTMLElement | null)?.dataset?.shortcutFinal !== "true") {
      return;
    }
    if (
      event.animationName === "pet-shortcut-roll-out" ||
      event.animationName === "pet-shortcut-roll-in" ||
      event.animationName === "pet-shortcut-slide-out" ||
      event.animationName === "pet-shortcut-slide-in"
    ) {
      if (petShortcutMotion === "closing") {
        setPetShortcutsVisible(false);
      }
      settlePetShortcutMotion();
    }
  }

  useEffect(() => () => clearPetShortcutMotionTimer(), []);

  useEffect(() => {
    const saved = readRendererUiState(petEntryHintStorageKey);
    setPetEntryHintStatus(saved === petEntryHintCompletedValue ? "completed" : "pending");
  }, []);

  useEffect(() => {
    if (
      windowMode !== "pet" ||
      petEntryHintStatus !== "pending" ||
      petShortcutsVisible ||
      petChat.inputVisible ||
      petChat.bubble.visible
    ) {
      return;
    }
    void writeRendererUiState(petEntryHintStorageKey, petEntryHintCompletedValue);
  }, [petChat.bubble.visible, petChat.inputVisible, petEntryHintStatus, petShortcutsVisible, windowMode]);

  useEffect(() => {
    const visible = windowMode === "pet" && petShortcutsVisible;
    window.agentDesktop?.setPetShortcutBarVisible?.(visible);
    return () => {
      window.agentDesktop?.setPetShortcutBarVisible?.(false);
    };
  }, [petShortcutsVisible, windowMode]);

  useEffect(() => {
    const visible = windowMode === "pet" && petChat.inputVisible;
    window.agentDesktop?.setPetInputVisible?.(visible);
    return () => {
      window.agentDesktop?.setPetInputVisible?.(false);
    };
  }, [petChat.inputVisible, windowMode]);

  useEffect(() => {
    if (windowMode !== "pet") {
      return;
    }
    const unsubscribe = window.agentDesktop?.onPetInputModeRequested?.((requestedMode) => {
      const normalizedMode = normalizePetInputMode(requestedMode);
      if (!normalizedMode) {
        return;
      }
      openPetInputModeRef.current(normalizedMode);
    });
    return unsubscribe;
  }, [windowMode]);

  useEffect(() => {
    const cancelPetDrag = () => {
      const dragState = petDragRef.current;
      try {
        window.agentDesktop?.endPetWindowDrag?.();
        if (dragState?.target?.hasPointerCapture(dragState.pointerId)) {
          dragState.target.releasePointerCapture(dragState.pointerId);
        }
      } catch {
        // 透明桌宠窗口在失焦或系统拖动中可能丢失 pointer capture；本地状态必须照常清理。
      } finally {
        petDragRef.current = null;
        finishPetDragVisualState();
      }
    };
    const unsubscribe = window.agentDesktop?.onPetDragCancelled?.(cancelPetDrag);
    window.addEventListener("blur", cancelPetDrag);
    window.addEventListener("pointercancel", cancelPetDrag);
    window.addEventListener("pointerup", cancelPetDrag);
    return () => {
      unsubscribe?.();
      window.removeEventListener("blur", cancelPetDrag);
      window.removeEventListener("pointercancel", cancelPetDrag);
      window.removeEventListener("pointerup", cancelPetDrag);
    };
  }, []);

  return {
    shellRef: petShellRef,
    petShortcutsVisible,
    petShortcutMotion,
    petDragging,
    petDragDirection,
    showPetEntryHint:
      windowMode === "pet" &&
      petEntryHintStatus === "pending" &&
      !petShortcutsVisible &&
      !petChat.inputVisible &&
      !petChat.bubble.visible,
    completePetEntryHint,
    beginPetDrag,
    movePetDrag,
    endPetDrag,
    togglePetShortcuts,
    openPetInputMode,
    openPetShortcutStage,
    quitAppFromShortcut,
    finishPetShortcutMotion,
  };
}
