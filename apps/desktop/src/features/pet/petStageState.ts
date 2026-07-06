import type { ChatContinuitySignal, ContinuityStateResponse } from "../../types";

export type PetStageState =
  | "disconnected"
  | "idle"
  | "presence"
  | "reflective"
  | "thinking"
  | "memory"
  | "confirming"
  | "tasking"
  | "diagnosed";

export type PetStageView = {
  state: PetStageState;
  label: string;
  mood: string;
  message: string;
  hint: string;
};

export function getPetStageView({
  connected,
  streaming,
  searchResultCount,
  pendingProposalCount,
  taskCount,
  diagnosticsReady,
  continuityState,
  continuitySignal,
}: {
  connected: boolean;
  streaming: boolean;
  searchResultCount: number;
  pendingProposalCount: number;
  taskCount: number;
  diagnosticsReady: boolean;
  continuityState: ContinuityStateResponse | null;
  continuitySignal: ChatContinuitySignal | null;
}): PetStageView {
  if (!connected) {
    return {
      state: "disconnected",
      label: "Offline",
      mood: "Waiting",
      message: "Local service is not connected.",
      hint: "Check the connection status.",
    };
  }
  if (streaming) {
    return {
      state: "thinking",
      label: "Thinking",
      mood: "Working",
      message: "Preparing the reply.",
      hint: "You can stop the reply at any time.",
    };
  }
  if (pendingProposalCount > 0) {
    return {
      state: "confirming",
      label: "Needs review",
      mood: "Waiting",
      message: `${pendingProposalCount} memory item(s) need confirmation.`,
      hint: "Open memories to review.",
    };
  }
  if (diagnosticsReady) {
    return {
      state: "diagnosed",
      label: "Diagnosed",
      mood: "Updated",
      message: "Diagnostics are ready.",
      hint: "Open diagnostics for details.",
    };
  }
  if (searchResultCount > 0) {
    return {
      state: "memory",
      label: "Memory",
      mood: "Found clues",
      message: `${searchResultCount} memory result(s) are available.`,
      hint: "Continue or cite the result.",
    };
  }
  if (taskCount > 0) {
    return {
      state: "tasking",
      label: "Task noted",
      mood: "Scheduled",
      message: `${taskCount} task item(s) are active.`,
      hint: "Open reminders and tasks.",
    };
  }
  if (continuitySignal?.kind === "open_thread") {
    return {
      state: "presence",
      label: "Continue next time",
      mood: "Thread saved",
      message: continuitySignal.summary,
      hint: continuitySignal.display_hint || "Saved locally for the next conversation.",
    };
  }
  if (continuitySignal) {
    return {
      state: "presence",
      label: "Presence updated",
      mood: continuitySignal.title || "Companion state updated",
      message: continuitySignal.summary,
      hint: continuitySignal.display_hint || "Confirmed context can shape later replies.",
    };
  }
  if (continuityState?.unresolved_threads) {
    return {
      state: "presence",
      label: "Continue next time",
      mood: "Thread saved",
      message: `Next time: ${continuityState.unresolved_threads}`,
      hint: "Shown at runtime only.",
    };
  }
  if (continuityState?.current_mood || continuityState?.energy_level) {
    const mood = continuityState.current_mood || "Confirmed mood";
    const energy = continuityState.energy_level ? `, ${continuityState.energy_level}` : "";
    return {
      state: "reflective",
      label: "Present",
      mood,
      message: `Companion state: ${mood}${energy}.`,
      hint: continuityState.mood_momentum || "Confirmed companion state.",
    };
  }
  return {
    state: "idle",
    label: "Idle",
    mood: "Online",
    message: "Ready.",
    hint: "Chat, write a note, or create a reminder.",
  };
}
