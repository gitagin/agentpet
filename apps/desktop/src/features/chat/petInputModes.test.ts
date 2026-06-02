import { describe, expect, it } from "vitest";

import { buildPetInputIntentMessage, normalizePetInputMode, petInputModes } from "./petInputModes";

describe("pet input modes", () => {
  it("normalizes only supported pet input modes", () => {
    expect(petInputModes.map((mode) => mode.id)).toEqual(["chat", "note", "task", "wiki", "review"]);
    expect(normalizePetInputMode("task")).toBe("task");
    expect(normalizePetInputMode("unknown")).toBeNull();
    expect(normalizePetInputMode(null)).toBeNull();
  });

  it("keeps chat as raw text and turns focused modes into explicit intent prompts", () => {
    expect(buildPetInputIntentMessage("chat", "  继续聊  ")).toBe("继续聊");
    expect(buildPetInputIntentMessage("note", "  我偏好简洁可追踪的结果  ")).toContain(
      "记一个：我偏好简洁可追踪的结果",
    );
    expect(buildPetInputIntentMessage("note", "我偏好简洁可追踪的结果")).toContain("现有记忆策略");
    expect(buildPetInputIntentMessage("task", "明天 10 点检查验收脚本")).toContain("新任务：明天 10 点检查验收脚本");
    expect(buildPetInputIntentMessage("task", "明天 10 点检查验收脚本")).toContain("需要确认的内容先进入确认流程");
    expect(buildPetInputIntentMessage("wiki", "把 TASK-05 决策沉淀到 Wiki")).toContain(
      "整理成 Wiki：把 TASK-05 决策沉淀到 Wiki",
    );
    expect(buildPetInputIntentMessage("wiki", "把 TASK-05 决策沉淀到 Wiki")).toContain("高风险写入仍需确认");
  });

  it("allows an empty today review request without bypassing retrieval policy", () => {
    const message = buildPetInputIntentMessage("review", "  ");

    expect(message).toContain("今日复盘：请根据今天的本地记录做一次简短复盘。");
    expect(message).toContain("优先检索本地聊天日记、长期记忆、任务和 Wiki");
  });
});
