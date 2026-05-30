import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import { openPrimaryNavigationTab, primaryNavigationTabs, type PrimaryNavigationTab } from "./navigation";

export function BottomNav({ activeTab }: { activeTab: PrimaryNavigationTab }) {
  const activeIndex = Math.max(0, primaryNavigationTabs.indexOf(activeTab));
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    buttonRefs.current[activeIndex]?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [activeIndex]);

  return (
    <nav
      className="bottom-nav"
      aria-label="主导航"
      style={{ "--bottom-nav-active-index": activeIndex } as CSSProperties}
    >
      <div className="bottom-nav-track">
        <span aria-hidden="true" className="bottom-nav-indicator" />
        {primaryNavigationTabs.map((tab, index) => (
          <button
            key={tab}
            ref={(node) => {
              buttonRefs.current[index] = node;
            }}
            type="button"
            className={`bottom-nav-button${tab === activeTab ? " active" : ""}`}
            aria-current={tab === activeTab ? "page" : undefined}
            onClick={() => openPrimaryNavigationTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
    </nav>
  );
}
