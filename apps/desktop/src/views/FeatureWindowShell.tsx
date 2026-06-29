import type { ReactNode } from "react";
import { BottomNav } from "./BottomNav";
import type { PrimaryNavigationTab } from "./navigation";

export function FeatureWindowShell({
  eyebrow,
  title,
  description,
  activeTab,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  activeTab?: PrimaryNavigationTab | null;
  children: ReactNode;
}) {
  return (
    <main className="feature-shell">
      <header className="feature-window-header">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </header>
      <section className="feature-window-content">{children}</section>
      <BottomNav activeTab={activeTab} />
    </main>
  );
}
