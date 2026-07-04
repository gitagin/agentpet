import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties } from "react";

import { useVersionedPublicAsset } from "../../hooks/useVersionedPublicAsset";

const HALFBODY_STATE_PATH = "/sprite-pet/state.json";
const BLINK_SEQUENCE: Array<[HalfbodyBlinkFrame, number]> = [
  ["open", 0],
  ["half", 55],
  ["closed", 125],
  ["half", 205],
  ["open", 280],
];

const visemeKeys = ["closed", "AI", "E", "O", "MBP", "FV", "smile"] as const;
const blinkFrameKeys = ["open", "half", "closed"] as const;

export type HalfbodyViseme = (typeof visemeKeys)[number];
type HalfbodyBlinkFrame = (typeof blinkFrameKeys)[number];

export type HalfbodyPhonemeCue = {
  phoneme?: string;
  phone?: string;
  label?: string;
  value?: string;
  viseme?: string;
  startMs?: number;
  timeMs?: number;
  atMs?: number;
  offsetMs?: number;
  startSeconds?: number;
  timeSeconds?: number;
  durationMs?: number;
};

export type HalfbodyPetPortraitHandle = {
  setHalfbodyViseme: (viseme: HalfbodyViseme | string) => void;
  speak: (_audioBuffer?: AudioBuffer | ArrayBuffer | null, phonemeTimeline?: HalfbodyPhonemeCue[] | null) => void;
};

type HalfbodyPetPortraitProps = {
  active?: boolean;
  ariaLabel?: string;
  className?: string;
};

type HalfbodyConfig = {
  window: "home";
  draggable: boolean;
  type: "layered-portrait";
  base: string;
  breathing: {
    enabled: boolean;
    durationMs: number;
    scale: [number, number];
    translateY: [number, number];
  };
  blink: {
    triggerIntervalMs: [number, number];
    frames: Record<HalfbodyBlinkFrame, string>;
  };
  visemes: Record<HalfbodyViseme, string>;
};

const DEFAULT_HALFBODY_CONFIG: HalfbodyConfig = {
  window: "home",
  draggable: false,
  type: "layered-portrait",
  base: "sprite-pet/halfbody/base.png",
  breathing: {
    enabled: true,
    durationMs: 3200,
    scale: [1, 1.006],
    translateY: [0, -2],
  },
  blink: {
    triggerIntervalMs: [2500, 6000],
    frames: {
      open: "sprite-pet/halfbody/blink/open.png",
      half: "sprite-pet/halfbody/blink/half.png",
      closed: "sprite-pet/halfbody/blink/closed.png",
    },
  },
  visemes: {
    closed: "sprite-pet/halfbody/viseme/closed.png",
    AI: "sprite-pet/halfbody/viseme/AI.png",
    E: "sprite-pet/halfbody/viseme/E.png",
    O: "sprite-pet/halfbody/viseme/O.png",
    MBP: "sprite-pet/halfbody/viseme/MBP.png",
    FV: "sprite-pet/halfbody/viseme/FV.png",
    smile: "sprite-pet/halfbody/viseme/smile.png",
  },
};

function resolvePublicAssetPath(path: string) {
  const trimmed = path.trim();
  if (!trimmed) {
    return "";
  }
  if (/^(https?:|data:|blob:)/i.test(trimmed) || trimmed.startsWith("/")) {
    return trimmed;
  }
  return `/${trimmed}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readString(record: Record<string, unknown> | undefined, key: string, fallback: string) {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value : fallback;
}

function readBoolean(record: Record<string, unknown> | undefined, key: string, fallback: boolean) {
  const value = record?.[key];
  return typeof value === "boolean" ? value : fallback;
}

function readNumber(record: Record<string, unknown> | undefined, key: string, fallback: number) {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function readNumberPair(value: unknown, fallback: [number, number]): [number, number] {
  if (!Array.isArray(value) || value.length < 2) {
    return fallback;
  }
  const first = typeof value[0] === "number" && Number.isFinite(value[0]) ? value[0] : fallback[0];
  const second = typeof value[1] === "number" && Number.isFinite(value[1]) ? value[1] : fallback[1];
  return [first, second];
}

function readPathRecord<Key extends string>(
  record: Record<string, unknown> | undefined,
  keys: readonly Key[],
  fallback: Record<Key, string>,
) {
  return keys.reduce<Record<Key, string>>((next, key) => {
    next[key] = readString(record, key, fallback[key]);
    return next;
  }, { ...fallback });
}

function normalizeHalfbodyConfig(manifest: unknown): HalfbodyConfig {
  const root = isRecord(manifest) ? manifest : undefined;
  const characters = isRecord(root?.characters) ? root.characters : undefined;
  const halfbody = isRecord(characters?.halfbody) ? characters.halfbody : undefined;
  const breathing = isRecord(halfbody?.breathing) ? halfbody.breathing : undefined;
  const blink = isRecord(halfbody?.blink) ? halfbody.blink : undefined;
  const blinkFrames = isRecord(blink?.frames) ? blink.frames : undefined;
  const visemes = isRecord(halfbody?.visemes) ? halfbody.visemes : undefined;

  return {
    window: "home",
    draggable: false,
    type: "layered-portrait",
    base: readString(halfbody, "base", DEFAULT_HALFBODY_CONFIG.base),
    breathing: {
      enabled: readBoolean(breathing, "enabled", DEFAULT_HALFBODY_CONFIG.breathing.enabled),
      durationMs: readNumber(breathing, "durationMs", DEFAULT_HALFBODY_CONFIG.breathing.durationMs),
      scale: readNumberPair(breathing?.scale, DEFAULT_HALFBODY_CONFIG.breathing.scale),
      translateY: readNumberPair(breathing?.translateY, DEFAULT_HALFBODY_CONFIG.breathing.translateY),
    },
    blink: {
      triggerIntervalMs: readNumberPair(blink?.triggerIntervalMs, DEFAULT_HALFBODY_CONFIG.blink.triggerIntervalMs),
      frames: readPathRecord(blinkFrames, blinkFrameKeys, DEFAULT_HALFBODY_CONFIG.blink.frames),
    },
    visemes: readPathRecord(visemes, visemeKeys, DEFAULT_HALFBODY_CONFIG.visemes),
  };
}

function randomBetween([min, max]: [number, number]) {
  const safeMin = Math.max(0, Math.min(min, max));
  const safeMax = Math.max(safeMin, Math.max(min, max));
  return safeMin + Math.random() * (safeMax - safeMin);
}

function isHalfbodyViseme(value: string): value is HalfbodyViseme {
  return visemeKeys.includes(value as HalfbodyViseme);
}

function normalizeViseme(value: string): HalfbodyViseme | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const directMatch = visemeKeys.find((key) => key.toLowerCase() === trimmed.toLowerCase());
  return directMatch ?? null;
}

function mapPhonemeToViseme(phoneme: string): HalfbodyViseme {
  const normalized = phoneme.trim().toLowerCase();
  if (!normalized || /^(silence|rest|pause|pau|sp|sil)$/.test(normalized)) {
    return "closed";
  }
  if (/^[ai]/.test(normalized)) {
    return "AI";
  }
  if (/^e/.test(normalized)) {
    return "AI";
  }
  if (/^[ou]/.test(normalized)) {
    return "O";
  }
  if (/^[mbp]/.test(normalized)) {
    return "closed";
  }
  if (/^[fv]/.test(normalized)) {
    return "closed";
  }
  return "closed";
}

function cueStartMs(cue: HalfbodyPhonemeCue) {
  if (typeof cue.startMs === "number" && Number.isFinite(cue.startMs)) {
    return cue.startMs;
  }
  if (typeof cue.timeMs === "number" && Number.isFinite(cue.timeMs)) {
    return cue.timeMs;
  }
  if (typeof cue.atMs === "number" && Number.isFinite(cue.atMs)) {
    return cue.atMs;
  }
  if (typeof cue.offsetMs === "number" && Number.isFinite(cue.offsetMs)) {
    return cue.offsetMs;
  }
  if (typeof cue.startSeconds === "number" && Number.isFinite(cue.startSeconds)) {
    return cue.startSeconds * 1000;
  }
  if (typeof cue.timeSeconds === "number" && Number.isFinite(cue.timeSeconds)) {
    return cue.timeSeconds * 1000;
  }
  return null;
}

function cueViseme(cue: HalfbodyPhonemeCue): HalfbodyViseme {
  const direct = cue.viseme ? normalizeViseme(cue.viseme) : null;
  if (direct) {
    return direct;
  }
  return mapPhonemeToViseme(cue.phoneme ?? cue.phone ?? cue.label ?? cue.value ?? "");
}

function PortraitLayer({
  assetPath,
  className,
  failed,
  onError,
}: {
  assetPath: string;
  className: string;
  failed: boolean;
  onError: (path: string) => void;
}) {
  const publicPath = resolvePublicAssetPath(assetPath);
  const src = useVersionedPublicAsset(publicPath || "/sprite-pet/halfbody/missing.png");

  if (!publicPath || failed) {
    return null;
  }

  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      draggable={false}
      className={className}
      onError={() => onError(assetPath)}
    />
  );
}

export const HalfbodyPetPortrait = forwardRef<HalfbodyPetPortraitHandle, HalfbodyPetPortraitProps>(
  function HalfbodyPetPortrait({ active = true, ariaLabel = "Agent Pet Neko halfbody portrait", className }, ref) {
    const [config, setConfig] = useState<HalfbodyConfig>(DEFAULT_HALFBODY_CONFIG);
    const [blinkFrame, setBlinkFrame] = useState<HalfbodyBlinkFrame>("open");
    const [viseme, setViseme] = useState<HalfbodyViseme>("closed");
    const [failedAssetPaths, setFailedAssetPaths] = useState<Set<string>>(() => new Set());
    const speechTimersRef = useRef<Set<number>>(new Set());

    useEffect(() => {
      let cancelled = false;

      if (typeof fetch !== "function") {
        return () => {
          cancelled = true;
        };
      }

      void fetch(HALFBODY_STATE_PATH, { cache: "no-store" })
        .then((response) => (response.ok ? response.json() : null))
        .then((manifest) => {
          if (!cancelled && manifest) {
            setConfig(normalizeHalfbodyConfig(manifest));
            setFailedAssetPaths(new Set());
          }
        })
        .catch(() => {
          if (!cancelled) {
            setConfig(DEFAULT_HALFBODY_CONFIG);
          }
        });

      return () => {
        cancelled = true;
      };
    }, []);

    const clearSpeechTimers = useCallback(() => {
      speechTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
      speechTimersRef.current.clear();
    }, []);

    useEffect(() => clearSpeechTimers, [clearSpeechTimers]);

    const setHalfbodyViseme = useCallback((nextViseme: HalfbodyViseme | string) => {
      const normalized = normalizeViseme(nextViseme);
      setViseme(normalized ?? "closed");
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        setHalfbodyViseme,
        speak: (_audioBuffer?: AudioBuffer | ArrayBuffer | null, phonemeTimeline?: HalfbodyPhonemeCue[] | null) => {
          clearSpeechTimers();
          if (!phonemeTimeline?.length) {
            setViseme("closed");
            return;
          }

          const cues = phonemeTimeline
            .map((cue) => {
              const startMs = cueStartMs(cue);
              if (startMs === null) {
                return null;
              }
              return {
                startMs: Math.max(0, startMs),
                durationMs:
                  typeof cue.durationMs === "number" && Number.isFinite(cue.durationMs)
                    ? Math.max(0, cue.durationMs)
                    : 140,
                viseme: cueViseme(cue),
              };
            })
            .filter((cue): cue is { startMs: number; durationMs: number; viseme: HalfbodyViseme } => cue !== null)
            .sort((left, right) => left.startMs - right.startMs);

          if (!cues.length) {
            setViseme("closed");
            return;
          }

          cues.forEach((cue) => {
            let timerId = 0;
            timerId = window.setTimeout(() => {
              speechTimersRef.current.delete(timerId);
              setViseme(cue.viseme);
            }, cue.startMs);
            speechTimersRef.current.add(timerId);
          });

          const lastCue = cues[cues.length - 1];
          let closeTimerId = 0;
          closeTimerId = window.setTimeout(() => {
            speechTimersRef.current.delete(closeTimerId);
            setViseme("closed");
          }, lastCue.startMs + lastCue.durationMs);
          speechTimersRef.current.add(closeTimerId);
        },
      }),
      [clearSpeechTimers, setHalfbodyViseme],
    );

    useEffect(() => {
      const timers = new Set<number>();
      let cancelled = false;

      const setTimer = (callback: () => void, delayMs: number) => {
        let timerId = 0;
        timerId = window.setTimeout(() => {
          timers.delete(timerId);
          callback();
        }, delayMs);
        timers.add(timerId);
      };

      const scheduleBlink = () => {
        if (cancelled) {
          return;
        }
        setTimer(() => {
          if (cancelled) {
            return;
          }
          BLINK_SEQUENCE.forEach(([frame, offsetMs]) => {
            setTimer(() => {
              if (!cancelled) {
                setBlinkFrame(frame);
              }
            }, offsetMs);
          });
          setTimer(scheduleBlink, BLINK_SEQUENCE[BLINK_SEQUENCE.length - 1][1] + 1);
        }, randomBetween(config.blink.triggerIntervalMs));
      };

      if (active) {
        scheduleBlink();
      } else {
        setBlinkFrame("open");
      }

      return () => {
        cancelled = true;
        timers.forEach((timerId) => window.clearTimeout(timerId));
        timers.clear();
      };
    }, [active, config.blink.triggerIntervalMs]);

    const markAssetFailed = useCallback((assetPath: string) => {
      setFailedAssetPaths((current) => {
        if (current.has(assetPath)) {
          return current;
        }
        const next = new Set(current);
        next.add(assetPath);
        return next;
      });
    }, []);

    const breathingStyle = useMemo(() => {
      const style = {
        "--halfbody-breathe-duration": `${Math.max(0, config.breathing.durationMs)}ms`,
        "--halfbody-breathe-scale-from": `${config.breathing.scale[0]}`,
        "--halfbody-breathe-scale-to": `${config.breathing.scale[1]}`,
        "--halfbody-breathe-y-from": `${config.breathing.translateY[0]}px`,
        "--halfbody-breathe-y-to": `${config.breathing.translateY[1]}px`,
        animationPlayState: active ? "running" : "paused",
      } as CSSProperties;
      return style;
    }, [active, config.breathing.durationMs, config.breathing.scale, config.breathing.translateY]);

    const portraitClassName = className ? `halfbody-pet-portrait ${className}` : "halfbody-pet-portrait";
    const frameClassName = config.breathing.enabled
      ? "halfbody-pet-portrait-frame is-breathing"
      : "halfbody-pet-portrait-frame";
    const blinkPath = config.blink.frames[blinkFrame];
    const visemePath = isHalfbodyViseme(viseme) ? config.visemes[viseme] : "";

    return (
      <figure
        className={portraitClassName}
        aria-label={ariaLabel}
        data-portrait-type={config.type}
        data-window-scope={config.window}
        data-draggable={config.draggable ? "true" : "false"}
      >
        <div className={frameClassName} style={breathingStyle}>
          <PortraitLayer
            assetPath={config.base}
            className="halfbody-pet-portrait-layer halfbody-pet-portrait-base"
            failed={failedAssetPaths.has(config.base)}
            onError={markAssetFailed}
          />
          <PortraitLayer
            assetPath={blinkPath}
            className="halfbody-pet-portrait-layer halfbody-pet-portrait-overlay halfbody-pet-portrait-blink"
            failed={failedAssetPaths.has(blinkPath)}
            onError={markAssetFailed}
          />
          <PortraitLayer
            assetPath={visemePath}
            className="halfbody-pet-portrait-layer halfbody-pet-portrait-overlay halfbody-pet-portrait-viseme"
            failed={failedAssetPaths.has(visemePath)}
            onError={markAssetFailed}
          />
        </div>
      </figure>
    );
  },
);
