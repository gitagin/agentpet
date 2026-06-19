import { useCallback, useEffect, useState } from "react";
import { describeError, isSidecarStartingError } from "../../services/apiErrorMessages";
import type { DesktopApi } from "../../services/desktopApi";
import type { VisibleContinuityLoadStatus, VisibleContinuitySnapshotResponse } from "./visibleContinuityTypes";

type VisibleContinuityApi = Pick<DesktopApi, "getVisibleContinuitySnapshot">;

type UseVisibleContinuityOptions = {
  api: VisibleContinuityApi;
  enabled?: boolean;
  autoLoad?: boolean;
};

const SIDECAR_STARTING_RETRY_DELAY_MS = 500;
const SIDECAR_STARTING_RETRY_COUNT = 4;

export function useVisibleContinuity({
  api,
  enabled = true,
  autoLoad = true,
}: UseVisibleContinuityOptions) {
  const [snapshot, setSnapshot] = useState<VisibleContinuitySnapshotResponse | null>(null);
  const [status, setStatus] = useState<VisibleContinuityLoadStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!enabled) {
      return null;
    }
    setStatus("loading");
    setError(null);

    for (let attempt = 0; attempt <= SIDECAR_STARTING_RETRY_COUNT; attempt += 1) {
      try {
        const response = await api.getVisibleContinuitySnapshot(signal);
        setSnapshot(response);
        setStatus("success");
        return response;
      } catch (cause) {
        if (isAbortError(cause) || signal?.aborted) {
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
