from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Iterable, Sequence, TypedDict

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[3]
MASTER_PATH = ROOT / "apps" / "desktop" / "public" / "images" / "pet-chibi-clean.png"
PACKAGE_DIR = ROOT / "output" / "hatch-pet" / "kuromimi-codex-standard"
PREVIEW_DIR = PACKAGE_DIR / "previews"
QA_JSON_PATH = PACKAGE_DIR / "validation.json"
SPRITESHEET_PATH = PACKAGE_DIR / "spritesheet.webp"
PET_JSON_PATH = PACKAGE_DIR / "pet.json"
CONTACT_SHEET_PATH = PACKAGE_DIR / "contact-sheet.png"

CODEX_PET_DIR = Path.home() / ".codex" / "pets" / "kuromimi-q-chibi"

CELL = 128
MAX_FRAMES = 6
BACKGROUND = (255, 0, 255)
WORK_SCALE = 4

RGBA = tuple[int, int, int, int]
INK: RGBA = (38, 19, 30, 255)
SKIN: RGBA = (255, 211, 204, 255)
BLACK: RGBA = (21, 18, 24, 255)
BLACK_LIGHT: RGBA = (58, 47, 56, 255)
GOLD: RGBA = (204, 148, 92, 255)
CYAN: RGBA = (80, 232, 246, 255)
PINK: RGBA = (220, 92, 135, 255)
MAGENTA_EYE: RGBA = (179, 73, 134, 255)


class AnimationSpec(TypedDict):
    key: str
    row: int
    frames: int
    fps: int


ANIMATIONS: list[AnimationSpec] = [
    {"key": "idle", "row": 0, "frames": 4, "fps": 4},
    {"key": "running-right", "row": 1, "frames": 6, "fps": 6},
    {"key": "running-left", "row": 2, "frames": 6, "fps": 6},
    {"key": "waving", "row": 3, "frames": 5, "fps": 5},
    {"key": "jumping", "row": 4, "frames": 4, "fps": 4},
    {"key": "waiting", "row": 5, "frames": 4, "fps": 4},
    {"key": "failed", "row": 6, "frames": 4, "fps": 4},
]


def ws(value: float) -> int:
    return int(round(value * WORK_SCALE))


def pt(points: Iterable[tuple[float, float]]) -> list[tuple[int, int]]:
    return [(ws(x), ws(y)) for x, y in points]


def box(values: Sequence[float]) -> tuple[int, int, int, int]:
    return (ws(values[0]), ws(values[1]), ws(values[2]), ws(values[3]))


def image_pixels(image: Image.Image):
    flattened_data = getattr(image, "get_flattened_data", None)
    if flattened_data is not None:
        return flattened_data()
    return image.getdata()


def trim_alpha(image: Image.Image, padding: int = 8) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        return image
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    return image.crop((left, top, right, bottom))


def load_master() -> Image.Image:
    if not MASTER_PATH.exists():
        raise FileNotFoundError(f"Missing Q-version master: {MASTER_PATH}")
    master = trim_alpha(Image.open(MASTER_PATH).convert("RGBA"), padding=6)
    if master.getchannel("A").getextrema()[0] == 255:
        raise ValueError("Master image must have alpha so it can be placed on #FF00FF cleanly.")
    return master


def fit_master(master: Image.Image) -> Image.Image:
    fitted = ImageOps.contain(master, (116 * WORK_SCALE, 122 * WORK_SCALE), Image.Resampling.LANCZOS)
    return fitted


def new_cell() -> Image.Image:
    return Image.new("RGBA", (CELL * WORK_SCALE, CELL * WORK_SCALE), (*BACKGROUND, 255))


def transparent_cell() -> Image.Image:
    return Image.new("RGBA", (CELL * WORK_SCALE, CELL * WORK_SCALE), (0, 0, 0, 0))


def make_sprite_layer(
    sprite: Image.Image,
    *,
    mirror: bool = False,
    brightness: float = 1,
) -> Image.Image:
    image = ImageOps.mirror(sprite) if mirror else sprite
    if brightness != 1:
        image = ImageEnhance.Brightness(image).enhance(brightness)
    layer = transparent_cell()
    px = int(round((CELL * WORK_SCALE - image.width) / 2))
    py = int(round(CELL * WORK_SCALE - image.height))
    layer.alpha_composite(image, (px, py))
    return layer


def erase_region(layer: Image.Image, rect: Sequence[float]) -> None:
    scaled = box(rect)
    cutout_alpha = layer.crop(scaled).getchannel("A")
    alpha = layer.getchannel("A")
    alpha.paste(Image.new("L", cutout_alpha.size, 0), scaled, cutout_alpha)
    layer.putalpha(alpha)


def pose_region(
    layer: Image.Image,
    rect: Sequence[float],
    *,
    x: float = 0,
    y: float = 0,
    angle: float = 0,
    scale: float = 1,
    erase: bool = True,
) -> None:
    scaled = box(rect)
    cutout = layer.crop(scaled)
    if erase:
        erase_region(layer, rect)
    if scale != 1:
        size = (
            max(1, int(round(cutout.width * scale))),
            max(1, int(round(cutout.height * scale))),
        )
        cutout = cutout.resize(size, Image.Resampling.LANCZOS)
    if angle:
        cutout = cutout.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    center_x = (scaled[0] + scaled[2]) // 2 + ws(x)
    center_y = (scaled[1] + scaled[3]) // 2 + ws(y)
    px = center_x - cutout.width // 2
    py = center_y - cutout.height // 2
    layer.alpha_composite(cutout, (px, py))


def add_failed_tear(layer: Image.Image, frame: int) -> None:
    if frame == 0:
        return
    draw = ImageDraw.Draw(layer)
    x = ws(76)
    y = ws(54 + frame * 2)
    tear = [
        (x, y - ws(3)),
        (x + ws(3), y + ws(2)),
        (x, y + ws(6)),
        (x - ws(3), y + ws(2)),
    ]
    draw.polygon(tear, fill=(86, 222, 255, 210), outline=(37, 63, 84, 230))


def add_wave_marks(layer: Image.Image, frame: int) -> None:
    if frame not in {1, 2, 3}:
        return
    draw = ImageDraw.Draw(layer)
    offset = [-1, 1, -2][frame - 1]
    draw.arc(box((18 + offset, 50, 39 + offset, 72)), 285, 55, fill=(238, 96, 166, 220), width=ws(1.4))
    draw.arc(box((14 + offset, 45, 45 + offset, 78)), 292, 48, fill=(82, 224, 238, 190), width=ws(1.1))


def render_layer(layer: Image.Image, *, x: float = 0, y: float = 0, angle: float = 0) -> Image.Image:
    image = layer
    if angle:
        image = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    cell = new_cell()
    px = int(round((CELL * WORK_SCALE - image.width) / 2 + x * WORK_SCALE))
    py = int(round((CELL * WORK_SCALE - image.height) / 2 + y * WORK_SCALE))
    cell.alpha_composite(image, (px, py))
    return cell.resize((CELL, CELL), Image.Resampling.LANCZOS).convert("RGB")


def paste_sprite(
    cell: Image.Image,
    sprite: Image.Image,
    *,
    x: float = 0,
    y: float = 0,
    angle: float = 0,
    mirror: bool = False,
    brightness: float = 1,
) -> None:
    image = ImageOps.mirror(sprite) if mirror else sprite
    if brightness != 1:
        image = ImageEnhance.Brightness(image).enhance(brightness)
    if angle:
        image = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    px = int(round((CELL * WORK_SCALE - image.width) / 2 + x * WORK_SCALE))
    py = int(round(CELL * WORK_SCALE - image.height + y * WORK_SCALE))
    cell.alpha_composite(image, (px, py))


def draw_frame(sprite: Image.Image, key: str, frame: int, frames: int) -> Image.Image:
    phase = frame / frames
    x = 0.0
    y = 0.0
    angle = 0.0
    mirror = False
    brightness = 1.0

    if key == "idle":
        layer = make_sprite_layer(sprite)
        y = [-1.0, -3.0, -1.0, 0.0][frame]
        angle = [-1.0, 0.0, 1.0, 0.0][frame]
    elif key in {"running-right", "running-left"}:
        direction = 1 if key == "running-right" else -1
        mirror = direction == -1
        layer = make_sprite_layer(sprite, mirror=mirror)
        run_poses = [
            ((-5, 0, -13), (5, -3, 12), 0, -1, 4.0),
            ((-2, -5, -6), (3, 2, 8), direction * 1, -4, 2.0),
            ((4, -4, 10), (-4, 1, -11), direction * 2, -2, -1.0),
            ((5, 0, 13), (-5, -3, -12), direction * 0, -1, -4.0),
            ((2, -5, 6), (-3, 2, -8), -direction * 1, -4, -2.0),
            ((-4, -4, -10), (4, 1, 11), -direction * 2, -2, 1.0),
        ]
        left_leg, right_leg, x, y, angle = run_poses[frame]
        pose_region(layer, (51, 99, 66, 128), x=left_leg[0], y=left_leg[1], angle=left_leg[2])
        pose_region(layer, (65, 99, 84, 128), x=right_leg[0], y=right_leg[1], angle=right_leg[2])
    elif key == "waving":
        layer = make_sprite_layer(sprite)
        arm_poses = [
            (-2, -1, -8, -1.0),
            (-5, -9, -34, -2.0),
            (-3, -5, -18, 0.5),
            (-6, -11, -42, -2.5),
            (-2, -2, -10, 0.0),
        ]
        arm_x, arm_y, arm_angle, angle = arm_poses[frame]
        pose_region(layer, (29, 60, 58, 96), x=arm_x, y=arm_y, angle=arm_angle, erase=False)
        add_wave_marks(layer, frame)
        y = [-1, -2, -1, -2, -1][frame]
    elif key == "jumping":
        layer = make_sprite_layer(sprite)
        jump_poses = [
            (4, 2.0, (2, 2, 5), (-2, 2, -5)),
            (-11, -1.0, (-3, -4, -14), (3, -4, 14)),
            (-26, 2.5, (-6, -7, -22), (6, -7, 22)),
            (-7, -2.0, (1, 1, 6), (-1, 1, -6)),
        ]
        y, angle, left_leg, right_leg = jump_poses[frame]
        pose_region(layer, (51, 99, 66, 128), x=left_leg[0], y=left_leg[1], angle=left_leg[2])
        pose_region(layer, (65, 99, 84, 128), x=right_leg[0], y=right_leg[1], angle=right_leg[2])
    elif key == "waiting":
        layer = make_sprite_layer(sprite)
        angle = [-8, 6, -6, 8][frame]
        x = [-2, 1, -1, 2][frame]
        y = [-2, -3, -2, -3][frame]
    elif key == "failed":
        layer = make_sprite_layer(sprite, brightness=brightness)
        y = [6, 11, 15, 10][frame]
        angle = [-5, -8, -10, -7][frame]
        brightness = 0.86
        layer = ImageEnhance.Brightness(layer).enhance(brightness)
        add_failed_tear(layer, frame)
    else:
        layer = make_sprite_layer(sprite, mirror=mirror, brightness=brightness)

    return render_layer(layer, x=x, y=y, angle=angle)


def compose_spritesheet(frames_by_state: dict[str, list[Image.Image]]) -> Image.Image:
    sheet = Image.new("RGB", (CELL * MAX_FRAMES, CELL * len(ANIMATIONS)), BACKGROUND)
    for spec in ANIMATIONS:
        for col, frame in enumerate(frames_by_state[spec["key"]]):
            sheet.paste(frame, (col * CELL, spec["row"] * CELL))
    return sheet


def make_contact_sheet(frames_by_state: dict[str, list[Image.Image]]) -> Image.Image:
    label_h = 18
    sheet = Image.new("RGB", (CELL * MAX_FRAMES, (CELL + label_h) * len(ANIMATIONS)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for spec in ANIMATIONS:
        y = spec["row"] * (CELL + label_h)
        draw.rectangle((0, y, sheet.width, y + label_h - 1), fill=(24, 24, 28))
        draw.text((4, y + 4), f"{spec['key']}  frames={spec['frames']} fps={spec['fps']}", fill=(240, 240, 240), font=font)
        for col in range(MAX_FRAMES):
            x = col * CELL
            if col < spec["frames"]:
                sheet.paste(frames_by_state[spec["key"]][col], (x, y + label_h))
                border = (20, 142, 88)
            else:
                ImageDraw.Draw(sheet).rectangle((x, y + label_h, x + CELL - 1, y + label_h + CELL - 1), fill=BACKGROUND)
                border = (138, 38, 60)
            draw.rectangle((x, y + label_h, x + CELL - 1, y + label_h + CELL - 1), outline=border, width=1)
            draw.text((x + 3, y + label_h + 3), str(col), fill=(20, 20, 20), font=font)
    return sheet


def save_previews(frames_by_state: dict[str, list[Image.Image]]) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    for spec in ANIMATIONS:
        frames = [frame.convert("P", palette=Image.Palette.ADAPTIVE) for frame in frames_by_state[spec["key"]]]
        frames[0].save(
            PREVIEW_DIR / f"{spec['key']}.gif",
            save_all=True,
            append_images=frames[1:],
            duration=int(1000 / spec["fps"]),
            loop=0,
            disposal=2,
        )


def make_pet_json() -> dict[str, object]:
    return {
        "id": "kuromimi-q-chibi",
        "displayName": "Kuromimi Q Chibi",
        "description": "Q版黑猫耳桌宠，128px 帧动画，品红背景用于自动透明抠图。",
        "spritesheetPath": "spritesheet.webp",
        "sprite": {
            "frameWidth": CELL,
            "frameHeight": CELL,
            "columns": MAX_FRAMES,
            "rows": len(ANIMATIONS),
            "backgroundColor": "#FF00FF",
        },
        "animations": {
            spec["key"]: {
                "row": spec["row"],
                "frames": spec["frames"],
                "fps": spec["fps"],
            }
            for spec in ANIMATIONS
        },
    }


def validate(sheet: Image.Image, frames_by_state: dict[str, list[Image.Image]]) -> dict[str, object]:
    errors: list[str] = []
    if sheet.size != (CELL * MAX_FRAMES, CELL * len(ANIMATIONS)):
        errors.append(f"spritesheet size is {sheet.size}, expected {(CELL * MAX_FRAMES, CELL * len(ANIMATIONS))}")

    used_cells: list[dict[str, object]] = []
    unused_cells: list[dict[str, object]] = []
    bg = BACKGROUND
    for spec in ANIMATIONS:
        for col in range(MAX_FRAMES):
            cell = sheet.crop((col * CELL, spec["row"] * CELL, (col + 1) * CELL, (spec["row"] + 1) * CELL))
            non_bg = sum(1 for pixel in image_pixels(cell) if pixel != bg)
            record = {"key": spec["key"], "row": spec["row"], "frame": col, "non_background_pixels": non_bg}
            if col < spec["frames"]:
                used_cells.append(record)
                if non_bg < 900:
                    errors.append(f"{spec['key']} frame {col} appears empty")
                for corner in [(0, 0), (CELL - 1, 0), (0, CELL - 1), (CELL - 1, CELL - 1)]:
                    if cell.getpixel(corner) != bg:
                        errors.append(f"{spec['key']} frame {col} corner {corner} is not #FF00FF")
            else:
                unused_cells.append(record)
                if non_bg != 0:
                    errors.append(f"{spec['key']} unused frame {col} is not pure #FF00FF")

    return {
        "ok": not errors,
        "spritesheet": str(SPRITESHEET_PATH),
        "pet_json": str(PET_JSON_PATH),
        "codex_pet_dir": str(CODEX_PET_DIR),
        "source_master": str(MASTER_PATH),
        "frame_size": [CELL, CELL],
        "spritesheet_size": list(sheet.size),
        "background": "#FF00FF",
        "columns": MAX_FRAMES,
        "rows": len(ANIMATIONS),
        "animations": ANIMATIONS,
        "used_cells": used_cells,
        "unused_cells": unused_cells,
        "errors": errors,
        "preview_dir": str(PREVIEW_DIR),
        "contact_sheet": str(CONTACT_SHEET_PATH),
    }


def main() -> None:
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    master = load_master()
    sprite = fit_master(master)

    frames_by_state = {
        spec["key"]: [draw_frame(sprite, spec["key"], frame, spec["frames"]) for frame in range(spec["frames"])]
        for spec in ANIMATIONS
    }
    sheet = compose_spritesheet(frames_by_state)
    sheet.save(SPRITESHEET_PATH, lossless=True, quality=100, method=6)
    make_contact_sheet(frames_by_state).save(CONTACT_SHEET_PATH)
    save_previews(frames_by_state)

    pet_json = make_pet_json()
    PET_JSON_PATH.write_text(json.dumps(pet_json, ensure_ascii=False, indent=2), encoding="utf-8")

    CODEX_PET_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SPRITESHEET_PATH, CODEX_PET_DIR / "spritesheet.webp")
    shutil.copy2(PET_JSON_PATH, CODEX_PET_DIR / "pet.json")

    report = validate(Image.open(SPRITESHEET_PATH).convert("RGB"), frames_by_state)
    QA_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
