export type PetInputMode = "chat" | "note" | "task" | "wiki" | "review";

export type PetInputModeOption = {
  id: PetInputMode;
  label: string;
  shortLabel: string;
  ariaLabel: string;
  placeholder: string;
};

export const petInputModes: PetInputModeOption[] = [
  {
    id: "chat",
    label: "聊天",
    shortLabel: "聊",
    ariaLabel: "切换到聊天模式",
    placeholder: "和桌宠说点什么...",
  },
  {
    id: "note",
    label: "记一个",
    shortLabel: "记",
    ariaLabel: "切换到记一个模式",
    placeholder: "写下想法、偏好或片段...",
  },
  {
    id: "task",
    label: "新任务",
    shortLabel: "办",
    ariaLabel: "切换到新任务模式",
    placeholder: "要做什么，什么时候提醒...",
  },
  {
    id: "wiki",
    label: "整理 Wiki",
    shortLabel: "理",
    ariaLabel: "切换到整理 Wiki 模式",
    placeholder: "粘贴要整理的知识片段...",
  },
  {
    id: "review",
    label: "今日复盘",
    shortLabel: "复",
    ariaLabel: "切换到今日复盘模式",
    placeholder: "留空可直接复盘今天...",
  },
];

const validPetInputModes = new Set<PetInputMode>(petInputModes.map((mode) => mode.id));

export function normalizePetInputMode(value: unknown): PetInputMode | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return validPetInputModes.has(trimmed as PetInputMode) ? (trimmed as PetInputMode) : null;
}

export function getPetInputModeOption(mode: PetInputMode): PetInputModeOption {
  return petInputModes.find((option) => option.id === mode) ?? petInputModes[0];
}

export function buildPetInputIntentMessage(mode: PetInputMode, rawText: string): string {
  const text = rawText.trim();
  if (mode === "chat") {
    return text;
  }

  if (mode === "review") {
    const subject = text || "请根据今天的本地记录做一次简短复盘。";
    return [
      `今日复盘：${subject}`,
      "请优先检索本地聊天日记、长期记忆、任务和 Wiki；没有依据的内容请明确说明。",
    ].join("\n");
  }

  if (!text) {
    return "";
  }

  const intentPrompts: Record<Exclude<PetInputMode, "chat" | "review">, string> = {
    note: "记一个",
    task: "新任务",
    wiki: "整理成 Wiki",
  };
  const guardrails: Record<Exclude<PetInputMode, "chat" | "review">, string> = {
    note: "请按现有记忆策略判断是否值得沉淀；敏感、高风险或低置信内容不要直接写入。",
    task: "请按现有任务策略创建任务或提醒；需要确认的内容先进入确认流程。",
    wiki: "请按现有 Wiki 策略规划整理；高风险写入仍需确认。",
  };
  const focusedMode = mode as Exclude<PetInputMode, "chat" | "review">;
  return [`${intentPrompts[focusedMode]}：${text}`, guardrails[focusedMode]].join("\n");
}
