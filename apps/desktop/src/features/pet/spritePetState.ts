import type { PetStageState, PetStageView } from "./petStageState";

export type SpritePetDragDirection = "none" | "left" | "right";

export type SpritePetActionKey =
  | "idle"
  | "sleep_quiet"
  | "chat_listen"
  | "chat_think"
  | "chat_talk"
  | "chat_done"
  | "memory_search"
  | "memory_found"
  | "memory_not_found"
  | "memory_save_diary"
  | "memory_save_long_term"
  | "memory_confirm_needed"
  | "memory_privacy_guard"
  | "memory_revert"
  | "wiki_organize"
  | "wiki_check"
  | "wiki_archive"
  | "task_create"
  | "task_reminder"
  | "task_complete"
  | "continuity_remember"
  | "emotion_comfort"
  | "celebrate_small"
  | "system_connecting"
  | "system_offline"
  | "system_error"
  | "system_diagnosed"
  | "pet_drag_right"
  | "pet_drag_left"
  | "pet_waving"
  | "pet_waiting"
  | "pet_review";

export type SpritePetEmotion = "neutral" | "bright" | "focused" | "soft" | "careful" | "worried" | "sleepy";

export type SpritePetMotionProfile = {
  bobPx: number;
  breathe: number;
  tiltDeg: number;
  swayDeg: number;
  blinkSeconds: number;
  mouth: "closed" | "talk" | "soft";
  glow: "none" | "pendant" | "warm";
  expression: SpritePetEmotion;
};

export type SpritePetAnimationKey =
  | "idle"
  | "running-right"
  | "running-left"
  | "waving"
  | "thinking"
  | "working"
  | "done"
  | "failed"
  | "sleeping";

export type SpritePetAtlasRowKey = SpritePetAnimationKey;

export type SpritePetAtlasRow = {
  key: SpritePetAtlasRowKey;
  frameCount: number;
};

export const spritePetAtlasRows: readonly SpritePetAtlasRow[] = [
  { key: "idle", frameCount: 6 },
  { key: "running-right", frameCount: 8 },
  { key: "running-left", frameCount: 8 },
  { key: "waving", frameCount: 6 },
  { key: "thinking", frameCount: 6 },
  { key: "working", frameCount: 6 },
  { key: "done", frameCount: 5 },
  { key: "failed", frameCount: 6 },
  { key: "sleeping", frameCount: 6 },
];

export type SpritePetAction = {
  key: SpritePetActionKey;
  label: string;
  detail: string;
  motion: SpritePetMotionProfile;
};

type ResolveSpritePetActionOptions = {
  stage: PetStageView;
  connected: boolean;
  streaming: boolean;
  speaking: boolean;
  inputVisible: boolean;
  shortcutVisible: boolean;
  dragging: boolean;
  dragDirection: SpritePetDragDirection;
  actionKeyOverride?: string | null;
};

const baseMotion: SpritePetMotionProfile = {
  bobPx: 2.4,
  breathe: 0.018,
  tiltDeg: 0,
  swayDeg: 0.9,
  blinkSeconds: 4.6,
  mouth: "closed",
  glow: "none",
  expression: "neutral",
};

export const spritePetActions: Record<SpritePetActionKey, SpritePetAction> = {
  idle: action("idle", "待机", "在线陪伴中", {}),
  sleep_quiet: action("sleep_quiet", "安静待机", "低打扰陪伴", {
    bobPx: 1.1,
    breathe: 0.012,
    blinkSeconds: 6.8,
    expression: "sleepy",
  }),
  chat_listen: action("chat_listen", "倾听", "正在等你输入", {
    tiltDeg: -1.2,
    bobPx: 1.8,
    expression: "soft",
  }),
  chat_think: action("chat_think", "思考", "正在整理回复", {
    tiltDeg: 1.8,
    bobPx: 1.5,
    swayDeg: 0.45,
    glow: "pendant",
    expression: "focused",
  }),
  chat_talk: action("chat_talk", "说话", "跟随语音开合嘴型", {
    bobPx: 2.1,
    mouth: "talk",
    expression: "bright",
  }),
  chat_done: action("chat_done", "完成回复", "轻轻回到待机", {
    bobPx: 2,
    tiltDeg: -0.8,
    expression: "bright",
  }),
  memory_search: action("memory_search", "检索记忆", "正在翻找线索", {
    bobPx: 1.4,
    tiltDeg: 1.6,
    swayDeg: 0.35,
    glow: "pendant",
    expression: "focused",
  }),
  memory_found: action("memory_found", "找到记忆", "发现了相关线索", {
    bobPx: 2.4,
    tiltDeg: -1.1,
    glow: "warm",
    expression: "bright",
  }),
  memory_not_found: action("memory_not_found", "没有找到", "保持诚实反馈", {
    bobPx: 1.3,
    tiltDeg: 2.4,
    expression: "careful",
  }),
  memory_save_diary: action("memory_save_diary", "写入日记", "整理到本地记录", {
    bobPx: 1.9,
    glow: "pendant",
    expression: "soft",
  }),
  memory_save_long_term: action("memory_save_long_term", "沉淀记忆", "保存长期线索", {
    bobPx: 1.9,
    glow: "pendant",
    expression: "soft",
  }),
  memory_confirm_needed: action("memory_confirm_needed", "等待确认", "需要你点头", {
    bobPx: 1.1,
    tiltDeg: 1.7,
    blinkSeconds: 5.6,
    expression: "careful",
  }),
  memory_privacy_guard: action("memory_privacy_guard", "隐私保护", "敏感内容已拦下", {
    bobPx: 1,
    tiltDeg: -1,
    blinkSeconds: 5.8,
    expression: "careful",
  }),
  memory_revert: action("memory_revert", "撤回整理", "已回滚记录", {
    bobPx: 1.4,
    tiltDeg: 2.2,
    expression: "worried",
  }),
  wiki_organize: action("wiki_organize", "整理资料", "正在组织 Wiki", {
    bobPx: 1.5,
    tiltDeg: 1.2,
    glow: "pendant",
    expression: "focused",
  }),
  wiki_check: action("wiki_check", "检查资料", "正在自检格式", {
    bobPx: 1.2,
    tiltDeg: -1.4,
    glow: "pendant",
    expression: "focused",
  }),
  wiki_archive: action("wiki_archive", "归档完成", "资料已归档", {
    bobPx: 2,
    tiltDeg: -0.9,
    expression: "bright",
  }),
  task_create: action("task_create", "创建任务", "提醒已记录", {
    bobPx: 2.3,
    tiltDeg: -1.2,
    glow: "warm",
    expression: "bright",
  }),
  task_reminder: action("task_reminder", "提醒时间", "温和提示中", {
    bobPx: 2.6,
    tiltDeg: -1.8,
    glow: "warm",
    expression: "bright",
  }),
  task_complete: action("task_complete", "任务完成", "小小庆祝", {
    bobPx: 3.2,
    tiltDeg: -2.2,
    swayDeg: 1.4,
    glow: "warm",
    expression: "bright",
  }),
  continuity_remember: action("continuity_remember", "记得话题", "下次能接着聊", {
    bobPx: 2,
    tiltDeg: -1,
    expression: "soft",
  }),
  emotion_comfort: action("emotion_comfort", "安慰陪伴", "慢一点也可以", {
    bobPx: 1.4,
    breathe: 0.014,
    blinkSeconds: 5.2,
    expression: "soft",
  }),
  celebrate_small: action("celebrate_small", "轻轻庆祝", "做得不错", {
    bobPx: 3,
    tiltDeg: -2,
    swayDeg: 1.4,
    glow: "warm",
    expression: "bright",
  }),
  system_connecting: action("system_connecting", "连接中", "等待本地服务", {
    bobPx: 1.2,
    tiltDeg: 1.3,
    glow: "pendant",
    expression: "focused",
  }),
  system_offline: action("system_offline", "离线", "本地服务未连接", {
    bobPx: 0.8,
    breathe: 0.01,
    tiltDeg: 2,
    blinkSeconds: 6.4,
    expression: "sleepy",
  }),
  system_error: action("system_error", "异常", "需要检查状态", {
    bobPx: 1.1,
    tiltDeg: 2.6,
    blinkSeconds: 5.7,
    expression: "worried",
  }),
  system_diagnosed: action("system_diagnosed", "诊断完成", "状态已更新", {
    bobPx: 2,
    tiltDeg: -0.8,
    glow: "pendant",
    expression: "focused",
  }),
  pet_drag_right: action("pet_drag_right", "向右拖拽", "跟随窗口移动", {
    bobPx: 1.7,
    tiltDeg: 5.2,
    swayDeg: 1.8,
    blinkSeconds: 5.4,
    expression: "focused",
  }),
  pet_drag_left: action("pet_drag_left", "向左拖拽", "跟随窗口移动", {
    bobPx: 1.7,
    tiltDeg: -5.2,
    swayDeg: 1.8,
    blinkSeconds: 5.4,
    expression: "focused",
  }),
  pet_waving: action("pet_waving", "招呼", "快捷动作已打开", {
    bobPx: 3.1,
    tiltDeg: -2.8,
    swayDeg: 1.7,
    expression: "bright",
  }),
  pet_waiting: action("pet_waiting", "等待", "等你下一步", {
    bobPx: 1.4,
    tiltDeg: 1.1,
    expression: "careful",
  }),
  pet_review: action("pet_review", "复查", "正在看结果", {
    bobPx: 1.3,
    tiltDeg: 1.9,
    glow: "pendant",
    expression: "focused",
  }),
};

const petStageToSpriteAction: Record<PetStageState, SpritePetActionKey> = {
  disconnected: "system_offline",
  idle: "idle",
  presence: "continuity_remember",
  reflective: "emotion_comfort",
  thinking: "chat_think",
  memory: "memory_search",
  confirming: "memory_confirm_needed",
  tasking: "task_create",
  diagnosed: "system_diagnosed",
};

export function resolveSpritePetAction({
  stage,
  connected,
  streaming,
  speaking,
  inputVisible,
  shortcutVisible,
  dragging,
  dragDirection,
  actionKeyOverride,
}: ResolveSpritePetActionOptions): SpritePetAction {
  if (dragging) {
    return spritePetActions[dragDirection === "left" ? "pet_drag_left" : "pet_drag_right"];
  }
  if (shortcutVisible) {
    return spritePetActions.pet_waving;
  }
  if (speaking) {
    return spritePetActions.chat_talk;
  }
  const overrideAction = normalizeSpritePetActionKey(actionKeyOverride);
  if (overrideAction) {
    return spritePetActions[overrideAction];
  }
  if (!connected) {
    return spritePetActions.system_offline;
  }
  if (inputVisible) {
    return spritePetActions.chat_listen;
  }
  if (streaming) {
    return spritePetActions.chat_think;
  }
  return spritePetActions[petStageToSpriteAction[stage.state] || "idle"];
}

export function normalizeSpritePetActionKey(value: string | null | undefined): SpritePetActionKey | null {
  const key = value?.trim();
  return key && key in spritePetActions ? (key as SpritePetActionKey) : null;
}

export function getSpritePetAnimationKey(actionKey: SpritePetActionKey): SpritePetAnimationKey {
  switch (actionKey) {
    case "pet_drag_right":
      return "running-right";
    case "pet_drag_left":
      return "running-left";
    case "pet_waving":
    case "chat_listen":
    case "chat_talk":
    case "celebrate_small":
      return "waving";
    case "task_complete":
    case "chat_done":
    case "memory_found":
    case "memory_confirm_needed":
    case "wiki_archive":
    case "pet_waiting":
      return "done";
    case "chat_think":
    case "memory_search":
    case "system_connecting":
      return "thinking";
    case "task_create":
    case "task_reminder":
    case "memory_save_diary":
    case "memory_save_long_term":
    case "wiki_organize":
    case "wiki_check":
    case "system_diagnosed":
    case "pet_review":
      return "working";
    case "system_error":
    case "memory_revert":
    case "memory_not_found":
    case "memory_privacy_guard":
      return "failed";
    case "system_offline":
    case "sleep_quiet":
      return "sleeping";
    case "emotion_comfort":
    case "continuity_remember":
    case "idle":
    default:
      return "idle";
  }
}

export function getSpritePetAtlasRowKey(actionKey: SpritePetActionKey): SpritePetAtlasRowKey {
  return getSpritePetAnimationKey(actionKey);
}

function action(
  key: SpritePetActionKey,
  label: string,
  detail: string,
  motion: Partial<SpritePetMotionProfile>,
): SpritePetAction {
  return {
    key,
    label,
    detail,
    motion: {
      ...baseMotion,
      ...motion,
    },
  };
}
