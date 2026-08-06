import { useEffect, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { HalfbodyPetPortraitHandle } from "../features/halfbody/HalfbodyPetPortrait";
import { buildHalfbodyTtsTimelineFromText } from "../features/halfbody/halfbodyTtsTimeline";
import { usePetChatBubble } from "../features/chat/usePetChatBubble";
import type { PetInputMode } from "../features/chat/petInputModes";
import { usePetWindowController } from "../features/pet/usePetWindowController";
import { useTtsOrchestrator } from "../features/tts/useTtsOrchestrator";
import type { DesktopWindowMode } from "../features/desktop/desktopWindowModes";
import type { DesktopApi } from "../services/desktopApi";
import type { ChatContinuitySignal, ChatMessage, TtsSettingsResponse } from "../types";
import { readTtsPlaybackDurationMs } from "./appShellUtils";
import type { Notice } from "./types";

type UsePetDomainOptions = {
  api: DesktopApi;
  settings: TtsSettingsResponse | null | undefined;
  windowMode: DesktopWindowMode;
  messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  latestContinuitySignal: ChatContinuitySignal | null;
  streamAbortRef: MutableRefObject<AbortController | null>;
  halfbodyPortraitRef: MutableRefObject<HalfbodyPetPortraitHandle | null>;
  setPetInputMode: Dispatch<SetStateAction<PetInputMode>>;
  onNotice: (notice: Notice | null) => void;
};

export function usePetDomain({
  api,
  settings,
  windowMode,
  messages,
  setMessages,
  latestContinuitySignal,
  streamAbortRef,
  halfbodyPortraitRef,
  setPetInputMode,
  onNotice,
}: UsePetDomainOptions) {
  const tts = useTtsOrchestrator({ api, settings, windowMode, onNotice });
  const chat = usePetChatBubble({
    messages,
    latestContinuitySignal,
    setMessages,
    setNotice: onNotice,
    abortStream: () => streamAbortRef.current?.abort(),
    tts: {
      enabled: tts.enabled,
      queue: tts.queue,
      provider: tts.provider,
      voice: tts.voice,
      speed: tts.speed,
      volume: tts.volume,
      cacheEnabled: tts.cacheEnabled,
      playbackState: tts.queue.state,
    },
  });
  const windowController = usePetWindowController({
    windowMode,
    petChat: chat,
    onPetInputModeChange: setPetInputMode,
  });
  const bindPlaybackHandlers = tts.bindPetPlaybackHandlers;
  const stopWaitingCue = tts.waitingCue.stop;
  const handlePlaybackStart = chat.handleTtsPlaybackStart;
  const handlePlaybackEnd = chat.handleTtsPlaybackEnd;

  useEffect(() => {
    bindPlaybackHandlers({
      onStart: (item) => {
        stopWaitingCue("assistant_tts_started");
        handlePlaybackStart?.(item);
        halfbodyPortraitRef.current?.speak(null, buildHalfbodyTtsTimelineFromText(item.text, {
          targetDurationMs: readTtsPlaybackDurationMs(item),
        }));
      },
      onEnd: (item, status) => {
        handlePlaybackEnd?.(item, status);
        halfbodyPortraitRef.current?.speak(null);
      },
    });
    return () => bindPlaybackHandlers({});
  }, [bindPlaybackHandlers, halfbodyPortraitRef, handlePlaybackEnd, handlePlaybackStart, stopWaitingCue]);

  useEffect(() => {
    if (!tts.speaking) {
      halfbodyPortraitRef.current?.speak(null);
    }
  }, [halfbodyPortraitRef, tts.speaking]);

  return { tts, chat, window: windowController };
}

export type PetDomain = ReturnType<typeof usePetDomain>;
