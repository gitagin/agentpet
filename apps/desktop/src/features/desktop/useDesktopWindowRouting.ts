import { useEffect, useRef, useState } from "react";

import {
  detectDesktopWindowMode,
  isDesktopFeatureWindowMode,
  isDesktopWindowMode,
  type DesktopWindowMode,
} from "./desktopWindowModes";

type UseDesktopWindowRoutingOptions = {
  onControlTargetRequested: (targetId?: string) => void;
};

function hasExplicitWindowRoute(): boolean {
  const hash = window.location.hash.replace("#/", "").replace("#", "").trim();
  return Boolean(hash);
}

export function useDesktopWindowRouting({
  onControlTargetRequested,
}: UseDesktopWindowRoutingOptions) {
  const [windowMode, setWindowMode] = useState<DesktopWindowMode>(() => detectDesktopWindowMode());
  const [desktopHostMode, setDesktopHostMode] = useState<DesktopWindowMode>(() => detectDesktopWindowMode());
  const onControlTargetRequestedRef = useRef(onControlTargetRequested);

  useEffect(() => {
    onControlTargetRequestedRef.current = onControlTargetRequested;
  }, [onControlTargetRequested]);

  useEffect(() => {
    document.body.dataset.windowMode = windowMode;
    return () => {
      delete document.body.dataset.windowMode;
    };
  }, [windowMode]);

  useEffect(() => {
    let cancelled = false;
    const getWindowMode = window.agentDesktop?.getWindowMode;
    if (getWindowMode) {
      void getWindowMode()
        .then((mode) => {
          if (!cancelled && isDesktopWindowMode(mode)) {
            setDesktopHostMode(mode);
          }
          const detectedMode = detectDesktopWindowMode();
          if (!cancelled && !hasExplicitWindowRoute() && (mode === "pet" || mode === "control")) {
            setWindowMode(mode);
            return;
          }
          if (!cancelled && detectedMode !== "control") {
            setWindowMode(detectedMode);
            return;
          }
          if (!cancelled && (mode === "pet" || mode === "control")) {
            setWindowMode(mode);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setDesktopHostMode(detectDesktopWindowMode());
          }
        });
    } else {
      setDesktopHostMode(detectDesktopWindowMode());
    }

    const updateFromHash = () => setWindowMode(detectDesktopWindowMode());
    window.addEventListener("hashchange", updateFromHash);
    return () => {
      cancelled = true;
      window.removeEventListener("hashchange", updateFromHash);
    };
  }, []);

  useEffect(() => {
    if (windowMode !== "control" && windowMode !== "stage") {
      return;
    }
    const unsubscribe = window.agentDesktop?.onControlTargetRequested?.((targetId) => {
      window.requestAnimationFrame(() => onControlTargetRequestedRef.current(targetId));
    });
    return unsubscribe;
  }, [windowMode]);

  useEffect(() => {
    if (desktopHostMode !== "stage") {
      return;
    }
    const unsubscribe = window.agentDesktop?.onStageRouteRequested?.((mode) => {
      const nextMode = isDesktopWindowMode(mode) ? mode : "stage";
      const nextHash = `#${nextMode}`;
      if (window.location.hash !== nextHash) {
        window.location.hash = nextMode;
        return;
      }
      setWindowMode(nextMode);
    });
    return unsubscribe;
  }, [desktopHostMode]);

  useEffect(() => {
    // feature 宿主窗口的复用切换：主进程发 IPC 而不是整页 reload（见 windows.js
    // createFeatureWindow），这里改 hash 让路由状态跟着走且不丢渲染端状态。
    if (!isDesktopFeatureWindowMode(desktopHostMode)) {
      return;
    }
    const unsubscribe = window.agentDesktop?.onFeatureRouteRequested?.((mode) => {
      if (!isDesktopFeatureWindowMode(mode)) {
        return;
      }
      const nextHash = `#${mode}`;
      if (window.location.hash !== nextHash) {
        window.location.hash = mode;
        return;
      }
      setWindowMode(mode);
    });
    return unsubscribe;
  }, [desktopHostMode]);

  return {
    windowMode,
    desktopHostMode,
    setWindowMode,
  };
}
