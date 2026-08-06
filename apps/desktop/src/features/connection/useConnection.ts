import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ConnectionSettings, DesktopSidecarStatus, HealthResponse, SettingsStatusResponse } from "../../types";
import { ApiClient, ApiError, loadConnectionSettings, saveConnectionSettings } from "../../services/apiClient";
import { businessAuthMismatchMessage, describeBusinessAuthFailure, describeError } from "../../services/apiErrorMessages";
import { DesktopApi } from "../../services/desktopApi";
import { getSidecarActionMessage, type BusinessAuthStatus } from "./connectionStatus";

type Notice = {
  tone: "info" | "error" | "success";
  message: string;
};

type UseConnectionOptions = {
  onNotice: (notice: Notice | null) => void;
};

export function useConnection({ onNotice }: UseConnectionOptions) {
  const [settings, setSettings] = useState<ConnectionSettings>(() => loadConnectionSettings());
  const [sidecarStatus, setSidecarStatus] = useState<DesktopSidecarStatus | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [loadingSettingsStatus, setLoadingSettingsStatus] = useState(false);
  const [settingsStatus, setSettingsStatus] = useState<SettingsStatusResponse | null>(null);
  const [businessAuthStatus, setBusinessAuthStatus] = useState<BusinessAuthStatus>("unknown");
  const [businessAuthMessage, setBusinessAuthMessage] = useState("尚未检查业务接口鉴权。");
  const readyHealthRefreshKey = useRef<string | null>(null);
  const callbacks = useRef({ onNotice });

  useEffect(() => {
    callbacks.current = { onNotice };
  }, [onNotice]);

  const client = useMemo(() => new ApiClient(settings), [settings]);
  const api = useMemo(() => new DesktopApi(client), [client]);

  const markBusinessAuthFailure = useCallback((error: unknown) => {
    const failure = describeBusinessAuthFailure(error);
    setBusinessAuthStatus(failure.status);
    setBusinessAuthMessage(failure.message);
  }, []);

  const setBusinessAuthReady = useCallback((message = "业务接口鉴权可用。") => {
    setBusinessAuthStatus("ready");
    setBusinessAuthMessage(message);
  }, []);

  const checkBusinessAccess = useCallback(async (options: { silent?: boolean; signal?: AbortSignal } = {}): Promise<boolean> => {
    setBusinessAuthStatus("checking");
    setBusinessAuthMessage("正在检查业务接口鉴权。");
    try {
      const response = await api.getSettingsStatus(options.signal);
      setSettingsStatus(response);
      setBusinessAuthReady();
      return true;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setBusinessAuthStatus("unknown");
        setBusinessAuthMessage("业务接口鉴权检查已取消。");
        return false;
      }
      markBusinessAuthFailure(error);
      if (error instanceof ApiError && error.status === 401) {
        callbacks.current.onNotice({ tone: "error", message: businessAuthMismatchMessage() });
      } else if (!options.silent) {
        callbacks.current.onNotice({ tone: "error", message: describeError(error, "业务接口鉴权检查失败") });
      }
      return false;
    }
  }, [api, markBusinessAuthFailure, setBusinessAuthReady]);

  const checkHealth = useCallback(async (options: { silent?: boolean } = {}) => {
    setCheckingHealth(true);
    if (!options.silent) {
      callbacks.current.onNotice(null);
    }
    try {
      const response = await client.health();
      setHealth(response);
      const businessReady = await checkBusinessAccess({ silent: options.silent });
      if (!options.silent && businessReady) {
        callbacks.current.onNotice({ tone: "success", message: "本机服务健康检查和业务鉴权均通过。" });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (options.silent) {
        return;
      }
      setBusinessAuthStatus("unknown");
      setBusinessAuthMessage("本机服务健康检查失败，尚未检查业务接口鉴权。");
      callbacks.current.onNotice({ tone: "error", message: describeError(error, "健康检查失败") });
    } finally {
      setCheckingHealth(false);
    }
  }, [checkBusinessAccess, client]);

  const loadSettingsStatus = useCallback(async (options: { silent?: boolean; signal?: AbortSignal } = {}) => {
    setLoadingSettingsStatus(true);
    if (!options.silent) {
      callbacks.current.onNotice(null);
    }
    try {
      const response = await api.getSettingsStatus(options.signal);
      setSettingsStatus(response);
      setBusinessAuthReady();
      if (!options.silent) {
        callbacks.current.onNotice({ tone: "success", message: "设置状态已刷新。" });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      markBusinessAuthFailure(error);
      if (!options.silent) {
        callbacks.current.onNotice({ tone: "error", message: describeError(error, "设置状态读取失败") });
      }
    } finally {
      setLoadingSettingsStatus(false);
    }
  }, [api, markBusinessAuthFailure, setBusinessAuthReady]);

  const persistSettings = useCallback((next: ConnectionSettings) => {
    const trimmed = {
      baseUrl: next.baseUrl,
    };
    saveConnectionSettings(trimmed);
    setSettings(trimmed);
    callbacks.current.onNotice({ tone: "success", message: "本次应用会话的连接设置已保存。" });
  }, []);

  useEffect(() => {
    let cancelled = false;
    void window.agentDesktop?.getSidecarStatus?.().then((status) => {
      if (!cancelled) {
        setSidecarStatus(status);
      }
    });
    const unsubscribe = window.agentDesktop?.onSidecarStatusChanged?.((status) => {
      setSidecarStatus(status);
    });
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, []);

  useEffect(() => {
    if (!sidecarStatus?.error) {
      return;
    }

    callbacks.current.onNotice({
      // degraded（降级复用外部后端）沿用旧 ready+复用 提示的 info 语气：
      // 有可用连接，只是令牌未校验，具体动作指引在消息正文里。
      tone: sidecarStatus.state === "ready" || sidecarStatus.state === "degraded" ? "info" : "error",
      message: getSidecarActionMessage(sidecarStatus),
    });
  }, [sidecarStatus]);

  useEffect(() => {
    if (sidecarStatus?.health) {
      setHealth(sidecarStatus.health);
    }

    if (sidecarStatus?.state !== "ready" && sidecarStatus?.state !== "degraded") {
      return;
    }

    const refreshKey = sidecarStatus.updatedAt || `${sidecarStatus.baseUrl}:${sidecarStatus.port}`;
    if (readyHealthRefreshKey.current === refreshKey) {
      return;
    }

    readyHealthRefreshKey.current = refreshKey;
    if (sidecarStatus.baseUrl && sidecarStatus.baseUrl !== settings.baseUrl) {
      const next = { ...settings, baseUrl: sidecarStatus.baseUrl };
      saveConnectionSettings(next);
      setSettings(next);
    }
    void checkHealth({ silent: true });
  }, [checkHealth, settings, sidecarStatus]);

  return {
    api,
    businessAuthMessage,
    businessAuthStatus,
    checkHealth,
    checkingHealth,
    client,
    health,
    loadSettingsStatus,
    loadingSettingsStatus,
    persistSettings,
    setBusinessAuthReady,
    setSettings,
    settings,
    settingsStatus,
    sidecarStatus,
  };
}
