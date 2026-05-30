import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function SettingsWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="模型与存储"
      title="配置"
      description="配置 AI 模型、Embedding、自动整理策略和长期记忆库位置。"
      activeTab="配置"
    >
      {children}
    </FeatureWindowShell>
  );
}
