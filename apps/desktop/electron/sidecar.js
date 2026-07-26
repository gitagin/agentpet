const { app, BrowserWindow, Notification } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

// 约定端口被占用时向上搜索的备选端口数量（例如 8765 -> 8766..8785）。
const PORT_SEARCH_RANGE = 20;
// 就绪等待的默认上限；可用 AGENT_PET_READY_TIMEOUT_MS 覆盖。到达上限只提示、不杀进程。
const DEFAULT_READY_TIMEOUT_MS = 30_000;
const READY_POLL_INTERVAL_MS = 250;
const READY_STALLED_POLL_INTERVAL_MS = 1_000;
// 非 Windows 平台 SIGTERM 后升级 SIGKILL 的宽限时间。
const STOP_FORCE_KILL_TIMEOUT_MS = 5_000;
// 已投递提醒通知去重集合的上限，防止长会话内存无界增长。
const MAX_DELIVERED_REMINDER_IDS = 500;

function resolveReadyTimeoutMs() {
  const raw = Number.parseInt(process.env.AGENT_PET_READY_TIMEOUT_MS ?? "", 10);
  return Number.isFinite(raw) && raw >= 1_000 ? raw : DEFAULT_READY_TIMEOUT_MS;
}

function createSidecarManager({ host, port, baseUrl, runtime, sessionToken, managedSidecarDataDir, state, showControlWindow }) {
  // runtime 是主进程各模块（proxy/ipc）共享的可变对象；端口搜索选中新端口后在这里
  // 就地更新，代理与 get-sidecar-config 随之切换。未传入时退化为本地对象（测试用）。
  const portRuntime = runtime ?? { host, port, baseUrl };
  const preferredPort = portRuntime.port;
  let sidecarProcess = null;
  let sidecarReadinessAbort = null;
  const deliveredReminderNotifications = new Set();
  let sidecarStatus = {
    state: "stopped",
    baseUrl: portRuntime.baseUrl,
    host: portRuntime.host,
    port: portRuntime.port,
    dataDir: managedSidecarDataDir,
    managed: false,
    pid: null,
    health: null,
    error: null,
    updatedAt: new Date().toISOString(),
  };

  function updateRuntimePort(nextPort) {
    portRuntime.port = nextPort;
    portRuntime.baseUrl = `http://${portRuntime.host}:${nextPort}`;
  }

  function findBackendDirectory() {
    const packagedResourcesPath =
      typeof process.resourcesPath === "string" ? process.resourcesPath : null;
    const candidates = [
      process.env.AGENT_PET_BACKEND_DIR,
      packagedResourcesPath ? path.join(packagedResourcesPath, "backend") : null,
      packagedResourcesPath ? path.join(packagedResourcesPath, "sidecar") : null,
      path.resolve(app.getAppPath(), "..", "backend"),
      path.resolve(app.getAppPath(), "..", "sidecar"),
      path.resolve(process.cwd(), "..", "backend"),
      path.resolve(__dirname, "..", "..", "backend"),
    ]
      .filter(Boolean)
      .map((candidate) => path.resolve(candidate));

    for (const candidate of candidates) {
      if (fs.existsSync(path.join(candidate, "app", "main.py"))) {
        return candidate;
      }
    }

    return null;
  }

  function getPublicSidecarStatus() {
    const { dataDir, ...publicStatus } = sidecarStatus;
    return publicStatus;
  }

  function getSidecarEnvironment() {
    const env = {
      ...process.env,
      AGENT_PET_SESSION_TOKEN: sessionToken,
      // 把最终选中的监听地址传给后端，供其构造自引用 URL 或诊断输出。
      AGENT_PET_BACKEND_HOST: portRuntime.host,
      AGENT_PET_BACKEND_PORT: String(portRuntime.port),
    };

    if (!env.AGENT_PET_DATA_DIR && !env.AGENT_PET_SQLITE_PATH) {
      env.AGENT_PET_DATA_DIR = managedSidecarDataDir;
    }

    return env;
  }

  function rememberDeliveredReminder(reminderId) {
    deliveredReminderNotifications.add(reminderId);
    while (deliveredReminderNotifications.size > MAX_DELIVERED_REMINDER_IDS) {
      const oldest = deliveredReminderNotifications.values().next().value;
      deliveredReminderNotifications.delete(oldest);
    }
  }

  function showReminderNotification(payload) {
    const reminderId = typeof payload?.reminder_id === "string" ? payload.reminder_id.trim() : "";
    if (!reminderId) {
      return {
        status: "failed",
        reason: "missing_reminder_id",
      };
    }
    if (deliveredReminderNotifications.has(reminderId)) {
      return {
        status: "duplicate",
        reminder_id: reminderId,
      };
    }
    if (!Notification.isSupported()) {
      return {
        status: "unsupported",
        reminder_id: reminderId,
      };
    }

    const title = typeof payload?.title === "string" && payload.title.trim()
      ? payload.title.trim()
      : "桌面记忆助手提醒";
    const body = typeof payload?.body === "string" && payload.body.trim()
      ? payload.body.trim()
      : "有一条提醒已到期。";
    const notification = new Notification({ title, body });
    notification.on("click", showControlWindow);
    notification.show();
    rememberDeliveredReminder(reminderId);
    return {
      status: "shown",
      reminder_id: reminderId,
    };
  }

  function setSidecarStatus(patch) {
    sidecarStatus = {
      ...sidecarStatus,
      host: portRuntime.host,
      port: portRuntime.port,
      baseUrl: portRuntime.baseUrl,
      ...patch,
      updatedAt: new Date().toISOString(),
    };

    for (const window of BrowserWindow.getAllWindows()) {
      window.webContents.send("agent-pet:sidecar-status-changed", getPublicSidecarStatus());
    }
  }

  function isPortAvailable(candidatePort) {
    return new Promise((resolve, reject) => {
      const server = net.createServer();

      server.once("error", (error) => {
        if (error.code === "EADDRINUSE") {
          resolve(false);
          return;
        }
        reject(error);
      });

      server.once("listening", () => {
        server.close(() => resolve(true));
      });

      server.listen(candidatePort, portRuntime.host);
    });
  }

  async function findAvailableFallbackPort() {
    for (let offset = 1; offset <= PORT_SEARCH_RANGE; offset += 1) {
      const candidate = preferredPort + offset;
      if (await isPortAvailable(candidate)) {
        return candidate;
      }
    }
    return null;
  }

  async function waitForSidecarReady(signal) {
    const timeoutMs = resolveReadyTimeoutMs();
    const deadline = Date.now() + timeoutMs;
    let stalledReported = false;
    let lastError = null;

    // 一直轮询直到就绪或被取消（进程退出/应用退出都会取消）。到达超时上限只把
    // 状态标成 READINESS_TIMEOUT 提醒用户，不主动杀正在冷启动的后端。
    for (;;) {
      if (signal.aborted) {
        throw new Error("后端就绪等待被取消。");
      }

      try {
        const health = await requestJson(`${portRuntime.baseUrl}/api/health`, signal);
        if (health && typeof health.status === "string") {
          return health;
        }
      } catch (error) {
        lastError = error;
      }

      if (!stalledReported && Date.now() >= deadline) {
        stalledReported = true;
        reportReadinessStalled(timeoutMs, lastError);
      }

      await delay(stalledReported ? READY_STALLED_POLL_INTERVAL_MS : READY_POLL_INTERVAL_MS, signal);
    }
  }

  function reportReadinessStalled(timeoutMs, lastError) {
    if (state.isQuitting || !sidecarProcess) {
      return;
    }
    const suffix = lastError?.message ? ` 最近一次错误：${lastError.message}` : "";
    console.warn(`FastAPI 后端在 ${timeoutMs}ms 内未通过健康检查，继续等待。${suffix}`);
    setSidecarStatus({
      state: "starting",
      managed: true,
      pid: sidecarProcess.pid ?? null,
      health: null,
      error: {
        code: "READINESS_TIMEOUT",
        message: `后端进程已启动，但 ${Math.round(timeoutMs / 1000)} 秒内未通过健康检查。进程仍在运行，将继续等待；冷启动或首次建库可能较慢。可稍候、重启应用重试，或用 AGENT_PET_READY_TIMEOUT_MS 调整该提醒时长。${suffix}`,
      },
    });
  }

  function requestJson(url, signal) {
    return new Promise((resolve, reject) => {
      const request = http.get(url, { signal, timeout: 2_000 }, (response) => {
        let body = "";

        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          body += chunk;
        });
        response.on("end", () => {
          if (response.statusCode < 200 || response.statusCode >= 300) {
            reject(new Error(`健康检查返回 HTTP ${response.statusCode}。`));
            return;
          }

          try {
            resolve(JSON.parse(body));
          } catch (error) {
            reject(error);
          }
        });
      });

      request.on("timeout", () => {
        request.destroy(new Error("健康检查超时。"));
      });
      request.on("error", reject);
    });
  }

  function delay(ms, signal) {
    return new Promise((resolve, reject) => {
      if (signal.aborted) {
        reject(new Error("延迟被取消。"));
        return;
      }

      const timeout = setTimeout(() => {
        signal.removeEventListener("abort", onAbort);
        resolve();
      }, ms);
      const onAbort = () => {
        clearTimeout(timeout);
        reject(new Error("延迟被取消。"));
      };

      signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  async function startSidecar() {
    if (sidecarProcess) {
      return;
    }

    setSidecarStatus({
      state: "checking-port",
      managed: false,
      pid: null,
      health: null,
      error: null,
    });

    let selectedPort = preferredPort;
    try {
      const preferredAvailable = await isPortAvailable(preferredPort);
      if (!preferredAvailable) {
        // 约定端口被占：先看占用者是不是一个活的后端（能响应 /api/health）。
        let existingHealth = null;
        try {
          existingHealth = await requestJson(`http://${portRuntime.host}:${preferredPort}/api/health`, AbortSignal.timeout(2_000));
        } catch {
          existingHealth = null;
        }

        if (existingHealth) {
          // 复用外部后端是降级运行：令牌可能不一致（业务请求会 401），
          // 明确用 degraded 状态区别于我们托管并验证过的 ready。
          updateRuntimePort(preferredPort);
          setSidecarStatus({
            state: "degraded",
            managed: false,
            pid: null,
            health: existingHealth,
            error: {
              code: "PORT_IN_USE_EXISTING_BACKEND",
              message: `端口 ${preferredPort} 已有后端响应，已降级复用现有后端（未校验会话令牌）。若业务请求返回 401，请关闭占用进程后重启，或用相同 AGENT_PET_SESSION_TOKEN 启动后端。`,
            },
          });
          return;
        }

        // 不是可用后端：向上搜索备选端口，找到就把整套运行时切过去。
        const fallbackPort = await findAvailableFallbackPort();
        if (fallbackPort === null) {
          setSidecarStatus({
            state: "error",
            managed: false,
            pid: null,
            health: null,
            error: {
              code: "PORT_IN_USE",
              message: `端口 ${preferredPort} 被占用且不是可用后端，且 ${preferredPort + 1}-${preferredPort + PORT_SEARCH_RANGE} 也全部被占用。请释放其中任一端口后重启应用。`,
            },
          });
          return;
        }
        console.warn(`端口 ${preferredPort} 被占用，改用备选端口 ${fallbackPort} 启动后端。`);
        selectedPort = fallbackPort;
      }
    } catch (error) {
      console.error("无法检查 FastAPI 后端端口。", error);
      setSidecarStatus({
        state: "error",
        health: null,
        error: {
          code: "PORT_CHECK_FAILED",
          message: error.message,
        },
      });
      return;
    }

    const backendDirectory = findBackendDirectory();
    if (!backendDirectory) {
      console.error("无法定位 FastAPI 后端目录。");
      setSidecarStatus({
        state: "error",
        health: null,
        error: {
          code: "BACKEND_NOT_FOUND",
          message: "未找到后端目录。请确认 apps/backend/app/main.py 存在，或设置 AGENT_PET_BACKEND_DIR 指向后端目录后重启。",
        },
      });
      return;
    }

    updateRuntimePort(selectedPort);

    const pythonCommand =
      process.env.AGENT_PET_PYTHON || (process.platform === "win32" ? "python" : "python3");

    setSidecarStatus({
      state: "starting",
      managed: true,
      pid: null,
      health: null,
      error: null,
    });

    sidecarProcess = spawn(
      pythonCommand,
      ["-m", "uvicorn", "app.main:app", "--host", portRuntime.host, "--port", String(portRuntime.port)],
      {
        cwd: backendDirectory,
        env: getSidecarEnvironment(),
        stdio: "inherit",
        windowsHide: true,
      },
    );

    setSidecarStatus({
      state: "starting",
      managed: true,
      pid: sidecarProcess.pid ?? null,
      health: null,
      error: null,
    });

    sidecarReadinessAbort?.abort();
    const readinessAbort = new AbortController();
    sidecarReadinessAbort = readinessAbort;
    waitForSidecarReady(readinessAbort.signal)
      .then((health) => {
        if (!sidecarProcess || readinessAbort.signal.aborted) {
          return;
        }

        setSidecarStatus({
          state: "ready",
          managed: true,
          pid: sidecarProcess.pid ?? null,
          error: null,
          health,
        });
      })
      .catch((error) => {
        // waitForSidecarReady 只在被取消时抛出（进程退出或应用退出触发），
        // 超时本身不再终止等待，也不再杀进程。
        if (readinessAbort.signal.aborted || state.isQuitting) {
          return;
        }
        console.error("后端就绪等待意外中断。", error);
      });

    sidecarProcess.on("exit", (code, signal) => {
      sidecarReadinessAbort?.abort();
      sidecarReadinessAbort = null;
      if (code && code !== 0) {
        console.error(`FastAPI 后端退出，返回码 ${code}。`);
      } else if (signal) {
        console.error(`FastAPI 后端收到信号 ${signal} 后退出。`);
      }
      sidecarProcess = null;
      setSidecarStatus({
        state: state.isQuitting ? "stopped" : "error",
        managed: false,
        pid: null,
        health: null,
        error: state.isQuitting
          ? null
          : {
              code: "PROCESS_EXITED",
              message: signal
                ? `后端进程收到 ${signal} 后退出。请查看启动日志。`
                : `后端进程退出，退出码 ${code ?? 0}。请查看启动日志。`,
            },
      });
    });

    sidecarProcess.on("error", (error) => {
      console.error("启动 FastAPI 后端失败。", error);
      sidecarReadinessAbort?.abort();
      sidecarReadinessAbort = null;
      sidecarProcess = null;
      setSidecarStatus({
        state: "error",
        managed: false,
        pid: null,
        health: null,
        error: {
          code: "SPAWN_FAILED",
          message: `无法启动后端进程。请确认 Python/uvicorn 可用，或设置 AGENT_PET_PYTHON。原始错误：${error.message}`,
        },
      });
    });
  }

  function killSidecarProcessTree(child) {
    if (typeof child.pid !== "number") {
      if (!child.killed) {
        child.kill();
      }
      return;
    }

    if (process.platform === "win32") {
      // child.kill() 只终止 uvicorn 主进程，reload/worker 子进程会残留并占住
      // 端口；taskkill /T /F 终止整棵进程树。taskkill 不可用时回退单进程 kill。
      try {
        const killer = spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
          stdio: "ignore",
          windowsHide: true,
        });
        killer.on("error", () => {
          if (!child.killed) {
            child.kill();
          }
        });
      } catch {
        if (!child.killed) {
          child.kill();
        }
      }
      return;
    }

    if (!child.killed) {
      child.kill();
    }
    const forceKillTimer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) {
        try {
          child.kill("SIGKILL");
        } catch {
          // 进程已经消失时忽略。
        }
      }
    }, STOP_FORCE_KILL_TIMEOUT_MS);
    forceKillTimer.unref?.();
    child.once("exit", () => clearTimeout(forceKillTimer));
  }

  function stopSidecar() {
    if (!sidecarProcess) {
      return;
    }

    const child = sidecarProcess;
    sidecarProcess = null;
    sidecarReadinessAbort?.abort();
    sidecarReadinessAbort = null;
    setSidecarStatus({
      state: "stopping",
      pid: child.pid ?? null,
      health: null,
      error: null,
    });

    killSidecarProcessTree(child);
  }

  function abortSidecarReadiness() {
    sidecarReadinessAbort?.abort();
    sidecarReadinessAbort = null;
  }

  return {
    startSidecar,
    stopSidecar,
    abortSidecarReadiness,
    getPublicSidecarStatus,
    showReminderNotification,
  };
}

module.exports = {
  createSidecarManager,
};
