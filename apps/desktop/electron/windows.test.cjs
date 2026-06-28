const { EventEmitter } = require("node:events");
const Module = require("node:module");

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

    expect(petWindow.options.transparent).toBe(true);
    expect(petWindow.options.backgroundColor).toBe("#00000000");
    expect(petWindow.options.webPreferences.backgroundThrottling).toBe(false);
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
});
