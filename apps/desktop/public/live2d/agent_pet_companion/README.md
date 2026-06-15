# Agent Pet Companion Live2D Character Pack

This folder is a design and integration specification for a new project-specific Live2D character.
It is registered as a `previewOnly` static character preview. It is not a runnable Cubism model yet
because no `.moc3`, texture atlas, physics, or exported `.model3.json` has been produced.

Keep this folder in `public/live2d/models.json` as `previewOnly: true` until a real Cubism export
exists with:

- `agent_pet_companion.model3.json`
- `.moc3`
- texture files
- expression `.exp3.json` files
- motion `.motion3.json` files
- optional physics/display info files

After those files exist and pass validation, remove `previewOnly` so the Cubism renderer can mount
the dynamic model.

The files here are intended for the model artist/rigger and for frontend integration planning:

- `character-design.json`: visual identity, rigging requirements, expression list, motion list.
- `agent_pet_companion.actions.json`: project event to expression/motion mapping for the future export.
- `CUBISM_MODEL_BLUEPRINT.md`: full PSD layer, Cubism part, parameter, expression, motion, and export blueprint.
- `cubism-production-spec.json`: machine-readable production contract for validation and handoff.
- `concept-reference.png`: visual character sheet reference for the model artist. This is not a runtime asset.
- `source/painted_v2/`: preferred high-quality Photoshop/Cubism source-art package extracted from
  the concept sheet. Start with `assemble-agent-pet-companion-painted-v2.jsx`.

Compatibility notes:

- The action profile follows the same `actions` shape supported by
  `src/services/live2dActions.ts`.
- Motion references use Cubism model3 motion groups and indexes.
- Expression names should be exported exactly as listed in `character-design.json`.
- This folder is accepted as a real dynamic model only after Cubism Editor exports
  the `.moc3`, `.model3.json`, textures, expressions, motions, physics, and display info.
