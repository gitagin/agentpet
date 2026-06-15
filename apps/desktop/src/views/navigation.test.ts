import { describe, expect, it } from "vitest";

import { navigationHashForTab, primaryNavigationTabs } from "./navigation";

describe("primary navigation", () => {
  it("keeps task workspace out of the primary navigation", () => {
    expect(primaryNavigationTabs).toEqual(["今日", "陪伴", "记忆", "设置"]);
    expect(primaryNavigationTabs).not.toContain("任务");
    expect(primaryNavigationTabs).not.toEqual(expect.arrayContaining(["知识整理", "工作流", "报告"]));
    primaryNavigationTabs.forEach((tab) => {
      expect(tab).not.toMatch(/Wiki|Markdown|Agent|Live2D|API|Vault|token|Bearer/);
    });
  });

  it("routes primary tabs to the user-facing companionship loop", () => {
    expect(navigationHashForTab("今日")).toBe("stage");
    expect(navigationHashForTab("陪伴")).toBe("chat");
    expect(navigationHashForTab("记忆")).toBe("memory");
    expect(navigationHashForTab("设置")).toBe("settings");
  });
});
