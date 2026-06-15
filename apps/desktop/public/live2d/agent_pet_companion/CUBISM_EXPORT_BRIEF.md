# Agent Pet Companion Cubism Export Brief

This folder does not contain a real Cubism model yet. A runnable Live2D model must be exported from
Live2D Cubism Editor as binary/runtime assets; `.moc3` cannot be authored safely by hand.

Use `CUBISM_MODEL_BLUEPRINT.md` as the full production design. It defines the character direction,
PSD layer tree, Cubism parts, parameters, expressions, motion groups, and runtime acceptance checks.
Use `cubism-production-spec.json` as the machine-readable version of the same production contract.

## Required Inputs

- Preferred visual source: `source/painted_v2/`.
- Run `source/painted_v2/assemble-agent-pet-companion-painted-v2.jsx` in Photoshop to create
  `agent_pet_companion_painted_v2_layered.psd`.
- Use `source/painted_v2/expression_references/*.png` as expression and action references.
- Clean the assembled PSD into final Cubism-ready layers: separated face, eyes, brows, mouth,
  hair, body, arms, hands, notebook prop, database charm, and status ribbon layers.
- Live2D Cubism Editor project file (`.cmo3`) created from that layered art.
- Rigging for the parameters listed in `character-design.json`.
- Motion and expression export names matching `CUBISM_MODEL_BLUEPRINT.md`.

## Required Runtime Export

Export these files into this directory:

- `agent_pet_companion.model3.json`
- `agent_pet_companion.moc3`
- one or more texture files, usually under `textures/`
- expression files matching every expression name in `character-design.json`
- motion files matching every motion group and index in `character-design.json`
- optional `agent_pet_companion.physics3.json`
- optional `agent_pet_companion.cdi3.json`

Recommended structure:

```text
agent_pet_companion.model3.json
agent_pet_companion.moc3
textures/texture_00.png
expressions/exp_idle_soft.exp3.json
motions/Idle/00_idle_breathe.motion3.json
agent_pet_companion.physics3.json
agent_pet_companion.cdi3.json
```

## Runtime Contract

The app expects the model catalog entry to become:

```json
{
  "id": "agent_pet_companion",
  "label": "Archivist Companion",
  "directory": "/live2d/agent_pet_companion/",
  "model": "agent_pet_companion.model3.json",
  "icon": "preview.svg",
  "actions": "agent_pet_companion.actions.json"
}
```

After a real export exists, remove `previewOnly` and `design` from `public/live2d/models.json`.

## Validation

Run:

```powershell
Push-Location apps\desktop
npm run live2d:companion:check
npm run live2d:check:public -- --model live2d/agent_pet_companion/agent_pet_companion.model3.json
npm run typecheck
Pop-Location
```

The model is not accepted as a real dynamic model until the `live2d:check:public` command validates
the new `agent_pet_companion.model3.json` and all referenced `.moc3`, textures, expressions, and
motions.
