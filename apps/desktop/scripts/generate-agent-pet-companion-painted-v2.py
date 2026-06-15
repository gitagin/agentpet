from __future__ import annotations

import json
import math
import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageDraw, ImageFilter


CANVAS = (4096, 4096)
ROOT = Path(__file__).resolve().parents[1]
DESIGN_DIR = ROOT / "public" / "live2d" / "agent_pet_companion"
REFERENCE_PATH = DESIGN_DIR / "concept-reference.png"
OUT_DIR = DESIGN_DIR / "source" / "painted_v2"
LAYERS_DIR = OUT_DIR / "layers"
COMPOSITE_PATH = OUT_DIR / "agent_pet_companion_painted_v2_composite.png"
CUBISM_READY_PREVIEW_PATH = OUT_DIR / "agent_pet_companion_painted_v2_cubism_ready_preview.png"
CUTOUT_PATH = OUT_DIR / "agent_pet_companion_painted_v2_full_cutout.png"
CONTACT_SHEET_PATH = OUT_DIR / "agent_pet_companion_painted_v2_layer_contact_sheet.png"
MANIFEST_PATH = OUT_DIR / "agent_pet_companion_painted_v2.layer-manifest.json"
PHOTOSHOP_SCRIPT_PATH = OUT_DIR / "assemble-agent-pet-companion-painted-v2.jsx"
README_PATH = OUT_DIR / "PAINTED_V2_SOURCE_ART.md"
EXPRESSION_DIR = OUT_DIR / "expression_references"
EXPRESSION_MANIFEST_PATH = OUT_DIR / "agent_pet_companion_painted_v2.expression-references.json"

# Left-side full-body character on the concept sheet.
SOURCE_CROP = (0, 0, 610, 1122)
TARGET_HEIGHT = 3500
TARGET_TOP = 250
PART_OVERLAP_PIXELS = 10
TRANSPARENT_RGB_PADDING_PIXELS = 18


@dataclass(frozen=True)
class ExpressionRef:
    name: str
    action: str
    expression: str
    crop: tuple[int, int, int, int]
    purpose: str


EXPRESSION_REFS = [
    ExpressionRef("exp_idle_soft_ref", "idle", "exp_idle_soft", (606, 82, 850, 310), "Default friendly online idle."),
    ExpressionRef("exp_listen_mic_ref", "chat_listen", "exp_listen_mic", (866, 82, 1115, 310), "Attentive listening pose."),
    ExpressionRef("exp_think_focus_ref", "chat_think", "exp_think_focus", (1118, 82, 1380, 310), "Thinking and confirmation hesitation."),
    ExpressionRef("exp_talk_warm_ref", "chat_talk", "exp_talk_warm", (600, 370, 850, 610), "Warm speaking expression."),
    ExpressionRef("exp_task_done_ref", "task_complete", "exp_task_done", (866, 370, 1115, 610), "Small positive celebration."),
    ExpressionRef("exp_privacy_guard_ref", "memory_privacy_guard", "exp_privacy_guard", (1116, 370, 1390, 615), "Privacy guard hand pose."),
    ExpressionRef("exp_confirm_careful_ref", "memory_confirm_needed", "exp_confirm_careful", (690, 720, 960, 1005), "Careful confirmation and uncertainty."),
    ExpressionRef("exp_sleep_quiet_ref", "sleep_quiet", "exp_sleep_quiet", (995, 720, 1280, 1005), "Quiet low-distraction sleepy state."),
]


@dataclass(frozen=True)
class LayerSpec:
    name: str
    group: str
    part: str
    purpose: str
    mask_fn: Callable[[tuple[int, int], Image.Image], Image.Image]
    visible_default: bool = True
    assign_exclusive: bool = True


@dataclass(frozen=True)
class AutoFillSpec:
    name: str
    group: str
    part: str
    purpose: str
    source_mask_fn: Callable[[tuple[int, int], Image.Image], Image.Image]
    target_mask_fn: Callable[[tuple[int, int], Image.Image], Image.Image]
    fallback_color: str
    alpha: int = 255
    texture_blur: float = 4.0
    visible_default: bool = True
    assign_exclusive: bool = False


def rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.stem}.tmp{path.suffix}")
    image.save(temp_path)
    temp_path.replace(path)


def estimate_background(rgb: Image.Image) -> tuple[int, int, int]:
    w, h = rgb.size
    samples: list[tuple[int, int, int]] = []
    for x in range(0, w, max(1, w // 30)):
        samples.append(rgb.getpixel((x, 0)))
        samples.append(rgb.getpixel((x, h - 1)))
    for y in range(0, h, max(1, h // 30)):
        samples.append(rgb.getpixel((0, y)))
        samples.append(rgb.getpixel((w - 1, y)))
    samples.sort()
    mid = len(samples) // 2
    return samples[mid]


def remove_connected_background(rgb: Image.Image) -> Image.Image:
    w, h = rgb.size
    bg = estimate_background(rgb)
    pixels = rgb.load()
    visited = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()

    def is_bg_like(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        distance = math.sqrt((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2)
        very_light = r > 218 and g > 212 and b > 204
        low_chroma = abs(r - g) < 22 and abs(g - b) < 28
        return distance < 26 and very_light and low_chroma

    def push_if_bg(x: int, y: int) -> None:
        index = y * w + x
        if visited[index] or not is_bg_like(x, y):
            return
        visited[index] = 1
        queue.append((x, y))

    for x in range(w):
        push_if_bg(x, 0)
        push_if_bg(x, h - 1)
    for y in range(h):
        push_if_bg(0, y)
        push_if_bg(w - 1, y)

    while queue:
        x, y = queue.popleft()
        if x > 0:
            push_if_bg(x - 1, y)
        if x + 1 < w:
            push_if_bg(x + 1, y)
        if y > 0:
            push_if_bg(x, y - 1)
        if y + 1 < h:
            push_if_bg(x, y + 1)

    alpha = Image.new("L", (w, h), 255)
    alpha_pixels = alpha.load()
    for y in range(h):
        row = y * w
        for x in range(w):
            if visited[row + x]:
                alpha_pixels[x, y] = 0

    # Trim the outer crop edge to avoid tiny fragments from the next expression pose.
    alpha_draw = ImageDraw.Draw(alpha)
    alpha_draw.rectangle((w - 8, 0, w, h), fill=0)

    # Contract one pixel before smoothing. The concept sheet is on a warm light
    # background, so this removes the visible light matte without making new art.
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.55))

    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    result = remove_light_matte(result, bg)
    return result


def remove_light_matte(image: Image.Image, matte: tuple[int, int, int]) -> Image.Image:
    pixels = image.load()
    w, h = image.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0:
                pixels[x, y] = (0, 0, 0, 0)
                continue
            if a >= 250:
                continue
            af = max(a / 255.0, 0.08)
            nr = max(0, min(255, round((r - matte[0] * (1 - af)) / af)))
            ng = max(0, min(255, round((g - matte[1] * (1 - af)) / af)))
            nb = max(0, min(255, round((b - matte[2] * (1 - af)) / af)))
            pixels[x, y] = (nr, ng, nb, a)
    return image


def canvas_from_crop(layer_crop: Image.Image) -> Image.Image:
    scale = TARGET_HEIGHT / layer_crop.height
    target_width = round(layer_crop.width * scale)
    target = layer_crop.resize((target_width, TARGET_HEIGHT), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    left = (CANVAS[0] - target_width) // 2
    canvas.alpha_composite(target, (left, TARGET_TOP))
    return canvas


def square_reference_canvas(crop: Image.Image, size: int = 1024) -> Image.Image:
    bbox = crop.getchannel("A").getbbox()
    if bbox:
        crop = crop.crop(bbox)
    max_edge = max(crop.width, crop.height)
    if max_edge > 0:
      scale = (size - 120) / max_edge
      crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(crop, ((size - crop.width) // 2, (size - crop.height) // 2))
    return canvas


def mask_image(size: tuple[int, int]) -> Image.Image:
    return Image.new("L", size, 0)


def rect(size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    mask = mask_image(size)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    return mask


def ellipse(size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    mask = mask_image(size)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    return mask


def polygon(size: tuple[int, int], points: list[tuple[int, int]]) -> Image.Image:
    mask = mask_image(size)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def union_masks(*masks: Image.Image) -> Image.Image:
    out = mask_image(masks[0].size)
    for mask in masks:
        out = Image.composite(Image.new("L", mask.size, 255), out, mask)
    return out


def color_mask(
    rgb: Image.Image,
    *,
    box: tuple[int, int, int, int],
    predicate: Callable[[int, int, int], bool],
) -> Image.Image:
    w, h = rgb.size
    x1, y1, x2, y2 = box
    mask = mask_image((w, h))
    pixels = rgb.load()
    out = mask.load()
    for y in range(max(0, y1), min(h, y2)):
        for x in range(max(0, x1), min(w, x2)):
            r, g, b = pixels[x, y]
            if predicate(r, g, b):
                out[x, y] = 255
    return mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(0.4))


def dark_teal(r: int, g: int, b: int) -> bool:
    return r < 92 and g < 116 and b < 128 and (g >= r or b >= r)


def warm_skin(r: int, g: int, b: int) -> bool:
    return r > 178 and 105 < g < 210 and 85 < b < 190 and r > g > b


def cyan_glow(r: int, g: int, b: int) -> bool:
    return g > 135 and b > 130 and r < 130


def notebook_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return union_masks(rect(size, (0, 185, 174, 486)), rect(size, (10, 250, 158, 412)))


def floating_shards_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return rect(size, (15, 90, 145, 255))


def database_charm_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return ellipse(size, (395, 610, 512, 742))


def badge_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return rect(size, (325, 385, 456, 594))


def status_light_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return ellipse(size, (247, 244, 334, 337))


def eye_l_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return ellipse(size, (211, 118, 273, 175))


def eye_r_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return ellipse(size, (303, 118, 365, 175))


def mouth_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return ellipse(size, (259, 180, 329, 226))


def front_hair_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return color_mask(rgb, box=(122, 0, 432, 285), predicate=dark_teal)


def side_hair_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return color_mask(rgb, box=(90, 105, 465, 440), predicate=dark_teal)


def face_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return union_masks(
        color_mask(rgb, box=(165, 78, 394, 292), predicate=warm_skin),
        ellipse(size, (164, 82, 397, 302)),
    )


def neck_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return rect(size, (229, 260, 345, 365))


def hand_l_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return color_mask(rgb, box=(34, 493, 174, 682), predicate=warm_skin)


def hand_r_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return color_mask(rgb, box=(450, 486, 600, 682), predicate=warm_skin)


def arm_l_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return polygon(size, [(70, 305), (176, 335), (152, 690), (35, 650), (45, 520)])


def arm_r_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return polygon(size, [(420, 305), (550, 350), (588, 635), (458, 690), (440, 510)])


def jacket_l_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return polygon(size, [(120, 255), (284, 276), (248, 742), (132, 737), (70, 410)])


def jacket_r_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return polygon(size, [(320, 276), (492, 258), (530, 415), (465, 742), (342, 742)])


def torso_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return polygon(size, [(190, 245), (390, 245), (420, 740), (168, 740)])


def leg_l_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return polygon(size, [(174, 700), (304, 700), (304, 1010), (186, 1010)])


def leg_r_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return polygon(size, [(288, 700), (430, 700), (424, 1010), (298, 1010)])


def shoes_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return rect(size, (162, 940, 430, 1121))


def leftover_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    mask = mask_image(size)
    ImageDraw.Draw(mask).rectangle((0, 0, size[0], size[1]), fill=255)
    return mask


def expand_part_mask(mask: Image.Image, pixels: int = PART_OVERLAP_PIXELS) -> Image.Image:
    if pixels <= 0:
        return mask
    size = pixels * 2 + 1
    return mask.filter(ImageFilter.MaxFilter(size)).point(lambda p: 255 if p > 0 else 0)


def threshold_mask(mask: Image.Image) -> Image.Image:
    return mask.point(lambda p: 255 if p > 0 else 0)


def soften_mask(mask: Image.Image, blur: float = 0.6) -> Image.Image:
    if blur <= 0:
        return threshold_mask(mask)
    return threshold_mask(mask).filter(ImageFilter.GaussianBlur(blur))


def average_rgb(image: Image.Image, mask: Image.Image, fallback: str) -> tuple[int, int, int]:
    rgba_image = image.convert("RGBA")
    alpha = rgba_image.getchannel("A")
    mask = threshold_mask(mask)
    pixels = rgba_image.load()
    mask_pixels = mask.load()
    alpha_pixels = alpha.load()
    total_r = 0
    total_g = 0
    total_b = 0
    count = 0
    width, height = rgba_image.size
    for y in range(height):
        for x in range(width):
            if mask_pixels[x, y] and alpha_pixels[x, y]:
                r, g, b, _ = pixels[x, y]
                total_r += r
                total_g += g
                total_b += b
                count += 1
    if count == 0:
        r, g, b, _ = rgba(fallback)
        return (r, g, b)
    return (round(total_r / count), round(total_g / count), round(total_b / count))


def textured_fill_from_source(
    source: Image.Image,
    source_mask: Image.Image,
    target_mask: Image.Image,
    *,
    fallback_color: str,
    alpha: int = 255,
    texture_blur: float = 4.0,
) -> Image.Image:
    source = source.convert("RGBA")
    source_mask = threshold_mask(source_mask)
    target_mask = soften_mask(target_mask, 0.75)
    fill_rgb = average_rgb(source, source_mask, fallback_color)
    fill = Image.new("RGBA", source.size, (*fill_rgb, alpha))
    sampled = apply_mask(source, source_mask)
    fill.alpha_composite(sampled)
    if texture_blur > 0:
        fill = fill.filter(ImageFilter.GaussianBlur(texture_blur))
    fill_alpha = target_mask.point(lambda p: min(alpha, round(p * alpha / 255)))
    fill.putalpha(fill_alpha)
    return remove_light_matte(fill, fill_rgb)


def solidify_transparent_rgb(image: Image.Image, pixels: int = TRANSPARENT_RGB_PADDING_PIXELS) -> Image.Image:
    if pixels <= 0:
        return image
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    solid_alpha = threshold_mask(alpha)
    if not solid_alpha.getbbox():
        return image
    padded_area = expand_part_mask(solid_alpha, pixels)
    padding = textured_fill_from_source(
        image,
        solid_alpha,
        padded_area,
        fallback_color="#2c3440",
        alpha=255,
        texture_blur=2.5,
    )
    transparent_padding = ImageChops.subtract(padded_area, solid_alpha)
    result_rgb = Image.composite(padding.convert("RGB"), image.convert("RGB"), transparent_padding)
    result = result_rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def face_skin_source_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return union_masks(
        color_mask(rgb, box=(150, 78, 410, 312), predicate=warm_skin),
        ellipse(size, (188, 130, 372, 292)),
        rect(size, (230, 252, 350, 360)),
    )


def face_under_hair_fill_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    head_limit = ellipse(size, (142, 46, 420, 328))
    skin_overlap = expand_part_mask(face_skin_source_mask(size, _), 22)
    return ImageChops.multiply(skin_overlap, head_limit)


def neck_skin_source_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return union_masks(
        color_mask(rgb, box=(215, 218, 368, 390), predicate=warm_skin),
    )


def neck_under_head_fill_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    neck_limit = union_masks(rect(size, (218, 238, 364, 392)), ellipse(size, (214, 222, 368, 392)))
    return ImageChops.multiply(expand_part_mask(neck_skin_source_mask(size, _), 20), neck_limit)


def torso_source_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    return torso_mask(size, _)


def torso_under_jacket_fill_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    torso_limit = polygon(size, [(150, 235), (430, 235), (452, 790), (140, 790)])
    return ImageChops.multiply(expand_part_mask(torso_mask(size, _), 12), torso_limit)


def hair_source_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return union_masks(front_hair_mask(size, rgb), side_hair_mask(size, rgb))


def back_hair_under_head_fill_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    hair_limit = union_masks(
        ellipse(size, (104, 20, 470, 438)),
        polygon(size, [(120, 98), (188, 410), (96, 512), (92, 214)]),
        polygon(size, [(390, 96), (486, 214), (478, 502), (392, 410)]),
    )
    return ImageChops.multiply(expand_part_mask(hair_source_mask(size, _), 18), hair_limit)


def left_hand_skin_source_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return hand_l_mask(size, rgb)


def right_hand_skin_source_mask(size: tuple[int, int], rgb: Image.Image) -> Image.Image:
    return hand_r_mask(size, rgb)


def left_hand_under_sleeve_fill_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    hand_limit = polygon(size, [(76, 462), (174, 500), (162, 684), (34, 674), (42, 538)])
    return ImageChops.multiply(expand_part_mask(hand_l_mask(size, _), 18), hand_limit)


def right_hand_under_sleeve_fill_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    hand_limit = polygon(size, [(448, 492), (566, 460), (596, 636), (456, 696), (438, 560)])
    return ImageChops.multiply(expand_part_mask(hand_r_mask(size, _), 18), hand_limit)


def left_leg_under_coat_fill_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    leg_limit = polygon(size, [(172, 660), (292, 660), (292, 1010), (188, 1010)])
    return ImageChops.multiply(expand_part_mask(leg_l_mask(size, _), 14), leg_limit)


def right_leg_under_coat_fill_mask(size: tuple[int, int], _: Image.Image) -> Image.Image:
    leg_limit = polygon(size, [(288, 660), (412, 660), (400, 1010), (298, 1010)])
    return ImageChops.multiply(expand_part_mask(leg_r_mask(size, _), 14), leg_limit)


LAYERS = [
    LayerSpec("painted_full_character_reference", "00_reference_do_not_export", "Reference", "Full transparent cutout from the high-quality concept sheet; hide before Cubism export.", leftover_mask, False, False),
    LayerSpec(
        "painted_preview_seam_guard_do_not_export",
        "00_preview_seam_guard_do_not_export",
        "PreviewOnly",
        "Full cutout placed below part layers to hide alpha seams while cleaning in Photoshop; hide or delete before Cubism export.",
        leftover_mask,
        True,
        False,
    ),
    LayerSpec("prop_floating_notebook", "90_props", "PartNotebook", "Floating notebook from the concept art.", notebook_mask),
    LayerSpec("prop_memory_shards", "90_props", "PartCards", "Small cyan memory shards around the notebook.", floating_shards_mask),
    LayerSpec("database_charm", "90_props", "PartDatabaseCharm", "Local database charm near the hip.", database_charm_mask),
    LayerSpec("id_badge", "90_props", "PartCards", "Hanging archive badge.", badge_mask),
    LayerSpec("status_light", "20_body", "PartStatusRibbon", "Chest status light for project state.", status_light_mask),
    LayerSpec("eye_l", "40_eyes", "PartEyeL", "Left eye cut layer.", eye_l_mask),
    LayerSpec("eye_r", "40_eyes", "PartEyeR", "Right eye cut layer.", eye_r_mask),
    LayerSpec("mouth", "60_mouth", "PartMouth", "Mouth cut layer for redraw/rig reference.", mouth_mask),
    LayerSpec("hair_front_and_top", "70_front_hair", "PartHairFront", "Visible front and top hair cut from concept art.", front_hair_mask),
    LayerSpec("hair_sides_and_back", "10_back_hair", "PartHairBack", "Side/back hair cut from concept art.", side_hair_mask),
    LayerSpec("face_base", "30_head", "PartHead", "Face skin area from concept art.", face_mask),
    LayerSpec("neck", "20_body", "PartBody", "Neck under head.", neck_mask),
    LayerSpec("hand_l", "80_arms", "PartArmL", "Left hand.", hand_l_mask),
    LayerSpec("hand_r", "80_arms", "PartArmR", "Right hand.", hand_r_mask),
    LayerSpec("arm_l_sleeve", "80_arms", "PartArmL", "Left sleeve and forearm.", arm_l_mask),
    LayerSpec("arm_r_sleeve", "80_arms", "PartArmR", "Right sleeve and forearm.", arm_r_mask),
    LayerSpec("jacket_l", "20_body", "PartBody", "Left jacket panel.", jacket_l_mask),
    LayerSpec("jacket_r", "20_body", "PartBody", "Right jacket panel.", jacket_r_mask),
    LayerSpec("torso_inner", "20_body", "PartBody", "Inner black tunic and upper torso.", torso_mask),
    LayerSpec("leg_l", "20_body", "PartBody", "Left leg.", leg_l_mask),
    LayerSpec("leg_r", "20_body", "PartBody", "Right leg.", leg_r_mask),
    LayerSpec("shoes", "20_body", "PartBody", "Shoes.", shoes_mask),
    LayerSpec("painted_visible_edge_recovery", "20_body", "PartBody", "Exact original pixels recovered from mask misses; keep for first Cubism import, then split later if desired.", leftover_mask),
    LayerSpec("painted_unassigned_details", "95_cleanup_needed", "Cleanup", "Remaining pixels from the concept cutout; split or repaint manually before final Cubism rig.", leftover_mask),
]


AUTO_FILLS = [
    AutoFillSpec(
        "hair_back_auto_fill",
        "10_back_hair",
        "PartHairBackAutoFill",
        "Auto-generated dark hair padding behind the head so head/hair motion does not reveal transparent holes.",
        hair_source_mask,
        back_hair_under_head_fill_mask,
        "#143541",
        alpha=245,
        texture_blur=5.0,
    ),
    AutoFillSpec(
        "torso_under_jacket_auto_fill",
        "20_body",
        "PartBodyAutoFill",
        "Auto-generated inner torso padding behind jacket panels for breathing and body sway.",
        torso_source_mask,
        torso_under_jacket_fill_mask,
        "#202833",
        alpha=245,
        texture_blur=5.5,
    ),
    AutoFillSpec(
        "neck_under_head_auto_fill",
        "20_body",
        "PartBodyAutoFill",
        "Auto-generated neck padding under the chin for head turns and nods.",
        neck_skin_source_mask,
        neck_under_head_fill_mask,
        "#f0bd9c",
        alpha=245,
        texture_blur=4.5,
    ),
    AutoFillSpec(
        "leg_l_under_coat_auto_fill",
        "20_body",
        "PartBodyAutoFill",
        "Auto-generated left-leg padding behind the coat hem.",
        leg_l_mask,
        left_leg_under_coat_fill_mask,
        "#232a31",
        alpha=245,
        texture_blur=5.0,
    ),
    AutoFillSpec(
        "leg_r_under_coat_auto_fill",
        "20_body",
        "PartBodyAutoFill",
        "Auto-generated right-leg padding behind the coat hem.",
        leg_r_mask,
        right_leg_under_coat_fill_mask,
        "#232a31",
        alpha=245,
        texture_blur=5.0,
    ),
    AutoFillSpec(
        "face_under_hair_auto_fill",
        "30_head",
        "PartHeadAutoFill",
        "Auto-generated skin padding under the bangs and side hair for head turns.",
        face_skin_source_mask,
        face_under_hair_fill_mask,
        "#f3c0a0",
        alpha=250,
        texture_blur=4.0,
    ),
    AutoFillSpec(
        "hand_l_under_sleeve_auto_fill",
        "80_arms",
        "PartArmLAutoFill",
        "Auto-generated left-hand/forearm padding tucked under the sleeve cuff.",
        left_hand_skin_source_mask,
        left_hand_under_sleeve_fill_mask,
        "#eeb691",
        alpha=245,
        texture_blur=4.0,
    ),
    AutoFillSpec(
        "hand_r_under_sleeve_auto_fill",
        "80_arms",
        "PartArmRAutoFill",
        "Auto-generated right-hand/forearm padding tucked under the sleeve cuff.",
        right_hand_skin_source_mask,
        right_hand_under_sleeve_fill_mask,
        "#eeb691",
        alpha=245,
        texture_blur=4.0,
    ),
]

REGULAR_LAYER_DRAW_ORDER = [
    "hair_sides_and_back",
    "leg_l",
    "leg_r",
    "shoes",
    "torso_inner",
    "neck",
    "arm_l_sleeve",
    "arm_r_sleeve",
    "jacket_l",
    "jacket_r",
    "status_light",
    "database_charm",
    "id_badge",
    "hand_l",
    "hand_r",
    "face_base",
    "eye_l",
    "eye_r",
    "mouth",
    "hair_front_and_top",
    "prop_floating_notebook",
    "prop_memory_shards",
    "painted_visible_edge_recovery",
    "painted_unassigned_details",
]


def ordered_regular_layers() -> list[LayerSpec]:
    specs_by_name = {spec.name: spec for spec in LAYERS[2:]}
    ordered = []
    for name in REGULAR_LAYER_DRAW_ORDER:
        spec = specs_by_name.pop(name, None)
        if spec is not None:
            ordered.append(spec)
    ordered.extend(specs_by_name.values())
    return ordered


def apply_mask(source: Image.Image, mask: Image.Image) -> Image.Image:
    out = Image.new("RGBA", source.size, (0, 0, 0, 0))
    out.alpha_composite(source)
    source_alpha = source.getchannel("A")
    combined_alpha = Image.composite(source_alpha, Image.new("L", source.size, 0), mask)
    out.putalpha(combined_alpha)
    return out


def subtract_mask(mask: Image.Image, assigned: Image.Image) -> Image.Image:
    return Image.eval(ImageChops.subtract(mask, assigned), lambda p: p)


def write_contact_sheet(layers: list[tuple[LayerSpec | AutoFillSpec, Image.Image]]) -> None:
    thumb_w, thumb_h = 360, 360
    cols = 4
    rows = math.ceil(len(layers) / cols)
    sheet = Image.new("RGBA", (cols * thumb_w, rows * thumb_h), rgba("#f6f1ea"))
    for index, (spec, canvas) in enumerate(layers):
        thumb = canvas.copy()
        bbox = thumb.getbbox()
        if bbox:
            thumb = thumb.crop(bbox)
            thumb.thumbnail((thumb_w - 36, thumb_h - 74), Image.Resampling.LANCZOS)
        else:
            thumb = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        tile = Image.new("RGBA", (thumb_w, thumb_h), rgba("#fffaf4"))
        tile.alpha_composite(thumb, ((thumb_w - thumb.width) // 2, 20))
        ImageDraw.Draw(tile).text((16, thumb_h - 44), spec.name[:34], fill=rgba("#202632"))
        sheet.alpha_composite(tile, ((index % cols) * thumb_w, (index // cols) * thumb_h))
    sheet.save(CONTACT_SHEET_PATH)


def write_photoshop_script(manifest_layers: list[dict[str, object]]) -> None:
    layer_json = json.dumps(manifest_layers, indent=2)
    script = f"""#target photoshop
app.bringToFront();

var oldDialogs = app.displayDialogs;
var oldUnits = app.preferences.rulerUnits;

try {{
  app.displayDialogs = DialogModes.NO;
  app.preferences.rulerUnits = Units.PIXELS;

  var scriptFile = new File($.fileName);
  var sourceDir = scriptFile.parent;
  var layers = {layer_json};

  function ensureGroup(doc, groupName) {{
    app.activeDocument = doc;
    for (var i = 0; i < doc.layerSets.length; i++) {{
      if (doc.layerSets[i].name === groupName) return doc.layerSets[i];
    }}
    var group = doc.layerSets.add();
    group.name = groupName;
  if (groupName === "00_reference_do_not_export") {{
    group.visible = false;
  }}
  if (groupName === "00_preview_seam_guard_do_not_export") {{
    group.visible = true;
  }}
    return group;
  }}

  alert("Start assembling Agent Pet Companion PSD. Photoshop will open " + layers.length + " PNG layers. Please wait until the final success message.");

  var doc = app.documents.add(
    UnitValue(4096, "px"),
    UnitValue(4096, "px"),
    72,
    "agent_pet_companion_painted_v2_layered",
    NewDocumentMode.RGB,
    DocumentFill.TRANSPARENT
  );

  for (var i = 0; i < layers.length; i++) {{
    var item = layers[i];
    var file = new File(sourceDir.fsName + "/" + item.file);
    if (!file.exists) {{
      throw new Error("Missing layer PNG: " + file.fsName);
    }}

    var group = ensureGroup(doc, item.group);
    var src = app.open(file);
    app.activeDocument = src;
    src.activeLayer.name = item.name;

    var duplicated = src.activeLayer.duplicate(doc, ElementPlacement.PLACEATBEGINNING);
    src.close(SaveOptions.DONOTSAVECHANGES);

    app.activeDocument = doc;
    duplicated.name = item.name;
    duplicated.visible = item.visibleDefault;
    try {{
      duplicated.move(group, ElementPlacement.INSIDE);
    }} catch (moveErr) {{
      duplicated.name = item.group + "__" + item.name;
    }}
  }}

  app.activeDocument = doc;
  var saveFile = new File(sourceDir.fsName + "/agent_pet_companion_painted_v2_layered.psd");
  var options = new PhotoshopSaveOptions();
  options.layers = true;
  options.alphaChannels = true;
  options.embedColorProfile = true;
  doc.saveAs(saveFile, options, true, Extension.LOWERCASE);
  alert("Success. Layered PSD created: " + saveFile.fsName);
}} catch (err) {{
  alert("Agent Pet Companion PSD assembly failed.\\n\\n" + err.message + "\\nLine: " + err.line);
}} finally {{
  app.displayDialogs = oldDialogs;
  app.preferences.rulerUnits = oldUnits;
}}
"""
    PHOTOSHOP_SCRIPT_PATH.write_text(script, encoding="utf-8")


def write_readme() -> None:
    README_PATH.write_text(
        """# Painted V2 Source Art

This is the preferred high-quality source-art package for the Archivist Companion.
It uses `concept-reference.png` as the visual master and extracts the left full-body
character into transparent PNG layers.

This is still not a `.moc3` runtime model. It is a Photoshop/Cubism source package.

## Why this exists

The first generated source-art package is a technical placeholder. This v2 package
prioritizes the look of the concept art, so it should be used as the actual visual
base for Photoshop cleanup and Live2D Cubism rigging.

## Files

- `agent_pet_companion_painted_v2_full_cutout.png`: transparent full character cutout.
- `layers/*.png`: transparent part layers cut from the concept art.
- `layers/painted_preview_seam_guard_do_not_export.png`: visible Photoshop preview seam guard.
  Hide or delete it before final Cubism export.
- `layers/*_auto_fill.png`: auto-generated hidden overlap layers. Keep these for Cubism;
  they reduce transparent holes when the head, hair, body, sleeves, and legs move.
- `layers/painted_visible_edge_recovery.png`: exact original pixels recovered from
  automatic mask misses. Keep this layer visible for the first Cubism import.
- `agent_pet_companion_painted_v2_composite.png`: visible composite preview.
- `agent_pet_companion_painted_v2_cubism_ready_preview.png`: preview with reference,
  seam guard, and cleanup leftovers excluded.
- `agent_pet_companion_painted_v2.layer-manifest.json`: layer order and Cubism part mapping.
- `assemble-agent-pet-companion-painted-v2.jsx`: Photoshop script that creates a layered PSD.
- `expression_references/*.png`: high-quality expression/action references cropped
  from the concept sheet.
- `agent_pet_companion_painted_v2.expression-references.json`: action-to-expression
  reference index.

## Photoshop

1. Open Photoshop.
2. Choose `File > Scripts > Browse...`.
3. Select `assemble-agent-pet-companion-painted-v2.jsx`.
4. Save or edit the generated `agent_pet_companion_painted_v2_layered.psd`.

## Manual cleanup before Cubism

Because this v2 package is extracted from a flat concept sheet, it now includes
automatic overlap/fill layers to reduce hand painting. A model artist should still
check it before final rigging:

- keep the `*_auto_fill` layers unless you have manually painted better replacements;
- keep `painted_visible_edge_recovery` visible; it patches pixels that the automatic
  masks missed, such as thin leg and boot-edge details;
- redraw eyes into separate white/iris/highlight/lid layers;
- redraw mouth into open/close mouth parts;
- separate sleeve, arm, hand, and finger layers if large gestures are required;
- hide or delete `painted_preview_seam_guard_do_not_export` before exporting to Cubism;
- keep `painted_unassigned_details` hidden; it should be empty or only contain future cleanup leftovers.
""",
        encoding="utf-8",
    )


def write_expression_references(concept: Image.Image) -> None:
    if EXPRESSION_DIR.exists():
        shutil.rmtree(EXPRESSION_DIR)
    EXPRESSION_DIR.mkdir(parents=True)

    records: list[dict[str, object]] = []
    for ref in EXPRESSION_REFS:
        crop = concept.crop(ref.crop)
        cutout = remove_connected_background(crop)
        square = square_reference_canvas(cutout)
        out_path = EXPRESSION_DIR / f"{ref.name}.png"
        save_png(square, out_path)
        records.append(
            {
                "name": ref.name,
                "action": ref.action,
                "expression": ref.expression,
                "file": f"expression_references/{ref.name}.png",
                "crop": {"left": ref.crop[0], "top": ref.crop[1], "right": ref.crop[2], "bottom": ref.crop[3]},
                "purpose": ref.purpose,
            }
        )

    EXPRESSION_MANIFEST_PATH.write_text(
        json.dumps(
            {
                "version": 1,
                "id": "agent_pet_companion",
                "status": "expression_references_only_not_runtime",
                "notRuntimeModel": True,
                "referenceCount": len(records),
                "references": records,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    if not REFERENCE_PATH.exists():
        raise FileNotFoundError(REFERENCE_PATH)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if LAYERS_DIR.exists():
        shutil.rmtree(LAYERS_DIR)
    LAYERS_DIR.mkdir(parents=True)

    concept = Image.open(REFERENCE_PATH).convert("RGB")
    write_expression_references(concept)
    crop = concept.crop(SOURCE_CROP)
    cutout_crop = remove_connected_background(crop)
    cutout_canvas = canvas_from_crop(cutout_crop)
    save_png(cutout_canvas, CUTOUT_PATH)

    assigned = Image.new("L", crop.size, 0)
    cutout_alpha = threshold_mask(cutout_crop.getchannel("A"))
    layer_records: list[dict[str, object]] = []
    layer_canvases: list[tuple[LayerSpec | AutoFillSpec, Image.Image]] = []
    composite = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    cubism_ready_preview = Image.new("RGBA", CANVAS, (0, 0, 0, 0))

    def add_layer(spec: LayerSpec | AutoFillSpec, layer_crop: Image.Image) -> None:
        layer_crop = solidify_transparent_rgb(layer_crop)
        layer_canvas = canvas_from_crop(layer_crop)
        file_name = f"{spec.name}.png"
        save_png(layer_canvas, LAYERS_DIR / file_name)
        layer_canvases.append((spec, layer_canvas))
        is_auto_fill = isinstance(spec, AutoFillSpec)
        is_preview_only = spec.name == "painted_preview_seam_guard_do_not_export"
        is_reference = spec.name == "painted_full_character_reference"
        is_cleanup = spec.name == "painted_unassigned_details"
        layer_records.append(
            {
                "name": spec.name,
                "group": spec.group,
                "part": spec.part,
                "purpose": spec.purpose,
                "file": f"layers/{file_name}",
                "visibleDefault": spec.visible_default,
                "assignExclusive": spec.assign_exclusive,
                "autoGeneratedFill": is_auto_fill,
                "keepForCubism": spec.visible_default and not is_preview_only and not is_reference and not is_cleanup,
            }
        )
        if spec.visible_default:
            composite.alpha_composite(layer_canvas)
            if not is_preview_only and not is_reference and not is_cleanup:
                cubism_ready_preview.alpha_composite(layer_canvas)

    for spec in [LAYERS[0], LAYERS[1]]:
        if spec.name == "painted_full_character_reference":
            layer_crop = cutout_crop
        elif spec.name == "painted_preview_seam_guard_do_not_export":
            layer_crop = cutout_crop
        add_layer(spec, layer_crop)

    for spec in AUTO_FILLS:
        source_mask = ImageChops.multiply(threshold_mask(spec.source_mask_fn(crop.size, crop)), cutout_alpha)
        target_mask = ImageChops.multiply(threshold_mask(spec.target_mask_fn(crop.size, crop)), cutout_alpha)
        layer_crop = textured_fill_from_source(
            cutout_crop,
            source_mask,
            target_mask,
            fallback_color=spec.fallback_color,
            alpha=spec.alpha,
            texture_blur=spec.texture_blur,
        )
        add_layer(spec, layer_crop)

    for spec in ordered_regular_layers():
        raw_mask = spec.mask_fn(crop.size, crop)
        foreground_mask = Image.composite(raw_mask, Image.new("L", crop.size, 0), cutout_crop.getchannel("A"))
        if spec.name == "painted_visible_edge_recovery":
            mask = ImageChops.subtract(cutout_crop.getchannel("A"), assigned)
            assigned = ImageChops.lighter(assigned, mask)
        elif spec.assign_exclusive and spec.name != "painted_unassigned_details":
            mask = expand_part_mask(foreground_mask)
            assigned = ImageChops.lighter(assigned, mask)
        elif spec.name == "painted_unassigned_details":
            mask = ImageChops.subtract(cutout_crop.getchannel("A"), assigned)
        else:
            mask = foreground_mask
        layer_crop = apply_mask(cutout_crop, mask)
        add_layer(spec, layer_crop)

    save_png(composite, COMPOSITE_PATH)
    save_png(cubism_ready_preview, CUBISM_READY_PREVIEW_PATH)
    write_contact_sheet(layer_canvases)
    write_photoshop_script(layer_records)
    write_readme()

    manifest = {
        "version": 2,
        "id": "agent_pet_companion",
        "displayName": "Archivist Companion",
        "status": "painted_source_art_generated_not_rigged",
        "notRuntimeModel": True,
        "visualSource": str(REFERENCE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "canvas": {"width": CANVAS[0], "height": CANVAS[1], "dpi": 72},
        "sourceCrop": {"left": SOURCE_CROP[0], "top": SOURCE_CROP[1], "right": SOURCE_CROP[2], "bottom": SOURCE_CROP[3]},
        "outputPsdName": "agent_pet_companion_painted_v2_layered.psd",
        "layerCount": len(layer_records),
        "partOverlapPixels": PART_OVERLAP_PIXELS,
        "transparentRgbPaddingPixels": TRANSPARENT_RGB_PADDING_PIXELS,
        "autoFillLayerCount": len(AUTO_FILLS),
        "previewSeamGuardLayer": "painted_preview_seam_guard_do_not_export",
        "cubismReadyPreview": CUBISM_READY_PREVIEW_PATH.name,
        "photoshopAssemblyScript": PHOTOSHOP_SCRIPT_PATH.name,
        "layers": layer_records,
        "manualCleanupRequired": [
            "review the auto-generated *_auto_fill layers and repaint only if a large motion exposes them too clearly",
            "keep painted_visible_edge_recovery visible for the first Cubism import because it contains exact original pixels missed by coarse masks",
            "redraw eyes into separate white, iris, highlight, upper lid, and lower lid layers",
            "redraw mouth into mouth line, mouth inside, teeth, and tongue layers",
            "hide or delete painted_preview_seam_guard_do_not_export before final Cubism export",
            "keep painted_unassigned_details hidden unless you intentionally split its remaining cleanup pixels",
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Generated painted v2 source art from {REFERENCE_PATH}")
    print(f"Layers: {LAYERS_DIR}")
    print(f"Layer count: {len(layer_records)}")
    print(f"Auto-fill layers: {len(AUTO_FILLS)}")
    print(f"Part overlap pixels: {PART_OVERLAP_PIXELS}")
    print(f"Transparent RGB padding pixels: {TRANSPARENT_RGB_PADDING_PIXELS}")
    print(f"Full cutout: {CUTOUT_PATH}")
    print(f"Composite: {COMPOSITE_PATH}")
    print(f"Cubism-ready preview: {CUBISM_READY_PREVIEW_PATH}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Photoshop script: {PHOTOSHOP_SCRIPT_PATH}")
    print(f"Expression references: {EXPRESSION_DIR}")


if __name__ == "__main__":
    main()
