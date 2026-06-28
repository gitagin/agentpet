const { app, BrowserWindow, Menu, shell, screen } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const petHitboxConfig = require("../pet-hitbox.json");

const DESKTOP_WINDOW_STATE_FILE = "desktop-window-state.json";
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
const PET_SHORTCUT_BAR_HIT_WIDTH = petHitboxConfig.hitboxes.shortcutBar.width;
const PET_SHORTCUT_BAR_HIT_HEIGHT = petHitboxConfig.hitboxes.shortcutBar.height;
const PET_SHORTCUT_BAR_HIT_RIGHT = petHitboxConfig.hitboxes.shortcutBar.right;
const PET_SHORTCUT_BAR_HIT_BOTTOM = petHitboxConfig.hitboxes.shortcutBar.bottom;
const PET_MOUSE_HIT_TEST_ACTIVE_INTERVAL_MS = 80;
const PET_MOUSE_HIT_TEST_IDLE_INTERVAL_MS = 500;
const PET_MOUSE_HIT_TEST_NEAR_PADDING_PX = 96;
const PET_ENTRY_CAPTURE_GRACE_MS = 2500;
const PET_INPUT_MODES = new Set(["chat", "note", "task", "wiki", "review"]);
function createWindowManager({ devServerUrl, state, quitApp }) {
  let petWindow = null;
  let controlWindow = null;
  let stageWindow = null;
  let agentWindow = null;
  let featureWindow = null;
  let featureWindowMode = "chat";
  let petAlwaysOnTop = true;
  let petDragState = null;
  let petDragTimer = null;
  let petDragWatchdog = null;
  let petMouseHitTestTimer = null;
  let petMouseHitTestIntervalMs = PET_MOUSE_HIT_TEST_ACTIVE_INTERVAL_MS;
  let petMousePassthrough = false;
  let petEntryCaptureActive = false;
  let petEntryCaptureTimer = null;
  let petShortcutBarVisible = false;
  let petInputDockVisible = false;
  let pendingControlTargetId = null;
  let restorePetAfterStageClosed = false;

  function isDevelopment() {
    return !app.isPackaged;
  }

  function normalizeFeatureWindowMode(mode) {
    return ["chat", "memory", "growth", "world", "settings"].includes(mode) ? mode : "chat";
  }

  function normalizePetInputMode(mode) {
    return PET_INPUT_MODES.has(mode) ? mode : "chat";
  }

  function isLiveWindow(window) {
    return Boolean(window && !window.isDestroyed?.());
  }

  function destroyStageWindowForCompanionSwitch() {
    const windowToDestroy = stageWindow;
    if (!isLiveWindow(windowToDestroy)) {
      return;
    }

    restorePetAfterStageClosed = false;
    windowToDestroy.destroy();
  }

  function destroyPetWindowForCompanionSwitch() {
    const windowToDestroy = petWindow;
    if (!isLiveWindow(windowToDestroy)) {
      return;
    }

    clearPetWindowDrag();
    restorePetAfterStageClosed = true;
    persistPetWindowBounds();
    stopPetMouseHitTest();
    clearPetEntryCapture();
    petMousePassthrough = false;
    petShortcutBarVisible = false;
    petInputDockVisible = false;
    windowToDestroy.webContents.send("agent-pet:cancel-pet-drag");
    windowToDestroy.destroy();
  }

  function getSenderWindowRole(sender) {
    if (isLiveWindow(petWindow) && sender === petWindow.webContents) {
      return "pet";
    }
    if (isLiveWindow(controlWindow) && sender === controlWindow.webContents) {
      return "control";
    }
    if (isLiveWindow(stageWindow) && sender === stageWindow.webContents) {
      return "stage";
    }
    if (isLiveWindow(agentWindow) && sender === agentWindow.webContents) {
      return "agent";
    }
    if (isLiveWindow(featureWindow) && sender === featureWindow.webContents) {
      return "feature";
    }
    return null;
  }

  function getFeatureWindowTitle(mode) {
    return {
      chat: "聊天",
      memory: "整理",
      growth: "成长",
      world: "知识库",
      settings: "配置",
    }[normalizeFeatureWindowMode(mode)];
  }

  function getAppEntryUrl(mode) {
    const debugHitboxQuery = mode === "pet" && process.env.AGENT_PET_DEBUG_HITBOX === "1" ? "?hitbox=1" : "";
    if (isDevelopment()) {
      return `${devServerUrl}${debugHitboxQuery}#${mode}`;
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
        ? devServerUrl
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
      || (petInputDockVisible && isPointInRect(localPoint, inputDockRect))
      || isPointInRect(localPoint, chatBubbleRect)
      || (
        petShortcutBarVisible
        && isPointInRect(localPoint, {
          x: PET_WINDOW_WIDTH - PET_SHORTCUT_BAR_HIT_RIGHT - PET_SHORTCUT_BAR_HIT_WIDTH,
          y: PET_WINDOW_HEIGHT - PET_SHORTCUT_BAR_HIT_BOTTOM - PET_SHORTCUT_BAR_HIT_HEIGHT,
          width: PET_SHORTCUT_BAR_HIT_WIDTH,
          height: PET_SHORTCUT_BAR_HIT_HEIGHT,
        })
      )
    );
  }

  function clearPetEntryCapture() {
    petEntryCaptureActive = false;
    if (petEntryCaptureTimer) {
      clearTimeout(petEntryCaptureTimer);
      petEntryCaptureTimer = null;
    }
  }

  function startPetEntryCapture() {
    clearPetEntryCapture();
    petEntryCaptureActive = true;
    petEntryCaptureTimer = setTimeout(() => {
      petEntryCaptureTimer = null;
      petEntryCaptureActive = false;
      updatePetMousePassthroughFromCursor();
      reschedulePetMouseHitTest();
    }, PET_ENTRY_CAPTURE_GRACE_MS);
    petEntryCaptureTimer?.unref?.();
  }

  function isCursorNearPetWindow(cursor, bounds) {
    return cursor.x >= bounds.x - PET_MOUSE_HIT_TEST_NEAR_PADDING_PX
      && cursor.x <= bounds.x + bounds.width + PET_MOUSE_HIT_TEST_NEAR_PADDING_PX
      && cursor.y >= bounds.y - PET_MOUSE_HIT_TEST_NEAR_PADDING_PX
      && cursor.y <= bounds.y + bounds.height + PET_MOUSE_HIT_TEST_NEAR_PADDING_PX;
  }

  function getPetMouseHitTestInterval(cursor, bounds) {
    if (petEntryCaptureActive || petDragState?.active) {
      return PET_MOUSE_HIT_TEST_ACTIVE_INTERVAL_MS;
    }
    if (cursor && bounds && isCursorNearPetWindow(cursor, bounds)) {
      return PET_MOUSE_HIT_TEST_ACTIVE_INTERVAL_MS;
    }
    return PET_MOUSE_HIT_TEST_IDLE_INTERVAL_MS;
  }

  function getDesktopWindowStatePath() {
    return path.join(app.getPath("userData"), DESKTOP_WINDOW_STATE_FILE);
  }

  function readDesktopWindowState() {
    try {
      const text = fs.readFileSync(getDesktopWindowStatePath(), "utf8");
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function writeDesktopWindowState(patch) {
    try {
      const statePath = getDesktopWindowStatePath();
      fs.mkdirSync(path.dirname(statePath), { recursive: true });
      fs.writeFileSync(
        statePath,
        `${JSON.stringify({ ...readDesktopWindowState(), ...patch }, null, 2)}\n`,
        "utf8",
      );
    } catch {
      // Window state persistence must never block the pet window.
    }
  }

  function isFiniteWindowCoordinate(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function getInitialPetWindowBounds() {
    const savedBounds = readDesktopWindowState().petWindowBounds;
    if (
      savedBounds
      && isFiniteWindowCoordinate(savedBounds.x)
      && isFiniteWindowCoordinate(savedBounds.y)
    ) {
      const cursor = {
        x: savedBounds.x + Math.round(PET_WINDOW_WIDTH / 2),
        y: savedBounds.y + Math.round(PET_WINDOW_HEIGHT / 2),
      };
      return clampPetWindowToWorkArea(savedBounds.x, savedBounds.y, cursor);
    }

    const workArea = screen.getPrimaryDisplay().workArea;
    return clampPetWindowToWorkArea(
      workArea.x + workArea.width - PET_WINDOW_WIDTH - 24,
      workArea.y + workArea.height - PET_WINDOW_HEIGHT - 24,
      {
        x: workArea.x + workArea.width,
        y: workArea.y + workArea.height,
      },
    );
  }

  function persistPetWindowBounds() {
    if (!petWindow || petWindow.isDestroyed()) {
      return;
    }
    const bounds = petWindow.getBounds();
    writeDesktopWindowState({
      petWindowBounds: {
        x: bounds.x,
        y: bounds.y,
      },
    });
  }

  function updatePetMousePassthroughFromCursor() {
    if (!petWindow || petWindow.isDestroyed()) {
      petMouseHitTestIntervalMs = PET_MOUSE_HIT_TEST_IDLE_INTERVAL_MS;
      return getPetMousePassthroughStatus("no_pet_window", false);
    }
    if (petEntryCaptureActive) {
      petMouseHitTestIntervalMs = PET_MOUSE_HIT_TEST_ACTIVE_INTERVAL_MS;
      return setPetMousePassthrough(false, "entry_hint_capture");
    }
    if (petDragState?.active) {
      petMouseHitTestIntervalMs = PET_MOUSE_HIT_TEST_ACTIVE_INTERVAL_MS;
      return setPetMousePassthrough(false, "dragging");
    }

    const cursor = screen.getCursorScreenPoint();
    const bounds = petWindow.getBounds();
    const insideInteractiveRegion = isCursorInsidePetInteractiveRegion(cursor, bounds);
    petMouseHitTestIntervalMs = getPetMouseHitTestInterval(cursor, bounds);
    return setPetMousePassthrough(
      !insideInteractiveRegion,
      insideInteractiveRegion ? "interactive_region" : "transparent_area",
    );
  }

  function schedulePetMouseHitTest(delayMs = petMouseHitTestIntervalMs) {
    if (petMouseHitTestTimer || !petWindow || petWindow.isDestroyed()) {
      return;
    }
    petMouseHitTestTimer = setTimeout(() => {
      petMouseHitTestTimer = null;
      updatePetMousePassthroughFromCursor();
      schedulePetMouseHitTest();
    }, delayMs);
    petMouseHitTestTimer?.unref?.();
  }

  function reschedulePetMouseHitTest(delayMs = petMouseHitTestIntervalMs) {
    if (!petMouseHitTestTimer) {
      return;
    }
    clearTimeout(petMouseHitTestTimer);
    petMouseHitTestTimer = null;
    schedulePetMouseHitTest(delayMs);
  }

  function startPetMouseHitTest() {
    if (petMouseHitTestTimer) {
      return;
    }
    schedulePetMouseHitTest();
  }

  function stopPetMouseHitTest() {
    if (!petMouseHitTestTimer) {
      return;
    }
    clearTimeout(petMouseHitTestTimer);
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
    destroyStageWindowForCompanionSwitch();

    if (petWindow && !petWindow.isDestroyed()) {
      petWindow.show();
      petWindow.focus();
      return petWindow;
    }

    petShortcutBarVisible = false;
    startPetEntryCapture();
    const initialBounds = getInitialPetWindowBounds();
    petWindow = new BrowserWindow({
      x: initialBounds.x,
      y: initialBounds.y,
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
        backgroundThrottling: false,
      },
    });

    configureCommonWindow(petWindow);
    enforcePetWindowSize();
    petWindow.setAlwaysOnTop(petAlwaysOnTop, "floating");
    petWindow.once("ready-to-show", () => {
      enforcePetWindowSize();
      petWindow?.show();
      startPetEntryCapture();
      updatePetMousePassthroughFromCursor();
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
    petWindow.on("close", persistPetWindowBounds);
    const currentPetWindow = petWindow;
    petWindow.on("closed", () => {
      clearPetWindowDrag();
      stopPetMouseHitTest();
      clearPetEntryCapture();
      petMousePassthrough = false;
      petShortcutBarVisible = false;
      petInputDockVisible = false;
      if (petWindow === currentPetWindow) {
        petWindow = null;
      }
    });
    petWindow.webContents.on("context-menu", (event) => {
      event.preventDefault();
      clearPetEntryCapture();
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
      if (!state.isQuitting) {
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

  function createStageWindow() {
    destroyPetWindowForCompanionSwitch();

    if (stageWindow && !stageWindow.isDestroyed()) {
      return stageWindow;
    }

    stageWindow = new BrowserWindow({
      width: 1100,
      height: 720,
      minWidth: 900,
      minHeight: 600,
      title: "桌面记忆助手主舞台",
      backgroundColor: "#f7f7f2",
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    });

    configureCommonWindow(stageWindow);
    const currentStageWindow = stageWindow;
    stageWindow.on("close", (event) => {
      if (!state.isQuitting) {
        const shouldRestorePet = restorePetAfterStageClosed;
        restorePetAfterStageClosed = false;
        event.preventDefault();
        if (shouldRestorePet) {
          currentStageWindow.once("closed", () => {
            if (!state.isQuitting) {
              createPetWindow();
            }
          });
        }
        currentStageWindow.destroy();
      }
    });
    stageWindow.on("closed", () => {
      if (stageWindow === currentStageWindow) {
        stageWindow = null;
      }
    });
    loadAppWindow(stageWindow, "/stage");
    return stageWindow;
  }

  function createAgentWindow() {
    if (agentWindow && !agentWindow.isDestroyed()) {
      return agentWindow;
    }

    agentWindow = new BrowserWindow({
      width: 980,
      height: 740,
      minWidth: 760,
      minHeight: 560,
      title: "桌面记忆助手 - 任务",
      alwaysOnTop: false,
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

    configureCommonWindow(agentWindow);
    agentWindow.on("close", (event) => {
      if (!state.isQuitting) {
        event.preventDefault();
        agentWindow?.hide();
      }
    });
    agentWindow.on("closed", () => {
      agentWindow = null;
    });
    loadAppWindow(agentWindow, "/agent");
    return agentWindow;
  }

  function showPetContextMenu() {
    if (!petWindow || petWindow.isDestroyed()) {
      return;
    }
    Menu.buildFromTemplate([
      {
        label: "桌宠输入入口",
        submenu: [
          { label: "聊天", click: () => showPetInputMode("chat") },
          { label: "记一个", click: () => showPetInputMode("note") },
          { label: "新任务", click: () => showPetInputMode("task") },
          { label: "整理 Wiki", click: () => showPetInputMode("wiki") },
          { label: "今日复盘", click: () => showPetInputMode("review") },
        ],
      },
      { type: "separator" },
      { label: "打开主舞台", click: () => showStageRouteWindow("stage") },
      { label: "打开聊天窗口", click: () => showStageRouteWindow("chat") },
      { label: "打开任务工作台", click: () => showStageRouteWindow("agent") },
        { label: "打开记忆整理", click: () => showStageRouteWindow("memory") },
        { label: "打开成长记录", click: () => showStageRouteWindow("growth") },
        { label: "打开知识库", click: () => showStageRouteWindow("world") },
      { label: "打开设置", click: () => showStageRouteWindow("settings") },
      { type: "separator" },
      {
        label: "桌宠置顶",
        type: "checkbox",
        checked: petAlwaysOnTop,
        click: (menuItem) => setPetAlwaysOnTop(menuItem.checked),
      },
      { label: "重载桌宠", click: reloadPetWindow },
      { type: "separator" },
      { label: "退出应用", click: quitApp },
    ]).popup({ window: petWindow });
  }

  function createFeatureWindow(mode) {
    const normalizedMode = normalizeFeatureWindowMode(mode);
    featureWindowMode = normalizedMode;

    if (featureWindow && !featureWindow.isDestroyed()) {
      featureWindow.setTitle(`桌面记忆助手 - ${getFeatureWindowTitle(normalizedMode)}`);
      loadAppWindow(featureWindow, normalizedMode);
      return featureWindow;
    }

    featureWindow = new BrowserWindow({
      width: 980,
      height: 740,
      minWidth: 760,
      minHeight: 560,
      title: `桌面记忆助手 - ${getFeatureWindowTitle(normalizedMode)}`,
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

    configureCommonWindow(featureWindow);
    featureWindow.once("ready-to-show", () => {
      featureWindow?.show();
    });
    featureWindow.on("close", (event) => {
      if (!state.isQuitting) {
        event.preventDefault();
        featureWindow?.hide();
      }
    });
    featureWindow.on("closed", () => {
      featureWindow = null;
    });
    loadAppWindow(featureWindow, normalizedMode);
    return featureWindow;
  }

  function showAgentWindow() {
    const window = createAgentWindow();
    if (window.isMinimized()) {
      window.restore();
    }
    window.show();
    window.focus();
  }

  function showFeatureWindow(mode) {
    const window = createFeatureWindow(mode);
    if (window.isMinimized()) {
      window.restore();
    }
    window.show();
    window.focus();
  }

  function showPetInputMode(mode) {
    const normalizedMode = normalizePetInputMode(mode);
    const window = createPetWindow();
    if (window.isMinimized()) {
      window.restore();
    }
    window.show();
    window.focus();
    const sendMode = () => {
      window.webContents.send("agent-pet:open-pet-input-mode", normalizedMode);
      setPetInputDockVisible(window.webContents, true);
    };
    if (window.webContents.isLoading()) {
      window.webContents.once("did-finish-load", sendMode);
      return;
    }
    sendMode();
  }

  function hideAgentWindow() {
    agentWindow?.hide();
  }

  function showStageRouteWindow(mode = "stage") {
    const window = createStageWindow();
    if (window.isMinimized()) {
      window.restore();
    }
    const routeMode = ["stage", "agent", "chat", "memory", "growth", "world", "settings"].includes(mode) ? mode : "stage";
    const showRoute = () => {
      window.webContents.send("agent-pet:show-stage-route", routeMode);
    };
    if (window.webContents.isLoading()) {
      window.webContents.once("did-finish-load", showRoute);
    } else {
      showRoute();
    }
    window.show();
    window.focus();
  }

  function showStageWindow(mode = "stage") {
    showStageRouteWindow(mode);
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

  function setPetShortcutBarVisible(sender, visible) {
    if (!petWindow || sender !== petWindow.webContents) {
      return getPetMousePassthroughStatus("ignored_sender", false);
    }

    petShortcutBarVisible = Boolean(visible);
    if (petShortcutBarVisible) {
      clearPetEntryCapture();
    }
    const status = updatePetMousePassthroughFromCursor();
    reschedulePetMouseHitTest();
    return status;
  }

  function setPetInputDockVisible(sender, visible) {
    if (!petWindow || sender !== petWindow.webContents) {
      return getPetMousePassthroughStatus("ignored_sender", false);
    }

    petInputDockVisible = Boolean(visible);
    if (petInputDockVisible) {
      clearPetEntryCapture();
    }
    const status = updatePetMousePassthroughFromCursor();
    reschedulePetMouseHitTest();
    return status;
  }

  function beginPetWindowDrag(sender) {
    if (!petWindow || sender !== petWindow.webContents) {
      return;
    }

    setPetMousePassthrough(false, "begin_drag");
    clearPetEntryCapture();
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
  }

  function activatePetWindowDrag(sender) {
    if (!petWindow || sender !== petWindow.webContents || !petDragState) {
      return;
    }

    setPetMousePassthrough(false, "activate_drag");
    petDragState.active = true;
    petMouseHitTestIntervalMs = PET_MOUSE_HIT_TEST_ACTIVE_INTERVAL_MS;
    reschedulePetMouseHitTest();
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
  }

  function endPetWindowDrag(sender) {
    if (petWindow && sender !== petWindow.webContents) {
      return;
    }

    clearPetWindowDrag();
    enforcePetWindowSize();
    persistPetWindowBounds();
    updatePetMousePassthroughFromCursor();
    reschedulePetMouseHitTest();
  }

  return {
    createPetWindow,
    createControlWindow,
    createStageWindow,
    createAgentWindow,
    createFeatureWindow,
    showControlWindow,
    showAgentWindow,
    hideAgentWindow,
    showStageWindow,
    showFeatureWindow,
    showPetInputMode,
    clearPetWindowDrag,
    getPetMousePassthroughStatus,
    updatePetMousePassthroughFromCursor,
    setPetShortcutBarVisible,
    setPetInputDockVisible,
    beginPetWindowDrag,
    activatePetWindowDrag,
    endPetWindowDrag,
    quitApp,
    getSenderWindowRole,
    getPetWindow: () => petWindow,
    getStageWindow: () => stageWindow,
    getAgentWindow: () => agentWindow,
    getFeatureWindowMode: (sender) => {
      if (featureWindow && sender === featureWindow.webContents) {
        return featureWindowMode;
      }
      return null;
    },
  };
}

module.exports = {
  createWindowManager,
};
