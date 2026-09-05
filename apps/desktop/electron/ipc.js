const { BrowserWindow, dialog, ipcMain, shell } = require("electron");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const deniedVaultPathParts = new Set([".git", ".obsidian"]);

const allowedRendererUiStateKeys = new Set([
  "agent-pet.first-use-onboarding",
  "agent-pet.pet-entry-hint",
  "agent-pet.wiki-archive-candidate",
  "agent-pet.control-home-day-records.v1",
]);
const trustedAppWindowRoles = new Set(["pet", "control", "stage", "agent", "feature"]);
const petWindowRoles = new Set(["pet"]);
const vaultPickerWindowRoles = new Set(["control", "stage", "feature"]);

function normalizeRendererUiStateKey(key) {
  if (typeof key !== "string") {
    return null;
  }
  const normalized = key.trim();
  return allowedRendererUiStateKeys.has(normalized) ? normalized : null;
}

function rejectVaultReveal(reason) {
  return {
    status: "rejected",
    reason,
  };
}

function getSenderWindowRole(windows, sender) {
  return windows.getSenderWindowRole?.(sender) ?? null;
}

function createUnauthorizedIpcError(channel, role) {
  const error = new Error(`Unauthorized IPC sender for ${channel}.`);
  error.code = "unauthorized_ipc_sender";
  error.details = {
    channel,
    role: role || "unknown",
  };
  return error;
}

function assertTrustedSender(windows, sender, allowedRoles, channel) {
  const role = getSenderWindowRole(windows, sender);
  if (!role || !allowedRoles.has(role)) {
    throw createUnauthorizedIpcError(channel, role);
  }
  return role;
}

function normalizeVaultRelativeMarkdownPath(relativePath) {
  if (typeof relativePath !== "string") {
    return null;
  }
  const raw = relativePath.replace(/\\/g, "/");
  if (!raw || raw.trim() !== raw) {
    return null;
  }
  if (raw.startsWith("/") || raw.startsWith("//") || /^[A-Za-z]:/.test(raw)) {
    return null;
  }
  const parts = raw.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    return null;
  }
  if (
    parts.some(
      (part) => part.startsWith(".") || part.includes("~") || part.includes(":") || deniedVaultPathParts.has(part.toLowerCase()),
    )
  ) {
    return null;
  }
  if (path.posix.extname(raw).toLowerCase() !== ".md") {
    return null;
  }
  return parts.join("/");
}

function isInsidePath(rootPath, targetPath) {
  const root = path.resolve(rootPath);
  const target = path.resolve(targetPath);
  const relative = path.relative(root, target);
  return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function resolveVaultMarkdownPath(rootPath, relativePath) {
  if (typeof rootPath !== "string" || !rootPath.trim()) {
    return null;
  }
  const normalizedRelativePath = normalizeVaultRelativeMarkdownPath(relativePath);
  if (!normalizedRelativePath) {
    return null;
  }

  const root = path.resolve(rootPath);
  const target = path.resolve(root, ...normalizedRelativePath.split("/"));
  if (!isInsidePath(root, target)) {
    return null;
  }

  try {
    const realRoot = fs.realpathSync.native(root);
    const existingPath = fs.existsSync(target) ? target : path.dirname(target);
    const realExistingPath = fs.realpathSync.native(existingPath);
    if (!isInsidePath(realRoot, realExistingPath)) {
      return null;
    }
  } catch (_error) {
    return null;
  }

  return {
    root,
    relativePath: normalizedRelativePath,
    absolutePath: target,
  };
}

async function getActiveVaultStatus(proxy) {
  const response = await proxy.proxyApiRequest("/api/vaults/status", { method: "GET" });
  if (!response || response.status < 200 || response.status >= 300) {
    return null;
  }
  try {
    return JSON.parse(response.body);
  } catch (_error) {
    return null;
  }
}

async function revealVaultPath({ proxy, relativePath, mode, shellApi = shell }) {
  const revealMode = mode === "show" ? "show" : mode === "open" ? "open" : null;
  if (!revealMode) {
    return rejectVaultReveal("invalid_mode");
  }

  const status = await getActiveVaultStatus(proxy);
  if (!status?.configured || typeof status.root_path !== "string" || !status.root_path) {
    return rejectVaultReveal("vault_not_configured");
  }

  const resolved = resolveVaultMarkdownPath(status.root_path, relativePath);
  if (!resolved) {
    return rejectVaultReveal("invalid_vault_path");
  }
  if (!fs.existsSync(resolved.absolutePath)) {
    return rejectVaultReveal("target_not_found");
  }

  if (revealMode === "show") {
    shellApi.showItemInFolder(resolved.absolutePath);
    return { status: "shown", relative_path: resolved.relativePath };
  }

  const openError = await shellApi.openPath(resolved.absolutePath);
  if (openError) {
    return { status: "failed", relative_path: resolved.relativePath, reason: openError };
  }
  return { status: "opened", relative_path: resolved.relativePath };
}

function parseProxyJson(response, operation) {
  if (!response || response.status < 200 || response.status >= 300) {
    throw new Error(`${operation} failed with HTTP ${response?.status ?? 0}`);
  }
  try {
    return JSON.parse(response.body);
  } catch (error) {
    throw new Error(`${operation} returned invalid JSON`, { cause: error });
  }
}

function reminderIdempotencyKey(payload) {
  if (payload.dispatch_kind === "manual") {
    return crypto.randomBytes(32).toString("hex");
  }
  return crypto
    .createHash("sha256")
    .update(`automatic\0${payload.reminder_id}\0${payload.trigger_at}`)
    .digest("hex");
}

async function dispatchReminderNotification({ proxy, sidecar, payload }) {
  const reminderId = typeof payload?.reminder_id === "string" ? payload.reminder_id.trim() : "";
  const triggerAt = typeof payload?.trigger_at === "string" ? payload.trigger_at.trim() : "";
  const dispatchKind = payload?.dispatch_kind === "manual" ? "manual" : "automatic";
  if (!reminderId || !triggerAt) {
    return { status: "failed", reminder_id: reminderId || undefined, reason: "invalid_reminder_identity" };
  }

  const key = reminderIdempotencyKey({
    reminder_id: reminderId,
    trigger_at: triggerAt,
    dispatch_kind: dispatchKind,
  });
  const reservation = parseProxyJson(
    await proxy.proxyApiRequest("/api/tasks/reminder-delivery/reservations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": key,
      },
      body: JSON.stringify({
        reminder_id: reminderId,
        trigger_at: triggerAt,
        dispatch_kind: dispatchKind,
      }),
    }),
    "reminder reservation",
  );

  if (reservation.duplicate) {
    const status = reservation.status === "display_invoked"
      ? "duplicate"
      : reservation.status === "unsupported"
        ? "unsupported"
        : reservation.status === "failed"
          ? "failed"
          : "unknown";
    return {
      status,
      reminder_id: reminderId,
      attempt_id: reservation.attempt_id,
      reason: reservation.status,
    };
  }

  let displayResult;
  try {
    displayResult = sidecar.showReminderNotification({
      reminder_id: reminderId,
      title: payload.title,
      body: payload.body,
    });
  } catch {
    displayResult = { status: "failed", reminder_id: reminderId, reason: "notification_api_failed" };
  }
  const resultCode = ["shown", "unsupported", "failed"].includes(displayResult.status)
    ? displayResult.status
    : "failed";
  try {
    parseProxyJson(
      await proxy.proxyApiRequest(
        `/api/tasks/reminder-delivery/attempts/${encodeURIComponent(reservation.attempt_id)}/display`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            result_code: resultCode,
            error: displayResult.reason || null,
          }),
        },
      ),
      "reminder display receipt",
    );
  } catch {
    return {
      status: "unknown",
      reminder_id: reminderId,
      attempt_id: reservation.attempt_id,
      reason: "display_receipt_unconfirmed",
    };
  }
  return {
    ...displayResult,
    attempt_id: reservation.attempt_id,
  };
}

function registerIpcHandlers({ baseUrl, getBaseUrl, rendererUiState, persistRendererUiState, sidecar, proxy, resident, windows }) {
  // 端口搜索可能在运行期改变后端 baseUrl；每次同步查询都返回当前值。
  const resolveBaseUrl = () => (typeof getBaseUrl === "function" ? getBaseUrl() : baseUrl);

  ipcMain.on("agent-pet:get-sidecar-config", (event) => {
    event.returnValue = {
      baseUrl: resolveBaseUrl(),
    };
  });

  ipcMain.on("agent-pet:get-ui-state", (event, key) => {
    const normalized = normalizeRendererUiStateKey(key);
    event.returnValue = normalized ? rendererUiState.get(normalized) ?? null : null;
  });

  ipcMain.handle("agent-pet:set-ui-state", (_event, key, value) => {
    const normalized = normalizeRendererUiStateKey(key);
    if (!normalized) {
      return;
    }
    if (typeof value !== "string" || value.length === 0) {
      rendererUiState.delete(normalized);
      persistRendererUiState?.();
      return;
    }
    if (value.length > 250000) {
      return;
    }
    rendererUiState.set(normalized, value);
    persistRendererUiState?.();
  });

  ipcMain.handle("agent-pet:get-sidecar-status", () => sidecar.getPublicSidecarStatus());

  ipcMain.handle("agent-pet:api-request", async (event, pathOrUrl, options) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:api-request");
    return proxy.proxyApiRequest(pathOrUrl, options);
  });

  ipcMain.handle("agent-pet:reveal-vault-path", async (event, relativePath, mode) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:reveal-vault-path");
    return revealVaultPath({ proxy, relativePath, mode });
  });

  ipcMain.handle("agent-pet:sse-start", async (event, streamId, pathOrUrl) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:sse-start");
    proxy.startSseStream(event.sender, streamId, pathOrUrl);
    return { streamId };
  });

  ipcMain.handle("agent-pet:sse-cancel", (event, streamId) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:sse-cancel");
    proxy.cancelSseStream(streamId);
  });

  ipcMain.handle("agent-pet:show-reminder-notification", (event, payload) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:show-reminder-notification");
    return dispatchReminderNotification({ proxy, sidecar, payload });
  });

  ipcMain.handle("agent-pet:get-login-item-status", (event) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:get-login-item-status");
    return resident.getLoginItemStatus();
  });

  ipcMain.handle("agent-pet:set-login-item-enabled", (event, enabled) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:set-login-item-enabled");
    return resident.setLoginItemEnabled(enabled);
  });

  ipcMain.handle("agent-pet:retry-sidecar", (event) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:retry-sidecar");
    return resident.retrySidecar();
  });

  ipcMain.handle("agent-pet:get-window-mode", (event) => {
    const role = getSenderWindowRole(windows, event.sender);
    if (role === "feature") {
      return windows.getFeatureWindowMode?.(event.sender) || "chat";
    }
    return role || "control";
  });

  ipcMain.handle("agent-pet:open-control-window", (event, targetId) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "agent-pet:open-control-window");
    windows.showControlWindow(targetId);
  });

  ipcMain.handle("window:open-agent", (event) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "window:open-agent");
    windows.showAgentWindow();
  });

  ipcMain.handle("window:close-agent", (event) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "window:close-agent");
    windows.hideAgentWindow();
  });

  ipcMain.handle("window:open-stage", (event, mode) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "window:open-stage");
    windows.showStageWindow(mode);
  });

  ipcMain.handle("window:open-feature", (event, mode) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "window:open-feature");
    windows.showFeatureWindow?.(mode);
  });

  ipcMain.handle("agent-pet:hide-pet-window", async (event) => {
    assertTrustedSender(windows, event.sender, petWindowRoles, "agent-pet:hide-pet-window");
    windows.hidePetWindow?.(event.sender);
  });

  ipcMain.handle("app:quit", (event) => {
    assertTrustedSender(windows, event.sender, trustedAppWindowRoles, "app:quit");
    windows.quitApp();
  });

  ipcMain.handle("agent-pet:get-pet-mouse-passthrough-status", (event) => {
    const petWindow = windows.getPetWindow();
    if (!petWindow || event.sender !== petWindow.webContents) {
      return windows.getPetMousePassthroughStatus("ignored_sender", false);
    }

    return windows.updatePetMousePassthroughFromCursor();
  });

  ipcMain.handle("agent-pet:set-pet-shortcut-bar-visible", (event, visible) => {
    return windows.setPetShortcutBarVisible?.(event.sender, visible);
  });

  ipcMain.handle("agent-pet:set-pet-input-visible", (event, visible) => {
    return windows.setPetInputDockVisible?.(event.sender, visible);
  });

  ipcMain.on("agent-pet:begin-pet-window-drag", (event) => {
    windows.beginPetWindowDrag(event.sender);
  });

  ipcMain.on("agent-pet:activate-pet-window-drag", (event) => {
    windows.activatePetWindowDrag(event.sender);
  });

  ipcMain.on("agent-pet:end-pet-window-drag", (event) => {
    windows.endPetWindowDrag(event.sender);
  });

  ipcMain.handle("agent-pet:select-knowledge-base-folder", async (event) => {
    assertTrustedSender(windows, event.sender, vaultPickerWindowRoles, "agent-pet:select-knowledge-base-folder");
    const ownerWindow = BrowserWindow.fromWebContents(event.sender);
    const result = await dialog.showOpenDialog(ownerWindow ?? undefined, {
      title: "选择知识库文件夹",
      properties: ["openDirectory", "createDirectory"],
    });

    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }

    return result.filePaths[0] || null;
  });
}

module.exports = {
  registerIpcHandlers,
  normalizeVaultRelativeMarkdownPath,
  resolveVaultMarkdownPath,
  revealVaultPath,
  assertTrustedSender,
  dispatchReminderNotification,
};
