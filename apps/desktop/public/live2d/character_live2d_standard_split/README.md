# Live2D Standard Character Split

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

Layer count: 146
Visible layers: 48
Hidden helper layers: 98

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
