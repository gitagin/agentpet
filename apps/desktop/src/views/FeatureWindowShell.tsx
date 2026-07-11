import type { ReactNode } from "react";
import { Cat } from "lucide-react";
import { BottomNav } from "./BottomNav";
import type { PrimaryNavigationTab } from "./navigation";
import { useVersionedPublicAsset } from "../hooks/useVersionedPublicAsset";

export function FeatureWindowShell({
  eyebrow,
  title,
  description,
  activeTab,
  showHeader = true,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  activeTab?: PrimaryNavigationTab | null;
  showHeader?: boolean;
  children: ReactNode;
}) {
  const homeImageSrc = useVersionedPublicAsset("/images/home.png");

  return (
    <main className="feature-shell" data-active-tab={activeTab ?? "secondary"}>
      <div className="feature-shell-backdrop" aria-hidden="true" />
      <div className="feature-reference-stage" aria-hidden="true">
        <img className="feature-reference-background" src={homeImageSrc} alt="" />
      </div>
      {showHeader ? (
        <header className="feature-window-header">
          <div className="feature-window-brand" aria-hidden="true">
            <span className="feature-window-brand-icon">
              <Cat size={22} />
            </span>
            <span>
              <strong>Agent Pet</strong>
              <small>本地模式</small>
            </span>
          </div>
          <div className="feature-window-copy">
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
        </header>
      ) : null}
      <section className="feature-window-content">{children}</section>
      <BottomNav activeTab={activeTab} />
    </main>
  );
}
