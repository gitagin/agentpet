import { describe, expect, it } from "vitest";

import { navigationHashForTab, primaryNavigationTabs } from "./navigation";

describe("primary navigation", () => {
  it("keeps only the daily companion loop in primary navigation", () => {
    expect(primaryNavigationTabs).toEqual(["今日", "聊天", "记忆", "设置"]);
    expect(primaryNavigationTabs).not.toEqual(expect.arrayContaining(["成长", "任务", "知识", "知识整理", "工作流", "报告"]));
    primaryNavigationTabs.forEach((tab) => {
      expect(tab).not.toMatch(/Wiki|Markdown|Agent|Live2D|API|Vault|token|Bearer/);
    });
  });

  it("routes primary tabs to the user-facing companionship loop", () => {
    expect(navigationHashForTab("今日")).toBe("stage");
    expect(navigationHashForTab("聊天")).toBe("chat");
    expect(navigationHashForTab("记忆")).toBe("memory");
    expect(navigationHashForTab("设置")).toBe("settings");
  });
});
