# Character Live2D Runtime Action Pack

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
