import { describe, expect, it } from "vitest";
import type { PetStageView } from "./petStageState";
import { getSpritePetAnimationKey, getSpritePetAtlasRowKey, resolveSpritePetAction } from "./spritePetState";

const idleStage: PetStageView = {
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

  it("maps project states onto the Agent Pet Neko atlas rows", () => {
    expect(getSpritePetAtlasRowKey("idle")).toBe("idle");
    expect(getSpritePetAtlasRowKey("chat_talk")).toBe("waving");
    expect(getSpritePetAtlasRowKey("chat_think")).toBe("thinking");
    expect(getSpritePetAtlasRowKey("pet_drag_right")).toBe("running-right");
    expect(getSpritePetAtlasRowKey("pet_drag_left")).toBe("running-left");
    expect(getSpritePetAtlasRowKey("task_create")).toBe("working");
    expect(getSpritePetAtlasRowKey("system_error")).toBe("failed");
    expect(getSpritePetAtlasRowKey("system_offline")).toBe("sleeping");
    expect(getSpritePetAtlasRowKey("memory_confirm_needed")).toBe("done");
    expect(getSpritePetAtlasRowKey("pet_review")).toBe("working");
  });

  it("maps project states onto the Agent Pet Neko animation rows", () => {
    expect(getSpritePetAnimationKey("idle")).toBe("idle");
    expect(getSpritePetAnimationKey("chat_talk")).toBe("waving");
    expect(getSpritePetAnimationKey("chat_think")).toBe("thinking");
    expect(getSpritePetAnimationKey("pet_drag_right")).toBe("running-right");
    expect(getSpritePetAnimationKey("pet_drag_left")).toBe("running-left");
    expect(getSpritePetAnimationKey("task_create")).toBe("working");
    expect(getSpritePetAnimationKey("task_complete")).toBe("done");
    expect(getSpritePetAnimationKey("system_error")).toBe("failed");
    expect(getSpritePetAnimationKey("system_offline")).toBe("sleeping");
    expect(getSpritePetAnimationKey("memory_confirm_needed")).toBe("done");
    expect(getSpritePetAnimationKey("pet_review")).toBe("working");
  });
});
