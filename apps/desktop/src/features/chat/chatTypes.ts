export type PetBubbleTone = "thinking" | "reply" | "tool" | "error" | "reminder";
export type PetBubblePhase = "idle" | "thinking" | "speaking" | "complete" | "fading";

export const petStreamFinalTimeoutMs = 90000;

export type PetBubbleState = {
  visible: boolean;
  title: string;
  message: string;
  tone: PetBubbleTone;
  phase: PetBubblePhase;
  continueHint?: string;
  canPageBackward?: boolean;
  canPageForward?: boolean;
};
