const Module = require("node:module");

const mainPath = require.resolve("./main.cjs");
const originalModuleLoad = Module._load;

function loadMainWithMocks(mocks) {
  Module._load = function loadMockedModule(request, parent, isMain) {
    if (Object.prototype.hasOwnProperty.call(mocks, request)) {
      return mocks[request];
    }
    return originalModuleLoad.call(this, request, parent, isMain);
  };

  delete require.cache[mainPath];
  try {
    require("./main.cjs");
  } finally {
    Module._load = originalModuleLoad;
  }
}

function createBootstrapMocks({
  hasSingleInstanceLock = true,
  existingWindows = [],
  ready = false,
  residentLaunch = false,
} = {}) {
  const appListeners = {};
  const app = {
    commandLine: {
      appendSwitch: vi.fn(),
    },
    getPath: vi.fn(() => "C:\\AgentPet"),
    requestSingleInstanceLock: vi.fn(() => hasSingleInstanceLock),
    whenReady: vi.fn(() => (ready ? Promise.resolve() : new Promise(() => undefined))),
    on: vi.fn((eventName, callback) => {
      appListeners[eventName] = callback;
    }),
    quit: vi.fn(),
  };
  const fs = {
    readFileSync: vi.fn(() => "{}"),
    mkdirSync: vi.fn(),
    writeFileSync: vi.fn(),
    renameSync: vi.fn(),
    rmSync: vi.fn(),
    unlinkSync: vi.fn(),
    rmdirSync: vi.fn(),
  };
  const windows = {
    createPetWindow: vi.fn(),
    showControlWindow: vi.fn(),
    showStageWindow: vi.fn(),
    showAgentWindow: vi.fn(),
    showFeatureWindow: vi.fn(),
    showPetInputMode: vi.fn(),
    clearPetWindowDrag: vi.fn(),
  };
  const sidecar = {
    startSidecar: vi.fn(),
    stopSidecar: vi.fn(),
    abortSidecarReadiness: vi.fn(),
  };
  const createWindowManager = vi.fn(() => windows);
  const createSidecarManager = vi.fn(() => sidecar);
  const tray = { createTray: vi.fn() };
  const createTrayManager = vi.fn(() => tray);
  const createProxyManager = vi.fn(() => ({}));
  const resident = {
    recoverBackendState: vi.fn(),
    handleSidecarReady: vi.fn(),
    startPowerMonitoring: vi.fn(),
    stopPowerMonitoring: vi.fn(),
  };
  const createResidentRuntime = vi.fn(() => resident);
  const isResidentLaunch = vi.fn(() => residentLaunch);
  const dispatchReminderNotification = vi.fn();
  const registerIpcHandlers = vi.fn();
  const clearCache = vi.fn();

  const mocks = {
    electron: {
      app,
      BrowserWindow: {
        getAllWindows: vi.fn(() => existingWindows),
      },
      Menu: {
        setApplicationMenu: vi.fn(),
      },
      globalShortcut: {
        register: vi.fn(),
        unregisterAll: vi.fn(),
      },
      powerMonitor: {},
      session: {
        defaultSession: {
          clearCache,
          webRequest: {
            onHeadersReceived: vi.fn(),
          },
        },
      },
    },
    "node:fs": fs,
    "./windows.js": {
      createWindowManager,
    },
    "./tray.js": {
      createTrayManager,
    },
    "./sidecar.js": {
      createSidecarManager,
    },
    "./proxy.js": {
      createProxyManager,
    },
    "./resident.js": {
      createResidentRuntime,
      isResidentLaunch,
    },
    "./ipc.js": {
      dispatchReminderNotification,
      registerIpcHandlers,
    },
  };

  return {
    app,
    appListeners,
    clearCache,
    createSidecarManager,
    createResidentRuntime,
    createWindowManager,
    dispatchReminderNotification,
    fs,
    mocks,
    registerIpcHandlers,
    resident,
    sidecar,
    tray,
    windows,
  };
}

describe("Electron main bootstrap", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[mainPath];
    Module._load = originalModuleLoad;
  });

  it("allows renderer TTS audio to autoplay after async synthesis", () => {
    const { app, mocks } = createBootstrapMocks();

    loadMainWithMocks(mocks);

    expect(app.commandLine.appendSwitch).toHaveBeenCalledWith(
      "autoplay-policy",
      "no-user-gesture-required",
    );
    expect(app.requestSingleInstanceLock).toHaveBeenCalledOnce();
  });

  it("quits a second main process before creating windows or starting the sidecar", () => {
    const {
      app,
      clearCache,
      createSidecarManager,
      createWindowManager,
      fs,
      mocks,
      registerIpcHandlers,
    } = createBootstrapMocks({ hasSingleInstanceLock: false });

    loadMainWithMocks(mocks);

    expect(app.requestSingleInstanceLock).toHaveBeenCalledOnce();
    expect(app.quit).toHaveBeenCalledOnce();
    expect(app.getPath).not.toHaveBeenCalled();
    expect(app.whenReady).not.toHaveBeenCalled();
    expect(createWindowManager).not.toHaveBeenCalled();
    expect(createSidecarManager).not.toHaveBeenCalled();
    expect(registerIpcHandlers).not.toHaveBeenCalled();
    expect(clearCache).not.toHaveBeenCalled();
    expect(fs.rmSync).not.toHaveBeenCalled();
    expect(fs.unlinkSync).not.toHaveBeenCalled();
    expect(fs.rmdirSync).not.toHaveBeenCalled();
  });

  it("restores and focuses an existing window when a second instance starts", () => {
    const existingWindow = {
      isDestroyed: vi.fn(() => false),
      isMinimized: vi.fn(() => true),
      restore: vi.fn(),
      focus: vi.fn(),
    };
    const { appListeners, mocks, windows } = createBootstrapMocks({
      existingWindows: [existingWindow],
    });

    loadMainWithMocks(mocks);
    appListeners["second-instance"]();

    expect(existingWindow.isMinimized).toHaveBeenCalledOnce();
    expect(existingWindow.restore).toHaveBeenCalledOnce();
    expect(existingWindow.focus).toHaveBeenCalledOnce();
    expect(windows.showControlWindow).not.toHaveBeenCalled();
  });

  it("starts a login resident instance in the tray without opening a visible window", async () => {
    const {
      createResidentRuntime,
      createSidecarManager,
      dispatchReminderNotification,
      mocks,
      resident,
      sidecar,
      tray,
      windows,
    } = createBootstrapMocks({
      ready: true,
      residentLaunch: true,
    });

    loadMainWithMocks(mocks);
    await vi.waitFor(() => {
      expect(sidecar.startSidecar).toHaveBeenCalledOnce();
    });

    expect(tray.createTray).toHaveBeenCalledOnce();
    expect(resident.startPowerMonitoring).toHaveBeenCalledOnce();
    expect(windows.createPetWindow).not.toHaveBeenCalled();
    expect(createResidentRuntime).toHaveBeenCalledWith(expect.objectContaining({
      dispatchReminderNotification,
      sidecar,
    }));
    await createSidecarManager.mock.calls[0][0].onReady();
    expect(resident.handleSidecarReady).toHaveBeenCalledOnce();
  });

  it("opens the pet window during an ordinary interactive launch", async () => {
    const { mocks, sidecar, tray, windows } = createBootstrapMocks({ ready: true });

    loadMainWithMocks(mocks);
    await vi.waitFor(() => {
      expect(sidecar.startSidecar).toHaveBeenCalledOnce();
    });

    expect(tray.createTray).toHaveBeenCalledOnce();
    expect(windows.createPetWindow).toHaveBeenCalledOnce();
  });
});
