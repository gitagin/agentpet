import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function SettingsWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="设置"
      title="设置"
      description="配置模型、语音、自动整理策略和本地记忆文件夹。"
      activeTab="设置"
    >
      {children}
    </FeatureWindowShell>
  );
}
