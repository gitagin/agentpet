import { describe, expect, it } from "vitest";

import { navigationHashForTab, primaryNavigationTabs } from "./navigation";

describe("primary navigation", () => {
  it("keeps every pet shortcut route reachable from the primary navigation", () => {
    expect(primaryNavigationTabs).toEqual(["今日", "陪伴", "记忆", "任务", "知识", "设置"]);
    expect(primaryNavigationTabs).not.toEqual(expect.arrayContaining(["知识整理", "工作流", "报告"]));
    primaryNavigationTabs.forEach((tab) => {
      expect(tab).not.toMatch(/Wiki|Markdown|Agent|Live2D|API|Vault|token|Bearer/);
    });
  });

  it("routes primary tabs to the user-facing companionship loop", () => {
    expect(navigationHashForTab("今日")).toBe("stage");
    expect(navigationHashForTab("陪伴")).toBe("chat");
    expect(navigationHashForTab("记忆")).toBe("memory");
    expect(navigationHashForTab("任务")).toBe("agent");
    expect(navigationHashForTab("知识")).toBe("world");
    expect(navigationHashForTab("设置")).toBe("settings");
  });
});
