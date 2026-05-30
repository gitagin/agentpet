import type { DesktopFeatureWindowMode } from "../types";

export const primaryNavigationTabs = ["桌宠", "聊天", "整理", "知识库", "任务", "配置"] as const;

export type PrimaryNavigationTab = (typeof primaryNavigationTabs)[number];

const featureWindowByTab: Partial<Record<PrimaryNavigationTab, DesktopFeatureWindowMode>> = {
  聊天: "chat",
  整理: "memory",
  知识库: "world",
  配置: "settings",
};

export function openPrimaryNavigationTab(tab: PrimaryNavigationTab) {
  if (tab === "桌宠") {
    void window.agentDesktop?.openStage?.();
    return;
  }

  if (tab === "任务") {
    void window.agentDesktop?.openAgent?.();
    return;
  }

  const featureWindow = featureWindowByTab[tab];
  if (featureWindow) {
    void window.agentDesktop?.openFeatureWindow?.(featureWindow);
  }
}
