import { render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SpritePetStage } from "./SpritePetStage";
import type { PetStageView } from "./petStageState";

const idleStage: PetStageView = {
  state: "idle",
  label: "idle",
  mood: "idle",
  message: "idle",
  hint: "idle",
};

const loadedImageSources: string[] = [];
const putImageDataMock = vi.fn();
let readableCanvasEnabled = false;
let latestCleanedAtlasData: Uint8ClampedArray | null = null;
let failedImageSourceIncludes: string[] = [];

const manifest = {
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
};

function renderStage(overrides: Partial<Parameters<typeof SpritePetStage>[0]> = {}) {
  const canvasRef = createRef<HTMLCanvasElement>();
  return render(
    <SpritePetStage
      stage={idleStage}
      canvasRef={canvasRef}
      connected
      streaming={false}
      speaking={false}
      inputVisible={false}
      shortcutVisible={false}
      dragging={false}
      dragDirection="none"
      active={false}
      {...overrides}
    />,
  );
}

class TestImage {
  decoding = "auto";
  naturalWidth = 1536;
  naturalHeight = 1872;
  width = 1536;
  height = 1872;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private nextSrc = "";

  set src(value: string) {
    this.nextSrc = value;
    loadedImageSources.push(value);
    queueMicrotask(() => {
      if (failedImageSourceIncludes.some((needle) => value.includes(needle))) {
        this.onerror?.();
        return;
      }
      this.onload?.();
    });
  }

  get src() {
    return this.nextSrc;
  }
}

beforeEach(() => {
  loadedImageSources.length = 0;
  readableCanvasEnabled = false;
  latestCleanedAtlasData = null;
  failedImageSourceIncludes = [];
  putImageDataMock.mockClear();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(manifest) })));
  vi.stubGlobal("Image", TestImage);
  vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    width: 192,
    height: 208,
    top: 0,
    right: 192,
    bottom: 208,
    left: 0,
    toJSON: () => ({}),
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => ({
    setTransform: vi.fn(),
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    drawImage: vi.fn(),
    beginPath: vi.fn(),
    ellipse: vi.fn(),
    fill: vi.fn(),
    arc: vi.fn(),
    stroke: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    quadraticCurveTo: vi.fn(),
    createRadialGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
    translate: vi.fn(),
    rotate: vi.fn(),
    scale: vi.fn(),
    set imageSmoothingEnabled(_value: boolean) {},
    set imageSmoothingQuality(_value: ImageSmoothingQuality) {},
    set fillStyle(_value: string | CanvasGradient | CanvasPattern) {},
    set strokeStyle(_value: string | CanvasGradient | CanvasPattern) {},
    set lineWidth(_value: number) {},
    set lineCap(_value: CanvasLineCap) {},
    set globalAlpha(_value: number) {},
    set globalCompositeOperation(_value: GlobalCompositeOperation) {},
    getImageData: readableCanvasEnabled
      ? vi.fn((_left: number, _top: number, width: number, height: number) => {
          const data = new Uint8ClampedArray(width * height * 4);
          const magentaOffset = (width + 1) * 4;
          data[magentaOffset] = 245;
          data[magentaOffset + 1] = 98;
          data[magentaOffset + 2] = 243;
          data[magentaOffset + 3] = 255;
          latestCleanedAtlasData = data;
          return { data, width, height } as ImageData;
        })
      : undefined,
    putImageData: readableCanvasEnabled
      ? vi.fn((imageData: ImageData) => {
          latestCleanedAtlasData = imageData.data;
          putImageDataMock(imageData);
        })
      : undefined,
  } as unknown as CanvasRenderingContext2D));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("SpritePetStage", () => {
  it("loads the Agent Pet Neko manifest and sizes the canvas from its cell", async () => {
    const { container } = renderStage();

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/pets/agent-pet-neko/pet.json", { cache: "no-store" }));
    await waitFor(() => expect(container.querySelector("canvas")).toHaveAttribute("width", "192"));
    expect(container.querySelector("canvas")).toHaveAttribute("height", "208");
  });

  it("keeps semantic action data attributes for speaking and dragging", async () => {
    const { rerender, unmount } = renderStage({ speaking: true });
    expect(screen.getByLabelText("桌面 Q 版桌宠")).toHaveAttribute("data-pet-action-key", "chat_talk");
    expect(screen.getByLabelText("桌面 Q 版桌宠")).toHaveAttribute("data-pet-speaking", "true");

    const canvasRef = createRef<HTMLCanvasElement>();
    rerender(
      <SpritePetStage
        stage={idleStage}
        canvasRef={canvasRef}
        connected
        streaming={false}
        speaking={false}
        inputVisible={false}
        shortcutVisible={false}
        dragging
        dragDirection="left"
        active={false}
      />,
    );
    expect(screen.getByLabelText("桌面 Q 版桌宠")).toHaveAttribute("data-pet-action-key", "pet_drag_left");
    unmount();
    await Promise.resolve();
  });

  it("does not use halfbody or legacy codex action assets for the pet window renderer", async () => {
    renderStage();
    await waitFor(() => expect(loadedImageSources.join("\n")).toContain("/pets/agent-pet-neko/spritesheet-clean.png"));

    const loadedSources = loadedImageSources.join("\n");
    expect(loadedSources).toContain("/pets/agent-pet-neko/spritesheet-clean.png");
    expect(loadedSources).toContain("/pets/agent-pet-neko/spritesheet.png");
    expect(loadedSources).not.toContain("sprite-pet/halfbody");
    expect(loadedSources).not.toContain("/images/pet-codex-actions.png");
  });

  it("falls back to the webp atlas when the cleaned spritesheet fails to load", async () => {
    failedImageSourceIncludes = ["spritesheet-clean.png"];

    renderStage();

    await waitFor(() => expect(loadedImageSources.join("\n")).toContain("/pets/agent-pet-neko/spritesheet.webp"));
    const cleanIndex = loadedImageSources.findIndex((source) => source.includes("/pets/agent-pet-neko/spritesheet-clean.png"));
    const webpIndex = loadedImageSources.findIndex((source) => source.includes("/pets/agent-pet-neko/spritesheet.webp"));
    expect(cleanIndex).toBeGreaterThanOrEqual(0);
    expect(webpIndex).toBeGreaterThan(cleanIndex);
  });

  it("falls back to the png atlas when the cleaned and webp spritesheets fail to load", async () => {
    failedImageSourceIncludes = ["spritesheet-clean.png", "spritesheet.webp"];

    renderStage();

    await waitFor(() => {
      const webpIndex = loadedImageSources.findIndex((source) => source.includes("/pets/agent-pet-neko/spritesheet.webp"));
      const pngIndex = loadedImageSources.findIndex(
        (source, index) => index > webpIndex && source.includes("/pets/agent-pet-neko/spritesheet.png"),
      );
      expect(webpIndex).toBeGreaterThanOrEqual(0);
      expect(pngIndex).toBeGreaterThan(webpIndex);
    });
    const cleanIndex = loadedImageSources.findIndex((source) => source.includes("/pets/agent-pet-neko/spritesheet-clean.png"));
    const webpIndex = loadedImageSources.findIndex((source) => source.includes("/pets/agent-pet-neko/spritesheet.webp"));
    const pngIndex = loadedImageSources.findIndex(
      (source, index) => index > webpIndex && source.includes("/pets/agent-pet-neko/spritesheet.png"),
    );
    expect(cleanIndex).toBeGreaterThanOrEqual(0);
    expect(webpIndex).toBeGreaterThan(cleanIndex);
    expect(pngIndex).toBeGreaterThan(webpIndex);
  });

  it("cleans bright magenta chroma pixels connected to the atlas background", async () => {
    readableCanvasEnabled = true;

    renderStage();

    await waitFor(() => expect(putImageDataMock).toHaveBeenCalled());
    const magentaOffset = (manifest.layout.width + 1) * 4;
    expect(latestCleanedAtlasData?.[magentaOffset + 3]).toBe(0);
  });
});
