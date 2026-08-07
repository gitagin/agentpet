const { app, BrowserWindow, Menu, globalShortcut, session } = require("electron");
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
const SIDECAR_PREFERRED_PORT = 8765;

app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

function buildContentSecurityPolicy() {
  const isDevelopment = !app.isPackaged;
  // 渲染进程不直接访问后端（全部走 IPC 代理），connect-src 无需放行 8765。
  // 开发模式放宽 script-src（Vite react-refresh 注入内联脚本）并放行 HMR websocket。
  const devWebSocketUrl = DEV_SERVER_URL.replace(/^http/, "ws");
  return [
    "default-src 'self'",
    isDevelopment ? "script-src 'self' 'unsafe-inline'" : "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    isDevelopment ? `connect-src 'self' ${DEV_SERVER_URL} ${devWebSocketUrl}` : "connect-src 'self'",
    "media-src 'self' blob: data:",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

function installContentSecurityPolicy() {
  const policy = buildContentSecurityPolicy();
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...(details.responseHeaders ?? {}),
        "Content-Security-Policy": [policy],
      },
    });
  });
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

function focusExistingInstanceWindow(windows) {
  const existingWindow = BrowserWindow.getAllWindows().find((window) => !window.isDestroyed?.());
  if (existingWindow) {
    if (existingWindow.isMinimized()) {
      existingWindow.restore();
    }
    existingWindow.focus();
    return;
  }
  windows.showControlWindow();
}

const hasSingleInstanceLock =
  typeof app.requestSingleInstanceLock === "function" ? app.requestSingleInstanceLock() : true;

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  const sessionToken = process.env.AGENT_PET_SESSION_TOKEN || crypto.randomBytes(32).toString("base64url");
  const rendererUiStatePath = path.join(app.getPath("userData"), "renderer-ui-state.json");
  const managedSidecarDataDir = path.join(app.getPath("userData"), "backend-state");
  // sidecar 管理器可能因约定端口被占而改用备选端口；proxy 与 IPC 通过这个共享
  // 运行时对象在每次请求时读取当前 baseUrl，而不是启动时固化。
  const sidecarRuntime = {
    host: SIDECAR_HOST,
    port: SIDECAR_PREFERRED_PORT,
    baseUrl: `http://${SIDECAR_HOST}:${SIDECAR_PREFERRED_PORT}`,
  };
  const getSidecarBaseUrl = () => sidecarRuntime.baseUrl;
  const state = {
    isQuitting: false,
    rendererUiState: loadRendererUiState(rendererUiStatePath),
  };

  function quitApp() {
    state.isQuitting = true;
    app.quit();
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
    host: sidecarRuntime.host,
    port: sidecarRuntime.port,
    baseUrl: sidecarRuntime.baseUrl,
    runtime: sidecarRuntime,
    sessionToken,
    managedSidecarDataDir,
    state,
    showControlWindow: windows.showControlWindow,
  });
  const proxy = createProxyManager({
    baseUrl: sidecarRuntime.baseUrl,
    getBaseUrl: getSidecarBaseUrl,
    sessionToken,
  });
  const tray = createTrayManager({
    createPetWindow: windows.createPetWindow,
    showStageWindow: windows.showStageWindow,
    showPetInputMode: windows.showPetInputMode,
    quitApp,
  });

  registerIpcHandlers({
    baseUrl: sidecarRuntime.baseUrl,
    getBaseUrl: getSidecarBaseUrl,
    rendererUiState: state.rendererUiState,
    persistRendererUiState,
    sidecar,
    proxy,
    windows,
  });

  app.on("second-instance", () => {
    focusExistingInstanceWindow(windows);
  });

  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    installContentSecurityPolicy();
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
}
