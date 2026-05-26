const { app, BrowserWindow, Menu, shell, screen } = require("electron");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const petHitboxConfig = require("../pet-hitbox.json");

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

function createWindowManager({ devServerUrl, state, quitApp }) {
  let petWindow = null;
  let controlWindow = null;
  let petAlwaysOnTop = true;
  let petDragState = null;
  let petDragTimer = null;
  let petDragWatchdog = null;
  let petMouseHitTestTimer = null;
  let petMousePassthrough = false;
  let pendingControlTargetId = null;

  function isDevelopment() {
    return !app.isPackaged;
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
        click: quitApp,
      },
    ]);
    menu.popup({
      window: petWindow ?? undefined,
      callback: () => {
        updatePetMousePassthroughFromCursor();
      },
    });
  }

  function beginPetWindowDrag(sender) {
    if (!petWindow || sender !== petWindow.webContents) {
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
  }

  function activatePetWindowDrag(sender) {
    if (!petWindow || sender !== petWindow.webContents || !petDragState) {
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
  }

  function endPetWindowDrag(sender) {
    if (petWindow && sender !== petWindow.webContents) {
      return;
    }

    clearPetWindowDrag();
    enforcePetWindowSize();
    updatePetMousePassthroughFromCursor();
  }

  return {
    createPetWindow,
    createControlWindow,
    showControlWindow,
    clearPetWindowDrag,
    getPetMousePassthroughStatus,
    updatePetMousePassthroughFromCursor,
    beginPetWindowDrag,
    activatePetWindowDrag,
    endPetWindowDrag,
    getPetWindow: () => petWindow,
  };
}

module.exports = {
  createWindowManager,
};
