import { useEffect, useRef } from "react";
import type { HabitLoopTriggerResponse, ProactiveTriggerFrequency } from "../../types";
import type { DesktopApi } from "../../services/desktopApi";

export const habitLoopPollIntervalMsByFrequency: Record<ProactiveTriggerFrequency, number> = {
  off: 0,
  low: 30 * 60 * 1000,
  normal: 15 * 60 * 1000,
  high: 8 * 60 * 1000,
};

type UseProactiveHabitLoopOptions = {
  api: Pick<DesktopApi, "triggerHabitLoop">;
  enabled: boolean;
  frequency: ProactiveTriggerFrequency;
  blocked: boolean;
  onTrigger: (response: HabitLoopTriggerResponse) => void;
};

function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function useProactiveHabitLoop({
  api,
  enabled,
  frequency,
  blocked,
  onTrigger,
}: UseProactiveHabitLoopOptions) {
  const callbacks = useRef({ blocked, onTrigger });
  const inFlight = useRef(false);

  callbacks.current = { blocked, onTrigger };

  useEffect(() => {
    const intervalMs = habitLoopPollIntervalMsByFrequency[frequency] || 0;
    if (!enabled || frequency === "off" || intervalMs <= 0) {
      return undefined;
    }

    let disposed = false;
    const maybeTrigger = async () => {
      if (disposed || inFlight.current || callbacks.current.blocked) {
        return;
      }
      inFlight.current = true;
      try {
        const response = await api.triggerHabitLoop({ timezone: localTimezone() });
        if (
          !disposed &&
          response.should_trigger &&
          response.candidate &&
          !callbacks.current.blocked
        ) {
          callbacks.current.onTrigger(response);
        }
      } catch {
        // The proactive loop is opportunistic; a transient sidecar/API failure should not surface as an unhandled rejection.
      } finally {
        inFlight.current = false;
      }
    };

    void maybeTrigger();
    const intervalId = window.setInterval(() => {
      void maybeTrigger();
    }, intervalMs);
    return () => {
      disposed = true;
      window.clearInterval(intervalId);
    };
  }, [api, enabled, frequency]);
}
