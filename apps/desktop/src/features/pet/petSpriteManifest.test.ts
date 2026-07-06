import { describe, expect, it } from "vitest";

import {
  DEFAULT_PET_SPRITE_MANIFEST,
  frameForAnimation,
  normalizePetSpriteManifest,
} from "./petSpriteManifest";

describe("normalizePetSpriteManifest", () => {
  it("normalizes the Agent Pet Neko spritesheet manifest", () => {
    const manifest = normalizePetSpriteManifest(
      {
        id: "agent-pet-neko",
        displayName: "Agent Pet Neko",
        spritesheetCleanPath: "spritesheet-clean.png",
        spritesheetPath: "spritesheet.webp",
        fallbackPngPath: "spritesheet.png",
        cell: { width: 192, height: 208 },
        layout: { columns: 8, rows: 9, width: 1536, height: 1872 },
        animations: {
          idle: { row: 0, frames: 6, columns: [0, 1, 2, 3, 4, 5], durationsMs: [280, 110, 110, 140, 140, 320] },
          "running-right": { row: 1, frames: 8, columns: [0, 1, 2, 3, 4, 5, 6, 7], durationsMs: [120, 120, 120, 120, 120, 120, 120, 220] },
          "running-left": { row: 2, frames: 8, columns: [0, 1, 2, 3, 4, 5, 6, 7], durationsMs: [120, 120, 120, 120, 120, 120, 120, 220] },
          waving: { row: 3, frames: 6, columns: [0, 1, 2, 3, 4, 5], durationsMs: [140, 140, 140, 140, 140, 280] },
          thinking: { row: 4, frames: 6, columns: [0, 1, 2, 3, 4, 5], durationsMs: [170, 150, 150, 170, 150, 260] },
          working: { row: 5, frames: 6, columns: [0, 1, 2, 3, 4, 5], durationsMs: [120, 120, 120, 120, 120, 220] },
          done: { row: 6, frames: 5, columns: [0, 1, 2, 3, 4], durationsMs: [140, 120, 120, 150, 280] },
          failed: { row: 7, frames: 6, columns: [0, 1, 2, 3, 4, 5], durationsMs: [180, 160, 160, 180, 180, 280] },
          sleeping: { row: 8, frames: 6, columns: [0, 1, 2, 3, 4, 5], durationsMs: [320, 320, 360, 320, 320, 420] },
        },
      },
      "/pets/agent-pet-neko/pet.json",
    );

    expect(manifest.id).toBe("agent-pet-neko");
    expect(manifest.spritesheetCleanPath).toBe("/pets/agent-pet-neko/spritesheet-clean.png");
    expect(manifest.spritesheetPath).toBe("/pets/agent-pet-neko/spritesheet.webp");
    expect(manifest.fallbackPngPath).toBe("/pets/agent-pet-neko/spritesheet.png");
    expect(manifest.cell).toEqual({ width: 192, height: 208 });
    expect(manifest.layout).toEqual({ columns: 8, rows: 9, width: 1536, height: 1872 });
    expect(manifest.animations.working.row).toBe(5);
    expect(manifest.animations.done.columns).toEqual([0, 1, 2, 3, 4]);
  });

  it("falls back to the bundled Agent Pet Neko manifest for invalid input", () => {
    const manifest = normalizePetSpriteManifest(null);

    expect(manifest).toEqual(DEFAULT_PET_SPRITE_MANIFEST);
    expect(manifest.spritesheetCleanPath).toBe("/pets/agent-pet-neko/spritesheet-clean.png");
    expect(manifest.spritesheetPath).toBe("/pets/agent-pet-neko/spritesheet.webp");
    expect(manifest.fallbackPngPath).toBe("/pets/agent-pet-neko/spritesheet.png");
    expect(manifest.spritesheetPath).not.toContain("/images/pet-codex-actions.png");
  });
});

describe("frameForAnimation", () => {
  it("uses configured per-frame durations", () => {
    const animation = {
      key: "idle" as const,
      row: 0,
      frames: 3,
      columns: [0, 1, 2],
      durationsMs: [100, 200, 300],
    };

    expect(frameForAnimation(animation, 0)).toBe(0);
    expect(frameForAnimation(animation, 120)).toBe(1);
    expect(frameForAnimation(animation, 350)).toBe(2);
    expect(frameForAnimation(animation, 620)).toBe(0);
  });
});
