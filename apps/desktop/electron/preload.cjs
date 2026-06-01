const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("agentDesktop", {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },
  getSidecarConfig: () => ipcRenderer.sendSync("agent-pet:get-sidecar-config"),
  getUiState: (key) => ipcRenderer.sendSync("agent-pet:get-ui-state", key),
  setUiState: (key, value) => ipcRenderer.send("agent-pet:set-ui-state", key, value),
  getSidecarStatus: () => ipcRenderer.invoke("agent-pet:get-sidecar-status"),
  apiRequest: (pathOrUrl, options) => ipcRenderer.invoke("agent-pet:api-request", pathOrUrl, options),
  startSseStream: (streamId, pathOrUrl) => ipcRenderer.invoke("agent-pet:sse-start", streamId, pathOrUrl),
  cancelSseStream: (streamId) => ipcRenderer.invoke("agent-pet:sse-cancel", streamId),
  onSseChunk: (callback) => {
    const listener = (_event, streamId, chunk) => callback(streamId, chunk);
    ipcRenderer.on("agent-pet:sse-chunk", listener);
    return () => {
      ipcRenderer.removeListener("agent-pet:sse-chunk", listener);
    };
  },
  onSseEnd: (callback) => {
    const listener = (_event, streamId) => callback(streamId);
    ipcRenderer.on("agent-pet:sse-end", listener);
    return () => {
      ipcRenderer.removeListener("agent-pet:sse-end", listener);
    };
  },
  onSseError: (callback) => {
    const listener = (_event, streamId, error) => callback(streamId, error);
    ipcRenderer.on("agent-pet:sse-error", listener);
    return () => {
      ipcRenderer.removeListener("agent-pet:sse-error", listener);
    };
  },
  showReminderNotification: (payload) => ipcRenderer.invoke("agent-pet:show-reminder-notification", payload),
  getWindowMode: () => ipcRenderer.invoke("agent-pet:get-window-mode"),
  openControlWindow: (targetId) => ipcRenderer.invoke("agent-pet:open-control-window", targetId),
  openAgent: () => ipcRenderer.invoke("window:open-agent"),
  closeAgent: () => ipcRenderer.invoke("window:close-agent"),
  openStage: () => ipcRenderer.invoke("window:open-stage"),
  openFeatureWindow: (mode) => ipcRenderer.invoke("window:open-feature", mode),
  quitApp: () => ipcRenderer.invoke("app:quit"),
  getPetMousePassthroughStatus: () => ipcRenderer.invoke("agent-pet:get-pet-mouse-passthrough-status"),
  setPetShortcutBarVisible: (visible) => ipcRenderer.invoke("agent-pet:set-pet-shortcut-bar-visible", visible),
  setPetInputVisible: (visible) => ipcRenderer.invoke("agent-pet:set-pet-input-visible", visible),
  beginPetWindowDrag: () => ipcRenderer.send("agent-pet:begin-pet-window-drag"),
  activatePetWindowDrag: () => ipcRenderer.send("agent-pet:activate-pet-window-drag"),
  endPetWindowDrag: () => ipcRenderer.send("agent-pet:end-pet-window-drag"),
  onPetDragCancelled: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("agent-pet:cancel-pet-drag", listener);
    return () => {
      ipcRenderer.removeListener("agent-pet:cancel-pet-drag", listener);
    };
  },
  onControlTargetRequested: (callback) => {
    const listener = (_event, targetId) => {
      if (typeof targetId === "string" && targetId.trim()) {
        callback(targetId);
      }
    };
    ipcRenderer.on("agent-pet:focus-control-target", listener);
    return () => {
      ipcRenderer.removeListener("agent-pet:focus-control-target", listener);
    };
  },
  selectKnowledgeBaseFolder: () => ipcRenderer.invoke("agent-pet:select-knowledge-base-folder"),
  onSidecarStatusChanged: (callback) => {
    const listener = (_event, status) => callback(status);
    ipcRenderer.on("agent-pet:sidecar-status-changed", listener);
    return () => {
      ipcRenderer.removeListener("agent-pet:sidecar-status-changed", listener);
    };
  },
});
