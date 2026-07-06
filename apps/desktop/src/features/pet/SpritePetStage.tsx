import { useEffect, useMemo, useState } from "react";
import type { MouseEvent, PointerEvent, RefObject } from "react";
import { useVersionedPublicAsset } from "../../hooks/useVersionedPublicAsset";
import type { PetStageView } from "./petStageState";
import {
  getSpritePetAnimationKey,
  resolveSpritePetAction,
  type SpritePetAction,
  type SpritePetDragDirection,
} from "./spritePetState";
import {
  DEFAULT_PET_SPRITE_MANIFEST,
  frameForAnimation,
  normalizePetSpriteManifest,
  PET_SPRITE_MANIFEST_PATH,
  type PetSpriteManifest,
} from "./petSpriteManifest";

export type SpritePetInteractions = {
  onPointerDown: (event: PointerEvent<HTMLElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLElement>) => void;
  onPointerCancel: (event: PointerEvent<HTMLElement>) => void;
  onLostPointerCapture: (event: PointerEvent<HTMLElement>) => void;
  onContextMenu: (event: MouseEvent<HTMLElement>) => void;
  onBubbleContextMenu: (event: MouseEvent<HTMLElement>) => void;
  onDoubleClick: () => void;
};

type SpritePetStageProps = {
  stage: PetStageView;
  canvasRef: RefObject<HTMLCanvasElement>;
  connected: boolean;
  streaming: boolean;
  speaking: boolean;
  inputVisible: boolean;
  shortcutVisible: boolean;
  dragging: boolean;
  dragDirection: SpritePetDragDirection;
  actionKeyOverride?: string | null;
  actionTriggerKey?: string | null;
  active?: boolean;
  petInteractions?: SpritePetInteractions;
};

type CanvasLayout = {
  width: number;
  height: number;
  pixelRatio: number;
};

const maxCanvasPixelRatio = 2;

export function SpritePetStage({
  stage,
  canvasRef,
  connected,
  streaming,
  speaking,
  inputVisible,
  shortcutVisible,
  dragging,
  dragDirection,
  actionKeyOverride = null,
  actionTriggerKey = null,
  active = true,
  petInteractions,
}: SpritePetStageProps) {
  const [manifest, setManifest] = useState<PetSpriteManifest>(DEFAULT_PET_SPRITE_MANIFEST);
  const [atlasSourcePath, setAtlasSourcePath] = useState(DEFAULT_PET_SPRITE_MANIFEST.spritesheetCleanPath);
  const petAtlasSrc = useVersionedPublicAsset(atlasSourcePath);
  const petImageSrc = useVersionedPublicAsset(manifest.fallbackPngPath);
  const [atlasImage, setAtlasImage] = useState<HTMLImageElement | null>(null);
  const [fallbackImage, setFallbackImage] = useState<HTMLImageElement | null>(null);
  const [cleanedAtlasImage, setCleanedAtlasImage] = useState<HTMLCanvasElement | null>(null);
  const [cleanedFallbackImage, setCleanedFallbackImage] = useState<HTMLCanvasElement | null>(null);
  useEffect(() => {
    let disposed = false;

    if (typeof fetch !== "function") {
      return () => {
        disposed = true;
      };
    }

    void fetch(PET_SPRITE_MANIFEST_PATH, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((rawManifest) => {
        if (disposed) {
          return;
        }
        const nextManifest = normalizePetSpriteManifest(rawManifest, PET_SPRITE_MANIFEST_PATH);
        setManifest(nextManifest);
        setAtlasSourcePath(nextManifest.spritesheetCleanPath);
      })
      .catch(() => {
        if (!disposed) {
          setManifest(DEFAULT_PET_SPRITE_MANIFEST);
          setAtlasSourcePath(DEFAULT_PET_SPRITE_MANIFEST.spritesheetCleanPath);
        }
      });

    return () => {
      disposed = true;
    };
  }, []);

  const action = useMemo(
    () =>
      resolveSpritePetAction({
        stage,
        connected,
        streaming,
        speaking,
        inputVisible,
        shortcutVisible,
        dragging,
        dragDirection,
        actionKeyOverride,
      }),
    [
      actionKeyOverride,
      connected,
      dragDirection,
      dragging,
      inputVisible,
      shortcutVisible,
      speaking,
      stage,
      streaming,
    ],
  );

  useEffect(() => {
    let disposed = false;
    const nextImage = new Image();
    nextImage.decoding = "async";
    nextImage.onload = () => {
      if (!disposed) {
        setAtlasImage(nextImage);
      }
    };
    nextImage.onerror = () => {
      if (!disposed) {
        setAtlasImage(null);
        const nextPath = getNextAtlasFallbackPath(atlasSourcePath, manifest);
        if (nextPath) {
          setAtlasSourcePath(nextPath);
        }
      }
    };
    nextImage.src = petAtlasSrc;
    return () => {
      disposed = true;
    };
  }, [atlasSourcePath, manifest, petAtlasSrc]);

  useEffect(() => {
    let disposed = false;
    const nextImage = new Image();
    nextImage.decoding = "async";
    nextImage.onload = () => {
      if (!disposed) {
        setFallbackImage(nextImage);
      }
    };
    nextImage.onerror = () => {
      if (!disposed) {
        setFallbackImage(null);
      }
    };
    nextImage.src = petImageSrc;
    return () => {
      disposed = true;
    };
  }, [petImageSrc]);

  useEffect(() => {
    let disposed = false;
    if (!atlasImage) {
      setCleanedAtlasImage(null);
      return () => {
        disposed = true;
      };
    }

    const cleanedImage = createCleanedSpriteAtlasCanvas(atlasImage, manifest);
    if (!disposed) {
      setCleanedAtlasImage(cleanedImage);
    }

    return () => {
      disposed = true;
    };
  }, [atlasImage, manifest]);

  useEffect(() => {
    let disposed = false;
    if (!fallbackImage) {
      setCleanedFallbackImage(null);
      return () => {
        disposed = true;
      };
    }

    const cleanedImage = createCleanedSpriteAtlasCanvas(fallbackImage, manifest);
    if (!disposed) {
      setCleanedFallbackImage(cleanedImage);
    }

    return () => {
      disposed = true;
    };
  }, [fallbackImage, manifest]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) {
      return;
    }

    let frameId = 0;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;

    const render = (timestamp: number) => {
      const layout = resizeCanvas(canvas);
      context.setTransform(layout.pixelRatio, 0, 0, layout.pixelRatio, 0, 0);
      context.clearRect(0, 0, layout.width, layout.height);

      const currentAtlasImage = cleanedAtlasImage ?? cleanedFallbackImage ?? atlasImage ?? fallbackImage;
      if (currentAtlasImage) {
        drawSpritePetAtlasFrame({
          action,
          actionTriggerKey,
          atlasImage: currentAtlasImage,
          context,
          dragging,
          layout,
          manifest,
          timestamp,
        });
      }

      if (!disposed && active) {
        frameId = window.requestAnimationFrame(render);
      }
    };

    const schedule = () => {
      if (frameId) {
        window.cancelAnimationFrame(frameId);
      }
      frameId = window.requestAnimationFrame(render);
    };

    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(schedule);
      resizeObserver.observe(canvas);
    }

    schedule();

    return () => {
      disposed = true;
      if (frameId) {
        window.cancelAnimationFrame(frameId);
      }
      resizeObserver?.disconnect();
    };
  }, [
    action,
    actionTriggerKey,
    active,
    atlasImage,
    canvasRef,
    cleanedAtlasImage,
    cleanedFallbackImage,
    dragging,
    fallbackImage,
    manifest,
    speaking,
  ]);

  const petModelInteractions = petInteractions
    ? {
        onPointerDown: petInteractions.onPointerDown,
        onPointerMove: petInteractions.onPointerMove,
        onPointerUp: petInteractions.onPointerUp,
        onPointerCancel: petInteractions.onPointerCancel,
        onLostPointerCapture: petInteractions.onLostPointerCapture,
        onContextMenu: petInteractions.onContextMenu,
        onDoubleClick: () => petInteractions.onDoubleClick(),
      }
    : null;
  const petBubbleInteractions = petInteractions
    ? {
        onPointerDown: petInteractions.onPointerDown,
        onPointerMove: petInteractions.onPointerMove,
        onPointerUp: petInteractions.onPointerUp,
        onPointerCancel: petInteractions.onPointerCancel,
        onLostPointerCapture: petInteractions.onLostPointerCapture,
        onContextMenu: petInteractions.onBubbleContextMenu,
      }
    : null;

  return (
    <section
      className={`sprite-pet-panel sprite-pet-${action.key}${speaking ? " sprite-pet-speaking" : ""}`}
      aria-label="桌面 Q 版桌宠"
      data-pet-action-key={action.key}
      data-pet-action-trigger={actionTriggerKey || ""}
      data-pet-speaking={speaking ? "true" : "false"}
    >
      <div className="sprite-pet-stage" role="img" aria-label={`桌宠状态：${action.label}`}>
        <div className="sprite-pet-canvas-host" aria-hidden="true">
          <canvas
            ref={canvasRef}
            className="sprite-pet-canvas"
            width={manifest.cell.width}
            height={manifest.cell.height}
          />
        </div>
        <span className="sprite-pet-status" role="status" aria-live="polite">
          {action.label}，{action.detail}
        </span>
        {petInteractions ? (
          <>
            <div className="pet-hit-region pet-hit-model" aria-label="桌宠角色交互区" {...petModelInteractions} />
            <div className="pet-hit-region pet-hit-bubble" aria-label="桌宠气泡交互区" {...petBubbleInteractions} />
          </>
        ) : null}
      </div>
    </section>
  );
}

function getSpritePetAtlasLoadOrder(manifest: PetSpriteManifest): string[] {
  return [manifest.spritesheetCleanPath, manifest.spritesheetPath, manifest.fallbackPngPath].filter(
    (pathName, index, paths): pathName is string => Boolean(pathName) && paths.indexOf(pathName) === index,
  );
}

function getNextAtlasFallbackPath(currentPath: string, manifest: PetSpriteManifest): string | null {
  const loadOrder = getSpritePetAtlasLoadOrder(manifest);
  const currentIndex = loadOrder.indexOf(currentPath);
  if (currentIndex < 0) {
    return loadOrder[0] ?? null;
  }
  return loadOrder[currentIndex + 1] ?? null;
}

function resizeCanvas(canvas: HTMLCanvasElement): CanvasLayout {
  const bounds = canvas.getBoundingClientRect();
  const fallbackWidth = canvas.width || 192;
  const fallbackHeight = canvas.height || 208;
  const width = Math.max(1, bounds.width || fallbackWidth);
  const height = Math.max(1, bounds.height || fallbackHeight);
  const pixelRatio = Math.min(window.devicePixelRatio || 1, maxCanvasPixelRatio);
  const nextWidth = Math.max(1, Math.round(width * pixelRatio));
  const nextHeight = Math.max(1, Math.round(height * pixelRatio));

  if (canvas.width !== nextWidth) {
    canvas.width = nextWidth;
  }
  if (canvas.height !== nextHeight) {
    canvas.height = nextHeight;
  }
  return { width, height, pixelRatio };
}

function drawSpritePetAtlasFrame({
  action,
  actionTriggerKey,
  atlasImage,
  context,
  dragging,
  layout,
  manifest,
  timestamp,
}: {
  action: SpritePetAction;
  actionTriggerKey: string | null;
  atlasImage: CanvasImageSource;
  context: CanvasRenderingContext2D;
  dragging: boolean;
  layout: CanvasLayout;
  manifest: PetSpriteManifest;
  timestamp: number;
}) {
  const animationKey = getSpritePetAnimationKey(action.key);
  const animation = manifest.animations[animationKey] || manifest.animations.idle;
  const seed = hashString(`${action.key}:${actionTriggerKey || ""}`) / 997;
  const frameIndex = frameForAnimation(animation, dragging ? timestamp * 1.18 : timestamp, seed);
  const column = animation.columns[frameIndex] ?? 0;
  const sourceX = column * manifest.cell.width;
  const sourceY = animation.row * manifest.cell.height;

  context.save();
  context.imageSmoothingEnabled = false;
  context.drawImage(
    atlasImage,
    sourceX,
    sourceY,
    manifest.cell.width,
    manifest.cell.height,
    0,
    0,
    layout.width,
    layout.height,
  );
  context.restore();
}

function createCleanedSpriteAtlasCanvas(image: HTMLImageElement, manifest: PetSpriteManifest): HTMLCanvasElement | null {
  if (typeof document === "undefined") {
    return null;
  }

  const sourceWidth = Math.max(1, Math.round(image.naturalWidth || image.width || manifest.layout.width));
  const sourceHeight = Math.max(1, Math.round(image.naturalHeight || image.height || manifest.layout.height));
  const canvas = document.createElement("canvas");
  canvas.width = sourceWidth;
  canvas.height = sourceHeight;

  const context = canvas.getContext("2d", { alpha: true, willReadFrequently: true });
  if (!context) {
    return null;
  }

  context.clearRect(0, 0, sourceWidth, sourceHeight);
  context.drawImage(image, 0, 0, sourceWidth, sourceHeight);

  if (typeof context.getImageData !== "function" || typeof context.putImageData !== "function") {
    return null;
  }

  try {
    const imageData = context.getImageData(0, 0, sourceWidth, sourceHeight);
    if (!hasChromaKeyPixels(imageData.data)) {
      return canvas;
    }
    cleanSpriteAtlasChromaPixels(imageData.data, sourceWidth, sourceHeight, manifest);
    context.putImageData(imageData, 0, 0);
    return canvas;
  } catch {
    return null;
  }
}

function hasChromaKeyPixels(data: Uint8ClampedArray): boolean {
  for (let offset = 0; offset < data.length; offset += 4) {
    if (readChromaKeyStrength(data, offset) !== null) {
      return true;
    }
  }
  return false;
}

function cleanSpriteAtlasChromaPixels(
  data: Uint8ClampedArray,
  sourceWidth: number,
  sourceHeight: number,
  manifest: PetSpriteManifest,
) {
  const visited = new Uint8Array(sourceWidth * sourceHeight);
  const columns = Math.max(1, Math.floor(sourceWidth / manifest.cell.width));
  const rows = Math.max(1, Math.floor(sourceHeight / manifest.cell.height));

  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      cleanSpriteFrameChromaPixels(data, visited, sourceWidth, sourceHeight, manifest, column, row);
    }
  }

  softenNearTransparentChromaPixels(data, sourceWidth, sourceHeight, manifest, columns, rows);
}

function cleanSpriteFrameChromaPixels(
  data: Uint8ClampedArray,
  visited: Uint8Array,
  sourceWidth: number,
  sourceHeight: number,
  manifest: PetSpriteManifest,
  column: number,
  row: number,
) {
  const frameLeft = column * manifest.cell.width;
  const frameTop = row * manifest.cell.height;
  const frameRight = Math.min(sourceWidth, frameLeft + manifest.cell.width);
  const frameBottom = Math.min(sourceHeight, frameTop + manifest.cell.height);
  if (frameLeft >= frameRight || frameTop >= frameBottom) {
    return;
  }

  const queue = new Int32Array((frameRight - frameLeft) * (frameBottom - frameTop));
  let queueStart = 0;
  let queueEnd = 0;

  const enqueue = (x: number, y: number) => {
    const pixelIndex = y * sourceWidth + x;
    if (visited[pixelIndex] || !isTransparentOrChromaKey(data, pixelIndex * 4)) {
      return;
    }
    visited[pixelIndex] = 1;
    queue[queueEnd] = pixelIndex;
    queueEnd += 1;
  };

  for (let x = frameLeft; x < frameRight; x += 1) {
    enqueue(x, frameTop);
    enqueue(x, frameBottom - 1);
  }
  for (let y = frameTop; y < frameBottom; y += 1) {
    enqueue(frameLeft, y);
    enqueue(frameRight - 1, y);
  }

  while (queueStart < queueEnd) {
    const pixelIndex = queue[queueStart];
    queueStart += 1;
    const offset = pixelIndex * 4;
    const strength = readChromaKeyStrength(data, offset);
    if (strength === "strong") {
      data[offset + 3] = 0;
    } else if (strength === "soft") {
      data[offset + 3] = Math.min(data[offset + 3], 88);
    }

    const y = Math.floor(pixelIndex / sourceWidth);
    const x = pixelIndex - y * sourceWidth;
    if (x > frameLeft) {
      enqueue(x - 1, y);
    }
    if (x < frameRight - 1) {
      enqueue(x + 1, y);
    }
    if (y > frameTop) {
      enqueue(x, y - 1);
    }
    if (y < frameBottom - 1) {
      enqueue(x, y + 1);
    }
  }
}

function softenNearTransparentChromaPixels(
  data: Uint8ClampedArray,
  sourceWidth: number,
  sourceHeight: number,
  manifest: PetSpriteManifest,
  columns: number,
  rows: number,
) {
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const frameLeft = column * manifest.cell.width;
      const frameTop = row * manifest.cell.height;
      const frameRight = Math.min(sourceWidth, frameLeft + manifest.cell.width);
      const frameBottom = Math.min(sourceHeight, frameTop + manifest.cell.height);
      for (let y = frameTop; y < frameBottom; y += 1) {
        for (let x = frameLeft; x < frameRight; x += 1) {
          const offset = (y * sourceWidth + x) * 4;
          const strength = readChromaKeyStrength(data, offset);
          if (!strength) {
            continue;
          }
          const radius = strength === "strong" ? 4 : 2;
          if (!isNearTransparentPixel(data, sourceWidth, x, y, frameLeft, frameTop, frameRight, frameBottom, radius)) {
            continue;
          }
          data[offset + 3] = strength === "strong" ? 0 : Math.min(data[offset + 3], 112);
        }
      }
    }
  }
}

function isNearTransparentPixel(
  data: Uint8ClampedArray,
  sourceWidth: number,
  x: number,
  y: number,
  frameLeft: number,
  frameTop: number,
  frameRight: number,
  frameBottom: number,
  radius: number,
): boolean {
  for (let offsetY = -radius; offsetY <= radius; offsetY += 1) {
    const nextY = y + offsetY;
    if (nextY < frameTop || nextY >= frameBottom) {
      continue;
    }
    for (let offsetX = -radius; offsetX <= radius; offsetX += 1) {
      if (Math.abs(offsetX) + Math.abs(offsetY) > radius) {
        continue;
      }
      const nextX = x + offsetX;
      if (nextX < frameLeft || nextX >= frameRight) {
        continue;
      }
      if (data[(nextY * sourceWidth + nextX) * 4 + 3] <= 4) {
        return true;
      }
    }
  }
  return false;
}

function isTransparentOrChromaKey(data: Uint8ClampedArray, offset: number): boolean {
  return data[offset + 3] <= 4 || readChromaKeyStrength(data, offset) !== null;
}

function readChromaKeyStrength(data: Uint8ClampedArray, offset: number): "strong" | "soft" | null {
  const red = data[offset];
  const green = data[offset + 1];
  const blue = data[offset + 2];
  const alpha = data[offset + 3];
  if (alpha <= 4) {
    return null;
  }

  const redGreenGap = red - green;
  const blueGreenGap = blue - green;
  const magentaLift = (red + blue) / 2 - green;
  const redBlueGap = Math.abs(red - blue);
  if (
    red >= 210 &&
    blue >= 170 &&
    green <= 120 &&
    redGreenGap >= 85 &&
    blueGreenGap >= 45 &&
    magentaLift >= 70 &&
    redBlueGap <= 130
  ) {
    return "strong";
  }

  if (
    red >= 195 &&
    blue >= 145 &&
    green <= 130 &&
    redGreenGap >= 70 &&
    blueGreenGap >= 25 &&
    magentaLift >= 55 &&
    redBlueGap <= 140
  ) {
    return "soft";
  }

  return null;
}

function hashString(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) % 997;
  }
  return hash;
}
