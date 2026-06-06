import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function WorldWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="知识"
      title="知识"
      description="把日常材料整理成可复用的 Wiki 页面；最近产物优先展示，维护工具收在高级区。"
      activeTab="知识"
    >
      {children}
    </FeatureWindowShell>
  );
}
