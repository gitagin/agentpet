from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_IMAGE = REPO_ROOT / "apps" / "desktop" / "public" / "images" / "character.png"
OUTPUT_ROOT = REPO_ROOT / "apps" / "desktop" / "public" / "live2d" / "character_live2d_standard_split"
LAYERS_DIR = OUTPUT_ROOT / "layers"
QA_DIR = OUTPUT_ROOT / "qa"
IMPORT_PSD_NAME = "character_live2d_import.psd"
EDIT_PSD_NAME = "character_live2d_edit.psd"


@dataclass
class LayerRecord:
    order: int
    filename: str
    name: str
    group: str
    visible: bool
    purpose: str
    nontransparent_pixels: int
    bbox: list[int] | None


def load_source() -> tuple[Image.Image, dict[str, np.ndarray]]:
    source = Image.open(SOURCE_IMAGE).convert("RGBA")
    rgba = np.asarray(source)
    alpha = rgba[:, :, 3] > 8
    rgb = rgba[:, :, :3].astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b)
    yy, xx = np.indices(alpha.shape)
    channels = {
        "alpha": alpha,
        "dark": (lum < 105) & alpha,
        "very_dark": (lum < 62) & alpha,
        "mid_dark": (lum >= 62) & (lum < 135) & alpha,
        "skin": (r > 126) & (g > 72) & (b > 60) & (r > g + 14) & (r > b + 16) & alpha,
        "pink": (r > 112) & (b > 74) & (g < 138) & alpha,
        "cyan": (b > 118) & (g > 98) & (r < 110) & alpha,
        "metal": (r > 92) & (g > 66) & (b < 92) & alpha,
        "light": (lum > 148) & alpha,
        "x": xx,
        "y": yy,
    }
    return source, channels


def aa_mask(size: tuple[int, int], draw_fn, scale: int = 3, blur: float = 0.0) -> np.ndarray:
    w, h = size
    mask = Image.new("L", (w * scale, h * scale), 0)
    draw = ImageDraw.Draw(mask)

    def sc_point(point: tuple[int, int]) -> tuple[int, int]:
        return point[0] * scale, point[1] * scale

    draw_fn(draw, sc_point, scale)
    mask = mask.resize(size, Image.Resampling.LANCZOS)
    if blur:
        mask = mask.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(mask) > 4


def poly(size: tuple[int, int], points: list[tuple[int, int]], blur: float = 0.0) -> np.ndarray:
    return aa_mask(size, lambda draw, sc, _scale: draw.polygon([sc(point) for point in points], fill=255), blur=blur)


def ellipse(size: tuple[int, int], box: tuple[int, int, int, int], blur: float = 0.0) -> np.ndarray:
    return aa_mask(
        size,
        lambda draw, _sc, scale: draw.ellipse(tuple(value * scale for value in box), fill=255),
        blur=blur,
    )


def rect(size: tuple[int, int], box: tuple[int, int, int, int], blur: float = 0.0) -> np.ndarray:
    return aa_mask(
        size,
        lambda draw, _sc, scale: draw.rectangle(tuple(value * scale for value in box), fill=255),
        blur=blur,
    )


def line_layer(size: tuple[int, int], points: list[tuple[int, int]], color: tuple[int, int, int, int], width: int, blur: float = 0.2) -> Image.Image:
    scale = 3
    layer = Image.new("RGBA", (size[0] * scale, size[1] * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.line([(x * scale, y * scale) for x, y in points], fill=color, width=width * scale, joint="curve")
    layer = layer.resize(size, Image.Resampling.LANCZOS)
    if blur:
        alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(blur))
        layer.putalpha(alpha)
    return layer


def mask_to_alpha(mask: np.ndarray, blur: float = 0.45) -> Image.Image:
    alpha = Image.fromarray((mask.astype(np.uint8) * 255), "L")
    if blur:
        alpha = alpha.filter(ImageFilter.GaussianBlur(blur))
    return alpha


def solid_layer(size: tuple[int, int], mask: np.ndarray, color: tuple[int, int, int, int], blur: float = 0.35) -> Image.Image:
    layer = Image.new("RGBA", size, color)
    layer.putalpha(mask_to_alpha(mask, blur))
    return layer


def source_extract(source: Image.Image, mask: np.ndarray, blur: float = 0.25) -> Image.Image:
    layer = Image.new("RGBA", source.size, (0, 0, 0, 0))
    layer.paste(source, (0, 0), mask_to_alpha(mask, blur))
    return layer


def shade_layer(size: tuple[int, int], mask: np.ndarray, color: tuple[int, int, int, int], blur: float = 3.0) -> Image.Image:
    return solid_layer(size, mask, color, blur)


def save_layer(image: Image.Image, order: int, filename_stem: str, name: str, group: str, visible: bool, purpose: str) -> LayerRecord:
    filename = f"{order:03d}_{filename_stem}.png"
    path = LAYERS_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    alpha = np.asarray(image.getchannel("A"))
    ys, xs = np.where(alpha > 0)
    bbox = None
    if xs.size:
        bbox = [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]
    return LayerRecord(order, filename, name, group, visible, purpose, int((alpha > 0).sum()), bbox)


def build_layers() -> list[LayerRecord]:
    source, ch = load_source()
    size = source.size
    records: list[LayerRecord] = []

    def add(order: int, stem: str, name: str, group: str, image: Image.Image, visible: bool = True, purpose: str = "") -> None:
        records.append(save_layer(image, order, stem, name, group, visible, purpose))

    alpha = ch["alpha"]
    dark = ch["dark"]
    skin = ch["skin"]
    pink = ch["pink"]
    cyan = ch["cyan"]
    metal = ch["metal"]
    light = ch["light"]
    very_dark = ch["very_dark"]

    # Large semantic masks. screen_l/screen_r means image side, not character anatomy.
    face_full = poly(size, [(560, 292), (705, 230), (855, 315), (862, 474), (776, 590), (612, 555), (538, 430)])
    face_visible = face_full & skin
    neck_full = poly(size, [(690, 507), (832, 505), (858, 660), (680, 665)])
    ear_l = poly(size, [(449, 118), (528, 178), (618, 292), (570, 315), (492, 244), (452, 150)])
    ear_r = poly(size, [(714, 112), (885, 38), (892, 185), (838, 270), (776, 218)])
    eye_l = ellipse(size, (575, 324, 710, 418))
    eye_r = ellipse(size, (742, 310, 874, 407))
    brow_l = poly(size, [(565, 299), (684, 286), (704, 327), (575, 343)])
    brow_r = poly(size, [(740, 287), (856, 281), (868, 322), (746, 331)])
    mouth = ellipse(size, (719, 489, 806, 548))
    back_hair = poly(size, [(452, 104), (657, 70), (804, 83), (892, 208), (865, 410), (720, 458), (540, 412), (474, 250)])
    hair_side_l = poly(size, [(425, 206), (556, 330), (620, 552), (555, 835), (390, 948), (236, 920), (390, 666)])
    hair_side_r = poly(size, [(827, 198), (1000, 360), (1182, 690), (1282, 922), (1103, 956), (913, 782), (826, 502)])
    tail_l = poly(size, [(306, 558), (562, 684), (506, 942), (239, 930), (320, 780)])
    tail_r = poly(size, [(1004, 502), (1182, 710), (1281, 922), (1092, 956), (936, 792)])
    bang_center = poly(size, [(590, 112), (716, 98), (790, 172), (797, 328), (730, 446), (628, 438), (576, 318)])
    bang_l = poly(size, [(486, 170), (626, 180), (668, 346), (612, 510), (516, 444), (482, 286)])
    bang_r = poly(size, [(716, 120), (870, 206), (866, 408), (782, 528), (714, 374)])
    lock_l = poly(size, [(382, 278), (560, 372), (598, 786), (416, 948), (306, 820), (392, 548)])
    lock_r = poly(size, [(846, 294), (1026, 408), (1118, 792), (1048, 952), (916, 786), (832, 504)])
    body = poly(size, [(600, 490), (870, 426), (1030, 558), (1020, 946), (612, 954), (504, 720)])
    jacket_l = poly(size, [(372, 478), (630, 512), (704, 732), (600, 948), (368, 926), (320, 690)])
    jacket_r = poly(size, [(824, 420), (1090, 410), (1172, 692), (1140, 926), (886, 954), (776, 724)])
    arm_l = poly(size, [(470, 494), (672, 512), (744, 690), (598, 912), (400, 842), (386, 642)])
    arm_r = poly(size, [(785, 682), (1100, 704), (1122, 948), (785, 954), (648, 852)])
    hand_cheek = poly(size, [(563, 414), (626, 380), (700, 414), (686, 510), (596, 536), (548, 488)])
    hand_front = poly(size, [(652, 816), (746, 820), (784, 900), (728, 958), (638, 936), (614, 868)])
    clip = poly(size, [(790, 190), (884, 201), (884, 294), (786, 288)])
    earring_r = poly(size, [(850, 292), (908, 292), (920, 532), (846, 532)])
    charm_l = poly(size, [(466, 204), (526, 216), (538, 354), (456, 354)])
    necklace = poly(size, [(725, 508), (838, 510), (866, 742), (724, 744)])
    device = poly(size, [(958, 596), (1092, 630), (1112, 812), (976, 812)])
    keychain = poly(size, [(1040, 640), (1174, 640), (1190, 946), (1044, 948)])

    add(1, "reference_original_do_not_import", "参考原图_不导入", "00_reference", source, False, "Original image for manual checking only.")

    add(10, "hair_back_under_fill", "后发_完整底色补全", "10_back_hair", solid_layer(size, back_hair | hair_side_l | hair_side_r, (30, 27, 35, 245)), True, "Complete dark back-hair plate under ears, face and front hair.")
    add(11, "hair_back_visible_texture", "后发_可见原画纹理", "10_back_hair", source_extract(source, (back_hair | hair_side_l | hair_side_r) & dark), True, "Original visible pixels on back hair.")
    add(12, "hair_tail_l_base", "左屏后发尾_底色", "10_back_hair", solid_layer(size, tail_l, (33, 28, 36, 240)), True, "Complete left-screen hair tail base.")
    add(13, "hair_tail_l_texture", "左屏后发尾_原画纹理", "10_back_hair", source_extract(source, tail_l & alpha), True, "Visible source texture for left-screen hair tail.")
    add(14, "hair_tail_r_base", "右屏后发尾_底色", "10_back_hair", solid_layer(size, tail_r, (34, 29, 37, 240)), True, "Complete right-screen hair tail base.")
    add(15, "hair_tail_r_texture", "右屏后发尾_原画纹理", "10_back_hair", source_extract(source, tail_r & alpha), True, "Visible source texture for right-screen hair tail.")
    add(16, "hair_tail_pink_inner_l", "左屏粉色发尾_独立", "10_back_hair", source_extract(source, tail_l & pink), True, "Pink hair-tip color separated for physics and color cleanup.")
    add(17, "hair_tail_pink_inner_r", "右屏粉色发尾_独立", "10_back_hair", source_extract(source, tail_r & pink), True, "Pink hair-tip color separated for physics and color cleanup.")

    add(20, "body_shadow_back", "身体后侧大阴影", "20_body", shade_layer(size, body | jacket_l | jacket_r, (0, 0, 0, 42), 7), True, "Soft back shadow under clothing.")
    add(21, "torso_inner_base_complete", "躯干内衫_完整底色", "20_body", solid_layer(size, body, (31, 29, 36, 245)), True, "Complete torso/inner clothing base.")
    add(22, "torso_inner_visible_texture", "躯干内衫_原画纹理", "20_body", source_extract(source, body & dark), True, "Visible source pixels for torso.")
    add(23, "jacket_l_back_panel", "左屏外套后片", "20_body", solid_layer(size, jacket_l, (32, 30, 37, 240)), True, "Left-screen jacket back/side panel.")
    add(24, "jacket_l_visible_texture", "左屏外套_原画纹理", "20_body", source_extract(source, jacket_l & alpha), True, "Visible source pixels for left-screen jacket.")
    add(25, "jacket_r_back_panel", "右屏外套后片", "20_body", solid_layer(size, jacket_r, (32, 30, 37, 240)), True, "Right-screen jacket back/side panel.")
    add(26, "jacket_r_visible_texture", "右屏外套_原画纹理", "20_body", source_extract(source, jacket_r & alpha), True, "Visible source pixels for right-screen jacket.")
    add(27, "cuff_and_strap_pink_accents", "袖口与绑带粉色细节", "20_body", source_extract(source, (body | jacket_l | jacket_r | arm_l | arm_r) & pink), True, "Pink cuffs/straps separated as details.")
    add(28, "torso_under_arms_repaint", "手臂下方衣服补全", "20_body", solid_layer(size, poly(size, [(490, 465), (870, 396), (1135, 590), (1130, 955), (480, 958), (355, 705)]), (31, 29, 36, 235)), False, "Hidden repaint fill for arm/body motion.")

    add(35, "neck_base_complete", "脖子_完整底色", "30_head_face", solid_layer(size, neck_full, (229, 170, 157, 235)), True, "Complete neck base under collar and hair.")
    add(36, "neck_visible_texture", "脖子_原画纹理", "30_head_face", source_extract(source, neck_full & skin), True, "Visible source pixels for neck.")
    add(40, "face_base_complete", "脸部_完整纯色底", "30_head_face", solid_layer(size, face_full, (232, 174, 160, 245)), True, "Complete face plate under bangs and hand.")
    add(41, "face_visible_texture", "脸部_原画肤色纹理", "30_head_face", source_extract(source, face_visible), True, "Visible face source pixels.")
    add(42, "face_contour_shadow", "脸部外轮廓阴影", "30_head_face", shade_layer(size, face_full & ~ellipse(size, (590, 306, 836, 552)), (96, 46, 56, 44), 4), True, "Outer face shadow separated in normal blend.")
    add(43, "cheek_blush_l", "左屏腮红", "30_head_face", solid_layer(size, ellipse(size, (610, 442, 710, 535), 2), (238, 125, 139, 70), 6), True, "Soft blush detail.")
    add(44, "cheek_blush_r", "右屏腮红", "30_head_face", solid_layer(size, ellipse(size, (758, 430, 858, 526), 2), (238, 125, 139, 65), 6), True, "Soft blush detail.")
    add(45, "nose_highlight", "鼻尖高光", "30_head_face", solid_layer(size, ellipse(size, (720, 404, 754, 438)), (251, 224, 207, 160), 1), True, "Nose highlight separated.")
    add(46, "hair_cast_shadow_on_face", "头发投在脸上的阴影", "30_head_face", shade_layer(size, (bang_center | bang_l | bang_r) & face_full, (26, 16, 26, 74), 3), True, "Hair-to-face shadow, normal blend.")
    add(47, "hand_cast_shadow_on_face", "手投在脸上的阴影", "30_head_face", shade_layer(size, hand_cheek & face_full, (86, 44, 52, 62), 4), True, "Hand-to-face shadow, normal blend.")

    add(50, "ear_l_outer_complete", "左屏猫耳_外轮廓", "35_ears", solid_layer(size, ear_l, (34, 29, 38, 245)), True, "Complete left-screen cat ear outer part.")
    add(51, "ear_l_outer_texture", "左屏猫耳_原画纹理", "35_ears", source_extract(source, ear_l & alpha), True, "Visible pixels for left-screen cat ear.")
    add(52, "ear_l_inner_fur", "左屏猫耳_内毛", "35_ears", solid_layer(size, poly(size, [(474, 154), (526, 192), (588, 276), (536, 262), (492, 225)]), (202, 121, 135, 220)), True, "Inner ear fur/pink area.")
    add(53, "ear_l_inner_texture", "左屏猫耳_内毛纹理", "35_ears", source_extract(source, ear_l & pink), True, "Original pink/light inner ear pixels.")
    add(54, "ear_r_outer_complete", "右屏猫耳_外轮廓", "35_ears", solid_layer(size, ear_r, (35, 30, 39, 245)), True, "Complete right-screen cat ear outer part.")
    add(55, "ear_r_outer_texture", "右屏猫耳_原画纹理", "35_ears", source_extract(source, ear_r & alpha), True, "Visible pixels for right-screen cat ear.")
    add(56, "ear_r_inner_fur", "右屏猫耳_内毛", "35_ears", solid_layer(size, poly(size, [(798, 88), (870, 60), (868, 170), (834, 236), (790, 202)]), (208, 126, 140, 220)), True, "Inner ear fur/pink area.")
    add(57, "ear_r_inner_texture", "右屏猫耳_内毛纹理", "35_ears", source_extract(source, ear_r & pink), True, "Original pink/light inner ear pixels.")

    def eye_layers(prefix_order: int, side: str, mask: np.ndarray, cx: int, cy: int) -> None:
        label = "左屏" if side == "l" else "右屏"
        add(prefix_order, f"eye_{side}_white_complete", f"{label}眼白_完整", "40_eyes", solid_layer(size, mask, (245, 214, 206, 235)), True, "Complete eye white mask.")
        add(prefix_order + 1, f"eye_{side}_white_texture", f"{label}眼白_原画纹理", "40_eyes", source_extract(source, mask & light), True, "Original eye white pixels.")
        add(prefix_order + 2, f"eye_{side}_iris_base", f"{label}虹膜_底色", "40_eyes", solid_layer(size, ellipse(size, (cx - 35, cy - 28, cx + 35, cy + 34)), (168, 70, 112, 240)), True, "Iris base color.")
        add(prefix_order + 3, f"eye_{side}_iris_texture", f"{label}虹膜_原画纹理", "40_eyes", source_extract(source, mask & pink), True, "Original iris pixels.")
        add(prefix_order + 4, f"eye_{side}_pupil", f"{label}瞳孔", "40_eyes", solid_layer(size, ellipse(size, (cx - 13, cy - 7, cx + 13, cy + 22)), (48, 20, 42, 230)), True, "Pupil layer.")
        add(prefix_order + 5, f"eye_{side}_highlight_main", f"{label}眼睛主高光", "40_eyes", solid_layer(size, ellipse(size, (cx - 18, cy - 23, cx + 4, cy - 3)), (255, 214, 224, 205)), True, "Eye highlight separated.")
        add(prefix_order + 6, f"eye_{side}_highlight_small", f"{label}眼睛小高光", "40_eyes", solid_layer(size, ellipse(size, (cx + 12, cy + 5, cx + 24, cy + 17)), (255, 230, 238, 185)), True, "Small eye highlight.")
        add(prefix_order + 7, f"eye_{side}_upper_lash_base", f"{label}上睫毛主枝", "40_eyes", source_extract(source, mask & very_dark), True, "Upper lash and dark eye line.")
        add(prefix_order + 8, f"eye_{side}_upper_lash_branch_1", f"{label}上睫毛枝杈1", "40_eyes", line_layer(size, [(cx - 57, cy - 7), (cx - 30, cy - 25), (cx + 24, cy - 23), (cx + 54, cy - 8)], (42, 24, 33, 230), 4), True, "Independent eyelash branch.")
        add(prefix_order + 9, f"eye_{side}_lower_lash", f"{label}下睫毛", "40_eyes", line_layer(size, [(cx - 44, cy + 24), (cx - 10, cy + 38), (cx + 42, cy + 22)], (56, 28, 38, 205), 3), True, "Lower lash separated.")
        add(prefix_order + 10, f"eye_{side}_lid_shadow", f"{label}眼睑阴影", "40_eyes", shade_layer(size, mask, (116, 54, 72, 42), 3), True, "Eyelid shadow separated.")
        add(prefix_order + 11, f"eye_{side}_blink_cover", f"{label}闭眼肤色遮罩", "40_eyes", solid_layer(size, mask, (229, 170, 158, 230)), False, "Hidden blink cover driven by ParamEyeOpen.")
        add(prefix_order + 12, f"eye_{side}_closed_lid_line", f"{label}闭眼线", "40_eyes", line_layer(size, [(cx - 50, cy + 10), (cx, cy + 27), (cx + 52, cy + 8)], (52, 30, 38, 230), 5), False, "Hidden closed-eye line.")

    eye_layers(60, "l", eye_l, 642, 372)
    eye_layers(80, "r", eye_r, 806, 360)
    add(100, "brow_l", "左屏眉毛", "45_brows", source_extract(source, brow_l & very_dark), True, "Brow separated for thinking/serious expression.")
    add(101, "brow_r", "右屏眉毛", "45_brows", source_extract(source, brow_r & very_dark), True, "Brow separated for thinking/serious expression.")

    add(110, "mouth_inner_a", "口腔_A形", "50_mouth", solid_layer(size, ellipse(size, (732, 506, 792, 540)), (58, 20, 33, 230)), False, "Open A mouth interior for lip sync.")
    add(111, "mouth_inner_o", "口腔_O形", "50_mouth", solid_layer(size, ellipse(size, (744, 502, 782, 544)), (54, 18, 32, 230)), False, "Open O mouth interior for lip sync.")
    add(112, "mouth_tongue", "舌头", "50_mouth", solid_layer(size, ellipse(size, (740, 520, 786, 543)), (193, 88, 112, 190)), False, "Tongue for open mouth.")
    add(113, "mouth_teeth", "牙齿", "50_mouth", solid_layer(size, poly(size, [(738, 508), (788, 509), (780, 522), (744, 522)]), (250, 224, 214, 210)), False, "Teeth layer.")
    add(114, "mouth_closed_smile_source", "闭口微笑线_原画", "50_mouth", source_extract(source, mouth & (dark | pink)), True, "Original closed smile.")
    add(115, "mouth_upper_lip", "上口片", "50_mouth", line_layer(size, [(724, 505), (756, 516), (800, 501)], (86, 34, 46, 215), 4), True, "Upper lip / smile line.")
    add(116, "mouth_lower_lip_shadow", "下唇阴影", "50_mouth", line_layer(size, [(734, 526), (760, 536), (792, 524)], (146, 69, 82, 105), 3, 0.8), True, "Lower lip shadow.")
    add(117, "mouth_serious_flat_line", "认真表情平口线", "50_mouth", line_layer(size, [(730, 524), (762, 515), (795, 526)], (72, 33, 44, 210), 4), False, "Hidden serious mouth overlay.")

    add(120, "bang_center_base_complete", "中刘海_完整底色", "60_front_hair", solid_layer(size, bang_center, (31, 27, 35, 245)), True, "Complete center bang clump.")
    add(121, "bang_center_texture", "中刘海_原画纹理", "60_front_hair", source_extract(source, bang_center & dark), True, "Visible center bang source texture.")
    add(122, "bang_l_base_complete", "左屏刘海_完整底色", "60_front_hair", solid_layer(size, bang_l, (31, 27, 35, 245)), True, "Complete left-screen bang clump.")
    add(123, "bang_l_texture", "左屏刘海_原画纹理", "60_front_hair", source_extract(source, bang_l & dark), True, "Visible left-screen bang source texture.")
    add(124, "bang_r_base_complete", "右屏刘海_完整底色", "60_front_hair", solid_layer(size, bang_r, (31, 27, 35, 245)), True, "Complete right-screen bang clump.")
    add(125, "bang_r_texture", "右屏刘海_原画纹理", "60_front_hair", source_extract(source, bang_r & dark), True, "Visible right-screen bang source texture.")
    add(126, "hair_over_eye_fine_strands", "眼前细发丝", "60_front_hair", source_extract(source, (eye_l | eye_r | face_full) & dark), True, "Fine hair crossing eyes/face.")
    add(127, "long_lock_l_complete", "左屏侧发_完整底色", "60_front_hair", solid_layer(size, lock_l, (32, 28, 36, 240)), True, "Complete left-screen side lock.")
    add(128, "long_lock_l_texture", "左屏侧发_原画纹理", "60_front_hair", source_extract(source, lock_l & alpha), True, "Visible side-lock texture.")
    add(129, "long_lock_r_complete", "右屏侧发_完整底色", "60_front_hair", solid_layer(size, lock_r, (32, 28, 36, 240)), True, "Complete right-screen side lock.")
    add(130, "long_lock_r_texture", "右屏侧发_原画纹理", "60_front_hair", source_extract(source, lock_r & alpha), True, "Visible side-lock texture.")
    add(131, "front_hair_highlight_strokes", "前发高光独立", "60_front_hair", source_extract(source, (bang_center | bang_l | bang_r | lock_l | lock_r) & light), True, "Hair highlight strokes separated.")
    add(132, "front_hair_pink_streaks", "前发粉色挑染", "60_front_hair", source_extract(source, (lock_l | lock_r | bang_l | bang_r) & pink), True, "Pink streaks separated.")

    add(140, "arm_l_sleeve_complete", "左屏手臂袖子_完整", "70_arms_hands", solid_layer(size, arm_l, (32, 30, 37, 242)), True, "Complete cheek-side sleeve for arm motion.")
    add(141, "arm_l_sleeve_texture", "左屏手臂袖子_原画纹理", "70_arms_hands", source_extract(source, arm_l & alpha), True, "Visible sleeve texture.")
    add(142, "hand_cheek_base_complete", "托脸手_完整肤色", "70_arms_hands", solid_layer(size, hand_cheek, (230, 169, 154, 238)), True, "Complete cheek hand skin base.")
    add(143, "hand_cheek_visible_texture", "托脸手_原画纹理", "70_arms_hands", source_extract(source, hand_cheek & skin), True, "Visible cheek hand source texture.")
    add(144, "hand_cheek_finger_lines", "托脸手_手指线", "70_arms_hands", line_layer(size, [(585, 430), (604, 475), (598, 523), (625, 484), (642, 428)], (103, 48, 55, 120), 2, 0.6), True, "Finger detail separated.")
    add(145, "arm_r_sleeve_complete", "右屏手臂袖子_完整", "70_arms_hands", solid_layer(size, arm_r, (32, 30, 37, 242)), True, "Complete folded sleeve for breathing motion.")
    add(146, "arm_r_sleeve_texture", "右屏手臂袖子_原画纹理", "70_arms_hands", source_extract(source, arm_r & alpha), True, "Visible sleeve texture.")
    add(147, "front_hand_base_complete", "前景手_完整肤色", "70_arms_hands", solid_layer(size, hand_front, (229, 169, 154, 238)), True, "Complete front hand skin base.")
    add(148, "front_hand_visible_texture", "前景手_原画纹理", "70_arms_hands", source_extract(source, hand_front & skin), True, "Visible front hand texture.")
    add(149, "front_hand_finger_lines", "前景手_手指线", "70_arms_hands", line_layer(size, [(662, 852), (698, 890), (736, 932), (726, 850), (764, 900)], (105, 50, 57, 120), 2, 0.6), True, "Finger detail separated.")
    add(150, "support_hand_down_upper_sleeve_repaint", "托腮手放下_上臂袖子补画", "70_arms_hands", solid_layer(size, poly(size, [(500, 560), (625, 590), (672, 746), (586, 812), (470, 704)]), (32, 30, 37, 230)), False, "Hidden alternate sleeve pose for lowering the cheek-supporting hand.")
    add(151, "support_hand_down_forearm_sleeve_repaint", "托腮手放下_前臂袖子补画", "70_arms_hands", solid_layer(size, poly(size, [(578, 730), (700, 710), (762, 832), (704, 924), (592, 894), (540, 800)]), (31, 29, 36, 230)), False, "Hidden alternate forearm sleeve for the hand-down seated pose.")
    add(152, "support_hand_down_cuff_repaint", "托腮手放下_袖口补画", "70_arms_hands", solid_layer(size, poly(size, [(620, 790), (718, 772), (748, 835), (650, 858)]), (38, 34, 40, 235)), False, "Hidden cuff for the lowered supporting hand.")
    add(153, "support_hand_down_hand_base_repaint", "托腮手放下_手掌补画", "70_arms_hands", solid_layer(size, poly(size, [(662, 818), (748, 806), (806, 864), (780, 930), (690, 944), (638, 886)]), (229, 169, 154, 228)), False, "Hidden alternate hand base resting down in a seated pose.")
    add(154, "support_hand_down_finger_lines_repaint", "托腮手放下_手指线补画", "70_arms_hands", line_layer(size, [(676, 844), (714, 888), (744, 930), (724, 836), (768, 882), (790, 916)], (104, 48, 56, 125), 2, 0.6), False, "Hidden finger-line guide for the lowered supporting hand.")
    add(155, "cheek_after_hand_removed_cleanup", "托腮手移开_脸颊补全检查层", "70_arms_hands", solid_layer(size, poly(size, [(548, 400), (650, 372), (708, 430), (686, 526), (590, 548), (528, 486)]), (231, 172, 158, 210)), False, "Hidden cheek fill/check layer that becomes visible when the supporting hand moves down.")

    add(160, "hair_clip_base", "发夹_主体", "80_accessories", source_extract(source, clip & (metal | dark | light)), True, "Hair clip accessory.")
    add(161, "hair_clip_highlight", "发夹_高光", "80_accessories", source_extract(source, clip & light), True, "Hair clip highlight.")
    add(162, "ear_charm_l", "左屏耳饰", "80_accessories", source_extract(source, charm_l & alpha), True, "Left-screen dangling ear charm.")
    add(163, "earring_chain_r", "右屏耳饰链条", "80_accessories", source_extract(source, earring_r & alpha), True, "Right-screen earring/chain.")
    add(164, "necklace_chain", "项链链条", "80_accessories", source_extract(source, necklace & (metal | dark)), True, "Necklace chain.")
    add(165, "necklace_cyan_pendant", "项链蓝色吊坠", "80_accessories", source_extract(source, necklace & cyan), True, "Cyan pendant pixels.")
    add(166, "necklace_pendant_glow", "项链吊坠发光", "80_accessories", shade_layer(size, necklace & cyan, (72, 235, 255, 120), 5), True, "Separated glow layer.")
    add(167, "sleeve_device_body", "袖章设备_主体", "80_accessories", source_extract(source, device & alpha), True, "Sleeve device body.")
    add(168, "sleeve_device_screen", "袖章设备_屏幕", "80_accessories", source_extract(source, device & cyan), True, "Sleeve device cyan screen.")
    add(169, "sleeve_device_glow", "袖章设备_发光", "80_accessories", shade_layer(size, device & cyan, (75, 220, 255, 105), 4), True, "Sleeve device glow.")
    add(170, "hanging_keychain_body", "右侧挂件_主体", "80_accessories", source_extract(source, keychain & alpha), True, "Right-side hanging keychain.")
    add(171, "hanging_keychain_glow", "右侧挂件_发光", "80_accessories", shade_layer(size, keychain & cyan, (80, 225, 255, 110), 5), True, "Keychain cyan glow.")
    add(172, "all_cyan_status_pixels_helper", "蓝色状态光像素_辅助", "80_accessories", source_extract(source, cyan), False, "All cyan pixels collected as a helper for status effects.")

    # Expression helper overlays. These stay hidden in the import composite and
    # are referenced by expressions_manifest.json for Cubism setup.
    add(175, "expr_angry_brow_l_down", "表情_愤怒_左屏压眉", "90_expressions", line_layer(size, [(575, 326), (624, 301), (690, 304)], (45, 20, 30, 230), 5), False, "Angry brow overlay.")
    add(176, "expr_angry_brow_r_down", "表情_愤怒_右屏压眉", "90_expressions", line_layer(size, [(752, 300), (812, 296), (866, 324)], (45, 20, 30, 230), 5), False, "Angry brow overlay.")
    add(177, "expr_angry_mouth_tight", "表情_愤怒_紧闭口", "90_expressions", line_layer(size, [(728, 523), (764, 514), (800, 523)], (72, 25, 34, 225), 5), False, "Angry tight mouth.")
    add(178, "expr_angry_shadow", "表情_愤怒_面部暗影", "90_expressions", shade_layer(size, face_full & poly(size, [(560, 292), (855, 315), (825, 426), (594, 430)]), (78, 18, 28, 55), 5), False, "Angry upper-face shadow.")

    add(179, "expr_happy_eye_l_arc", "表情_高兴_左屏笑眼", "90_expressions", line_layer(size, [(590, 378), (640, 395), (696, 374)], (58, 25, 38, 225), 5), False, "Happy closed eye arc.")
    add(180, "expr_happy_eye_r_arc", "表情_高兴_右屏笑眼", "90_expressions", line_layer(size, [(760, 364), (808, 382), (858, 362)], (58, 25, 38, 225), 5), False, "Happy closed eye arc.")
    add(181, "expr_happy_mouth_smile_open", "表情_高兴_开口笑", "90_expressions", solid_layer(size, ellipse(size, (728, 504, 802, 552)), (60, 20, 34, 225)), False, "Happy open smile mouth.")
    add(182, "expr_happy_blush_boost", "表情_高兴_腮红增强", "90_expressions", solid_layer(size, ellipse(size, (604, 432, 716, 538)) | ellipse(size, (752, 422, 866, 530)), (242, 118, 142, 82), 6), False, "Happy blush boost.")

    add(183, "expr_confused_brow_l_raise", "表情_疑惑_左屏挑眉", "90_expressions", line_layer(size, [(570, 292), (628, 278), (698, 306)], (48, 24, 34, 225), 5), False, "Confused asymmetrical brow.")
    add(184, "expr_confused_brow_r_flat", "表情_疑惑_右屏平眉", "90_expressions", line_layer(size, [(746, 306), (808, 300), (866, 306)], (48, 24, 34, 225), 4), False, "Confused brow.")
    add(185, "expr_confused_mouth_small", "表情_疑惑_小口", "90_expressions", solid_layer(size, ellipse(size, (746, 512, 776, 536)), (58, 22, 34, 220)), False, "Small confused mouth.")
    add(186, "expr_confused_question_mark", "表情_疑惑_问号符号", "90_expressions", line_layer(size, [(880, 232), (910, 212), (938, 232), (928, 264), (906, 282)], (124, 210, 228, 150), 7), False, "Optional question mark effect.")

    add(187, "expr_sad_brow_l_soft", "表情_悲伤_左屏八字眉", "90_expressions", line_layer(size, [(584, 306), (634, 288), (696, 300)], (50, 24, 34, 225), 5), False, "Sad brow.")
    add(188, "expr_sad_brow_r_soft", "表情_悲伤_右屏八字眉", "90_expressions", line_layer(size, [(748, 300), (810, 288), (858, 308)], (50, 24, 34, 225), 5), False, "Sad brow.")
    add(189, "expr_sad_mouth_down", "表情_悲伤_下弯口", "90_expressions", line_layer(size, [(728, 532), (762, 512), (800, 532)], (82, 32, 43, 220), 4), False, "Sad downturned mouth.")
    add(190, "expr_sad_tears", "表情_悲伤_泪滴", "90_expressions", solid_layer(size, ellipse(size, (602, 414, 620, 454)) | ellipse(size, (836, 398, 854, 438)), (150, 226, 255, 165), 1), False, "Optional tears.")

    add(191, "expr_fear_eye_l_wide", "表情_恐惧_左屏瞪眼补白", "90_expressions", solid_layer(size, ellipse(size, (574, 318, 712, 424)), (246, 222, 216, 230)), False, "Fear wide-eye white.")
    add(192, "expr_fear_eye_r_wide", "表情_恐惧_右屏瞪眼补白", "90_expressions", solid_layer(size, ellipse(size, (740, 304, 878, 412)), (246, 222, 216, 230)), False, "Fear wide-eye white.")
    add(193, "expr_fear_mouth_small_open", "表情_恐惧_小开口", "90_expressions", solid_layer(size, ellipse(size, (742, 508, 782, 548)), (48, 18, 32, 230)), False, "Fear small open mouth.")
    add(194, "expr_fear_face_shadow", "表情_恐惧_脸部冷阴影", "90_expressions", shade_layer(size, face_full, (42, 68, 108, 45), 6), False, "Cool fear shadow.")

    add(195, "expr_surprise_eye_l_round", "表情_惊讶_左屏圆眼", "90_expressions", solid_layer(size, ellipse(size, (574, 318, 714, 426)), (248, 224, 218, 232)), False, "Surprise round eye white.")
    add(196, "expr_surprise_eye_r_round", "表情_惊讶_右屏圆眼", "90_expressions", solid_layer(size, ellipse(size, (738, 304, 880, 414)), (248, 224, 218, 232)), False, "Surprise round eye white.")
    add(197, "expr_surprise_mouth_o", "表情_惊讶_O形口", "90_expressions", solid_layer(size, ellipse(size, (738, 500, 790, 552)), (50, 17, 31, 230)), False, "Surprise O mouth.")
    add(198, "expr_surprise_highlight_pop", "表情_惊讶_眼高光增强", "90_expressions", solid_layer(size, ellipse(size, (620, 344, 648, 372)) | ellipse(size, (792, 332, 820, 360)), (255, 232, 240, 210)), False, "Surprise highlight pop.")

    add(199, "expr_disgust_brow_l", "表情_厌恶_左屏皱眉", "90_expressions", line_layer(size, [(574, 314), (622, 300), (686, 318)], (45, 20, 30, 225), 5), False, "Disgust brow.")
    add(200, "expr_disgust_brow_r", "表情_厌恶_右屏皱眉", "90_expressions", line_layer(size, [(752, 316), (810, 298), (864, 310)], (45, 20, 30, 225), 5), False, "Disgust brow.")
    add(201, "expr_disgust_mouth_skew", "表情_厌恶_歪嘴", "90_expressions", line_layer(size, [(724, 520), (760, 532), (802, 512)], (78, 28, 40, 225), 5), False, "Disgust skewed mouth.")
    add(202, "expr_disgust_nose_wrinkle", "表情_厌恶_鼻梁皱褶", "90_expressions", line_layer(size, [(716, 438), (742, 424), (764, 438)], (112, 55, 62, 115), 2, 0.5), False, "Nose wrinkle.")

    add(203, "expr_contempt_brow_l", "表情_轻蔑_左屏轻挑眉", "90_expressions", line_layer(size, [(570, 294), (632, 284), (696, 304)], (47, 22, 32, 220), 4), False, "Contempt asymmetrical brow.")
    add(204, "expr_contempt_eye_r_half_lid", "表情_轻蔑_右屏半眯眼", "90_expressions", shade_layer(size, eye_r & poly(size, [(738, 304), (880, 304), (868, 356), (742, 360)]), (46, 24, 32, 135), 1.5), False, "Half-lid overlay.")
    add(205, "expr_contempt_smirk", "表情_轻蔑_单边笑", "90_expressions", line_layer(size, [(724, 512), (760, 526), (804, 500)], (84, 32, 44, 225), 4), False, "Asymmetric smirk.")

    recovery_mask = alpha.copy()
    for mask in [
        back_hair, hair_side_l, hair_side_r, tail_l, tail_r, body, jacket_l, jacket_r, neck_full, face_full,
        ear_l, ear_r, eye_l, eye_r, brow_l, brow_r, mouth, bang_center, bang_l, bang_r, lock_l, lock_r,
        arm_l, arm_r, hand_cheek, hand_front, clip, earring_r, charm_l, necklace, device, keychain,
    ]:
        recovery_mask &= ~mask
    add(230, "unassigned_visible_recovery_review", "未分配可见像素_检查用", "99_review", source_extract(source, recovery_mask), False, "Visible pixels not assigned to a semantic part; review manually.")

    return records


def render_composite(records: list[LayerRecord], output_path: Path, include_hidden: bool = False) -> Image.Image:
    source, _ = load_source()
    composite = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for record in sorted(records, key=lambda item: item.order):
        if not include_hidden and not record.visible:
            continue
        layer = Image.open(LAYERS_DIR / record.filename).convert("RGBA")
        composite.alpha_composite(layer)
    composite.save(output_path)
    return composite


def refresh_layer_metadata(record: LayerRecord) -> None:
    image = Image.open(LAYERS_DIR / record.filename).convert("RGBA")
    alpha = np.asarray(image.getchannel("A"))
    ys, xs = np.where(alpha > 0)
    record.nontransparent_pixels = int((alpha > 0).sum())
    record.bbox = None
    if xs.size:
        record.bbox = [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]


def exact_source_layer(source_array: np.ndarray, mask: np.ndarray) -> Image.Image:
    layer_array = source_array.copy()
    layer_array[:, :, 3] = np.where(mask, layer_array[:, :, 3], 0).astype(np.uint8)
    return Image.fromarray(layer_array, "RGBA")


def add_visible_recovery_from_source(records: list[LayerRecord]) -> None:
    """Patch visible recomposite artifacts without destroying part layers.

    The generated semantic layers remain editable and non-empty. Any pixel where
    their default composite does not match the flattened source is copied into
    the review/recovery layer above them. This keeps the first Photoshop view
    faithful to the original while still making the imperfect areas explicit.
    """
    source, _ = load_source()
    source_array = np.asarray(source).copy()
    source_alpha = source_array[:, :, 3] > 0

    recovery_record = next(
        (record for record in records if record.filename.endswith("unassigned_visible_recovery_review.png")),
        None,
    )
    if recovery_record is None:
        return

    recovery_record.visible = False
    composite = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for record in sorted(records, key=lambda item: item.order):
        if not record.visible:
            continue
        layer = Image.open(LAYERS_DIR / record.filename).convert("RGBA")
        layer_array = np.asarray(layer).copy()
        layer_array[:, :, 3] = np.where(source_alpha, layer_array[:, :, 3], 0).astype(np.uint8)
        layer = Image.fromarray(layer_array, "RGBA")
        layer.save(LAYERS_DIR / record.filename)
        refresh_layer_metadata(record)
        composite.alpha_composite(layer)

    composite_array = np.asarray(composite)
    mismatch = np.any(np.abs(source_array.astype(np.int16) - composite_array.astype(np.int16)) > 2, axis=2)
    recovery_mask = source_alpha & mismatch
    recovery_record.visible = bool(recovery_mask.any())
    exact_source_layer(source_array, recovery_mask).save(LAYERS_DIR / recovery_record.filename)
    refresh_layer_metadata(recovery_record)


def write_manifest(records: list[LayerRecord]) -> None:
    source, _ = load_source()
    data = {
        "version": 1,
        "canvas_width": source.width,
        "canvas_height": source.height,
        "source_image": str(SOURCE_IMAGE.relative_to(REPO_ROOT)).replace("\\", "/"),
        "occlusion_strategy": "B: redraw/inpaint hidden areas with editable helper layers",
        "import_psd": IMPORT_PSD_NAME,
        "edit_psd": EDIT_PSD_NAME,
        "layers": [record.__dict__ for record in sorted(records, key=lambda item: item.order)],
    }
    (OUTPUT_ROOT / "layers_manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_expressions_manifest(records: list[LayerRecord]) -> None:
    by_filename = {record.filename: record for record in records}

    def layer_name(stem: str) -> str:
        matches = [record.filename for record in records if stem in record.filename]
        if not matches:
            raise KeyError(stem)
        return matches[0]

    expressions = [
        {
            "id": "angry",
            "name": "愤怒",
            "layers": [
                layer_name("expr_angry_brow_l_down"),
                layer_name("expr_angry_brow_r_down"),
                layer_name("expr_angry_mouth_tight"),
                layer_name("expr_angry_shadow"),
            ],
            "parameters": {"ParamBrowLY": -0.7, "ParamBrowRY": -0.7, "ParamBrowLAngle": -0.4, "ParamBrowRAngle": 0.4, "ParamMouthForm": -0.25},
        },
        {
            "id": "happy",
            "name": "高兴",
            "layers": [
                layer_name("expr_happy_eye_l_arc"),
                layer_name("expr_happy_eye_r_arc"),
                layer_name("expr_happy_mouth_smile_open"),
                layer_name("expr_happy_blush_boost"),
            ],
            "parameters": {"ParamEyeLOpen": 0.18, "ParamEyeROpen": 0.18, "ParamMouthOpenY": 0.45, "ParamMouthForm": 0.8},
        },
        {
            "id": "confused",
            "name": "疑惑",
            "layers": [
                layer_name("expr_confused_brow_l_raise"),
                layer_name("expr_confused_brow_r_flat"),
                layer_name("expr_confused_mouth_small"),
                layer_name("expr_confused_question_mark"),
            ],
            "parameters": {"ParamBrowLY": 0.45, "ParamBrowRY": -0.15, "ParamBrowLAngle": 0.35, "ParamEyeBallX": -0.35, "ParamMouthForm": -0.1},
        },
        {
            "id": "sad",
            "name": "悲伤",
            "layers": [
                layer_name("expr_sad_brow_l_soft"),
                layer_name("expr_sad_brow_r_soft"),
                layer_name("expr_sad_mouth_down"),
                layer_name("expr_sad_tears"),
            ],
            "parameters": {"ParamBrowLY": -0.35, "ParamBrowRY": -0.35, "ParamMouthForm": -0.75, "ParamEyeLOpen": 0.65, "ParamEyeROpen": 0.65},
        },
        {
            "id": "fear",
            "name": "恐惧",
            "layers": [
                layer_name("expr_fear_eye_l_wide"),
                layer_name("expr_fear_eye_r_wide"),
                layer_name("expr_fear_mouth_small_open"),
                layer_name("expr_fear_face_shadow"),
            ],
            "parameters": {"ParamEyeLOpen": 1.0, "ParamEyeROpen": 1.0, "ParamMouthOpenY": 0.55, "ParamBodyAngleY": -0.25},
        },
        {
            "id": "surprise",
            "name": "惊讶",
            "layers": [
                layer_name("expr_surprise_eye_l_round"),
                layer_name("expr_surprise_eye_r_round"),
                layer_name("expr_surprise_mouth_o"),
                layer_name("expr_surprise_highlight_pop"),
            ],
            "parameters": {"ParamEyeLOpen": 1.0, "ParamEyeROpen": 1.0, "ParamMouthOpenY": 0.85, "ParamMouthForm": 0.0, "ParamAngleY": 0.2},
        },
        {
            "id": "disgust",
            "name": "厌恶",
            "layers": [
                layer_name("expr_disgust_brow_l"),
                layer_name("expr_disgust_brow_r"),
                layer_name("expr_disgust_mouth_skew"),
                layer_name("expr_disgust_nose_wrinkle"),
            ],
            "parameters": {"ParamBrowLY": -0.35, "ParamBrowRY": -0.25, "ParamMouthForm": -0.55, "ParamAngleZ": -0.1},
        },
        {
            "id": "contempt",
            "name": "轻蔑",
            "layers": [
                layer_name("expr_contempt_brow_l"),
                layer_name("expr_contempt_eye_r_half_lid"),
                layer_name("expr_contempt_smirk"),
            ],
            "parameters": {"ParamBrowLY": 0.25, "ParamEyeROpen": 0.45, "ParamMouthForm": 0.45, "ParamAngleZ": 0.08},
        },
    ]
    data = {
        "version": 1,
        "note": "Expression helper layers are hidden by default. Use these as Cubism expression setup references, then tune opacity and parameters manually.",
        "expressions": expressions,
    }
    (OUTPUT_ROOT / "expressions_manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def jsx_layer_data(records: list[LayerRecord]) -> str:
    layers = [
        {
            "name": record.name,
            "group": record.group,
            "file": f"layers/{record.filename}",
            "visibleDefault": record.visible,
        }
        for record in sorted(records, key=lambda item: item.order)
    ]
    return json.dumps(layers, ensure_ascii=True, indent=2)


def write_merge_script(records: list[LayerRecord]) -> None:
    source, _ = load_source()
    script = r'''#target photoshop
app.bringToFront();

var oldDialogs = app.displayDialogs;
var oldUnits = app.preferences.rulerUnits;
var logFile = null;

function px(unitValue) {
  return Math.round(unitValue.as("px"));
}

function writeLog(message) {
  try {
    if (logFile === null) return;
    logFile.open("a");
    logFile.writeln(new Date().toString() + " " + message);
    logFile.close();
  } catch (logErr) {
  }
}

function validateLayerSize(src, expectedWidth, expectedHeight, file) {
  if (px(src.width) !== expectedWidth || px(src.height) !== expectedHeight) {
    var badSize = file.fsName + " is " + px(src.width) + "x" + px(src.height);
    src.close(SaveOptions.DONOTSAVECHANGES);
    throw new Error("Layer size mismatch: " + badSize);
  }
}

try {
  app.displayDialogs = DialogModes.NO;
  app.preferences.rulerUnits = Units.PIXELS;

  var scriptFile = new File($.fileName);
  var sourceDir = scriptFile.parent;
  var qaDir = new Folder(sourceDir.fsName + "/qa");
  if (!qaDir.exists) qaDir.create();

  logFile = new File(sourceDir.fsName + "/merge_layers.log.txt");
  if (logFile.exists) logFile.remove();

  var outputPsd = new File(sourceDir.fsName + "/character_live2d_import.psd");
  var outputFlat = new File(qaDir.fsName + "/photoshop_flatten_preview.png");
  var layers = __LAYERS__;
  var expectedWidth = __WIDTH__;
  var expectedHeight = __HEIGHT__;

  writeLog("Start assembling import PSD. Layer count: " + layers.length);

  var doc = app.documents.add(
    UnitValue(expectedWidth, "px"),
    UnitValue(expectedHeight, "px"),
    72,
    "character_live2d_import",
    NewDocumentMode.RGB,
    DocumentFill.TRANSPARENT
  );

  for (var i = 0; i < layers.length; i++) {
    var item = layers[i];
    writeLog("Importing " + (i + 1) + "/" + layers.length + ": " + item.file);
    var file = new File(sourceDir.fsName + "/" + item.file);
    if (!file.exists) {
      throw new Error("Missing layer PNG: " + file.fsName);
    }

    var src = app.open(file);
    app.activeDocument = src;
    validateLayerSize(src, expectedWidth, expectedHeight, file);
    src.activeLayer.name = item.name;

    var duplicated = src.activeLayer.duplicate(doc, ElementPlacement.PLACEATBEGINNING);
    src.close(SaveOptions.DONOTSAVECHANGES);

    app.activeDocument = doc;
    duplicated.name = item.name;
    duplicated.visible = item.visibleDefault;
  }

  app.activeDocument = doc;
  var saveOptions = new PhotoshopSaveOptions();
  saveOptions.layers = true;
  saveOptions.alphaChannels = true;
  saveOptions.embedColorProfile = true;
  doc.saveAs(outputPsd, saveOptions, true, Extension.LOWERCASE);

  var flatDoc = doc.duplicate("character_live2d_import_flatten", true);
  var pngOptions = new PNGSaveOptions();
  flatDoc.saveAs(outputFlat, pngOptions, true, Extension.LOWERCASE);
  flatDoc.close(SaveOptions.DONOTSAVECHANGES);

  writeLog("Success. PSD: " + outputPsd.fsName);
  writeLog("Success. Flatten preview: " + outputFlat.fsName);
} catch (err) {
  writeLog("FAILED: " + err.message + " Line: " + err.line);
  throw err;
} finally {
  app.displayDialogs = oldDialogs;
  app.preferences.rulerUnits = oldUnits;
}
'''
    script = (
        script.replace("__LAYERS__", jsx_layer_data(records))
        .replace("__WIDTH__", str(source.width))
        .replace("__HEIGHT__", str(source.height))
    )
    (OUTPUT_ROOT / "merge_layers.jsx").write_text(script, encoding="utf-8")


def write_edit_script(records: list[LayerRecord]) -> None:
    source, _ = load_source()
    script = r'''#target photoshop
app.bringToFront();

var oldDialogs = app.displayDialogs;
var oldUnits = app.preferences.rulerUnits;
var logFile = null;

function px(unitValue) {
  return Math.round(unitValue.as("px"));
}

function writeLog(message) {
  try {
    if (logFile === null) return;
    logFile.open("a");
    logFile.writeln(new Date().toString() + " " + message);
    logFile.close();
  } catch (logErr) {
  }
}

function validateLayerSize(src, expectedWidth, expectedHeight, file) {
  if (px(src.width) !== expectedWidth || px(src.height) !== expectedHeight) {
    var badSize = file.fsName + " is " + px(src.width) + "x" + px(src.height);
    src.close(SaveOptions.DONOTSAVECHANGES);
    throw new Error("Layer size mismatch: " + badSize);
  }
}

function ensureGroup(doc, groupName) {
  app.activeDocument = doc;
  for (var i = 0; i < doc.layerSets.length; i++) {
    if (doc.layerSets[i].name === groupName) return doc.layerSets[i];
  }
  var group = doc.layerSets.add();
  group.name = groupName;
  return group;
}

try {
  app.displayDialogs = DialogModes.NO;
  app.preferences.rulerUnits = Units.PIXELS;

  var scriptFile = new File($.fileName);
  var sourceDir = scriptFile.parent;

  logFile = new File(sourceDir.fsName + "/merge_edit_layers.log.txt");
  if (logFile.exists) logFile.remove();

  var outputPsd = new File(sourceDir.fsName + "/character_live2d_edit.psd");
  var layers = __LAYERS__;
  var expectedWidth = __WIDTH__;
  var expectedHeight = __HEIGHT__;

  writeLog("Start assembling grouped edit PSD. Layer count: " + layers.length);

  var doc = app.documents.add(
    UnitValue(expectedWidth, "px"),
    UnitValue(expectedHeight, "px"),
    72,
    "character_live2d_edit",
    NewDocumentMode.RGB,
    DocumentFill.TRANSPARENT
  );

  var groups = {};
  for (var i = 0; i < layers.length; i++) {
    var item = layers[i];
    writeLog("Importing " + (i + 1) + "/" + layers.length + ": " + item.file);
    var file = new File(sourceDir.fsName + "/" + item.file);
    if (!file.exists) {
      throw new Error("Missing layer PNG: " + file.fsName);
    }

    if (!groups[item.group]) {
      groups[item.group] = ensureGroup(doc, item.group);
    }

    var src = app.open(file);
    app.activeDocument = src;
    validateLayerSize(src, expectedWidth, expectedHeight, file);
    src.activeLayer.name = item.name;

    var duplicated = src.activeLayer.duplicate(doc, ElementPlacement.PLACEATBEGINNING);
    src.close(SaveOptions.DONOTSAVECHANGES);

    app.activeDocument = doc;
    duplicated.name = item.name;
    duplicated.visible = item.visibleDefault;
    try {
      duplicated.move(groups[item.group], ElementPlacement.INSIDE);
    } catch (moveErr) {
      duplicated.name = item.group + "__" + item.name;
      writeLog("Move-to-group failed, kept ungrouped: " + duplicated.name + " Error: " + moveErr.message);
    }
  }

  app.activeDocument = doc;
  var saveOptions = new PhotoshopSaveOptions();
  saveOptions.layers = true;
  saveOptions.alphaChannels = true;
  saveOptions.embedColorProfile = true;
  doc.saveAs(outputPsd, saveOptions, true, Extension.LOWERCASE);

  writeLog("Success. PSD: " + outputPsd.fsName);
} catch (err) {
  writeLog("FAILED: " + err.message + " Line: " + err.line);
  throw err;
} finally {
  app.displayDialogs = oldDialogs;
  app.preferences.rulerUnits = oldUnits;
}
'''
    script = (
        script.replace("__LAYERS__", jsx_layer_data(records))
        .replace("__WIDTH__", str(source.width))
        .replace("__HEIGHT__", str(source.height))
    )
    (OUTPUT_ROOT / "merge_edit_layers.jsx").write_text(script, encoding="utf-8")


def write_readme(records: list[LayerRecord]) -> None:
    visible = sum(1 for record in records if record.visible)
    hidden = len(records) - visible
    text = f"""# Live2D Standard Character Split

This package follows the requested Live2D source-art split workflow.

Source: `apps/desktop/public/images/character.png`

## Output

- `layers/`: full-canvas transparent PNG layers. Every file is 1484x1060 and keeps original coordinates.
- `layers_manifest.json`: layer order, names, groups, visibility, and QA metadata.
- `expressions_manifest.json`: angry, happy, confused, sad, fear, surprise, disgust, and contempt helper-layer mappings.
- `merge_layers.jsx`: Photoshop script for the Cubism import PSD. The layer
  list is embedded directly in the JSX, matching the stable duplicate-layer
  style used by `assemble-agent-pet-companion-painted-v2.jsx`.
- `merge_edit_layers.jsx`: Photoshop script for a grouped edit PSD. The layer
  list is embedded directly in the JSX, so Photoshop does not need to read or
  parse JSON.
- `qa/composite_visible_preview.png`: visible-layer composite preview.
- `qa/diff_against_source.png`: rough visual diff against the original.
- `99_review/未分配可见像素_检查用`: visible recovery layer. It keeps the
  default PSD view close to the original where automatic semantic masks leave
  seams or missed edge pixels. Review and manually split these pixels before a
  final production rig.

Layer count: {len(records)}
Visible layers: {visible}
Hidden helper layers: {hidden}

## Photoshop Usage

1. Open Photoshop.
2. Use `File > Scripts > Browse...`.
3. Run `merge_edit_layers.jsx` to create `character_live2d_edit.psd`.
4. Run `merge_layers.jsx` to create `character_live2d_import.psd` and `qa/photoshop_flatten_preview.png`.
5. If Photoshop reports an error, check `merge_edit_layers.log.txt` or
   `merge_layers.log.txt` in this folder.

## Split Policy

Occlusion strategy: B, hidden areas are redrawn as editable helper layers.

The source is a flattened PNG, so all hidden geometry is reconstructed by approximation.
Before final Cubism rigging, manually inspect helper layers such as the
supporting-hand-down alternate pose, under-arm fills, face fills, blink covers,
and mouth interiors.

## Requested Motion Coverage

- Breath: torso, jacket panels, sleeves, and hair tails are separated.
- Blink: eye whites, irises, pupils, highlights, lashes, lid shadows, blink covers, and closed-eye lines are separated.
- Ear movement: both cat ears have outer, inner, and texture layers.
- Talk mouth: closed smile, A/O mouth interiors, tongue, teeth, lip line, lower shadow, and serious mouth overlay are separated.
- Supporting hand down / seated idle: alternate sleeve, cuff, hand, finger-line,
  and cheek-cleanup helper layers are included for the current cheek-supporting
  hand to move down into a seated pose.
- Wait/thinking/serious inspect: brows, eye details, mouth form overlays, hair shadows, and body layers are separated.
- Extra expressions: angry, happy, confused, sad, fear, surprise, disgust, and contempt overlays are included as hidden helper layers.
"""
    (OUTPUT_ROOT / "README.md").write_text(text, encoding="utf-8")


def qa(records: list[LayerRecord]) -> None:
    source, _ = load_source()
    composite = render_composite(records, QA_DIR / "composite_visible_preview.png", include_hidden=False)
    source.save(QA_DIR / "source_reference.png")
    diff = ImageChops.difference(source, composite)
    diff.save(QA_DIR / "diff_against_source.png")
    diff_alpha = np.asarray(diff.convert("RGBA"))
    qa_report = {
        "layer_count": len(records),
        "visible_layers": sum(1 for record in records if record.visible),
        "hidden_layers": sum(1 for record in records if not record.visible),
        "zero_pixel_layers": [record.filename for record in records if record.nontransparent_pixels == 0],
        "all_layers_full_canvas": True,
        "mean_abs_rgba_diff": float(np.mean(diff_alpha)),
        "note": "Diff is only a rough visual QA because hidden areas were redrawn and the package is not expected to pixel-match the flattened source exactly.",
    }
    (QA_DIR / "qa_report.json").write_text(json.dumps(qa_report, ensure_ascii=False, indent=2), encoding="utf-8")


def set_default_visibility(records: list[LayerRecord]) -> None:
    helper_keywords = [
        "under_fill",
        "base_complete",
        "outer_complete",
        "back_panel",
        "body_shadow_back",
        "face_contour_shadow",
        "cheek_blush",
        "nose_highlight",
        "cast_shadow",
        "inner_fur",
        "white_complete",
        "iris_base",
        "pupil",
        "highlight_main",
        "highlight_small",
        "upper_lash_branch",
        "lower_lash",
        "lid_shadow",
        "mouth_upper_lip",
        "mouth_lower_lip_shadow",
        "_glow",
        "_repaint",
        "hair_tail_l_base",
        "hair_tail_r_base",
        "complete",
    ]
    for record in records:
        if record.order == 1:
            record.visible = False
            continue
        if any(keyword in record.filename for keyword in helper_keywords):
            record.visible = False


def main() -> None:
    if not SOURCE_IMAGE.exists():
        raise FileNotFoundError(SOURCE_IMAGE)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    LAYERS_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    for stale_layer in LAYERS_DIR.glob("*.png"):
        stale_layer.unlink()
    for stale_qa_file in QA_DIR.glob("*"):
        if stale_qa_file.is_file():
            stale_qa_file.unlink()

    records = build_layers()
    set_default_visibility(records)
    add_visible_recovery_from_source(records)
    write_manifest(records)
    write_expressions_manifest(records)
    write_merge_script(records)
    write_edit_script(records)
    write_readme(records)
    qa(records)

    summary = {
        "source": str(SOURCE_IMAGE),
        "output": str(OUTPUT_ROOT),
        "layers": len(records),
        "visible_layers": sum(1 for record in records if record.visible),
        "hidden_helper_layers": sum(1 for record in records if not record.visible),
        "zero_pixel_layers": [record.filename for record in records if record.nontransparent_pixels == 0],
        "manifest": str(OUTPUT_ROOT / "layers_manifest.json"),
        "merge_layers_jsx": str(OUTPUT_ROOT / "merge_layers.jsx"),
        "merge_edit_layers_jsx": str(OUTPUT_ROOT / "merge_edit_layers.jsx"),
        "qa_report": str(QA_DIR / "qa_report.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
