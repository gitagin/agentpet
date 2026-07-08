import type { ReactNode } from "react";
import { productCopy } from "../productCopy";
import { FeatureWindowShell } from "./FeatureWindowShell";

export default function WorldWindowView({ children }: { children: ReactNode }) {
  return (
    <FeatureWindowShell
      eyebrow={productCopy.worldPage.eyebrow}
      title={productCopy.worldPage.title}
      description={productCopy.worldPage.description}
      activeTab={productCopy.worldPage.tabLabel}
    >
      {children}
    </FeatureWindowShell>
  );
}
