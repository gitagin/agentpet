import { useEffect } from "react";
import { useConnection } from "../features/connection/useConnection";
import { isTtsSettingsSavedMessage, settingsSyncChannelName } from "../features/settings/settingsSync";
import { useSettings } from "../features/settings/useSettings";
import type { Notice } from "./types";

type UseConnectionSettingsDomainOptions = {
  onNotice: (notice: Notice | null) => void;
};

export function useConnectionSettingsDomain({ onNotice }: UseConnectionSettingsDomainOptions) {
  const isElectronRuntime = Boolean(window.agentDesktop);
  const canSelectVaultDirectory = Boolean(window.agentDesktop?.selectKnowledgeBaseFolder);
  const connection = useConnection({ onNotice });
  const settings = useSettings({
    api: connection.api,
    isElectronRuntime,
    onNotice,
  });
  const applySettingsStatus = settings.applySettingsStatus;
  const loadSettingsStatus = settings.loadSettingsStatus;
  const loadVaultStatus = settings.loadVaultStatus;
  const sidecarConnected =
    connection.sidecarStatus?.state === "ready" || connection.sidecarStatus?.state === "degraded";
  const hasConnection = sidecarConnected || connection.health?.status === "ok";

  useEffect(() => {
    if (connection.settingsStatus) {
      applySettingsStatus(connection.settingsStatus);
    }
  }, [applySettingsStatus, connection.settingsStatus]);

  useEffect(() => {
    const abort = new AbortController();
    void loadSettingsStatus({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [loadSettingsStatus]);

  useEffect(() => {
    if (!("BroadcastChannel" in window)) {
      return;
    }
    const channel = new BroadcastChannel(settingsSyncChannelName);
    channel.onmessage = (event) => {
      if (isTtsSettingsSavedMessage(event.data)) {
        void loadSettingsStatus({ silent: true });
      }
    };
    return () => channel.close();
  }, [loadSettingsStatus]);

  useEffect(() => {
    if (!sidecarConnected) {
      return;
    }
    const abort = new AbortController();
    void loadVaultStatus({ silent: true, signal: abort.signal });
    return () => abort.abort();
  }, [connection.sidecarStatus?.updatedAt, loadVaultStatus, sidecarConnected]);

  return {
    connection,
    settings,
    sidecarConnected,
    hasConnection,
    isElectronRuntime,
    canSelectVaultDirectory,
  };
}

export type ConnectionSettingsDomain = ReturnType<typeof useConnectionSettingsDomain>;
