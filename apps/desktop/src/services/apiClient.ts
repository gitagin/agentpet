import type { ApiErrorBody, ConnectionSettings, DesktopApiResponse, HealthResponse } from "../types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly requestId?: string;
  readonly details?: Record<string, unknown>;

  constructor(message: string, status: number, body?: ApiErrorBody) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.error?.code;
    this.requestId = body?.error?.request_id;
    this.details = body?.error?.details;
  }
}

export function loadConnectionSettings(): ConnectionSettings {
  const sidecarConfig = window.agentDesktop?.getSidecarConfig?.();
  if (sidecarConfig) {
    return {
      baseUrl: normalizeBaseUrl(sidecarConfig.baseUrl),
    };
  }

  return {
    baseUrl: sessionStorage.getItem("agent-pet.base-url") || DEFAULT_BASE_URL,
  };
}

export function saveConnectionSettings(settings: ConnectionSettings): void {
  sessionStorage.setItem("agent-pet.base-url", normalizeBaseUrl(settings.baseUrl));
}

export function normalizeBaseUrl(baseUrl: string): string {
  return (baseUrl.trim() || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

export class ApiClient {
  private baseUrl: string;

  constructor(settings: ConnectionSettings) {
    this.baseUrl = normalizeBaseUrl(settings.baseUrl);
  }

  setSettings(settings: ConnectionSettings): void {
    this.baseUrl = normalizeBaseUrl(settings.baseUrl);
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  async health(signal?: AbortSignal): Promise<HealthResponse> {
    return this.request<HealthResponse>("/api/health", { signal, auth: false });
  }

  async get<T>(path: string, signal?: AbortSignal): Promise<T> {
    return this.request<T>(path, { signal });
  }

  async post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    });
  }

  async postWithHeaders<T>(
    path: string,
    body: unknown,
    headers: Record<string, string>,
    signal?: AbortSignal,
  ): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      body: JSON.stringify(body),
      headers,
      signal,
    });
  }

  async put<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    return this.request<T>(path, {
      method: "PUT",
      body: JSON.stringify(body),
      signal,
    });
  }

  async patch<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    return this.request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(body),
      signal,
    });
  }

  async request<T>(
    path: string,
    init: RequestInit & { auth?: boolean } = {},
  ): Promise<T> {
    const headers = new Headers(init.headers);

    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    headers.set("Accept", "application/json");

    const bridge = window.agentDesktop?.apiRequest;
    if (bridge) {
      // Electron IPC 无法序列化 AbortSignal：渲染进程侧用 race 实现中止语义，
      // 中止后丢弃仍在主进程执行的请求结果。
      const bridgePromise = bridge(path, {
        method: init.method,
        headers: Object.fromEntries(headers.entries()),
        body: typeof init.body === "string" ? init.body : undefined,
        auth: init.auth,
      });
      if (!init.signal) {
        return parseDesktopApiResponse<T>(await bridgePromise);
      }
      const signal = init.signal;
      return await new Promise<T>((resolve, reject) => {
        const onAbort = () => reject(new DOMException("请求已取消", "AbortError"));
        // 先给 bridgePromise 挂上处理:signal 已经 aborted 时下面会立刻返回,
        // 那时若还没有处理器,主进程侧失败就成了未处理的 rejection(而且无人看见)。
        bridgePromise.then(
          (response) => {
            signal.removeEventListener("abort", onAbort);
            resolve(parseDesktopApiResponse<T>(response));
          },
          (error) => {
            signal.removeEventListener("abort", onAbort);
            reject(error);
          },
        );
        if (signal.aborted) {
          onAbort();
          return;
        }
        signal.addEventListener("abort", onAbort, { once: true });
      });
    }

    const response = await fetch(this.toUrl(path), {
      ...init,
      headers,
    });

    if (!response.ok) {
      throw await toApiError(response);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json() as Promise<T>;
  }

  toUrl(pathOrUrl: string): string {
    if (/^https?:\/\//i.test(pathOrUrl)) {
      return pathOrUrl;
    }
    return `${this.baseUrl}${pathOrUrl.startsWith("/") ? "" : "/"}${pathOrUrl}`;
  }
}

function parseDesktopApiResponse<T>(response: DesktopApiResponse): T {
  if (response.status < 200 || response.status >= 300) {
    throw toApiErrorFromText(response.status, response.statusText, response.body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return JSON.parse(response.body) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  const text = await response.text();
  return toApiErrorFromText(response.status, response.statusText, text);
}

function toApiErrorFromText(status: number, statusText: string, text: string): ApiError {
  let body: ApiErrorBody | undefined;

  try {
    body = JSON.parse(text) as ApiErrorBody;
  } catch {
    body = undefined;
  }

  const message = body?.error?.message || `${status} ${statusText}`;
  return new ApiError(message, status, body);
}
