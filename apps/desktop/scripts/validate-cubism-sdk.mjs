import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const sdkRelativePath = "live2d/CubismSdkForWeb-5-r.5";
const allowedTargets = new Set(["public", "dist", "all"]);

const options = parseArgs(process.argv.slice(2));
const checks = [];

function parseArgs(args) {
  const parsed = {
    target: "public",
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];

    if (arg === "--target") {
      parsed.target = args[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg.startsWith("--target=")) {
      parsed.target = arg.slice("--target=".length);
      continue;
    }

    if (arg === "--help" || arg === "-h") {
      printUsage();
      process.exit(0);
    }

    parsed.target = arg;
  }

  if (!allowedTargets.has(parsed.target)) {
    console.error(`错误：--target 只支持 public、dist 或 all，当前值为 ${JSON.stringify(parsed.target)}。`);
    printUsage();
    process.exit(1);
  }

  return parsed;
}

function printUsage() {
  console.log(`用法：node scripts/validate-cubism-sdk.mjs [--target public|dist|all]

示例：
  npm run live2d:sdk:check
  npm run live2d:sdk:check:dist
  node scripts/validate-cubism-sdk.mjs --target all`);
}

function targetsToCheck(target) {
  return target === "all" ? ["public", "dist"] : [target];
}

function record(scope, name, ok, detail) {
  checks.push({ scope, name, ok, detail });
}

function toDisplayPath(absolutePath) {
  return path.relative(desktopRoot, absolutePath).replaceAll(path.sep, "/");
}

function fileExistsAndNotEmpty(absolutePath) {
  if (!fs.existsSync(absolutePath)) {
    return false;
  }

  const stat = fs.statSync(absolutePath);
  return stat.isFile() && stat.size > 0;
}

function directoryExists(absolutePath) {
  return fs.existsSync(absolutePath) && fs.statSync(absolutePath).isDirectory();
}

function readTextIfExists(absolutePath) {
  if (!fileExistsAndNotEmpty(absolutePath)) {
    return "";
  }

  return fs.readFileSync(absolutePath, "utf8");
}

function assertDirectory(scope, root, relativePath) {
  const absolutePath = path.join(root, relativePath);
  record(scope, `${relativePath} 目录存在`, directoryExists(absolutePath), toDisplayPath(absolutePath));
}

function assertFile(scope, root, relativePath) {
  const absolutePath = path.join(root, relativePath);
  record(scope, `${relativePath} 文件存在且非空`, fileExistsAndNotEmpty(absolutePath), toDisplayPath(absolutePath));
}

function assertContains(scope, root, relativePath, pattern, description) {
  const absolutePath = path.join(root, relativePath);
  const content = readTextIfExists(absolutePath);
  record(scope, description, pattern.test(content), toDisplayPath(absolutePath));
}

function validateSdkTarget(target) {
  const sdkRoot = path.join(desktopRoot, target, sdkRelativePath);

  record(target, "Cubism SDK 根目录存在", directoryExists(sdkRoot), toDisplayPath(sdkRoot));
  if (!directoryExists(sdkRoot)) {
    return;
  }

  assertFile(target, sdkRoot, "LICENSE.md");
  assertFile(target, sdkRoot, "NOTICE.md");
  assertFile(target, sdkRoot, "cubism-info.yml");
  assertDirectory(target, sdkRoot, "Core");
  assertDirectory(target, sdkRoot, "Framework/src");
  assertDirectory(target, sdkRoot, "Framework/src/rendering");
  assertDirectory(target, sdkRoot, "Samples/TypeScript/Demo/src");

  assertFile(target, sdkRoot, "Core/live2dcubismcore.js");
  assertFile(target, sdkRoot, "Core/live2dcubismcore.min.js");
  assertFile(target, sdkRoot, "Core/live2dcubismcore.d.ts");
  assertContains(
    target,
    sdkRoot,
    "Core/live2dcubismcore.d.ts",
    /declare namespace Live2DCubismCore/,
    "Core 类型声明包含 Live2DCubismCore namespace",
  );

  assertFile(target, sdkRoot, "Framework/src/live2dcubismframework.ts");
  assertFile(target, sdkRoot, "Framework/src/cubismmodelsettingjson.ts");
  assertFile(target, sdkRoot, "Framework/src/model/cubismusermodel.ts");
  assertFile(target, sdkRoot, "Framework/src/model/cubismmoc.ts");
  assertFile(target, sdkRoot, "Framework/src/rendering/cubismrenderer_webgl.ts");
  assertFile(target, sdkRoot, "Framework/src/rendering/cubismshader_webgl.ts");
  assertContains(
    target,
    sdkRoot,
    "Framework/src/rendering/cubismrenderer_webgl.ts",
    /class\s+CubismRenderer_WebGL/,
    "Framework WebGL 渲染器类存在",
  );

  assertFile(target, sdkRoot, "Samples/TypeScript/Demo/src/lappdelegate.ts");
  assertFile(target, sdkRoot, "Samples/TypeScript/Demo/src/lappmodel.ts");
  assertFile(target, sdkRoot, "Samples/TypeScript/Demo/src/lappview.ts");
  assertFile(target, sdkRoot, "Samples/TypeScript/Demo/src/lapptexturemanager.ts");
  assertContains(
    target,
    sdkRoot,
    "Samples/TypeScript/Demo/src/lappmodel.ts",
    /createRenderer\(/,
    "官方示例包含 createRenderer 调用链",
  );

  const sampleTsconfigPath = path.join(sdkRoot, "Samples/TypeScript/Demo/tsconfig.json");
  if (fileExistsAndNotEmpty(sampleTsconfigPath)) {
    const sampleTsconfig = JSON.parse(fs.readFileSync(sampleTsconfigPath, "utf8"));
    const frameworkAlias = sampleTsconfig?.compilerOptions?.paths?.["@framework/*"];
    record(
      target,
      "官方示例声明 @framework 路径别名",
      Array.isArray(frameworkAlias) && frameworkAlias.includes("../../../Framework/src/*"),
      toDisplayPath(sampleTsconfigPath),
    );
  } else {
    record(target, "官方示例声明 @framework 路径别名", false, toDisplayPath(sampleTsconfigPath));
  }
}

for (const target of targetsToCheck(options.target)) {
  validateSdkTarget(target);
}

for (const check of checks) {
  const prefix = check.ok ? "通过" : "错误";
  const output = `[${prefix}] ${check.scope}: ${check.name}: ${check.detail}`;
  if (check.ok) {
    console.log(output);
  } else {
    console.error(output);
  }
}

const failures = checks.filter((check) => !check.ok);

if (failures.length > 0) {
  console.error(`\nCubism SDK 校验失败：${failures.length} 项错误。`);
  process.exitCode = 1;
} else {
  console.log("\nCubism SDK 校验通过。");
}
