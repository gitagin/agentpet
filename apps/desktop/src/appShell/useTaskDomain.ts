import { useCallback, useEffect, useRef, useState } from "react";
import { useTasks } from "../features/tasks/useTasks";
import type { DesktopApi } from "../services/desktopApi";
import type { DesktopWindowMode } from "../features/desktop/desktopWindowModes";
import type { Notice } from "./types";

const PET_TASK_STAGE_ACTIVE_MS = 12_000;

type UseTaskDomainOptions = {
  api: DesktopApi;
  desktopHostMode: DesktopWindowMode;
  windowMode: DesktopWindowMode;
  sidecarConnected: boolean;
  onNotice: (notice: Notice | null) => void;
};

export function useTaskDomain({
  api,
  desktopHostMode,
  windowMode,
  sidecarConnected,
  onNotice,
}: UseTaskDomainOptions) {
  const [recentTaskStageActive, setRecentTaskStageActive] = useState(false);
  const taskStageTimeoutRef = useRef<number | null>(null);

  const triggerPetTaskStage = useCallback(() => {
    setRecentTaskStageActive(true);
    if (taskStageTimeoutRef.current !== null) {
      window.clearTimeout(taskStageTimeoutRef.current);
    }
    taskStageTimeoutRef.current = window.setTimeout(() => {
      setRecentTaskStageActive(false);
      taskStageTimeoutRef.current = null;
    }, PET_TASK_STAGE_ACTIVE_MS);
  }, []);

  useEffect(() => () => {
    if (taskStageTimeoutRef.current !== null) {
      window.clearTimeout(taskStageTimeoutRef.current);
    }
  }, []);

  const pollingEnabled =
    (desktopHostMode === "pet" && windowMode === "pet") ||
    windowMode === "control" ||
    windowMode === "stage";
  const controller = useTasks({
    api,
    pollingEnabled,
    sidecarReady: sidecarConnected,
    onNotice,
    onTaskStage: triggerPetTaskStage,
  });

  return { controller, recentTaskStageActive, triggerPetTaskStage };
}

export type TaskDomain = ReturnType<typeof useTaskDomain>;
