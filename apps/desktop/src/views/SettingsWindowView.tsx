import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function SettingsWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="设置"
      title="设置"
      description="决定我用哪个模型、哪些内容可自动整理，以及记忆要不要导出到本机文件夹。"
      activeTab="设置"
    >
      {children}
    </FeatureWindowShell>
  );
}
