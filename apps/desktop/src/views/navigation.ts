import type { DesktopFeatureWindowMode } from "../types";

export const primaryNavigationTabs = ["首页", "聊天", "任务", "记忆", "知识", "设置"] as const;

export type PrimaryNavigationTab = (typeof primaryNavigationTabs)[number];

const routeByTab: Record<PrimaryNavigationTab, "stage" | "agent" | DesktopFeatureWindowMode> = {
  首页: "stage",
  聊天: "chat",
  任务: "agent",
  记忆: "memory",
  知识: "world",
  设置: "settings",
};

export function navigationHashForTab(tab: PrimaryNavigationTab): string {
  return routeByTab[tab];
}

export function openPrimaryNavigationTab(tab: PrimaryNavigationTab) {
  window.location.hash = navigationHashForTab(tab);
}
