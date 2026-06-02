const fs = require("node:fs");
const Module = require("node:module");
const os = require("node:os");
const path = require("node:path");

const ipcPath = require.resolve("./ipc.js");
const originalModuleLoad = Module._load;

function createElectronMock() {
  return {
    BrowserWindow: {},
    dialog: {},
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
