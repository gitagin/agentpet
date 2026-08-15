const crypto = require("node:crypto");

const DEFAULT_REMINDER_POLL_INTERVAL_MS = 15_000;
const RESIDENT_LOGIN_ARGS = Object.freeze(["--resident"]);

function isResidentLaunch(argv = process.argv) {
  return Array.isArray(argv) && argv.includes("--resident");
}

function parseApiJson(response, operation) {
  if (response && typeof response.status === "number") {
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`${operation} failed with HTTP ${response.status}`);
    }
    try {
      return JSON.parse(response.body);
    } catch (error) {
      throw new Error(`${operation} returned invalid JSON`, { cause: error });
    }
  }
  if (response && typeof response === "object") {
    return response;
  }
  throw new Error(`${operation} returned an invalid response`);
}

function reminderPayload(task) {
  if (!task || typeof task !== "object" || task.reminder_status !== "triggered") {
    return null;
  }
  const reminderId = typeof task.reminder_id === "string" ? task.reminder_id.trim() : "";
  const triggerAt = typeof task.remind_at === "string" && task.remind_at.trim()
    ? task.remind_at.trim()
    : typeof task.triggered_at === "string"
      ? task.triggered_at.trim()
      : "";
  if (!reminderId || !triggerAt) {
    return null;
  }
  const title = typeof task.title === "string" && task.title.trim()
    ? task.title.trim()
    : "Agent Pet 提醒";
  const body = typeof task.description === "string" && task.description.trim()
    ? task.description.trim()
    : typeof task.remind_at === "string" && task.remind_at.trim()
      ? task.remind_at.trim()
      : "提醒已到期。";
  return {
    reminder_id: reminderId,
    trigger_at: triggerAt,
    dispatch_kind: "automatic",
    title,
    body,
  };
}

function createResidentRuntime({
  electronApp,
  powerMonitor,
  sidecar,
  proxy,
  dispatchReminderNotification,
  platform = process.platform,
  reminderPollIntervalMs = DEFAULT_REMINDER_POLL_INTERVAL_MS,
  timerApi = globalThis,
  onReminderDispatch,
}) {
  let monitoring = false;
  let suspended = false;
  let stopped = false;
  let lifecycleGeneration = 0;
  let reminderTimer = null;
  let reminderPollInFlight = null;
  let backendRecoveryInFlight = null;
  let sidecarRecoveryReportInFlight = null;
  let activeResume = null;
  const pollInterval = Number.isFinite(reminderPollIntervalMs) && reminderPollIntervalMs > 0
    ? reminderPollIntervalMs
    : DEFAULT_REMINDER_POLL_INTERVAL_MS;

  const scheduleInterval = typeof timerApi?.setInterval === "function"
    ? timerApi.setInterval.bind(timerApi)
    : setInterval;
  const cancelInterval = typeof timerApi?.clearInterval === "function"
    ? timerApi.clearInterval.bind(timerApi)
    : clearInterval;

  function getLoginItemStatus() {
    const supported = platform === "win32"
      && typeof electronApp.getLoginItemSettings === "function"
      && typeof electronApp.setLoginItemSettings === "function";
    if (!supported) {
      return { supported: false, enabled: false };
    }
    const settings = electronApp.getLoginItemSettings({ args: [...RESIDENT_LOGIN_ARGS] });
    return {
      supported: true,
      enabled: Boolean(settings?.openAtLogin),
    };
  }

  function setLoginItemEnabled(enabled) {
    if (typeof enabled !== "boolean") {
      throw new TypeError("enabled must be a boolean");
    }
    const current = getLoginItemStatus();
    if (!current.supported) {
      return current;
    }
    electronApp.setLoginItemSettings({
      openAtLogin: enabled,
      args: [...RESIDENT_LOGIN_ARGS],
    });
    return getLoginItemStatus();
  }

  async function reportPendingSidecarRecovery() {
    if (stopped || suspended || typeof sidecar.getPendingRecoveryIncident !== "function") {
      return null;
    }
    const incident = sidecar.getPendingRecoveryIncident();
    if (!incident?.incident_id || !incident.ready_at) {
      return null;
    }
    if (sidecarRecoveryReportInFlight) {
      return sidecarRecoveryReportInFlight;
    }
    const report = (async () => {
      const idempotencyKey = crypto
        .createHash("sha256")
        .update(`sidecar-recovery:${incident.incident_id}`)
        .digest("hex");
      const response = await proxy.requestInternalApi("/api/metrics/sidecar-recovery", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify(incident),
      });
      const parsed = parseApiJson(response, "sidecar recovery metric");
      if (
        parsed.incident_id !== incident.incident_id
        || !["recorded", "replayed"].includes(parsed.status)
      ) {
        throw new Error("sidecar recovery metric returned a mismatched receipt");
      }
      sidecar.acknowledgeRecoveryIncident?.(incident.incident_id);
      return parsed;
    })();
    sidecarRecoveryReportInFlight = report;
    try {
      return await report;
    } finally {
      if (sidecarRecoveryReportInFlight === report) {
        sidecarRecoveryReportInFlight = null;
      }
    }
  }

  async function recoverBackendState() {
    if (backendRecoveryInFlight) {
      return backendRecoveryInFlight;
    }
    const recovery = (async () => {
      const result = {
        reminders: null,
        graph: null,
      };
      try {
        result.reminders = await proxy.proxyApiRequest(
          "/api/tasks/reminder-delivery/recover",
          { method: "POST", body: "{}" },
        );
      } catch (error) {
        console.warn("提醒恢复检查失败。", error);
      }
      try {
        result.graph = await proxy.proxyApiRequest("/api/memory/graph?limit=5", { method: "GET" });
      } catch (error) {
        console.warn("记忆图谱代次检查失败，SQLite 仍是权威回退。", error);
      }
      return result;
    })();
    backendRecoveryInFlight = recovery;
    try {
      return await recovery;
    } finally {
      if (backendRecoveryInFlight === recovery) {
        backendRecoveryInFlight = null;
      }
    }
  }

  function stopReminderPolling() {
    if (reminderTimer === null) {
      return;
    }
    cancelInterval(reminderTimer);
    reminderTimer = null;
  }

  async function pollTriggeredReminders() {
    if (stopped) {
      return { status: "stopped", attempted: 0, results: [] };
    }
    if (suspended) {
      return { status: "suspended", attempted: 0, results: [] };
    }
    if (typeof sidecar.getPublicSidecarStatus === "function") {
      let sidecarStatus;
      try {
        sidecarStatus = sidecar.getPublicSidecarStatus();
      } catch (error) {
        console.warn("Resident reminder poll could not read sidecar status.", error);
        return { status: "not_ready", attempted: 0, results: [] };
      }
      if (sidecarStatus?.state && sidecarStatus.state !== "ready") {
        return { status: "not_ready", attempted: 0, results: [] };
      }
    }
    try {
      await reportPendingSidecarRecovery();
    } catch (error) {
      console.warn("Sidecar recovery metric could not be recorded; the next resident poll will retry.", error);
    }
    if (reminderPollInFlight) {
      return reminderPollInFlight;
    }

    const poll = (async () => {
      const response = await proxy.proxyApiRequest("/api/tasks", { method: "GET" });
      const parsed = parseApiJson(response, "resident reminder poll");
      if (!Array.isArray(parsed.tasks)) {
        throw new Error("resident reminder poll returned no task list");
      }

      const reminders = parsed.tasks
        .map(reminderPayload)
        .filter(Boolean)
        .sort((left, right) => {
          const leftTime = Date.parse(left.trigger_at);
          const rightTime = Date.parse(right.trigger_at);
          if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
            return leftTime - rightTime;
          }
          return left.reminder_id.localeCompare(right.reminder_id);
        });
      const results = [];
      for (const payload of reminders) {
        if (suspended) {
          break;
        }
        if (typeof dispatchReminderNotification !== "function") {
          throw new Error("resident reminder dispatcher is unavailable");
        }
        try {
          const result = await dispatchReminderNotification({ proxy, sidecar, payload });
          results.push({ payload, result });
          try {
            onReminderDispatch?.(result, payload);
          } catch (error) {
            console.warn("Resident reminder status callback failed.", error);
          }
        } catch (error) {
          console.warn(`Resident reminder dispatch failed for ${payload.reminder_id}.`, error);
          const result = {
            status: "unknown",
            reminder_id: payload.reminder_id,
            reason: "dispatch_unconfirmed",
          };
          results.push({ payload, result, error });
          try {
            onReminderDispatch?.(result, payload);
          } catch (callbackError) {
            console.warn("Resident reminder status callback failed.", callbackError);
          }
        }
      }
      return {
        status: "ok",
        attempted: results.length,
        results,
      };
    })();
    reminderPollInFlight = poll;
    try {
      return await poll;
    } catch (error) {
      console.warn("Resident reminder poll failed; the next poll will retry.", error);
      return {
        status: "error",
        attempted: 0,
        results: [],
        error,
      };
    } finally {
      if (reminderPollInFlight === poll) {
        reminderPollInFlight = null;
      }
    }
  }

  function startReminderPolling() {
    if (stopped || suspended || reminderTimer !== null) {
      return false;
    }
    reminderTimer = scheduleInterval(() => {
      void pollTriggeredReminders();
    }, pollInterval);
    reminderTimer?.unref?.();
    void pollTriggeredReminders();
    return true;
  }

  async function handleSidecarReady() {
    if (stopped) {
      return { reminders: null, graph: null };
    }
    if (suspended) {
      return { reminders: null, graph: null };
    }
    if (activeResume && activeResume.generation === lifecycleGeneration) {
      activeResume.readyHandled = true;
    }
    suspended = false;
    stopReminderPolling();
    try {
      await reportPendingSidecarRecovery();
    } catch (error) {
      console.warn("Sidecar recovery metric could not be recorded; the resident loop will retry.", error);
    }
    const result = await recoverBackendState();
    if (!suspended) {
      startReminderPolling();
    }
    return result;
  }

  function handleSuspend() {
    lifecycleGeneration += 1;
    suspended = true;
    activeResume = null;
    stopReminderPolling();
    sidecar.handleSuspend?.();
  }

  function handleResume() {
    const resumeGeneration = lifecycleGeneration;
    const resumeContext = { generation: resumeGeneration, readyHandled: false };
    activeResume = resumeContext;
    suspended = false;
    return Promise.resolve()
      .then(() => sidecar.handleResume?.())
      .then(async (status) => {
        if (
          !stopped
          && resumeGeneration === lifecycleGeneration
          && status?.state === "ready"
          && !resumeContext.readyHandled
        ) {
          await handleSidecarReady();
        }
        return status;
      })
      .catch((error) => {
        console.warn("睡眠恢复失败，需要手动重试。", error);
        return null;
      })
      .finally(() => {
        if (activeResume === resumeContext) {
          activeResume = null;
        }
      });
  }

  function startPowerMonitoring() {
    if (monitoring || !powerMonitor?.on) {
      return;
    }
    stopped = false;
    monitoring = true;
    powerMonitor.on("suspend", handleSuspend);
    powerMonitor.on("resume", handleResume);
  }

  function stopPowerMonitoring() {
    stopped = true;
    suspended = true;
    lifecycleGeneration += 1;
    stopReminderPolling();
    if (!monitoring || !powerMonitor?.removeListener) {
      return;
    }
    monitoring = false;
    powerMonitor.removeListener("suspend", handleSuspend);
    powerMonitor.removeListener("resume", handleResume);
  }

  return {
    getLoginItemStatus,
    setLoginItemEnabled,
    recoverBackendState,
    reportPendingSidecarRecovery,
    handleSidecarReady,
    handleSuspend,
    handleResume,
    pollTriggeredReminders,
    startReminderPolling,
    stopReminderPolling,
    retrySidecar: () => sidecar.retrySidecar?.(),
    startPowerMonitoring,
    stopPowerMonitoring,
  };
}

module.exports = {
  DEFAULT_REMINDER_POLL_INTERVAL_MS,
  createResidentRuntime,
  isResidentLaunch,
  parseApiJson,
  reminderPayload,
};
