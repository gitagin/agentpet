import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { BookOpen, Brain, ListChecks, MessageCircle, Settings, Sparkles, Sprout } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { openPrimaryNavigationTab, primaryNavigationTabs, type PrimaryNavigationTab } from "./navigation";

const bottomNavIcons: Record<PrimaryNavigationTab, LucideIcon> = {
  [primaryNavigationTabs[0]]: Sparkles,
  [primaryNavigationTabs[1]]: MessageCircle,
  [primaryNavigationTabs[2]]: Brain,
  [primaryNavigationTabs[3]]: Sprout,
  [primaryNavigationTabs[4]]: ListChecks,
  [primaryNavigationTabs[5]]: BookOpen,
  [primaryNavigationTabs[6]]: Settings,
};

let hasBottomNavPosition = false;
let lastBottomNavActiveIndex = 0;

export function BottomNav({ activeTab, visible = true }: { activeTab: PrimaryNavigationTab; visible?: boolean }) {
  const activeIndex = Math.max(0, primaryNavigationTabs.indexOf(activeTab));
  const [indicatorIndex, setIndicatorIndex] = useState(() => (hasBottomNavPosition ? lastBottomNavActiveIndex : activeIndex));
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useLayoutEffect(() => {
    if (!visible) {
      return;
    }

    if (!hasBottomNavPosition) {
      hasBottomNavPosition = true;
      lastBottomNavActiveIndex = activeIndex;
      setIndicatorIndex(activeIndex);
      return;
    }

    setIndicatorIndex(lastBottomNavActiveIndex);

    const animationFrame = window.requestAnimationFrame(() => {
      setIndicatorIndex(activeIndex);
      lastBottomNavActiveIndex = activeIndex;
    });

    return () => window.cancelAnimationFrame(animationFrame);
  }, [activeIndex, visible]);

  useEffect(() => {
    const activeButton = buttonRefs.current[activeIndex];
    if (!activeButton?.scrollIntoView) {
      return;
    }
    activeButton.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [activeIndex]);

  return (
    <nav
      className="bottom-nav"
      aria-label="主导航"
      style={{ "--bottom-nav-active-index": indicatorIndex } as CSSProperties}
    >
      <div className="bottom-nav-track">
        <span aria-hidden="true" className="bottom-nav-indicator" />
        {primaryNavigationTabs.map((tab, index) => {
          const Icon = bottomNavIcons[tab];

          return (
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
              <Icon aria-hidden="true" focusable="false" className="bottom-nav-icon" strokeWidth={2.2} />
              <span className="bottom-nav-label">{tab}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
