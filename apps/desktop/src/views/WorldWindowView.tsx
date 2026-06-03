import type { ReactNode } from "react";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function WorldWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow="本地知识"
      title="知识库"
      description="查看知识页面、查询历史和只读检查结果；高级维护默认收起。"
      activeTab="知识库"
    >
      {children}
    </FeatureWindowShell>
  );
}
