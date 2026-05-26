export type PetBubbleTone = "thinking" | "reply" | "tool" | "error" | "reminder";
export type PetBubblePhase = "idle" | "thinking" | "speaking" | "complete" | "fading";

export const petStreamFinalTimeoutMs = 45000;
export const petStreamFinalWatchdogDelayMs = 18000;

export type PetBubbleState = {
  visible: boolean;
  title: string;
  message: string;
  tone: PetBubbleTone;
  phase: PetBubblePhase;
  continueHint?: string;
};
