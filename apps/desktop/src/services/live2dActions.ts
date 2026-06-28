export type Live2DActionMotion = {
  group?: string;
  index?: number;
};

export type Live2DActionDirective = {
  expression?: string;
  motion?: Live2DActionMotion;
  petHint?: string;
  controlSummary?: string;
};

export type Live2DActionProfile = {
  version?: number;
  description?: string;
  actions: Record<string, Live2DActionDirective>;
};

export type Live2DMotionRef = {
  group: string;
  index: number;
};

export type Live2DResolvedActionDirective = {
  actionKey: string;
  expression: string;
  motionGroup: string;
  motionIndex: number;
  petHint: string;
  controlSummary: string;
  warnings: string[];
};

const defaultActionDirectives: Record<string, Required<Pick<Live2DActionDirective, "expression" | "petHint" | "controlSummary">>> = {
  idle: {
    expression: "1desk",
    petHint: "在线陪伴中，双击打开控制台。",
    controlSummary: "待机动作，使用模型默认循环。",
  },
  chat_listen: {
    expression: "2mic",
    petHint: "我在听你说。",
    controlSummary: "倾听状态，等待用户输入。",
  },
  chat_think: {
    expression: "3clever",
    petHint: "正在思考，回复生成中。",
    controlSummary: "思考状态，适配聊天生成。",
  },
  chat_talk: {
    expression: "2mic",
    petHint: "正在朗读或回复。",
    controlSummary: "说话状态，适配 TTS 或流式回复。",
  },
  chat_done: {
    expression: "1desk",
    petHint: "回复完成。",
    controlSummary: "回复完成状态，回到轻待机。",
  },
  memory_search: {
    expression: "7keyboard",
    petHint: "已找到记忆线索，打开控制台查看。",
    controlSummary: "记忆检索状态。",
  },
  memory_found: {
    expression: "7keyboard",
    petHint: "翻到相关记忆了。",
    controlSummary: "记忆命中状态。",
  },
  memory_not_found: {
    expression: "5QAQ",
    petHint: "暂时没有翻到相关记忆。",
    controlSummary: "记忆未命中状态。",
  },
  memory_save_diary: {
    expression: "1desk",
    petHint: "这段对话已整理到本机日记。",
    controlSummary: "聊天日记自动整理状态。",
  },
  memory_save_long_term: {
    expression: "1desk",
    petHint: "值得长期记住的内容已沉淀。",
    controlSummary: "长期记忆沉淀状态。",
  },
  memory_confirm_needed: {
    expression: "4OAO",
    petHint: "有记忆待确认，双击处理。",
    controlSummary: "记忆确认状态。",
  },
  memory_privacy_guard: {
    expression: "4OAO",
    petHint: "这部分内容需要先保护隐私。",
    controlSummary: "敏感内容保护状态。",
  },
  memory_revert: {
    expression: "5QAQ",
    petHint: "已撤回这次整理记录。",
    controlSummary: "记忆或资料撤回状态。",
  },
  task_create: {
    expression: "1desk",
    petHint: "任务已记录，打开控制台管理。",
    controlSummary: "任务创建状态。",
  },
  task_reminder: {
    expression: "2mic",
    petHint: "提醒时间到了。",
    controlSummary: "提醒触发状态。",
  },
  task_complete: {
    expression: "8punch",
    petHint: "这件事完成了。",
    controlSummary: "任务完成状态。",
  },
  wiki_organize: {
    expression: "7keyboard",
    petHint: "正在整理资料。",
    controlSummary: "资料整理状态。",
  },
  wiki_check: {
    expression: "3clever",
    petHint: "正在检查资料格式。",
    controlSummary: "资料检查状态。",
  },
  wiki_archive: {
    expression: "1desk",
    petHint: "资料已归档。",
    controlSummary: "资料归档状态。",
  },
  continuity_remember: {
    expression: "2mic",
    petHint: "这个话题下次还能接着聊。",
    controlSummary: "下次接着聊状态。",
  },
  emotion_comfort: {
    expression: "6i gi a ri",
    petHint: "我会慢一点陪你。",
    controlSummary: "情绪陪伴状态。",
  },
  system_connecting: {
    expression: "3clever",
    petHint: "正在连接本地后端。",
    controlSummary: "系统连接中状态。",
  },
  system_offline: {
    expression: "5QAQ",
    petHint: "离线待命，双击打开控制台检查连接。",
    controlSummary: "离线状态。",
  },
  system_error: {
    expression: "5QAQ",
    petHint: "有一处状态需要检查。",
    controlSummary: "错误检查状态。",
  },
  system_diagnosed: {
    expression: "9",
    petHint: "诊断已完成，可回控制台查看。",
    controlSummary: "诊断完成状态。",
  },
  tts_speaking: {
    expression: "2mic",
    petHint: "TTS 朗读反馈已开启。",
    controlSummary: "TTS 说话状态。",
  },
  sleep_quiet: {
    expression: "1desk",
    petHint: "安静待机中。",
    controlSummary: "安静模式状态。",
  },
  celebrate_small: {
    expression: "8punch",
    petHint: "做得不错。",
    controlSummary: "轻庆祝状态。",
  },
};

export const live2DRecommendedActionKeys = Object.freeze(Object.keys(defaultActionDirectives));

export function normalizeLive2DActionProfile(raw: unknown): Live2DActionProfile | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }

  const record = raw as Record<string, unknown>;
  const actions = normalizeActionMap(record.actions);
  if (Object.keys(actions).length === 0) {
    return null;
  }

  return {
    version: typeof record.version === "number" ? record.version : undefined,
    description: typeof record.description === "string" ? record.description : undefined,
    actions,
  };
}

export function resolveLive2DActionDirective({
  actionKey,
  profile,
  availableExpressions,
  availableMotions,
  defaultMotionGroup,
  defaultMotionIndex,
}: {
  actionKey: string;
  profile?: Live2DActionProfile | null;
  availableExpressions?: string[];
  availableMotions?: Live2DMotionRef[];
  defaultMotionGroup?: string;
  defaultMotionIndex?: number;
}): Live2DResolvedActionDirective {
  const warnings: string[] = [];
  const fallback = defaultActionDirectives[actionKey] || defaultActionDirectives.idle;
  const profileDirective = profile?.actions[actionKey] || null;
  const availableExpressionSet = new Set((availableExpressions || []).filter(Boolean));
  const availableMotionSet = new Set((availableMotions || []).map((motion) => motionKey(motion.group, motion.index)));
  const expression = resolveExpression(profileDirective?.expression, "", availableExpressionSet, warnings);
  const defaultMotion = validMotion(defaultMotionGroup ?? "", defaultMotionIndex);
  const resolvedMotion = resolveMotion(profileDirective?.motion, availableMotionSet, defaultMotion, warnings);
  const petHint = profileDirective?.petHint || fallback.petHint;
  const controlSummary = profileDirective?.controlSummary || fallback.controlSummary;

  return {
    actionKey,
    expression,
    motionGroup: resolvedMotion?.group ?? "",
    motionIndex: resolvedMotion?.index ?? -1,
    petHint,
    controlSummary,
    warnings,
  };
}

function normalizeActionMap(raw: unknown): Record<string, Live2DActionDirective> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }

  const normalized: Record<string, Live2DActionDirective> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (!key.trim() || !value || typeof value !== "object" || Array.isArray(value)) {
      continue;
    }
    const action = normalizeActionDirective(value as Record<string, unknown>);
    if (action) {
      normalized[key.trim()] = action;
    }
  }
  return normalized;
}

function normalizeActionDirective(raw: Record<string, unknown>): Live2DActionDirective | null {
  const expression = typeof raw.expression === "string" ? raw.expression.trim() : undefined;
  const motion = normalizeMotion(raw.motion);
  const petHint = typeof raw.petHint === "string" ? raw.petHint.trim() : undefined;
  const controlSummary = typeof raw.controlSummary === "string" ? raw.controlSummary.trim() : undefined;

  if (!expression && !motion && !petHint && !controlSummary) {
    return null;
  }

  return {
    expression,
    motion,
    petHint,
    controlSummary,
  };
}

function normalizeMotion(raw: unknown): Live2DActionMotion | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }

  const record = raw as Record<string, unknown>;
  const group = typeof record.group === "string" ? record.group : undefined;
  const index = typeof record.index === "number" && Number.isInteger(record.index) ? record.index : undefined;
  if (group === undefined && index === undefined) {
    return undefined;
  }
  return { group, index };
}

function resolveExpression(
  candidate: string | undefined,
  fallback: string,
  availableExpressionSet: Set<string>,
  warnings: string[],
): string {
  const fallbackExpression = fallback.trim();
  if (!candidate && !fallbackExpression) {
    return "";
  }
  if (availableExpressionSet.size === 0) {
    warnings.push(`模型没有可用表情，跳过表情 ${candidate || fallbackExpression}。`);
    return "";
  }
  if (candidate && availableExpressionSet.has(candidate)) {
    return candidate;
  }
  if (candidate) {
    warnings.push(
      fallbackExpression
        ? `模型缺少表情 ${candidate}，使用默认表情 ${fallbackExpression}。`
        : `模型缺少表情 ${candidate}，跳过表情切换。`,
    );
  }
  if (fallbackExpression && availableExpressionSet.has(fallbackExpression)) {
    return fallbackExpression;
  }
  if (fallbackExpression) {
    warnings.push(`模型缺少默认表情 ${fallbackExpression}，跳过表情切换。`);
  }
  return "";
}

function resolveMotion(
  candidate: Live2DActionMotion | undefined,
  availableMotionSet: Set<string>,
  defaultMotion: Live2DMotionRef | null,
  warnings: string[],
): Live2DMotionRef | null {
  const candidateMotion = validMotion(candidate?.group ?? "", candidate?.index);
  if (candidateMotion && availableMotionSet.has(motionKey(candidateMotion.group, candidateMotion.index))) {
    return candidateMotion;
  }

  if (candidateMotion) {
    warnings.push(`模型缺少动作 ${candidateMotion.group || "(default)"}[${candidateMotion.index}]，使用默认动作。`);
  }

  if (defaultMotion && availableMotionSet.has(motionKey(defaultMotion.group, defaultMotion.index))) {
    return defaultMotion;
  }
  return null;
}

function validMotion(group: string, index: number | undefined): Live2DMotionRef | null {
  if (typeof index !== "number" || !Number.isInteger(index) || index < 0) {
    return null;
  }
  return { group, index };
}

function motionKey(group: string, index: number): string {
  return `${group}\u0000${index}`;
}
