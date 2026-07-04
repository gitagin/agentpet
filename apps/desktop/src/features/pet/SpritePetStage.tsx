import { useEffect, useMemo, useState } from "react";
import type { MouseEvent, PointerEvent, RefObject } from "react";
import type { Live2DStageView } from "../../components/Live2DStage";
import { useVersionedPublicAsset } from "../../hooks/useVersionedPublicAsset";
import {
  getSpritePetAtlasRowKey,
  resolveSpritePetAction,
  type SpritePetAction,
  type SpritePetDragDirection,
  spritePetAtlasRows,
} from "./spritePetState";

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
  stage: Live2DStageView;
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
const petAtlasPath = "/images/pet-codex-actions.png";
const petImagePath = "/images/pet-chibi-clean.png";
const petAtlasCellWidth = 220;
const petAtlasCellHeight = 282;
const petAtlasFrameCount = 8;
const petAtlasRows = new Map(spritePetAtlasRows.map((row, index) => [row.key, { ...row, index }]));

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
  const petAtlasSrc = useVersionedPublicAsset(petAtlasPath);
  const petImageSrc = useVersionedPublicAsset(petImagePath);
  const [atlasImage, setAtlasImage] = useState<HTMLImageElement | null>(null);
  const [fallbackImage, setFallbackImage] = useState<HTMLImageElement | null>(null);
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
      }
    };
    nextImage.src = petAtlasSrc;
    return () => {
      disposed = true;
    };
  }, [petAtlasSrc]);

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

      if (atlasImage) {
        drawSpritePetAtlasFrame({
          action,
          actionTriggerKey,
          atlasImage,
          context,
          dragging,
          layout,
          speaking,
          timestamp,
        });
      } else if (fallbackImage) {
        drawSpritePetFrame({
          action,
          actionTriggerKey,
          context,
          dragging,
          image: fallbackImage,
          layout,
          speaking,
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
  }, [action, actionTriggerKey, active, atlasImage, canvasRef, dragging, fallbackImage, speaking]);

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
          <canvas ref={canvasRef} className="sprite-pet-canvas" width={220} height={282} />
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

function resizeCanvas(canvas: HTMLCanvasElement): CanvasLayout {
  const bounds = canvas.getBoundingClientRect();
  const fallbackWidth = canvas.width || 220;
  const fallbackHeight = canvas.height || 282;
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
  speaking,
  timestamp,
}: {
  action: SpritePetAction;
  actionTriggerKey: string | null;
  atlasImage: HTMLImageElement;
  context: CanvasRenderingContext2D;
  dragging: boolean;
  layout: CanvasLayout;
  speaking: boolean;
  timestamp: number;
}) {
  const row = petAtlasRows.get(getSpritePetAtlasRowKey(action.key)) || petAtlasRows.get("idle");
  const rowIndex = row?.index ?? 0;
  const frameCount = row?.frameCount ?? petAtlasFrameCount;
  const t = timestamp / 1000;
  const seed = hashString(`${action.key}:${actionTriggerKey || ""}`) / 997;
  const atlasRowKey = row?.key || "idle";
  const fps = speaking ? 12 : getSpritePetAtlasFps(atlasRowKey, dragging);
  const frameIndex = Math.floor((t + seed) * fps) % frameCount;
  const sourceX = frameIndex * petAtlasCellWidth;
  const sourceY = rowIndex * petAtlasCellHeight;

  context.save();
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(
    atlasImage,
    sourceX,
    sourceY,
    petAtlasCellWidth,
    petAtlasCellHeight,
    0,
    0,
    layout.width,
    layout.height,
  );
  if (speaking || action.motion.mouth === "talk") {
    drawAtlasSpeechMouth(context, layout, computeSpeechOpen(t, seed));
  }
  context.restore();
}

function getSpritePetAtlasFps(rowKey: string, dragging: boolean): number {
  if (dragging) {
    return 10;
  }
  switch (rowKey) {
    case "idle":
      return 4.8;
    case "waving":
    case "jumping":
      return 7.5;
    case "failed":
      return 4.5;
    case "running-right":
    case "running-left":
      return 9.5;
    case "running":
      return 7;
    case "review":
    case "waiting":
    default:
      return 5.5;
  }
}

function drawAtlasSpeechMouth(context: CanvasRenderingContext2D, layout: CanvasLayout, open: number) {
  const centerX = layout.width * 0.5;
  const centerY = layout.height * 0.455;
  const width = layout.width * (0.022 + open * 0.012);
  const height = layout.height * (0.006 + open * 0.024);
  context.save();
  context.fillStyle = "rgba(48, 18, 30, 0.94)";
  context.beginPath();
  context.ellipse(centerX, centerY, width, height, 0.05, 0, Math.PI * 2);
  context.fill();
  if (open > 0.55) {
    context.fillStyle = "rgba(230, 88, 124, 0.62)";
    context.beginPath();
    context.ellipse(centerX, centerY + height * 0.25, width * 0.55, height * 0.28, 0, 0, Math.PI * 2);
    context.fill();
  }
  context.restore();
}

function drawSpritePetFrame({
  action,
  actionTriggerKey,
  context,
  dragging,
  image,
  layout,
  speaking,
  timestamp,
}: {
  action: SpritePetAction;
  actionTriggerKey: string | null;
  context: CanvasRenderingContext2D;
  dragging: boolean;
  image: HTMLImageElement;
  layout: CanvasLayout;
  speaking: boolean;
  timestamp: number;
}) {
  const t = timestamp / 1000;
  const motion = action.motion;
  const phaseSeed = hashString(`${action.key}:${actionTriggerKey || ""}`) / 997;
  const naturalBob = Math.sin(t * 2.55 + phaseSeed) * motion.bobPx;
  const breathe = Math.sin(t * 1.82 + phaseSeed * 0.7) * motion.breathe;
  const sway = Math.sin(t * 1.32 + phaseSeed) * motion.swayDeg;
  const dragLean = dragging ? Math.sin(t * 7.1) * 0.7 : 0;
  const tilt = degreesToRadians(motion.tiltDeg + sway + dragLean);
  const speechOpen = motion.mouth === "talk" || speaking ? computeSpeechOpen(t, phaseSeed) : 0;
  const blink = computeBlink(t, motion.blinkSeconds, phaseSeed);

  const imageWidth = image.naturalWidth || image.width;
  const imageHeight = image.naturalHeight || image.height;
  const drawScale = Math.min((layout.width * 0.98) / imageWidth, (layout.height * 0.985) / imageHeight);
  const drawWidth = imageWidth * drawScale;
  const drawHeight = imageHeight * drawScale;
  const drawX = (layout.width - drawWidth) / 2;
  const drawY = layout.height - drawHeight - 1;
  const pivotX = layout.width / 2;
  const pivotY = drawY + drawHeight * 0.42;
  const dragOffsetX = dragging ? Math.sin(t * 5.8 + phaseSeed) * 1.2 : 0;

  context.save();
  context.translate(pivotX + dragOffsetX, pivotY + naturalBob);
  context.rotate(tilt);
  context.scale(1 + breathe * 0.18, 1 + breathe);
  const localX = drawX - pivotX;
  const localY = drawY - pivotY;
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(image, localX, localY, drawWidth, drawHeight);

  drawAttachedGlow(context, action, localX, localY, drawWidth, drawHeight, t);
  drawExpressionOverlays(context, action, localX, localY, drawWidth, drawHeight, blink, speechOpen);
  context.restore();
}

function computeSpeechOpen(t: number, seed: number): number {
  const fast = Math.abs(Math.sin(t * 16.2 + seed * 2.1));
  const mid = Math.abs(Math.sin(t * 9.4 + 1.7 + seed));
  const pulse = Math.max(fast * 0.72, mid * 0.48);
  return clamp(0.16 + pulse * 0.84, 0, 1);
}

function computeBlink(t: number, blinkSeconds: number, seed: number): number {
  const cycle = Math.max(2.8, blinkSeconds + (seed % 1.4));
  const phase = (t + seed) % cycle;
  if (phase > 0.16) {
    return 0;
  }
  const progress = phase / 0.16;
  return Math.sin(progress * Math.PI);
}

function drawAttachedGlow(
  context: CanvasRenderingContext2D,
  action: SpritePetAction,
  x: number,
  y: number,
  width: number,
  height: number,
  t: number,
) {
  if (action.motion.glow === "none") {
    return;
  }

  const pendantX = x + width * 0.505;
  const pendantY = y + height * 0.548;
  const pulse = 0.58 + Math.sin(t * 4.2) * 0.18;
  const radius = Math.max(5, width * (action.motion.glow === "warm" ? 0.055 : 0.044));
  const gradient = context.createRadialGradient(pendantX, pendantY, 1, pendantX, pendantY, radius);
  if (action.motion.glow === "warm") {
    gradient.addColorStop(0, `rgba(255, 188, 118, ${0.34 * pulse})`);
    gradient.addColorStop(1, "rgba(255, 188, 118, 0)");
  } else {
    gradient.addColorStop(0, `rgba(84, 231, 255, ${0.42 * pulse})`);
    gradient.addColorStop(1, "rgba(84, 231, 255, 0)");
  }
  context.save();
  context.globalCompositeOperation = "lighter";
  context.fillStyle = gradient;
  context.beginPath();
  context.arc(pendantX, pendantY, radius, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

function drawExpressionOverlays(
  context: CanvasRenderingContext2D,
  action: SpritePetAction,
  x: number,
  y: number,
  width: number,
  height: number,
  blink: number,
  speechOpen: number,
) {
  const leftEye = rectFromSource(x, y, width, height, 0.405, 0.386, 0.105, 0.045);
  const rightEye = rectFromSource(x, y, width, height, 0.566, 0.372, 0.104, 0.045);
  const mouth = rectFromSource(x, y, width, height, 0.507, 0.392, 0.054, 0.022);

  if (action.motion.expression === "bright" || action.motion.expression === "soft") {
    drawCheek(context, x + width * 0.378, y + height * 0.412, width * 0.028, action.motion.expression);
    drawCheek(context, x + width * 0.63, y + height * 0.399, width * 0.026, action.motion.expression);
  }

  if (action.motion.expression === "worried" || action.motion.expression === "careful") {
    drawBrow(context, leftEye, -0.5);
    drawBrow(context, rightEye, 0.5);
  }

  if (blink > 0) {
    drawBlink(context, leftEye, blink);
    drawBlink(context, rightEye, blink);
  }

  if (speechOpen > 0.04) {
    drawMouth(context, mouth, speechOpen);
  }
}

function rectFromSource(
  x: number,
  y: number,
  width: number,
  height: number,
  centerX: number,
  centerY: number,
  rectWidth: number,
  rectHeight: number,
) {
  return {
    x: x + width * (centerX - rectWidth / 2),
    y: y + height * (centerY - rectHeight / 2),
    width: width * rectWidth,
    height: height * rectHeight,
  };
}

function drawCheek(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  expression: "bright" | "soft",
) {
  context.save();
  context.globalAlpha = expression === "bright" ? 0.22 : 0.14;
  context.fillStyle = "#f4829e";
  context.beginPath();
  context.ellipse(x, y, radius, radius * 0.48, -0.12, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

function drawBrow(context: CanvasRenderingContext2D, rect: { x: number; y: number; width: number; height: number }, slope: number) {
  context.save();
  context.strokeStyle = "rgba(42, 22, 28, 0.62)";
  context.lineWidth = Math.max(1, rect.width * 0.08);
  context.lineCap = "round";
  context.beginPath();
  context.moveTo(rect.x + rect.width * 0.18, rect.y - rect.height * (0.52 + slope * 0.16));
  context.lineTo(rect.x + rect.width * 0.82, rect.y - rect.height * (0.18 - slope * 0.16));
  context.stroke();
  context.restore();
}

function drawBlink(context: CanvasRenderingContext2D, rect: { x: number; y: number; width: number; height: number }, amount: number) {
  const coverHeight = rect.height * clamp(amount * 1.18, 0, 1);
  context.save();
  context.fillStyle = "rgba(246, 205, 199, 0.9)";
  context.beginPath();
  context.ellipse(
    rect.x + rect.width / 2,
    rect.y + rect.height * 0.52,
    rect.width * 0.53,
    Math.max(1, coverHeight * 0.58),
    -0.08,
    0,
    Math.PI * 2,
  );
  context.fill();
  context.strokeStyle = "rgba(51, 24, 31, 0.88)";
  context.lineWidth = Math.max(1, rect.width * 0.06);
  context.lineCap = "round";
  context.beginPath();
  context.moveTo(rect.x + rect.width * 0.14, rect.y + rect.height * 0.58);
  context.quadraticCurveTo(
    rect.x + rect.width * 0.5,
    rect.y + rect.height * (0.74 + amount * 0.08),
    rect.x + rect.width * 0.86,
    rect.y + rect.height * 0.56,
  );
  context.stroke();
  context.restore();
}

function drawMouth(context: CanvasRenderingContext2D, rect: { x: number; y: number; width: number; height: number }, open: number) {
  const mouthHeight = Math.max(1.4, rect.height * (0.35 + open * 1.8));
  context.save();
  context.fillStyle = "rgba(55, 24, 32, 0.92)";
  context.beginPath();
  context.ellipse(
    rect.x + rect.width / 2,
    rect.y + rect.height * 0.5,
    rect.width * (0.28 + open * 0.22),
    mouthHeight * 0.5,
    0.05,
    0,
    Math.PI * 2,
  );
  context.fill();
  if (open > 0.5) {
    context.fillStyle = "rgba(233, 105, 132, 0.58)";
    context.beginPath();
    context.ellipse(
      rect.x + rect.width / 2,
      rect.y + rect.height * 0.67,
      rect.width * 0.2,
      mouthHeight * 0.2,
      0,
      0,
      Math.PI * 2,
    );
    context.fill();
  }
  context.restore();
}

function hashString(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) % 997;
  }
  return hash;
}

function degreesToRadians(value: number): number {
  return (value * Math.PI) / 180;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
