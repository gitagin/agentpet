import type { HalfbodyPhonemeCue, HalfbodyViseme } from "./HalfbodyPetPortrait";

const defaultCueDurationMs = 110;
const pauseCueDurationMs = 220;
const terminalPauseCueDurationMs = 320;
const minEstimatedDurationMs = 1200;

type BuildHalfbodyTtsTimelineOptions = {
  targetDurationMs?: number | null;
};

const aiApproximationChars = new Set(
  Array.from(
    "\u554a\u5440\u54ce\u7231\u8bf6\u6b38\u4e5f\u8036\u767d\u6765\u5728\u5f00\u8fd8\u8be5\u592a\u4e70\u5356\u6b6a\u5feb",
  ),
);
const oApproximationChars = new Set(
  Array.from(
    "\u54e6\u5594\u5662\u545c\u65e0\u6211\u7a9d\u8fc7\u56fd\u679c\u8bf4\u505a\u9519\u591a\u6258\u62d6\u843d\u7f57\u82e5\u7684",
  ),
);

function isPauseGrapheme(value: string) {
  return /^[\s,.;:!?\uFF0C\u3002\uFF01\uFF1F\u3001\uFF1B\uFF1A\u2026]+$/u.test(value);
}

function isTerminalPause(value: string) {
  return /^[.!?\u3002\uFF01\uFF1F\u2026]+$/u.test(value);
}

function isCjkGrapheme(value: string) {
  return /[\u3400-\u9fff]/u.test(value);
}

function isAsciiLetterOrDigit(value: string) {
  return /^[a-z0-9]$/iu.test(value);
}

function approximateVisemeForGrapheme(value: string, index: number): HalfbodyViseme {
  const lower = value.toLowerCase();
  if (isPauseGrapheme(value)) {
    return "closed";
  }
  if (/^[aie]$/u.test(lower)) {
    return "AI";
  }
  if (/^[ou]$/u.test(lower)) {
    return "O";
  }
  if (/^[mbpfv]$/u.test(lower)) {
    return "closed";
  }
  if (aiApproximationChars.has(value)) {
    return "AI";
  }
  if (oApproximationChars.has(value)) {
    return "O";
  }
  if (isCjkGrapheme(value)) {
    return index % 4 === 0 ? "closed" : "AI";
  }
  if (isAsciiLetterOrDigit(value)) {
    return index % 3 === 0 ? "closed" : "AI";
  }
  return "closed";
}

function cueWeightForGrapheme(value: string) {
  if (isTerminalPause(value)) {
    return terminalPauseCueDurationMs;
  }
  if (isPauseGrapheme(value)) {
    return pauseCueDurationMs;
  }
  if (isCjkGrapheme(value)) {
    return 210;
  }
  if (isAsciiLetterOrDigit(value)) {
    return 95;
  }
  return defaultCueDurationMs;
}

function normalizeTargetDurationMs(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.round(value) : null;
}

export function estimateHalfbodyTtsDurationMs(text: string): number {
  const graphemes = Array.from(text.normalize("NFKC"));
  const estimated = graphemes.reduce((total, grapheme) => total + cueWeightForGrapheme(grapheme), 0);
  return Math.max(minEstimatedDurationMs, Math.round(estimated));
}

export function buildHalfbodyTtsTimelineFromText(
  text: string,
  options: BuildHalfbodyTtsTimelineOptions = {},
): HalfbodyPhonemeCue[] {
  const graphemes = Array.from(text.normalize("NFKC"));
  const targetDurationMs = normalizeTargetDurationMs(options.targetDurationMs) ?? estimateHalfbodyTtsDurationMs(text);
  const cues: HalfbodyPhonemeCue[] = [];
  const cueWeights = graphemes.map(cueWeightForGrapheme);
  const totalWeight = cueWeights.reduce((total, weight) => total + weight, 0);

  if (!graphemes.length || totalWeight <= 0) {
    return [{ viseme: "closed", startMs: targetDurationMs, durationMs: defaultCueDurationMs }];
  }

  let elapsedWeight = 0;
  graphemes.forEach((grapheme, index) => {
    const nextElapsedWeight = elapsedWeight + cueWeights[index];
    const startMs = Math.round((elapsedWeight / totalWeight) * targetDurationMs);
    const nextStartMs = Math.round((nextElapsedWeight / totalWeight) * targetDurationMs);
    cues.push({
      viseme: approximateVisemeForGrapheme(grapheme, index),
      startMs,
      durationMs: Math.max(0, nextStartMs - startMs),
    });
    elapsedWeight = nextElapsedWeight;
  });

  cues.push({
    viseme: "closed",
    startMs: targetDurationMs,
    durationMs: defaultCueDurationMs,
  });

  return cues;
}
