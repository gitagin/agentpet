const { app, BrowserWindow, Notification } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const SIDECAR_EXECUTABLE_NAME = "agent-pet-sidecar.exe";
const RUNTIME_LINE_PREFIX = "AGENT_PET_SIDECAR_RUNTIME ";
const ERROR_LINE_PREFIX = "AGENT_PET_SIDECAR_ERROR ";
const PORT_SEARCH_RANGE = 20;
const DEFAULT_READY_TIMEOUT_MS = 30_000;
const READY_POLL_INTERVAL_MS = 250;
const READY_STALLED_POLL_INTERVAL_MS = 1_000;
const STOP_FORCE_KILL_TIMEOUT_MS = 5_000;
const MAX_DELIVERED_REMINDER_IDS = 500;

function resolveReadyTimeoutMs() {
  const raw = Number.parseInt(process.env.AGENT_PET_READY_TIMEOUT_MS ?? "", 10);
  return Number.isFinite(raw) && raw >= 1_000 ? raw : DEFAULT_READY_TIMEOUT_MS;
}

function createSidecarManager({
  host,
  port,
  baseUrl,
  runtime,
  sessionToken,
  managedSidecarDataDir,
  state,
  showControlWindow,
  platform = process.platform,
}) {
  const portRuntime = runtime ?? { host, port, baseUrl };
  const preferredPort = portRuntime.port;
  const sidecarLogPath = path.join(app.getPath("logs"), "sidecar", "agent-pet-sidecar.log");
  let sidecarProcess = null;
  let stoppingSidecarProcess = null;
  let sidecarReadinessAbort = null;
  let runtimeHandshakeTimer = null;
  let logWriteErrorReported = false;
  const deliveredReminderNotifications = new Set();
  let sidecarStatus = {
    state: "stopped",
    baseUrl: portRuntime.baseUrl,
    host: portRuntime.host,
    port: portRuntime.port,
    logPath: sidecarLogPath,
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
    const candidates = [
      process.env.AGENT_PET_BACKEND_DIR,
      path.resolve(app.getAppPath(), "..", "backend"),
      path.resolve(process.cwd(), "..", "backend"),
      path.resolve(__dirname, "..", "..", "backend"),
    ]
      .filter(Boolean)
      .map((candidate) => path.resolve(candidate));

    for (const candidate of candidates) {
      if (fs.existsSync(path.join(candidate, "app", "sidecar_entry.py"))) {
        return candidate;
      }
    }

    return null;
  }

  function findPackagedSidecarExecutable() {
    const packagedResourcesPath =
      typeof process.resourcesPath === "string" ? process.resourcesPath : null;
    const candidates = [
      process.env.AGENT_PET_SIDECAR_EXECUTABLE,
      packagedResourcesPath
        ? path.join(packagedResourcesPath, "sidecar", SIDECAR_EXECUTABLE_NAME)
        : null,
    ]
      .filter(Boolean)
      .map((candidate) => path.resolve(candidate));

    return candidates.find((candidate) => fs.existsSync(candidate)) ?? null;
  }

  function getPublicSidecarStatus() {
    const { dataDir, ...publicStatus } = sidecarStatus;
    return publicStatus;
  }

  function getSidecarEnvironment() {
    const env = {
      ...process.env,
      AGENT_PET_SESSION_TOKEN: sessionToken,
      AGENT_PET_BACKEND_HOST: portRuntime.host,
      AGENT_PET_BACKEND_PORT: String(portRuntime.port),
    };

    if (!env.AGENT_PET_DATA_DIR && !env.AGENT_PET_SQLITE_PATH) {
      env.AGENT_PET_DATA_DIR = managedSidecarDataDir;
    }

    return env;
  }

  function messageWithLogPath(message) {
    return `${message} 日志：${sidecarLogPath}`;
  }

  function prepareSidecarLog() {
    try {
      fs.mkdirSync(path.dirname(sidecarLogPath), { recursive: true });
      fs.appendFileSync(
        sidecarLogPath,
        `\n[${new Date().toISOString()}] Agent Pet sidecar launch requested.\n`,
        "utf8",
      );
      return null;
    } catch (error) {
      return error;
    }
  }

  function appendSidecarLog(chunk) {
    try {
      fs.appendFileSync(sidecarLogPath, chunk);
    } catch (error) {
      if (!logWriteErrorReported) {
        logWriteErrorReported = true;
        console.error(`无法写入 sidecar 日志 ${sidecarLogPath}。`, error);
      }
    }
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
      : "Agent Pet 提醒";
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
      logPath: sidecarLogPath,
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

  async function waitForSidecarReady(signal) {
    const timeoutMs = resolveReadyTimeoutMs();
    const deadline = Date.now() + timeoutMs;
    let stalledReported = false;
    let lastError = null;

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
        message: messageWithLogPath(
          `后端进程已启动，但 ${Math.round(timeoutMs / 1000)} 秒内未通过健康检查。进程仍在运行并会继续等待；可稍候或重启应用重试，也可用 AGENT_PET_READY_TIMEOUT_MS 调整提示时长。${suffix}`,
        ),
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

  function clearRuntimeHandshakeTimer() {
    if (runtimeHandshakeTimer) {
      clearTimeout(runtimeHandshakeTimer);
      runtimeHandshakeTimer = null;
    }
  }

  function createLineConsumer(onLine) {
    let buffered = "";
    return {
      write(chunk) {
        appendSidecarLog(chunk);
        buffered += Buffer.isBuffer(chunk) ? chunk.toString("utf8") : String(chunk);
        const lines = buffered.split(/\r?\n/);
        buffered = lines.pop() ?? "";
        for (const line of lines) {
          onLine(line);
        }
      },
      flush() {
        if (buffered) {
          onLine(buffered);
          buffered = "";
        }
      },
    };
  }

  function parseControlPayload(line, prefix) {
    if (!line.startsWith(prefix)) {
      return null;
    }
    const payload = JSON.parse(line.slice(prefix.length));
    if (!payload || typeof payload !== "object") {
      throw new Error("control payload must be an object");
    }
    return payload;
  }

  function resolveSidecarLaunch() {
    const commonArgs = [
      "--host",
      portRuntime.host,
      "--port",
      String(preferredPort),
      "--port-search-range",
      String(PORT_SEARCH_RANGE),
    ];

    if (app.isPackaged) {
      const executable = findPackagedSidecarExecutable();
      if (!executable) {
        return {
          error: {
            code: "SIDECAR_EXECUTABLE_NOT_FOUND",
            message: messageWithLogPath(
              `发布包缺少 resources/sidecar/${SIDECAR_EXECUTABLE_NAME}，无法启动本机服务。请重新下载或重新打包应用。`,
            ),
          },
        };
      }
      return {
        command: executable,
        args: commonArgs,
        cwd: path.dirname(executable),
        kind: "frozen",
      };
    }

    const backendDirectory = findBackendDirectory();
    if (!backendDirectory) {
      return {
        error: {
          code: "BACKEND_NOT_FOUND",
          message: messageWithLogPath(
            "未找到开发后端目录。请确认 apps/backend/app/sidecar_entry.py 存在，或设置 AGENT_PET_BACKEND_DIR 后重启。",
          ),
        },
      };
    }

    const pythonCommand =
      process.env.AGENT_PET_PYTHON || (platform === "win32" ? "python" : "python3");
    return {
      command: pythonCommand,
      args: ["-m", "app.sidecar_entry", ...commonArgs],
      cwd: backendDirectory,
      kind: "python",
    };
  }

  function beginReadinessWait(child) {
    sidecarReadinessAbort?.abort();
    const readinessAbort = new AbortController();
    sidecarReadinessAbort = readinessAbort;
    waitForSidecarReady(readinessAbort.signal)
      .then((health) => {
        if (sidecarProcess !== child || readinessAbort.signal.aborted) {
          return;
        }

        setSidecarStatus({
          state: "ready",
          managed: true,
          pid: child.pid ?? null,
          error: null,
          health,
        });
      })
      .catch((error) => {
        if (readinessAbort.signal.aborted || state.isQuitting) {
          return;
        }
        console.error("后端就绪等待意外中断。", error);
      });
  }

  async function startSidecar() {
    if (sidecarProcess || stoppingSidecarProcess) {
      return;
    }

    updateRuntimePort(preferredPort);
    setSidecarStatus({
      state: "checking-port",
      managed: false,
      pid: null,
      health: null,
      error: null,
    });

    try {
      const preferredAvailable = await isPortAvailable(preferredPort);
      if (!preferredAvailable) {
        let existingHealth = null;
        try {
          existingHealth = await requestJson(
            `http://${portRuntime.host}:${preferredPort}/api/health`,
            AbortSignal.timeout(2_000),
          );
        } catch {
          existingHealth = null;
        }

        if (existingHealth && typeof existingHealth.status === "string") {
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

        console.warn(
          `端口 ${preferredPort} 被非后端进程占用；sidecar 将原子搜索 ${preferredPort + 1}-${preferredPort + PORT_SEARCH_RANGE}。`,
        );
      }
    } catch (error) {
      console.error("无法检查 FastAPI 后端端口。", error);
      setSidecarStatus({
        state: "error",
        health: null,
        error: {
          code: "PORT_CHECK_FAILED",
          message: messageWithLogPath(error.message),
        },
      });
      return;
    }

    const logError = prepareSidecarLog();
    if (logError) {
      setSidecarStatus({
        state: "error",
        managed: false,
        pid: null,
        health: null,
        error: {
          code: "SIDECAR_LOG_UNAVAILABLE",
          message: `无法创建 sidecar 日志 ${sidecarLogPath}：${logError.message}`,
        },
      });
      return;
    }

    const launch = resolveSidecarLaunch();
    if (launch.error) {
      appendSidecarLog(`${launch.error.code}: ${launch.error.message}\n`);
      setSidecarStatus({
        state: "error",
        managed: false,
        pid: null,
        health: null,
        error: launch.error,
      });
      return;
    }

    appendSidecarLog(`Launching ${launch.kind} sidecar: ${launch.command} ${launch.args.join(" ")}\n`);
    setSidecarStatus({
      state: "starting",
      managed: true,
      pid: null,
      health: null,
      error: null,
    });

    let child;
    try {
      child = spawn(launch.command, launch.args, {
        cwd: launch.cwd,
        env: getSidecarEnvironment(),
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      });
    } catch (error) {
      setSidecarStatus({
        state: "error",
        managed: false,
        pid: null,
        health: null,
        error: {
          code: "SPAWN_FAILED",
          message: messageWithLogPath(`无法启动后端进程。原始错误：${error.message}`),
        },
      });
      return;
    }

    sidecarProcess = child;
    let runtimeReceived = false;
    let startupError = null;
    let terminalHandled = false;

    const handleOutputLine = (line) => {
      try {
        const runtimePayload = parseControlPayload(line, RUNTIME_LINE_PREFIX);
        if (runtimePayload) {
          const runtimePort = Number(runtimePayload.port);
          if (
            runtimePayload.host !== portRuntime.host ||
            !Number.isInteger(runtimePort) ||
            runtimePort < 1 ||
            runtimePort > 65_535
          ) {
            throw new Error("runtime host or port is invalid");
          }
          if (runtimeReceived || sidecarProcess !== child) {
            return;
          }

          runtimeReceived = true;
          startupError = null;
          clearRuntimeHandshakeTimer();
          updateRuntimePort(runtimePort);
          setSidecarStatus({
            state: "starting",
            managed: true,
            pid: child.pid ?? null,
            health: null,
            error: null,
          });
          beginReadinessWait(child);
          return;
        }

        const errorPayload = parseControlPayload(line, ERROR_LINE_PREFIX);
        if (errorPayload) {
          startupError = {
            code: typeof errorPayload.code === "string" ? errorPayload.code : "STARTUP_FAILED",
            message: messageWithLogPath(
              typeof errorPayload.message === "string"
                ? errorPayload.message
                : "Sidecar reported an unknown startup failure.",
            ),
          };
          setSidecarStatus({
            state: "error",
            managed: true,
            pid: child.pid ?? null,
            health: null,
            error: startupError,
          });
        }
      } catch (error) {
        startupError = {
          code: "RUNTIME_HANDSHAKE_INVALID",
          message: messageWithLogPath(`Sidecar 运行时握手无效：${error.message}`),
        };
        setSidecarStatus({
          state: "starting",
          managed: true,
          pid: child.pid ?? null,
          health: null,
          error: startupError,
        });
      }
    };

    const stdoutConsumer = createLineConsumer(handleOutputLine);
    const stderrConsumer = createLineConsumer(handleOutputLine);
    child.stdout?.on("data", (chunk) => stdoutConsumer.write(chunk));
    child.stderr?.on("data", (chunk) => stderrConsumer.write(chunk));

    const cleanupChildRuntime = () => {
      clearRuntimeHandshakeTimer();
      if (sidecarReadinessAbort) {
        sidecarReadinessAbort.abort();
        sidecarReadinessAbort = null;
      }
      stdoutConsumer.flush();
      stderrConsumer.flush();
    };

    child.on("exit", (code, signal) => {
      if (terminalHandled) {
        return;
      }
      terminalHandled = true;
      const stoppedIntentionally = stoppingSidecarProcess === child || state.isQuitting;
      cleanupChildRuntime();
      if (sidecarProcess === child) {
        sidecarProcess = null;
      }
      if (stoppingSidecarProcess === child) {
        stoppingSidecarProcess = null;
      }

      if (stoppedIntentionally) {
        setSidecarStatus({
          state: "stopped",
          managed: false,
          pid: null,
          health: null,
          error: null,
        });
        return;
      }

      if (code && code !== 0) {
        console.error(`FastAPI 后端退出，返回码 ${code}。`);
      } else if (signal) {
        console.error(`FastAPI 后端收到信号 ${signal} 后退出。`);
      }
      setSidecarStatus({
        state: "error",
        managed: false,
        pid: null,
        health: null,
        error: startupError ?? {
          code: "PROCESS_EXITED",
          message: messageWithLogPath(
            signal
              ? `后端进程收到 ${signal} 后退出。`
              : `后端进程退出，退出码 ${code ?? 0}。`,
          ),
        },
      });
    });

    child.on("error", (error) => {
      if (terminalHandled) {
        return;
      }
      terminalHandled = true;
      console.error("启动 FastAPI 后端失败。", error);
      const stoppedIntentionally = stoppingSidecarProcess === child || state.isQuitting;
      cleanupChildRuntime();
      if (sidecarProcess === child) {
        sidecarProcess = null;
      }
      if (stoppingSidecarProcess === child) {
        stoppingSidecarProcess = null;
      }
      setSidecarStatus({
        state: stoppedIntentionally ? "stopped" : "error",
        managed: false,
        pid: null,
        health: null,
        error: stoppedIntentionally
          ? null
          : {
              code: "SPAWN_FAILED",
              message: messageWithLogPath(`无法启动后端进程。原始错误：${error.message}`),
            },
      });
    });

    runtimeHandshakeTimer = setTimeout(() => {
      if (sidecarProcess !== child || runtimeReceived) {
        return;
      }
      startupError = {
        code: "RUNTIME_HANDSHAKE_TIMEOUT",
        message: messageWithLogPath(
          `后端进程已启动，但 ${Math.round(resolveReadyTimeoutMs() / 1000)} 秒内未报告监听端口。进程仍在运行并会继续等待。`,
        ),
      };
      setSidecarStatus({
        state: "starting",
        managed: true,
        pid: child.pid ?? null,
        health: null,
        error: startupError,
      });
    }, resolveReadyTimeoutMs());
    runtimeHandshakeTimer.unref?.();

    setSidecarStatus({
      state: "starting",
      managed: true,
      pid: child.pid ?? null,
      health: null,
      error: null,
    });
  }

  function killSidecarProcessTree(child) {
    if (typeof child.pid !== "number") {
      if (!child.killed) {
        child.kill();
      }
      return;
    }

    if (platform === "win32") {
      let fallbackUsed = false;
      const fallbackKill = () => {
        if (fallbackUsed) {
          return;
        }
        fallbackUsed = true;
        if (!child.killed && child.exitCode == null && child.signalCode == null) {
          child.kill();
        }
      };

      try {
        const killer = spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
          stdio: "ignore",
          windowsHide: true,
        });
        killer.once("error", fallbackKill);
        killer.once("exit", (code) => {
          if (code !== 0) {
            fallbackKill();
          }
        });
      } catch {
        fallbackKill();
      }

      const fallbackTimer = setTimeout(fallbackKill, STOP_FORCE_KILL_TIMEOUT_MS);
      fallbackTimer.unref?.();
      child.once("exit", () => clearTimeout(fallbackTimer));
      return;
    }

    if (!child.killed) {
      child.kill();
    }
    const forceKillTimer = setTimeout(() => {
      if (child.exitCode == null && child.signalCode == null) {
        try {
          child.kill("SIGKILL");
        } catch {
          // The process already exited.
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
    stoppingSidecarProcess = child;
    clearRuntimeHandshakeTimer();
    sidecarReadinessAbort?.abort();
    sidecarReadinessAbort = null;
    setSidecarStatus({
      state: "stopping",
      managed: true,
      pid: child.pid ?? null,
      health: null,
      error: null,
    });

    killSidecarProcessTree(child);
  }

  function abortSidecarReadiness() {
    clearRuntimeHandshakeTimer();
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
