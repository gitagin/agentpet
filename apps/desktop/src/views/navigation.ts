import type { DesktopFeatureWindowMode } from "../types";

export const primaryNavigationTabs = ["桌宠", "聊天", "整理", "知识库", "任务", "配置"] as const;

export type PrimaryNavigationTab = (typeof primaryNavigationTabs)[number];

const routeByTab: Record<PrimaryNavigationTab, "stage" | "agent" | DesktopFeatureWindowMode> = {
  桌宠: "stage",
  聊天: "chat",
  整理: "memory",
  知识库: "world",
  任务: "agent",
  配置: "settings",
};

export function navigationHashForTab(tab: PrimaryNavigationTab): string {
  return routeByTab[tab];
}

export function openPrimaryNavigationTab(tab: PrimaryNavigationTab) {
  window.location.hash = navigationHashForTab(tab);
}
