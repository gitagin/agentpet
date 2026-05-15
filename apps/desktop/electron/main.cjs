const { app, BrowserWindow, Menu, Tray, globalShortcut, ipcMain, shell, dialog, nativeImage, screen, Notification } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const petHitboxConfig = require("../pet-hitbox.json");

const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173";
const SIDECAR_HOST = "127.0.0.1";
const SIDECAR_PORT = 8765;
const SIDECAR_BASE_URL = `http://${SIDECAR_HOST}:${SIDECAR_PORT}`;
const PET_WINDOW_WIDTH = petHitboxConfig.window.width;
const PET_WINDOW_HEIGHT = petHitboxConfig.window.height;
const PET_MIN_VISIBLE_WIDTH = petHitboxConfig.window.minVisibleWidth;
const PET_MIN_VISIBLE_HEIGHT = petHitboxConfig.window.minVisibleHeight;
const PET_MODEL_HIT_WIDTH = petHitboxConfig.hitboxes.model.width;
const PET_MODEL_HIT_HEIGHT = petHitboxConfig.hitboxes.model.height;
const PET_MODEL_HIT_BOTTOM = petHitboxConfig.hitboxes.model.bottom;
const PET_INPUT_DOCK_HIT_WIDTH = petHitboxConfig.hitboxes.inputDock.width;
const PET_INPUT_DOCK_HIT_HEIGHT = petHitboxConfig.hitboxes.inputDock.height;
const PET_INPUT_DOCK_HIT_BOTTOM = petHitboxConfig.hitboxes.inputDock.bottom;
const PET_CHAT_BUBBLE_HIT_WIDTH = petHitboxConfig.hitboxes.chatBubble.width;
const PET_CHAT_BUBBLE_HIT_HEIGHT = petHitboxConfig.hitboxes.chatBubble.height;
const PET_CHAT_BUBBLE_HIT_BOTTOM = petHitboxConfig.hitboxes.chatBubble.bottom;

let petWindow = null;
let controlWindow = null;
let tray = null;
let sidecarProcess = null;
let sidecarReadinessAbort = null;
let sidecarExitErrorOverride = null;
let isQuitting = false;
let petAlwaysOnTop = true;
let petDragState = null;
let petDragTimer = null;
let petDragWatchdog = null;
let petMouseHitTestTimer = null;
let petMousePassthrough = false;
let pendingControlTargetId = null;
const deliveredReminderNotifications = new Set();
const allowedRendererUiStateKeys = new Set([
  "agent-pet.live2d-model-id",
  "agent-pet.wiki-archive-candidate",
]);
const rendererUiState = new Map();
const sessionToken = process.env.AGENT_PET_SESSION_TOKEN || crypto.randomBytes(32).toString("base64url");
const managedSidecarDataDir = path.join(app.getPath("userData"), "backend-state");
let sidecarStatus = {
  state: "stopped",
  baseUrl: SIDECAR_BASE_URL,
  host: SIDECAR_HOST,
  port: SIDECAR_PORT,
  dataDir: managedSidecarDataDir,
  managed: false,
  pid: null,
  health: null,
  error: null,
  updatedAt: new Date().toISOString(),
};

function isDevelopment() {
  return !app.isPackaged;
}

function getAppEntryUrl(mode) {
  const debugHitboxQuery = mode === "pet" && process.env.AGENT_PET_DEBUG_HITBOX === "1" ? "?hitbox=1" : "";
  if (isDevelopment()) {
    return `${DEV_SERVER_URL}${debugHitboxQuery}#${mode}`;
  }

  return pathToFileURL(path.join(app.getAppPath(), "dist", "index.html")).toString() + `${debugHitboxQuery}#${mode}`;
}

function loadAppWindow(window, mode) {
  if (isDevelopment()) {
    window.loadURL(getAppEntryUrl(mode));
    return;
  }

  if (mode === "pet" && process.env.AGENT_PET_DEBUG_HITBOX === "1") {
    window.loadURL(getAppEntryUrl(mode));
    return;
  }

  window.loadFile(path.join(app.getAppPath(), "dist", "index.html"), { hash: mode });
}

function configureCommonWindow(window) {
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  window.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(false);
  });

  window.webContents.on("will-navigate", (event, url) => {
    const allowedUrl = isDevelopment()
      ? DEV_SERVER_URL
      : pathToFileURL(path.join(app.getAppPath(), "dist", "index.html")).toString();

    if (!url.startsWith(allowedUrl)) {
      event.preventDefault();
      if (url.startsWith("http://") || url.startsWith("https://")) {
        shell.openExternal(url);
      }
    }
  });
}

function enforcePetWindowSize() {
  if (!petWindow || petWindow.isDestroyed()) {
    return;
  }

  petWindow.setMinimumSize(PET_WINDOW_WIDTH, PET_WINDOW_HEIGHT);
  petWindow.setMaximumSize(PET_WINDOW_WIDTH, PET_WINDOW_HEIGHT);
  petWindow.setResizable(false);

  const [x, y] = petWindow.getPosition();
  const [width, height] = petWindow.getSize();
  if (width !== PET_WINDOW_WIDTH || height !== PET_WINDOW_HEIGHT) {
    petWindow.setBounds({ x, y, width: PET_WINDOW_WIDTH, height: PET_WINDOW_HEIGHT }, false);
  }
}

function clearPetWindowDrag() {
  petDragState = null;
  if (petDragTimer) {
    clearInterval(petDragTimer);
    petDragTimer = null;
  }
  if (petDragWatchdog) {
    clearTimeout(petDragWatchdog);
    petDragWatchdog = null;
  }
}

function getPetMousePassthroughStatus(reason, changed = false) {
  return {
    enabled: petMousePassthrough,
    reason,
    changed,
  };
}

function setPetMousePassthrough(enabled, reason = "manual") {
  if (!petWindow || petWindow.isDestroyed()) {
    petMousePassthrough = false;
    return getPetMousePassthroughStatus("no_pet_window", false);
  }

  const next = Boolean(enabled);
  if (petMousePassthrough === next) {
    return getPetMousePassthroughStatus(reason, false);
  }

  petMousePassthrough = next;
  petWindow.setIgnoreMouseEvents(next, { forward: true });
  return getPetMousePassthroughStatus(reason, true);
}

function isPointInRect(point, rect) {
  return point.x >= rect.x
    && point.x <= rect.x + rect.width
    && point.y >= rect.y
    && point.y <= rect.y + rect.height;
}

function createCenteredPetHitRect(width, height, bottom) {
  return {
    x: Math.round((PET_WINDOW_WIDTH - width) / 2),
    y: PET_WINDOW_HEIGHT - bottom - height,
    width,
    height,
  };
}

function isCursorInsidePetInteractiveRegion(cursor, bounds) {
  const localPoint = {
    x: cursor.x - bounds.x,
    y: cursor.y - bounds.y,
  };
  const modelRect = createCenteredPetHitRect(PET_MODEL_HIT_WIDTH, PET_MODEL_HIT_HEIGHT, PET_MODEL_HIT_BOTTOM);
  const inputDockRect = createCenteredPetHitRect(
    PET_INPUT_DOCK_HIT_WIDTH,
    PET_INPUT_DOCK_HIT_HEIGHT,
    PET_INPUT_DOCK_HIT_BOTTOM,
  );
  const chatBubbleRect = createCenteredPetHitRect(
    PET_CHAT_BUBBLE_HIT_WIDTH,
    PET_CHAT_BUBBLE_HIT_HEIGHT,
    PET_CHAT_BUBBLE_HIT_BOTTOM,
  );
  return (
    isPointInRect(localPoint, modelRect)
    || isPointInRect(localPoint, inputDockRect)
    || isPointInRect(localPoint, chatBubbleRect)
  );
}

function updatePetMousePassthroughFromCursor() {
  if (!petWindow || petWindow.isDestroyed()) {
    return getPetMousePassthroughStatus("no_pet_window", false);
  }
  if (petDragState?.active) {
    return setPetMousePassthrough(false, "dragging");
  }

  const cursor = screen.getCursorScreenPoint();
  const bounds = petWindow.getBounds();
  const insideInteractiveRegion = isCursorInsidePetInteractiveRegion(cursor, bounds);
  return setPetMousePassthrough(
    !insideInteractiveRegion,
    insideInteractiveRegion ? "interactive_region" : "transparent_area",
  );
}

function startPetMouseHitTest() {
  if (petMouseHitTestTimer) {
    return;
  }
  petMouseHitTestTimer = setInterval(updatePetMousePassthroughFromCursor, 80);
}

function stopPetMouseHitTest() {
  if (!petMouseHitTestTimer) {
    return;
  }
  clearInterval(petMouseHitTestTimer);
  petMouseHitTestTimer = null;
}

function clampNumber(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function clampPetWindowToWorkArea(x, y, cursor) {
  const display = screen.getDisplayNearestPoint(cursor) || screen.getPrimaryDisplay();
  const workArea = display.workArea;
  const minX = workArea.x - PET_WINDOW_WIDTH + PET_MIN_VISIBLE_WIDTH;
  const maxX = workArea.x + workArea.width - PET_MIN_VISIBLE_WIDTH;
  const minY = workArea.y - PET_WINDOW_HEIGHT + PET_MIN_VISIBLE_HEIGHT;
  const maxY = workArea.y + workArea.height - PET_MIN_VISIBLE_HEIGHT;

  return {
    x: clampNumber(x, minX, maxX),
    y: clampNumber(y, minY, maxY),
  };
}

function movePetWindowFromCursor() {
  if (!petWindow || petWindow.isDestroyed() || !petDragState?.active) {
    return;
  }

  const cursor = screen.getCursorScreenPoint();
  const next = clampPetWindowToWorkArea(
    Math.round(cursor.x - petDragState.offsetX),
    Math.round(cursor.y - petDragState.offsetY),
    cursor,
  );

  if (petDragState.lastX === next.x && petDragState.lastY === next.y) {
    return;
  }

  petWindow.setPosition(next.x, next.y, false);
  petDragState.lastX = next.x;
  petDragState.lastY = next.y;
}

function createPetWindow() {
  if (petWindow) {
    petWindow.show();
    petWindow.focus();
    return petWindow;
  }

  petWindow = new BrowserWindow({
    width: PET_WINDOW_WIDTH,
    height: PET_WINDOW_HEIGHT,
    minWidth: PET_WINDOW_WIDTH,
    minHeight: PET_WINDOW_HEIGHT,
    maxWidth: PET_WINDOW_WIDTH,
    maxHeight: PET_WINDOW_HEIGHT,
    title: "桌面记忆助手",
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    hasShadow: false,
    resizable: false,
    maximizable: false,
    minimizable: false,
    skipTaskbar: true,
    alwaysOnTop: petAlwaysOnTop,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  configureCommonWindow(petWindow);
  enforcePetWindowSize();
  petWindow.setAlwaysOnTop(petAlwaysOnTop, "floating");
  petWindow.once("ready-to-show", () => {
    enforcePetWindowSize();
    petWindow?.show();
    setPetMousePassthrough(true, "ready_to_show");
    startPetMouseHitTest();
  });
  petWindow.on("will-resize", (event) => {
    event.preventDefault();
    enforcePetWindowSize();
  });
  petWindow.on("resize", enforcePetWindowSize);
  petWindow.on("blur", () => {
    clearPetWindowDrag();
    petWindow?.webContents.send("agent-pet:cancel-pet-drag");
    updatePetMousePassthroughFromCursor();
  });
  petWindow.on("closed", () => {
    clearPetWindowDrag();
    stopPetMouseHitTest();
    petMousePassthrough = false;
    petWindow = null;
  });
  petWindow.webContents.on("context-menu", () => {
    showPetContextMenu();
  });
  petWindow.webContents.on("did-finish-load", () => {
    updatePetMousePassthroughFromCursor();
  });

  loadAppWindow(petWindow, "pet");
  return petWindow;
}

function normalizeControlTargetId(targetId) {
  if (typeof targetId !== "string") {
    return null;
  }
  const trimmed = targetId.trim();
  return /^[A-Za-z0-9_-]{1,80}$/.test(trimmed) ? trimmed : null;
}

function focusControlTarget(targetId) {
  const normalized = normalizeControlTargetId(targetId);
  if (!normalized) {
    return;
  }
  if (!controlWindow || controlWindow.isDestroyed()) {
    pendingControlTargetId = normalized;
    return;
  }
  if (controlWindow.webContents.isLoading()) {
    pendingControlTargetId = normalized;
    return;
  }
  controlWindow.webContents.send("agent-pet:focus-control-target", normalized);
}

function createControlWindow() {
  if (controlWindow) {
    return controlWindow;
  }

  controlWindow = new BrowserWindow({
    width: 1200,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    title: "桌面记忆助手控制台",
    backgroundColor: "#f7f7f2",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  configureCommonWindow(controlWindow);
  controlWindow.once("ready-to-show", () => {
    controlWindow?.show();
  });
  controlWindow.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      controlWindow?.hide();
    }
  });
  controlWindow.on("closed", () => {
    controlWindow = null;
  });
  controlWindow.webContents.on("did-finish-load", () => {
    if (!pendingControlTargetId) {
      return;
    }
    const targetId = pendingControlTargetId;
    pendingControlTargetId = null;
    focusControlTarget(targetId);
  });

  loadAppWindow(controlWindow, "control");
  return controlWindow;
}

function showControlWindow(targetId) {
  const normalizedTargetId = normalizeControlTargetId(targetId);
  if (normalizedTargetId) {
    pendingControlTargetId = normalizedTargetId;
  }
  clearPetWindowDrag();
  setPetMousePassthrough(false, "open_control_window");
  petWindow?.webContents.send("agent-pet:cancel-pet-drag");
  const window = createControlWindow();
  if (window.isMinimized()) {
    window.restore();
  }
  window.show();
  window.focus();
  if (normalizedTargetId) {
    setTimeout(() => focusControlTarget(normalizedTargetId), 80);
  }
  updatePetMousePassthroughFromCursor();
}

function reloadPetWindow() {
  clearPetWindowDrag();
  setPetMousePassthrough(false, "reload_pet_window");
  petWindow?.webContents.reloadIgnoringCache();
}

function setPetAlwaysOnTop(enabled) {
  petAlwaysOnTop = enabled;
  petWindow?.setAlwaysOnTop(petAlwaysOnTop, "floating");
}

function showPetContextMenu() {
  clearPetWindowDrag();
  setPetMousePassthrough(false, "context_menu");
  petWindow?.webContents.send("agent-pet:cancel-pet-drag");
  const menu = Menu.buildFromTemplate([
    { label: "打开控制台", click: showControlWindow },
    { label: "重新加载模型", click: reloadPetWindow },
    {
      label: "保持置顶",
      type: "checkbox",
      checked: petAlwaysOnTop,
      click: (item) => setPetAlwaysOnTop(item.checked),
    },
    { type: "separator" },
    {
      label: "退出应用",
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  menu.popup({
    window: petWindow ?? undefined,
    callback: () => {
      updatePetMousePassthroughFromCursor();
    },
  });
}

function findTrayIconPath() {
  const candidates = [
    path.join(app.getAppPath(), "dist", "live2d", "UG", "icon.png"),
    path.join(app.getAppPath(), "public", "live2d", "UG", "icon.png"),
  ];

  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function createTray() {
  if (tray) {
    return;
  }

  const iconPath = findTrayIconPath();
  if (!iconPath) {
    return;
  }

  const icon = nativeImage.createFromPath(iconPath);
  if (icon.isEmpty()) {
    return;
  }

  tray = new Tray(icon.resize({ width: 16, height: 16 }));
  tray.setToolTip("桌面记忆助手");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "显示桌宠", click: () => createPetWindow() },
      { label: "打开控制台", click: showControlWindow },
      { type: "separator" },
      {
        label: "退出应用",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", () => createPetWindow());
}

function findBackendDirectory() {
  const packagedResourcesPath =
    typeof process.resourcesPath === "string" ? process.resourcesPath : null;
  const candidates = [
    process.env.AGENT_PET_BACKEND_DIR,
    packagedResourcesPath ? path.join(packagedResourcesPath, "backend") : null,
    packagedResourcesPath ? path.join(packagedResourcesPath, "sidecar") : null,
    path.resolve(app.getAppPath(), "..", "backend"),
    path.resolve(app.getAppPath(), "..", "sidecar"),
    path.resolve(process.cwd(), "..", "backend"),
    path.resolve(__dirname, "..", "..", "backend"),
  ]
    .filter(Boolean)
    .map((candidate) => path.resolve(candidate));

  for (const candidate of candidates) {
    if (fs.existsSync(path.join(candidate, "app", "main.py"))) {
      return candidate;
    }
  }

  return null;
}

function getPublicSidecarStatus() {
  return { ...sidecarStatus };
}

function getSidecarEnvironment() {
  const env = {
    ...process.env,
    AGENT_PET_SESSION_TOKEN: sessionToken,
  };

  if (!env.AGENT_PET_DATA_DIR && !env.AGENT_PET_SQLITE_PATH) {
    env.AGENT_PET_DATA_DIR = managedSidecarDataDir;
  }

  return env;
}

function showReminderNotification(payload) {
  const reminderId = typeof payload?.reminder_id === "string" ? payload.reminder_id.trim() : "";
  if (!reminderId) {
    return {
      status: "failed",
      reason: "missing_reminder_id",
    };
  }
  if (deliveredReminderNotifications.has(reminderId)) {
    return {
      status: "duplicate",
      reminder_id: reminderId,
    };
  }
  if (!Notification.isSupported()) {
    return {
      status: "unsupported",
      reminder_id: reminderId,
    };
  }

  const title = typeof payload?.title === "string" && payload.title.trim()
    ? payload.title.trim()
    : "桌面记忆助手提醒";
  const body = typeof payload?.body === "string" && payload.body.trim()
    ? payload.body.trim()
    : "有一条提醒已到期。";
  const notification = new Notification({ title, body });
  notification.on("click", showControlWindow);
  notification.show();
  deliveredReminderNotifications.add(reminderId);
  return {
    status: "shown",
    reminder_id: reminderId,
  };
}

function setSidecarStatus(patch) {
  sidecarStatus = {
    ...sidecarStatus,
    ...patch,
    updatedAt: new Date().toISOString(),
  };

  for (const window of BrowserWindow.getAllWindows()) {
    window.webContents.send("agent-pet:sidecar-status-changed", getPublicSidecarStatus());
  }
}

function isPortAvailable(host, port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();

    server.once("error", (error) => {
      if (error.code === "EADDRINUSE") {
        resolve(false);
        return;
      }
      reject(error);
    });

    server.once("listening", () => {
      server.close(() => resolve(true));
    });

    server.listen(port, host);
  });
}

async function waitForSidecarReady(signal) {
  const deadline = Date.now() + 30_000;
  let lastError = null;

  while (Date.now() < deadline) {
    if (signal.aborted) {
      throw new Error("Sidecar readiness wait was aborted.");
    }

    try {
      const health = await requestJson(`${SIDECAR_BASE_URL}/api/health`, signal);
      if (health && typeof health.status === "string") {
        return health;
      }
    } catch (error) {
      lastError = error;
    }

    await delay(250, signal);
  }

  const message = lastError?.message ? ` Last error: ${lastError.message}` : "";
  throw new Error(`Timed out waiting for sidecar health readiness.${message}`);
}

function requestJson(url, signal) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { signal, timeout: 2_000 }, (response) => {
      let body = "";

      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`Health check returned HTTP ${response.statusCode}.`));
          return;
        }

        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });

    request.on("timeout", () => {
      request.destroy(new Error("Health check timed out."));
    });
    request.on("error", reject);
  });
}

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(resolve, ms);

    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timeout);
        reject(new Error("Delay was aborted."));
      },
      { once: true },
    );
  });
}

async function startSidecar() {
  if (sidecarProcess) {
    return;
  }

  setSidecarStatus({
    state: "checking-port",
    managed: false,
    pid: null,
    health: null,
    error: null,
  });

  let portAvailable = false;
  try {
    portAvailable = await isPortAvailable(SIDECAR_HOST, SIDECAR_PORT);
  } catch (error) {
    console.error("Unable to check FastAPI sidecar port.", error);
    setSidecarStatus({
      state: "error",
      health: null,
      error: {
        code: "PORT_CHECK_FAILED",
        message: error.message,
      },
    });
    return;
  }

  if (!portAvailable) {
    try {
      const health = await requestJson(`${SIDECAR_BASE_URL}/api/health`, AbortSignal.timeout(2_000));
      setSidecarStatus({
        state: "ready",
        managed: false,
        pid: null,
        health,
        error: {
          code: "PORT_IN_USE_EXISTING_BACKEND",
          message: `端口 ${SIDECAR_PORT} 已有后端响应，已复用现有后端。若业务请求返回 401，请关闭占用进程后重启，或用相同 AGENT_PET_SESSION_TOKEN 启动后端。`,
        },
      });
    } catch (error) {
      setSidecarStatus({
        state: "error",
        managed: false,
        pid: null,
        health: null,
        error: {
          code: "PORT_IN_USE",
          message: `端口 ${SIDECAR_PORT} 已被占用，但没有响应 /api/health。请关闭占用 8765 的进程，或把后端改到桌面端约定端口后重启 npm run electron:dev。原始错误：${error.message}`,
        },
      });
    }
    return;
  }

  const backendDirectory = findBackendDirectory();
  if (!backendDirectory) {
    console.error("Unable to locate FastAPI sidecar directory.");
    setSidecarStatus({
      state: "error",
      health: null,
      error: {
        code: "BACKEND_NOT_FOUND",
        message: "未找到后端目录。请确认 apps/backend/app/main.py 存在，或设置 AGENT_PET_BACKEND_DIR 指向后端目录后重启。",
      },
    });
    return;
  }

  const pythonCommand =
    process.env.AGENT_PET_PYTHON || (process.platform === "win32" ? "python" : "python3");

  setSidecarStatus({
    state: "starting",
    managed: true,
    pid: null,
    health: null,
    error: null,
  });

  sidecarProcess = spawn(
    pythonCommand,
    ["-m", "uvicorn", "app.main:app", "--host", SIDECAR_HOST, "--port", String(SIDECAR_PORT)],
    {
      cwd: backendDirectory,
      env: getSidecarEnvironment(),
      stdio: "inherit",
      windowsHide: true,
    },
  );

  setSidecarStatus({
    state: "starting",
    managed: true,
    pid: sidecarProcess.pid ?? null,
    health: null,
    error: null,
  });

  sidecarReadinessAbort?.abort();
  sidecarReadinessAbort = new AbortController();
  waitForSidecarReady(sidecarReadinessAbort.signal)
    .then((health) => {
      if (!sidecarProcess || sidecarReadinessAbort?.signal.aborted) {
        return;
      }

      setSidecarStatus({
        state: "ready",
        managed: true,
        pid: sidecarProcess.pid ?? null,
        error: null,
        health,
      });
    })
    .catch((error) => {
      if (sidecarReadinessAbort?.signal.aborted || isQuitting) {
        return;
      }

      console.error("FastAPI sidecar did not become ready.", error);
      const readinessError = {
        code: "READINESS_FAILED",
        message: `后端进程已启动但健康检查未通过。请检查 Python 依赖、数据库配置和控制台日志。原始错误：${error.message}`,
      };
      sidecarExitErrorOverride = readinessError;
      setSidecarStatus({
        state: "error",
        managed: true,
        pid: sidecarProcess?.pid ?? null,
        health: null,
        error: readinessError,
      });
      stopSidecar();
    });

  sidecarProcess.on("exit", (code, signal) => {
    sidecarReadinessAbort?.abort();
    sidecarReadinessAbort = null;
    if (code && code !== 0) {
      console.error(`FastAPI sidecar exited with code ${code}.`);
    } else if (signal) {
      console.error(`FastAPI sidecar exited after signal ${signal}.`);
    }
    sidecarProcess = null;
    const exitErrorOverride = sidecarExitErrorOverride;
    sidecarExitErrorOverride = null;
    setSidecarStatus({
      state: isQuitting ? "stopped" : "error",
      managed: false,
      pid: null,
      health: null,
      error: isQuitting
        ? null
        : exitErrorOverride ?? {
            code: "PROCESS_EXITED",
            message: signal
              ? `后端进程收到 ${signal} 后退出。请查看启动日志。`
              : `后端进程退出，退出码 ${code ?? 0}。请查看启动日志。`,
          },
    });
  });

  sidecarProcess.on("error", (error) => {
    console.error("Failed to start FastAPI sidecar.", error);
    sidecarReadinessAbort?.abort();
    sidecarReadinessAbort = null;
    sidecarProcess = null;
    setSidecarStatus({
      state: "error",
      managed: false,
      pid: null,
      health: null,
      error: {
        code: "SPAWN_FAILED",
        message: `无法启动后端进程。请确认 Python/uvicorn 可用，或设置 AGENT_PET_PYTHON。原始错误：${error.message}`,
      },
    });
  });
}

function stopSidecar() {
  if (!sidecarProcess) {
    return;
  }

  const child = sidecarProcess;
  sidecarProcess = null;
  sidecarReadinessAbort?.abort();
  sidecarReadinessAbort = null;
  setSidecarStatus({
    state: "stopping",
    pid: child.pid ?? null,
    health: null,
    error: null,
  });

  if (!child.killed) {
    child.kill();
  }
}

function normalizeRendererUiStateKey(key) {
  if (typeof key !== "string") {
    return null;
  }
  const normalized = key.trim();
  return allowedRendererUiStateKeys.has(normalized) ? normalized : null;
}

ipcMain.on("agent-pet:get-sidecar-config", (event) => {
  event.returnValue = {
    baseUrl: SIDECAR_BASE_URL,
    sessionToken,
    dataDir: managedSidecarDataDir,
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

ipcMain.handle("agent-pet:get-sidecar-status", () => getPublicSidecarStatus());

ipcMain.handle("agent-pet:show-reminder-notification", (_event, payload) => showReminderNotification(payload));

ipcMain.handle("agent-pet:get-window-mode", (event) => {
  if (petWindow && event.sender === petWindow.webContents) {
    return "pet";
  }
  return "control";
});

ipcMain.handle("agent-pet:open-control-window", (_event, targetId) => {
  showControlWindow(targetId);
});

ipcMain.handle("agent-pet:get-pet-mouse-passthrough-status", (event) => {
  if (!petWindow || event.sender !== petWindow.webContents) {
    return getPetMousePassthroughStatus("ignored_sender", false);
  }

  return updatePetMousePassthroughFromCursor();
});

ipcMain.on("agent-pet:begin-pet-window-drag", (event) => {
  if (!petWindow || event.sender !== petWindow.webContents) {
    return;
  }

  setPetMousePassthrough(false, "begin_drag");
  const cursor = screen.getCursorScreenPoint();
  const bounds = petWindow.getBounds();
  petDragState = {
    active: false,
    startX: cursor.x,
    startY: cursor.y,
    offsetX: clampNumber(cursor.x - bounds.x, 0, PET_WINDOW_WIDTH),
    offsetY: clampNumber(cursor.y - bounds.y, 0, PET_WINDOW_HEIGHT),
    lastX: bounds.x,
    lastY: bounds.y,
  };
  enforcePetWindowSize();
});

ipcMain.on("agent-pet:activate-pet-window-drag", (event) => {
  if (!petWindow || event.sender !== petWindow.webContents || !petDragState) {
    return;
  }

  setPetMousePassthrough(false, "activate_drag");
  petDragState.active = true;
  movePetWindowFromCursor();
  if (!petDragTimer) {
    petDragTimer = setInterval(movePetWindowFromCursor, 16);
  }
  if (!petDragWatchdog) {
    petDragWatchdog = setTimeout(() => {
      clearPetWindowDrag();
      petWindow?.webContents.send("agent-pet:cancel-pet-drag");
      updatePetMousePassthroughFromCursor();
    }, 15000);
  }
});

ipcMain.on("agent-pet:end-pet-window-drag", (event) => {
  if (petWindow && event.sender !== petWindow.webContents) {
    return;
  }

  clearPetWindowDrag();
  enforcePetWindowSize();
  updatePetMousePassthroughFromCursor();
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

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  startSidecar();
  createPetWindow();
  createTray();
  globalShortcut.register("CommandOrControl+Shift+A", showControlWindow);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createPetWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (isQuitting && process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  clearPetWindowDrag();
  stopSidecar();
});

app.on("quit", () => {
  clearPetWindowDrag();
  globalShortcut.unregisterAll();
  sidecarReadinessAbort?.abort();
  sidecarReadinessAbort = null;
});
