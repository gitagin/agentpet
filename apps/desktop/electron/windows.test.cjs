const { EventEmitter } = require("node:events");
const Module = require("node:module");
const petHitboxConfig = require("../pet-hitbox.json");

const windowsPath = require.resolve("./windows.js");
const originalModuleLoad = Module._load;

function createElectronMock() {
  const windows = [];

  const BrowserWindow = vi.fn(function BrowserWindow(options) {
    const window = new EventEmitter();
    window.options = options;
    window.hidden = false;
    window.minimized = false;
    window.destroyed = false;
    window.webContents = new EventEmitter();
    window.webContents.setWindowOpenHandler = vi.fn();
    window.webContents.session = {
      setPermissionRequestHandler: vi.fn(),
    };
    window.webContents.send = vi.fn();
    window.webContents.isLoading = vi.fn(() => false);
    window.webContents.once = vi.fn();
    window.loadURL = vi.fn();
    window.loadFile = vi.fn();
    window.setTitle = vi.fn();
    window.isDestroyed = vi.fn(() => window.destroyed);
    window.isMinimized = vi.fn(() => window.minimized);
    window.setMinimumSize = vi.fn();
    window.setMaximumSize = vi.fn();
    window.setResizable = vi.fn();
    window.getBounds = vi.fn(() => ({
      x: options.x || 0,
      y: options.y || 0,
      width: options.width || 0,
      height: options.height || 0,
    }));
    window.getPosition = vi.fn(() => [0, 0]);
    window.getSize = vi.fn(() => [options.width || 0, options.height || 0]);
    window.setBounds = vi.fn();
    window.setAlwaysOnTop = vi.fn();
    window.setIgnoreMouseEvents = vi.fn();
    window.restore = vi.fn(() => {
      window.minimized = false;
    });
    window.show = vi.fn();
    window.focus = vi.fn();
    window.hide = vi.fn(() => {
      window.hidden = true;
    });
    window.destroy = vi.fn(() => {
      if (window.destroyed) {
        return;
      }
      window.destroyed = true;
      window.emit("closed");
    });
    windows.push(window);
    return window;
  });

  return {
    app: {
      isPackaged: false,
      getAppPath: vi.fn(() => "/workspace/apps/desktop"),
    },
    BrowserWindow,
    Menu: {
      buildFromTemplate: vi.fn((template) => Object.assign(template, { popup: vi.fn() })),
      setApplicationMenu: vi.fn(),
    },
    shell: {
      openExternal: vi.fn(),
    },
    screen: {
      getCursorScreenPoint: vi.fn(() => ({ x: 0, y: 0 })),
      getDisplayMatching: vi.fn(() => ({
        scaleFactor: 1,
        workArea: { x: 0, y: 0, width: 1920, height: 1080 },
      })),
      getPrimaryDisplay: vi.fn(() => ({
        workArea: { x: 0, y: 0, width: 1920, height: 1080 },
      })),
      getDisplayNearestPoint: vi.fn(() => ({
        workArea: { x: 0, y: 0, width: 1920, height: 1080 },
      })),
    },
    windows,
  };
}

function loadWindowsWithMocks(mocks) {
  Module._load = function loadMockedModule(request, parent, isMain) {
    if (Object.prototype.hasOwnProperty.call(mocks, request)) {
      return mocks[request];
    }
    return originalModuleLoad.call(this, request, parent, isMain);
  };

  delete require.cache[windowsPath];
  try {
    return require("./windows.js");
  } finally {
    Module._load = originalModuleLoad;
  }
}

function createManager(createWindowManager, state) {
  return createWindowManager({
    devServerUrl: "http://127.0.0.1:5173",
    state,
    quitApp: vi.fn(),
  });
}

describe("createWindowManager stage window lifecycle", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete require.cache[windowsPath];
    Module._load = originalModuleLoad;
  });

  it("destroys and recreates the stage window when the user closes it", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const stageWindow = manager.createStageWindow();
    const closeEvent = { preventDefault: vi.fn() };
    stageWindow.emit("close", closeEvent);

    expect(closeEvent.preventDefault).toHaveBeenCalledOnce();
    expect(stageWindow.hide).not.toHaveBeenCalled();
    expect(stageWindow.destroy).toHaveBeenCalledOnce();

    const reopenedWindow = manager.createStageWindow();

    expect(reopenedWindow).not.toBe(stageWindow);
    expect(electron.BrowserWindow).toHaveBeenCalledTimes(2);
  });

  it("lets the stage window close during app shutdown", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: true };
    const manager = createManager(createWindowManager, state);

    const stageWindow = manager.createStageWindow();
    const closeEvent = { preventDefault: vi.fn() };
    stageWindow.emit("close", closeEvent);

    expect(closeEvent.preventDefault).not.toHaveBeenCalled();
    expect(stageWindow.hide).not.toHaveBeenCalled();
    expect(stageWindow.destroy).not.toHaveBeenCalled();

    stageWindow.emit("closed");
    const recreatedWindow = manager.createStageWindow();

    expect(recreatedWindow).not.toBe(stageWindow);
    expect(electron.BrowserWindow).toHaveBeenCalledTimes(2);
  });

  it("asks an existing stage renderer to return to the stage route when shown", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const stageWindow = manager.createStageWindow();
    stageWindow.webContents.send.mockClear();

    manager.showStageWindow();

    expect(stageWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-stage-route", "stage");
    expect(electron.BrowserWindow).toHaveBeenCalledOnce();
  });

  it("opens the control window on the stage home route", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const controlWindow = manager.createControlWindow();

    expect(controlWindow.loadURL).toHaveBeenCalledWith("http://127.0.0.1:5173#stage");
  });

  it("recreates the control window when a stale destroyed reference is left behind", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const controlWindow = manager.createControlWindow();
    // 模拟窗口已被销毁但 closed 回调尚未清空引用的窗口期。
    controlWindow.destroyed = true;

    const recreatedWindow = manager.createControlWindow();

    expect(recreatedWindow).not.toBe(controlWindow);
    expect(electron.BrowserWindow).toHaveBeenCalledTimes(2);
  });

  it("uses bare hash route names for the stage and agent windows", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const stageWindow = manager.createStageWindow();
    const agentWindow = manager.createAgentWindow();

    expect(stageWindow.loadURL).toHaveBeenCalledWith("http://127.0.0.1:5173#stage");
    expect(agentWindow.loadURL).toHaveBeenCalledWith("http://127.0.0.1:5173#agent");
  });

  it("switches a reused feature window over IPC instead of reloading it", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const featureWindow = manager.createFeatureWindow("chat");
    expect(featureWindow.loadURL).toHaveBeenCalledWith("http://127.0.0.1:5173#chat");
    featureWindow.loadURL.mockClear();
    featureWindow.loadFile.mockClear();

    const reusedWindow = manager.createFeatureWindow("settings");

    expect(reusedWindow).toBe(featureWindow);
    expect(electron.BrowserWindow).toHaveBeenCalledOnce();
    expect(featureWindow.loadURL).not.toHaveBeenCalled();
    expect(featureWindow.loadFile).not.toHaveBeenCalled();
    expect(featureWindow.setTitle).toHaveBeenCalledWith("Agent Pet - 配置");
    expect(featureWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-feature-route", "settings");
    expect(manager.getFeatureWindowMode(featureWindow.webContents)).toBe("settings");
  });

  it("blocks cross-origin navigation with a URL origin comparison", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const controlWindow = manager.createControlWindow();

    const sameOriginEvent = { preventDefault: vi.fn() };
    controlWindow.webContents.emit("will-navigate", sameOriginEvent, "http://127.0.0.1:5173/#agent");
    expect(sameOriginEvent.preventDefault).not.toHaveBeenCalled();

    // startsWith 时代的绕过样例：前缀相同但 origin 不同，必须拦截。
    const prefixBypassEvent = { preventDefault: vi.fn() };
    controlWindow.webContents.emit("will-navigate", prefixBypassEvent, "http://127.0.0.1:5173.evil.example/");
    expect(prefixBypassEvent.preventDefault).toHaveBeenCalledOnce();
    expect(electron.shell.openExternal).toHaveBeenCalledWith("http://127.0.0.1:5173.evil.example/");

    const externalEvent = { preventDefault: vi.fn() };
    controlWindow.webContents.emit("will-navigate", externalEvent, "https://example.com/");
    expect(externalEvent.preventDefault).toHaveBeenCalledOnce();
    expect(electron.shell.openExternal).toHaveBeenCalledWith("https://example.com/");
  });

  it("destroys the pet window before showing the stage window", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const petWindow = manager.createPetWindow();

    manager.showStageWindow();

    const stageWindow = manager.getStageWindow();
    expect(stageWindow).toBeTruthy();
    expect(manager.getPetWindow()).toBeNull();
    expect(petWindow.destroy).toHaveBeenCalledOnce();
    expect(electron.BrowserWindow).toHaveBeenCalledTimes(2);
  });

  it("destroys the stage window before showing the pet window", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const stageWindow = manager.createStageWindow();

    const petWindow = manager.createPetWindow();

    expect(petWindow).toBeTruthy();
    expect(manager.getStageWindow()).toBeNull();
    expect(stageWindow.destroy).toHaveBeenCalledOnce();
    expect(electron.BrowserWindow).toHaveBeenCalledTimes(2);
  });

  it("restores the pet window when a stage window that replaced it is closed", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const originalPetWindow = manager.createPetWindow();
    manager.showStageWindow();
    const stageWindow = manager.getStageWindow();

    expect(manager.getPetWindow()).toBeNull();
    expect(originalPetWindow.destroy).toHaveBeenCalledOnce();

    stageWindow.emit("close", { preventDefault: vi.fn() });

    const restoredPetWindow = manager.getPetWindow();
    expect(manager.getStageWindow()).toBeNull();
    expect(restoredPetWindow).toBeTruthy();
    expect(restoredPetWindow).not.toBe(originalPetWindow);
    expect(electron.BrowserWindow).toHaveBeenCalledTimes(3);
  });

  it("reuses the stage window for pet context menu shortcuts", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const petWindow = manager.createPetWindow();
    petWindow.webContents.emit("context-menu", { preventDefault: vi.fn() });
    const menuTemplate = electron.Menu.buildFromTemplate.mock.calls.at(-1)?.[0];
    const openShortcut = (label) => {
      const item = menuTemplate.find((entry) => entry?.label === label);
      expect(item).toBeTruthy();
      item.click();
    };

    openShortcut("打开聊天窗口");
    openShortcut("打开任务工作台");
    openShortcut("打开成长记录");
    openShortcut("打开设置");

    const stageWindow = manager.getStageWindow();
    expect(stageWindow).toBeTruthy();
    expect(manager.getAgentWindow()).toBeNull();
    expect(manager.getFeatureWindowMode(stageWindow.webContents)).toBeNull();
    expect(electron.BrowserWindow).toHaveBeenCalledTimes(2);
    expect(stageWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-stage-route", "chat");
    expect(stageWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-stage-route", "agent");
    expect(stageWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-stage-route", "growth");
    expect(stageWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-stage-route", "settings");
  });

  it("keeps the transparent pet window renderer active while dragging", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const petWindow = manager.createPetWindow();

    expect(petWindow.options.width).toBe(petHitboxConfig.window.width);
    expect(petWindow.options.height).toBe(petHitboxConfig.window.height);
    expect(petWindow.options.frame).toBe(false);
    expect(petWindow.options.transparent).toBe(true);
    expect(petWindow.options.backgroundColor).toBe("#00000000");
    expect(petWindow.options.alwaysOnTop).toBe(true);
    expect(petWindow.options.webPreferences.backgroundThrottling).toBe(false);
  });

  it("hides the pet window without destroying it or quitting the app", () => {
    const electron = createElectronMock();
    const quitApp = vi.fn();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createWindowManager({
      devServerUrl: "http://127.0.0.1:5173",
      state,
      quitApp,
    });

    const petWindow = manager.createPetWindow();
    const result = manager.hidePetWindow(petWindow.webContents);

    expect(result).toBe(true);
    expect(petWindow.hide).toHaveBeenCalledOnce();
    expect(petWindow.destroy).not.toHaveBeenCalled();
    expect(petWindow.webContents.send).toHaveBeenCalledWith("agent-pet:cancel-pet-drag");
    expect(quitApp).not.toHaveBeenCalled();

    const shownAgain = manager.createPetWindow();
    expect(shownAgain).toBe(petWindow);
    expect(petWindow.show).toHaveBeenCalled();
  });

  it("backs off pet mouse hit testing after the startup capture grace period", async () => {
    vi.useFakeTimers();
    const electron = createElectronMock();
    electron.screen.getCursorScreenPoint.mockReturnValue({ x: 10, y: 10 });
    const setTimeoutSpy = vi.spyOn(global, "setTimeout");
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const petWindow = manager.createPetWindow();
    petWindow.emit("ready-to-show");

    expect(setTimeoutSpy).toHaveBeenLastCalledWith(expect.any(Function), 80);
    expect(petWindow.setIgnoreMouseEvents).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(2500);

    expect(petWindow.setIgnoreMouseEvents).toHaveBeenCalledWith(true, { forward: true });
    expect(setTimeoutSpy).toHaveBeenLastCalledWith(expect.any(Function), 500);
  });

  it.each([1, 1.25, 1.5, 2])(
    "keeps the visible pet and hit region pixel-aligned at %sx display scale",
    (scaleFactor) => {
      const electron = createElectronMock();
      electron.screen.getDisplayMatching.mockReturnValue({ scaleFactor });
      const { createWindowManager } = loadWindowsWithMocks({ electron });
      const manager = createManager(createWindowManager, { isQuitting: false });
      const petWindow = manager.createPetWindow();
      const bounds = { x: 240, y: 120, width: petHitboxConfig.window.width, height: petHitboxConfig.window.height };
      petWindow.getBounds.mockReturnValue(bounds);

      const model = petHitboxConfig.hitboxes.model;
      const anchor = petHitboxConfig.layout.anchors.model;
      expect(anchor).toEqual({ horizontal: "center", vertical: "bottom" });
      const localCenter = {
        x: Math.round((petHitboxConfig.window.width - model.width) / 2) + model.width / 2,
        y: petHitboxConfig.window.height - model.bottom - model.height / 2,
      };
      electron.screen.getCursorScreenPoint.mockReturnValue({
        x: bounds.x + localCenter.x,
        y: bounds.y + localCenter.y,
      });

      manager.setPetShortcutBarVisible(false);
      manager.setPetInputDockVisible(false);
      const status = manager.updatePetMousePassthroughFromCursor();

      expect(status.enabled).toBe(false);
      expect(status.displayScaleFactor).toBe(scaleFactor);
      expect(Math.round((electron.screen.getCursorScreenPoint().x - bounds.x) * scaleFactor)).toBe(
        Math.round(localCenter.x * scaleFactor),
      );
      expect(Math.round((electron.screen.getCursorScreenPoint().y - bounds.y) * scaleFactor)).toBe(
        Math.round(localCenter.y * scaleFactor),
      );
    },
  );

  it("preserves the local hit region while crossing displays with different DPI", () => {
    const electron = createElectronMock();
    electron.screen.getDisplayMatching.mockImplementation((bounds) => ({
      scaleFactor: bounds.x < 1920 ? 1.25 : 2,
    }));
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const manager = createManager(createWindowManager, { isQuitting: false });
    const petWindow = manager.createPetWindow();
    const model = petHitboxConfig.hitboxes.model;
    const localPoint = {
      x: Math.round((petHitboxConfig.window.width - model.width) / 2) + model.width / 2,
      y: petHitboxConfig.window.height - model.bottom - model.height / 2,
    };

    for (const display of [
      { bounds: { x: 120, y: 80, width: 560, height: 720 }, scaleFactor: 1.25 },
      { bounds: { x: 2160, y: 160, width: 560, height: 720 }, scaleFactor: 2 },
    ]) {
      petWindow.getBounds.mockReturnValue(display.bounds);
      electron.screen.getCursorScreenPoint.mockReturnValue({
        x: display.bounds.x + localPoint.x,
        y: display.bounds.y + localPoint.y,
      });

      const status = manager.updatePetMousePassthroughFromCursor();

      expect(status.enabled).toBe(false);
      expect(status.displayScaleFactor).toBe(display.scaleFactor);
    }
  });
});
