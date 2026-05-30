const { app, BrowserWindow, Notification } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

function createSidecarManager({ host, port, baseUrl, sessionToken, managedSidecarDataDir, state, showControlWindow }) {
  let sidecarProcess = null;
  let sidecarReadinessAbort = null;
  let sidecarExitErrorOverride = null;
  const deliveredReminderNotifications = new Set();
  let sidecarStatus = {
    state: "stopped",
    baseUrl,
    host,
    port,
    dataDir: managedSidecarDataDir,
    managed: false,
    pid: null,
    health: null,
    error: null,
    updatedAt: new Date().toISOString(),
  };

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
    };

    if (!env.AGENT_PET_DATA_DIR && !env.AGENT_PET_SQLITE_PATH) {
      env.AGENT_PET_DATA_DIR = managedSidecarDataDir;
    }

    return env;
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
    deliveredReminderNotifications.add(reminderId);
    return {
      status: "shown",
      reminder_id: reminderId,
    };
  }

  function setSidecarStatus(patch) {
    sidecarStatus = {
      ...sidecarStatus,
      ...patch,
      updatedAt: new Date().toISOString(),
    };

    for (const window of BrowserWindow.getAllWindows()) {
      window.webContents.send("agent-pet:sidecar-status-changed", getPublicSidecarStatus());
    }
  }

  function isPortAvailable() {
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

      server.listen(port, host);
    });
  }

  async function waitForSidecarReady(signal) {
    const deadline = Date.now() + 30_000;
    let lastError = null;

    while (Date.now() < deadline) {
      if (signal.aborted) {
        throw new Error("后端就绪等待被取消。");
      }

      try {
        const health = await requestJson(`${baseUrl}/api/health`, signal);
        if (health && typeof health.status === "string") {
          return health;
        }
      } catch (error) {
        lastError = error;
      }

      await delay(250, signal);
    }

    const message = lastError?.message ? ` Last error: ${lastError.message}` : "";
    throw new Error(`等待后端健康就绪超时。${message}`);
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

    let portAvailable = false;
    try {
      portAvailable = await isPortAvailable();
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

    if (!portAvailable) {
      try {
        const health = await requestJson(`${baseUrl}/api/health`, AbortSignal.timeout(2_000));
        setSidecarStatus({
          state: "ready",
          managed: false,
          pid: null,
          health,
          error: {
            code: "PORT_IN_USE_EXISTING_BACKEND",
            message: `端口 ${port} 已有后端响应，已复用现有后端。若业务请求返回 401，请关闭占用进程后重启，或用相同 AGENT_PET_SESSION_TOKEN 启动后端。`,
          },
        });
      } catch (error) {
        setSidecarStatus({
          state: "error",
          managed: false,
          pid: null,
          health: null,
          error: {
            code: "PORT_IN_USE",
            message: `端口 ${port} 已被占用，但没有响应 /api/health。请关闭占用 ${port} 的进程，或把后端改到桌面端约定端口后重启 npm run electron:dev。原始错误：${error.message}`,
          },
        });
      }
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
      ["-m", "uvicorn", "app.main:app", "--host", host, "--port", String(port)],
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
    sidecarReadinessAbort = new AbortController();
    waitForSidecarReady(sidecarReadinessAbort.signal)
      .then((health) => {
        if (!sidecarProcess || sidecarReadinessAbort?.signal.aborted) {
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
        if (sidecarReadinessAbort?.signal.aborted || state.isQuitting) {
          return;
        }

        console.error("FastAPI 后端未能就绪。", error);
        const readinessError = {
          code: "READINESS_FAILED",
          message: `后端进程已启动但健康检查未通过。请检查 Python 依赖、数据库配置和控制台日志。原始错误：${error.message}`,
        };
        sidecarExitErrorOverride = readinessError;
        setSidecarStatus({
          state: "error",
          managed: true,
          pid: sidecarProcess?.pid ?? null,
          health: null,
          error: readinessError,
        });
        stopSidecar();
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
      const exitErrorOverride = sidecarExitErrorOverride;
      sidecarExitErrorOverride = null;
      setSidecarStatus({
        state: state.isQuitting ? "stopped" : "error",
        managed: false,
        pid: null,
        health: null,
        error: state.isQuitting
          ? null
          : exitErrorOverride ?? {
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

    if (!child.killed) {
      child.kill();
    }
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
