const { EventEmitter } = require("node:events");
const Module = require("node:module");

const sidecarPath = require.resolve("./sidecar.js");
const originalModuleLoad = Module._load;

function createElectronMock({ notificationsSupported = false } = {}) {
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
      { isSupported: vi.fn(() => notificationsSupported) },
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

function createPortSearchServerMock(occupiedPorts) {
  return {
    createServer: vi.fn(() => {
      const server = new EventEmitter();
      server.listen = vi.fn((port) => {
        queueMicrotask(() => {
          if (occupiedPorts.has(port)) {
            const error = new Error("address already in use");
            error.code = "EADDRINUSE";
            server.emit("error", error);
            return;
          }
          server.emit("listening");
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

function createHealthyHttpMock(healthPayload = { status: "ok" }) {
  return {
    get: vi.fn((_url, _options, callback) => {
      const request = new EventEmitter();
      request.destroy = vi.fn();
      const response = new EventEmitter();
      response.statusCode = 200;
      response.setEncoding = vi.fn();
      queueMicrotask(() => {
        callback(response);
        response.emit("data", JSON.stringify(healthPayload));
        response.emit("end");
      });
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

  it("reports PORT_IN_USE when the preferred and all fallback ports are occupied by non-backends", async () => {
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

  it("reuses a foreign healthy backend as degraded instead of ready", async () => {
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": createChildProcessMock(),
      "node:fs": { existsSync: vi.fn(() => true) },
      "node:http": createHealthyHttpMock({ status: "ok" }),
      "node:net": createServerMock(false),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();

    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "degraded",
      managed: false,
      pid: null,
      port: 8765,
      health: { status: "ok" },
      error: {
        code: "PORT_IN_USE_EXISTING_BACKEND",
      },
    });
  });

  it("searches upward for a free port when the preferred one is blocked by a non-backend", async () => {
    const childProcess = createChildProcessMock();
    const runtime = { host: "127.0.0.1", port: 8765, baseUrl: "http://127.0.0.1:8765" };
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": { existsSync: vi.fn(() => true) },
      "node:http": createFailingHttpMock("not a backend"),
      "node:net": createPortSearchServerMock(new Set([8765, 8766])),
    });
    const manager = createManager(createSidecarManager, { runtime });

    await manager.startSidecar();
    await flushMicrotasks();

    expect(childProcess.spawn).toHaveBeenCalledWith(
      expect.any(String),
      ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8767"],
      expect.objectContaining({
        env: expect.objectContaining({ AGENT_PET_BACKEND_PORT: "8767" }),
      }),
    );
    // 共享运行时被就地更新，proxy/get-sidecar-config 会跟着切换。
    expect(runtime).toMatchObject({ port: 8767, baseUrl: "http://127.0.0.1:8767" });
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "starting",
      managed: true,
      pid: 4321,
      port: 8767,
      baseUrl: "http://127.0.0.1:8767",
    });

    // 停掉就绪轮询，避免真实定时器泄漏到后续测试。
    manager.stopSidecar();
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

  it("reports READINESS_TIMEOUT after the deadline but keeps the backend running and keeps waiting", async () => {
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
    // 超时只提示，不杀正在冷启动的进程。
    const child = childProcess.spawn.mock.results[0].value;
    expect(child.kill).not.toHaveBeenCalled();
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "starting",
      managed: true,
      pid: 4321,
      health: null,
      error: {
        code: "READINESS_TIMEOUT",
      },
    });

    // 超时后不放弃：状态保持 starting，轮询继续（1s 慢频率）。
    expect(childProcess.spawn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5_000);
    expect(manager.getPublicSidecarStatus().state).toBe("starting");
  });

  it("dedupes reminder notifications and evicts the oldest ids beyond the cap", async () => {
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock({ notificationsSupported: true }),
      "node:child_process": createChildProcessMock(),
      "node:fs": { existsSync: vi.fn(() => true) },
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    expect(manager.showReminderNotification({ reminder_id: "reminder-0", title: "t" }).status).toBe("shown");
    expect(manager.showReminderNotification({ reminder_id: "reminder-0", title: "t" }).status).toBe("duplicate");

    for (let index = 1; index <= 500; index += 1) {
      expect(manager.showReminderNotification({ reminder_id: `reminder-${index}`, title: "t" }).status).toBe("shown");
    }

    // 集合上限 500：最早的 reminder-0 已被逐出，可再次投递；新近的仍然去重。
    expect(manager.showReminderNotification({ reminder_id: "reminder-0", title: "t" }).status).toBe("shown");
    expect(manager.showReminderNotification({ reminder_id: "reminder-500", title: "t" }).status).toBe("duplicate");
  });
});
