import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function SettingsWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="设置"
      title="设置"
      description="管理对话连接、记忆保存位置、自动整理和本地隐私边界。"
      activeTab="设置"
    >
      {children}
    </FeatureWindowShell>
  );
}
