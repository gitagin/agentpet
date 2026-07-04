from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = REPO_ROOT / "apps" / "desktop" / "public" / "live2d" / "character_live2d_runtime"


def linear_curve(target: str, parameter_id: str, keyframes: list[tuple[float, float]]) -> dict:
    if len(keyframes) < 2:
        raise ValueError(parameter_id)
    segments: list[float | int] = [round(keyframes[0][0], 3), round(keyframes[0][1], 4)]
    for time, value in keyframes[1:]:
        segments.extend([0, round(time, 3), round(value, 4)])
    return {"Target": target, "Id": parameter_id, "Segments": segments}


def motion(duration: float, fps: float, loop: bool, curves: list[dict]) -> dict:
    total_segment_count = 0
    total_point_count = 0
    for curve in curves:
        point_count = 1 + (len(curve["Segments"]) - 2) // 3
        total_point_count += point_count
        total_segment_count += point_count - 1
    return {
        "Version": 3,
        "Meta": {
            "Duration": duration,
            "Fps": fps,
            "Loop": loop,
            "AreBeziersRestricted": True,
            "CurveCount": len(curves),
            "TotalSegmentCount": total_segment_count,
            "TotalPointCount": total_point_count,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": curves,
    }


def expression(parameters: list[tuple[str, float, str]], fade_in: float = 0.25, fade_out: float = 0.35) -> dict:
    return {
        "Type": "Live2D Expression",
        "FadeInTime": fade_in,
        "FadeOutTime": fade_out,
        "Parameters": [
            {"Id": parameter_id, "Value": value, "Blend": blend}
            for parameter_id, value, blend in parameters
        ],
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_motions() -> dict[str, list[str]]:
    motions: dict[str, list[tuple[str, dict]]] = {
        "Idle": [
            (
                "00_idle_breathe.motion3.json",
                motion(
                    6.0,
                    30.0,
                    True,
                    [
                        linear_curve("Model", "Opacity", [(0, 1), (6, 1)]),
                        linear_curve("Parameter", "ParamBreath", [(0, 0.15), (1.5, 0.82), (3.0, 0.2), (4.5, 0.72), (6.0, 0.15)]),
                        linear_curve("Parameter", "ParamBodyAngleY", [(0, 0), (1.5, 1.4), (3.0, 0), (4.5, -1.0), (6.0, 0)]),
                        linear_curve("Parameter", "ParamBodyAngleZ", [(0, 0), (1.5, -0.8), (3.0, 0), (4.5, 0.7), (6.0, 0)]),
                        linear_curve("Parameter", "ParamHairFront", [(0, 0), (1.5, 0.18), (3.0, 0), (4.5, -0.12), (6.0, 0)]),
                        linear_curve("Parameter", "ParamHairSide", [(0, 0), (1.5, -0.12), (3.0, 0), (4.5, 0.12), (6.0, 0)]),
                    ],
                ),
            ),
            (
                "01_wait_soft_loop.motion3.json",
                motion(
                    8.0,
                    30.0,
                    True,
                    [
                        linear_curve("Model", "Opacity", [(0, 1), (8, 1)]),
                        linear_curve("Parameter", "ParamAngleX", [(0, 0), (2.0, -3), (4.0, 2), (6.0, 0.5), (8.0, 0)]),
                        linear_curve("Parameter", "ParamAngleY", [(0, 0), (2.0, 1.5), (4.0, -1), (6.0, 0.5), (8.0, 0)]),
                        linear_curve("Parameter", "ParamEyeBallX", [(0, 0), (2.0, -0.18), (4.0, 0.16), (6.0, 0.05), (8.0, 0)]),
                        linear_curve("Parameter", "ParamEyeBallY", [(0, 0), (2.0, 0.08), (4.0, -0.06), (6.0, 0.03), (8.0, 0)]),
                        linear_curve("Parameter", "ParamEyeLOpen", [(0, 1), (3.0, 1), (3.08, 0), (3.18, 1), (8.0, 1)]),
                        linear_curve("Parameter", "ParamEyeROpen", [(0, 1), (3.0, 1), (3.08, 0), (3.18, 1), (8.0, 1)]),
                    ],
                ),
            ),
        ],
        "Face": [
            (
                "00_blink.motion3.json",
                motion(
                    0.55,
                    30.0,
                    False,
                    [
                        linear_curve("Parameter", "ParamEyeLOpen", [(0, 1), (0.12, 0), (0.2, 0), (0.34, 1), (0.55, 1)]),
                        linear_curve("Parameter", "ParamEyeROpen", [(0, 1), (0.12, 0), (0.2, 0), (0.34, 1), (0.55, 1)]),
                    ],
                ),
            ),
            (
                "01_talk_mouth_loop.motion3.json",
                motion(
                    2.4,
                    30.0,
                    True,
                    [
                        linear_curve("Parameter", "ParamMouthOpenY", [(0, 0.0), (0.16, 0.65), (0.32, 0.18), (0.54, 0.82), (0.78, 0.25), (1.0, 0.55), (1.22, 0.12), (1.5, 0.7), (1.78, 0.2), (2.1, 0.45), (2.4, 0.0)]),
                        linear_curve("Parameter", "ParamMouthForm", [(0, 0.2), (0.54, 0.55), (1.22, -0.2), (1.78, 0.45), (2.4, 0.2)]),
                        linear_curve("Parameter", "ParamCheek", [(0, 0.1), (1.2, 0.18), (2.4, 0.1)]),
                    ],
                ),
            ),
        ],
        "Gesture": [
            (
                "00_support_hand_down_to_sit.motion3.json",
                motion(
                    3.2,
                    30.0,
                    False,
                    [
                        linear_curve("Parameter", "ParamArmLA", [(0, 1.0), (0.8, 0.82), (1.8, 0.35), (3.2, 0.0)]),
                        linear_curve("Parameter", "ParamArmLB", [(0, 0.0), (0.8, 0.2), (1.8, 0.72), (3.2, 1.0)]),
                        linear_curve("Parameter", "ParamHandDown", [(0, 0.0), (0.8, 0.25), (1.8, 0.78), (3.2, 1.0)]),
                        linear_curve("Parameter", "ParamBodyAngleZ", [(0, -2), (1.2, -0.8), (2.3, 0.2), (3.2, 0)]),
                        linear_curve("Parameter", "ParamBodyAngleY", [(0, -1), (1.4, 0.2), (3.2, 0)]),
                        linear_curve("Parameter", "ParamAngleZ", [(0, -2), (1.6, -0.6), (3.2, 0)]),
                    ],
                ),
            ),
            (
                "01_ear_twitch.motion3.json",
                motion(
                    1.35,
                    30.0,
                    False,
                    [
                        linear_curve("Parameter", "ParamEarLAngle", [(0, 0), (0.18, 0.55), (0.32, -0.25), (0.48, 0.2), (0.8, 0), (1.35, 0)]),
                        linear_curve("Parameter", "ParamEarRAngle", [(0, 0), (0.16, -0.45), (0.34, 0.25), (0.52, -0.16), (0.8, 0), (1.35, 0)]),
                        linear_curve("Parameter", "ParamAngleZ", [(0, 0), (0.24, 1.1), (0.55, -0.7), (1.35, 0)]),
                    ],
                ),
            ),
        ],
        "Chat": [
            (
                "00_thinking_loop.motion3.json",
                motion(
                    4.0,
                    30.0,
                    True,
                    [
                        linear_curve("Parameter", "ParamAngleX", [(0, 0), (1.5, -4), (3.0, -2), (4.0, 0)]),
                        linear_curve("Parameter", "ParamAngleY", [(0, 0), (1.5, 2.5), (3.0, 1.0), (4.0, 0)]),
                        linear_curve("Parameter", "ParamEyeBallX", [(0, 0), (1.4, -0.3), (3.0, -0.1), (4.0, 0)]),
                        linear_curve("Parameter", "ParamEyeBallY", [(0, 0), (1.4, 0.18), (3.0, 0.08), (4.0, 0)]),
                        linear_curve("Parameter", "ParamBrowLY", [(0, 0), (1.4, 0.25), (3.0, 0.12), (4.0, 0)]),
                        linear_curve("Parameter", "ParamBrowRY", [(0, 0), (1.4, -0.12), (3.0, -0.05), (4.0, 0)]),
                        linear_curve("Parameter", "ParamMouthForm", [(0, 0), (1.4, -0.18), (4.0, 0)]),
                    ],
                ),
            ),
            (
                "01_serious_inspect_loop.motion3.json",
                motion(
                    4.8,
                    30.0,
                    True,
                    [
                        linear_curve("Parameter", "ParamAngleX", [(0, 0), (1.6, 3.5), (3.2, -1.5), (4.8, 0)]),
                        linear_curve("Parameter", "ParamAngleY", [(0, 0), (1.6, -2.2), (3.2, -1.0), (4.8, 0)]),
                        linear_curve("Parameter", "ParamEyeBallX", [(0, 0), (1.6, 0.28), (3.2, -0.18), (4.8, 0)]),
                        linear_curve("Parameter", "ParamEyeBallY", [(0, 0), (1.6, -0.12), (3.2, -0.16), (4.8, 0)]),
                        linear_curve("Parameter", "ParamEyeLOpen", [(0, 1), (1.6, 0.72), (3.2, 0.82), (4.8, 1)]),
                        linear_curve("Parameter", "ParamEyeROpen", [(0, 1), (1.6, 0.72), (3.2, 0.82), (4.8, 1)]),
                        linear_curve("Parameter", "ParamMouthForm", [(0, 0), (1.6, -0.32), (3.2, -0.2), (4.8, 0)]),
                    ],
                ),
            ),
        ],
    }

    written: dict[str, list[str]] = {}
    for group, items in motions.items():
        written[group] = []
        for filename, data in items:
            write_json(OUTPUT_ROOT / "motions" / group / filename, data)
            written[group].append(f"motions/{group}/{filename}")
    return written


def build_expressions() -> list[tuple[str, str]]:
    expressions = {
        "angry": expression([
            ("ParamBrowLY", -0.55, "Add"),
            ("ParamBrowRY", -0.55, "Add"),
            ("ParamBrowLAngle", -0.45, "Add"),
            ("ParamBrowRAngle", 0.45, "Add"),
            ("ParamMouthForm", -0.45, "Add"),
            ("ParamMouthOpenY", 0.08, "Add"),
            ("ParamCheek", 0.15, "Add"),
        ]),
        "happy": expression([
            ("ParamEyeLOpen", 0.35, "Multiply"),
            ("ParamEyeROpen", 0.35, "Multiply"),
            ("ParamEyeLSmile", 0.75, "Add"),
            ("ParamEyeRSmile", 0.75, "Add"),
            ("ParamMouthForm", 0.8, "Add"),
            ("ParamMouthOpenY", 0.28, "Add"),
            ("ParamCheek", 0.35, "Add"),
        ]),
        "confused": expression([
            ("ParamBrowLY", 0.45, "Add"),
            ("ParamBrowRY", -0.18, "Add"),
            ("ParamBrowLAngle", 0.35, "Add"),
            ("ParamEyeBallX", -0.25, "Add"),
            ("ParamEyeBallY", 0.08, "Add"),
            ("ParamMouthForm", -0.18, "Add"),
            ("ParamMouthOpenY", 0.08, "Add"),
        ]),
        "sad": expression([
            ("ParamBrowLY", -0.28, "Add"),
            ("ParamBrowRY", -0.28, "Add"),
            ("ParamBrowLAngle", 0.25, "Add"),
            ("ParamBrowRAngle", -0.25, "Add"),
            ("ParamEyeLOpen", 0.72, "Multiply"),
            ("ParamEyeROpen", 0.72, "Multiply"),
            ("ParamMouthForm", -0.72, "Add"),
            ("ParamTear", 0.75, "Add"),
        ]),
        "fear": expression([
            ("ParamEyeLOpen", 1.12, "Multiply"),
            ("ParamEyeROpen", 1.12, "Multiply"),
            ("ParamBrowLY", 0.5, "Add"),
            ("ParamBrowRY", 0.5, "Add"),
            ("ParamMouthOpenY", 0.52, "Add"),
            ("ParamMouthForm", -0.18, "Add"),
            ("ParamBodyAngleY", -0.22, "Add"),
        ]),
        "surprise": expression([
            ("ParamEyeLOpen", 1.18, "Multiply"),
            ("ParamEyeROpen", 1.18, "Multiply"),
            ("ParamBrowLY", 0.6, "Add"),
            ("ParamBrowRY", 0.6, "Add"),
            ("ParamMouthOpenY", 0.82, "Add"),
            ("ParamMouthForm", 0.02, "Add"),
        ]),
        "disgust": expression([
            ("ParamBrowLY", -0.35, "Add"),
            ("ParamBrowRY", -0.22, "Add"),
            ("ParamBrowLForm", 0.45, "Add"),
            ("ParamBrowRForm", 0.25, "Add"),
            ("ParamMouthForm", -0.55, "Add"),
            ("ParamAngleZ", -0.08, "Add"),
        ]),
        "contempt": expression([
            ("ParamBrowLY", 0.22, "Add"),
            ("ParamBrowRY", -0.18, "Add"),
            ("ParamEyeROpen", 0.5, "Multiply"),
            ("ParamMouthForm", 0.42, "Add"),
            ("ParamAngleZ", 0.08, "Add"),
        ]),
    }
    entries: list[tuple[str, str]] = []
    for name, data in expressions.items():
        file = f"expressions/{name}.exp3.json"
        write_json(OUTPUT_ROOT / file, data)
        entries.append((name, file))
    return entries


def build_profiles(motions: dict[str, list[str]], expressions: list[tuple[str, str]]) -> None:
    expression_refs = [{"Name": name, "File": file} for name, file in expressions]
    motion_refs = {
        group: [{"File": file.replace(f"motions/{group}/", f"motions/{group}/")} for file in files]
        for group, files in motions.items()
    }
    write_json(
        OUTPUT_ROOT / "character_live2d.model3.template.json",
        {
            "Version": 3,
            "FileReferences": {
                "Moc": "character_live2d_import.moc3",
                "Textures": ["character_live2d_import.2048/texture_00.png"],
                "Expressions": expression_refs,
                "Motions": motion_refs,
            },
            "Groups": [
                {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]},
                {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
            ],
            "HitAreas": [
                {"Id": "HitAreaHead", "Name": "Head"},
                {"Id": "HitAreaBody", "Name": "Body"},
            ],
        },
    )

    action_profile = {
        "version": 1,
        "description": "Action map for character_live2d_import after Cubism export.",
        "actions": {
            "idle": {"expression": "happy", "motion": {"group": "Idle", "index": 0}, "petHint": "待机呼吸。", "controlSummary": "呼吸和轻微身体摆动。"},
            "chat_listen": {"expression": "happy", "motion": {"group": "Idle", "index": 1}, "petHint": "正在听你说。", "controlSummary": "等待与注视动作。"},
            "chat_think": {"expression": "confused", "motion": {"group": "Chat", "index": 0}, "petHint": "正在思考。", "controlSummary": "疑惑眉眼和思考视线。"},
            "chat_talk": {"expression": "happy", "motion": {"group": "Face", "index": 1}, "petHint": "正在说话。", "controlSummary": "循环口型动作。"},
            "chat_done": {"expression": "happy", "motion": {"group": "Idle", "index": 0}, "petHint": "回复完成。", "controlSummary": "回到轻待机。"},
            "serious_inspect": {"expression": "contempt", "motion": {"group": "Chat", "index": 1}, "petHint": "认真查看。", "controlSummary": "压眼、视线巡查、轻微前倾。"},
            "support_hand_down": {"expression": "happy", "motion": {"group": "Gesture", "index": 0}, "petHint": "把撑脸的手放下。", "controlSummary": "从托脸姿势过渡到端坐。"},
            "ear_twitch": {"expression": "happy", "motion": {"group": "Gesture", "index": 1}, "petHint": "耳朵轻动。", "controlSummary": "左右耳轻微抖动。"},
            "blink": {"expression": "happy", "motion": {"group": "Face", "index": 0}, "petHint": "眨眼。", "controlSummary": "双眼快速闭合再张开。"},
            "system_error": {"expression": "angry", "motion": {"group": "Chat", "index": 1}, "petHint": "状态需要检查。", "controlSummary": "严肃查看。"},
            "emotion_comfort": {"expression": "sad", "motion": {"group": "Idle", "index": 0}, "petHint": "我会陪着你。", "controlSummary": "柔和陪伴状态。"},
            "celebrate_small": {"expression": "happy", "motion": {"group": "Gesture", "index": 1}, "petHint": "做得不错。", "controlSummary": "轻快反应。"},
        },
    }
    write_json(OUTPUT_ROOT / "character_live2d.actions.json", action_profile)


def write_readme() -> None:
    (OUTPUT_ROOT / "README.md").write_text(
        """# Character Live2D Runtime Action Pack

This folder contains runtime motions and expressions for `character_live2d_import`.

It does not replace Cubism rigging. Import the PSD in Cubism, bind the named
parameters to ArtMeshes/deformers, export `character_live2d_import.moc3` plus
textures, then copy or rename `character_live2d.model3.template.json` to the
exported model3 manifest shape.

Required rig parameters:

- `ParamBreath`
- `ParamEyeLOpen`, `ParamEyeROpen`
- `ParamMouthOpenY`, `ParamMouthForm`
- `ParamEarLAngle`, `ParamEarRAngle`
- `ParamArmLA`, `ParamArmLB`, `ParamHandDown`
- `ParamAngleX`, `ParamAngleY`, `ParamAngleZ`
- `ParamBodyAngleY`, `ParamBodyAngleZ`
- `ParamBrowLY`, `ParamBrowRY`, `ParamBrowLAngle`, `ParamBrowRAngle`
- `ParamEyeBallX`, `ParamEyeBallY`

Included requested actions:

- breathing
- blinking
- ear twitch
- speaking mouth shapes
- support-hand-down-to-seated transition
- waiting
- thinking
- serious inspecting
- angry, happy, confused, sad, fear, surprise, disgust, contempt expressions
""",
        encoding="utf-8",
    )


def main() -> None:
    motions = build_motions()
    expressions = build_expressions()
    build_profiles(motions, expressions)
    write_readme()
    summary = {
        "output": str(OUTPUT_ROOT),
        "motion_count": sum(len(files) for files in motions.values()),
        "expression_count": len(expressions),
        "groups": motions,
        "actions": str(OUTPUT_ROOT / "character_live2d.actions.json"),
        "model3_template": str(OUTPUT_ROOT / "character_live2d.model3.template.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
