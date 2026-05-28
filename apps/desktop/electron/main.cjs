const { app, BrowserWindow, Menu, globalShortcut } = require("electron");
const crypto = require("node:crypto");
const path = require("node:path");
const { createWindowManager } = require("./windows.js");
const { createTrayManager } = require("./tray.js");
const { createSidecarManager } = require("./sidecar.js");
const { createProxyManager } = require("./proxy.js");
const { registerIpcHandlers } = require("./ipc.js");

const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173";
const SIDECAR_HOST = "127.0.0.1";
const SIDECAR_PORT = 8765;
const SIDECAR_BASE_URL = `http://${SIDECAR_HOST}:${SIDECAR_PORT}`;
const sessionToken = process.env.AGENT_PET_SESSION_TOKEN || crypto.randomBytes(32).toString("base64url");
const managedSidecarDataDir = path.join(app.getPath("userData"), "backend-state");
const state = {
  isQuitting: false,
  rendererUiState: new Map(),
};

function quitApp() {
  state.isQuitting = true;
  app.quit();
}

const windows = createWindowManager({
  devServerUrl: DEV_SERVER_URL,
  state,
  quitApp,
});
const sidecar = createSidecarManager({
  host: SIDECAR_HOST,
  port: SIDECAR_PORT,
  baseUrl: SIDECAR_BASE_URL,
  sessionToken,
  managedSidecarDataDir,
  state,
  showControlWindow: windows.showControlWindow,
});
const proxy = createProxyManager({
  baseUrl: SIDECAR_BASE_URL,
  sessionToken,
});
const tray = createTrayManager({
  createPetWindow: windows.createPetWindow,
  showControlWindow: windows.showControlWindow,
  quitApp,
});

registerIpcHandlers({
  baseUrl: SIDECAR_BASE_URL,
  rendererUiState: state.rendererUiState,
  sidecar,
  proxy,
  windows,
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  sidecar.startSidecar();
  windows.createPetWindow();
  windows.createStageWindow();
  windows.createAgentWindow();
  tray.createTray();
  globalShortcut.register("CommandOrControl+Shift+A", windows.showControlWindow);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      windows.createPetWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (state.isQuitting && process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  state.isQuitting = true;
  windows.clearPetWindowDrag();
  sidecar.stopSidecar();
});

app.on("quit", () => {
  windows.clearPetWindowDrag();
  globalShortcut.unregisterAll();
  sidecar.abortSidecarReadiness();
});
