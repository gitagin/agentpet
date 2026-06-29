import { describe, expect, it } from "vitest";

import { buildPetInputIntentMessage, normalizePetInputMode, petInputModes } from "./petInputModes";

describe("pet input modes", () => {
  it("normalizes only supported pet input modes", () => {
    expect(petInputModes.map((mode) => mode.id)).toEqual(["chat", "note", "task", "wiki", "review"]);
    expect(petInputModes.map((mode) => mode.label)).toEqual(["陪伴", "记住", "提醒", "整理资料", "回顾今天"]);
    expect(petInputModes.map((mode) => mode.ariaLabel)).toEqual([
      "切换到陪伴",
      "切换到记住",
      "切换到提醒",
      "切换到整理资料",
      "切换到回顾今天",
    ]);
    expect(petInputModes.map((mode) => mode.placeholder)).toEqual([
      "和我说说现在发生的事...",
      "告诉我一件希望以后还能接上的事...",
      "要我在什么时候提醒你...",
      "粘贴想整理的资料或想法...",
      "留空也可以直接回顾今天...",
    ]);
    petInputModes.forEach((mode) => {
      expect(`${mode.label} ${mode.ariaLabel} ${mode.placeholder}`).not.toMatch(/Wiki|Markdown|Agent|Live2D|API|Vault|token|Bearer|任务/);
    });
    expect(normalizePetInputMode("task")).toBe("task");
    expect(normalizePetInputMode("unknown")).toBeNull();
    expect(normalizePetInputMode(null)).toBeNull();
  });

  it("keeps chat as raw text and turns focused modes into explicit intent prompts", () => {
    expect(buildPetInputIntentMessage("chat", "  继续聊  ")).toBe("继续聊");
    expect(buildPetInputIntentMessage("note", "  我偏好简洁可追踪的结果  ")).toContain(
      "记住：我偏好简洁可追踪的结果",
    );
    expect(buildPetInputIntentMessage("note", "我偏好简洁可追踪的结果")).toContain("现有记忆策略");
    expect(buildPetInputIntentMessage("task", "明天 10 点检查验收脚本")).toContain("提醒：明天 10 点检查验收脚本");
    expect(buildPetInputIntentMessage("task", "明天 10 点检查验收脚本")).toContain("需要确认的内容先进入确认流程");
    expect(buildPetInputIntentMessage("wiki", "把 TASK-05 决策沉淀到资料页")).toContain(
      "整理资料到资料页：把 TASK-05 决策沉淀到资料页",
    );
    expect(buildPetInputIntentMessage("wiki", "把 TASK-05 决策沉淀到资料页")).toContain("高风险写入仍需确认");
    expect(buildPetInputIntentMessage("wiki", "把 TASK-05 决策沉淀到资料页")).toContain("用户可见回复请用“资料”“资料页”表达");
  });

  it("allows an empty today review request without bypassing retrieval policy", () => {
    const message = buildPetInputIntentMessage("review", "  ");

    expect(message).toContain("回顾今天：请根据今天的本地记录做一次简短回顾。");
    expect(message).toContain("优先检索本地聊天日记、长期记忆、任务和资料整理内容");
    expect(message).toContain("用户可见回复请使用普通中文，不要使用工程词");
  });
});
