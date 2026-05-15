import type { ApiErrorBody, ConnectionSettings, HealthResponse } from "../types";

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
      sessionToken: sidecarConfig.sessionToken.trim(),
    };
  }

  return {
    baseUrl: sessionStorage.getItem("agent-pet.base-url") || DEFAULT_BASE_URL,
    sessionToken: sessionStorage.getItem("agent-pet.session-token") || "",
  };
}

export function saveConnectionSettings(settings: ConnectionSettings): void {
  sessionStorage.setItem("agent-pet.base-url", normalizeBaseUrl(settings.baseUrl));
  sessionStorage.setItem("agent-pet.session-token", settings.sessionToken.trim());
}

export function normalizeBaseUrl(baseUrl: string): string {
  return (baseUrl.trim() || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

export class ApiClient {
  private baseUrl: string;
  private sessionToken: string;

  constructor(settings: ConnectionSettings) {
    this.baseUrl = normalizeBaseUrl(settings.baseUrl);
    this.sessionToken = settings.sessionToken.trim();
  }

  setSettings(settings: ConnectionSettings): void {
    this.baseUrl = normalizeBaseUrl(settings.baseUrl);
    this.sessionToken = settings.sessionToken.trim();
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  getSessionToken(): string {
    return this.sessionToken;
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
    const auth = init.auth !== false;
    const headers = new Headers(init.headers);

    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    headers.set("Accept", "application/json");

    if (auth) {
      if (!this.sessionToken) {
        throw new ApiError("该请求需要会话令牌。", 401);
      }
      headers.set("Authorization", `Bearer ${this.sessionToken}`);
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

async function toApiError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | undefined;

  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    body = undefined;
  }

  const message = body?.error?.message || `${response.status} ${response.statusText}`;
  return new ApiError(message, response.status, body);
}
