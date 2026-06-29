import type { DesktopFeatureWindowMode } from "../types";

export const primaryNavigationTabs = ["今日", "聊天", "记忆", "设置"] as const;

export type PrimaryNavigationTab = (typeof primaryNavigationTabs)[number];

const routeByTab: Record<PrimaryNavigationTab, "stage" | "agent" | DesktopFeatureWindowMode> = {
  今日: "stage",
  聊天: "chat",
  记忆: "memory",
  设置: "settings",
};

export function navigationHashForTab(tab: PrimaryNavigationTab): string {
  return routeByTab[tab];
}

export function openPrimaryNavigationTab(tab: PrimaryNavigationTab) {
  window.location.hash = navigationHashForTab(tab);
}
