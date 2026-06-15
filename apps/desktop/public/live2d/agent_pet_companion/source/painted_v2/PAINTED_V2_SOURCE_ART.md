# Painted V2 Source Art

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
