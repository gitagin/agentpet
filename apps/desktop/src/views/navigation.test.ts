import { describe, expect, it } from "vitest";

import { navigationHashForTab, primaryNavigationTabs } from "./navigation";

describe("primary navigation", () => {
  it("keeps the screenshot-style companion navigation visible", () => {
    expect(primaryNavigationTabs).toEqual(["首页", "对话", "记忆", "计划", "设置"]);
    expect(primaryNavigationTabs).not.toContain("资料");
    primaryNavigationTabs.forEach((tab) => {
      expect(tab).not.toMatch(/Wiki|Markdown|Agent|Live2D|API|Vault|token|Bearer/);
    });
  });

  it("routes primary tabs to existing user-facing windows", () => {
    expect(navigationHashForTab("首页")).toBe("stage");
    expect(navigationHashForTab("对话")).toBe("chat");
    expect(navigationHashForTab("记忆")).toBe("memory");
    expect(navigationHashForTab("计划")).toBe("agent");
    expect(navigationHashForTab("设置")).toBe("settings");
  });
});
