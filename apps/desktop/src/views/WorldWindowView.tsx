import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function WorldWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="高级"
      title="知识整理"
      description="本地文本导出与知识整理工具收在这里，不打扰主流程。"
      activeTab="设置"
    >
      {children}
    </FeatureWindowShell>
  );
}
