import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function WorldWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="高级"
      title="资料工具"
      description="本地文本导出、资料整理和维护工具收在这里，不打扰主流程。"
      activeTab={null}
    >
      {children}
    </FeatureWindowShell>
  );
}
