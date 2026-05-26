import type { DesktopSidecarStatus, HealthResponse } from "../../types";

export type BusinessAuthStatus = "unknown" | "checking" | "ready" | "unauthorized" | "error";

export function formatSidecarStatus(
  sidecarStatus: DesktopSidecarStatus | null,
  health: HealthResponse | null,
): string {
  if (sidecarStatus?.state === "ready" && sidecarStatus.error?.code === "PORT_IN_USE_EXISTING_BACKEND") {
    return "后端已就绪（复用已有进程）";
  }
  if (sidecarStatus?.state === "error") {
    return sidecarStatus.error?.code ? `后端异常：${formatSidecarErrorCode(sidecarStatus.error.code)}` : "后端异常";
  }
  if (sidecarStatus?.state) {
    return `后端${formatSidecarState(sidecarStatus.state)}`;
  }
  return health ? `后端${formatHealthStatus(health.status)}` : "后端未检查";
}

export function getSidecarActionMessage(sidecarStatus: DesktopSidecarStatus): string {
  const fallback = sidecarStatus.error?.message || formatSidecarStatus(sidecarStatus, sidecarStatus.health);
  switch (sidecarStatus.error?.code) {
    case "PORT_IN_USE_EXISTING_BACKEND":
      return "8765 端口已有后端响应，桌面端已先复用它。若聊天、知识库或任务请求返回 401，请关闭占用 8765 的进程后重启，或用相同 AGENT_PET_SESSION_TOKEN 启动后端。";
    case "PORT_IN_USE":
      return "8765 端口被其他程序占用且不是可用后端。请关闭占用进程后重启 npm run electron:dev。";
    case "BACKEND_NOT_FOUND":
      return "未找到后端目录。请确认 apps/backend/app/main.py 存在，或设置 AGENT_PET_BACKEND_DIR 后重启。";
    case "READINESS_FAILED":
      return "后端进程启动后没有通过健康检查。请查看终端日志，优先检查 Python 依赖、数据库配置和端口 8765。";
    case "SPAWN_FAILED":
      return "无法启动后端进程。请确认 Python 和 uvicorn 可用，或设置 AGENT_PET_PYTHON 指向可用解释器。";
    case "PROCESS_EXITED":
      return "后端进程已退出。请查看终端日志中的 Python/FastAPI 报错后再重启桌面端。";
    case "PORT_CHECK_FAILED":
      return "桌面端无法检查 8765 端口。请确认本机网络栈正常后重启。";
    default:
      return fallback;
  }
}

export function formatBusinessAuthStatus(status: BusinessAuthStatus): string {
  const labels: Record<BusinessAuthStatus, string> = {
    unknown: "未检查",
    checking: "检查中",
    ready: "可用",
    unauthorized: "令牌不一致",
    error: "异常",
  };
  return labels[status];
}

export function formatSidecarState(state: DesktopSidecarStatus["state"]): string {
  const labels: Record<DesktopSidecarStatus["state"], string> = {
    stopped: "已停止",
    "checking-port": "正在检查端口",
    starting: "正在启动",
    ready: "已就绪",
    error: "异常",
    stopping: "正在停止",
  };
  return labels[state];
}

export function formatSidecarErrorCode(code: string): string {
  const labels: Record<string, string> = {
    PORT_CHECK_FAILED: "端口检查失败",
    PORT_IN_USE: "端口被占用",
    PORT_IN_USE_EXISTING_BACKEND: "复用已有后端",
    BACKEND_NOT_FOUND: "未找到后端目录",
    READINESS_FAILED: "健康检查未通过",
    SPAWN_FAILED: "启动后端失败",
    PROCESS_EXITED: "后端进程退出",
  };
  return labels[code] || code;
}

export function formatHealthStatus(status: string): string {
  return status === "ok" ? "正常" : status;
}

export function formatDatabaseStatus(status?: string | null): string {
  if (!status) {
    return "未知";
  }
  const labels: Record<string, string> = {
    connected: "已连接",
    not_configured: "未配置",
    reachable: "可访问",
    ok: "正常",
  };
  return labels[status] || status;
}
