import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function WorldWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="Vault / Wiki"
      title="知识库"
      description="维护资料库、归档查询结果，并检查长期知识状态。"
      activeTab="知识库"
    >
      {children}
    </FeatureWindowShell>
  );
}
