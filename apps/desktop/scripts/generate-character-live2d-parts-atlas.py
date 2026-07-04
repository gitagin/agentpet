from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_IMAGE = REPO_ROOT / "apps" / "desktop" / "public" / "images" / "character.png"
OUTPUT_ROOT = REPO_ROOT / "apps" / "desktop" / "public" / "live2d" / "character_live2d_parts_atlas"
PARTS_DIR = OUTPUT_ROOT / "parts"
DOC_NAME = "character_live2d_parts_atlas"
ATLAS_SIZE = 4096
ATLAS_PADDING = 32


MaskBuilder = Callable[[tuple[int, int], dict[str, np.ndarray]], np.ndarray]


@dataclass(frozen=True)
class PartSpec:
    group: str
    name: str
    mask: MaskBuilder
    purpose: str
    visible: bool = True
    padding: int = 8


@dataclass
class PartOutput:
    group: str
    name: str
    purpose: str
    visible: bool
    file: str
    bbox_source: list[int]
    bbox_atlas: list[int]
    size: list[int]
    nontransparent_pixels: int


def polygon(points: list[tuple[int, int]], *filters: str) -> MaskBuilder:
    def build(size: tuple[int, int], channels: dict[str, np.ndarray]) -> np.ndarray:
        mask_image = Image.new("L", size, 0)
        ImageDraw.Draw(mask_image).polygon(points, fill=255)
        mask = np.asarray(mask_image) > 0
        if filters:
            allowed = np.zeros_like(mask)
            for key in filters:
                allowed |= channels[key]
            mask &= allowed
        else:
            mask &= channels["alpha"]
        return mask

    return build


def ellipse(box: tuple[int, int, int, int], *filters: str) -> MaskBuilder:
    def build(size: tuple[int, int], channels: dict[str, np.ndarray]) -> np.ndarray:
        mask_image = Image.new("L", size, 0)
        ImageDraw.Draw(mask_image).ellipse(box, fill=255)
        mask = np.asarray(mask_image) > 0
        if filters:
            allowed = np.zeros_like(mask)
            for key in filters:
                allowed |= channels[key]
            mask &= allowed
        else:
            mask &= channels["alpha"]
        return mask

    return build


def rect(box: tuple[int, int, int, int], *filters: str) -> MaskBuilder:
    def build(size: tuple[int, int], channels: dict[str, np.ndarray]) -> np.ndarray:
        mask_image = Image.new("L", size, 0)
        ImageDraw.Draw(mask_image).rectangle(box, fill=255)
        mask = np.asarray(mask_image) > 0
        if filters:
            allowed = np.zeros_like(mask)
            for key in filters:
                allowed |= channels[key]
            mask &= allowed
        else:
            mask &= channels["alpha"]
        return mask

    return build


def union(*builders: MaskBuilder) -> MaskBuilder:
    def build(size: tuple[int, int], channels: dict[str, np.ndarray]) -> np.ndarray:
        result = np.zeros((size[1], size[0]), dtype=bool)
        for item in builders:
            result |= item(size, channels)
        return result

    return build


def generated_polygon(points: list[tuple[int, int]], color: tuple[int, int, int, int], blur: float = 1.0) -> MaskBuilder:
    def build(size: tuple[int, int], _channels: dict[str, np.ndarray]) -> np.ndarray:
        mask_image = Image.new("L", size, 0)
        ImageDraw.Draw(mask_image).polygon(points, fill=255)
        if blur:
            mask_image = mask_image.filter(ImageFilter.GaussianBlur(blur))
        return np.asarray(mask_image) > 4

    build.generated_color = color  # type: ignore[attr-defined]
    return build


def generated_ellipse(box: tuple[int, int, int, int], color: tuple[int, int, int, int], blur: float = 1.0) -> MaskBuilder:
    def build(size: tuple[int, int], _channels: dict[str, np.ndarray]) -> np.ndarray:
        mask_image = Image.new("L", size, 0)
        ImageDraw.Draw(mask_image).ellipse(box, fill=255)
        if blur:
            mask_image = mask_image.filter(ImageFilter.GaussianBlur(blur))
        return np.asarray(mask_image) > 4

    build.generated_color = color  # type: ignore[attr-defined]
    return build


def generated_curve(points: list[tuple[int, int]], color: tuple[int, int, int, int], width: int, blur: float = 0.4) -> MaskBuilder:
    def build(size: tuple[int, int], _channels: dict[str, np.ndarray]) -> np.ndarray:
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).line(points, fill=color, width=width, joint="curve")
        alpha = layer.getchannel("A")
        if blur:
            alpha = alpha.filter(ImageFilter.GaussianBlur(blur))
        return np.asarray(alpha) > 4

    build.generated_color = color  # type: ignore[attr-defined]
    build.generated_curve_points = points  # type: ignore[attr-defined]
    build.generated_curve_width = width  # type: ignore[attr-defined]
    return build


def load_source() -> tuple[Image.Image, dict[str, np.ndarray]]:
    source = Image.open(SOURCE_IMAGE).convert("RGBA")
    rgba = np.asarray(source)
    alpha = rgba[:, :, 3] > 8
    rgb = rgba[:, :, :3].astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b)
    channels = {
        "alpha": alpha,
        "dark": (luminance < 96) & alpha,
        "very_dark": (luminance < 58) & alpha,
        "skin": (r > 128) & (g > 76) & (b > 64) & (r > g + 15) & (r > b + 18) & alpha,
        "pink": (r > 116) & (b > 78) & (g < 132) & alpha,
        "cyan": (b > 124) & (g > 104) & (r < 100) & alpha,
        "metal": (r > 95) & (g > 70) & (b < 86) & alpha,
        "light": (luminance > 150) & alpha,
    }
    return source, channels


def feather(mask: np.ndarray, radius: float = 0.75) -> Image.Image:
    image = Image.fromarray((mask.astype(np.uint8) * 255), "L")
    if radius:
        image = image.filter(ImageFilter.GaussianBlur(radius))
    return image


def extract_part(source: Image.Image, spec: PartSpec, channels: dict[str, np.ndarray]) -> tuple[Image.Image, list[int], int]:
    mask = spec.mask(source.size, channels)
    ys, xs = np.where(mask)
    if xs.size == 0:
        raise ValueError(f"Part mask produced no pixels: {spec.name}")

    x0 = max(0, int(xs.min()) - spec.padding)
    y0 = max(0, int(ys.min()) - spec.padding)
    x1 = min(source.width, int(xs.max()) + spec.padding + 1)
    y1 = min(source.height, int(ys.max()) + spec.padding + 1)

    generated_color = getattr(spec.mask, "generated_color", None)
    if generated_color is not None:
        layer = Image.new("RGBA", source.size, generated_color)
        alpha = feather(mask, 0.9)
        layer.putalpha(alpha)
    elif hasattr(spec.mask, "generated_curve_points"):
        layer = Image.new("RGBA", source.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.line(
            getattr(spec.mask, "generated_curve_points"),
            fill=generated_color or (64, 24, 36, 220),
            width=getattr(spec.mask, "generated_curve_width"),
            joint="curve",
        )
        alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(0.4))
        layer.putalpha(alpha)
    else:
        layer = Image.new("RGBA", source.size, (0, 0, 0, 0))
        layer.paste(source, (0, 0), feather(mask, 0.65))

    cropped = layer.crop((x0, y0, x1, y1))
    nontransparent = int((np.asarray(cropped.getchannel("A")) > 0).sum())
    return cropped, [x0, y0, x1, y1], nontransparent


def part_specs() -> list[PartSpec]:
    return [
        PartSpec("10_head", "face_base", polygon([(566, 300), (720, 244), (855, 324), (861, 471), (774, 570), (622, 546), (551, 438)], "skin"), "Main visible face plate for head angle and expressions."),
        PartSpec("10_head", "neck", polygon([(700, 515), (825, 513), (849, 650), (686, 657)], "skin"), "Neck skin part hidden partly by collar and hair."),
        PartSpec("10_head", "ear_screen_l_outer", polygon([(450, 120), (526, 181), (614, 291), (574, 311), (494, 244), (454, 150)]), "Left-screen cat ear outer silhouette."),
        PartSpec("10_head", "ear_screen_l_inner", polygon([(474, 154), (526, 192), (585, 272), (536, 260), (492, 225)]), "Left-screen cat ear inner fur/pink area."),
        PartSpec("10_head", "ear_screen_r_outer", polygon([(716, 113), (884, 39), (890, 184), (838, 266), (776, 218)]), "Right-screen cat ear outer silhouette."),
        PartSpec("10_head", "ear_screen_r_inner", polygon([(800, 90), (868, 61), (866, 170), (833, 235), (790, 202)]), "Right-screen cat ear inner fur/pink area."),
        PartSpec("10_head", "face_under_bangs_fill", generated_polygon([(548, 260), (742, 205), (868, 310), (860, 527), (765, 631), (592, 560), (526, 392)], (235, 176, 162, 232), 3.0), "Hidden fill plate behind bangs for head-angle and blink cleanup.", False),
        PartSpec("20_eyes", "eye_screen_l_white", ellipse((580, 330, 705, 414), "light"), "Left-screen eye white."),
        PartSpec("20_eyes", "eye_screen_l_iris", ellipse((584, 330, 705, 414), "pink"), "Left-screen iris and pupil color."),
        PartSpec("20_eyes", "eye_screen_l_line", ellipse((572, 318, 713, 421), "dark"), "Left-screen eyelid/line art."),
        PartSpec("20_eyes", "eye_screen_l_blink_cover", generated_ellipse((584, 327, 704, 414), (228, 171, 158, 228), 1.0), "Left-screen blink skin cover.", False),
        PartSpec("20_eyes", "eye_screen_l_closed_line", generated_curve([(592, 374), (632, 391), (688, 375)], (54, 31, 38, 225), 5), "Left-screen closed-eye line.", False),
        PartSpec("20_eyes", "eye_screen_r_white", ellipse((748, 318, 868, 402), "light"), "Right-screen eye white."),
        PartSpec("20_eyes", "eye_screen_r_iris", ellipse((748, 318, 868, 402), "pink"), "Right-screen iris and pupil color."),
        PartSpec("20_eyes", "eye_screen_r_line", ellipse((740, 306, 878, 410), "dark"), "Right-screen eyelid/line art."),
        PartSpec("20_eyes", "eye_screen_r_blink_cover", generated_ellipse((749, 315, 869, 402), (228, 171, 158, 228), 1.0), "Right-screen blink skin cover.", False),
        PartSpec("20_eyes", "eye_screen_r_closed_line", generated_curve([(758, 360), (806, 377), (858, 358)], (54, 31, 38, 225), 5), "Right-screen closed-eye line.", False),
        PartSpec("25_brows", "brow_screen_l", polygon([(570, 302), (683, 288), (700, 326), (579, 342)], "very_dark"), "Left-screen brow for thinking/serious expression."),
        PartSpec("25_brows", "brow_screen_r", polygon([(743, 289), (854, 283), (865, 321), (748, 329)], "very_dark"), "Right-screen brow for thinking/serious expression."),
        PartSpec("30_mouth", "mouth_closed_smile", ellipse((720, 492, 805, 546), "dark", "pink"), "Original closed smile mouth."),
        PartSpec("30_mouth", "mouth_open_a", generated_ellipse((733, 507, 790, 538), (62, 23, 34, 225), 0.55), "Open A mouth interior for talk/lip sync.", False),
        PartSpec("30_mouth", "mouth_open_o", generated_ellipse((744, 503, 781, 543), (55, 20, 34, 225), 0.55), "Rounded O mouth interior for talk/lip sync.", False),
        PartSpec("30_mouth", "mouth_smile_overlay", generated_curve([(724, 505), (756, 529), (799, 501)], (96, 40, 50, 210), 4), "Smile form overlay.", False),
        PartSpec("30_mouth", "mouth_serious_overlay", generated_curve([(731, 525), (760, 514), (793, 526)], (72, 34, 45, 210), 4), "Serious/flat mouth form overlay.", False),
        PartSpec("40_back_hair", "hair_back_top_mass", polygon([(492, 100), (657, 75), (800, 84), (884, 205), (858, 390), (704, 438), (550, 392), (486, 246)], "dark"), "Back/top hair mass behind face and bangs."),
        PartSpec("40_back_hair", "hair_side_screen_l", polygon([(438, 210), (555, 330), (612, 548), (555, 832), (396, 941), (245, 912), (392, 668)], "dark"), "Left-screen side hair mass."),
        PartSpec("40_back_hair", "hair_side_screen_r", polygon([(826, 200), (996, 359), (1178, 693), (1278, 916), (1108, 953), (916, 780), (830, 502)], "dark"), "Right-screen side hair mass."),
        PartSpec("40_back_hair", "hair_tail_screen_l", polygon([(313, 565), (558, 688), (499, 936), (243, 925), (321, 784)]), "Left-screen long tail hair with visible pink tips."),
        PartSpec("40_back_hair", "hair_tail_screen_r", polygon([(1006, 505), (1179, 714), (1280, 917), (1097, 950), (937, 795)]), "Right-screen long tail hair with visible pink tips."),
        PartSpec("40_back_hair", "hair_under_ears_fill", generated_polygon([(464, 105), (690, 45), (900, 71), (934, 376), (833, 560), (511, 517), (409, 249)], (27, 24, 31, 235), 4.0), "Hidden dark hair plate under moving ears.", False),
        PartSpec("50_front_hair", "bangs_center", polygon([(596, 116), (715, 101), (785, 172), (793, 325), (731, 437), (633, 433), (579, 318)], "dark"), "Center bangs over forehead."),
        PartSpec("50_front_hair", "bangs_screen_l", polygon([(492, 176), (624, 181), (664, 345), (610, 504), (520, 438), (486, 287)], "dark"), "Left-screen bangs and cheek-side front hair."),
        PartSpec("50_front_hair", "bangs_screen_r", polygon([(718, 124), (866, 208), (861, 405), (783, 521), (716, 374)], "dark"), "Right-screen bangs and front hair."),
        PartSpec("50_front_hair", "hair_over_eyes_strands", union(ellipse((570, 315, 712, 426), "dark"), ellipse((738, 306, 876, 410), "dark")), "Fine front hair crossing the eyes."),
        PartSpec("50_front_hair", "long_lock_screen_l", polygon([(386, 278), (555, 374), (594, 780), (418, 944), (308, 822), (394, 548)], "dark", "pink"), "Left-screen long front/side lock."),
        PartSpec("50_front_hair", "long_lock_screen_r", polygon([(846, 295), (1023, 410), (1114, 790), (1050, 946), (918, 784), (832, 505)], "dark", "pink"), "Right-screen long front/side lock."),
        PartSpec("60_body", "torso_inner", polygon([(606, 492), (866, 431), (1025, 558), (1010, 941), (617, 947), (505, 720)], "dark"), "Center torso and inner clothing."),
        PartSpec("60_body", "jacket_sleeve_screen_l", polygon([(381, 484), (628, 514), (700, 730), (598, 941), (372, 920), (327, 691)], "dark", "pink"), "Left-screen jacket sleeve."),
        PartSpec("60_body", "jacket_sleeve_screen_r", polygon([(826, 423), (1088, 414), (1169, 690), (1138, 917), (887, 947), (779, 722)], "dark", "pink"), "Right-screen jacket sleeve."),
        PartSpec("60_body", "torso_under_arms_fill", generated_polygon([(494, 465), (866, 398), (1130, 593), (1128, 944), (483, 949), (362, 706)], (31, 29, 36, 232), 4.0), "Hidden body/jacket fill under arm motion.", False),
        PartSpec("70_arms_hands", "hand_at_cheek", polygon([(568, 418), (625, 382), (696, 414), (684, 507), (598, 532), (553, 489)], "skin"), "Hand resting on cheek."),
        PartSpec("70_arms_hands", "front_hand", polygon([(656, 821), (744, 825), (779, 899), (728, 952), (643, 932), (617, 870)], "skin"), "Front resting hand."),
        PartSpec("70_arms_hands", "cheek_hand_socket_fill", generated_polygon([(548, 451), (685, 430), (728, 545), (626, 612), (520, 558)], (236, 176, 160, 220), 2.5), "Hidden cheek/skin fill behind cheek hand.", False),
        PartSpec("70_arms_hands", "wave_arm_proxy", generated_polygon([(468, 482), (642, 426), (708, 552), (584, 665), (438, 592)], (31, 29, 36, 230), 2.5), "Wave pose proxy sleeve; repaint before final production.", False),
        PartSpec("70_arms_hands", "wave_hand_proxy", generated_polygon([(586, 374), (674, 356), (716, 420), (670, 502), (568, 492)], (234, 173, 159, 215), 2.0), "Wave pose proxy hand; repaint before final production.", False),
        PartSpec("80_accessories", "hair_clip_screen_r", polygon([(795, 194), (881, 203), (881, 293), (789, 284)], "metal", "dark", "light"), "Hair clip accessory."),
        PartSpec("80_accessories", "earring_screen_r", polygon([(855, 296), (906, 293), (918, 526), (850, 530)], "metal", "dark", "pink"), "Right-screen earring/chain."),
        PartSpec("80_accessories", "ear_charm_screen_l", polygon([(466, 205), (523, 218), (535, 352), (458, 351)]), "Left-screen ear charm."),
        PartSpec("80_accessories", "necklace_center_charm", polygon([(733, 520), (834, 514), (862, 734), (731, 739)], "metal", "cyan", "dark"), "Necklace and center cyan charm."),
        PartSpec("80_accessories", "sleeve_device_badge", polygon([(966, 606), (1088, 636), (1106, 783), (982, 806)], "cyan", "metal", "dark", "pink", "light"), "Sleeve device/status badge."),
        PartSpec("80_accessories", "hanging_keychain_charm", polygon([(1046, 642), (1167, 643), (1187, 940), (1050, 944)], "cyan", "metal", "dark", "pink", "light"), "Hanging keychain charm."),
        PartSpec("80_accessories", "cyan_status_lights", rect((500, 120, 1205, 930), "cyan"), "All cyan glow pixels gathered for status-light effects.", False),
    ]


def pack_parts(parts: list[tuple[PartSpec, Image.Image, list[int], int]]) -> list[tuple[PartSpec, Image.Image, list[int], int, int, int]]:
    packed: list[tuple[PartSpec, Image.Image, list[int], int, int, int]] = []
    x = ATLAS_PADDING
    y = ATLAS_PADDING
    row_h = 0
    for spec, image, bbox, pixels in parts:
        w, h = image.size
        if x + w + ATLAS_PADDING > ATLAS_SIZE:
            x = ATLAS_PADDING
            y += row_h + ATLAS_PADDING
            row_h = 0
        if y + h + ATLAS_PADDING > ATLAS_SIZE:
            raise RuntimeError("Atlas is full; increase ATLAS_SIZE or reduce padding.")
        packed.append((spec, image, bbox, pixels, x, y))
        x += w + ATLAS_PADDING
        row_h = max(row_h, h)
    return packed


def build_atlas() -> list[PartOutput]:
    source, channels = load_source()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    PARTS_DIR.mkdir(parents=True, exist_ok=True)

    extracted: list[tuple[PartSpec, Image.Image, list[int], int]] = []
    for spec in part_specs():
        image, bbox, pixels = extract_part(source, spec, channels)
        extracted.append((spec, image, bbox, pixels))

    # Grouped order keeps the atlas readable like a Cubism texture page.
    packed = pack_parts(extracted)
    atlas = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (0, 0, 0, 0))
    labeled = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (0, 0, 0, 0))
    label_draw = ImageDraw.Draw(labeled)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()

    outputs: list[PartOutput] = []
    for spec, image, bbox, pixels, x, y in packed:
        part_dir = PARTS_DIR / spec.group
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = part_dir / f"{spec.name}.png"
        image.save(part_path)

        atlas.alpha_composite(image, (x, y))
        labeled.alpha_composite(image, (x, y))
        label_draw.rectangle((x, max(0, y - 24), x + min(image.width, 360), y - 2), fill=(20, 20, 24, 180))
        label_draw.text((x + 4, max(0, y - 23)), spec.name[:38], fill=(240, 240, 244, 255), font=font)

        rel = str(part_path.relative_to(OUTPUT_ROOT)).replace("\\", "/")
        outputs.append(
            PartOutput(
                group=spec.group,
                name=spec.name,
                purpose=spec.purpose,
                visible=spec.visible,
                file=rel,
                bbox_source=bbox,
                bbox_atlas=[x, y, x + image.width, y + image.height],
                size=[image.width, image.height],
                nontransparent_pixels=pixels,
            )
        )

    atlas.save(OUTPUT_ROOT / f"{DOC_NAME}.png")
    labeled.save(OUTPUT_ROOT / f"{DOC_NAME}_labeled.png")
    write_manifest(outputs)
    write_notes(outputs)
    write_photoshop_script(outputs)
    return outputs


def write_manifest(outputs: Iterable[PartOutput]) -> None:
    data = {
        "version": 1,
        "source": str(SOURCE_IMAGE.relative_to(REPO_ROOT)).replace("\\", "/"),
        "atlas": {
            "file": f"{DOC_NAME}.png",
            "labeledFile": f"{DOC_NAME}_labeled.png",
            "width": ATLAS_SIZE,
            "height": ATLAS_SIZE,
        },
        "intent": "Body-part texture-atlas style split for Live2D Cubism source preparation.",
        "coordinateConvention": "screen_l/screen_r refer to visible image side, not character anatomical left/right.",
        "requestedMotionCoverage": {
            "breath": ["torso_inner", "jacket_sleeve_screen_l", "jacket_sleeve_screen_r", "hair_tail_screen_l", "hair_tail_screen_r"],
            "blink": ["eye_screen_l_*", "eye_screen_r_*", "brow_screen_l", "brow_screen_r"],
            "ear_flick": ["ear_screen_l_outer", "ear_screen_l_inner", "ear_screen_r_outer", "ear_screen_r_inner", "hair_under_ears_fill"],
            "talk_lip_sync": ["mouth_closed_smile", "mouth_open_a", "mouth_open_o", "mouth_smile_overlay", "mouth_serious_overlay"],
            "wave": ["hand_at_cheek", "wave_arm_proxy", "wave_hand_proxy", "cheek_hand_socket_fill"],
            "wait": ["front/back hair parts", "torso_inner", "accessory parts"],
            "thinking": ["brow_screen_l", "brow_screen_r", "eye parts", "mouth_serious_overlay"],
            "serious_inspect": ["brows", "eye lines", "mouth_serious_overlay", "torso body lean"],
        },
        "parts": [part.__dict__ for part in outputs],
        "warnings": [
            "The source is a flattened illustration. Hidden geometry cannot be recovered perfectly without manual repaint.",
            "Proxy/fill parts are hidden helpers and should be redrawn by an artist before final commercial-quality Cubism export.",
            "This atlas is for part separation review and Photoshop/Cubism preparation, not a final Cubism texture exported from a rigged .cmo3.",
        ],
    }
    (OUTPUT_ROOT / f"{DOC_NAME}.parts-manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_notes(outputs: Iterable[PartOutput]) -> None:
    parts = list(outputs)
    groups: dict[str, list[PartOutput]] = {}
    for part in parts:
        groups.setdefault(part.group, []).append(part)

    lines = [
        "# Character Live2D Parts Atlas",
        "",
        "This is the corrected output format: each visible body part is cropped as its own transparent PNG and placed on a 4096x4096 atlas, similar to a Cubism texture page.",
        "",
        "## Files",
        "",
        f"- `{DOC_NAME}.png`: unlabeled texture-atlas style page.",
        f"- `{DOC_NAME}_labeled.png`: same page with part labels for review.",
        f"- `{DOC_NAME}_layered.psd`: Photoshop-generated layered atlas document after running the JSX script.",
        f"- `{DOC_NAME}.parts-manifest.json`: machine-readable part list and atlas positions.",
        "- `parts/`: cropped transparent PNGs by semantic group.",
        "",
        "## Production Caveat",
        "",
        "A flattened PNG cannot reveal hidden skin, sleeve, hair, or mouth interiors. The generated `*_fill`, blink, mouth, and wave proxy parts are rigging placeholders. For professional Cubism production, repaint those helper parts in Photoshop before final mesh setup.",
        "",
        "## Groups",
        "",
    ]
    for group, group_parts in groups.items():
        lines.append(f"### {group}")
        for part in group_parts:
            visibility = "visible" if part.visible else "hidden/helper"
            lines.append(f"- `{part.name}` ({visibility}, {part.size[0]}x{part.size[1]}): {part.purpose}")
        lines.append("")

    lines.extend(
        [
            "## Rigging Targets",
            "",
            "| Requested action | Parameters / parts |",
            "| --- | --- |",
            "| Breathing | `ParamBreath`, torso/jacket parts, subtle hair tail physics |",
            "| Blinking | `ParamEyeLOpen`, `ParamEyeROpen`, blink covers and closed lid lines |",
            "| Ear light movement | ear outer/inner parts plus `hair_under_ears_fill` |",
            "| Talking mouth | `ParamMouthOpenY`, `ParamMouthForm`, A/O/closed mouth parts |",
            "| Waving | repaint and rig `wave_arm_proxy` and `wave_hand_proxy` |",
            "| Waiting | low-amplitude body sway, eye tracking, hair/accessory physics |",
            "| Thinking | lower brows, eye gaze up/side, serious mouth overlay |",
            "| Serious inspect | focused brows, small forward body lean, reduced smile |",
            "",
        ]
    )
    (OUTPUT_ROOT / "LIVE2D_PARTS_ATLAS_NOTES.md").write_text("\n".join(lines), encoding="utf-8")


def write_photoshop_script(outputs: Iterable[PartOutput]) -> None:
    payload = {
        "docName": DOC_NAME,
        "width": ATLAS_SIZE,
        "height": ATLAS_SIZE,
        "root": str(OUTPUT_ROOT).replace("\\", "/"),
        "psd": str((OUTPUT_ROOT / f"{DOC_NAME}_layered.psd")).replace("\\", "/"),
        "parts": [part.__dict__ for part in outputs],
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

function px(value) {{
  return value.as("px");
}}

function importPart(targetDoc, group, part) {{
  var file = new File(payload.root + "/" + part.file);
  if (!file.exists) {{
    throw new Error("Missing part PNG: " + file.fsName);
  }}
  var sourceDoc = app.open(file);
  app.activeDocument = sourceDoc;
  sourceDoc.selection.selectAll();
  sourceDoc.selection.copy(true);
  sourceDoc.close(SaveOptions.DONOTSAVECHANGES);
  app.activeDocument = targetDoc;
  targetDoc.paste();
  var imported = targetDoc.activeLayer;
  imported.name = part.name;
  imported.visible = part.visible;
  var left = px(imported.bounds[0]);
  var top = px(imported.bounds[1]);
  imported.translate(part.bbox_atlas[0] - left, part.bbox_atlas[1] - top);
  imported.move(group, ElementPlacement.INSIDE);
}}

for (var existingIndex = app.documents.length - 1; existingIndex >= 0; existingIndex--) {{
  var existingDoc = app.documents[existingIndex];
  if (existingDoc.name.indexOf(payload.docName) === 0) {{
    app.activeDocument = existingDoc;
    existingDoc.close(SaveOptions.DONOTSAVECHANGES);
  }}
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
for (var i = payload.parts.length - 1; i >= 0; i--) {{
  var part = payload.parts[i];
  if (!groups[part.group]) {{
    groups[part.group] = ensureGroup(targetDoc, part.group);
  }}
  importPart(targetDoc, groups[part.group], part);
}}

app.activeDocument = targetDoc;
var saveFile = new File(payload.psd);
var saveOptions = new PhotoshopSaveOptions();
saveOptions.layers = true;
targetDoc.saveAs(saveFile, saveOptions, true, Extension.LOWERCASE);
"""
    (OUTPUT_ROOT / "assemble-character-live2d-parts-atlas.jsx").write_text(script, encoding="utf-8")


def main() -> None:
    if not SOURCE_IMAGE.exists():
        raise FileNotFoundError(SOURCE_IMAGE)
    outputs = build_atlas()
    summary = {
        "source": str(SOURCE_IMAGE),
        "output": str(OUTPUT_ROOT),
        "atlas": str(OUTPUT_ROOT / f"{DOC_NAME}.png"),
        "labeledAtlas": str(OUTPUT_ROOT / f"{DOC_NAME}_labeled.png"),
        "photoshopScript": str(OUTPUT_ROOT / "assemble-character-live2d-parts-atlas.jsx"),
        "partCount": len(outputs),
        "visibleParts": sum(1 for part in outputs if part.visible),
        "hiddenHelperParts": sum(1 for part in outputs if not part.visible),
        "groups": sorted({part.group for part in outputs}),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
