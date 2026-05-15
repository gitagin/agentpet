import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(scriptDir, "..");

const checks = [];

function addCheck(name, details) {
  checks.push({ name, ...details });
}

function fileExists(filePath) {
  try {
    return fs.existsSync(filePath);
  } catch {
    return false;
  }
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function runCommand(name, command, args, options = {}) {
  const started = Date.now();
  const result = spawnSync(command, args, {
    cwd: desktopRoot,
    encoding: "utf8",
    timeout: options.timeout ?? 30_000,
    shell: options.shell ?? false,
    env: process.env,
  });

  addCheck(name, {
    command: [command, ...args].join(" "),
    status: result.status,
    signal: result.signal,
    error: result.error ? {
      code: result.error.code,
      errno: result.error.errno,
      syscall: result.error.syscall,
      path: result.error.path,
      message: result.error.message,
    } : null,
    stdout: trimOutput(result.stdout),
    stderr: trimOutput(result.stderr),
    durationMs: Date.now() - started,
  });

  return result;
}

function trimOutput(value) {
  const text = String(value || "").trim();
  return text.length > 4000 ? `${text.slice(0, 4000)}\n...[truncated]` : text;
}

function tryAccess(filePath) {
  const modes = [
    ["F_OK", fs.constants.F_OK],
    ["R_OK", fs.constants.R_OK],
    ["X_OK", fs.constants.X_OK],
  ];

  return modes.map(([name, mode]) => {
    try {
      fs.accessSync(filePath, mode);
      return { mode: name, ok: true };
    } catch (error) {
      return { mode: name, ok: false, code: error.code, message: error.message };
    }
  });
}

const packagePath = path.join(desktopRoot, "package.json");
const packageLockPath = path.join(desktopRoot, "package-lock.json");
const esbuildPackagePath = path.join(desktopRoot, "node_modules", "esbuild", "package.json");
const vitePackagePath = path.join(desktopRoot, "node_modules", "vite", "package.json");

const packageJson = fileExists(packagePath) ? readJson(packagePath) : null;
const esbuildPackage = fileExists(esbuildPackagePath) ? readJson(esbuildPackagePath) : null;
const vitePackage = fileExists(vitePackagePath) ? readJson(vitePackagePath) : null;

const platformPackageName = process.platform === "win32"
  ? `@esbuild/win32-${process.arch === "ia32" ? "ia32" : process.arch === "arm64" ? "arm64" : "x64"}`
  : null;
const platformBinary = platformPackageName
  ? path.join(desktopRoot, "node_modules", platformPackageName, "esbuild.exe")
  : null;
const esbuildJsBin = path.join(desktopRoot, "node_modules", "esbuild", "bin", "esbuild");
const viteBin = path.join(desktopRoot, "node_modules", "vite", "bin", "vite.js");

const report = {
  generatedAt: new Date().toISOString(),
  cwd: desktopRoot,
  os: {
    platform: process.platform,
    arch: process.arch,
    release: os.release(),
    type: os.type(),
  },
  node: process.version,
  npmUserAgent: process.env.npm_config_user_agent || null,
  packageScripts: packageJson?.scripts || null,
  versions: {
    vite: vitePackage?.version || null,
    esbuild: esbuildPackage?.version || null,
    packageLockPresent: fileExists(packageLockPath),
  },
  paths: {
    esbuildJsBin,
    esbuildJsBinExists: fileExists(esbuildJsBin),
    platformPackageName,
    platformBinary,
    platformBinaryExists: platformBinary ? fileExists(platformBinary) : null,
    viteBin,
    viteBinExists: fileExists(viteBin),
  },
  access: {
    esbuildJsBin: fileExists(esbuildJsBin) ? tryAccess(esbuildJsBin) : [],
    platformBinary: platformBinary && fileExists(platformBinary) ? tryAccess(platformBinary) : [],
    viteBin: fileExists(viteBin) ? tryAccess(viteBin) : [],
  },
  checks,
};

runCommand("node version", process.execPath, ["--version"]);
runCommand("npm version", process.platform === "win32" ? "npm.cmd" : "npm", ["--version"]);

if (fileExists(esbuildJsBin)) {
  runCommand("esbuild JS launcher via node", process.execPath, [esbuildJsBin, "--version"]);
}

if (platformBinary && fileExists(platformBinary)) {
  runCommand("esbuild platform binary direct", platformBinary, ["--version"]);
}

runCommand("npm exec esbuild", process.platform === "win32" ? "npm.cmd" : "npm", ["exec", "--", "esbuild", "--version"]);

if (fileExists(viteBin)) {
  runCommand("vite CLI via node", process.execPath, [viteBin, "--version"]);
  runCommand("vite build", process.execPath, [viteBin, "build"], { timeout: 60_000 });
}

const failedSpawn = checks.find((check) => check.error?.code === "EPERM");
report.summary = failedSpawn
  ? `EPERM reproduced while running: ${failedSpawn.command}`
  : "No EPERM was reproduced by the diagnostic commands.";

console.log(JSON.stringify(report, null, 2));

if (failedSpawn) {
  process.exitCode = 1;
}
