import type { DesktopFeatureWindowMode } from "../types";

export const primaryNavigationTabs = ["今日", "聊天", "任务", "回放", "设置"] as const;

export type PrimaryNavigationTab = (typeof primaryNavigationTabs)[number];

const routeByTab: Record<PrimaryNavigationTab, "stage" | "agent" | DesktopFeatureWindowMode> = {
  今日: "stage",
  聊天: "chat",
  任务: "agent",
  回放: "memory",
  设置: "settings",
};

export function navigationHashForTab(tab: PrimaryNavigationTab): string {
  return routeByTab[tab];
}

export function openPrimaryNavigationTab(tab: PrimaryNavigationTab) {
  window.location.hash = navigationHashForTab(tab);
}
