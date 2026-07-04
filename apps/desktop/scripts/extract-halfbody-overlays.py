from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

try:
    import cv2
except ImportError:  # pragma: no cover - local asset helper fallback.
    cv2 = None


ROOT = Path(__file__).resolve().parents[3]
HALFBODY_DIR = ROOT / "apps" / "desktop" / "public" / "sprite-pet" / "halfbody"
WORK_DIR = HALFBODY_DIR / "work"
BLINK_DIR = HALFBODY_DIR / "blink"
VISEME_DIR = HALFBODY_DIR / "viseme"
PREVIEW_DIR = ROOT / "output" / "halfbody-overlays"

BASE_PATH = HALFBODY_DIR / "base.png"

OVERLAY_SPECS = [
    {
        "name": "blink-closed",
        "source": WORK_DIR / "blink_closed_full.png",
        "target": BLINK_DIR / "closed.png",
        "mask": "eyes",
        "threshold": 8,
        "expand": 1,
        "blur": 0.8,
        "crop": (560, 285, 890, 470),
    },
    {
        "name": "viseme-AI",
        "source": WORK_DIR / "viseme_AI_full.png",
        "target": VISEME_DIR / "AI.png",
        "mask": "mouth",
        "threshold": 8,
        "expand": 1,
        "blur": 0.65,
        "crop": (665, 405, 805, 500),
    },
    {
        "name": "viseme-O",
        "source": WORK_DIR / "viseme_O_full.png",
        "target": VISEME_DIR / "O.png",
        "mask": "mouth",
        "threshold": 8,
        "expand": 1,
        "blur": 0.65,
        "crop": (665, 405, 805, 500),
    },
]

PLACEHOLDERS = [
    BLINK_DIR / "open.png",
    BLINK_DIR / "half.png",
    VISEME_DIR / "closed.png",
    VISEME_DIR / "E.png",
    VISEME_DIR / "MBP.png",
    VISEME_DIR / "FV.png",
    VISEME_DIR / "smile.png",
]


def require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing required image: {path}")


def normalize_to_base_size(image: Image.Image, base: Image.Image) -> Image.Image:
    """Return an RGB image on the base canvas without scaling facial pixels."""
    image = image.convert("RGB")
    if image.size == base.size:
        return image

    canvas = base.copy()
    width = min(image.width, base.width)
    height = min(image.height, base.height)
    canvas.paste(image.crop((0, 0, width, height)), (0, 0))
    return canvas


def draw_polygon(mask: Image.Image, points: list[tuple[int, int]], fill: int) -> None:
    ImageDraw.Draw(mask).polygon(points, fill=fill)


def make_mask(kind: str, size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    if kind == "eyes":
        # Locked to the original left/right eye regions in base.png.
        draw_polygon(
            mask,
            [(610, 370), (632, 352), (680, 356), (707, 382), (702, 417), (646, 427), (611, 410)],
            255,
        )
        draw_polygon(
            mask,
            [(722, 333), (754, 315), (807, 323), (837, 349), (827, 384), (770, 397), (724, 373)],
            255,
        )
        return mask.filter(ImageFilter.GaussianBlur(1.4))

    if kind == "mouth":
        # Locked to the original mouth area, with room for small viseme shapes.
        draw_polygon(
            mask,
            [(706, 430), (727, 420), (760, 426), (779, 444), (774, 466), (733, 477), (702, 462)],
            255,
        )
        return mask.filter(ImageFilter.GaussianBlur(1.1))

    raise ValueError(f"Unknown mask kind: {kind}")


def alpha_from_bool(mask: np.ndarray, *, expand: int, blur: float, clip_mask: Image.Image | None = None) -> Image.Image:
    raw_alpha = np.where(mask, 255, 0).astype(np.uint8)
    alpha = Image.fromarray(raw_alpha, mode="L")

    if expand > 0:
        alpha = alpha.filter(ImageFilter.MaxFilter(expand * 2 + 1))
    if blur > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(blur))

    if clip_mask is not None:
        alpha = ImageChops.multiply(alpha, clip_mask)
    return alpha


def inpaint_base_layer(base: Image.Image, alpha: Image.Image, *, radius: int) -> Image.Image:
    hard_mask = np.asarray(alpha.point(lambda value: 255 if value > 8 else 0), dtype=np.uint8)

    if cv2 is not None:
        repaired_np = cv2.inpaint(np.asarray(base), hard_mask, radius, cv2.INPAINT_TELEA)
        repaired = Image.fromarray(repaired_np, mode="RGB")
    else:
        repaired = base.filter(ImageFilter.GaussianBlur(radius))

    overlay = repaired.convert("RGBA")
    overlay.putalpha(alpha)
    return overlay


def source_layer(source: Image.Image, alpha: Image.Image) -> Image.Image:
    overlay = source.convert("RGBA")
    overlay.putalpha(alpha)
    return overlay


def color_matched_source_layer(base: Image.Image, source: Image.Image, alpha: Image.Image) -> Image.Image:
    base_np = np.asarray(base, dtype=np.int16)
    source_np = np.asarray(source, dtype=np.int16)

    core = np.asarray(alpha) > 8
    expanded = np.asarray(alpha.filter(ImageFilter.MaxFilter(81))) > 0
    ring = expanded & ~core

    diff = base_np - source_np
    stable = ring & (np.max(np.abs(diff), axis=2) < 70)
    if int(np.count_nonzero(stable)) < 200:
        stable = ring

    if int(np.count_nonzero(stable)) > 0:
        delta = np.median(diff[stable], axis=0)
    else:
        delta = np.array([0, 0, 0], dtype=np.float32)
    delta = np.clip(delta, -36, 36)

    corrected_np = np.clip(source_np + delta.reshape(1, 1, 3), 0, 255).astype(np.uint8)
    overlay = Image.fromarray(corrected_np, mode="RGB").convert("RGBA")
    overlay.putalpha(alpha)
    return overlay


def make_eye_repair_alpha(base_size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", base_size, 0)
    draw_polygon(
        mask,
        [(615, 381), (637, 366), (676, 369), (699, 390), (696, 411), (661, 420), (622, 410), (607, 395)],
        255,
    )
    draw_polygon(
        mask,
        [(728, 341), (757, 326), (801, 332), (828, 353), (821, 374), (782, 390), (741, 378), (719, 358)],
        255,
    )
    return mask.filter(ImageFilter.GaussianBlur(1.4))


def make_mouth_repair_alpha(base_size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", base_size, 0)
    draw_polygon(
        mask,
        [(716, 437), (736, 432), (762, 438), (770, 452), (758, 463), (729, 464), (710, 453)],
        255,
    )
    return mask.filter(ImageFilter.GaussianBlur(1.0))


def extract_eye_overlay(base: Image.Image, source: Image.Image, spec: dict[str, object]) -> Image.Image:
    del spec
    alpha = make_mask("eyes", base.size)
    return color_matched_source_layer(base, source, alpha)


def extract_mouth_overlay(base: Image.Image, source: Image.Image, spec: dict[str, object]) -> Image.Image:
    del spec
    alpha = make_mask("mouth", base.size)
    return color_matched_source_layer(base, source, alpha)


def extract_overlay(base: Image.Image, spec: dict[str, object]) -> Image.Image:
    source_path = spec["source"]
    if not isinstance(source_path, Path):
        raise TypeError("source must be a Path")

    require_file(source_path)
    source_raw = Image.open(source_path)
    source = normalize_to_base_size(source_raw, base)

    if spec["mask"] == "eyes":
        return extract_eye_overlay(base, source, spec)
    if spec["mask"] == "mouth":
        return extract_mouth_overlay(base, source, spec)
    raise ValueError(f"Unknown mask kind: {spec['mask']}")


def save_transparent_placeholder(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (0, 0, 0, 0)).save(path)


def save_composite_preview(base: Image.Image, overlay: Image.Image, spec: dict[str, object]) -> None:
    name = str(spec["name"])
    crop = spec["crop"]
    if not isinstance(crop, tuple):
        raise TypeError("crop must be a tuple")

    composite = base.convert("RGBA")
    composite.alpha_composite(overlay)
    composite.convert("RGB").save(PREVIEW_DIR / f"{name}-composite.png")
    composite.crop(crop).convert("RGB").save(PREVIEW_DIR / f"{name}-crop.png")

    overlay_alpha = overlay.getchannel("A")
    alpha_bbox = overlay_alpha.getbbox()
    if alpha_bbox:
        padded = (
            max(0, alpha_bbox[0] - 24),
            max(0, alpha_bbox[1] - 24),
            min(base.width, alpha_bbox[2] + 24),
            min(base.height, alpha_bbox[3] + 24),
        )
        composite.crop(padded).convert("RGB").save(PREVIEW_DIR / f"{name}-tight-crop.png")


def main() -> None:
    require_file(BASE_PATH)
    for spec in OVERLAY_SPECS:
        source = spec["source"]
        if isinstance(source, Path):
            require_file(source)

    base = Image.open(BASE_PATH).convert("RGB")
    BLINK_DIR.mkdir(parents=True, exist_ok=True)
    VISEME_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    print(f"base={BASE_PATH} size={base.size} mode={base.mode}")

    for path in PLACEHOLDERS:
        save_transparent_placeholder(path, base.size)
        print(f"placeholder={path} size={base.size} mode=RGBA alpha_bbox=None")

    for spec in OVERLAY_SPECS:
        overlay = extract_overlay(base, spec)
        target = spec["target"]
        if not isinstance(target, Path):
            raise TypeError("target must be a Path")

        target.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(target)
        save_composite_preview(base, overlay, spec)

        alpha = overlay.getchannel("A")
        bbox = alpha.getbbox()
        alpha_pixels = int(np.count_nonzero(np.asarray(alpha)))
        source = spec["source"]
        if not isinstance(source, Path):
            raise TypeError("source must be a Path")
        source_size = Image.open(source).size
        print(
            f"overlay={target} source_size={source_size} output_size={overlay.size} "
            f"mode={overlay.mode} alpha_bbox={bbox} alpha_pixels={alpha_pixels}"
        )

    print(f"previews={PREVIEW_DIR}")


if __name__ == "__main__":
    main()
