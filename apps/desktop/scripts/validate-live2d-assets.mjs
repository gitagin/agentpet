import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const referenceModelRelativePath = "live2d/UG/ugofficial.model3.json";
const allowedTargets = new Set(["public", "dist", "all"]);

const options = parseArgs(process.argv.slice(2));
const targetRoots = resolveTargetRoots(options.target);
const checks = [];
const manifests = [];

function parseArgs(args) {
  const parsed = {
    target: "all",
    model: referenceModelRelativePath,
    summary: false,
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

    if (arg === "--model") {
      parsed.model = normalizeModelPath(args[index + 1] ?? "");
      index += 1;
      continue;
    }

    if (arg.startsWith("--model=")) {
      parsed.model = normalizeModelPath(arg.slice("--model=".length));
      continue;
    }

    if (arg === "--summary" || arg === "-s") {
      parsed.summary = true;
      continue;
    }

    if (arg === "--help" || arg === "-h") {
      printUsage();
      process.exit(0);
    }

    parsed.model = normalizeModelPath(arg);
  }

  if (!allowedTargets.has(parsed.target)) {
    console.error(`错误：--target 只支持 public、dist 或 all，当前值为 ${JSON.stringify(parsed.target)}。`);
    printUsage();
    process.exit(1);
  }

  return parsed;
}

function normalizeModelPath(modelPath) {
  if (!modelPath) {
    return referenceModelRelativePath;
  }

  const normalized = modelPath.replaceAll("\\", "/").replace(/^\.?\//, "");
  if (normalized.startsWith("public/") || normalized.startsWith("dist/")) {
    return normalized.split("/").slice(1).join("/");
  }

  return normalized;
}

function resolveTargetRoots(target) {
  if (target === "all") {
    return ["public", "dist"];
  }

  return [target];
}

function printUsage() {
  console.log(`用法：node scripts/validate-live2d-assets.mjs [--target public|dist|all] [--model live2d/UG/ugofficial.model3.json] [--summary]

示例：
  npm run live2d:check
  npm run live2d:check:public
  npm run live2d:check:dist
  npm run live2d:summary`);
}

function record(scope, name, ok, detail) {
  checks.push({ scope, name, ok, detail });
}

function toDisplayPath(absolutePath) {
  return path.relative(desktopRoot, absolutePath).replaceAll(path.sep, "/");
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function listModelFiles(directory) {
  if (!fs.existsSync(directory)) {
    return [];
  }

  const entries = fs.readdirSync(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...listModelFiles(entryPath));
      continue;
    }

    if (entry.isFile() && entry.name.endsWith(".model3.json")) {
      files.push(entryPath);
    }
  }

  return files;
}

function readJson(absolutePath) {
  return JSON.parse(fs.readFileSync(absolutePath, "utf8"));
}

function fileExistsAndNotEmpty(absolutePath) {
  if (!fs.existsSync(absolutePath)) {
    return false;
  }

  const stat = fs.statSync(absolutePath);
  return stat.isFile() && stat.size > 0;
}

function assertFileReference(scope, modelDirectory, groupName, relativeFile, expectedExtension) {
  if (!isNonEmptyString(relativeFile)) {
    record(scope, `${groupName} 引用格式正确`, false, `期望非空 File 字符串，实际为 ${JSON.stringify(relativeFile)}`);
    return null;
  }

  if (expectedExtension && !relativeFile.endsWith(expectedExtension)) {
    record(scope, `${groupName} 文件扩展名正确`, false, `期望 ${expectedExtension}，实际为 ${relativeFile}`);
  } else if (expectedExtension) {
    record(scope, `${groupName} 文件扩展名正确`, true, relativeFile);
  }

  const absoluteFile = path.resolve(modelDirectory, relativeFile);
  record(scope, `${groupName} 引用文件存在且非空`, fileExistsAndNotEmpty(absoluteFile), toDisplayPath(absoluteFile));
  return absoluteFile;
}

function validateJsonFile(scope, filePath, label, validator) {
  if (!filePath || !fs.existsSync(filePath)) {
    return null;
  }

  try {
    const json = readJson(filePath);
    record(scope, `${label} 可解析`, true, toDisplayPath(filePath));
    validator(json, label);
    return json;
  } catch (error) {
    record(scope, `${label} 可解析`, false, `${toDisplayPath(filePath)}: ${error.message}`);
    return null;
  }
}

function validateModelShape(scope, modelJson) {
  record(scope, "model3.json Version 结构正确", isFiniteNumber(modelJson.Version), `Version=${JSON.stringify(modelJson.Version)}`);
  record(scope, "model3.json FileReferences 结构正确", isPlainObject(modelJson.FileReferences), "期望 FileReferences 为对象");

  if (modelJson.Groups !== undefined) {
    const groupsValid =
      Array.isArray(modelJson.Groups) &&
      modelJson.Groups.every(
        (group) =>
          isPlainObject(group) &&
          isNonEmptyString(group.Target) &&
          isNonEmptyString(group.Name) &&
          Array.isArray(group.Ids) &&
          group.Ids.every(isNonEmptyString),
      );
    record(scope, "Groups 结构正确", groupsValid, `Groups=${Array.isArray(modelJson.Groups) ? modelJson.Groups.length : "非数组"}`);
  }

  if (modelJson.HitAreas !== undefined) {
    const hitAreasValid =
      Array.isArray(modelJson.HitAreas) &&
      modelJson.HitAreas.every((hitArea) => isPlainObject(hitArea) && isNonEmptyString(hitArea.Id) && isNonEmptyString(hitArea.Name));
    record(scope, "HitAreas 结构正确", hitAreasValid, `HitAreas=${Array.isArray(modelJson.HitAreas) ? modelJson.HitAreas.length : "非数组"}`);
  }
}

function validateExpressionShape(scope, references) {
  if (!Array.isArray(references.Expressions) || references.Expressions.length === 0) {
    record(scope, "Expressions 结构正确", false, "期望至少一个包含 Name 与 File 字段的表情配置。");
    return [];
  }

  const expressionsValid = references.Expressions.every(
    (expression) => isPlainObject(expression) && isNonEmptyString(expression.Name) && isNonEmptyString(expression.File),
  );
  record(scope, "Expressions 结构正确", expressionsValid, `Expressions=${references.Expressions.length}`);
  return references.Expressions;
}

function validateMotionShape(scope, references) {
  if (!isPlainObject(references.Motions)) {
    record(scope, "Motions 结构正确", false, "期望 Motions 为动作分组对象。");
    return [];
  }

  const motionGroups = Object.entries(references.Motions);
  const groupsValid = motionGroups.every(([groupName, motions]) => typeof groupName === "string" && Array.isArray(motions));
  record(scope, "Motions 分组结构正确", groupsValid, `Groups=${motionGroups.length}`);

  const motionEntries = motionGroups.flatMap(([groupName, motions]) =>
    Array.isArray(motions) ? motions.map((motion, index) => ({ groupName, motion, index })) : [],
  );

  if (motionEntries.length === 0) {
    record(scope, "Motions 条目结构正确", false, "期望至少一个 motion3.json 动作文件。");
    return [];
  }

  const entriesValid = motionEntries.every(({ motion }) => {
    if (!isPlainObject(motion) || !isNonEmptyString(motion.File)) {
      return false;
    }

    const fadeInValid = motion.FadeInTime === undefined || isFiniteNumber(motion.FadeInTime);
    const fadeOutValid = motion.FadeOutTime === undefined || isFiniteNumber(motion.FadeOutTime);
    const soundValid = motion.Sound === undefined || isNonEmptyString(motion.Sound);
    return fadeInValid && fadeOutValid && soundValid;
  });

  record(scope, "Motions 条目结构正确", entriesValid, `Motions=${motionEntries.length}`);
  return motionEntries;
}

function validateReferencedJsonShapes(scope, modelDirectory, references, expressions, motionEntries) {
  const physicsFile = assertFileReference(scope, modelDirectory, "Physics", references.Physics, ".physics3.json");
  validateJsonFile(scope, physicsFile, "Physics", (physicsJson, label) => {
    const valid =
      isFiniteNumber(physicsJson.Version) &&
      isPlainObject(physicsJson.Meta) &&
      Array.isArray(physicsJson.PhysicsSettings);
    record(scope, `${label} 内容结构正确`, valid, "期望 Version、Meta、PhysicsSettings。");
  });

  const displayInfoFile = assertFileReference(scope, modelDirectory, "DisplayInfo", references.DisplayInfo, ".cdi3.json");
  validateJsonFile(scope, displayInfoFile, "DisplayInfo", (displayInfoJson, label) => {
    const arraysValid = ["Parameters", "ParameterGroups", "Parts"].every(
      (key) => displayInfoJson[key] === undefined || Array.isArray(displayInfoJson[key]),
    );
    record(
      scope,
      `${label} 内容结构正确`,
      isFiniteNumber(displayInfoJson.Version) && arraysValid,
      "期望 Version，Parameters/ParameterGroups/Parts 如存在必须为数组。",
    );
  });

  expressions.forEach((expression, index) => {
    const expressionFile = assertFileReference(scope, modelDirectory, `Expressions[${index}].File`, expression.File, ".exp3.json");
    validateJsonFile(scope, expressionFile, `Expressions[${index}]`, (expressionJson, label) => {
      const valid =
        Array.isArray(expressionJson.Parameters) &&
        expressionJson.Parameters.every((parameter) => isPlainObject(parameter) && isNonEmptyString(parameter.Id) && parameter.Value !== undefined);
      record(scope, `${label} 内容结构正确`, valid, "期望 Parameters 数组，每项包含 Id 与 Value。");
    });
  });

  motionEntries.forEach(({ groupName, motion, index }) => {
    const motionLabel = `Motions[${groupName || "默认"}][${index}]`;
    const motionFile = assertFileReference(scope, modelDirectory, `${motionLabel}.File`, motion.File, ".motion3.json");
    validateJsonFile(scope, motionFile, motionLabel, (motionJson, label) => {
      const valid =
        isFiniteNumber(motionJson.Version) &&
        isPlainObject(motionJson.Meta) &&
        Array.isArray(motionJson.Curves) &&
        isFiniteNumber(motionJson.Meta.Duration) &&
        isFiniteNumber(motionJson.Meta.Fps);
      record(scope, `${label} 内容结构正确`, valid, "期望 Version、Meta.Duration、Meta.Fps 与 Curves。");
    });
  });
}

function buildManifestSummary(scope, modelPath, modelJson, references, expressions, motionEntries) {
  const expressionNames = expressions.map((expression) => expression.Name);
  const uniqueExpressionNames = new Set(expressionNames);
  const motionGroupNames = Object.keys(references.Motions ?? {});

  return {
    scope,
    modelPath: toDisplayPath(modelPath),
    version: modelJson.Version ?? "未知",
    moc: references.Moc ?? "未配置",
    textureCount: Array.isArray(references.Textures) ? references.Textures.length : 0,
    expressionCount: expressions.length,
    uniqueExpressionCount: uniqueExpressionNames.size,
    duplicateExpressionCount: expressionNames.length - uniqueExpressionNames.size,
    motionGroupCount: motionGroupNames.length,
    motionCount: motionEntries.length,
    motionGroups: motionGroupNames.map((groupName) => groupName || "默认"),
    hasPhysics: isNonEmptyString(references.Physics),
    hasDisplayInfo: isNonEmptyString(references.DisplayInfo),
    groupCount: Array.isArray(modelJson.Groups) ? modelJson.Groups.length : 0,
    hitAreaCount: Array.isArray(modelJson.HitAreas) ? modelJson.HitAreas.length : 0,
  };
}

function validateModelReferences(scope, modelPath) {
  let modelJson = null;
  try {
    modelJson = readJson(modelPath);
  } catch (error) {
    record(scope, "model3.json 可解析", false, `${toDisplayPath(modelPath)}: ${error.message}`);
    return;
  }

  record(scope, "model3.json 可解析", true, toDisplayPath(modelPath));
  validateModelShape(scope, modelJson);

  const modelDirectory = path.dirname(modelPath);
  const references = isPlainObject(modelJson.FileReferences) ? modelJson.FileReferences : {};

  assertFileReference(scope, modelDirectory, "Moc", references.Moc, ".moc3");
  assertFileReference(scope, modelDirectory, "Icon", "icon.png", ".png");

  if (!Array.isArray(references.Textures) || references.Textures.length === 0) {
    record(scope, "Textures 结构正确", false, "期望至少一个纹理文件路径。");
  } else {
    record(scope, "Textures 结构正确", references.Textures.every(isNonEmptyString), `Textures=${references.Textures.length}`);
    references.Textures.forEach((textureFile, index) => {
      assertFileReference(scope, modelDirectory, `Textures[${index}]`, textureFile, ".png");
    });
  }

  const expressions = validateExpressionShape(scope, references);
  const motionEntries = validateMotionShape(scope, references);
  validateReferencedJsonShapes(scope, modelDirectory, references, expressions, motionEntries);

  manifests.push(buildManifestSummary(scope, modelPath, modelJson, references, expressions, motionEntries));
}

function resolveCatalogReference(scope, assetRoot, model, fieldName, fileName) {
  if (!isNonEmptyString(fileName)) {
    record(scope, `models.json ${model.id || "未知模型"} ${fieldName} 引用格式正确`, false, `实际为 ${JSON.stringify(fileName)}`);
    return null;
  }

  if (!isNonEmptyString(model.directory)) {
    record(scope, `models.json ${model.id || "未知模型"} directory 引用格式正确`, false, `实际为 ${JSON.stringify(model.directory)}`);
    return null;
  }

  const normalizedDirectory = model.directory.trim().replaceAll("\\", "/").replace(/^\/+/, "");
  const modelDirectory = path.resolve(desktopRoot, scope, normalizedDirectory);
  if (!modelDirectory.startsWith(assetRoot)) {
    record(scope, `models.json ${model.id || "未知模型"} directory 保持在 live2d 目录内`, false, toDisplayPath(modelDirectory));
    return null;
  }

  return path.resolve(modelDirectory, fileName);
}

function validateModelCatalog(scope, assetRoot) {
  const catalogPath = path.join(assetRoot, "models.json");
  record(scope, "models.json 存在且非空", fileExistsAndNotEmpty(catalogPath), toDisplayPath(catalogPath));
  if (!fs.existsSync(catalogPath)) {
    return;
  }

  let catalog = null;
  try {
    catalog = readJson(catalogPath);
    record(scope, "models.json 可解析", true, toDisplayPath(catalogPath));
  } catch (error) {
    record(scope, "models.json 可解析", false, `${toDisplayPath(catalogPath)}: ${error.message}`);
    return;
  }

  const models = Array.isArray(catalog.models) ? catalog.models : [];
  record(scope, "models.json models 结构正确", models.length > 0, `models=${models.length}`);

  for (const model of models) {
    const modelId = isNonEmptyString(model?.id) ? model.id : "未知模型";
    const modelShapeValid =
      isPlainObject(model) &&
      isNonEmptyString(model.id) &&
      isNonEmptyString(model.label) &&
      isNonEmptyString(model.directory) &&
      isNonEmptyString(model.model);
    record(scope, `models.json ${modelId} 条目结构正确`, modelShapeValid, JSON.stringify({ id: model?.id, directory: model?.directory, model: model?.model }));
    if (!modelShapeValid) {
      continue;
    }

    const manifestPath = resolveCatalogReference(scope, assetRoot, model, "model", model.model);
    if (model.previewOnly === true) {
      record(scope, `models.json ${model.id} previewOnly manifest 可缺省`, true, manifestPath ? toDisplayPath(manifestPath) : model.model);
    } else {
      record(scope, `models.json ${model.id} manifest 存在且非空`, Boolean(manifestPath) && fileExistsAndNotEmpty(manifestPath), manifestPath ? toDisplayPath(manifestPath) : model.model);
    }

    for (const [fieldName, fileName] of [
      ["icon", model.icon],
      ["actions", model.actions],
      ["design", model.design],
    ]) {
      if (!isNonEmptyString(fileName)) {
        continue;
      }
      const referencePath = resolveCatalogReference(scope, assetRoot, model, fieldName, fileName);
      record(scope, `models.json ${model.id} ${fieldName} 存在且非空`, Boolean(referencePath) && fileExistsAndNotEmpty(referencePath), referencePath ? toDisplayPath(referencePath) : fileName);
    }
  }
}

function validateTarget(target) {
  const assetRoot = path.join(desktopRoot, target, "live2d");
  const modelPath = path.join(desktopRoot, target, options.model);
  const modelFiles = listModelFiles(assetRoot);

  record(
    target,
    `${target}/live2d 目录存在`,
    fs.existsSync(assetRoot) && fs.statSync(assetRoot).isDirectory(),
    toDisplayPath(assetRoot),
  );

  record(
    target,
    `${target}/live2d 下存在 model3.json`,
    modelFiles.length > 0,
    modelFiles.length > 0 ? modelFiles.map(toDisplayPath).join(", ") : toDisplayPath(assetRoot),
  );

  record(target, "参考 Cubism 模型存在且非空", fileExistsAndNotEmpty(modelPath), toDisplayPath(modelPath));

  if (fs.existsSync(assetRoot)) {
    validateModelCatalog(target, assetRoot);
  }

  if (fs.existsSync(modelPath)) {
    validateModelReferences(target, modelPath);
  }
}

function printManifestSummaries() {
  if (manifests.length === 0) {
    console.log("\nManifest 统计摘要：未读取到可统计的 model3.json。");
    return;
  }

  console.log("\nManifest 统计摘要：");
  for (const manifest of manifests) {
    console.log(`- ${manifest.scope}: ${manifest.modelPath}`);
    console.log(`  Version: ${manifest.version}`);
    console.log(`  MOC: ${manifest.moc}`);
    console.log(`  贴图: ${manifest.textureCount} 个`);
    console.log(
      `  表情: ${manifest.expressionCount} 个，唯一名称 ${manifest.uniqueExpressionCount} 个，重复名称 ${manifest.duplicateExpressionCount} 个`,
    );
    console.log(`  动作: ${manifest.motionCount} 个，分组 ${manifest.motionGroupCount} 个（${manifest.motionGroups.join(", ") || "无"}）`);
    console.log(`  Physics: ${manifest.hasPhysics ? "已配置" : "未配置"}`);
    console.log(`  DisplayInfo: ${manifest.hasDisplayInfo ? "已配置" : "未配置"}`);
    console.log(`  Groups: ${manifest.groupCount} 个`);
    console.log(`  HitAreas: ${manifest.hitAreaCount} 个`);
  }
}

for (const target of targetRoots) {
  validateTarget(target);
}

const failures = checks.filter((check) => !check.ok);

if (!options.summary) {
  for (const check of checks) {
    const prefix = check.ok ? "通过" : "错误";
    const output = `[${prefix}] ${check.scope}: ${check.name}: ${check.detail}`;
    if (check.ok) {
      console.log(output);
    } else {
      console.error(output);
    }
  }
}

printManifestSummaries();

if (failures.length > 0) {
  console.error(`\nLive2D 资源校验失败：${failures.length} 项错误。`);
  process.exitCode = 1;
} else if (!options.summary) {
  console.log("\nLive2D 资源校验通过。");
}
