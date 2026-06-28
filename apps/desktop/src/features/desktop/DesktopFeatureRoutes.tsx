import { lazy, Suspense, useEffect } from "react";
import type { ComponentProps, ReactNode } from "react";
import type { DesktopWindowMode } from "./desktopWindowModes";

const loadAgentWorkspaceView = () => import("../../views/AgentWorkspaceView");
const loadChatWindowView = () => import("../../views/ChatWindowView");
const loadGrowthWindowView = () => import("../../views/GrowthWindowView");
const loadMemoryWindowView = () => import("../../views/MemoryWindowView");
const loadSettingsWindowView = () => import("../../views/SettingsWindowView");
const loadWorldWindowView = () => import("../../views/WorldWindowView");

const AgentWorkspaceView = lazy(loadAgentWorkspaceView);
const ChatWindowView = lazy(loadChatWindowView);
const GrowthWindowView = lazy(loadGrowthWindowView);
const MemoryWindowView = lazy(loadMemoryWindowView);
const SettingsWindowView = lazy(loadSettingsWindowView);
const WorldWindowView = lazy(loadWorldWindowView);

export function preloadDesktopFeatureRoutes() {
  void loadAgentWorkspaceView();
  void loadChatWindowView();
  void loadGrowthWindowView();
  void loadMemoryWindowView();
  void loadSettingsWindowView();
  void loadWorldWindowView();
}

type DesktopFeatureRoutesProps = {
  windowMode: DesktopWindowMode;
  isStageHostWindow: boolean;
  stageView: ReactNode;
  agentWorkspaceProps: ComponentProps<typeof AgentWorkspaceView>;
  chatWindowProps: ComponentProps<typeof ChatWindowView>;
  memoryWindowProps: ComponentProps<typeof MemoryWindowView>;
  growthWindowProps: ComponentProps<typeof GrowthWindowView>;
  connectionPanel: ReactNode;
  wikiWorkflowPanel: ReactNode;
  settingsPanel: ReactNode;
};

export function DesktopFeatureRoutes({
  windowMode,
  isStageHostWindow,
  stageView,
  agentWorkspaceProps,
  chatWindowProps,
  memoryWindowProps,
  growthWindowProps,
  connectionPanel,
  wikiWorkflowPanel,
  settingsPanel,
}: DesktopFeatureRoutesProps) {
  useEffect(() => {
    const preloadTimer = window.setTimeout(preloadDesktopFeatureRoutes, 1);
    return () => window.clearTimeout(preloadTimer);
  }, []);

  function renderFeatureRoute(mode: DesktopWindowMode, options: { standalone?: boolean } = {}) {
    switch (mode) {
      case "agent":
        return <AgentWorkspaceView {...agentWorkspaceProps} />;
      case "chat":
        return <ChatWindowView {...chatWindowProps} />;
      case "memory":
        return <MemoryWindowView {...memoryWindowProps} />;
      case "growth":
        return <GrowthWindowView {...growthWindowProps} />;
      case "world":
        return (
          <WorldWindowView>
            <div className={options.standalone ? "feature-page-stack wiki-page-stack" : "feature-page-stack"}>
              {wikiWorkflowPanel}
            </div>
          </WorldWindowView>
        );
      case "settings":
        return (
          <SettingsWindowView>
            <div className="feature-page-stack">
              {connectionPanel}
              {settingsPanel}
            </div>
          </SettingsWindowView>
        );
      default:
        return null;
    }
  }

  if (isStageHostWindow) {
    const activeRoute = renderFeatureRoute(windowMode);

    return (
      <div className="stage-host-routes" data-active-route={windowMode}>
        <div
          className={`stage-host-route${windowMode === "stage" ? " is-active" : ""}`}
          aria-label="首页常驻路由"
          aria-hidden={windowMode !== "stage"}
        >
          {stageView}
        </div>
        {windowMode !== "stage" ? (
          <div className="stage-host-route is-active" aria-label="当前活动路由">
            <Suspense fallback={<FeatureRouteFallback />}>{activeRoute}</Suspense>
          </div>
        ) : null}
      </div>
    );
  }

  if (windowMode === "stage") {
    return <>{stageView}</>;
  }

  return (
    <Suspense fallback={<FeatureRouteFallback />}>
      {renderFeatureRoute(windowMode, { standalone: windowMode === "world" })}
    </Suspense>
  );
}

function FeatureRouteFallback() {
  return (
    <div className="feature-route-loading" role="status" aria-live="polite">
      <span className="feature-route-loading-dot" aria-hidden="true" />
      <strong>正在打开...</strong>
    </div>
  );
}
