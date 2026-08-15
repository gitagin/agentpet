const { EventEmitter } = require("node:events");
const crypto = require("node:crypto");
const { createResidentRuntime, isResidentLaunch } = require("./resident.js");

function createLoginItemApp(initial = {}) {
  let settings = {
    openAtLogin: false,
    args: [],
    ...initial,
  };
  return {
    getLoginItemSettings: vi.fn((options = {}) => ({
      openAtLogin: Boolean(settings.openAtLogin)
        && JSON.stringify(options.args || []) === JSON.stringify(settings.args || []),
    })),
    setLoginItemSettings: vi.fn((next) => {
      settings = {
        openAtLogin: Boolean(next.openAtLogin),
        args: [...(next.args || [])],
      };
    }),
  };
}

function createRuntime(overrides = {}) {
  return createResidentRuntime({
    electronApp: createLoginItemApp(),
    powerMonitor: new EventEmitter(),
    sidecar: {},
    proxy: {
      proxyApiRequest: vi.fn(async (path) => ({
        status: 200,
        body: path === "/api/tasks" ? JSON.stringify({ tasks: [] }) : "{}",
      })),
    },
    platform: "win32",
    ...overrides,
  });
}

describe("resident runtime", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("enables and disables login startup using authoritative Electron readback", () => {
    const electronApp = createLoginItemApp();
    const runtime = createRuntime({ electronApp });

    expect(runtime.getLoginItemStatus()).toEqual({
      supported: true,
      enabled: false,
    });
    expect(runtime.setLoginItemEnabled(true)).toEqual({
      supported: true,
      enabled: true,
    });
    expect(electronApp.setLoginItemSettings).toHaveBeenLastCalledWith({
      openAtLogin: true,
      args: ["--resident"],
    });

    expect(runtime.setLoginItemEnabled(false)).toEqual({
      supported: true,
      enabled: false,
    });
    expect(electronApp.setLoginItemSettings).toHaveBeenLastCalledWith({
      openAtLogin: false,
      args: ["--resident"],
    });
    expect(electronApp.getLoginItemSettings).toHaveBeenCalledTimes(5);
    for (const [options] of electronApp.getLoginItemSettings.mock.calls) {
      expect(options).toEqual({ args: ["--resident"] });
    }
  });

  it("recognizes only the explicit resident startup argument", () => {
    expect(isResidentLaunch(["electron.exe", "main.cjs", "--resident"])).toBe(true);
    expect(isResidentLaunch(["electron.exe", "main.cjs", "--resident=true"])).toBe(false);
    expect(isResidentLaunch(["electron.exe", "main.cjs"])).toBe(false);
    expect(isResidentLaunch(null)).toBe(false);
  });

  it("reports the real readback when the operating system does not accept the requested state", () => {
    const electronApp = {
      getLoginItemSettings: vi.fn(() => ({ openAtLogin: false })),
      setLoginItemSettings: vi.fn(),
    };
    const runtime = createRuntime({ electronApp });

    expect(runtime.setLoginItemEnabled(true)).toEqual({
      supported: true,
      enabled: false,
    });
    expect(electronApp.setLoginItemSettings).toHaveBeenCalledOnce();
  });

  it("does not treat a different Windows startup argument as the resident item", () => {
    const electronApp = createLoginItemApp({ openAtLogin: true, args: ["--other-mode"] });
    const runtime = createRuntime({ electronApp });

    expect(runtime.getLoginItemStatus()).toEqual({
      supported: true,
      enabled: false,
    });
    expect(electronApp.getLoginItemSettings).toHaveBeenCalledWith({ args: ["--resident"] });
  });

  it("does not expose a false login-startup capability on unsupported platforms", () => {
    const electronApp = createLoginItemApp({ openAtLogin: true, args: ["--resident"] });
    const runtime = createRuntime({ electronApp, platform: "linux" });

    expect(runtime.getLoginItemStatus()).toEqual({
      supported: false,
      enabled: false,
    });
    expect(runtime.setLoginItemEnabled(true)).toEqual({
      supported: false,
      enabled: false,
    });
    expect(electronApp.setLoginItemSettings).not.toHaveBeenCalled();
    expect(() => runtime.setLoginItemEnabled("true")).toThrow(TypeError);
  });

  it("registers one suspend and resume listener and removes both on shutdown", async () => {
    const powerMonitor = new EventEmitter();
    const sidecar = {
      handleSuspend: vi.fn(),
      handleResume: vi.fn(async () => ({ state: "ready" })),
    };
    const runtime = createRuntime({ powerMonitor, sidecar });

    runtime.startPowerMonitoring();
    runtime.startPowerMonitoring();
    expect(powerMonitor.listenerCount("suspend")).toBe(1);
    expect(powerMonitor.listenerCount("resume")).toBe(1);

    powerMonitor.emit("suspend");
    powerMonitor.emit("resume");
    await Promise.resolve();
    expect(sidecar.handleSuspend).toHaveBeenCalledOnce();
    expect(sidecar.handleResume).toHaveBeenCalledOnce();

    runtime.stopPowerMonitoring();
    runtime.stopPowerMonitoring();
    expect(powerMonitor.listenerCount("suspend")).toBe(0);
    expect(powerMonitor.listenerCount("resume")).toBe(0);
  });

  it("contains an unexpected asynchronous resume failure", async () => {
    const powerMonitor = new EventEmitter();
    const resumeError = new Error("resume failed");
    const sidecar = {
      handleResume: vi.fn(async () => {
        throw resumeError;
      }),
    };
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const runtime = createRuntime({ powerMonitor, sidecar });

    runtime.startPowerMonitoring();
    expect(() => powerMonitor.emit("resume")).not.toThrow();
    await vi.waitFor(() => {
      expect(warning).toHaveBeenCalledWith("睡眠恢复失败，需要手动重试。", resumeError);
    });
    runtime.stopPowerMonitoring();
  });

  it("does not restart reminder polling when shutdown overtakes resume", async () => {
    const powerMonitor = new EventEmitter();
    let finishResume;
    const sidecar = {
      handleSuspend: vi.fn(),
      handleResume: vi.fn(() => new Promise((resolve) => {
        finishResume = resolve;
      })),
    };
    const proxy = { proxyApiRequest: vi.fn() };
    const runtime = createRuntime({
      powerMonitor,
      sidecar,
      proxy,
      dispatchReminderNotification: vi.fn(),
    });

    runtime.startPowerMonitoring();
    powerMonitor.emit("suspend");
    powerMonitor.emit("resume");
    await vi.waitFor(() => expect(sidecar.handleResume).toHaveBeenCalledOnce());
    runtime.stopPowerMonitoring();
    finishResume({ state: "ready" });
    await Promise.resolve();
    await Promise.resolve();

    expect(proxy.proxyApiRequest).not.toHaveBeenCalled();
  });

  it("reconciles reminder delivery and graph projection after sidecar readiness", async () => {
    const proxy = {
      proxyApiRequest: vi.fn(async (path) => ({ status: 200, body: path })),
    };
    const runtime = createRuntime({ proxy });

    await expect(runtime.recoverBackendState()).resolves.toEqual({
      reminders: { status: 200, body: "/api/tasks/reminder-delivery/recover" },
      graph: { status: 200, body: "/api/memory/graph?limit=5" },
    });
    expect(proxy.proxyApiRequest.mock.calls).toEqual([
      ["/api/tasks/reminder-delivery/recover", { method: "POST", body: "{}" }],
      ["/api/memory/graph?limit=5", { method: "GET" }],
    ]);
  });

  it("records and acknowledges a paired sidecar recovery through the internal backend API", async () => {
    const incident = {
      incident_id: "a".repeat(32),
      unhealthy_at: "2026-08-11T08:00:00.000Z",
      ready_at: "2026-08-11T08:00:02.500Z",
      cause: "process_exited",
      restart_attempt: 1,
    };
    const sidecar = {
      getPendingRecoveryIncident: vi.fn(() => incident),
      acknowledgeRecoveryIncident: vi.fn(() => true),
    };
    const proxy = {
      requestInternalApi: vi.fn(async () => ({
        status: 200,
        body: JSON.stringify({
          status: "recorded",
          incident_id: incident.incident_id,
          unhealthy_event_id: "event-unhealthy",
          ready_event_id: "event-ready",
          recovery_time_ms: 2500,
        }),
      })),
      proxyApiRequest: vi.fn(),
    };
    const runtime = createRuntime({ sidecar, proxy });

    await expect(runtime.reportPendingSidecarRecovery()).resolves.toMatchObject({
      status: "recorded",
      incident_id: incident.incident_id,
    });

    const expectedKey = crypto
      .createHash("sha256")
      .update(`sidecar-recovery:${incident.incident_id}`)
      .digest("hex");
    expect(proxy.requestInternalApi).toHaveBeenCalledWith("/api/metrics/sidecar-recovery", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": expectedKey,
      },
      body: JSON.stringify(incident),
    });
    expect(proxy.proxyApiRequest).not.toHaveBeenCalled();
    expect(sidecar.acknowledgeRecoveryIncident).toHaveBeenCalledWith(incident.incident_id);
  });

  it("polls the authenticated task list and dispatches only triggered reminders", async () => {
    const dispatchReminderNotification = vi.fn(async ({ payload }) => ({
      status: "shown",
      reminder_id: payload.reminder_id,
    }));
    const proxy = {
      proxyApiRequest: vi.fn(async (path) => {
        if (path === "/api/tasks") {
          return {
            status: 200,
            body: JSON.stringify({
              tasks: [
                {
                  reminder_id: "scheduled-reminder",
                  reminder_status: "scheduled",
                  remind_at: "2026-08-10T09:00:00Z",
                },
                {
                  reminder_id: "triggered-reminder",
                  reminder_status: "triggered",
                  remind_at: "2026-08-10T08:00:00Z",
                  title: "Review",
                  description: "Review the evidence trail",
                },
                {
                  reminder_status: "triggered",
                  remind_at: "2026-08-10T08:01:00Z",
                },
              ],
            }),
          };
        }
        return { status: 200, body: "{}" };
      }),
    };
    const runtime = createRuntime({ proxy, dispatchReminderNotification });

    await expect(runtime.pollTriggeredReminders()).resolves.toMatchObject({
      status: "ok",
      attempted: 1,
    });
    expect(proxy.proxyApiRequest).toHaveBeenCalledWith("/api/tasks", { method: "GET" });
    expect(dispatchReminderNotification).toHaveBeenCalledWith({
      proxy,
      sidecar: expect.anything(),
      payload: {
        reminder_id: "triggered-reminder",
        trigger_at: "2026-08-10T08:00:00Z",
        dispatch_kind: "automatic",
        title: "Review",
        body: "Review the evidence trail",
      },
    });
  });

  it("does not expose source conversation text in automatic notifications", async () => {
    const dispatchReminderNotification = vi.fn(async ({ payload }) => ({
      status: "shown",
      reminder_id: payload.reminder_id,
    }));
    const proxy = {
      proxyApiRequest: vi.fn(async () => ({
        status: 200,
        body: JSON.stringify({
          tasks: [{
            reminder_id: "private-reminder",
            reminder_status: "triggered",
            triggered_at: "2026-08-10T08:00:00Z",
            title: "Private reminder",
            source_text: "private conversation content",
          }],
        }),
      })),
    };
    const runtime = createRuntime({ proxy, dispatchReminderNotification });

    await runtime.pollTriggeredReminders();

    expect(dispatchReminderNotification).toHaveBeenCalledWith(expect.objectContaining({
      payload: expect.objectContaining({
        body: "提醒已到期。",
      }),
    }));
    expect(dispatchReminderNotification.mock.calls[0][0].payload.body).not.toContain("private conversation content");
  });

  it("coalesces overlapping polls while a task-list request is in flight", async () => {
    let resolveTasks;
    const tasksResponse = new Promise((resolve) => {
      resolveTasks = resolve;
    });
    const proxy = {
      proxyApiRequest: vi.fn(() => tasksResponse),
    };
    const runtime = createRuntime({
      proxy,
      dispatchReminderNotification: vi.fn(),
    });

    const first = runtime.pollTriggeredReminders();
    const second = runtime.pollTriggeredReminders();
    await vi.waitFor(() => expect(proxy.proxyApiRequest).toHaveBeenCalledOnce());
    resolveTasks({ status: 200, body: JSON.stringify({ tasks: [] }) });
    await expect(first).resolves.toMatchObject({ status: "ok", attempted: 0 });
    await expect(second).resolves.toMatchObject({ status: "ok", attempted: 0 });
  });

  it("pauses resident reminder polling during suspend and catches up after recovery", async () => {
    const powerMonitor = new EventEmitter();
    const dispatchReminderNotification = vi.fn(async ({ payload }) => ({
      status: "shown",
      reminder_id: payload.reminder_id,
    }));
    const calls = [];
    const proxy = {
      proxyApiRequest: vi.fn(async (path) => {
        calls.push(path);
        if (path === "/api/tasks/reminder-delivery/recover") {
          return { status: 200, body: "{}" };
        }
        if (path === "/api/memory/graph?limit=5") {
          return { status: 200, body: "{}" };
        }
        return {
          status: 200,
          body: JSON.stringify({
            tasks: [{
              reminder_id: "resume-reminder",
              reminder_status: "triggered",
              remind_at: "2026-08-10T08:00:00Z",
              title: "Catch up",
            }],
          }),
        };
      }),
    };
    const sidecar = {
      handleSuspend: vi.fn(),
      handleResume: vi.fn(async () => ({ state: "ready" })),
    };
    const runtime = createRuntime({
      powerMonitor,
      sidecar,
      proxy,
      dispatchReminderNotification,
      reminderPollIntervalMs: 60_000,
    });

    runtime.startPowerMonitoring();
    powerMonitor.emit("suspend");
    await expect(runtime.pollTriggeredReminders()).resolves.toMatchObject({ status: "suspended" });
    expect(dispatchReminderNotification).not.toHaveBeenCalled();

    powerMonitor.emit("resume");
    await vi.waitFor(() => {
      expect(sidecar.handleResume).toHaveBeenCalledOnce();
      expect(calls.slice(0, 3)).toEqual([
        "/api/tasks/reminder-delivery/recover",
        "/api/memory/graph?limit=5",
        "/api/tasks",
      ]);
      expect(dispatchReminderNotification).toHaveBeenCalledOnce();
    });
    runtime.stopPowerMonitoring();
  });

  it("does not recover twice when sidecar resume invokes the readiness callback", async () => {
    const powerMonitor = new EventEmitter();
    const proxy = {
      proxyApiRequest: vi.fn(async (path) => ({
        status: 200,
        body: path === "/api/tasks" ? JSON.stringify({ tasks: [] }) : "{}",
      })),
    };
    let onReady;
    const sidecar = {
      handleResume: vi.fn(async () => {
        await onReady();
        return { state: "ready" };
      }),
    };
    const runtime = createRuntime({ powerMonitor, sidecar, proxy });
    onReady = () => runtime.handleSidecarReady();

    runtime.startPowerMonitoring();
    powerMonitor.emit("suspend");
    powerMonitor.emit("resume");
    await vi.waitFor(() => expect(sidecar.handleResume).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect(proxy.proxyApiRequest).toHaveBeenCalledWith(
      "/api/tasks/reminder-delivery/recover",
      { method: "POST", body: "{}" },
    ));
    await Promise.resolve();

    expect(proxy.proxyApiRequest.mock.calls.filter(([path]) => path === "/api/tasks/reminder-delivery/recover")).toHaveLength(1);
    runtime.stopPowerMonitoring();
  });

  it("ignores a stale sidecar readiness callback while the machine is suspended", async () => {
    const powerMonitor = new EventEmitter();
    const proxy = { proxyApiRequest: vi.fn() };
    const runtime = createRuntime({ powerMonitor, proxy });

    runtime.startPowerMonitoring();
    powerMonitor.emit("suspend");
    await expect(runtime.handleSidecarReady()).resolves.toEqual({ reminders: null, graph: null });

    expect(proxy.proxyApiRequest).not.toHaveBeenCalled();
    runtime.stopPowerMonitoring();
  });

  it("preserves unknown dispatch outcomes for the manual retry surface", async () => {
    const onReminderDispatch = vi.fn();
    const payload = {
      reminder_id: "unknown-reminder",
      reminder_status: "triggered",
      triggered_at: "2026-08-10T08:00:00Z",
    };
    const dispatchReminderNotification = vi.fn(async () => ({
      status: "unknown",
      reminder_id: "unknown-reminder",
      attempt_id: "attempt-unknown",
      reason: "unknown_after_crash",
    }));
    const proxy = {
      proxyApiRequest: vi.fn(async () => ({
        status: 200,
        body: JSON.stringify({ tasks: [payload] }),
      })),
    };
    const runtime = createRuntime({ proxy, dispatchReminderNotification, onReminderDispatch });

    const result = await runtime.pollTriggeredReminders();
    expect(result.results[0].result).toEqual({
      status: "unknown",
      reminder_id: "unknown-reminder",
      attempt_id: "attempt-unknown",
      reason: "unknown_after_crash",
    });
    expect(onReminderDispatch).toHaveBeenCalledWith(result.results[0].result, expect.objectContaining({
      dispatch_kind: "automatic",
    }));
  });
});
