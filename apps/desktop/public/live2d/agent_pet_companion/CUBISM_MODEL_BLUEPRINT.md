# Archivist Companion Cubism Model Blueprint

This is the production blueprint for a real Cubism runtime model. It is not a
substitute for `agent_pet_companion.moc3`; the `.moc3` file must still be
exported from Live2D Cubism Editor after the layered source art is drawn and
rigged.

## Target Runtime Deliverable

The final runnable export must contain these files in this folder:

- `agent_pet_companion.model3.json`
- `agent_pet_companion.moc3`
- `textures/texture_00.png`
- `textures/texture_01.png` if the atlas needs a second page
- `expressions/*.exp3.json`
- `motions/<Group>/<motion_name>.motion3.json`
- `agent_pet_companion.physics3.json`
- `agent_pet_companion.cdi3.json`

Only after those files exist should `previewOnly` and `design` be removed from
`public/live2d/models.json`.

## Character Direction

Name: Archivist Companion

Role: local-first memory companion for Agent Pet.

Read: compact desktop assistant, calm and attentive, with enough personality to
feel present while staying quiet beside the user's work.

Core visual anchors:

- Short layered dark teal hair with large, clean Live2D-friendly clumps.
- Warm amber eyes with a tiny cyan interface reflection.
- Cream utility jacket over a charcoal tunic.
- Chest ribbon status light for connection, privacy, memory, and task states.
- Floating notebook shard for chat, wiki, and diary actions.
- Small local-database charm attached near the hip or sleeve.
- Minimal archive tags and straps, kept sparse so the pet stays readable.

Desktop pet priority: the face, shoulders, hands, notebook shard, database charm,
and status light must remain readable at roughly 220 px character width.

## Source Art Requirements

Recommended source format: layered PSD at 4096 x 4096 px.

Recommended safe model frame:

- Full character height: 3500 px.
- Head center: x=2048, y=920.
- Waist center: x=2048, y=2080.
- Feet bottom: y=3820.
- Leave at least 220 px transparent padding around hair, hands, props, and feet.

Art style:

- Clean anime-inspired production art.
- Crisp line art and separated flat-color regions.
- Soft cel shading; avoid painterly merged shadows that cross part boundaries.
- Avoid loose semi-transparent hair strands unless the rigger intentionally
  creates extra physics meshes for them.

PSD group naming must use ASCII names. Display names can be localized later in
Cubism display info, but layer names should stay stable for export automation.

## PSD Layer Tree

Use this layer hierarchy as the source-art contract.

```text
Root
  00_guides_do_not_export
  10_back_hair
    hair_back_base
    hair_back_shadow
    hair_back_highlight
    hair_tail_l
    hair_tail_r
  20_body
    neck
    torso_tunic
    torso_tunic_shadow
    jacket_back
    jacket_left
    jacket_right
    jacket_collar_l
    jacket_collar_r
    chest_status_ribbon_base
    chest_status_ribbon_glow
    belt_archive_tag
  30_head
    head_base
    ear_l
    ear_r
    face_shadow
    nose
    cheek_l
    cheek_r
  40_eyes
    eye_l_white
    eye_l_iris
    eye_l_highlight
    eye_l_line
    eye_l_upper_lid
    eye_l_lower_lid
    eye_r_white
    eye_r_iris
    eye_r_highlight
    eye_r_line
    eye_r_upper_lid
    eye_r_lower_lid
  50_brows
    brow_l
    brow_r
  60_mouth
    mouth_line
    mouth_inner
    mouth_teeth
    mouth_tongue
    mouth_smile_shadow
  70_front_hair
    hair_front_center
    hair_front_l1
    hair_front_l2
    hair_front_r1
    hair_front_r2
    hair_ahoge
  80_arms
    arm_l_upper
    arm_l_lower
    hand_l_base
    hand_l_fingers
    arm_r_upper
    arm_r_lower
    hand_r_base
    hand_r_fingers
  90_props
    notebook_base
    notebook_page_l
    notebook_page_r
    notebook_tabs
    notebook_glow
    database_charm_base
    database_charm_glow
    memory_card_01
    memory_card_02
    wiki_card_01
    task_note
    privacy_shield
```

Layer separation rules:

- Eyes must be independently deformable: whites, irises, highlights, lids, and
  line art separated for each side.
- Mouth must support open/close and form changes without exposing gaps.
- Arms and hands must not be painted into the torso or jacket.
- Props must be separate from hands so motions can show, hide, orbit, or hand off
  props per project action.
- Status glow must be a separate additive-friendly layer.

## Cubism Parts

Use these part IDs in Cubism where possible:

| Part ID | Content | Notes |
| --- | --- | --- |
| `PartRoot` | whole model | top-level root |
| `PartHead` | head, face, ears | driven by head angle deformers |
| `PartHairBack` | back hair | physics target |
| `PartHairFront` | bangs and ahoge | physics target |
| `PartEyeL` | left eye | blink and eyeball tracking |
| `PartEyeR` | right eye | blink and eyeball tracking |
| `PartBrowL` | left brow | expression target |
| `PartBrowR` | right brow | expression target |
| `PartMouth` | mouth | lip sync and expression target |
| `PartBody` | torso and jacket | body sway |
| `PartArmL` | left arm and hand | action motions |
| `PartArmR` | right arm and hand | action motions |
| `PartStatusRibbon` | chest status ribbon | color/glow states |
| `PartNotebook` | floating notebook shard | chat/wiki/memory prop |
| `PartDatabaseCharm` | database charm | memory/search prop |
| `PartCards` | memory/wiki/task cards | action prop family |
| `PartPrivacyShield` | privacy shield | hidden by default |

## Parameter Map

Core parameters:

| Parameter | Range | Default | Purpose |
| --- | ---: | ---: | --- |
| `ParamAngleX` | -30..30 | 0 | head turn |
| `ParamAngleY` | -30..30 | 0 | head tilt up/down |
| `ParamAngleZ` | -30..30 | 0 | head roll |
| `ParamBodyAngleX` | -15..15 | 0 | torso turn |
| `ParamBodyAngleY` | -10..10 | 0 | torso lift/slump |
| `ParamBodyAngleZ` | -10..10 | 0 | torso roll |
| `ParamEyeLOpen` | 0..1 | 1 | left blink |
| `ParamEyeROpen` | 0..1 | 1 | right blink |
| `ParamEyeBallX` | -1..1 | 0 | eye tracking horizontal |
| `ParamEyeBallY` | -1..1 | 0 | eye tracking vertical |
| `ParamBrowLY` | -1..1 | 0 | left brow emotion |
| `ParamBrowRY` | -1..1 | 0 | right brow emotion |
| `ParamBrowLAngle` | -1..1 | 0 | left brow angle |
| `ParamBrowRAngle` | -1..1 | 0 | right brow angle |
| `ParamMouthOpenY` | 0..1 | 0 | speech/open mouth |
| `ParamMouthForm` | -1..1 | 0 | sad to smile |
| `ParamBreath` | 0..1 | 0 | breathing loop |

Project-specific parameters:

| Parameter | Range | Default | Purpose |
| --- | ---: | ---: | --- |
| `ParamArmL` | -1..1 | 0 | left arm pose blend |
| `ParamArmR` | -1..1 | 0 | right arm pose blend |
| `ParamHandL` | 0..1 | 0 | left hand open/gesture |
| `ParamHandR` | 0..1 | 0 | right hand open/gesture |
| `ParamNotebookOpen` | 0..1 | 0 | notebook page open |
| `ParamNotebookX` | -1..1 | 0 | notebook horizontal orbit |
| `ParamNotebookY` | -1..1 | 0 | notebook vertical orbit |
| `ParamDatabaseCharm` | -1..1 | 0 | charm swing / spin |
| `ParamStatusLight` | 0..1 | 0.25 | status glow strength |
| `ParamStatusMode` | 0..6 | 0 | neutral, chat, memory, privacy, task, error, offline |
| `ParamMemoryCards` | 0..1 | 0 | reveal memory cards |
| `ParamWikiCards` | 0..1 | 0 | reveal wiki cards |
| `ParamTaskNote` | 0..1 | 0 | reveal task note |
| `ParamPrivacyShield` | 0..1 | 0 | reveal privacy shield |
| `ParamSleep` | 0..1 | 0 | sleepy/offline posture |

## Deformer Plan

Recommended deformer structure:

```text
RootWarp
  BodyXYZWarp
    TorsoWarp
    ArmLWarp
    ArmRWarp
    PropOrbitWarp
  HeadXYZWarp
    FaceAngleWarp
    EyeLWarp
    EyeRWarp
    BrowLWarp
    BrowRWarp
    MouthWarp
    HairFrontPhysicsWarp
    HairBackPhysicsWarp
```

Physics targets:

- `hair_ahoge`
- `hair_front_l1`
- `hair_front_r1`
- `hair_tail_l`
- `hair_tail_r`
- `jacket_collar_l`
- `jacket_collar_r`
- `chest_status_ribbon_base`
- `notebook_base`
- `database_charm_base`

Physics should be subtle. The pet window is small; excessive secondary motion
will read as jitter.

## Expressions

Every expression below must be exported as `expressions/<name>.exp3.json`:

| Expression | Main parameter differences |
| --- | --- |
| `exp_idle_soft` | neutral smile, relaxed brows |
| `exp_listen_mic` | attentive eyes, slight mouth close, status chat mode |
| `exp_think_focus` | eyes focused upward, brows lowered, notebook visible |
| `exp_talk_warm` | warmer mouth form, lip-sync ready |
| `exp_memory_scan` | eyes side scan, database charm active |
| `exp_memory_found` | bright eyes, memory card visible |
| `exp_memory_missing` | small apologetic mouth, brows soft down |
| `exp_confirm_careful` | careful brows, task/confirm card visible |
| `exp_privacy_guard` | serious brows, privacy shield visible |
| `exp_wiki_sort` | notebook and wiki cards visible |
| `exp_task_note` | task note visible, focused eyes |
| `exp_task_done` | smile eyes, small celebration pose |
| `exp_continuity_soft` | gentle smile, memory card half visible |
| `exp_emotion_comfort` | soft eyes, mouth form warm |
| `exp_offline_sleepy` | half-lidded eyes, sleep parameter active |
| `exp_error_alert` | alert brows, status error mode |
| `exp_diagnosed_ok` | relieved expression, status neutral-to-ok glow |
| `exp_sleep_quiet` | closed eyes, low glow, quiet posture |

## Motion Groups

Use these exact group names and file names in `agent_pet_companion.model3.json`.
The app currently maps project actions by group and index, so order matters.

```text
Idle/
  00_idle_breathe.motion3.json
  01_idle_look_around.motion3.json
  02_idle_notebook_float.motion3.json
  03_idle_sleep_quiet.motion3.json
Chat/
  00_chat_listen.motion3.json
  01_chat_think.motion3.json
  02_chat_talk.motion3.json
  03_chat_done.motion3.json
Memory/
  00_memory_search.motion3.json
  01_memory_found.motion3.json
  02_memory_not_found.motion3.json
  03_memory_save.motion3.json
  04_memory_confirm.motion3.json
  05_memory_privacy_guard.motion3.json
  06_memory_revert.motion3.json
Wiki/
  00_wiki_organize.motion3.json
  01_wiki_check.motion3.json
  02_wiki_archive.motion3.json
Task/
  00_task_create.motion3.json
  01_task_reminder.motion3.json
  02_task_complete.motion3.json
Continuity/
  00_continuity_remember.motion3.json
  01_emotion_comfort.motion3.json
System/
  00_system_connecting.motion3.json
  01_system_offline.motion3.json
  02_system_error.motion3.json
  03_system_diagnosed.motion3.json
Reaction/
  00_tts_speaking.motion3.json
  01_celebrate_small.motion3.json
```

Motion timing:

- Idle loops: 6-12 seconds, loop enabled.
- Listening/thinking/searching loops: 2-4 seconds, loop enabled.
- Talk/TTS: 1-2 seconds, loop enabled while speech is active.
- Confirm/privacy/error: 1.5-3 seconds, loop enabled but low motion.
- Completion/celebration: 1-1.6 seconds, non-loop.
- Offline/sleep: 6-10 seconds, loop enabled, low glow and small breathing.

## Project Action Fit

The action profile already maps project events to expression and motion indexes:

- Chat: listen, think, talk, done.
- Memory: search, found, not found, diary save, long-term save, confirmation,
  privacy guard, revert.
- Wiki: organize, check, archive.
- Task: create, reminder, complete.
- Continuity: unresolved topic, emotional comfort.
- System: connecting, offline, error, diagnosed.
- Reaction: TTS speaking, small celebration.

Do not collapse these into one idle animation. The model should visibly respond
to app state changes even in the compact pet window.

## Runtime Export Manifest Template

The exported `agent_pet_companion.model3.json` should follow this shape:

```json
{
  "Version": 3,
  "FileReferences": {
    "Moc": "agent_pet_companion.moc3",
    "Textures": [
      "textures/texture_00.png"
    ],
    "Physics": "agent_pet_companion.physics3.json",
    "DisplayInfo": "agent_pet_companion.cdi3.json",
    "Expressions": [
      { "Name": "exp_idle_soft", "File": "expressions/exp_idle_soft.exp3.json" }
    ],
    "Motions": {
      "Idle": [
        { "File": "motions/Idle/00_idle_breathe.motion3.json" }
      ]
    }
  },
  "Groups": [
    { "Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"] },
    { "Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"] }
  ],
  "HitAreas": [
    { "Id": "HitAreaHead", "Name": "Head" },
    { "Id": "HitAreaBody", "Name": "Body" },
    { "Id": "HitAreaNotebook", "Name": "Notebook" }
  ]
}
```

The real export should include all expressions and all motion files listed
above, not only the single sample entry.

## Acceptance Checklist

1. Source art exists as layered PSD or Cubism `.cmo3`.
2. Cubism Editor can open the project without missing layers.
3. All core parameters move correctly.
4. Eye blink, lip sync, breath, and physics are enabled.
5. All 18 expressions are exported.
6. All 28 motion files are exported in the exact group/index order.
7. `agent_pet_companion.model3.json` references real files only.
8. `npm run live2d:check:public -- --model live2d/agent_pet_companion/agent_pet_companion.model3.json` passes.
9. `models.json` removes `previewOnly` only after the above validation passes.
10. `#pet` reaches `live2d-render-mounted`, not `live2d-render-preview`.
