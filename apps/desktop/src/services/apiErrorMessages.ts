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
      return `${lead}无法连接后端。请确认桌面端已启动托管后端，或检查后端地址和端口 8765。`;
    }
    return `${lead}${error.message}`;
  }
  return `${lead}发生未知桌面客户端错误。`;
}

export function isSidecarStartingError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 503 && error.code === "sidecar_starting";
}

export function businessAuthMismatchMessage(): string {
  return "后端健康检查通过，但业务接口鉴权失败。可能已有 8765 后端和当前桌面端会话令牌不一致，请关闭旧后端后重新运行 npm run electron:dev。";
}

export function describeBusinessAuthFailure(error: unknown): BusinessAuthFailure {
  if (error instanceof ApiError && error.status === 401) {
    return {
      status: "unauthorized",
      message: "后端已启动，但业务接口鉴权失败。可能已有 8765 后端和当前桌面端会话令牌不一致。",
    };
  }
  return {
    status: "error",
    message: describeError(error, "业务接口鉴权检查失败"),
  };
}
