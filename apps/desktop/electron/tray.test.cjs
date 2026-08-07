const Module = require("node:module");

const trayPath = require.resolve("./tray.js");
const originalModuleLoad = Module._load;

function loadTrayWithMocks(mocks) {
  Module._load = function loadMockedModule(request, parent, isMain) {
    if (Object.prototype.hasOwnProperty.call(mocks, request)) {
      return mocks[request];
    }
    return originalModuleLoad.call(this, request, parent, isMain);
  };

  delete require.cache[trayPath];
  try {
    return require("./tray.js");
  } finally {
    Module._load = originalModuleLoad;
  }
}

describe("createTrayManager", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[trayPath];
    Module._load = originalModuleLoad;
  });

  it("routes every page action through the reusable stage window", () => {
    let menuTemplate = null;
    const tray = {
      setToolTip: vi.fn(),
      setContextMenu: vi.fn(),
      on: vi.fn(),
    };
    const electron = {
      app: {
        getAppPath: vi.fn(() => "E:\\agentproject\\apps\\desktop"),
      },
      Menu: {
        buildFromTemplate: vi.fn((template) => {
          menuTemplate = template;
          return template;
        }),
      },
      Tray: vi.fn(() => tray),
      nativeImage: {
        createFromPath: vi.fn(() => ({
          isEmpty: vi.fn(() => false),
          resize: vi.fn(() => "tray-icon"),
        })),
      },
    };
    const { createTrayManager } = loadTrayWithMocks({
      electron,
      "node:fs": { existsSync: vi.fn(() => true) },
    });
    const showStageWindow = vi.fn();
    const manager = createTrayManager({
      createPetWindow: vi.fn(),
      showStageWindow,
      showPetInputMode: vi.fn(),
      quitApp: vi.fn(),
    });

    manager.createTray();

    const expectedRoutes = new Map([
      ["打开主舞台", "stage"],
      ["打开聊天窗口", "chat"],
      ["打开任务工作台", "agent"],
      ["打开记忆整理", "memory"],
      ["打开成长记录", "growth"],
      ["打开知识库", "world"],
      ["打开设置", "settings"],
      ["打开控制台", "stage"],
    ]);

    for (const [label, route] of expectedRoutes) {
      const menuItem = menuTemplate.find((item) => item.label === label);
      expect(menuItem).toBeTruthy();
      menuItem.click();
      expect(showStageWindow).toHaveBeenLastCalledWith(route);
    }

    expect(showStageWindow).toHaveBeenCalledTimes(expectedRoutes.size);
  });
});
