const { EventEmitter } = require("node:events");
const Module = require("node:module");

const sidecarPath = require.resolve("./sidecar.js");
const originalModuleLoad = Module._load;

function createElectronMock() {
  return {
    app: {
      getAppPath: vi.fn(() => "/workspace/apps/desktop"),
    },
    BrowserWindow: {
      getAllWindows: vi.fn(() => []),
    },
    Notification: Object.assign(
      vi.fn(function Notification() {
        return { on: vi.fn(), show: vi.fn() };
      }),
      { isSupported: vi.fn(() => false) },
    ),
  };
}

function createServerMock(available) {
  return {
    createServer: vi.fn(() => {
      const server = new EventEmitter();
      server.listen = vi.fn(() => {
        queueMicrotask(() => {
          if (available) {
            server.emit("listening");
            return;
          }

          const error = new Error("address already in use");
          error.code = "EADDRINUSE";
          server.emit("error", error);
        });
      });
      server.close = vi.fn((callback) => callback());
      return server;
    }),
  };
}

function createFailingHttpMock(message = "connection refused") {
  return {
    get: vi.fn((_url, _options, _callback) => {
      const request = new EventEmitter();
      request.destroy = vi.fn((error) => request.emit("error", error));
      queueMicrotask(() => request.emit("error", new Error(message)));
      return request;
    }),
  };
}

function createChildProcessMock() {
  return {
    spawn: vi.fn(() => {
      const child = new EventEmitter();
      child.pid = 4321;
      child.killed = false;
      child.kill = vi.fn(() => {
        child.killed = true;
        queueMicrotask(() => child.emit("exit", 1, null));
      });
      return child;
    }),
  };
}

function loadSidecarWithMocks(mocks) {
  Module._load = function loadMockedModule(request, parent, isMain) {
    if (Object.prototype.hasOwnProperty.call(mocks, request)) {
      return mocks[request];
    }
    return originalModuleLoad.call(this, request, parent, isMain);
  };

  delete require.cache[sidecarPath];
  try {
    return require("./sidecar.js");
  } finally {
    Module._load = originalModuleLoad;
  }
}

function createManager(createSidecarManager, overrides = {}) {
  return createSidecarManager({
    host: "127.0.0.1",
    port: 8765,
    baseUrl: "http://127.0.0.1:8765",
    sessionToken: "test-token",
    managedSidecarDataDir: "/tmp/agent-pet-test",
    state: { isQuitting: false },
    showControlWindow: vi.fn(),
    ...overrides,
  });
}

async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("createSidecarManager", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete require.cache[sidecarPath];
    Module._load = originalModuleLoad;
  });

  it("reports PORT_IN_USE when the port is occupied by a non-health endpoint", async () => {
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": createChildProcessMock(),
      "node:fs": { existsSync: vi.fn(() => true) },
      "node:http": createFailingHttpMock("health endpoint unavailable"),
      "node:net": createServerMock(false),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();

    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "error",
      managed: false,
      pid: null,
      health: null,
      error: {
        code: "PORT_IN_USE",
      },
    });
  });

  it("reports BACKEND_NOT_FOUND when no backend entrypoint exists", async () => {
    const childProcess = createChildProcessMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": { existsSync: vi.fn(() => false) },
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();

    expect(childProcess.spawn).not.toHaveBeenCalled();
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "error",
      health: null,
      error: {
        code: "BACKEND_NOT_FOUND",
      },
    });
  });

  it("reports READINESS_FAILED when the spawned backend never becomes healthy", async () => {
    vi.useFakeTimers();
    const childProcess = createChildProcessMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": { existsSync: vi.fn(() => true) },
      "node:http": createFailingHttpMock("health check failed"),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await vi.advanceTimersByTimeAsync(31_000);
    await flushMicrotasks();

    expect(childProcess.spawn).toHaveBeenCalledWith(
      expect.any(String),
      ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8765"],
      expect.objectContaining({
        cwd: expect.any(String),
        windowsHide: true,
      }),
    );
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "error",
      managed: false,
      pid: null,
      health: null,
      error: {
        code: "READINESS_FAILED",
      },
    });
  });
});
