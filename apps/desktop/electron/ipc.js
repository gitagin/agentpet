const { BrowserWindow, dialog, ipcMain } = require("electron");

const allowedRendererUiStateKeys = new Set([
  "agent-pet.live2d-model-id",
  "agent-pet.wiki-archive-candidate",
]);

function normalizeRendererUiStateKey(key) {
  if (typeof key !== "string") {
    return null;
  }
  const normalized = key.trim();
  return allowedRendererUiStateKeys.has(normalized) ? normalized : null;
}

function registerIpcHandlers({ baseUrl, rendererUiState, sidecar, proxy, windows }) {
  ipcMain.on("agent-pet:get-sidecar-config", (event) => {
    event.returnValue = {
      baseUrl,
    };
  });

  ipcMain.on("agent-pet:get-ui-state", (event, key) => {
    const normalized = normalizeRendererUiStateKey(key);
    event.returnValue = normalized ? rendererUiState.get(normalized) ?? null : null;
  });

  ipcMain.on("agent-pet:set-ui-state", (_event, key, value) => {
    const normalized = normalizeRendererUiStateKey(key);
    if (!normalized) {
      return;
    }
    if (typeof value !== "string" || value.length === 0) {
      rendererUiState.delete(normalized);
      return;
    }
    if (value.length > 250000) {
      return;
    }
    rendererUiState.set(normalized, value);
  });

  ipcMain.handle("agent-pet:get-sidecar-status", () => sidecar.getPublicSidecarStatus());

  ipcMain.handle("agent-pet:api-request", async (_event, pathOrUrl, options) => proxy.proxyApiRequest(pathOrUrl, options));

  ipcMain.handle("agent-pet:sse-start", async (event, streamId, pathOrUrl) => {
    proxy.startSseStream(event.sender, streamId, pathOrUrl);
    return { streamId };
  });

  ipcMain.handle("agent-pet:sse-cancel", (_event, streamId) => {
    proxy.cancelSseStream(streamId);
  });

  ipcMain.handle("agent-pet:show-reminder-notification", (_event, payload) => sidecar.showReminderNotification(payload));

  ipcMain.handle("agent-pet:get-window-mode", (event) => {
    const petWindow = windows.getPetWindow();
    if (petWindow && event.sender === petWindow.webContents) {
      return "pet";
    }
    return "control";
  });

  ipcMain.handle("agent-pet:open-control-window", (_event, targetId) => {
    windows.showControlWindow(targetId);
  });

  ipcMain.handle("window:open-agent", () => {
    windows.showAgentWindow();
  });

  ipcMain.handle("window:close-agent", () => {
    windows.hideAgentWindow();
  });

  ipcMain.handle("window:open-stage", () => {
    windows.showStageWindow();
  });

  ipcMain.handle("companion:set-ignore-mouse", (_event, ignore) => windows.setCompanionMousePassthrough(ignore));

  ipcMain.handle("agent-pet:get-pet-mouse-passthrough-status", (event) => {
    const petWindow = windows.getPetWindow();
    if (!petWindow || event.sender !== petWindow.webContents) {
      return windows.getPetMousePassthroughStatus("ignored_sender", false);
    }

    return windows.updatePetMousePassthroughFromCursor();
  });

  ipcMain.on("agent-pet:begin-pet-window-drag", (event) => {
    windows.beginPetWindowDrag(event.sender);
  });

  ipcMain.on("agent-pet:activate-pet-window-drag", (event) => {
    windows.activatePetWindowDrag(event.sender);
  });

  ipcMain.on("agent-pet:end-pet-window-drag", (event) => {
    windows.endPetWindowDrag(event.sender);
  });

  ipcMain.handle("agent-pet:select-knowledge-base-folder", async (event) => {
    const ownerWindow = BrowserWindow.fromWebContents(event.sender);
    const result = await dialog.showOpenDialog(ownerWindow ?? undefined, {
      title: "选择知识库文件夹",
      properties: ["openDirectory", "createDirectory"],
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    return result.filePaths[0] || null;
  });
}

module.exports = {
  registerIpcHandlers,
};
