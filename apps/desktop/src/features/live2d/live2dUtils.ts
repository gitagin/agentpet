import type { ChatContinuitySignal, ContinuityStateResponse } from "../../types";
import type { Live2DStageView } from "../../components/Live2DStage";
import { defaultLive2DModelOption } from "../../services/live2dRuntime";
import type { Live2DModelCatalog, Live2DModelOption } from "../../services/live2dRuntime";

export function checkImageExists(src: string): Promise<boolean> {
  if (!src) {
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve(true);
    image.onerror = () => resolve(false);
    image.src = src;
  });
}

export function normalizeLive2DModelCatalog(catalog: Live2DModelCatalog): Live2DModelOption[] {
  const models = Array.isArray(catalog.models) ? catalog.models : [];
  const normalized = models
    .filter((model) => model.id && model.label && model.directory && model.model)
    .map((model) => ({
      ...model,
      directory: model.directory.trim().replace(/\\/g, "/").replace(/\/?$/, "/"),
    }));
  return normalized.length > 0 ? normalized : [defaultLive2DModelOption];
}

export function getLive2DStageView({
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
}): Live2DStageView {
  if (!connected) {
    return {
      state: "disconnected",
      label: "未连接",
      mood: "离线待命",
      message: "模型壳已经就位，正在等待本地后端连接。",
      hint: "请先检查连接状态",
    };
  }
  if (streaming) {
    return {
      state: "thinking",
      label: "思考中",
      mood: "正在想",
      message: "我在想，马上回你。",
      hint: "可以随时打断",
    };
  }
  if (pendingProposalCount > 0) {
    return {
      state: "confirming",
      label: "等待确认",
      mood: "等你看看",
      message: `有 ${pendingProposalCount} 条内容等你确认。`,
      hint: "打开记忆看看",
    };
  }
  if (diagnosticsReady) {
    return {
      state: "diagnosed",
      label: "诊断完成",
      mood: "状态已归档",
      message: "诊断快照已导出，可以用于排查本地环境。",
      hint: "查看诊断信息面板",
    };
  }
  if (searchResultCount > 0) {
    return {
      state: "memory",
      label: "检索记忆",
      mood: "找到线索",
      message: `已展示 ${searchResultCount} 条记忆搜索结果。`,
      hint: "可继续追问或引用",
    };
  }
  if (taskCount > 0) {
    return {
      state: "tasking",
      label: "记录任务",
      mood: "任务已记录",
      message: `当前列表中有 ${taskCount} 条任务。`,
      hint: "可完成或取消任务",
    };
  }
  if (continuitySignal?.kind === "open_thread") {
    return {
      state: "presence",
      label: "下次接着聊",
      mood: "话题已记住",
      message: continuitySignal.summary,
      hint: continuitySignal.display_hint || "只在本机提示，不会创建系统通知。",
    };
  }
  if (continuitySignal) {
    return {
      state: "presence",
      label: "陪伴状态",
      mood: continuitySignal.title || "陪伴状态已更新",
      message: continuitySignal.summary,
      hint: continuitySignal.display_hint || "已确认的状态会影响之后的陪伴表现。",
    };
  }
  if (continuityState?.unresolved_threads) {
    return {
      state: "presence",
      label: "下次接着聊",
      mood: "话题已记住",
      message: `下次可以接着聊：${continuityState.unresolved_threads}`,
      hint: "只在运行时显示，不发系统通知。",
    };
  }
  if (continuityState?.current_mood || continuityState?.energy_level) {
    const mood = continuityState.current_mood || "情绪已确认";
    const energy = continuityState.energy_level ? `；${continuityState.energy_level}` : "";
    return {
      state: "reflective",
      label: "连续待机",
      mood,
      message: `桌宠沿用已确认的情绪状态${energy}。`,
      hint: continuityState.mood_momentum || "已确认陪伴状态",
    };
  }
  return {
    state: "idle",
    label: "待机",
    mood: "在线陪伴",
    message: "我在，右键可以快速行动。",
    hint: "继续聊、记一条或建提醒",
  };
}
