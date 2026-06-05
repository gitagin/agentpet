const fs = require("node:fs");
const Module = require("node:module");
const os = require("node:os");
const path = require("node:path");

const ipcPath = require.resolve("./ipc.js");
const originalModuleLoad = Module._load;

function createElectronMock() {
  return {
    BrowserWindow: {
      fromWebContents: vi.fn(() => null),
    },
    dialog: {
      showOpenDialog: vi.fn(async () => ({ canceled: true, filePaths: [] })),
    },
    ipcMain: {
      on: vi.fn(),
      handle: vi.fn(),
    },
    shell: {
      openPath: vi.fn(async () => ""),
      showItemInFolder: vi.fn(),
    },
  };
}

function getIpcHandle(electronMock, channel) {
  const call = electronMock.ipcMain.handle.mock.calls.find(([registeredChannel]) => registeredChannel === channel);
  expect(call).toBeTruthy();
  return call[1];
}

function createWindowsMock(roleBySender = new Map()) {
  const petSender = { id: "pet" };
  return {
    petSender,
    getSenderWindowRole: vi.fn((sender) => roleBySender.get(sender) ?? null),
    getFeatureWindowMode: vi.fn(() => "settings"),
    showControlWindow: vi.fn(),
    showAgentWindow: vi.fn(),
    hideAgentWindow: vi.fn(),
    showStageWindow: vi.fn(),
    showFeatureWindow: vi.fn(),
    quitApp: vi.fn(),
    getPetWindow: vi.fn(() => ({ webContents: petSender })),
    getPetMousePassthroughStatus: vi.fn((reason, changed) => ({ enabled: false, reason, changed })),
    updatePetMousePassthroughFromCursor: vi.fn(() => ({ enabled: false, reason: "interactive_region", changed: false })),
    setPetShortcutBarVisible: vi.fn((sender, visible) => ({
      enabled: false,
      reason: sender === petSender ? "interactive_region" : "ignored_sender",
      changed: Boolean(visible) && sender === petSender,
    })),
    setPetInputDockVisible: vi.fn(),
    beginPetWindowDrag: vi.fn(),
    activatePetWindowDrag: vi.fn(),
    endPetWindowDrag: vi.fn(),
  };
}

function registerHandlersForTest({ electronMock = createElectronMock(), windows, proxy, sidecar } = {}) {
  const { registerIpcHandlers } = loadIpcWithMocks(electronMock);
  registerIpcHandlers({
    baseUrl: "http://127.0.0.1:8765",
    rendererUiState: new Map(),
    persistRendererUiState: vi.fn(),
    sidecar: sidecar || { getPublicSidecarStatus: vi.fn(() => ({ status: "ready" })) },
    proxy: proxy || {
      proxyApiRequest: vi.fn(async () => ({ status: 200, body: "{}" })),
      startSseStream: vi.fn(),
      cancelSseStream: vi.fn(),
    },
    windows: windows || createWindowsMock(),
  });
  return { electronMock };
}

function loadIpcWithMocks(electronMock = createElectronMock()) {
  Module._load = function loadMockedModule(request, parent, isMain) {
    if (request === "electron") {
      return electronMock;
    }
    return originalModuleLoad.call(this, request, parent, isMain);
  };

  delete require.cache[ipcPath];
  try {
    return require("./ipc.js");
  } finally {
    Module._load = originalModuleLoad;
  }
}

function createVaultFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agent-pet-vault-"));
  const wikiDir = path.join(root, "Wiki");
  fs.mkdirSync(wikiDir, { recursive: true });
  const target = path.join(wikiDir, "Page.md");
  fs.writeFileSync(target, "# Page\n", "utf-8");
  return { root, target };
}

describe("vault reveal IPC helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[ipcPath];
    Module._load = originalModuleLoad;
  });

  it("normalizes only Vault-relative Markdown paths", () => {
    const { normalizeVaultRelativeMarkdownPath } = loadIpcWithMocks();

    expect(normalizeVaultRelativeMarkdownPath("Wiki/Page.md")).toBe("Wiki/Page.md");
    expect(normalizeVaultRelativeMarkdownPath("Wiki\\Page.md")).toBe("Wiki/Page.md");
    expect(normalizeVaultRelativeMarkdownPath("../Page.md")).toBeNull();
    expect(normalizeVaultRelativeMarkdownPath("C:/Vault/Page.md")).toBeNull();
    expect(normalizeVaultRelativeMarkdownPath(".obsidian/Page.md")).toBeNull();
    expect(normalizeVaultRelativeMarkdownPath("Wiki/Page.txt")).toBeNull();
  });

  it("resolves existing files inside the active Vault and rejects escapes", () => {
    const { root } = createVaultFixture();
    const { resolveVaultMarkdownPath } = loadIpcWithMocks();

    expect(resolveVaultMarkdownPath(root, "Wiki/Page.md")).toMatchObject({
      relativePath: "Wiki/Page.md",
      absolutePath: path.join(root, "Wiki", "Page.md"),
    });
    expect(resolveVaultMarkdownPath(root, "../outside.md")).toBeNull();
  });

  it("opens or shows only files under the active Vault", async () => {
    const { root } = createVaultFixture();
    const shellApi = {
      openPath: vi.fn(async () => ""),
      showItemInFolder: vi.fn(),
    };
    const proxy = {
      proxyApiRequest: vi.fn(async () => ({
        status: 200,
        body: JSON.stringify({ configured: true, root_path: root }),
      })),
    };
    const { revealVaultPath } = loadIpcWithMocks();

    await expect(revealVaultPath({ proxy, relativePath: "Wiki/Page.md", mode: "open", shellApi })).resolves.toMatchObject({
      status: "opened",
      relative_path: "Wiki/Page.md",
    });
    expect(shellApi.openPath).toHaveBeenCalledWith(path.join(root, "Wiki", "Page.md"));

    await expect(revealVaultPath({ proxy, relativePath: "C:/Vault/Page.md", mode: "show", shellApi })).resolves.toMatchObject({
      status: "rejected",
      reason: "invalid_vault_path",
    });
    expect(shellApi.showItemInFolder).not.toHaveBeenCalled();
  });
});

describe("renderer UI state IPC", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[ipcPath];
    Module._load = originalModuleLoad;
  });

  it("persists the pet entry hint state through the invoke handler", async () => {
    const electronMock = createElectronMock();
    const { registerIpcHandlers } = loadIpcWithMocks(electronMock);
    const rendererUiState = new Map();
    const persistRendererUiState = vi.fn();

    registerIpcHandlers({
      baseUrl: "http://127.0.0.1:8765",
      rendererUiState,
      persistRendererUiState,
      sidecar: {},
      proxy: {},
      windows: {},
    });

    const setUiStateCall = electronMock.ipcMain.handle.mock.calls.find(
      ([channel]) => channel === "agent-pet:set-ui-state",
    );
    expect(setUiStateCall).toBeTruthy();

    await setUiStateCall[1]({}, "agent-pet.pet-entry-hint", "completed:v1");

    expect(rendererUiState.get("agent-pet.pet-entry-hint")).toBe("completed:v1");
    expect(persistRendererUiState).toHaveBeenCalledTimes(1);
  });
});

describe("IPC sender authorization", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[ipcPath];
    Module._load = originalModuleLoad;
  });

  it("rejects unknown senders before proxying protected API requests", async () => {
    const electronMock = createElectronMock();
    const sender = { id: "unknown" };
    const proxy = {
      proxyApiRequest: vi.fn(async () => ({ status: 200, body: "{}" })),
      startSseStream: vi.fn(),
      cancelSseStream: vi.fn(),
    };
    const windows = createWindowsMock();

    registerHandlersForTest({ electronMock, windows, proxy });

    const apiRequest = getIpcHandle(electronMock, "agent-pet:api-request");
    await expect(apiRequest({ sender }, "/api/health", { method: "GET" })).rejects.toMatchObject({
      code: "unauthorized_ipc_sender",
      details: {
        channel: "agent-pet:api-request",
        role: "unknown",
      },
    });
    expect(proxy.proxyApiRequest).not.toHaveBeenCalled();
    expect(windows.getSenderWindowRole).toHaveBeenCalledWith(sender);
  });

  it("allows trusted app window senders to call sensitive window and API handlers", async () => {
    const electronMock = createElectronMock();
    const sender = { id: "control" };
    const roleBySender = new Map([[sender, "control"]]);
    const windows = createWindowsMock(roleBySender);
    const proxy = {
      proxyApiRequest: vi.fn(async () => ({ status: 200, body: "{}" })),
      startSseStream: vi.fn(),
      cancelSseStream: vi.fn(),
    };

    registerHandlersForTest({ electronMock, windows, proxy });

    const apiRequest = getIpcHandle(electronMock, "agent-pet:api-request");
    const openStage = getIpcHandle(electronMock, "window:open-stage");

    await expect(apiRequest({ sender }, "/api/health", { method: "GET" })).resolves.toMatchObject({ status: 200 });
    await openStage({ sender }, "settings");

    expect(proxy.proxyApiRequest).toHaveBeenCalledWith("/api/health", { method: "GET" });
    expect(windows.showStageWindow).toHaveBeenCalledWith("settings");
  });

  it("limits knowledge-base folder selection to trusted non-pet app windows", async () => {
    const electronMock = createElectronMock();
    const petSender = { id: "pet" };
    const controlSender = { id: "control" };
    const roleBySender = new Map([
      [petSender, "pet"],
      [controlSender, "control"],
    ]);
    const windows = createWindowsMock(roleBySender);

    registerHandlersForTest({ electronMock, windows });

    const selectKnowledgeBaseFolder = getIpcHandle(electronMock, "agent-pet:select-knowledge-base-folder");
    await expect(selectKnowledgeBaseFolder({ sender: petSender })).rejects.toMatchObject({
      code: "unauthorized_ipc_sender",
      details: {
        channel: "agent-pet:select-knowledge-base-folder",
        role: "pet",
      },
    });
    await expect(selectKnowledgeBaseFolder({ sender: controlSender })).resolves.toBeNull();

    expect(electronMock.dialog.showOpenDialog).toHaveBeenCalledTimes(1);
  });

  it("keeps pet-only hitbox status handlers constrained to the pet sender", async () => {
    const electronMock = createElectronMock();
    const windows = createWindowsMock();
    const unknownSender = { id: "unknown" };

    registerHandlersForTest({ electronMock, windows });

    const getPassthroughStatus = getIpcHandle(electronMock, "agent-pet:get-pet-mouse-passthrough-status");
    expect(getPassthroughStatus({ sender: unknownSender })).toMatchObject({
      reason: "ignored_sender",
    });
    expect(getPassthroughStatus({ sender: windows.petSender })).toMatchObject({
      reason: "interactive_region",
    });

    expect(windows.updatePetMousePassthroughFromCursor).toHaveBeenCalledTimes(1);
  });
});
