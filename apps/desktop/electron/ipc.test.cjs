const fs = require("node:fs");
const Module = require("node:module");
const os = require("node:os");
const path = require("node:path");

const ipcPath = require.resolve("./ipc.js");
const originalModuleLoad = Module._load;
const absoluteMarkdownPath = "C:" + "/Vault/Page.md";

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
    getSenderWindowRole: vi.fn((sender) => (sender === petSender ? "pet" : roleBySender.get(sender) ?? null)),
    getFeatureWindowMode: vi.fn(() => "settings"),
    showControlWindow: vi.fn(),
    showAgentWindow: vi.fn(),
    hideAgentWindow: vi.fn(),
    showStageWindow: vi.fn(),
    showFeatureWindow: vi.fn(),
    hidePetWindow: vi.fn(),
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
    expect(normalizeVaultRelativeMarkdownPath(absoluteMarkdownPath)).toBeNull();
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

    await expect(revealVaultPath({ proxy, relativePath: absoluteMarkdownPath, mode: "show", shellApi })).resolves.toMatchObject({
      status: "rejected",
      reason: "invalid_vault_path",
    });
    expect(shellApi.showItemInFolder).not.toHaveBeenCalled();
  });
});

describe("sidecar config IPC", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[ipcPath];
    Module._load = originalModuleLoad;
  });

  it("returns the live sidecar base URL so port fallback reaches the renderer", () => {
    const electronMock = createElectronMock();
    const { registerIpcHandlers } = loadIpcWithMocks(electronMock);
    let currentBaseUrl = "http://127.0.0.1:8765";
    registerIpcHandlers({
      baseUrl: "http://127.0.0.1:8765",
      getBaseUrl: () => currentBaseUrl,
      rendererUiState: new Map(),
      persistRendererUiState: vi.fn(),
      sidecar: {},
      proxy: {},
      windows: {},
    });

    const call = electronMock.ipcMain.on.mock.calls.find(
      ([channel]) => channel === "agent-pet:get-sidecar-config",
    );
    expect(call).toBeTruthy();
    const handler = call[1];

    const firstEvent = {};
    handler(firstEvent);
    expect(firstEvent.returnValue).toEqual({ baseUrl: "http://127.0.0.1:8765" });

    // 端口搜索切换后端后，同步查询应立刻反映新地址。
    currentBaseUrl = "http://127.0.0.1:8767";
    const secondEvent = {};
    handler(secondEvent);
    expect(secondEvent.returnValue).toEqual({ baseUrl: "http://127.0.0.1:8767" });
  });
});

describe("renderer UI state IPC", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[ipcPath];
    Module._load = originalModuleLoad;
  });

  it("persists allowed renderer UI state through the invoke handler", async () => {
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
    await setUiStateCall[1]({}, "agent-pet.control-home-day-records.v1", "{\"2026-07-02\":{\"journal\":\"ok\",\"goals\":[]}}");

    expect(rendererUiState.get("agent-pet.pet-entry-hint")).toBe("completed:v1");
    expect(rendererUiState.get("agent-pet.control-home-day-records.v1")).toBe("{\"2026-07-02\":{\"journal\":\"ok\",\"goals\":[]}}");
    expect(persistRendererUiState).toHaveBeenCalledTimes(2);
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

  it("only lets the pet renderer hide the pet window", async () => {
    const electronMock = createElectronMock();
    const controlSender = { id: "control" };
    const roleBySender = new Map([[controlSender, "control"]]);
    const windows = createWindowsMock(roleBySender);

    registerHandlersForTest({ electronMock, windows });

    const hidePetWindow = getIpcHandle(electronMock, "agent-pet:hide-pet-window");
    await expect(hidePetWindow({ sender: controlSender })).rejects.toMatchObject({
      code: "unauthorized_ipc_sender",
      details: {
        channel: "agent-pet:hide-pet-window",
        role: "control",
      },
    });
    await expect(hidePetWindow({ sender: windows.petSender })).resolves.toBeUndefined();

    expect(windows.hidePetWindow).toHaveBeenCalledWith(windows.petSender);
    expect(windows.quitApp).not.toHaveBeenCalled();
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

describe("reminder delivery IPC", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete require.cache[ipcPath];
    Module._load = originalModuleLoad;
  });

  function registerReminderHandler({ reservation, receipt, displayResult = { status: "shown" }, receiptError } = {}) {
    const electronMock = createElectronMock();
    const windows = createWindowsMock();
    const sidecar = {
      getPublicSidecarStatus: vi.fn(() => ({ state: "ready" })),
      showReminderNotification: vi.fn((input) => ({
        ...displayResult,
        reminder_id: input.reminder_id,
      })),
    };
    const proxy = {
      proxyApiRequest: vi.fn(async (path) => {
        if (path === "/api/tasks/reminder-delivery/reservations") {
          return { status: 200, body: JSON.stringify(reservation) };
        }
        if (receiptError) {
          throw receiptError;
        }
        return { status: 200, body: JSON.stringify(receipt ?? { status: "recorded" }) };
      }),
      startSseStream: vi.fn(),
      cancelSseStream: vi.fn(),
    };
    registerHandlersForTest({ electronMock, windows, proxy, sidecar });
    return {
      handler: getIpcHandle(electronMock, "agent-pet:show-reminder-notification"),
      sender: windows.petSender,
      proxy,
      sidecar,
    };
  }

  const payload = {
    reminder_id: "reminder-1",
    trigger_at: "2026-08-08T09:00:00Z",
    title: "Review",
    body: "Review the evidence trail",
  };

  it("reserves an automatic attempt before invoking the operating-system notification", async () => {
    const harness = registerReminderHandler({
      reservation: { duplicate: false, attempt_id: "attempt-1", status: "reserved" },
    });

    await expect(harness.handler({ sender: harness.sender }, payload)).resolves.toMatchObject({
      status: "shown",
      reminder_id: "reminder-1",
      attempt_id: "attempt-1",
    });
    expect(harness.proxy.proxyApiRequest).toHaveBeenCalledTimes(2);
    expect(harness.proxy.proxyApiRequest.mock.calls[0][0]).toBe(
      "/api/tasks/reminder-delivery/reservations",
    );
    expect(harness.proxy.proxyApiRequest.mock.calls[0][1]).toMatchObject({
      method: "POST",
      headers: {
        "Idempotency-Key": expect.stringMatching(/^[0-9a-f]{64}$/),
      },
    });
    expect(harness.sidecar.showReminderNotification.mock.invocationCallOrder[0]).toBeGreaterThan(
      harness.proxy.proxyApiRequest.mock.invocationCallOrder[0],
    );
    expect(harness.proxy.proxyApiRequest.mock.calls[1][0]).toBe(
      "/api/tasks/reminder-delivery/attempts/attempt-1/display",
    );
    expect(JSON.parse(harness.proxy.proxyApiRequest.mock.calls[1][1].body)).toMatchObject({
      result_code: "shown",
      error: null,
    });
  });

  it("does not invoke the OS when the reservation is a known duplicate or crash-unknown", async () => {
    const duplicate = registerReminderHandler({
      reservation: { duplicate: true, attempt_id: "attempt-old", status: "display_invoked" },
    });
    await expect(duplicate.handler({ sender: duplicate.sender }, payload)).resolves.toMatchObject({
      status: "duplicate",
      reason: "display_invoked",
    });
    expect(duplicate.sidecar.showReminderNotification).not.toHaveBeenCalled();

    const unknown = registerReminderHandler({
      reservation: { duplicate: true, attempt_id: "attempt-unknown", status: "unknown_after_crash" },
    });
    await expect(unknown.handler({ sender: unknown.sender }, payload)).resolves.toMatchObject({
      status: "unknown",
      reason: "unknown_after_crash",
    });
    expect(unknown.sidecar.showReminderNotification).not.toHaveBeenCalled();
  });

  it("returns unknown when the OS was called but the display receipt cannot be confirmed", async () => {
    const harness = registerReminderHandler({
      reservation: { duplicate: false, attempt_id: "attempt-2", status: "reserved" },
      receiptError: new Error("backend crashed after display"),
    });

    await expect(harness.handler({ sender: harness.sender }, payload)).resolves.toMatchObject({
      status: "unknown",
      reminder_id: "reminder-1",
      attempt_id: "attempt-2",
      reason: "display_receipt_unconfirmed",
    });
    expect(harness.sidecar.showReminderNotification).toHaveBeenCalledOnce();
  });

  it("records unsupported and API-failed display attempts without claiming delivery", async () => {
    const unsupported = registerReminderHandler({
      reservation: { duplicate: false, attempt_id: "attempt-unsupported", status: "reserved" },
      displayResult: { status: "unsupported", reason: "notification_unsupported" },
    });
    await expect(unsupported.handler({ sender: unsupported.sender }, payload)).resolves.toMatchObject({
      status: "unsupported",
      reason: "notification_unsupported",
    });
    expect(JSON.parse(unsupported.proxy.proxyApiRequest.mock.calls[1][1].body)).toMatchObject({
      result_code: "unsupported",
      error: "notification_unsupported",
    });

    const failed = registerReminderHandler({
      reservation: { duplicate: false, attempt_id: "attempt-failed", status: "reserved" },
      displayResult: { status: "failed", reason: "notification_api_failed" },
    });
    await expect(failed.handler({ sender: failed.sender }, payload)).resolves.toMatchObject({
      status: "failed",
      reason: "notification_api_failed",
    });
    expect(JSON.parse(failed.proxy.proxyApiRequest.mock.calls[1][1].body)).toMatchObject({
      result_code: "failed",
      error: "notification_api_failed",
    });
  });

  it("keeps the reminder untouched when reservation fails", async () => {
    const electronMock = createElectronMock();
    const windows = createWindowsMock();
    const sidecar = { showReminderNotification: vi.fn() };
    const proxy = {
      proxyApiRequest: vi.fn(async () => {
        throw new Error("sqlite unavailable");
      }),
      startSseStream: vi.fn(),
      cancelSseStream: vi.fn(),
    };
    registerHandlersForTest({ electronMock, windows, proxy, sidecar });
    const handler = getIpcHandle(electronMock, "agent-pet:show-reminder-notification");

    await expect(handler({ sender: windows.petSender }, payload)).rejects.toThrow("sqlite unavailable");
    expect(sidecar.showReminderNotification).not.toHaveBeenCalled();
  });
});
