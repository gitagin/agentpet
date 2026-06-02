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
    vi.restoreAllMocks();
    delete require.cache[windowsPath];
    Module._load = originalModuleLoad;
  });

  it("hides and reuses the stage window when the user closes it", () => {
    const electron = createElectronMock();
    const { createWindowManager } = loadWindowsWithMocks({ electron });
    const state = { isQuitting: false };
    const manager = createManager(createWindowManager, state);

    const stageWindow = manager.createStageWindow();
    const closeEvent = { preventDefault: vi.fn() };
    stageWindow.emit("close", closeEvent);

    expect(closeEvent.preventDefault).toHaveBeenCalledOnce();
    expect(stageWindow.hide).toHaveBeenCalledOnce();

    const reopenedWindow = manager.createStageWindow();

    expect(reopenedWindow).toBe(stageWindow);
    expect(electron.BrowserWindow).toHaveBeenCalledOnce();
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
    openShortcut("打开设置");

    const stageWindow = manager.getStageWindow();
    expect(stageWindow).toBeTruthy();
    expect(manager.getAgentWindow()).toBeNull();
    expect(manager.getFeatureWindowMode(stageWindow.webContents)).toBeNull();
    expect(electron.BrowserWindow).toHaveBeenCalledTimes(2);
    expect(stageWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-stage-route", "chat");
    expect(stageWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-stage-route", "agent");
    expect(stageWindow.webContents.send).toHaveBeenCalledWith("agent-pet:show-stage-route", "settings");
  });
});
