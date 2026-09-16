import { useCallback, useEffect, useRef, useState } from "react";
import { describeError, isSidecarStartingError } from "../../services/apiErrorMessages";
import type { DesktopApi } from "../../services/desktopApi";
import type { VisibleContinuityLoadStatus, VisibleContinuitySnapshotResponse } from "./visibleContinuityTypes";

type VisibleContinuityApi = Pick<DesktopApi, "getVisibleContinuitySnapshot">;

type UseVisibleContinuityOptions = {
  api: VisibleContinuityApi;
  enabled?: boolean;
  autoLoad?: boolean;
  /** Bump to refetch: the snapshot is derived state that other panels can invalidate. */
  refreshKey?: number;
};

const SIDECAR_STARTING_RETRY_DELAY_MS = 500;
const SIDECAR_STARTING_RETRY_COUNT = 4;
export const VISIBLE_CONTINUITY_REQUEST_TIMEOUT_MS = 8000;
const VISIBLE_CONTINUITY_TIMEOUT_MESSAGE = "连续性快照加载超时，请刷新重试。";

export function useVisibleContinuity({
  api,
  enabled = true,
  autoLoad = true,
  refreshKey = 0,
}: UseVisibleContinuityOptions) {
  const [snapshot, setSnapshot] = useState<VisibleContinuitySnapshotResponse | null>(null);
  const [status, setStatus] = useState<VisibleContinuityLoadStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!enabled) {
      return null;
    }
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const isCurrentRequest = () => requestIdRef.current === requestId && !signal?.aborted;
    setStatus("loading");
    setError(null);

    for (let attempt = 0; attempt <= SIDECAR_STARTING_RETRY_COUNT; attempt += 1) {
      try {
        const response = await withSnapshotTimeout(api.getVisibleContinuitySnapshot(signal), signal);
        if (!isCurrentRequest()) {
          return null;
        }
        setSnapshot(response);
        setStatus("success");
        return response;
      } catch (cause) {
        if (isAbortError(cause) || signal?.aborted) {
          return null;
        }
        if (!isCurrentRequest()) {
          return null;
        }
        if (isSidecarStartingError(cause) && attempt < SIDECAR_STARTING_RETRY_COUNT) {
          const canRetry = await waitForRetry(SIDECAR_STARTING_RETRY_DELAY_MS, signal);
          if (!canRetry) {
            return null;
          }
          continue;
        }
        setStatus("error");
        setError(describeError(cause, "连续性快照加载失败"));
        return null;
      }
    }
    return null;
  }, [api, enabled]);

  useEffect(() => {
    if (!enabled || !autoLoad) {
      return;
    }
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [autoLoad, enabled, refresh]);

  // 外部失效:宿主(例如撤销未完话题的页面)递增值表示"这份派生快照过期了"。
  const previousRefreshKeyRef = useRef(refreshKey);
  useEffect(() => {
    if (previousRefreshKeyRef.current === refreshKey) {
      return;
    }
    previousRefreshKeyRef.current = refreshKey;
    void refresh();
  }, [refresh, refreshKey]);

  return {
    error,
    refresh,
    snapshot,
    status,
  };
}

function isAbortError(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}

function withSnapshotTimeout<T>(request: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) {
    return Promise.reject(new DOMException("操作已取消。", "AbortError"));
  }

  return new Promise((resolve, reject) => {
    let timeout = 0;
    const cleanup = () => {
      window.clearTimeout(timeout);
      signal?.removeEventListener("abort", onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(new DOMException("操作已取消。", "AbortError"));
    };
    timeout = window.setTimeout(() => {
      cleanup();
      reject(new Error(VISIBLE_CONTINUITY_TIMEOUT_MESSAGE));
    }, VISIBLE_CONTINUITY_REQUEST_TIMEOUT_MS);

    signal?.addEventListener("abort", onAbort, { once: true });
    request.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (cause) => {
        cleanup();
        reject(cause);
      },
    );
  });
}

function waitForRetry(ms: number, signal?: AbortSignal): Promise<boolean> {
  if (signal?.aborted) {
    return Promise.resolve(false);
  }

  return new Promise((resolve) => {
    const timeout = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve(true);
    }, ms);
    const onAbort = () => {
      window.clearTimeout(timeout);
      resolve(false);
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
