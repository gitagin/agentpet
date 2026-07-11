import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function SettingsWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="设置"
      title="设置"
      description="管理我怎么聊天、怎么保存记忆、什么时候自动整理，以及是否朗读回复。"
      activeTab="设置"
    >
      {children}
    </FeatureWindowShell>
  );
}
