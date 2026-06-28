import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DesktopApi } from "../../services/desktopApi";
import type { HabitLoopTriggerResponse, ProactiveTriggerFrequency } from "../../types";
import { habitLoopPollIntervalMsByFrequency, useProactiveHabitLoop } from "./useProactiveHabitLoop";

function triggerResponse(overrides: Partial<HabitLoopTriggerResponse> = {}): HabitLoopTriggerResponse {
  return {
    should_trigger: true,
    reason: "triggered",
    frequency: "low",
    daily_limit: 1,
    daily_count: 1,
    cooldown_minutes: 480,
    next_eligible_at: "2026-06-21T20:00:00Z",
    quiet_hours: "22:00-08:00",
    action_id: "trigger-1",
    candidate: {
      trigger_id: "trigger-1",
      content_type: "task_followup",
      title: "Follow up on an unfinished task",
      message: "Review acceptance notes is still open.",
      suggested_prompt: "Help me break this task into the next step: Review acceptance notes",
      source_count: 1,
      sources: ["tasks:habit-task-1"],
    },
    ...overrides,
  };
}

function renderHabitLoop({
  enabled = true,
  frequency = "low",
  blocked = false,
  response = triggerResponse(),
}: {
  enabled?: boolean;
  frequency?: ProactiveTriggerFrequency;
  blocked?: boolean;
  response?: HabitLoopTriggerResponse;
} = {}) {
  const triggerHabitLoop = vi.fn().mockResolvedValue(response);
  const onTrigger = vi.fn();
  const api = { triggerHabitLoop } as unknown as Pick<DesktopApi, "triggerHabitLoop">;
  const hook = renderHook(
    (props: { blocked: boolean; frequency: ProactiveTriggerFrequency }) =>
      useProactiveHabitLoop({
        api,
        enabled,
        frequency: props.frequency,
        blocked: props.blocked,
        onTrigger,
      }),
    { initialProps: { blocked, frequency } },
  );
  return { ...hook, triggerHabitLoop, onTrigger };
}

describe("useProactiveHabitLoop", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("requests a trigger immediately and surfaces the candidate", async () => {
    const { triggerHabitLoop, onTrigger } = renderHabitLoop();

    await act(async () => {
      await Promise.resolve();
    });

    expect(triggerHabitLoop).toHaveBeenCalledWith({ timezone: expect.any(String) });
    expect(onTrigger).toHaveBeenCalledWith(expect.objectContaining({ should_trigger: true }));
  });

  it("does not poll while blocked or disabled", async () => {
    const blocked = renderHabitLoop({ blocked: true });
    const off = renderHabitLoop({ frequency: "off" });

    await act(async () => {
      vi.advanceTimersByTime(habitLoopPollIntervalMsByFrequency.low);
      await Promise.resolve();
    });

    expect(blocked.triggerHabitLoop).not.toHaveBeenCalled();
    expect(off.triggerHabitLoop).not.toHaveBeenCalled();
  });

  it("uses the selected frequency interval", async () => {
    const { triggerHabitLoop } = renderHabitLoop({ frequency: "high" });

    await act(async () => {
      await Promise.resolve();
    });
    expect(triggerHabitLoop).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(habitLoopPollIntervalMsByFrequency.high);
      await Promise.resolve();
    });

    expect(triggerHabitLoop).toHaveBeenCalledTimes(2);
  });

  it("keeps polling after a transient trigger failure", async () => {
    const triggerHabitLoop = vi
      .fn()
      .mockRejectedValueOnce(new Error("sidecar unavailable"))
      .mockResolvedValue(triggerResponse());
    const onTrigger = vi.fn();
    const api = { triggerHabitLoop } as unknown as Pick<DesktopApi, "triggerHabitLoop">;

    renderHook(() =>
      useProactiveHabitLoop({
        api,
        enabled: true,
        frequency: "high",
        blocked: false,
        onTrigger,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(triggerHabitLoop).toHaveBeenCalledTimes(1);
    expect(onTrigger).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(habitLoopPollIntervalMsByFrequency.high);
      await Promise.resolve();
    });

    expect(triggerHabitLoop).toHaveBeenCalledTimes(2);
    expect(onTrigger).toHaveBeenCalledWith(expect.objectContaining({ should_trigger: true }));
  });
});
