import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const require = createRequire(import.meta.url);

const checks = [];

function record(name, ok, detail) {
  checks.push({ name, ok, detail });
}

function exists(relativePath) {
  return fs.existsSync(path.join(root, relativePath));
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
record("electron-builder config exists", Boolean(packageJson.build?.win?.target), "build.win.target");
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
  "Electron runtime searches packaged resources backend and sidecar",
  /process\.resourcesPath/.test(runtimeText) &&
    /path\.join\(packagedResourcesPath,\s*["']backend["']\)/.test(runtimeText) &&
    /path\.join\(packagedResourcesPath,\s*["']sidecar["']\)/.test(runtimeText),
  "process.resourcesPath/backend and process.resourcesPath/sidecar",
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
const backendResource = Array.isArray(extraResources)
  ? extraResources.find((entry) => entry?.to === "backend")
  : null;
const backendFilters = backendResource?.filter ?? [];
record(
  "electron-builder extraResources includes backend sidecar source",
  Boolean(backendResource) &&
    backendResource.from === "../backend" &&
    backendFilters.includes("app/**/*") &&
    backendFilters.includes("migrations/**/*") &&
    backendFilters.includes("pyproject.toml"),
  JSON.stringify(backendResource ?? null),
);
record(
  "electron-builder excludes Python environments and generated state",
  backendFilters.some((filter) => /venv/.test(filter)) &&
    backendFilters.includes("!**/__pycache__/**") &&
    backendFilters.includes("!**/.pytest_cache/**") &&
    backendFilters.includes("!**/*.pyc") &&
    backendFilters.includes("!**/*.sqlite3") &&
    backendFilters.includes("!**/*.db"),
  JSON.stringify(backendFilters),
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
