import type { ComponentProps, ReactNode } from "react";
import type { DesktopWindowMode } from "./desktopWindowModes";
import AgentWorkspaceView from "../../views/AgentWorkspaceView";
import ChatWindowView from "../../views/ChatWindowView";
import GrowthWindowView from "../../views/GrowthWindowView";
import MemoryWindowView from "../../views/MemoryWindowView";
import SettingsWindowView from "../../views/SettingsWindowView";
import WorldWindowView from "../../views/WorldWindowView";

export function preloadDesktopFeatureRoutes() {
  return undefined;
}

type DesktopFeatureRoutesProps = {
  windowMode: DesktopWindowMode;
  isStageHostWindow: boolean;
  agentWorkspaceProps: ComponentProps<typeof AgentWorkspaceView>;
  chatWindowProps: ComponentProps<typeof ChatWindowView>;
  memoryWindowProps: ComponentProps<typeof MemoryWindowView>;
  growthWindowProps: ComponentProps<typeof GrowthWindowView>;
  wikiWorkflowPanel: ReactNode;
  settingsPanel: ReactNode;
};

export function DesktopFeatureRoutes({
  windowMode,
  isStageHostWindow,
  agentWorkspaceProps,
  chatWindowProps,
  memoryWindowProps,
  growthWindowProps,
  wikiWorkflowPanel,
  settingsPanel,
}: DesktopFeatureRoutesProps) {
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
        return <SettingsWindowView>{settingsPanel}</SettingsWindowView>;
      default:
        return null;
    }
  }

  if (isStageHostWindow) {
    const activeRoute = renderFeatureRoute(windowMode);

    return (
      <div className="stage-host-routes" data-active-route={windowMode}>
        <div className={`stage-host-route is-active stage-host-route-${windowMode}`} aria-label="当前活动路由">
          {activeRoute}
        </div>
      </div>
    );
  }

  return <>{renderFeatureRoute(windowMode, { standalone: windowMode === "world" })}</>;
}
