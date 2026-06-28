import type { DesktopFeatureWindowMode } from "../types";

export const primaryNavigationTabs = ["今日", "陪伴", "记忆", "成长", "任务", "知识", "设置"] as const;

export type PrimaryNavigationTab = (typeof primaryNavigationTabs)[number];

const routeByTab: Record<PrimaryNavigationTab, "stage" | "agent" | DesktopFeatureWindowMode> = {
  今日: "stage",
  陪伴: "chat",
  记忆: "memory",
  成长: "growth",
  任务: "agent",
  知识: "world",
  设置: "settings",
};

export function navigationHashForTab(tab: PrimaryNavigationTab): string {
  return routeByTab[tab];
}

export function openPrimaryNavigationTab(tab: PrimaryNavigationTab) {
  window.location.hash = navigationHashForTab(tab);
}
