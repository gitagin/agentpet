import type { DesktopFeatureWindowMode } from "../../types";

export type DesktopWindowMode = "pet" | "control" | "stage" | "agent" | DesktopFeatureWindowMode;
export type DesktopStageRouteMode = "stage" | "agent" | DesktopFeatureWindowMode;

export function detectDesktopWindowMode(): DesktopWindowMode {
  const mode = window.location.hash.replace("#/", "").replace("#", "") || "stage";
  if (isDesktopWindowMode(mode)) {
    return mode;
  }
  return "stage";
}

export function isDesktopWindowMode(mode: unknown): mode is DesktopWindowMode {
  return (
    mode === "pet" ||
    mode === "control" ||
    mode === "stage" ||
    mode === "agent" ||
    mode === "chat" ||
    mode === "growth" ||
    mode === "memory" ||
    mode === "world" ||
    mode === "settings"
  );
}
