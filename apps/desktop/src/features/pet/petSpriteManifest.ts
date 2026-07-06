import type { SpritePetAnimationKey } from "./spritePetState";

export type PetSpriteAnimation = {
  key: SpritePetAnimationKey;
  row: number;
  frames: number;
  columns: number[];
  durationsMs: number[];
};

export type PetSpriteManifest = {
  id: string;
  displayName: string;
  manifestPath: string;
  spritesheetCleanPath: string;
  spritesheetPath: string;
  fallbackPngPath: string;
  cell: {
    width: number;
    height: number;
  };
  layout: {
    columns: number;
    rows: number;
    width: number;
    height: number;
  };
  animations: Record<SpritePetAnimationKey, PetSpriteAnimation>;
};

const defaultAnimationKeys = [
  "idle",
  "running-right",
  "running-left",
  "waving",
  "thinking",
  "working",
  "done",
  "failed",
  "sleeping",
] as const satisfies readonly SpritePetAnimationKey[];

export const PET_SPRITE_MANIFEST_PATH = "/pets/agent-pet-neko/pet.json";

export const DEFAULT_PET_SPRITE_MANIFEST: PetSpriteManifest = {
  id: "agent-pet-neko",
  displayName: "Agent Pet Neko",
  manifestPath: PET_SPRITE_MANIFEST_PATH,
  spritesheetCleanPath: "/pets/agent-pet-neko/spritesheet-clean.png",
  spritesheetPath: "/pets/agent-pet-neko/spritesheet.webp",
  fallbackPngPath: "/pets/agent-pet-neko/spritesheet.png",
  cell: {
    width: 192,
    height: 208,
  },
  layout: {
    columns: 8,
    rows: 9,
    width: 1536,
    height: 1872,
  },
  animations: {
    idle: animation("idle", 0, 6, [280, 110, 110, 140, 140, 320]),
    "running-right": animation("running-right", 1, 8, [120, 120, 120, 120, 120, 120, 120, 220]),
    "running-left": animation("running-left", 2, 8, [120, 120, 120, 120, 120, 120, 120, 220]),
    waving: animation("waving", 3, 6, [140, 140, 140, 140, 140, 280]),
    thinking: animation("thinking", 4, 6, [170, 150, 150, 170, 150, 260]),
    working: animation("working", 5, 6, [120, 120, 120, 120, 120, 220]),
    done: animation("done", 6, 5, [140, 120, 120, 150, 280]),
    failed: animation("failed", 7, 6, [180, 160, 160, 180, 180, 280]),
    sleeping: animation("sleeping", 8, 6, [320, 320, 360, 320, 320, 420]),
  },
};

function animation(key: SpritePetAnimationKey, row: number, frames: number, durationsMs: number[]): PetSpriteAnimation {
  return {
    key,
    row,
    frames,
    columns: Array.from({ length: frames }, (_, index) => index),
    durationsMs,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function readPositiveNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

function readNonNegativeInteger(value: unknown, fallback: number): number {
  return Number.isInteger(value) && Number(value) >= 0 ? Number(value) : fallback;
}

function readPositiveInteger(value: unknown, fallback: number): number {
  return Number.isInteger(value) && Number(value) > 0 ? Number(value) : fallback;
}

function normalizePublicPath(value: string, baseDirectory: string): string {
  const normalized = value.trim().replace(/\\/g, "/");
  if (!normalized) {
    return baseDirectory;
  }
  if (normalized.startsWith("/")) {
    return normalized;
  }
  return `${baseDirectory.replace(/\/+$/u, "")}/${normalized.replace(/^\/+/, "")}`;
}

function isSpritePetAnimationKey(value: string): value is SpritePetAnimationKey {
  return (defaultAnimationKeys as readonly string[]).includes(value);
}

function readColumns(value: unknown, frames: number, layoutColumns: number): number[] {
  if (!Array.isArray(value)) {
    return Array.from({ length: frames }, (_, index) => index).filter((index) => index < layoutColumns);
  }
  const columns = value
    .map((column) => readNonNegativeInteger(column, -1))
    .filter((column) => column >= 0 && column < layoutColumns)
    .slice(0, frames);
  return columns.length > 0 ? columns : Array.from({ length: frames }, (_, index) => index).filter((index) => index < layoutColumns);
}

function readDurations(value: unknown, frames: number, fallback: number[]): number[] {
  if (!Array.isArray(value)) {
    return normalizeDurationLength(fallback, frames);
  }
  const durations = value
    .map((duration) => readPositiveNumber(duration, 0))
    .filter((duration) => duration > 0)
    .slice(0, frames);
  return normalizeDurationLength(durations.length > 0 ? durations : fallback, frames);
}

function normalizeDurationLength(durations: number[], frames: number): number[] {
  const fallback = durations.find((duration) => duration > 0) ?? 140;
  return Array.from({ length: frames }, (_, index) => durations[index] || fallback);
}

export function normalizePetSpriteManifest(raw: unknown, manifestPath = PET_SPRITE_MANIFEST_PATH): PetSpriteManifest {
  if (!isRecord(raw)) {
    return DEFAULT_PET_SPRITE_MANIFEST;
  }

  const baseDirectory = manifestPath.split("/").slice(0, -1).join("/") || "/";
  const defaultManifest = DEFAULT_PET_SPRITE_MANIFEST;
  const defaultCell = defaultManifest.cell;
  const defaultLayout = defaultManifest.layout;
  const rawCell = isRecord(raw.cell) ? raw.cell : {};
  const rawLayout = isRecord(raw.layout) ? raw.layout : {};
  const cell = {
    width: readPositiveNumber(rawCell.width, defaultCell.width),
    height: readPositiveNumber(rawCell.height, defaultCell.height),
  };
  const layout = {
    columns: readPositiveInteger(rawLayout.columns, defaultLayout.columns),
    rows: readPositiveInteger(rawLayout.rows, defaultLayout.rows),
    width: readPositiveNumber(rawLayout.width, cell.width * readPositiveInteger(rawLayout.columns, defaultLayout.columns)),
    height: readPositiveNumber(rawLayout.height, cell.height * readPositiveInteger(rawLayout.rows, defaultLayout.rows)),
  };
  const rawAnimations = isRecord(raw.animations) ? raw.animations : {};
  const animations = Object.fromEntries(
    defaultAnimationKeys.map((key) => {
      const fallback = defaultManifest.animations[key];
      const rawAnimation = isRecord(rawAnimations[key]) ? rawAnimations[key] : {};
      const row = Math.min(readNonNegativeInteger(rawAnimation.row, fallback.row), Math.max(0, layout.rows - 1));
      const frames = readPositiveInteger(rawAnimation.frames, fallback.frames);
      return [
        key,
        {
          key,
          row,
          frames,
          columns: readColumns(rawAnimation.columns, frames, layout.columns),
          durationsMs: readDurations(rawAnimation.durationsMs, frames, fallback.durationsMs),
        },
      ];
    }),
  ) as Record<SpritePetAnimationKey, PetSpriteAnimation>;

  for (const [key, value] of Object.entries(rawAnimations)) {
    if (!isSpritePetAnimationKey(key) || !isRecord(value)) {
      continue;
    }
    const fallback = animations[key];
    const frames = readPositiveInteger(value.frames, fallback.frames);
    animations[key] = {
      key,
      row: Math.min(readNonNegativeInteger(value.row, fallback.row), Math.max(0, layout.rows - 1)),
      frames,
      columns: readColumns(value.columns, frames, layout.columns),
      durationsMs: readDurations(value.durationsMs, frames, fallback.durationsMs),
    };
  }

  return {
    id: readString(raw.id, defaultManifest.id),
    displayName: readString(raw.displayName, defaultManifest.displayName),
    manifestPath,
    spritesheetCleanPath: normalizePublicPath(
      readString(raw.spritesheetCleanPath, defaultManifest.spritesheetCleanPath),
      baseDirectory,
    ),
    spritesheetPath: normalizePublicPath(readString(raw.spritesheetPath, defaultManifest.spritesheetPath), baseDirectory),
    fallbackPngPath: normalizePublicPath(readString(raw.fallbackPngPath, defaultManifest.fallbackPngPath), baseDirectory),
    cell,
    layout,
    animations,
  };
}

export function frameForAnimation(animation: PetSpriteAnimation, timestamp: number, seed = 0): number {
  const durations = animation.durationsMs.length ? animation.durationsMs : [140];
  const cycleMs = durations.reduce((total, duration) => total + duration, 0);
  if (cycleMs <= 0) {
    return 0;
  }
  const seededTime = (timestamp + Math.floor(seed * cycleMs)) % cycleMs;
  let elapsed = 0;
  for (let index = 0; index < durations.length; index += 1) {
    elapsed += durations[index];
    if (seededTime < elapsed) {
      return Math.min(index, animation.columns.length - 1);
    }
  }
  return Math.min(durations.length - 1, animation.columns.length - 1);
}
