import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const args = new Set(process.argv.slice(2));
const targetArg = process.argv.find((arg) => arg.startsWith("--target="));
const target = targetArg ? targetArg.slice("--target=".length) : args.has("--target") ? process.argv[process.argv.indexOf("--target") + 1] : "public";
const validTargets = new Set(["public", "dist", "all"]);
const checks = [];

function record(name, ok, detail) {
  checks.push({ name, ok, detail });
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readPngSize(filePath) {
  const header = Buffer.alloc(24);
  const fd = fs.openSync(filePath, "r");
  try {
    fs.readSync(fd, header, 0, header.length, 0);
  } finally {
    fs.closeSync(fd);
  }
  const signatureOk =
    header[0] === 0x89 &&
    header[1] === 0x50 &&
    header[2] === 0x4e &&
    header[3] === 0x47 &&
    header[4] === 0x0d &&
    header[5] === 0x0a &&
    header[6] === 0x1a &&
    header[7] === 0x0a;
  if (!signatureOk) {
    return null;
  }
  return {
    width: header.readUInt32BE(16),
    height: header.readUInt32BE(20),
  };
}

function normalizeAssetPath(assetPath) {
  if (typeof assetPath !== "string" || !assetPath.trim()) {
    return null;
  }
  const cleanPath = assetPath.trim().replace(/^\/+/, "").replace(/\\/g, "/");
  if (cleanPath.startsWith("../") || cleanPath.includes("/../") || path.isAbsolute(cleanPath)) {
    return null;
  }
  return cleanPath;
}

const qversionAnimationKeys = [
  "idle",
  "running-right",
  "running-left",
  "waving",
  "thinking",
  "working",
  "done",
  "failed",
  "sleeping",
];

function validateTarget(scope) {
  const scopeRoot = path.join(root, scope);
  validateHalfbodyTarget(scope, scopeRoot);
  validateQversionTarget(scope, scopeRoot);
}

function validateHalfbodyTarget(scope, scopeRoot) {
  const statePath = path.join(scopeRoot, "sprite-pet", "state.json");
  record(`${scope} sprite-pet state.json exists`, fs.existsSync(statePath), path.relative(root, statePath));
  if (!fs.existsSync(statePath)) {
    return;
  }

  const manifest = readJson(statePath);
  const halfbody = manifest?.characters?.halfbody;
  record(`${scope} halfbody manifest exists`, isObject(halfbody), "characters.halfbody");
  if (!isObject(halfbody)) {
    return;
  }

  record(`${scope} halfbody is home-only`, halfbody.window === "home", String(halfbody.window));
  record(`${scope} halfbody is not draggable`, halfbody.draggable === false, String(halfbody.draggable));
  record(`${scope} halfbody uses layered portrait`, halfbody.type === "layered-portrait", String(halfbody.type));

  const blinkFrames = isObject(halfbody.blink?.frames) ? halfbody.blink.frames : {};
  const visemes = isObject(halfbody.visemes) ? halfbody.visemes : {};
  const assetEntries = [
    ["base", halfbody.base],
    ["blink.open", blinkFrames.open],
    ["blink.half", blinkFrames.half],
    ["blink.closed", blinkFrames.closed],
    ["viseme.closed", visemes.closed],
    ["viseme.AI", visemes.AI],
    ["viseme.E", visemes.E],
    ["viseme.O", visemes.O],
    ["viseme.MBP", visemes.MBP],
    ["viseme.FV", visemes.FV],
    ["viseme.smile", visemes.smile],
  ];

  const baseRelativePath = normalizeAssetPath(halfbody.base);
  const basePath = baseRelativePath ? path.join(scopeRoot, baseRelativePath) : null;
  const baseSize = basePath && fs.existsSync(basePath) ? readPngSize(basePath) : null;
  record(`${scope} halfbody base is readable PNG`, Boolean(baseSize), baseRelativePath ?? "invalid base path");

  for (const [name, configuredPath] of assetEntries) {
    const relativePath = normalizeAssetPath(configuredPath);
    const filePath = relativePath ? path.join(scopeRoot, relativePath) : null;
    const exists = Boolean(filePath && fs.existsSync(filePath));
    record(`${scope} ${name} asset exists`, exists, relativePath ?? "invalid path");
    if (!exists) {
      continue;
    }
    const size = readPngSize(filePath);
    record(`${scope} ${name} asset is PNG`, Boolean(size), relativePath);
    if (baseSize && size) {
      record(
        `${scope} ${name} matches base dimensions`,
        size.width === baseSize.width && size.height === baseSize.height,
        `${size.width}x${size.height}`,
      );
    }
  }
}

function validateQversionTarget(scope, scopeRoot) {
  const petRoot = path.join(scopeRoot, "pets", "agent-pet-neko");
  const manifestPath = path.join(petRoot, "pet.json");
  record(`${scope} qversion pet.json exists`, fs.existsSync(manifestPath), path.relative(root, manifestPath));
  if (!fs.existsSync(manifestPath)) {
    return;
  }

  const manifest = readJson(manifestPath);
  record(`${scope} qversion manifest id is agent-pet-neko`, manifest?.id === "agent-pet-neko", String(manifest?.id));
  const cell = isObject(manifest?.cell) ? manifest.cell : {};
  const layout = isObject(manifest?.layout) ? manifest.layout : {};
  const cellWidth = Number(cell.width);
  const cellHeight = Number(cell.height);
  const layoutColumns = Number(layout.columns);
  const layoutRows = Number(layout.rows);
  const layoutWidth = Number(layout.width);
  const layoutHeight = Number(layout.height);
  record(`${scope} qversion cell dimensions are positive`, cellWidth > 0 && cellHeight > 0, `${cellWidth}x${cellHeight}`);
  record(`${scope} qversion layout dimensions are positive`, layoutColumns > 0 && layoutRows > 0 && layoutWidth > 0 && layoutHeight > 0, `${layoutColumns}x${layoutRows} ${layoutWidth}x${layoutHeight}`);

  const cleanConfigured = typeof manifest?.spritesheetCleanPath === "string" && manifest.spritesheetCleanPath.trim();
  const cleanRelativePath = normalizeAssetPath(cleanConfigured ? manifest.spritesheetCleanPath : "spritesheet-clean.png");
  const webpRelativePath = normalizeAssetPath(manifest?.spritesheetPath);
  const pngRelativePath = normalizeAssetPath(manifest?.fallbackPngPath);
  const cleanPath = cleanRelativePath ? path.join(petRoot, cleanRelativePath) : null;
  const webpPath = webpRelativePath ? path.join(petRoot, webpRelativePath) : null;
  const pngPath = pngRelativePath ? path.join(petRoot, pngRelativePath) : null;
  record(`${scope} qversion clean spritesheet exists`, Boolean(cleanPath && fs.existsSync(cleanPath)), cleanRelativePath ?? "invalid path");
  if (cleanConfigured) {
    record(`${scope} qversion configured clean spritesheet exists`, Boolean(cleanPath && fs.existsSync(cleanPath)), cleanRelativePath ?? "invalid path");
  }
  record(`${scope} qversion webp spritesheet exists`, Boolean(webpPath && fs.existsSync(webpPath)), webpRelativePath ?? "invalid path");
  record(`${scope} qversion png fallback exists`, Boolean(pngPath && fs.existsSync(pngPath)), pngRelativePath ?? "invalid path");

  const cleanSize = cleanPath && fs.existsSync(cleanPath) ? readPngSize(cleanPath) : null;
  record(`${scope} qversion clean spritesheet is readable PNG`, Boolean(cleanSize), cleanRelativePath ?? "invalid path");
  if (cleanSize) {
    record(
      `${scope} qversion clean spritesheet matches layout dimensions`,
      cleanSize.width === layoutWidth && cleanSize.height === layoutHeight,
      `${cleanSize.width}x${cleanSize.height}`,
    );
  }

  const pngSize = pngPath && fs.existsSync(pngPath) ? readPngSize(pngPath) : null;
  record(`${scope} qversion png fallback is readable PNG`, Boolean(pngSize), pngRelativePath ?? "invalid path");
  if (pngSize) {
    record(
      `${scope} qversion png fallback matches layout dimensions`,
      pngSize.width === layoutWidth && pngSize.height === layoutHeight,
      `${pngSize.width}x${pngSize.height}`,
    );
  }

  const animations = isObject(manifest?.animations) ? manifest.animations : {};
  for (const key of qversionAnimationKeys) {
    const animation = animations[key];
    record(`${scope} qversion animation ${key} exists`, isObject(animation), key);
    if (!isObject(animation)) {
      continue;
    }
    const row = Number(animation.row);
    const frames = Number(animation.frames);
    const columns = Array.isArray(animation.columns) ? animation.columns : [];
    const durations = Array.isArray(animation.durationsMs) ? animation.durationsMs : [];
    record(`${scope} qversion animation ${key} row is in range`, Number.isInteger(row) && row >= 0 && row < layoutRows, String(row));
    record(`${scope} qversion animation ${key} frame count is positive`, Number.isInteger(frames) && frames > 0, String(frames));
    record(
      `${scope} qversion animation ${key} columns are in range`,
      columns.length > 0 && columns.every((column) => Number.isInteger(column) && column >= 0 && column < layoutColumns),
      JSON.stringify(columns),
    );
    record(
      `${scope} qversion animation ${key} durations are positive`,
      durations.length > 0 && durations.every((duration) => typeof duration === "number" && Number.isFinite(duration) && duration > 0),
      JSON.stringify(durations),
    );
  }
}

if (!validTargets.has(target)) {
  console.error(`Unknown target "${target}". Use public, dist, or all.`);
  process.exit(1);
}

for (const scope of target === "all" ? ["public", "dist"] : [target]) {
  validateTarget(scope);
}

const failures = checks.filter((check) => !check.ok);
for (const check of checks) {
  const prefix = check.ok ? "ok" : "fail";
  console.log(`[${prefix}] ${check.name}: ${check.detail}`);
}

if (failures.length > 0) {
  console.error(`\nSprite-pet asset validation failed ${failures.length} check(s).`);
  process.exitCode = 1;
}
