from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_IMAGE = REPO_ROOT / "apps" / "desktop" / "public" / "images" / "character.png"
OUTPUT_ROOT = REPO_ROOT / "apps" / "desktop" / "public" / "live2d" / "character_live2d_split"
LAYERS_DIR = OUTPUT_ROOT / "layers"
DOC_NAME = "character_live2d_split"


def load_source() -> tuple[Image.Image, np.ndarray, np.ndarray]:
    image = Image.open(SOURCE_IMAGE).convert("RGBA")
    rgba = np.asarray(image)
    alpha = rgba[:, :, 3] > 8
    return image, rgba, alpha


def mask_from_polygon(size: tuple[int, int], points: list[tuple[int, int]]) -> np.ndarray:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return np.asarray(mask) > 0


def mask_from_ellipse(size: tuple[int, int], box: tuple[int, int, int, int]) -> np.ndarray:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    return np.asarray(mask) > 0


def mask_from_rect(size: tuple[int, int], box: tuple[int, int, int, int]) -> np.ndarray:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    return np.asarray(mask) > 0


def blur_mask(mask: np.ndarray, radius: float = 1.0) -> np.ndarray:
    image = Image.fromarray((mask.astype(np.uint8) * 255), "L")
    return np.asarray(image.filter(ImageFilter.GaussianBlur(radius))) > 8


def soften_alpha(mask: np.ndarray, radius: float = 0.8) -> Image.Image:
    image = Image.fromarray((mask.astype(np.uint8) * 255), "L")
    if radius > 0:
        image = image.filter(ImageFilter.GaussianBlur(radius))
    return image


def extract_layer(source: Image.Image, mask: np.ndarray, softness: float = 0.65) -> Image.Image:
    layer = Image.new("RGBA", source.size, (0, 0, 0, 0))
    layer.paste(source, (0, 0), soften_alpha(mask, softness))
    return layer


def paint_polygon_layer(
    size: tuple[int, int],
    points: list[tuple[int, int]],
    fill: tuple[int, int, int, int],
    blur: float = 1.0,
) -> Image.Image:
    mask = mask_from_polygon(size, points)
    image = Image.new("RGBA", size, fill)
    image.putalpha(soften_alpha(mask, blur))
    return image


def paint_ellipse_layer(
    size: tuple[int, int],
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    blur: float = 1.0,
) -> Image.Image:
    mask = mask_from_ellipse(size, box)
    image = Image.new("RGBA", size, fill)
    image.putalpha(soften_alpha(mask, blur))
    return image


def paint_curve_layer(
    size: tuple[int, int],
    points: list[tuple[int, int]],
    fill: tuple[int, int, int, int],
    width: int,
    blur: float = 0.25,
) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.line(points, fill=fill, width=width, joint="curve")
    if blur > 0:
        alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(blur))
        layer.putalpha(alpha)
    return layer


def paint_mouth_shape(
    size: tuple[int, int],
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    teeth: bool = False,
    tongue: bool = False,
) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse(box, fill=fill)
    if teeth:
        x0, y0, x1, y1 = box
        draw.pieslice((x0 + 2, y0 + 1, x1 - 2, y0 + (y1 - y0) * 0.52), 180, 360, fill=(252, 224, 213, 205))
    if tongue:
        x0, y0, x1, y1 = box
        draw.ellipse((x0 + 5, y0 + (y1 - y0) * 0.48, x1 - 5, y1 - 1), fill=(194, 93, 112, 190))
    alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(0.45))
    layer.putalpha(alpha)
    return layer


def save_layer(layer: Image.Image, relative_path: str) -> dict[str, object]:
    output_path = LAYERS_DIR / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    layer.save(output_path)
    alpha = np.asarray(layer.getchannel("A"))
    ys, xs = np.where(alpha > 0)
    bbox = None
    nontransparent = int((alpha > 0).sum())
    if nontransparent:
        bbox = [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]
    return {
        "file": str(Path("layers") / relative_path).replace("\\", "/"),
        "name": Path(relative_path).stem,
        "group": Path(relative_path).parts[0],
        "bbox": bbox,
        "nontransparentPixels": nontransparent,
    }


def make_contact_sheet(layer_records: list[dict[str, object]]) -> None:
    thumbs: list[tuple[str, Image.Image]] = []
    for record in layer_records:
        if record["nontransparentPixels"] == 0:
            continue
        layer = Image.open(OUTPUT_ROOT / record["file"]).convert("RGBA")
        bbox = layer.getbbox()
        if bbox is None:
            continue
        cropped = layer.crop(bbox)
        cropped.thumbnail((180, 120), Image.LANCZOS)
        thumbs.append((record["name"], cropped.copy()))

    columns = 4
    cell_w, cell_h = 260, 170
    rows = max(1, math.ceil(len(thumbs) / columns))
    sheet = Image.new("RGBA", (columns * cell_w, rows * cell_h), (28, 28, 30, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font = ImageFont.load_default()

    for index, (name, thumb) in enumerate(thumbs):
        col = index % columns
        row = index // columns
        x = col * cell_w
        y = row * cell_h
        checker = Image.new("RGBA", (cell_w - 24, cell_h - 48), (44, 44, 48, 255))
        checker_draw = ImageDraw.Draw(checker)
        for cy in range(0, checker.height, 16):
            for cx in range(0, checker.width, 16):
                if (cx // 16 + cy // 16) % 2 == 0:
                    checker_draw.rectangle((cx, cy, cx + 15, cy + 15), fill=(58, 58, 64, 255))
        sheet.alpha_composite(checker, (x + 12, y + 10))
        tx = x + 12 + (checker.width - thumb.width) // 2
        ty = y + 10 + (checker.height - thumb.height) // 2
        sheet.alpha_composite(thumb, (tx, ty))
        label = name[:34]
        draw.text((x + 12, y + cell_h - 32), label, fill=(235, 235, 238, 255), font=font)

    sheet.save(OUTPUT_ROOT / f"{DOC_NAME}_layer_contact_sheet.png")


def alpha_composite_preview(layer_records: list[dict[str, object]], hidden: set[str]) -> None:
    source, _, _ = load_source()
    composite = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for record in layer_records:
        name = str(record["name"])
        if name in hidden or name.endswith("_do_not_export") or "guide" in name:
            continue
        layer = Image.open(OUTPUT_ROOT / record["file"]).convert("RGBA")
        composite.alpha_composite(layer)
    composite.save(OUTPUT_ROOT / f"{DOC_NAME}_composite_preview.png")


def build_layers() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    source, rgba, alpha = load_source()
    size = source.size
    rgb = rgba[:, :, :3].astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b)
    dark = (luminance < 92) & alpha
    very_dark = (luminance < 58) & alpha
    skin = (r > 130) & (g > 82) & (b > 70) & (r > g + 18) & (r > b + 20) & alpha
    pink = (r > 118) & (b > 82) & (g < 126) & alpha
    cyan = (b > 130) & (g > 110) & (r < 95) & alpha
    warm_metal = (r > 105) & (g > 76) & (b < 78) & alpha
    light = (luminance > 150) & alpha

    regions = {
        "ear_screen_l": mask_from_polygon(size, [(450, 124), (526, 184), (610, 289), (568, 306), (496, 240), (455, 154)]),
        "ear_screen_r": mask_from_polygon(size, [(718, 114), (882, 40), (889, 188), (840, 265), (779, 216)]),
        "face": mask_from_polygon(size, [(595, 315), (735, 255), (854, 332), (844, 475), (769, 568), (633, 536), (574, 436)]),
        "neck": mask_from_polygon(size, [(716, 530), (816, 526), (838, 645), (696, 650)]),
        "eye_screen_l": mask_from_ellipse(size, (580, 330, 705, 412)),
        "eye_screen_r": mask_from_ellipse(size, (748, 318, 866, 398)),
        "mouth": mask_from_ellipse(size, (723, 493, 801, 544)),
        "brow_screen_l": mask_from_polygon(size, [(570, 302), (683, 288), (700, 326), (579, 342)]),
        "brow_screen_r": mask_from_polygon(size, [(743, 289), (854, 283), (865, 321), (748, 329)]),
        "hair_top": mask_from_polygon(size, [(494, 107), (657, 76), (798, 84), (878, 205), (849, 386), (703, 436), (550, 392), (486, 245)]),
        "hair_front_center": mask_from_polygon(size, [(596, 116), (715, 101), (785, 172), (793, 325), (731, 437), (633, 433), (579, 318)]),
        "hair_front_screen_l": mask_from_polygon(size, [(492, 176), (624, 181), (664, 345), (610, 504), (520, 438), (486, 287)]),
        "hair_front_screen_r": mask_from_polygon(size, [(718, 124), (866, 208), (861, 405), (783, 521), (716, 374)]),
        "hair_side_screen_l": mask_from_polygon(size, [(442, 206), (553, 330), (612, 548), (555, 832), (396, 941), (245, 912), (392, 668)]),
        "hair_side_screen_r": mask_from_polygon(size, [(826, 200), (996, 359), (1178, 693), (1278, 916), (1108, 953), (916, 780), (830, 502)]),
        "hair_tail_screen_l": mask_from_polygon(size, [(313, 565), (558, 688), (499, 936), (243, 925), (321, 784)]),
        "hair_tail_screen_r": mask_from_polygon(size, [(1006, 505), (1179, 714), (1280, 917), (1097, 950), (937, 795)]),
        "body_center": mask_from_polygon(size, [(607, 492), (866, 431), (1025, 558), (1010, 941), (617, 947), (505, 720)]),
        "jacket_screen_l": mask_from_polygon(size, [(381, 484), (628, 514), (700, 730), (598, 941), (372, 920), (327, 691)]),
        "jacket_screen_r": mask_from_polygon(size, [(826, 423), (1088, 414), (1169, 690), (1138, 917), (887, 947), (779, 722)]),
        "arm_screen_l": mask_from_polygon(size, [(473, 505), (670, 516), (740, 685), (600, 903), (408, 838), (390, 646)]),
        "arm_screen_r": mask_from_polygon(size, [(788, 688), (1089, 711), (1116, 936), (789, 945), (655, 856)]),
        "hand_face": mask_from_polygon(size, [(568, 418), (625, 382), (696, 414), (684, 507), (598, 532), (553, 489)]),
        "hand_front": mask_from_polygon(size, [(656, 821), (744, 825), (779, 899), (728, 952), (643, 932), (617, 870)]),
        "hair_clip": mask_from_polygon(size, [(795, 194), (881, 203), (881, 293), (789, 284)]),
        "earring_screen_r": mask_from_polygon(size, [(855, 296), (906, 293), (918, 526), (850, 530)]),
        "ear_charm_screen_l": mask_from_polygon(size, [(466, 205), (523, 218), (535, 352), (458, 351)]),
        "necklace": mask_from_polygon(size, [(733, 520), (834, 514), (862, 734), (731, 739)]),
        "sleeve_badge": mask_from_polygon(size, [(966, 606), (1088, 636), (1106, 783), (982, 806)]),
        "hanging_charm": mask_from_polygon(size, [(1046, 642), (1167, 643), (1187, 940), (1050, 944)]),
    }

    raw_masks: dict[str, np.ndarray] = {}
    raw_masks["hair_back_mass"] = (regions["hair_top"] | regions["hair_side_screen_l"] | regions["hair_side_screen_r"]) & dark
    raw_masks["hair_tail_screen_l"] = regions["hair_tail_screen_l"] & (dark | pink)
    raw_masks["hair_tail_screen_r"] = regions["hair_tail_screen_r"] & (dark | pink)
    raw_masks["hair_pink_tips_screen_l"] = regions["hair_tail_screen_l"] & pink
    raw_masks["hair_pink_tips_screen_r"] = regions["hair_tail_screen_r"] & pink
    raw_masks["cat_ear_screen_l_outer"] = regions["ear_screen_l"] & (dark | pink | light)
    raw_masks["cat_ear_screen_l_inner"] = regions["ear_screen_l"] & pink
    raw_masks["cat_ear_screen_r_outer"] = regions["ear_screen_r"] & (dark | pink | light)
    raw_masks["cat_ear_screen_r_inner"] = regions["ear_screen_r"] & pink
    raw_masks["face_base_visible"] = regions["face"] & skin
    raw_masks["neck_visible"] = regions["neck"] & skin
    raw_masks["brow_screen_l"] = regions["brow_screen_l"] & very_dark
    raw_masks["brow_screen_r"] = regions["brow_screen_r"] & very_dark
    raw_masks["eye_screen_l_white"] = regions["eye_screen_l"] & light & ~pink
    raw_masks["eye_screen_l_iris"] = regions["eye_screen_l"] & pink
    raw_masks["eye_screen_l_line"] = regions["eye_screen_l"] & dark
    raw_masks["eye_screen_r_white"] = regions["eye_screen_r"] & light & ~pink
    raw_masks["eye_screen_r_iris"] = regions["eye_screen_r"] & pink
    raw_masks["eye_screen_r_line"] = regions["eye_screen_r"] & dark
    raw_masks["mouth_closed_line_visible"] = regions["mouth"] & (dark | pink)
    raw_masks["hair_front_center"] = regions["hair_front_center"] & dark
    raw_masks["hair_front_screen_l"] = regions["hair_front_screen_l"] & dark
    raw_masks["hair_front_screen_r"] = regions["hair_front_screen_r"] & dark
    raw_masks["hair_bangs_over_eyes"] = (regions["eye_screen_l"] | regions["eye_screen_r"]) & dark
    raw_masks["jacket_screen_l_sleeve"] = regions["jacket_screen_l"] & dark
    raw_masks["jacket_screen_r_sleeve"] = regions["jacket_screen_r"] & dark
    raw_masks["torso_inner_and_collar"] = regions["body_center"] & dark
    raw_masks["pink_cuff_and_strap_accents"] = (regions["body_center"] | regions["jacket_screen_l"] | regions["jacket_screen_r"]) & pink
    raw_masks["hand_screen_l_at_cheek"] = regions["hand_face"] & skin
    raw_masks["hand_screen_r_front"] = regions["hand_front"] & skin
    raw_masks["hair_clip_screen_r"] = regions["hair_clip"] & (warm_metal | dark | light)
    raw_masks["earring_screen_r"] = regions["earring_screen_r"] & (warm_metal | dark | pink)
    raw_masks["ear_charm_screen_l"] = regions["ear_charm_screen_l"] & alpha
    raw_masks["necklace_and_center_charm"] = regions["necklace"] & (warm_metal | cyan | dark)
    raw_masks["sleeve_device_badge"] = regions["sleeve_badge"] & (cyan | warm_metal | dark | pink | light)
    raw_masks["hanging_keychain_charm"] = regions["hanging_charm"] & (cyan | warm_metal | dark | pink | light)
    raw_masks["cyan_status_lights"] = cyan

    layer_records: list[dict[str, object]] = []
    layer_defs: list[dict[str, object]] = []

    def add(layer: Image.Image, group: str, name: str, purpose: str, visible: bool = True) -> None:
        record = save_layer(layer, f"{group}/{name}.png")
        record.update({"purpose": purpose, "visible": visible})
        layer_records.append(record)
        layer_defs.append(
            {
                "group": group,
                "name": name,
                "file": record["file"],
                "visible": visible,
                "purpose": purpose,
                "bbox": record["bbox"],
                "nontransparentPixels": record["nontransparentPixels"],
            }
        )

    add(source, "00_reference_do_not_export", "painted_full_character_reference", "Original merged artwork for visual checking only.", False)

    add(paint_polygon_layer(size, [(548, 260), (742, 205), (868, 310), (860, 527), (765, 631), (592, 560), (526, 392)], (236, 177, 163, 236), 4.0), "10_auto_underfills", "head_face_under_bangs_auto_fill", "Painted skin continuation behind bangs for blink/head-angle rigging.", False)
    add(paint_polygon_layer(size, [(464, 105), (690, 45), (900, 71), (934, 376), (833, 560), (511, 517), (409, 249)], (28, 24, 31, 240), 5.0), "10_auto_underfills", "hair_back_under_ears_auto_fill", "Dark hair mass under ears and front hair for ear/head movement.", False)
    add(paint_polygon_layer(size, [(494, 465), (866, 398), (1130, 593), (1128, 944), (483, 949), (362, 706)], (31, 29, 36, 236), 5.0), "10_auto_underfills", "torso_under_arms_auto_fill", "Jacket/body continuation under arms for breath and wave motion.", False)
    add(paint_polygon_layer(size, [(548, 451), (685, 430), (728, 545), (626, 612), (520, 558)], (236, 176, 160, 220), 3.0), "10_auto_underfills", "cheek_hand_overlap_skin_fill", "Skin patch hidden behind the cheek hand.", False)
    add(paint_polygon_layer(size, [(622, 796), (779, 793), (805, 948), (596, 956)], (30, 28, 34, 235), 4.0), "10_auto_underfills", "front_hand_under_sleeve_fill", "Sleeve/body continuation behind the front hand.", False)

    for name in [
        "hair_back_mass",
        "hair_tail_screen_l",
        "hair_tail_screen_r",
        "hair_pink_tips_screen_l",
        "hair_pink_tips_screen_r",
    ]:
        add(extract_layer(source, raw_masks[name]), "20_back_hair", name, "Visible source pixels split for back hair physics and hair sway.")

    for name in [
        "neck_visible",
        "torso_inner_and_collar",
        "jacket_screen_l_sleeve",
        "jacket_screen_r_sleeve",
        "pink_cuff_and_strap_accents",
    ]:
        add(extract_layer(source, raw_masks[name]), "30_body_and_clothes", name, "Body/clothing layer for breath, body angle, and sleeve secondary motion.")

    for name in [
        "cat_ear_screen_l_outer",
        "cat_ear_screen_l_inner",
        "cat_ear_screen_r_outer",
        "cat_ear_screen_r_inner",
        "face_base_visible",
    ]:
        add(extract_layer(source, raw_masks[name]), "40_head_face_ears", name, "Head/ear/face source layer for head angle, ear flick, and expressions.")
    add(paint_ellipse_layer(size, (615, 452, 701, 535), (241, 141, 149, 72), 7.0), "40_head_face_ears", "cheek_blush_screen_l", "Soft blush overlay for warm/listening expressions.", False)
    add(paint_ellipse_layer(size, (760, 438, 850, 522), (241, 141, 149, 62), 7.0), "40_head_face_ears", "cheek_blush_screen_r", "Soft blush overlay for warm/listening expressions.", False)
    add(paint_ellipse_layer(size, (720, 408, 752, 436), (251, 219, 203, 150), 1.5), "40_head_face_ears", "nose_highlight", "Small nose highlight separated for face-angle cleanup.", False)

    for name in [
        "eye_screen_l_white",
        "eye_screen_l_iris",
        "eye_screen_l_line",
        "eye_screen_r_white",
        "eye_screen_r_iris",
        "eye_screen_r_line",
    ]:
        add(extract_layer(source, raw_masks[name]), "50_eyes_blink", name, "Eye component for blink, gaze, and serious-looking states.")
    add(paint_ellipse_layer(size, (584, 327, 704, 414), (229, 173, 162, 230), 1.8), "50_eyes_blink", "eye_screen_l_lid_cover_for_blink", "Skin-toned blink cover; hide by default and drive with ParamEyeLOpen.", False)
    add(paint_curve_layer(size, [(592, 374), (632, 391), (688, 375)], (56, 34, 40, 230), 5, 0.45), "50_eyes_blink", "eye_screen_l_closed_lid_line", "Closed-eye curved line for blink/sleep expression.", False)
    add(paint_ellipse_layer(size, (749, 315, 869, 402), (229, 173, 162, 230), 1.8), "50_eyes_blink", "eye_screen_r_lid_cover_for_blink", "Skin-toned blink cover; hide by default and drive with ParamEyeROpen.", False)
    add(paint_curve_layer(size, [(758, 360), (806, 377), (858, 358)], (56, 34, 40, 230), 5, 0.45), "50_eyes_blink", "eye_screen_r_closed_lid_line", "Closed-eye curved line for blink/sleep expression.", False)
    add(extract_layer(source, raw_masks["brow_screen_l"]), "55_brows", "brow_screen_l", "Brow source pixels for serious/thinking expression.")
    add(extract_layer(source, raw_masks["brow_screen_r"]), "55_brows", "brow_screen_r", "Brow source pixels for serious/thinking expression.")

    add(extract_layer(source, raw_masks["mouth_closed_line_visible"]), "60_mouth_lipsync", "mouth_closed_line_visible", "Original small smile mouth line.")
    add(paint_mouth_shape(size, (733, 507, 790, 538), (58, 22, 32, 225), teeth=True, tongue=True), "60_mouth_lipsync", "mouth_open_a_inner", "Open A mouth inner for speech/lip-sync.", False)
    add(paint_mouth_shape(size, (744, 503, 781, 543), (54, 20, 34, 225), tongue=True), "60_mouth_lipsync", "mouth_open_o_inner", "Rounded O mouth inner for speech/lip-sync.", False)
    add(paint_curve_layer(size, [(724, 505), (756, 529), (799, 501)], (96, 40, 50, 210), 4, 0.35), "60_mouth_lipsync", "mouth_smile_form_overlay", "Smile-form overlay for warm talk and idle.", False)
    add(paint_curve_layer(size, [(731, 525), (760, 514), (793, 526)], (72, 34, 45, 210), 4, 0.35), "60_mouth_lipsync", "mouth_serious_form_overlay", "Flatter mouth overlay for serious checking/thinking.", False)

    for name in [
        "hair_front_center",
        "hair_front_screen_l",
        "hair_front_screen_r",
        "hair_bangs_over_eyes",
    ]:
        add(extract_layer(source, raw_masks[name]), "70_front_hair", name, "Front hair clump for head angle, blink clearance, and subtle physics.")
    add(extract_layer(source, regions["hair_side_screen_l"] & dark), "70_front_hair", "long_side_locks_screen_l", "Long side lock source pixels for hair physics.")
    add(extract_layer(source, regions["hair_side_screen_r"] & dark), "70_front_hair", "long_side_locks_screen_r", "Long side lock source pixels for hair physics.")

    add(extract_layer(source, raw_masks["hand_screen_l_at_cheek"]), "80_arms_hands_wave", "hand_screen_l_at_cheek", "Separated visible hand for cheek pose and potential wave source.")
    add(extract_layer(source, raw_masks["hand_screen_r_front"]), "80_arms_hands_wave", "hand_screen_r_front", "Separated visible front hand for subtle gesture or breathing overlap.")
    add(extract_layer(source, regions["arm_screen_l"] & dark), "80_arms_hands_wave", "arm_screen_l_sleeve", "Left-screen sleeve for arm pose and wave-ready separation.")
    add(extract_layer(source, regions["arm_screen_r"] & dark), "80_arms_hands_wave", "arm_screen_r_folded_sleeve", "Right-screen folded sleeve for idle/breath motion.")
    add(paint_polygon_layer(size, [(472, 475), (642, 430), (703, 553), (586, 651), (442, 589)], (30, 28, 35, 230), 3.5), "80_arms_hands_wave", "arm_screen_l_wave_socket_underfill", "Dark sleeve socket underfill used when lifting the cheek-side arm.", False)
    add(paint_polygon_layer(size, [(585, 375), (674, 356), (715, 421), (670, 501), (568, 491)], (234, 173, 159, 210), 3.0), "80_arms_hands_wave", "hand_wave_source_proxy", "Proxy repaint guide for a future raised-hand wave pose; replace with hand-drawn art before final export.", False)

    for name in [
        "hair_clip_screen_r",
        "earring_screen_r",
        "ear_charm_screen_l",
        "necklace_and_center_charm",
        "sleeve_device_badge",
        "hanging_keychain_charm",
        "cyan_status_lights",
    ]:
        add(extract_layer(source, raw_masks[name]), "90_accessories_props", name, "Accessory/prop detail layer for status and secondary motion.")

    covered = np.zeros_like(alpha)
    for name, mask in raw_masks.items():
        if name not in {"cyan_status_lights"}:
            covered |= blur_mask(mask, 1.2)
    recovery = alpha & ~covered
    add(extract_layer(source, recovery, softness=0.35), "99_recovery_review", "visible_unassigned_recovery", "Pixels not confidently assigned by the automated split; review and merge into final hand-cleaned layers.")

    return layer_records, layer_defs


def write_manifest(layer_defs: list[dict[str, object]]) -> None:
    manifest = {
        "version": 1,
        "source": str(SOURCE_IMAGE.relative_to(REPO_ROOT)).replace("\\", "/"),
        "canvas": {"width": 1484, "height": 1060},
        "outputIntent": "Layered Live2D source-art split from a merged PNG. Keep as source PSD/PNG package, then hand-clean and rig in Live2D Cubism Editor.",
        "coordinateConvention": "screen_l/screen_r refer to the visible image side, not character anatomical left/right.",
        "actionsRequested": [
            "breath",
            "blink",
            "ear_flick",
            "mouth_lip_sync",
            "wave",
            "idle_wait",
            "thinking",
            "serious_inspect",
        ],
        "recommendedParameters": {
            "breath": ["ParamBreath", "ParamBodyAngleY", "ParamBodyAngleZ"],
            "blink": ["ParamEyeLOpen", "ParamEyeROpen"],
            "ear_flick": ["ParamEarScreenLAngle", "ParamEarScreenRAngle", "ParamEarScreenLForm", "ParamEarScreenRForm"],
            "mouth_lip_sync": ["ParamMouthOpenY", "ParamMouthForm"],
            "wave": ["ParamArmScreenL", "ParamHandScreenL", "ParamBodyAngleZ"],
            "idle_wait": ["ParamAngleX", "ParamAngleY", "ParamEyeBallX", "ParamEyeBallY"],
            "thinking": ["ParamBrowY", "ParamEyeBallY", "ParamMouthForm"],
            "serious_inspect": ["ParamBrowAngle", "ParamEyeBallX", "ParamBodyAngleY"],
        },
        "layers": layer_defs,
        "notes": [
            "This is an automated production-prep split from a single flattened illustration, not a replacement for final hand-painted Live2D source art.",
            "All PNG layers keep full canvas size and can be imported into Photoshop/Cubism without coordinate drift.",
            "Layers ending in auto_fill/proxy/recovery should be reviewed by an artist before final Cubism texture export.",
            "For a convincing wave, redraw the wave proxy into a true raised arm/hand layer before final rigging.",
        ],
    }
    (OUTPUT_ROOT / f"{DOC_NAME}.layer-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_rigging_notes(layer_defs: list[dict[str, object]]) -> None:
    lines = [
        "# Character Live2D Split Rigging Notes",
        "",
        "Source image: `apps/desktop/public/images/character.png`",
        "",
        "This package is split for the requested actions: breath, blink, ear flick, mouth/lip sync, wave, idle/wait, thinking, and serious inspection. It intentionally does not depend on the current app action table.",
        "",
        "## Important Limits",
        "",
        "- The input is a flattened PNG. Hidden art under hair, hands, sleeves, and mouth/eyes was estimated with `*_auto_fill`, blink cover, mouth-inner, and proxy layers.",
        "- Review `visible_unassigned_recovery` and move useful pixels into semantic layers before final Cubism export.",
        "- For a real waving motion, repaint `hand_wave_source_proxy` and `arm_screen_l_wave_socket_underfill` into a proper raised-arm pose. The current source pose does not contain a raised hand.",
        "",
        "## Layer Groups",
        "",
    ]
    groups: dict[str, list[dict[str, object]]] = {}
    for layer in layer_defs:
        groups.setdefault(str(layer["group"]), []).append(layer)
    for group, items in groups.items():
        lines.append(f"### {group}")
        for item in items:
            visibility = "visible" if item["visible"] else "hidden"
            lines.append(f"- `{item['name']}` ({visibility}): {item['purpose']}")
        lines.append("")

    lines.extend(
        [
            "## Motion-Oriented Split Map",
            "",
            "| Motion need | Required layers | Notes |",
            "| --- | --- | --- |",
            "| Breath | `torso_inner_and_collar`, jacket sleeve layers, hair tails | Drive with low-amplitude body Y/Z and subtle hair physics. |",
            "| Blink | eye whites/iris/line layers plus blink covers and closed lid lines | Blink covers are hidden helper layers; drive them opposite open-eye visibility. |",
            "| Ear flick | cat ear outer/inner layers, hair underfill | Rotate ears from their bases; keep hair underfill below them. |",
            "| Speech | mouth closed line plus `mouth_open_a_inner`, `mouth_open_o_inner`, form overlays | Use `ParamMouthOpenY` and `ParamMouthForm`; do not stretch the face base. |",
            "| Wave | `hand_screen_l_at_cheek`, `arm_screen_l_sleeve`, wave socket/proxy | Needs artist repaint for production-quality raised hand. |",
            "| Wait | back/front hair, eyes, body, accessories | Idle loops should stay subtle for desktop-pet readability. |",
            "| Thinking | brow layers, gaze layers, mouth serious overlay, hair/front hand | Lower brows slightly, look upward/sideways, reduce mouth smile. |",
            "| Serious inspect | brow layers, eye line layers, body lean, mouth serious overlay | Keep movements small and attentive rather than dramatic. |",
            "",
            "## Photoshop",
            "",
            "Run `assemble-character-live2d-split.jsx` in Photoshop to rebuild the grouped PSD. The script saves `character_live2d_split_layered.psd` in this folder.",
            "",
        ]
    )
    (OUTPUT_ROOT / "LIVE2D_SPLIT_RIGGING_NOTES.md").write_text("\n".join(lines), encoding="utf-8")


def write_photoshop_script(layer_defs: list[dict[str, object]]) -> None:
    payload = {
        "docName": DOC_NAME,
        "width": 1484,
        "height": 1060,
        "root": str(OUTPUT_ROOT).replace("\\", "/"),
        "psd": str((OUTPUT_ROOT / f"{DOC_NAME}_layered.psd")).replace("\\", "/"),
        "layers": layer_defs,
    }
    script = f"""#target photoshop
app.displayDialogs = DialogModes.NO;

var payload = {json.dumps(payload, ensure_ascii=False, indent=2)};

function ensureGroup(doc, groupName) {{
  for (var i = 0; i < doc.layerSets.length; i++) {{
    if (doc.layerSets[i].name === groupName) {{
      return doc.layerSets[i];
    }}
  }}
  var group = doc.layerSets.add();
  group.name = groupName;
  return group;
}}

function importPngLayer(targetDoc, group, layerInfo) {{
  var file = new File(payload.root + "/" + layerInfo.file);
  if (!file.exists) {{
    throw new Error("Missing layer PNG: " + file.fsName);
  }}
  var sourceDoc = app.open(file);
  app.activeDocument = sourceDoc;
  sourceDoc.activeLayer.name = layerInfo.name;
  sourceDoc.activeLayer.duplicate(targetDoc, ElementPlacement.PLACEATBEGINNING);
  sourceDoc.close(SaveOptions.DONOTSAVECHANGES);
  app.activeDocument = targetDoc;
  var imported = targetDoc.activeLayer;
  imported.name = layerInfo.name;
  imported.visible = layerInfo.visible;
  imported.move(group, ElementPlacement.INSIDE);
}}

var targetDoc = app.documents.add(
  payload.width,
  payload.height,
  72,
  payload.docName,
  NewDocumentMode.RGB,
  DocumentFill.TRANSPARENT
);

var groups = {{}};
for (var i = payload.layers.length - 1; i >= 0; i--) {{
  var layerInfo = payload.layers[i];
  if (!groups[layerInfo.group]) {{
    groups[layerInfo.group] = ensureGroup(targetDoc, layerInfo.group);
  }}
  importPngLayer(targetDoc, groups[layerInfo.group], layerInfo);
}}

app.activeDocument = targetDoc;
var saveFile = new File(payload.psd);
var saveOptions = new PhotoshopSaveOptions();
saveOptions.layers = true;
targetDoc.saveAs(saveFile, saveOptions, true, Extension.LOWERCASE);
"""
    (OUTPUT_ROOT / "assemble-character-live2d-split.jsx").write_text(script, encoding="utf-8")


def main() -> None:
    if not SOURCE_IMAGE.exists():
        raise FileNotFoundError(SOURCE_IMAGE)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    LAYERS_DIR.mkdir(parents=True, exist_ok=True)

    layer_records, layer_defs = build_layers()
    write_manifest(layer_defs)
    write_rigging_notes(layer_defs)
    write_photoshop_script(layer_defs)
    make_contact_sheet(layer_records)
    hidden = {str(layer["name"]) for layer in layer_defs if not layer["visible"]}
    alpha_composite_preview(layer_records, hidden)

    summary = {
        "source": str(SOURCE_IMAGE),
        "output": str(OUTPUT_ROOT),
        "layers": len(layer_defs),
        "visibleLayers": sum(1 for layer in layer_defs if layer["visible"]),
        "hiddenHelperLayers": sum(1 for layer in layer_defs if not layer["visible"]),
        "contactSheet": str(OUTPUT_ROOT / f"{DOC_NAME}_layer_contact_sheet.png"),
        "photoshopScript": str(OUTPUT_ROOT / "assemble-character-live2d-split.jsx"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
