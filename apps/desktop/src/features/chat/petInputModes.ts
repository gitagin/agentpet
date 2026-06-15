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
    label: "陪伴",
    shortLabel: "陪",
    ariaLabel: "切换到陪伴",
    placeholder: "和我说说现在发生的事...",
  },
  {
    id: "note",
    label: "记住",
    shortLabel: "记",
    ariaLabel: "切换到记住",
    placeholder: "告诉我一件希望以后还能接上的事...",
  },
  {
    id: "task",
    label: "提醒",
    shortLabel: "醒",
    ariaLabel: "切换到提醒",
    placeholder: "要我在什么时候提醒你...",
  },
  {
    id: "wiki",
    label: "整理资料",
    shortLabel: "理",
    ariaLabel: "切换到整理资料",
    placeholder: "粘贴想整理的资料或想法...",
  },
  {
    id: "review",
    label: "回顾今天",
    shortLabel: "顾",
    ariaLabel: "切换到回顾今天",
    placeholder: "留空也可以直接回顾今天...",
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
    const subject = text || "请根据今天的本地记录做一次简短回顾。";
    return [
      `回顾今天：${subject}`,
      "请优先检索本地聊天日记、长期记忆、任务和知识整理内容；没有依据的内容请明确说明。用户可见回复请使用普通中文，不要使用工程词。",
    ].join("\n");
  }

  if (!text) {
    return "";
  }

  const intentPrompts: Record<Exclude<PetInputMode, "chat" | "review">, string> = {
    note: "记住",
    task: "提醒",
    wiki: "整理资料到知识页",
  };
  const guardrails: Record<Exclude<PetInputMode, "chat" | "review">, string> = {
    note: "请按现有记忆策略判断是否值得沉淀；敏感、高风险或低置信内容不要直接写入。用户可见回复请用“记住”“记忆”表达。",
    task: "请按现有任务策略创建任务或提醒；需要确认的内容先进入确认流程。用户可见回复请用“提醒”表达。",
    wiki: "这是资料整理请求，请按现有知识页策略规划整理；高风险写入仍需确认。用户可见回复请用“资料”“知识页”表达，避免直接说技术格式或内部模块名。",
  };
  const focusedMode = mode as Exclude<PetInputMode, "chat" | "review">;
  return [`${intentPrompts[focusedMode]}：${text}`, guardrails[focusedMode]].join("\n");
}
