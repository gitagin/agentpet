import { describe, expect, it } from "vitest";
import type { Live2DStageView } from "../../components/Live2DStage";
import { getSpritePetAtlasRowKey, resolveSpritePetAction } from "./spritePetState";

const idleStage: Live2DStageView = {
  state: "idle",
  label: "idle",
  mood: "idle",
  message: "idle",
  hint: "idle",
};

function resolve(overrides: Partial<Parameters<typeof resolveSpritePetAction>[0]> = {}) {
  return resolveSpritePetAction({
    stage: idleStage,
    connected: true,
    streaming: false,
    speaking: false,
    inputVisible: false,
    shortcutVisible: false,
    dragging: false,
    dragDirection: "none",
    actionKeyOverride: null,
    ...overrides,
  });
}

describe("resolveSpritePetAction", () => {
  it("uses the talking state while TTS is speaking", () => {
    expect(resolve({ speaking: true }).key).toBe("chat_talk");
  });

  it("uses directional drag states before other state hints", () => {
    expect(resolve({ dragging: true, dragDirection: "left", speaking: true }).key).toBe("pet_drag_left");
    expect(resolve({ dragging: true, dragDirection: "right" }).key).toBe("pet_drag_right");
  });

  it("accepts project action overrides for memory and wiki flows", () => {
    expect(resolve({ actionKeyOverride: "memory_save_diary" }).key).toBe("memory_save_diary");
    expect(resolve({ actionKeyOverride: "wiki_archive" }).key).toBe("wiki_archive");
  });

  it("falls back to project stage state when no direct override is active", () => {
    expect(resolve({ stage: { ...idleStage, state: "memory" } }).key).toBe("memory_search");
    expect(resolve({ connected: false }).key).toBe("system_offline");
  });

  it("maps project states onto the Codex-style atlas rows", () => {
    expect(getSpritePetAtlasRowKey("idle")).toBe("idle");
    expect(getSpritePetAtlasRowKey("chat_talk")).toBe("idle");
    expect(getSpritePetAtlasRowKey("chat_think")).toBe("running");
    expect(getSpritePetAtlasRowKey("pet_drag_right")).toBe("running-right");
    expect(getSpritePetAtlasRowKey("pet_drag_left")).toBe("running-left");
    expect(getSpritePetAtlasRowKey("task_create")).toBe("jumping");
    expect(getSpritePetAtlasRowKey("system_error")).toBe("failed");
    expect(getSpritePetAtlasRowKey("memory_confirm_needed")).toBe("waiting");
    expect(getSpritePetAtlasRowKey("pet_review")).toBe("review");
  });
});
