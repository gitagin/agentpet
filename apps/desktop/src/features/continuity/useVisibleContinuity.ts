import { useCallback, useEffect, useState } from "react";
import { describeError } from "../../services/apiErrorMessages";
import type { DesktopApi } from "../../services/desktopApi";
import type { VisibleContinuityLoadStatus, VisibleContinuitySnapshotResponse } from "./visibleContinuityTypes";

type VisibleContinuityApi = Pick<DesktopApi, "getVisibleContinuitySnapshot">;

type UseVisibleContinuityOptions = {
  api: VisibleContinuityApi;
  enabled?: boolean;
  autoLoad?: boolean;
};

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
    try {
      const response = await api.getVisibleContinuitySnapshot(signal);
      setSnapshot(response);
      setStatus("success");
      return response;
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") {
        return null;
      }
      setStatus("error");
      setError(describeError(cause, "连续性快照加载失败"));
      return null;
    }
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
