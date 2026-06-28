import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { readRendererUiState, writeRendererUiState } from "../../services/rendererUiState";
import type { DesktopWindowMode } from "../desktop/desktopWindowModes";
import {
  FirstUseOnboardingCard,
  buildFirstUseOnboardingMessage,
} from "./FirstUseOnboardingCard";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type FirstUseOnboardingStatus = "unknown" | "pending" | "completed";

type SendFirstUseOnboardingMessage = (
  message: string,
  options: { displayText?: string },
) => Promise<boolean>;

type UseFirstUseOnboardingOptions = {
  connected: boolean;
  streaming: boolean;
  windowMode: DesktopWindowMode;
  onNotice: (notice: Notice | null) => void;
  onSendMessage: SendFirstUseOnboardingMessage;
};

export const firstUseOnboardingStorageKey = "agent-pet.first-use-onboarding";
const firstUseOnboardingCompletedValue = "completed:v1";

export function useFirstUseOnboarding({
  connected,
  streaming,
  windowMode,
  onNotice,
  onSendMessage,
}: UseFirstUseOnboardingOptions): ReactNode {
  const [status, setStatus] = useState<FirstUseOnboardingStatus>("unknown");
  const [draft, setDraft] = useState({
    currentFocus: "",
    preferredName: "",
    longTermContext: "",
    savePreference: "",
  });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const saved = readRendererUiState(firstUseOnboardingStorageKey);
    setStatus(saved === firstUseOnboardingCompletedValue ? "completed" : "pending");
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting || streaming || !connected) {
      return;
    }
    const message = buildFirstUseOnboardingMessage(draft);
    if (!message) {
      onNotice({ tone: "error", message: "请先告诉我今天想从哪里陪你继续。" });
      return;
    }
    setSubmitting(true);
    const completed = await onSendMessage(message, { displayText: draft.currentFocus });
    setSubmitting(false);
    if (!completed) {
      return;
    }
    await writeRendererUiState(firstUseOnboardingStorageKey, firstUseOnboardingCompletedValue);
    setStatus("completed");
    onNotice({
      tone: "success",
      message: "已经开始陪你接上这件事；之后可以在记忆里查看和撤回我记下的内容。",
    });
  }

  function skip() {
    void writeRendererUiState(firstUseOnboardingStorageKey, firstUseOnboardingCompletedValue);
    setStatus("completed");
    onNotice({ tone: "info", message: "已跳过首次引导，可以直接开始聊天。" });
  }

  const show = status === "pending" && (windowMode === "control" || windowMode === "chat");
  return show ? (
    <FirstUseOnboardingCard
      currentFocus={draft.currentFocus}
      preferredName={draft.preferredName}
      longTermContext={draft.longTermContext}
      savePreference={draft.savePreference}
      connected={connected}
      streaming={streaming}
      submitting={submitting}
      onCurrentFocusChange={(value) => setDraft((current) => ({ ...current, currentFocus: value }))}
      onPreferredNameChange={(value) => setDraft((current) => ({ ...current, preferredName: value }))}
      onLongTermContextChange={(value) => setDraft((current) => ({ ...current, longTermContext: value }))}
      onSavePreferenceChange={(value) => setDraft((current) => ({ ...current, savePreference: value }))}
      onSubmit={submit}
      onSkip={skip}
    />
  ) : null;
}
