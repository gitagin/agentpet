import type { DesktopSidecarStatus, HealthResponse } from "../../types";

export type BusinessAuthStatus = "unknown" | "checking" | "ready" | "unauthorized" | "error";

function withSidecarLog(message: string, sidecarStatus: DesktopSidecarStatus): string {
  return sidecarStatus.logPath ? `${message} 日志：${sidecarStatus.logPath}` : message;
}

export function formatSidecarStatus(
  sidecarStatus: DesktopSidecarStatus | null,
  health: HealthResponse | null,
): string {
  if (sidecarStatus?.state === "degraded") {
    return "本机服务降级运行（复用外部进程，未校验令牌）";
  }
  if (sidecarStatus?.state === "error") {
    return sidecarStatus.error?.code ? `本机服务异常：${formatSidecarErrorCode(sidecarStatus.error.code)}` : "本机服务异常";
  }
  if (sidecarStatus?.state) {
    return `本机服务${formatSidecarState(sidecarStatus.state)}`;
  }
  return health ? `本机服务${formatHealthStatus(health.status)}` : "本机服务未检查";
}

export function getSidecarActionMessage(sidecarStatus: DesktopSidecarStatus): string {
  const fallback = sidecarStatus.error?.message || formatSidecarStatus(sidecarStatus, sidecarStatus.health);
  switch (sidecarStatus.error?.code) {
    case "PORT_IN_USE_EXISTING_BACKEND":
      return `端口 ${sidecarStatus.port} 已有本机服务响应，桌面端以降级状态复用它（无法校验会话令牌）。若聊天、资料库或任务请求返回 401，请关闭占用进程后重启，或用与桌面端一致的本地会话令牌启动服务。`;
    case "PORT_IN_USE":
      return "约定端口与备选端口都被占用，且占用者不是可用本机服务。请释放约定端口附近的端口后重启桌面端。";
    case "BACKEND_NOT_FOUND":
      return "未找到本机服务目录。请确认 apps/backend/app/main.py 存在，或设置 AGENT_PET_BACKEND_DIR 后重启。";
    case "SIDECAR_EXECUTABLE_NOT_FOUND":
      return withSidecarLog("发布包缺少本机服务组件，请重新下载或重新打包应用。", sidecarStatus);
    case "READINESS_FAILED":
      return withSidecarLog("本机服务启动后没有通过健康检查。请查看本机服务日志。", sidecarStatus);
    case "READINESS_TIMEOUT":
      return "本机服务已启动，但在约定时间内未通过健康检查；进程仍在运行、桌面端会继续等待。冷启动或首次建库可能较慢，可稍候或重启应用重试，也可用 AGENT_PET_READY_TIMEOUT_MS 调整提醒时长。";
    case "SPAWN_FAILED":
      return withSidecarLog("无法启动本机服务。请检查发布包完整性、文件权限和本机服务日志。", sidecarStatus);
    case "PROCESS_EXITED":
      return withSidecarLog("本机服务已退出。请查看本机服务日志后再重启桌面端。", sidecarStatus);
    case "PORT_CHECK_FAILED":
      return "桌面端无法检查本机服务端口。请确认本机网络栈正常后重启。";
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
    degraded: "降级运行（复用外部进程）",
    recovering: "正在恢复",
    "manual-retry": "等待手动重试",
    suspended: "已暂停",
    error: "异常",
    stopping: "正在停止",
  };
  return labels[state];
}

export function formatSidecarErrorCode(code: string): string {
  const labels: Record<string, string> = {
    PORT_CHECK_FAILED: "端口检查失败",
    PORT_IN_USE: "端口被占用",
    PORT_IN_USE_EXISTING_BACKEND: "降级复用已有服务",
    BACKEND_NOT_FOUND: "未找到服务目录",
    SIDECAR_EXECUTABLE_NOT_FOUND: "发布包缺少服务组件",
    READINESS_FAILED: "健康检查未通过",
    READINESS_TIMEOUT: "就绪等待超时（进程仍在运行）",
    SPAWN_FAILED: "启动服务失败",
    PROCESS_EXITED: "服务进程退出",
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
