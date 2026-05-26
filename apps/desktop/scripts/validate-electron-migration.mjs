import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(desktopRoot, "..", "..");
const failures = [];
const notes = [];

function rel(filePath) {
  return path.relative(repoRoot, filePath).replaceAll(path.sep, "/");
}

function readText(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function exists(filePath) {
  return fs.existsSync(filePath);
}

function fail(message) {
  failures.push(message);
}

function note(message) {
  notes.push(message);
}

function hasAny(text, patterns) {
  return patterns.some((pattern) => pattern.test(text));
}

function listFiles(dir, ignoredNames = new Set()) {
  if (!exists(dir)) {
    return [];
  }

  const result = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ignoredNames.has(entry.name)) {
      continue;
    }

    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      result.push(...listFiles(fullPath, ignoredNames));
    } else if (entry.isFile()) {
      result.push(fullPath);
    }
  }
  return result;
}

const packagePath = path.join(desktopRoot, "package.json");
let packageJson = {};
if (!exists(packagePath)) {
  fail("apps/desktop/package.json is missing.");
} else {
  packageJson = JSON.parse(readText(packagePath));
  const scripts = packageJson.scripts || {};
  const dependencyNames = [
    ...Object.keys(packageJson.dependencies || {}),
    ...Object.keys(packageJson.devDependencies || {}),
    ...Object.keys(packageJson.optionalDependencies || {}),
  ];

  for (const [name, value] of Object.entries(scripts)) {
    if (/tauri/i.test(name) || /tauri/i.test(String(value))) {
      fail(`Tauri script remains in package.json: ${name} = ${value}`);
    }
  }

  for (const name of dependencyNames) {
    if (/^@tauri-apps\//i.test(name) || /^tauri$/i.test(name)) {
      fail(`Tauri dependency remains in package.json: ${name}`);
    }
  }

  if (!dependencyNames.some((name) => name === "electron" || name.startsWith("@electron/"))) {
    fail("package.json does not declare an Electron dependency.");
  }

  if (!Object.values(scripts).some((value) => /electron/i.test(String(value)))) {
    fail("package.json does not expose an Electron launch/build script.");
  }
}

const packageLockPath = path.join(desktopRoot, "package-lock.json");
if (exists(packageLockPath) && /@tauri-apps|src-tauri|\btauri\b/i.test(readText(packageLockPath))) {
  fail("package-lock.json still contains Tauri packages or references.");
}

const srcTauriPath = path.join(desktopRoot, "src-tauri");
if (exists(srcTauriPath)) {
  fail("apps/desktop/src-tauri still exists.");
}

const frontendFiles = listFiles(path.join(desktopRoot, "src"), new Set(["node_modules", "dist"]));
for (const file of frontendFiles) {
  const text = readText(file);
  if (/\bEventSource\s*(?:\(|\{|\[|$)|new\s+EventSource\b/.test(text)) {
    fail(`Native EventSource usage found in ${rel(file)}.`);
  }
  if (/\blocalStorage\b/.test(text)) {
    fail(`localStorage usage found in ${rel(file)}.`);
  }
}

const ssePath = path.join(desktopRoot, "src", "services", "sse.ts");
if (!exists(ssePath)) {
  fail("SSE client file is missing: apps/desktop/src/services/sse.ts");
} else {
  const sseText = readText(ssePath);
  if (!/\bfetch\s*\(/.test(sseText)) {
    fail("SSE client does not use fetch.");
  }
  if (!/text\/event-stream/.test(sseText)) {
    fail("SSE client does not request text/event-stream.");
  }
  if (!/Authorization/.test(sseText)) {
    fail("SSE client does not send Authorization.");
  }
}

const checklistPath = path.join(repoRoot, "docs", "electron-migration-checklist.md");
if (!exists(checklistPath)) {
  fail("docs/electron-migration-checklist.md is missing.");
} else {
  const checklist = readText(checklistPath);
  for (const expected of [
    "contextIsolation: true",
    "nodeIntegration: false",
    "sandbox: true",
    "webSecurity: true",
    "contextBridge",
    "Content Security Policy",
  ]) {
    if (!checklist.includes(expected)) {
      fail(`Electron security checklist is missing: ${expected}`);
    }
  }
}

const electronFiles = listFiles(desktopRoot, new Set(["node_modules", "dist", "src-tauri"]))
  .filter((file) => {
    const normalized = rel(file).toLowerCase();
    return normalized.startsWith("apps/desktop/electron/")
      || normalized.startsWith("apps/desktop/src-electron/")
      || /(^|\/)(electron-main|preload)\.[cm]?[jt]s$/.test(normalized);
  });

if (electronFiles.length === 0) {
  fail("No Electron main/preload files were found under apps/desktop.");
} else {
  note(`Electron files inspected: ${electronFiles.map(rel).join(", ")}`);
}

const electronMainPath = packageJson.main
  ? path.resolve(desktopRoot, packageJson.main)
  : path.join(desktopRoot, "electron", "main.cjs");
const electronRuntimeFiles = electronFiles.filter((file) => /\.(?:cjs|js)$/i.test(file));
const electronRuntimeText = electronRuntimeFiles.map(readText).join("\n");

if (!exists(electronMainPath)) {
  fail(`Electron main file is missing: ${rel(electronMainPath)}`);
} else {
  for (const expected of [
    "contextIsolation: true",
    "nodeIntegration: false",
    "sandbox: true",
    "webSecurity: true",
    "setWindowOpenHandler",
    "will-navigate",
  ]) {
    if (!electronRuntimeText.includes(expected)) {
      fail(`Electron runtime security setting is missing: ${expected}`);
    }
  }

  if (!/127\.0\.0\.1|localhost/.test(electronRuntimeText)) {
    fail("Electron runtime does not declare a loopback sidecar/API origin.");
  }

  if (!hasAny(electronRuntimeText, [/\bspawn\s*\(/, /\bexecFile\s*\(/, /child_process/])) {
    fail("Electron runtime does not include a sidecar process launch signal.");
  }

  if (!hasAny(electronRuntimeText, [/\brandomUUID\s*\(/, /\brandomBytes\s*\(/, /crypto\.getRandomValues/])) {
    fail("Electron runtime does not generate a per-launch session token with a cryptographic RNG.");
  }

  if (!/AGENT_PET_SESSION_TOKEN/.test(electronRuntimeText)) {
    fail("Electron runtime does not pass the session token to the sidecar through AGENT_PET_SESSION_TOKEN.");
  }

  if (!hasAny(electronRuntimeText, [/\benv\s*:/, /\.stdin\.write\s*\(/])) {
    fail("Electron runtime does not pass sidecar secrets through environment variables or stdin.");
  }

  if (hasAny(electronRuntimeText, [
    /["']--?(?:session-)?token["']/i,
    /["']AGENT_PET_SESSION_TOKEN["']\s*,/,
    /\bargs\s*[:=]\s*\[[^\]]*(?:sessionToken|AGENT_PET_SESSION_TOKEN|Bearer)/is,
    /spawn\s*\([^)]*\[[^\]]*(?:sessionToken|AGENT_PET_SESSION_TOKEN|Bearer)/is,
    /execFile\s*\([^)]*\[[^\]]*(?:sessionToken|AGENT_PET_SESSION_TOKEN|Bearer)/is,
  ])) {
    fail("Electron runtime appears to include a token in sidecar command-line arguments.");
  }

  if (hasAny(electronRuntimeText, [
    /console\.(?:log|info|warn|error)\s*\([^)]*(?:sessionToken|AGENT_PET_SESSION_TOKEN|Bearer)/is,
    /shell\.openExternal\s*\([^)]*(?:sessionToken|AGENT_PET_SESSION_TOKEN|Bearer)/is,
  ])) {
    fail("Electron runtime appears to log or externalize bearer-token material.");
  }

  if (!hasAny(electronRuntimeText, [/\bkill\s*\(/, /\bAbortController\b/, /\bdispose\b/])) {
    fail("Electron runtime does not include sidecar shutdown/cleanup handling.");
  }

  if (!hasAny(electronRuntimeText, [/setPermissionRequestHandler/, /session\.defaultSession\.setPermissionRequestHandler/])) {
    fail("Electron runtime does not deny or broker renderer permission requests.");
  }
}

const preloadCandidates = electronFiles.filter((file) => /preload\.[cm]?[jt]s$/i.test(file));
if (preloadCandidates.length === 0) {
  fail("Electron preload file was not found.");
} else if (!preloadCandidates.some((file) => readText(file).includes("contextBridge"))) {
  fail("Electron preload does not use contextBridge.");
} else {
  for (const file of preloadCandidates) {
    const preloadText = readText(file);
    if (/\brequire\s*\(\s*["'](?:fs|child_process|node:fs|node:child_process)["']\s*\)/.test(preloadText)) {
      fail(`Electron preload imports filesystem or process-spawn modules: ${rel(file)}.`);
    }
    if (/\b(sessionToken|AGENT_PET_SESSION_TOKEN|Authorization|Bearer)\b/.test(preloadText)) {
      fail(`Electron preload exposes or references bearer-token material: ${rel(file)}.`);
    }
    if (!/exposeInMainWorld/.test(preloadText)) {
      fail(`Electron preload does not expose an explicit contextBridge API: ${rel(file)}.`);
    }
  }
}

if (notes.length > 0) {
  for (const item of notes) {
    console.log(`note: ${item}`);
  }
}

if (failures.length > 0) {
  console.error("Electron migration validation failed:");
  for (const item of failures) {
    console.error(`- ${item}`);
  }
  process.exitCode = 1;
} else {
  console.log("Electron migration validation passed.");
}
