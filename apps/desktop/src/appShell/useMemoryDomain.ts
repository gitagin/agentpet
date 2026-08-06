import { useEffect } from "react";
import { useMemory } from "../features/memory/useMemory";
import type { LastIndexRun } from "../features/settings/settingsTypes";
import type { DesktopApi } from "../services/desktopApi";
import type { DiagnosticsExportResponse } from "../types";
import { getSearchEmptyNotice } from "./appShellUtils";
import type { Notice } from "./types";

type UseMemoryDomainOptions = {
  api: DesktopApi;
  lastIndexRun: LastIndexRun | null;
  diagnostics: DiagnosticsExportResponse | null;
  onNotice: (notice: Notice | null) => void;
  onAgentActionsRefresh: () => void;
};

export function useMemoryDomain({
  api,
  lastIndexRun,
  diagnostics,
  onNotice,
  onAgentActionsRefresh,
}: UseMemoryDomainOptions) {
  const controller = useMemory({
    api,
    onNotice,
    getSearchEmptyNotice: (query) => getSearchEmptyNotice(query, lastIndexRun, diagnostics),
    onAgentActionsRefresh,
  });
  const loadPendingProposals = controller.loadPendingProposals;

  useEffect(() => {
    const abort = new AbortController();
    void loadPendingProposals({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [loadPendingProposals]);

  return controller;
}

export type MemoryDomain = ReturnType<typeof useMemoryDomain>;
