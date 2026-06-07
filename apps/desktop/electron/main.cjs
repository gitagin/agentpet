const { app, BrowserWindow, Menu, globalShortcut } = require("electron");
const crypto = require("node:crypto");
const fs = require("node:fs");
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
const rendererUiStatePath = path.join(app.getPath("userData"), "renderer-ui-state.json");
const managedSidecarDataDir = path.join(app.getPath("userData"), "backend-state");
const state = {
  isQuitting: false,
  rendererUiState: loadRendererUiState(rendererUiStatePath),
};

app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

function quitApp() {
  state.isQuitting = true;
  app.quit();
}

function loadRendererUiState(filePath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return new Map();
    }
    return new Map(
      Object.entries(parsed).filter((entry) => typeof entry[1] === "string" && entry[1].length <= 250000),
    );
  } catch {
    return new Map();
  }
}

function persistRendererUiState() {
  try {
    fs.mkdirSync(path.dirname(rendererUiStatePath), { recursive: true });
    const payload = Object.fromEntries(state.rendererUiState.entries());
    const tempPath = `${rendererUiStatePath}.tmp`;
    fs.writeFileSync(tempPath, JSON.stringify(payload, null, 2), "utf8");
    fs.renameSync(tempPath, rendererUiStatePath);
  } catch (error) {
    console.warn("Failed to persist renderer UI state.", error);
  }
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
  showStageWindow: windows.showStageWindow,
  showAgentWindow: windows.showAgentWindow,
  showFeatureWindow: windows.showFeatureWindow,
  showPetInputMode: windows.showPetInputMode,
  quitApp,
});

registerIpcHandlers({
  baseUrl: SIDECAR_BASE_URL,
  rendererUiState: state.rendererUiState,
  persistRendererUiState,
  sidecar,
  proxy,
  windows,
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  sidecar.startSidecar();
  windows.createPetWindow();
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
