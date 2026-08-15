const { EventEmitter } = require("node:events");
const Module = require("node:module");
const path = require("node:path");

const sidecarPath = require.resolve("./sidecar.js");
const originalModuleLoad = Module._load;
const originalResourcesPathDescriptor = Object.getOwnPropertyDescriptor(process, "resourcesPath");
const trackedEnvironment = new Map(
  [
    "AGENT_PET_BACKEND_DIR",
    "AGENT_PET_PYTHON",
    "AGENT_PET_READY_TIMEOUT_MS",
    "AGENT_PET_SIDECAR_EXECUTABLE",
  ].map((name) => [name, process.env[name]]),
);

function createElectronMock({
  notificationsSupported = false,
  isPackaged = false,
  notificationError = null,
  supportCheckError = null,
} = {}) {
  return {
    app: {
      isPackaged,
      getAppPath: vi.fn(() => "/workspace/apps/desktop"),
      getPath: vi.fn((name) => {
        if (name === "logs") {
          return "/workspace/logs";
        }
        throw new Error(`unexpected Electron path: ${name}`);
      }),
    },
    BrowserWindow: {
      getAllWindows: vi.fn(() => []),
    },
    Notification: Object.assign(
      vi.fn(function Notification() {
        if (notificationError) {
          throw notificationError;
        }
        return { on: vi.fn(), show: vi.fn() };
      }),
      {
        isSupported: vi.fn(() => {
          if (supportCheckError) {
            throw supportCheckError;
          }
          return notificationsSupported;
        }),
      },
    ),
  };
}

function createFsMock(existsSync = () => true) {
  return {
    existsSync: vi.fn(existsSync),
    mkdirSync: vi.fn(),
    appendFileSync: vi.fn(),
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

function createSessionRejectedHttpMock() {
  return {
    get: vi.fn((url, _options, callback) => {
      const request = new EventEmitter();
      request.destroy = vi.fn((error) => request.emit("error", error));
      const response = new EventEmitter();
      response.statusCode = url.endsWith("/api/health") ? 200 : 401;
      response.setEncoding = vi.fn();
      queueMicrotask(() => {
        callback(response);
        response.emit("data", JSON.stringify({ status: "ok" }));
        response.emit("end");
      });
      return request;
    }),
  };
}

function createMockChild(pid) {
  const child = new EventEmitter();
  child.pid = pid;
  child.killed = false;
  child.exitCode = null;
  child.signalCode = null;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = vi.fn((signal) => {
    child.killed = true;
    child.signalCode = signal ?? null;
    queueMicrotask(() => emitChildExit(child, 1, signal ?? null));
    return true;
  });
  return child;
}

function emitChildExit(child, code = 0, signal = null) {
  child.exitCode = code;
  child.signalCode = signal;
  child.emit("exit", code, signal);
}

function createChildProcessMock({ autoHandshake = true, runtimePort = 8765 } = {}) {
  const backendChildren = [];
  const killerChildren = [];
  let nextPid = 4300;
  const spawn = vi.fn((command) => {
    const child = createMockChild(nextPid += 1);
    if (command === "taskkill") {
      killerChildren.push(child);
      return child;
    }

    backendChildren.push(child);
    if (autoHandshake) {
      queueMicrotask(() => {
        child.stdout.emit(
          "data",
          Buffer.from(
            `AGENT_PET_SIDECAR_RUNTIME {"host":"127.0.0.1","port":${runtimePort},"pid":${child.pid}}\n`,
          ),
        );
      });
    }
    return child;
  });

  return { spawn, backendChildren, killerChildren };
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
    platform: "win32",
    ...overrides,
  });
}

function setResourcesPath(value) {
  Object.defineProperty(process, "resourcesPath", {
    configurable: true,
    value,
  });
}

function restoreProcessState() {
  if (originalResourcesPathDescriptor) {
    Object.defineProperty(process, "resourcesPath", originalResourcesPathDescriptor);
  } else {
    delete process.resourcesPath;
  }
  for (const [name, value] of trackedEnvironment) {
    if (value === undefined) {
      delete process.env[name];
    } else {
      process.env[name] = value;
    }
  }
}

async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

async function stopManagedSidecar(manager, child) {
  manager.stopSidecar();
  emitChildExit(child, 0, null);
  await flushMicrotasks();
}

describe("createSidecarManager", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete require.cache[sidecarPath];
    Module._load = originalModuleLoad;
    restoreProcessState();
  });

  it("enters bounded recovery after structured port exhaustion", async () => {
    const childProcess = createChildProcessMock({ autoHandshake: false });
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock("health endpoint unavailable"),
      "node:net": createServerMock(false),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();
    const child = childProcess.backendChildren[0];
    child.stderr.emit(
      "data",
      Buffer.from(
        'AGENT_PET_SIDECAR_ERROR {"code":"PORT_IN_USE","message":"no available sidecar port"}\n',
      ),
    );
    emitChildExit(child, 2, null);

    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "recovering",
      managed: false,
      pid: null,
      health: null,
      logPath: path.join("/workspace/logs", "sidecar", "agent-pet-sidecar.log"),
      restartAttempt: 1,
      retryAt: expect.any(String),
      error: {
        code: "SIDECAR_RECOVERING",
        cause: "PORT_IN_USE",
      },
    });

    manager.abortSidecarReadiness();
  });

  it("starts its own managed sidecar when the preferred port has a foreign healthy backend", async () => {
    const childProcess = createChildProcessMock({ runtimePort: 8767 });
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createHealthyHttpMock({ status: "ok" }),
      "node:net": createServerMock(false),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();

    expect(childProcess.spawn).toHaveBeenCalledOnce();
    await vi.waitFor(() => {
      expect(manager.getPublicSidecarStatus().state).toBe("ready");
    });
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "ready",
      managed: true,
      pid: childProcess.backendChildren[0].pid,
      port: 8767,
      health: { status: "ok" },
      error: null,
    });

    await stopManagedSidecar(manager, childProcess.backendChildren[0]);
  });

  it("lets the Python entrypoint retain a fallback port and then updates the shared runtime", async () => {
    const childProcess = createChildProcessMock({ runtimePort: 8767 });
    const runtime = { host: "127.0.0.1", port: 8765, baseUrl: "http://127.0.0.1:8765" };
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock("not a backend"),
      "node:net": createServerMock(false),
    });
    const manager = createManager(createSidecarManager, { runtime });

    await manager.startSidecar();
    await flushMicrotasks();

    expect(childProcess.spawn).toHaveBeenCalledWith(
      "python",
      [
        "-m",
        "app.sidecar_entry",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--port-search-range",
        "20",
      ],
      expect.objectContaining({
        env: expect.objectContaining({ AGENT_PET_BACKEND_PORT: "8765" }),
        stdio: ["ignore", "pipe", "pipe"],
      }),
    );
    expect(runtime).toMatchObject({ port: 8767, baseUrl: "http://127.0.0.1:8767" });
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "starting",
      managed: true,
      port: 8767,
      baseUrl: "http://127.0.0.1:8767",
    });

    await stopManagedSidecar(manager, childProcess.backendChildren[0]);
  });

  it("uses python -m app.sidecar_entry only in development", async () => {
    process.env.AGENT_PET_PYTHON = "custom-python";
    const childProcess = createChildProcessMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock({ isPackaged: false }),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();

    expect(childProcess.spawn).toHaveBeenCalledWith(
      "custom-python",
      expect.arrayContaining(["-m", "app.sidecar_entry"]),
      expect.objectContaining({ cwd: expect.any(String), windowsHide: true }),
    );
    await stopManagedSidecar(manager, childProcess.backendChildren[0]);
  });

  it("prefers the bundled executable in a packaged app", async () => {
    const resourcesPath = path.resolve("/opt/agent-pet/resources");
    const executablePath = path.join(resourcesPath, "sidecar", "agent-pet-sidecar.exe");
    setResourcesPath(resourcesPath);
    const childProcess = createChildProcessMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock({ isPackaged: true }),
      "node:child_process": childProcess,
      "node:fs": createFsMock((candidate) => candidate === executablePath),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();

    expect(childProcess.spawn).toHaveBeenCalledWith(
      executablePath,
      ["--host", "127.0.0.1", "--port", "8765", "--port-search-range", "20"],
      expect.objectContaining({ cwd: path.dirname(executablePath) }),
    );
    expect(childProcess.spawn).not.toHaveBeenCalledWith(
      expect.stringMatching(/python/i),
      expect.anything(),
      expect.anything(),
    );
    await stopManagedSidecar(manager, childProcess.backendChildren[0]);
  });

  it("reports an actionable packaged-app error without falling back to Python", async () => {
    setResourcesPath(path.resolve("/opt/agent-pet/resources"));
    const childProcess = createChildProcessMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock({ isPackaged: true }),
      "node:child_process": childProcess,
      "node:fs": createFsMock(() => false),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();

    expect(childProcess.spawn).not.toHaveBeenCalled();
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "error",
      managed: false,
      error: {
        code: "SIDECAR_EXECUTABLE_NOT_FOUND",
        message: expect.stringMatching(/agent-pet-sidecar\.exe.*agent-pet-sidecar\.log/s),
      },
    });
  });

  it("persists both stdout and stderr to the discoverable log", async () => {
    const fsMock = createFsMock();
    const childProcess = createChildProcessMock({ autoHandshake: false });
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": fsMock,
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    const child = childProcess.backendChildren[0];
    child.stdout.emit(
      "data",
      Buffer.from(
        `AGENT_PET_SIDECAR_RUNTIME {"host":"127.0.0.1","port":8765,"pid":${child.pid}}\nstdout marker\n`,
      ),
    );
    child.stderr.emit("data", Buffer.from("stderr marker\n"));
    await flushMicrotasks();

    const logText = fsMock.appendFileSync.mock.calls
      .map(([, value]) => (Buffer.isBuffer(value) ? value.toString("utf8") : String(value)))
      .join("");
    expect(logText).toContain("stdout marker");
    expect(logText).toContain("stderr marker");
    expect(manager.getPublicSidecarStatus().logPath).toBe(
      path.join("/workspace/logs", "sidecar", "agent-pet-sidecar.log"),
    );
    await stopManagedSidecar(manager, child);
  });

  it("reports READINESS_TIMEOUT after the deadline but keeps the backend running", async () => {
    vi.useFakeTimers();
    const childProcess = createChildProcessMock();
    const httpMock = createFailingHttpMock("health check failed");
    const observedAt = [
      new Date("2026-08-11T08:00:00.000Z"),
      new Date("2026-08-11T08:00:03.000Z"),
    ];
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": httpMock,
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager, {
      incidentIdFactory: () => "d".repeat(32),
      clock: () => observedAt.shift(),
    });

    await manager.startSidecar();
    await flushMicrotasks();
    await vi.advanceTimersByTimeAsync(31_000);
    await flushMicrotasks();

    const child = childProcess.backendChildren[0];
    expect(child.kill).not.toHaveBeenCalled();
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "starting",
      managed: true,
      pid: child.pid,
      health: null,
      error: {
        code: "READINESS_TIMEOUT",
      },
    });

    const healthyHttp = createHealthyHttpMock({ status: "ok" });
    httpMock.get.mockImplementation(healthyHttp.get.getMockImplementation());
    await vi.advanceTimersByTimeAsync(1_000);
    await flushMicrotasks();
    await vi.waitFor(() => expect(manager.getPublicSidecarStatus().state).toBe("ready"));
    expect(manager.getPendingRecoveryIncident()).toEqual({
      incident_id: "d".repeat(32),
      unhealthy_at: "2026-08-11T08:00:00.000Z",
      ready_at: "2026-08-11T08:00:03.000Z",
      cause: "readiness_failed",
      restart_attempt: 1,
    });
    await stopManagedSidecar(manager, child);
  });

  it("requires the runtime handshake pid to match the spawned process", async () => {
    const childProcess = createChildProcessMock({ autoHandshake: false });
    const httpMock = createFailingHttpMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": httpMock,
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    const child = childProcess.backendChildren[0];
    child.stdout.emit(
      "data",
      Buffer.from(
        `AGENT_PET_SIDECAR_RUNTIME {"host":"127.0.0.1","port":8765,"pid":${child.pid + 1}}\n`,
      ),
    );
    await flushMicrotasks();

    expect(httpMock.get).not.toHaveBeenCalled();
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "starting",
      managed: true,
      pid: child.pid,
      error: {
        code: "RUNTIME_HANDSHAKE_INVALID",
        message: expect.stringContaining("runtime process identity is invalid"),
      },
    });

    await stopManagedSidecar(manager, child);
  });

  it("does not become ready when the session token is rejected", async () => {
    const childProcess = createChildProcessMock();
    const httpMock = createSessionRejectedHttpMock();
    const onReady = vi.fn();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": httpMock,
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager, { onReady });

    await manager.startSidecar();
    await flushMicrotasks();

    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "starting",
      managed: true,
      pid: childProcess.backendChildren[0].pid,
      health: null,
    });
    expect(onReady).not.toHaveBeenCalled();
    const settingsRequest = httpMock.get.mock.calls.find(([url]) => url.endsWith("/api/settings"));
    expect(settingsRequest?.[1]).toMatchObject({
      headers: { Authorization: "Bearer test-token" },
    });

    await stopManagedSidecar(manager, childProcess.backendChildren[0]);
  });

  it("uses 1s, 2s, 5s, 15s, and 30s recovery delays before requiring manual retry", async () => {
    vi.useFakeTimers();
    process.env.AGENT_PET_READY_TIMEOUT_MS = "120000";
    const childProcess = createChildProcessMock({ autoHandshake: false });
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);
    const expectedDelays = [1_000, 2_000, 5_000, 15_000, 30_000];

    await manager.startSidecar();
    await flushMicrotasks();

    for (const [index, expectedDelay] of expectedDelays.entries()) {
      const failedAt = Date.now();
      emitChildExit(childProcess.backendChildren[index], 1, null);
      const status = manager.getPublicSidecarStatus();
      expect(status).toMatchObject({
        state: "recovering",
        managed: false,
        restartAttempt: index + 1,
        error: {
          code: "SIDECAR_RECOVERING",
          cause: "PROCESS_EXITED",
        },
      });
      expect(Date.parse(status.retryAt) - failedAt).toBe(expectedDelay);

      await vi.advanceTimersByTimeAsync(expectedDelay - 1);
      expect(childProcess.backendChildren).toHaveLength(index + 1);
      await vi.advanceTimersByTimeAsync(1);
      await flushMicrotasks();
      expect(childProcess.backendChildren).toHaveLength(index + 2);
    }

    emitChildExit(childProcess.backendChildren[5], 1, null);
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "manual-retry",
      managed: false,
      restartAttempt: 5,
      retryAt: null,
      error: { code: "RESTART_LIMIT_REACHED" },
    });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(childProcess.backendChildren).toHaveLength(6);

    manager.retrySidecar();
    await flushMicrotasks();
    expect(childProcess.backendChildren).toHaveLength(7);
    emitChildExit(childProcess.backendChildren[6], 1, null);
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "recovering",
      restartAttempt: 1,
    });
    manager.abortSidecarReadiness();
  });

  it("pairs one unexpected process exit with the later authenticated readiness", async () => {
    vi.useFakeTimers();
    const childProcess = createChildProcessMock();
    const onReady = vi.fn();
    const observedAt = [
      new Date("2026-08-11T08:00:00.000Z"),
      new Date("2026-08-11T08:00:02.500Z"),
    ];
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createHealthyHttpMock({ status: "ok" }),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager, {
      onReady,
      incidentIdFactory: () => "a".repeat(32),
      clock: () => observedAt.shift(),
    });

    await manager.startSidecar();
    await flushMicrotasks();
    await vi.waitFor(() => expect(onReady).toHaveBeenCalledOnce());
    expect(manager.getPendingRecoveryIncident()).toBeNull();

    emitChildExit(childProcess.backendChildren[0], 1, null);
    expect(manager.getPendingRecoveryIncident()).toBeNull();
    await vi.advanceTimersByTimeAsync(1_000);
    await flushMicrotasks();
    await vi.waitFor(() => expect(onReady).toHaveBeenCalledTimes(2));

    expect(manager.getPendingRecoveryIncident()).toEqual({
      incident_id: "a".repeat(32),
      unhealthy_at: "2026-08-11T08:00:00.000Z",
      ready_at: "2026-08-11T08:00:02.500Z",
      cause: "process_exited",
      restart_attempt: 1,
    });
    expect(manager.acknowledgeRecoveryIncident("a".repeat(32))).toBe(true);
    expect(manager.getPendingRecoveryIncident()).toBeNull();

    await stopManagedSidecar(manager, childProcess.backendChildren[1]);
  });

  it("pauses automatic recovery during suspend and starts a managed sidecar on resume", async () => {
    vi.useFakeTimers();
    const childProcess = createChildProcessMock({ autoHandshake: false });
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();
    manager.handleSuspend();
    expect(manager.getPublicSidecarStatus().state).toBe("suspended");

    emitChildExit(childProcess.backendChildren[0], 1, null);
    expect(manager.getPendingRecoveryIncident()).toBeNull();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(childProcess.backendChildren).toHaveLength(1);

    await manager.handleResume();
    await flushMicrotasks();
    expect(childProcess.backendChildren).toHaveLength(2);
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "starting",
      managed: true,
      pid: childProcess.backendChildren[1].pid,
    });

    await stopManagedSidecar(manager, childProcess.backendChildren[1]);
  });

  it("checks health and the session token before resume recovery", async () => {
    const childProcess = createChildProcessMock();
    const httpMock = createHealthyHttpMock({ status: "ok" });
    const onReady = vi.fn();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": httpMock,
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager, { onReady });

    await manager.startSidecar();
    await flushMicrotasks();
    await vi.waitFor(() => {
      expect(onReady).toHaveBeenCalledOnce();
    });
    onReady.mockClear();
    httpMock.get.mockClear();
    manager.handleSuspend();
    await manager.handleResume();

    expect(httpMock.get.mock.calls.map(([url]) => url)).toEqual([
      "http://127.0.0.1:8765/api/health",
      "http://127.0.0.1:8765/api/settings",
    ]);
    expect(httpMock.get.mock.calls[1][1]).toMatchObject({
      headers: { Authorization: "Bearer test-token" },
    });
    expect(onReady).toHaveBeenCalledOnce();
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "ready",
      managed: true,
      pid: childProcess.backendChildren[0].pid,
    });

    await stopManagedSidecar(manager, childProcess.backendChildren[0]);
  });

  it("uses taskkill /T /F for a managed Windows sidecar", async () => {
    const childProcess = createChildProcessMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();
    await flushMicrotasks();
    const child = childProcess.backendChildren[0];
    manager.stopSidecar();

    expect(childProcess.spawn).toHaveBeenCalledWith(
      "taskkill",
      ["/pid", String(child.pid), "/T", "/F"],
      { stdio: "ignore", windowsHide: true },
    );
    emitChildExit(child, 0, null);
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "stopped",
      managed: false,
      pid: null,
      error: null,
    });
  });

  it("completes 20 mocked start-stop cycles without retaining process state", async () => {
    const childProcess = createChildProcessMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    for (let cycle = 0; cycle < 20; cycle += 1) {
      await manager.startSidecar();
      await flushMicrotasks();
      const child = childProcess.backendChildren[cycle];
      expect(child).toBeDefined();
      manager.stopSidecar();
      emitChildExit(child, 0, null);
      await flushMicrotasks();
      expect(manager.getPublicSidecarStatus()).toMatchObject({
        state: "stopped",
        managed: false,
        pid: null,
        error: null,
      });
    }

    expect(childProcess.backendChildren).toHaveLength(20);
    expect(childProcess.killerChildren).toHaveLength(20);
  });

  it("reports BACKEND_NOT_FOUND when the development entrypoint is absent", async () => {
    const childProcess = createChildProcessMock();
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock(),
      "node:child_process": childProcess,
      "node:fs": createFsMock(() => false),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    await manager.startSidecar();

    expect(childProcess.spawn).not.toHaveBeenCalled();
    expect(manager.getPublicSidecarStatus()).toMatchObject({
      state: "error",
      health: null,
      error: {
        code: "BACKEND_NOT_FOUND",
      },
    });
  });

  it("leaves reminder deduplication to the durable reservation ledger", () => {
    const electronMock = createElectronMock({ notificationsSupported: true });
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: electronMock,
      "node:child_process": createChildProcessMock(),
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    expect(manager.showReminderNotification({ reminder_id: "reminder-0", title: "t" }).status).toBe("shown");
    expect(manager.showReminderNotification({ reminder_id: "reminder-0", title: "t" }).status).toBe("shown");
    expect(electronMock.Notification).toHaveBeenCalledTimes(2);
  });

  it("records unsupported notifications without claiming a display", () => {
    const { createSidecarManager } = loadSidecarWithMocks({
      electron: createElectronMock({ notificationsSupported: false }),
      "node:child_process": createChildProcessMock(),
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    const manager = createManager(createSidecarManager);

    expect(manager.showReminderNotification({ reminder_id: "reminder-unsupported", title: "t" })).toEqual({
      status: "unsupported",
      reminder_id: "reminder-unsupported",
    });
  });

  it("turns notification API and support-check exceptions into explicit failures", () => {
    const notificationFailure = new Error("notification permission rejected");
    const { createSidecarManager: createApiFailureManager } = loadSidecarWithMocks({
      electron: createElectronMock({ notificationsSupported: true, notificationError: notificationFailure }),
      "node:child_process": createChildProcessMock(),
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    expect(createManager(createApiFailureManager).showReminderNotification({ reminder_id: "reminder-api", title: "t" })).toEqual({
      status: "failed",
      reminder_id: "reminder-api",
      reason: "notification_api_failed",
    });

    const supportFailure = new Error("notification support unavailable");
    const { createSidecarManager: createSupportFailureManager } = loadSidecarWithMocks({
      electron: createElectronMock({ supportCheckError: supportFailure }),
      "node:child_process": createChildProcessMock(),
      "node:fs": createFsMock(),
      "node:http": createFailingHttpMock(),
      "node:net": createServerMock(true),
    });
    expect(createManager(createSupportFailureManager).showReminderNotification({ reminder_id: "reminder-support", title: "t" })).toEqual({
      status: "failed",
      reminder_id: "reminder-support",
      reason: "notification_support_check_failed",
    });
  });
});
