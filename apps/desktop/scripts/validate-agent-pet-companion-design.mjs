import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const designDir = path.join(root, "public", "live2d", "agent_pet_companion");
const designPath = path.join(designDir, "character-design.json");
const actionsPath = path.join(designDir, "agent_pet_companion.actions.json");
const blueprintPath = path.join(designDir, "CUBISM_MODEL_BLUEPRINT.md");
const productionSpecPath = path.join(designDir, "cubism-production-spec.json");
const conceptReferencePath = path.join(designDir, "concept-reference.png");
const model3TemplatePath = path.join(designDir, "agent_pet_companion.model3.template.json");
const sourceDir = path.join(designDir, "source");
const paintedV2Dir = path.join(sourceDir, "painted_v2");
const paintedV2ManifestPath = path.join(paintedV2Dir, "agent_pet_companion_painted_v2.layer-manifest.json");
const paintedV2ExpressionManifestPath = path.join(
  paintedV2Dir,
  "agent_pet_companion_painted_v2.expression-references.json",
);
const paintedV2CompositePath = path.join(paintedV2Dir, "agent_pet_companion_painted_v2_composite.png");
const paintedV2FullCutoutPath = path.join(paintedV2Dir, "agent_pet_companion_painted_v2_full_cutout.png");
const paintedV2ContactSheetPath = path.join(paintedV2Dir, "agent_pet_companion_painted_v2_layer_contact_sheet.png");
const paintedV2AssemblyScriptPath = path.join(paintedV2Dir, "assemble-agent-pet-companion-painted-v2.jsx");
const paintedV2ReadmePath = path.join(paintedV2Dir, "PAINTED_V2_SOURCE_ART.md");
const paintedV2RiggingNotesPath = path.join(paintedV2Dir, "CUBISM_ACTION_RIGGING_NOTES.md");
const catalogPath = path.join(root, "public", "live2d", "models.json");

const requiredActionKeys = [
  "idle",
  "chat_listen",
  "chat_think",
  "chat_talk",
  "chat_done",
  "memory_search",
  "memory_found",
  "memory_not_found",
  "memory_save_diary",
  "memory_save_long_term",
  "memory_confirm_needed",
  "memory_privacy_guard",
  "memory_revert",
  "task_create",
  "task_reminder",
  "task_complete",
  "wiki_organize",
  "wiki_check",
  "wiki_archive",
  "continuity_remember",
  "emotion_comfort",
  "system_connecting",
  "system_offline",
  "system_error",
  "system_diagnosed",
  "tts_speaking",
  "sleep_quiet",
  "celebrate_small",
];

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function fail(message) {
  console.error(`[failed] ${message}`);
  process.exitCode = 1;
}

function pass(message) {
  console.log(`[ok] ${message}`);
}

function expressionNames(design) {
  return new Set((Array.isArray(design.expressions) ? design.expressions : []).map((item) => item?.name).filter(Boolean));
}

function motionGroupSizes(design) {
  const groups = new Map();
  const rawGroups = design.motionGroups && typeof design.motionGroups === "object" ? design.motionGroups : {};
  for (const [group, motions] of Object.entries(rawGroups)) {
    groups.set(group, Array.isArray(motions) ? motions.length : 0);
  }
  return groups;
}

function validate() {
  if (!fs.existsSync(designPath)) {
    fail(`missing design file: ${path.relative(root, designPath)}`);
    return;
  }
  if (!fs.existsSync(actionsPath)) {
    fail(`missing action profile: ${path.relative(root, actionsPath)}`);
    return;
  }
  if (!fs.existsSync(blueprintPath)) {
    fail(`missing Cubism production blueprint: ${path.relative(root, blueprintPath)}`);
    return;
  }
  if (!fs.existsSync(productionSpecPath)) {
    fail(`missing machine-readable Cubism production spec: ${path.relative(root, productionSpecPath)}`);
    return;
  }
  if (!fs.existsSync(conceptReferencePath)) {
    fail(`missing visual concept reference: ${path.relative(root, conceptReferencePath)}`);
    return;
  }
  if (!fs.existsSync(model3TemplatePath)) {
    fail(`missing model3 export template: ${path.relative(root, model3TemplatePath)}`);
    return;
  }
  if (!fs.existsSync(paintedV2ManifestPath)) {
    fail(`missing painted v2 source art manifest: ${path.relative(root, paintedV2ManifestPath)}`);
    return;
  }
  if (!fs.existsSync(paintedV2ExpressionManifestPath)) {
    fail(`missing painted v2 expression reference manifest: ${path.relative(root, paintedV2ExpressionManifestPath)}`);
    return;
  }
  if (!fs.existsSync(paintedV2CompositePath)) {
    fail(`missing painted v2 composite preview: ${path.relative(root, paintedV2CompositePath)}`);
    return;
  }
  if (!fs.existsSync(paintedV2FullCutoutPath)) {
    fail(`missing painted v2 full cutout: ${path.relative(root, paintedV2FullCutoutPath)}`);
    return;
  }
  if (!fs.existsSync(paintedV2ContactSheetPath)) {
    fail(`missing painted v2 contact sheet: ${path.relative(root, paintedV2ContactSheetPath)}`);
    return;
  }
  if (!fs.existsSync(paintedV2AssemblyScriptPath)) {
    fail(`missing painted v2 Photoshop assembly script: ${path.relative(root, paintedV2AssemblyScriptPath)}`);
    return;
  }
  if (!fs.existsSync(paintedV2ReadmePath)) {
    fail(`missing painted v2 source art readme: ${path.relative(root, paintedV2ReadmePath)}`);
    return;
  }
  if (!fs.existsSync(paintedV2RiggingNotesPath)) {
    fail(`missing painted v2 action rigging notes: ${path.relative(root, paintedV2RiggingNotesPath)}`);
    return;
  }
  if (!fs.existsSync(catalogPath)) {
    fail(`missing model catalog: ${path.relative(root, catalogPath)}`);
    return;
  }

  const design = readJson(designPath);
  const actionProfile = readJson(actionsPath);
  const productionSpec = readJson(productionSpecPath);
  const model3Template = readJson(model3TemplatePath);
  const paintedV2Manifest = readJson(paintedV2ManifestPath);
  const paintedV2ExpressionManifest = readJson(paintedV2ExpressionManifestPath);
  const catalog = readJson(catalogPath);
  const expressions = expressionNames(design);
  const motionGroups = motionGroupSizes(design);
  const specExpressions = new Set(Array.isArray(productionSpec.expressions) ? productionSpec.expressions : []);
  const specMotionGroups = productionSpec.motionGroups && typeof productionSpec.motionGroups === "object" ? productionSpec.motionGroups : {};
  const actions = actionProfile.actions && typeof actionProfile.actions === "object" ? actionProfile.actions : {};
  const catalogModels = Array.isArray(catalog.models) ? catalog.models : [];
  const defaultCatalogEntry = catalogModels[0] || null;
  const companionCatalogEntry = catalogModels.find((entry) => entry?.id === design.id) || null;
  const exportContract = design.exportContract?.modelsJsonEntryAfterExport;
  const previewContract = design.exportContract?.modelsJsonEntryWhilePreview;

  if (design.status === "design_spec_only") {
    pass("design is explicitly marked as non-runnable until Cubism export");
  } else {
    fail("design status must stay design_spec_only until a real Cubism export exists");
  }

  pass(`Cubism production blueprint exists: ${path.relative(root, blueprintPath)}`);
  pass(`visual concept reference exists: ${path.relative(root, conceptReferencePath)}`);

  if (productionSpec.status === "awaiting_source_art_and_cubism_export" && productionSpec.notRuntimeModel === true) {
    pass("Cubism production spec is explicitly marked as awaiting source art and export");
  } else {
    fail("Cubism production spec must be marked as awaiting source art/export, not as a runnable model");
  }

  if (productionSpec.id === design.id) {
    pass(`Cubism production spec id matches design id: ${productionSpec.id}`);
  } else {
    fail(`Cubism production spec id does not match design id: ${productionSpec.id}`);
  }

  if (model3Template.Version === 3 && model3Template.FileReferences?.Moc === "agent_pet_companion.moc3") {
    pass("model3 export template declares the expected Cubism moc file");
  } else {
    fail("model3 export template must declare Version 3 and agent_pet_companion.moc3");
  }

  if (
    paintedV2Manifest.id === design.id &&
    paintedV2Manifest.status === "painted_source_art_generated_not_rigged" &&
    paintedV2Manifest.notRuntimeModel === true &&
    paintedV2Manifest.layerCount >= 20
  ) {
    pass(`painted v2 source art package declares ${paintedV2Manifest.layerCount} source layers`);
  } else {
    fail("painted v2 source art package must be marked painted_source_art_generated_not_rigged with at least 20 layers");
  }

  const paintedV2Layers = Array.isArray(paintedV2Manifest.layers) ? paintedV2Manifest.layers : [];
  const requiredPaintedV2Parts = new Set([
    "PartHead",
    "PartHairFront",
    "PartHairBack",
    "PartEyeL",
    "PartEyeR",
    "PartMouth",
    "PartBody",
    "PartArmL",
    "PartArmR",
    "PartNotebook",
    "PartDatabaseCharm",
  ]);
  const actualPaintedV2Parts = new Set(paintedV2Layers.map((entry) => entry?.part).filter(Boolean));
  for (const part of requiredPaintedV2Parts) {
    if (actualPaintedV2Parts.has(part)) {
      pass(`painted v2 source part exists: ${part}`);
    } else {
      fail(`painted v2 source part is missing: ${part}`);
    }
  }
  for (const entry of paintedV2Layers) {
    if (entry?.file && !fs.existsSync(path.join(paintedV2Dir, entry.file))) {
      fail(`painted v2 source art layer file is missing: ${entry.file}`);
    }
  }
  if (paintedV2Layers.length === paintedV2Manifest.layerCount) {
    pass("painted v2 manifest layer count matches listed layer files");
  } else {
    fail("painted v2 manifest layer count does not match listed layer files");
  }

  const paintedV2ExpressionRefs = Array.isArray(paintedV2ExpressionManifest.references)
    ? paintedV2ExpressionManifest.references
    : [];
  if (
    paintedV2ExpressionManifest.id === design.id &&
    paintedV2ExpressionManifest.status === "expression_references_only_not_runtime" &&
    paintedV2ExpressionManifest.notRuntimeModel === true &&
    paintedV2ExpressionRefs.length >= 8
  ) {
    pass(`painted v2 expression reference package declares ${paintedV2ExpressionRefs.length} references`);
  } else {
    fail("painted v2 expression reference package must be marked expression_references_only_not_runtime with at least 8 references");
  }
  for (const entry of paintedV2ExpressionRefs) {
    if (entry?.file && !fs.existsSync(path.join(paintedV2Dir, entry.file))) {
      fail(`painted v2 expression reference file is missing: ${entry.file}`);
    }
  }

  if (!defaultCatalogEntry) {
    fail("models.json must list at least one default model");
  } else {
    pass(`models.json default model is ${defaultCatalogEntry.id}`);
  }

  if (!companionCatalogEntry) {
    fail("models.json must include the project-specific companion entry");
  } else {
    pass(`models.json includes project companion entry: ${companionCatalogEntry.id}`);
  }

  if (exportContract) {
    for (const field of ["id", "label", "directory", "model", "icon", "actions"]) {
      if (companionCatalogEntry?.[field] !== exportContract[field]) {
        fail(`models.json companion ${field} does not match character export contract`);
      }
    }
  }

  if (previewContract) {
    for (const [field, value] of Object.entries(previewContract)) {
      if (companionCatalogEntry?.[field] !== value) {
        fail(`models.json companion preview ${field} does not match character preview contract`);
      }
    }
  }

  if (companionCatalogEntry?.previewOnly === true) {
    pass("project companion is explicitly registered as previewOnly");
  } else {
    fail("project companion must stay previewOnly until a real Cubism export exists");
  }

  if (companionCatalogEntry?.design === "character-design.json" && fs.existsSync(path.join(designDir, companionCatalogEntry.design))) {
    pass(`project companion design file exists: ${companionCatalogEntry.design}`);
  } else {
    fail(`project companion design file is missing: ${companionCatalogEntry?.design}`);
  }

  if (companionCatalogEntry?.icon && fs.existsSync(path.join(designDir, companionCatalogEntry.icon))) {
    pass(`project companion icon exists: ${companionCatalogEntry.icon}`);
  } else {
    fail(`project companion icon is missing: ${companionCatalogEntry?.icon}`);
  }

  if (companionCatalogEntry?.actions && fs.existsSync(path.join(designDir, companionCatalogEntry.actions))) {
    pass(`project companion action profile exists: ${companionCatalogEntry.actions}`);
  } else {
    fail(`project companion action profile is missing: ${companionCatalogEntry?.actions}`);
  }

  const modelPath = companionCatalogEntry?.model ? path.join(designDir, companionCatalogEntry.model) : "";
  if (modelPath && !fs.existsSync(modelPath)) {
    pass("project companion model3 export is intentionally pending");
  }

  for (const key of requiredActionKeys) {
    if (!actions[key]) {
      fail(`missing project action: ${key}`);
    }
  }

  for (const [key, action] of Object.entries(actions)) {
    if (!requiredActionKeys.includes(key)) {
      fail(`unexpected project action: ${key}`);
    }
    if (!action || typeof action !== "object") {
      fail(`invalid action entry: ${key}`);
      continue;
    }
    if (typeof action.expression !== "string" || !expressions.has(action.expression)) {
      fail(`action ${key} references unknown expression: ${action.expression}`);
    }
    const motion = action.motion;
    if (!motion || typeof motion !== "object") {
      fail(`action ${key} has no motion reference`);
      continue;
    }
    const groupSize = motionGroups.get(String(motion.group));
    if (groupSize === undefined) {
      fail(`action ${key} references unknown motion group: ${motion.group}`);
    } else if (!Number.isInteger(motion.index) || motion.index < 0 || motion.index >= groupSize) {
      fail(`action ${key} references invalid motion index: ${motion.group}[${motion.index}]`);
    }
    if (!specExpressions.has(action.expression)) {
      fail(`production spec is missing expression used by action ${key}: ${action.expression}`);
    }
    const specGroup = specMotionGroups[String(motion.group)];
    if (!Array.isArray(specGroup)) {
      fail(`production spec is missing motion group used by action ${key}: ${motion.group}`);
    } else if (!specGroup[motion.index]) {
      fail(`production spec is missing motion file for action ${key}: ${motion.group}[${motion.index}]`);
    }
  }

  if (process.exitCode) {
    return;
  }

  pass(`validated ${requiredActionKeys.length} project actions for ${design.displayName || design.id}`);
}

validate();
