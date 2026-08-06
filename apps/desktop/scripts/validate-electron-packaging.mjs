import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repositoryRoot = path.resolve(root, "..", "..");
const require = createRequire(import.meta.url);

const checks = [];

function record(name, ok, detail) {
  checks.push({ name, ok, detail });
}

function exists(relativePath) {
  return fs.existsSync(path.join(root, relativePath));
}

function repositoryFileExists(relativePath) {
  return fs.existsSync(path.join(repositoryRoot, relativePath));
}

function readRepositoryFile(relativePath) {
  return fs.readFileSync(path.join(repositoryRoot, relativePath), "utf8");
}

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(root, relativePath), "utf8"));
}

const packageJson = readJson("package.json");

record("package.json main points to Electron main", packageJson.main === "electron/main.cjs", packageJson.main);
record("Electron main exists", exists("electron/main.cjs"), "electron/main.cjs");
record("Electron preload exists", exists("electron/preload.cjs"), "electron/preload.cjs");
record("Desktop pet hitbox config exists", exists("pet-hitbox.json"), "pet-hitbox.json");
record("Vite build output exists", exists("dist/index.html"), "dist/index.html");
record("Windows dir package script exists", Boolean(packageJson.scripts?.["package:win:dir"]), "package:win:dir");
record("Windows zip package script exists", Boolean(packageJson.scripts?.["package:win:zip"]), "package:win:zip");
record(
  "Windows package scripts build the frozen sidecar first",
  typeof packageJson.scripts?.["build:sidecar"] === "string" &&
    packageJson.scripts["build:sidecar"].includes("build-sidecar.ps1") &&
    packageJson.scripts?.["package:win:dir"]?.startsWith("npm run build:sidecar &&") &&
    packageJson.scripts?.["package:win:zip"]?.startsWith("npm run build:sidecar &&"),
  JSON.stringify({
    buildSidecar: packageJson.scripts?.["build:sidecar"],
    dir: packageJson.scripts?.["package:win:dir"],
    zip: packageJson.scripts?.["package:win:zip"],
  }),
);
record("electron-builder config exists", Boolean(packageJson.build?.win?.target), "build.win.target");
record(
  "electron-builder reuses the installed Electron runtime",
  packageJson.build?.electronDist === "node_modules/electron/dist",
  packageJson.build?.electronDist ?? null,
);
record(
  "electron-builder targets include dir and zip",
  Array.isArray(packageJson.build?.win?.target) &&
    packageJson.build.win.target.includes("dir") &&
    packageJson.build.win.target.includes("zip"),
  JSON.stringify(packageJson.build?.win?.target ?? null),
);
record(
  "electron-builder package files include pet hitbox config",
  Array.isArray(packageJson.build?.files) && packageJson.build.files.includes("pet-hitbox.json"),
  JSON.stringify(packageJson.build?.files ?? null),
);

const electronRuntimeFiles = [
  "electron/main.cjs",
  "electron/windows.js",
  "electron/tray.js",
  "electron/sidecar.js",
  "electron/proxy.js",
  "electron/ipc.js",
];
const runtimeText = electronRuntimeFiles
  .filter(exists)
  .map((relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8"))
  .join("\n");
record(
  "Electron runtime reads shared pet hitbox config",
  /require\(["']\.\.\/pet-hitbox\.json["']\)/.test(runtimeText),
  "require(\"../pet-hitbox.json\")",
);
record(
  "Electron runtime supports AGENT_PET_BACKEND_DIR override",
  /process\.env\.AGENT_PET_BACKEND_DIR/.test(runtimeText),
  "AGENT_PET_BACKEND_DIR",
);
record(
  "Packaged Electron runtime requires the frozen sidecar executable",
  /app\.isPackaged/.test(runtimeText) &&
    /process\.resourcesPath/.test(runtimeText) &&
    /path\.join\(packagedResourcesPath,\s*["']sidecar["'],\s*SIDECAR_EXECUTABLE_NAME\)/.test(runtimeText) &&
    /SIDECAR_EXECUTABLE_NOT_FOUND/.test(runtimeText),
  "process.resourcesPath/sidecar/agent-pet-sidecar.exe",
);
record(
  "Development Electron runtime falls back to the Python sidecar entrypoint",
  /["']-m["'],\s*["']app\.sidecar_entry["']/.test(runtimeText) &&
    !/["']-m["'],\s*["']uvicorn["']/.test(runtimeText),
  "python -m app.sidecar_entry",
);
record(
  "Electron parses the atomic sidecar runtime handshake",
  /AGENT_PET_SIDECAR_RUNTIME/.test(runtimeText) &&
    /updateRuntimePort\(runtimePort\)/.test(runtimeText),
  "AGENT_PET_SIDECAR_RUNTIME -> shared runtime port",
);
record(
  "Electron persists sidecar output and exposes its log path",
  /app\.getPath\(["']logs["']\)/.test(runtimeText) &&
    /fs\.appendFileSync\(sidecarLogPath/.test(runtimeText) &&
    /logPath:\s*sidecarLogPath/.test(runtimeText),
  "app logs/sidecar/agent-pet-sidecar.log",
);
record(
  "Electron runtime keeps sidecar token in environment",
  /AGENT_PET_SESSION_TOKEN:\s*sessionToken/.test(runtimeText) &&
    !/["']--?(?:session-)?token["']/i.test(runtimeText),
  "AGENT_PET_SESSION_TOKEN env",
);
record(
  "Electron runtime gives managed sidecar a persistent data directory",
  /app\.getPath\(["']userData["']\)/.test(runtimeText) &&
    /AGENT_PET_DATA_DIR/.test(runtimeText) &&
    /AGENT_PET_SQLITE_PATH/.test(runtimeText),
  "app.getPath(\"userData\") -> AGENT_PET_DATA_DIR unless explicit env overrides exist",
);
const extraResources = packageJson.build?.extraResources ?? [];
const sidecarResource = Array.isArray(extraResources)
  ? extraResources.find((entry) => entry?.to === "sidecar")
  : null;
record(
  "electron-builder packages the frozen sidecar directory",
  Boolean(sidecarResource) && sidecarResource.from === "../backend/dist/agent-pet-sidecar",
  JSON.stringify(sidecarResource ?? null),
);
record(
  "electron-builder no longer packages backend source as the runtime",
  !extraResources.some((entry) => entry?.to === "backend" || entry?.from === "../backend"),
  JSON.stringify(extraResources),
);

const sidecarSpecPath = "apps/backend/agent-pet-sidecar.spec";
const buildSidecarScriptPath = "scripts/build-sidecar.ps1";
const backendProjectPath = "apps/backend/pyproject.toml";
record(
  "PyInstaller sidecar spec exists and bundles migrations",
  repositoryFileExists(sidecarSpecPath) &&
    /migrations/.test(readRepositoryFile(sidecarSpecPath)) &&
    /name=["']agent-pet-sidecar["']/.test(readRepositoryFile(sidecarSpecPath)),
  sidecarSpecPath,
);
record(
  "PowerShell sidecar build script verifies the executable",
  repositoryFileExists(buildSidecarScriptPath) &&
    /PyInstaller/.test(readRepositoryFile(buildSidecarScriptPath)) &&
    /agent-pet-sidecar\.exe/.test(readRepositoryFile(buildSidecarScriptPath)),
  buildSidecarScriptPath,
);
record(
  "Backend packaging extra declares PyInstaller",
  repositoryFileExists(backendProjectPath) &&
    /packaging\s*=\s*\[[\s\S]*?pyinstaller/i.test(readRepositoryFile(backendProjectPath)),
  backendProjectPath,
);

let electronBuilderResolved = null;
try {
  electronBuilderResolved = require.resolve("electron-builder");
} catch {
  electronBuilderResolved = null;
}

record(
  "electron-builder is installed",
  Boolean(electronBuilderResolved),
  electronBuilderResolved ?? "Run npm install in apps/desktop before package:win:*",
);

if (exists("package-lock.json")) {
  const packageLock = readJson("package-lock.json");
  const rootPackage = packageLock.packages?.[""] ?? {};
  record(
    "package-lock includes electron-builder",
    Boolean(rootPackage.devDependencies?.["electron-builder"]),
    "package-lock.json must be refreshed after npm install",
  );
}

const failures = checks.filter((check) => !check.ok);

for (const check of checks) {
  const prefix = check.ok ? "ok" : "fail";
  console.log(`[${prefix}] ${check.name}: ${check.detail}`);
}

if (failures.length > 0) {
  console.error(`\nPackaging readiness failed ${failures.length} check(s).`);
  process.exitCode = 1;
}
