import type { DesktopFeatureWindowMode } from "../types";

export const primaryNavigationTabs = ["首页", "对话", "记忆", "计划", "工具", "设置"] as const;

export type PrimaryNavigationTab = (typeof primaryNavigationTabs)[number];

const routeByTab: Record<PrimaryNavigationTab, "stage" | "agent" | DesktopFeatureWindowMode> = {
  首页: "stage",
  对话: "chat",
  记忆: "memory",
  计划: "agent",
  工具: "world",
  设置: "settings",
};

export function navigationHashForTab(tab: PrimaryNavigationTab): string {
  return routeByTab[tab];
}

export function openPrimaryNavigationTab(tab: PrimaryNavigationTab) {
  window.location.hash = navigationHashForTab(tab);
}
