import { ApiError } from "./apiClient";

export type BusinessAuthFailure = {
  status: "unauthorized" | "error";
  message: string;
};

export function describeError(error: unknown, prefix?: string): string {
  const lead = prefix ? `${prefix}: ` : "";
  if (error instanceof ApiError) {
    const code = error.code ? `${error.code}: ` : "";
    const request = error.requestId ? ` (request ${error.requestId})` : "";
    return `${lead}${code}${error.message}${request}`;
  }
  if (error instanceof Error) {
    if (error.name === "TypeError" && /fetch|network/i.test(error.message)) {
      return `${lead}无法连接本机服务。请重新启动桌面应用；仍未恢复时打开连接诊断。`;
    }
    return `${lead}${error.message}`;
  }
  return `${lead}发生未知桌面客户端错误。`;
}

export function isSidecarStartingError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 503 && error.code === "sidecar_starting";
}

export function businessAuthMismatchMessage(): string {
  return "本机服务已响应，但当前桌面会话无法访问。请关闭其他 Agent Pet 窗口并重新启动桌面应用；仍未恢复时打开连接诊断。";
}

export function describeBusinessAuthFailure(error: unknown): BusinessAuthFailure {
  if (error instanceof ApiError && error.status === 401) {
    return {
      status: "unauthorized",
      message: "本机服务已响应，但当前桌面会话无法访问。请关闭其他 Agent Pet 窗口并重新启动桌面应用。",
    };
  }
  return {
    status: "error",
    message: describeError(error, "业务接口鉴权检查失败"),
  };
}
