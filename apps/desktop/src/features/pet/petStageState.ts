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
      label: "离线",
      mood: "待命中",
      message: "本机服务未连接。",
      hint: "请检查连接状态。",
    };
  }
  if (streaming) {
    return {
      state: "thinking",
      label: "思考中",
      mood: "整理中",
      message: "正在准备回复。",
      hint: "随时可以停止回复。",
    };
  }
  if (pendingProposalCount > 0) {
    return {
      state: "confirming",
      label: "待确认",
      mood: "待命中",
      message: `${pendingProposalCount} 条记忆待确认。`,
      hint: "打开记忆页复核。",
    };
  }
  if (diagnosticsReady) {
    return {
      state: "diagnosed",
      label: "已诊断",
      mood: "已更新",
      message: "诊断信息已就绪。",
      hint: "打开诊断查看详情。",
    };
  }
  if (searchResultCount > 0) {
    return {
      state: "memory",
      label: "记忆",
      mood: "找到线索",
      message: `${searchResultCount} 条记忆线索可用。`,
      hint: "继续追问或引用这条结果。",
    };
  }
  if (taskCount > 0) {
    return {
      state: "tasking",
      label: "已记任务",
      mood: "已安排",
      message: `${taskCount} 个任务进行中。`,
      hint: "打开提醒和任务。",
    };
  }
  if (continuitySignal?.kind === "open_thread") {
    return {
      state: "presence",
      label: "下次继续",
      mood: "话题已保存",
      message: continuitySignal.summary,
      hint: continuitySignal.display_hint || "已保存在本机，供下次继续。",
    };
  }
  if (continuitySignal) {
    return {
      state: "presence",
      label: "陪伴状态已更新",
      mood: continuitySignal.title || "陪伴状态已更新",
      message: continuitySignal.summary,
      hint: continuitySignal.display_hint || "已确认的上下文会影响后续回复。",
    };
  }
  if (continuityState?.unresolved_threads) {
    return {
      state: "presence",
      label: "下次继续",
      mood: "话题已保存",
      message: `下次继续：${continuityState.unresolved_threads}`,
      hint: "仅在运行时展示。",
    };
  }
  if (continuityState?.current_mood || continuityState?.energy_level) {
    const mood = continuityState.current_mood || "已确认心情";
    const energy = continuityState.energy_level ? `，${continuityState.energy_level}` : "";
    return {
      state: "reflective",
      label: "当前",
      mood,
      message: `陪伴状态：${mood}${energy}。`,
      hint: continuityState.mood_momentum || "已确认的陪伴状态。",
    };
  }
  return {
    state: "idle",
    label: "待命",
    mood: "在线",
    message: "随时可以聊。",
    hint: "聊天、记一条，或者创建一个提醒。",
  };
}
