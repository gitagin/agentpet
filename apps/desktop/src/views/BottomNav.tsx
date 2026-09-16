import { Fragment, useCallback, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { CalendarDays, Home, MessageCircle, Settings, Star } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useVersionedPublicAsset } from "../hooks/useVersionedPublicAsset";
import { openPrimaryNavigationTab, primaryNavigationTabs, type PrimaryNavigationTab } from "./navigation";

const bottomNavIcons: Record<PrimaryNavigationTab, LucideIcon> = {
  首页: Home,
  对话: MessageCircle,
  记忆: Star,
  计划: CalendarDays,
  设置: Settings,
};

export function BottomNav({ activeTab, visible = true }: { activeTab?: PrimaryNavigationTab | null; visible?: boolean }) {
  const activeIndex = activeTab ? primaryNavigationTabs.indexOf(activeTab) : -1;
  const hasActiveTab = activeIndex >= 0;
  // Initialise from the current page so a remounted nav never paints the
  // previous page's active item for a frame during route transitions.
  const [indicatorIndex, setIndicatorIndex] = useState(() => Math.max(0, activeIndex));
  const characterImageSrc = useVersionedPublicAsset("/images/character.png");
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [indicatorMetrics, setIndicatorMetrics] = useState({ x: 0, width: 0 });

  const updateIndicatorMetrics = useCallback((index = activeIndex) => {
    if (index < 0) {
      return;
    }

    const activeButton = buttonRefs.current[index];
    const track = trackRef.current;
    if (!activeButton || !track) {
      return;
    }

    const nextMetrics = {
      x: activeButton.offsetLeft,
      width: activeButton.offsetWidth,
    };

    setIndicatorMetrics((previousMetrics) => (
      previousMetrics.x === nextMetrics.x && previousMetrics.width === nextMetrics.width
        ? previousMetrics
        : nextMetrics
    ));
  }, [activeIndex]);

  useLayoutEffect(() => {
    if (!visible || !hasActiveTab) {
      return;
    }

    setIndicatorIndex(activeIndex);
    updateIndicatorMetrics(activeIndex);
  }, [activeIndex, hasActiveTab, updateIndicatorMetrics, visible]);

  useLayoutEffect(() => {
    if (!visible || !hasActiveTab) {
      return;
    }

    updateIndicatorMetrics(activeIndex);

    const track = trackRef.current;
    if (!track || typeof ResizeObserver === "undefined") {
      return;
    }

    const resizeObserver = new ResizeObserver(() => updateIndicatorMetrics(activeIndex));
    resizeObserver.observe(track);
    return () => resizeObserver.disconnect();
  }, [activeIndex, hasActiveTab, updateIndicatorMetrics, visible]);

  const navStyle = {
    "--bottom-nav-active-index": indicatorIndex,
    "--bottom-nav-indicator-x": indicatorMetrics.width > 0
      ? `${indicatorMetrics.x}px`
      : `calc(${indicatorIndex} * (var(--bottom-nav-item-width) + var(--bottom-nav-gap)))`,
    "--bottom-nav-indicator-width": indicatorMetrics.width > 0
      ? `${indicatorMetrics.width}px`
      : "var(--bottom-nav-item-width)",
  } as CSSProperties;

  if (!visible) {
    return null;
  }

  return (
    <nav
      className={`bottom-nav bottom-nav-with-avatar${hasActiveTab ? "" : " no-active"}`}
      aria-label="主导航"
      style={navStyle}
    >
      <div className="bottom-nav-track" ref={trackRef}>
        <span aria-hidden="true" className="bottom-nav-indicator" />
        {primaryNavigationTabs.map((tab, index) => {
          const Icon = bottomNavIcons[tab];

          return (
            <Fragment key={tab}>
              {index === 3 ? (
                <span className="bottom-nav-center-avatar" aria-hidden="true">
                  <img src={characterImageSrc} alt="" />
                </span>
              ) : null}
              <button
                ref={(node) => {
                  buttonRefs.current[index] = node;
                }}
                type="button"
                className={`bottom-nav-button${tab === activeTab ? " active" : ""}`}
                aria-current={tab === activeTab ? "page" : undefined}
                onClick={() => openPrimaryNavigationTab(tab)}
              >
                <Icon aria-hidden="true" focusable="false" className="bottom-nav-icon" strokeWidth={2.1} />
                <span className="bottom-nav-label">{tab}</span>
              </button>
            </Fragment>
          );
        })}
      </div>
    </nav>
  );
}
