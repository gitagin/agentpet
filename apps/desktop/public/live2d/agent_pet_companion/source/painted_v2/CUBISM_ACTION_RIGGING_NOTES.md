# Painted V2 Cubism Action Rigging Notes

Use `agent_pet_companion_painted_v2_layered.psd` as the visual base after running
`assemble-agent-pet-companion-painted-v2.jsx` in Photoshop.

This file maps project actions to the painted v2 layers. It is a rigging guide,
not a runtime model.

## Default Setup

- Keep the character readable at small desktop-pet size.
- Hide `00_reference_do_not_export` before Cubism texture export.
- Split `painted_unassigned_details` into proper parts during cleanup, then delete
  or hide the original catch-all layer.
- Repaint hidden overlap behind hair, hands, jacket sleeves, and props before
  large motion rigging.

## Required Cleanup Layers

For best Cubism results, redraw or split these after Photoshop assembly:

```text
40_eyes
  eye_l_white
  eye_l_iris
  eye_l_highlight
  eye_l_upper_lid
  eye_l_lower_lid
  eye_r_white
  eye_r_iris
  eye_r_highlight
  eye_r_upper_lid
  eye_r_lower_lid

60_mouth
  mouth_line
  mouth_inner
  mouth_teeth
  mouth_tongue

80_arms
  arm_l_upper
  arm_l_lower
  hand_l_base
  hand_l_fingers
  arm_r_upper
  arm_r_lower
  hand_r_base
  hand_r_fingers
```

## Project Action Mapping

| Project action | Expression target | Motion idea | Painted v2 layers to emphasize |
| --- | --- | --- | --- |
| `idle` | `exp_idle_soft` | breathing, tiny hair sway, notebook hover | `hair_front_and_top`, `hair_sides_and_back`, `prop_floating_notebook`, `status_light` |
| `chat_listen` | `exp_listen_mic` | slight forward lean, attentive eyes | `eye_l`, `eye_r`, `status_light` |
| `chat_think` | `exp_think_focus` | eyes shift, notebook tilts, memory shards pulse | `prop_floating_notebook`, `prop_memory_shards`, `status_light` |
| `chat_talk` | `exp_talk_warm` | mouth open/close, small hand gesture | `mouth`, `hand_l`, `hand_r` |
| `memory_search` | `exp_memory_scan` | database charm glow and swing | `database_charm`, `status_light`, `prop_memory_shards` |
| `memory_found` | `exp_memory_found` | notebook pops forward, status light brightens | `prop_floating_notebook`, `status_light` |
| `memory_not_found` | `exp_memory_missing` | small head tilt, notebook lowers | `prop_floating_notebook`, `hair_front_and_top` |
| `memory_privacy_guard` | `exp_privacy_guard` | hand raises in stop pose, status light cyan shield state | `hand_r`, `arm_r_sleeve`, `status_light` |
| `wiki_organize` | `exp_wiki_sort` | notebook flips, shards arrange into pages | `prop_floating_notebook`, `prop_memory_shards` |
| `task_create` | `exp_task_note` | badge/card bounces once | `id_badge`, `status_light` |
| `task_complete` | `exp_task_done` | small celebration, charm bounce | `database_charm`, `prop_memory_shards` |
| `system_offline` | `exp_offline_sleepy` | eyes half close, status light dims | `eye_l`, `eye_r`, `status_light` |
| `system_error` | `exp_error_alert` | status light red pulse, body stiffens | `status_light`, `torso_inner` |

## Cubism Parameter Priorities

1. `ParamAngleX`, `ParamAngleY`, `ParamAngleZ` for head motion.
2. `ParamEyeLOpen`, `ParamEyeROpen`, `ParamEyeBallX`, `ParamEyeBallY`.
3. `ParamMouthOpenY`, `ParamMouthForm`.
4. `ParamBreath`, `ParamBodyAngleX`, `ParamBodyAngleY`, `ParamBodyAngleZ`.
5. Project props: `ParamNotebookOpen`, `ParamDatabaseCharm`, `ParamStatusLight`,
   `ParamMemoryCards`, `ParamPrivacyShield`.

## Export Reminder

After rigging in Live2D Cubism Editor, export real runtime files into:

```text
apps/desktop/public/live2d/agent_pet_companion/
```

The export is accepted only when this folder contains a real
`agent_pet_companion.moc3` and `agent_pet_companion.model3.json` with referenced
textures, expressions, motions, physics, and display info.
