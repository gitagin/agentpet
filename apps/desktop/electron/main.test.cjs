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

describe("Electron main bootstrap", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[mainPath];
    Module._load = originalModuleLoad;
  });

  it("allows renderer TTS audio to autoplay after async synthesis", () => {
    const app = {
      commandLine: {
        appendSwitch: vi.fn(),
      },
      getPath: vi.fn(() => "C:\\AgentPet"),
      whenReady: vi.fn(() => new Promise(() => undefined)),
      on: vi.fn(),
      quit: vi.fn(),
    };

    loadMainWithMocks({
      electron: {
        app,
        BrowserWindow: {
          getAllWindows: vi.fn(() => []),
        },
        Menu: {
          setApplicationMenu: vi.fn(),
        },
        globalShortcut: {
          register: vi.fn(),
          unregisterAll: vi.fn(),
        },
      },
      "node:fs": {
        readFileSync: vi.fn(() => "{}"),
        mkdirSync: vi.fn(),
        writeFileSync: vi.fn(),
        renameSync: vi.fn(),
      },
      "./windows.js": {
        createWindowManager: vi.fn(() => ({
          createPetWindow: vi.fn(),
          showControlWindow: vi.fn(),
          showStageWindow: vi.fn(),
          showAgentWindow: vi.fn(),
          showFeatureWindow: vi.fn(),
          showPetInputMode: vi.fn(),
          clearPetWindowDrag: vi.fn(),
        })),
      },
      "./tray.js": {
        createTrayManager: vi.fn(() => ({ createTray: vi.fn() })),
      },
      "./sidecar.js": {
        createSidecarManager: vi.fn(() => ({
          startSidecar: vi.fn(),
          stopSidecar: vi.fn(),
          abortSidecarReadiness: vi.fn(),
        })),
      },
      "./proxy.js": {
        createProxyManager: vi.fn(() => ({})),
      },
      "./ipc.js": {
        registerIpcHandlers: vi.fn(),
      },
    });

    expect(app.commandLine.appendSwitch).toHaveBeenCalledWith(
      "autoplay-policy",
      "no-user-gesture-required",
    );
  });
});
