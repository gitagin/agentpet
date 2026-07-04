#target photoshop
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
  var layers = [
  {
    "name": "\u53c2\u8003\u539f\u56fe_\u4e0d\u5bfc\u5165",
    "group": "00_reference",
    "file": "layers/001_reference_original_do_not_import.png",
    "visibleDefault": false
  },
  {
    "name": "\u540e\u53d1_\u5b8c\u6574\u5e95\u8272\u8865\u5168",
    "group": "10_back_hair",
    "file": "layers/010_hair_back_under_fill.png",
    "visibleDefault": false
  },
  {
    "name": "\u540e\u53d1_\u53ef\u89c1\u539f\u753b\u7eb9\u7406",
    "group": "10_back_hair",
    "file": "layers/011_hair_back_visible_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u540e\u53d1\u5c3e_\u5e95\u8272",
    "group": "10_back_hair",
    "file": "layers/012_hair_tail_l_base.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u540e\u53d1\u5c3e_\u539f\u753b\u7eb9\u7406",
    "group": "10_back_hair",
    "file": "layers/013_hair_tail_l_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u540e\u53d1\u5c3e_\u5e95\u8272",
    "group": "10_back_hair",
    "file": "layers/014_hair_tail_r_base.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u540e\u53d1\u5c3e_\u539f\u753b\u7eb9\u7406",
    "group": "10_back_hair",
    "file": "layers/015_hair_tail_r_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u7c89\u8272\u53d1\u5c3e_\u72ec\u7acb",
    "group": "10_back_hair",
    "file": "layers/016_hair_tail_pink_inner_l.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u7c89\u8272\u53d1\u5c3e_\u72ec\u7acb",
    "group": "10_back_hair",
    "file": "layers/017_hair_tail_pink_inner_r.png",
    "visibleDefault": true
  },
  {
    "name": "\u8eab\u4f53\u540e\u4fa7\u5927\u9634\u5f71",
    "group": "20_body",
    "file": "layers/020_body_shadow_back.png",
    "visibleDefault": false
  },
  {
    "name": "\u8eaf\u5e72\u5185\u886b_\u5b8c\u6574\u5e95\u8272",
    "group": "20_body",
    "file": "layers/021_torso_inner_base_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u8eaf\u5e72\u5185\u886b_\u539f\u753b\u7eb9\u7406",
    "group": "20_body",
    "file": "layers/022_torso_inner_visible_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u5916\u5957\u540e\u7247",
    "group": "20_body",
    "file": "layers/023_jacket_l_back_panel.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u5916\u5957_\u539f\u753b\u7eb9\u7406",
    "group": "20_body",
    "file": "layers/024_jacket_l_visible_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u5916\u5957\u540e\u7247",
    "group": "20_body",
    "file": "layers/025_jacket_r_back_panel.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u5916\u5957_\u539f\u753b\u7eb9\u7406",
    "group": "20_body",
    "file": "layers/026_jacket_r_visible_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u8896\u53e3\u4e0e\u7ed1\u5e26\u7c89\u8272\u7ec6\u8282",
    "group": "20_body",
    "file": "layers/027_cuff_and_strap_pink_accents.png",
    "visibleDefault": true
  },
  {
    "name": "\u624b\u81c2\u4e0b\u65b9\u8863\u670d\u8865\u5168",
    "group": "20_body",
    "file": "layers/028_torso_under_arms_repaint.png",
    "visibleDefault": false
  },
  {
    "name": "\u8116\u5b50_\u5b8c\u6574\u5e95\u8272",
    "group": "30_head_face",
    "file": "layers/035_neck_base_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u8116\u5b50_\u539f\u753b\u7eb9\u7406",
    "group": "30_head_face",
    "file": "layers/036_neck_visible_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u8138\u90e8_\u5b8c\u6574\u7eaf\u8272\u5e95",
    "group": "30_head_face",
    "file": "layers/040_face_base_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u8138\u90e8_\u539f\u753b\u80a4\u8272\u7eb9\u7406",
    "group": "30_head_face",
    "file": "layers/041_face_visible_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u8138\u90e8\u5916\u8f6e\u5ed3\u9634\u5f71",
    "group": "30_head_face",
    "file": "layers/042_face_contour_shadow.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u816e\u7ea2",
    "group": "30_head_face",
    "file": "layers/043_cheek_blush_l.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u816e\u7ea2",
    "group": "30_head_face",
    "file": "layers/044_cheek_blush_r.png",
    "visibleDefault": false
  },
  {
    "name": "\u9f3b\u5c16\u9ad8\u5149",
    "group": "30_head_face",
    "file": "layers/045_nose_highlight.png",
    "visibleDefault": false
  },
  {
    "name": "\u5934\u53d1\u6295\u5728\u8138\u4e0a\u7684\u9634\u5f71",
    "group": "30_head_face",
    "file": "layers/046_hair_cast_shadow_on_face.png",
    "visibleDefault": false
  },
  {
    "name": "\u624b\u6295\u5728\u8138\u4e0a\u7684\u9634\u5f71",
    "group": "30_head_face",
    "file": "layers/047_hand_cast_shadow_on_face.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u732b\u8033_\u5916\u8f6e\u5ed3",
    "group": "35_ears",
    "file": "layers/050_ear_l_outer_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u732b\u8033_\u539f\u753b\u7eb9\u7406",
    "group": "35_ears",
    "file": "layers/051_ear_l_outer_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u732b\u8033_\u5185\u6bdb",
    "group": "35_ears",
    "file": "layers/052_ear_l_inner_fur.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u732b\u8033_\u5185\u6bdb\u7eb9\u7406",
    "group": "35_ears",
    "file": "layers/053_ear_l_inner_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u732b\u8033_\u5916\u8f6e\u5ed3",
    "group": "35_ears",
    "file": "layers/054_ear_r_outer_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u732b\u8033_\u539f\u753b\u7eb9\u7406",
    "group": "35_ears",
    "file": "layers/055_ear_r_outer_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u732b\u8033_\u5185\u6bdb",
    "group": "35_ears",
    "file": "layers/056_ear_r_inner_fur.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u732b\u8033_\u5185\u6bdb\u7eb9\u7406",
    "group": "35_ears",
    "file": "layers/057_ear_r_inner_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u773c\u767d_\u5b8c\u6574",
    "group": "40_eyes",
    "file": "layers/060_eye_l_white_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u773c\u767d_\u539f\u753b\u7eb9\u7406",
    "group": "40_eyes",
    "file": "layers/061_eye_l_white_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u8679\u819c_\u5e95\u8272",
    "group": "40_eyes",
    "file": "layers/062_eye_l_iris_base.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u8679\u819c_\u539f\u753b\u7eb9\u7406",
    "group": "40_eyes",
    "file": "layers/063_eye_l_iris_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u77b3\u5b54",
    "group": "40_eyes",
    "file": "layers/064_eye_l_pupil.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u773c\u775b\u4e3b\u9ad8\u5149",
    "group": "40_eyes",
    "file": "layers/065_eye_l_highlight_main.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u773c\u775b\u5c0f\u9ad8\u5149",
    "group": "40_eyes",
    "file": "layers/066_eye_l_highlight_small.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u4e0a\u776b\u6bdb\u4e3b\u679d",
    "group": "40_eyes",
    "file": "layers/067_eye_l_upper_lash_base.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u4e0a\u776b\u6bdb\u679d\u67481",
    "group": "40_eyes",
    "file": "layers/068_eye_l_upper_lash_branch_1.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u4e0b\u776b\u6bdb",
    "group": "40_eyes",
    "file": "layers/069_eye_l_lower_lash.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u773c\u7751\u9634\u5f71",
    "group": "40_eyes",
    "file": "layers/070_eye_l_lid_shadow.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u95ed\u773c\u80a4\u8272\u906e\u7f69",
    "group": "40_eyes",
    "file": "layers/071_eye_l_blink_cover.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u95ed\u773c\u7ebf",
    "group": "40_eyes",
    "file": "layers/072_eye_l_closed_lid_line.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u773c\u767d_\u5b8c\u6574",
    "group": "40_eyes",
    "file": "layers/080_eye_r_white_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u773c\u767d_\u539f\u753b\u7eb9\u7406",
    "group": "40_eyes",
    "file": "layers/081_eye_r_white_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u8679\u819c_\u5e95\u8272",
    "group": "40_eyes",
    "file": "layers/082_eye_r_iris_base.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u8679\u819c_\u539f\u753b\u7eb9\u7406",
    "group": "40_eyes",
    "file": "layers/083_eye_r_iris_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u77b3\u5b54",
    "group": "40_eyes",
    "file": "layers/084_eye_r_pupil.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u773c\u775b\u4e3b\u9ad8\u5149",
    "group": "40_eyes",
    "file": "layers/085_eye_r_highlight_main.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u773c\u775b\u5c0f\u9ad8\u5149",
    "group": "40_eyes",
    "file": "layers/086_eye_r_highlight_small.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u4e0a\u776b\u6bdb\u4e3b\u679d",
    "group": "40_eyes",
    "file": "layers/087_eye_r_upper_lash_base.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u4e0a\u776b\u6bdb\u679d\u67481",
    "group": "40_eyes",
    "file": "layers/088_eye_r_upper_lash_branch_1.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u4e0b\u776b\u6bdb",
    "group": "40_eyes",
    "file": "layers/089_eye_r_lower_lash.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u773c\u7751\u9634\u5f71",
    "group": "40_eyes",
    "file": "layers/090_eye_r_lid_shadow.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u95ed\u773c\u80a4\u8272\u906e\u7f69",
    "group": "40_eyes",
    "file": "layers/091_eye_r_blink_cover.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u95ed\u773c\u7ebf",
    "group": "40_eyes",
    "file": "layers/092_eye_r_closed_lid_line.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u7709\u6bdb",
    "group": "45_brows",
    "file": "layers/100_brow_l.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u7709\u6bdb",
    "group": "45_brows",
    "file": "layers/101_brow_r.png",
    "visibleDefault": true
  },
  {
    "name": "\u53e3\u8154_A\u5f62",
    "group": "50_mouth",
    "file": "layers/110_mouth_inner_a.png",
    "visibleDefault": false
  },
  {
    "name": "\u53e3\u8154_O\u5f62",
    "group": "50_mouth",
    "file": "layers/111_mouth_inner_o.png",
    "visibleDefault": false
  },
  {
    "name": "\u820c\u5934",
    "group": "50_mouth",
    "file": "layers/112_mouth_tongue.png",
    "visibleDefault": false
  },
  {
    "name": "\u7259\u9f7f",
    "group": "50_mouth",
    "file": "layers/113_mouth_teeth.png",
    "visibleDefault": false
  },
  {
    "name": "\u95ed\u53e3\u5fae\u7b11\u7ebf_\u539f\u753b",
    "group": "50_mouth",
    "file": "layers/114_mouth_closed_smile_source.png",
    "visibleDefault": true
  },
  {
    "name": "\u4e0a\u53e3\u7247",
    "group": "50_mouth",
    "file": "layers/115_mouth_upper_lip.png",
    "visibleDefault": false
  },
  {
    "name": "\u4e0b\u5507\u9634\u5f71",
    "group": "50_mouth",
    "file": "layers/116_mouth_lower_lip_shadow.png",
    "visibleDefault": false
  },
  {
    "name": "\u8ba4\u771f\u8868\u60c5\u5e73\u53e3\u7ebf",
    "group": "50_mouth",
    "file": "layers/117_mouth_serious_flat_line.png",
    "visibleDefault": false
  },
  {
    "name": "\u4e2d\u5218\u6d77_\u5b8c\u6574\u5e95\u8272",
    "group": "60_front_hair",
    "file": "layers/120_bang_center_base_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u4e2d\u5218\u6d77_\u539f\u753b\u7eb9\u7406",
    "group": "60_front_hair",
    "file": "layers/121_bang_center_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u5218\u6d77_\u5b8c\u6574\u5e95\u8272",
    "group": "60_front_hair",
    "file": "layers/122_bang_l_base_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u5218\u6d77_\u539f\u753b\u7eb9\u7406",
    "group": "60_front_hair",
    "file": "layers/123_bang_l_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u5218\u6d77_\u5b8c\u6574\u5e95\u8272",
    "group": "60_front_hair",
    "file": "layers/124_bang_r_base_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u5218\u6d77_\u539f\u753b\u7eb9\u7406",
    "group": "60_front_hair",
    "file": "layers/125_bang_r_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u773c\u524d\u7ec6\u53d1\u4e1d",
    "group": "60_front_hair",
    "file": "layers/126_hair_over_eye_fine_strands.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u4fa7\u53d1_\u5b8c\u6574\u5e95\u8272",
    "group": "60_front_hair",
    "file": "layers/127_long_lock_l_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u4fa7\u53d1_\u539f\u753b\u7eb9\u7406",
    "group": "60_front_hair",
    "file": "layers/128_long_lock_l_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u4fa7\u53d1_\u5b8c\u6574\u5e95\u8272",
    "group": "60_front_hair",
    "file": "layers/129_long_lock_r_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u4fa7\u53d1_\u539f\u753b\u7eb9\u7406",
    "group": "60_front_hair",
    "file": "layers/130_long_lock_r_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u524d\u53d1\u9ad8\u5149\u72ec\u7acb",
    "group": "60_front_hair",
    "file": "layers/131_front_hair_highlight_strokes.png",
    "visibleDefault": true
  },
  {
    "name": "\u524d\u53d1\u7c89\u8272\u6311\u67d3",
    "group": "60_front_hair",
    "file": "layers/132_front_hair_pink_streaks.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u624b\u81c2\u8896\u5b50_\u5b8c\u6574",
    "group": "70_arms_hands",
    "file": "layers/140_arm_l_sleeve_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u5de6\u5c4f\u624b\u81c2\u8896\u5b50_\u539f\u753b\u7eb9\u7406",
    "group": "70_arms_hands",
    "file": "layers/141_arm_l_sleeve_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u6258\u8138\u624b_\u5b8c\u6574\u80a4\u8272",
    "group": "70_arms_hands",
    "file": "layers/142_hand_cheek_base_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u6258\u8138\u624b_\u539f\u753b\u7eb9\u7406",
    "group": "70_arms_hands",
    "file": "layers/143_hand_cheek_visible_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u6258\u8138\u624b_\u624b\u6307\u7ebf",
    "group": "70_arms_hands",
    "file": "layers/144_hand_cheek_finger_lines.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u624b\u81c2\u8896\u5b50_\u5b8c\u6574",
    "group": "70_arms_hands",
    "file": "layers/145_arm_r_sleeve_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u5c4f\u624b\u81c2\u8896\u5b50_\u539f\u753b\u7eb9\u7406",
    "group": "70_arms_hands",
    "file": "layers/146_arm_r_sleeve_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u524d\u666f\u624b_\u5b8c\u6574\u80a4\u8272",
    "group": "70_arms_hands",
    "file": "layers/147_front_hand_base_complete.png",
    "visibleDefault": false
  },
  {
    "name": "\u524d\u666f\u624b_\u539f\u753b\u7eb9\u7406",
    "group": "70_arms_hands",
    "file": "layers/148_front_hand_visible_texture.png",
    "visibleDefault": true
  },
  {
    "name": "\u524d\u666f\u624b_\u624b\u6307\u7ebf",
    "group": "70_arms_hands",
    "file": "layers/149_front_hand_finger_lines.png",
    "visibleDefault": true
  },
  {
    "name": "\u6258\u816e\u624b\u653e\u4e0b_\u4e0a\u81c2\u8896\u5b50\u8865\u753b",
    "group": "70_arms_hands",
    "file": "layers/150_support_hand_down_upper_sleeve_repaint.png",
    "visibleDefault": false
  },
  {
    "name": "\u6258\u816e\u624b\u653e\u4e0b_\u524d\u81c2\u8896\u5b50\u8865\u753b",
    "group": "70_arms_hands",
    "file": "layers/151_support_hand_down_forearm_sleeve_repaint.png",
    "visibleDefault": false
  },
  {
    "name": "\u6258\u816e\u624b\u653e\u4e0b_\u8896\u53e3\u8865\u753b",
    "group": "70_arms_hands",
    "file": "layers/152_support_hand_down_cuff_repaint.png",
    "visibleDefault": false
  },
  {
    "name": "\u6258\u816e\u624b\u653e\u4e0b_\u624b\u638c\u8865\u753b",
    "group": "70_arms_hands",
    "file": "layers/153_support_hand_down_hand_base_repaint.png",
    "visibleDefault": false
  },
  {
    "name": "\u6258\u816e\u624b\u653e\u4e0b_\u624b\u6307\u7ebf\u8865\u753b",
    "group": "70_arms_hands",
    "file": "layers/154_support_hand_down_finger_lines_repaint.png",
    "visibleDefault": false
  },
  {
    "name": "\u6258\u816e\u624b\u79fb\u5f00_\u8138\u988a\u8865\u5168\u68c0\u67e5\u5c42",
    "group": "70_arms_hands",
    "file": "layers/155_cheek_after_hand_removed_cleanup.png",
    "visibleDefault": false
  },
  {
    "name": "\u53d1\u5939_\u4e3b\u4f53",
    "group": "80_accessories",
    "file": "layers/160_hair_clip_base.png",
    "visibleDefault": true
  },
  {
    "name": "\u53d1\u5939_\u9ad8\u5149",
    "group": "80_accessories",
    "file": "layers/161_hair_clip_highlight.png",
    "visibleDefault": true
  },
  {
    "name": "\u5de6\u5c4f\u8033\u9970",
    "group": "80_accessories",
    "file": "layers/162_ear_charm_l.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u5c4f\u8033\u9970\u94fe\u6761",
    "group": "80_accessories",
    "file": "layers/163_earring_chain_r.png",
    "visibleDefault": true
  },
  {
    "name": "\u9879\u94fe\u94fe\u6761",
    "group": "80_accessories",
    "file": "layers/164_necklace_chain.png",
    "visibleDefault": true
  },
  {
    "name": "\u9879\u94fe\u84dd\u8272\u540a\u5760",
    "group": "80_accessories",
    "file": "layers/165_necklace_cyan_pendant.png",
    "visibleDefault": true
  },
  {
    "name": "\u9879\u94fe\u540a\u5760\u53d1\u5149",
    "group": "80_accessories",
    "file": "layers/166_necklace_pendant_glow.png",
    "visibleDefault": false
  },
  {
    "name": "\u8896\u7ae0\u8bbe\u5907_\u4e3b\u4f53",
    "group": "80_accessories",
    "file": "layers/167_sleeve_device_body.png",
    "visibleDefault": true
  },
  {
    "name": "\u8896\u7ae0\u8bbe\u5907_\u5c4f\u5e55",
    "group": "80_accessories",
    "file": "layers/168_sleeve_device_screen.png",
    "visibleDefault": true
  },
  {
    "name": "\u8896\u7ae0\u8bbe\u5907_\u53d1\u5149",
    "group": "80_accessories",
    "file": "layers/169_sleeve_device_glow.png",
    "visibleDefault": false
  },
  {
    "name": "\u53f3\u4fa7\u6302\u4ef6_\u4e3b\u4f53",
    "group": "80_accessories",
    "file": "layers/170_hanging_keychain_body.png",
    "visibleDefault": true
  },
  {
    "name": "\u53f3\u4fa7\u6302\u4ef6_\u53d1\u5149",
    "group": "80_accessories",
    "file": "layers/171_hanging_keychain_glow.png",
    "visibleDefault": false
  },
  {
    "name": "\u84dd\u8272\u72b6\u6001\u5149\u50cf\u7d20_\u8f85\u52a9",
    "group": "80_accessories",
    "file": "layers/172_all_cyan_status_pixels_helper.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u6124\u6012_\u5de6\u5c4f\u538b\u7709",
    "group": "90_expressions",
    "file": "layers/175_expr_angry_brow_l_down.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u6124\u6012_\u53f3\u5c4f\u538b\u7709",
    "group": "90_expressions",
    "file": "layers/176_expr_angry_brow_r_down.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u6124\u6012_\u7d27\u95ed\u53e3",
    "group": "90_expressions",
    "file": "layers/177_expr_angry_mouth_tight.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u6124\u6012_\u9762\u90e8\u6697\u5f71",
    "group": "90_expressions",
    "file": "layers/178_expr_angry_shadow.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u9ad8\u5174_\u5de6\u5c4f\u7b11\u773c",
    "group": "90_expressions",
    "file": "layers/179_expr_happy_eye_l_arc.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u9ad8\u5174_\u53f3\u5c4f\u7b11\u773c",
    "group": "90_expressions",
    "file": "layers/180_expr_happy_eye_r_arc.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u9ad8\u5174_\u5f00\u53e3\u7b11",
    "group": "90_expressions",
    "file": "layers/181_expr_happy_mouth_smile_open.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u9ad8\u5174_\u816e\u7ea2\u589e\u5f3a",
    "group": "90_expressions",
    "file": "layers/182_expr_happy_blush_boost.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u7591\u60d1_\u5de6\u5c4f\u6311\u7709",
    "group": "90_expressions",
    "file": "layers/183_expr_confused_brow_l_raise.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u7591\u60d1_\u53f3\u5c4f\u5e73\u7709",
    "group": "90_expressions",
    "file": "layers/184_expr_confused_brow_r_flat.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u7591\u60d1_\u5c0f\u53e3",
    "group": "90_expressions",
    "file": "layers/185_expr_confused_mouth_small.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u7591\u60d1_\u95ee\u53f7\u7b26\u53f7",
    "group": "90_expressions",
    "file": "layers/186_expr_confused_question_mark.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u60b2\u4f24_\u5de6\u5c4f\u516b\u5b57\u7709",
    "group": "90_expressions",
    "file": "layers/187_expr_sad_brow_l_soft.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u60b2\u4f24_\u53f3\u5c4f\u516b\u5b57\u7709",
    "group": "90_expressions",
    "file": "layers/188_expr_sad_brow_r_soft.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u60b2\u4f24_\u4e0b\u5f2f\u53e3",
    "group": "90_expressions",
    "file": "layers/189_expr_sad_mouth_down.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u60b2\u4f24_\u6cea\u6ef4",
    "group": "90_expressions",
    "file": "layers/190_expr_sad_tears.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u6050\u60e7_\u5de6\u5c4f\u77aa\u773c\u8865\u767d",
    "group": "90_expressions",
    "file": "layers/191_expr_fear_eye_l_wide.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u6050\u60e7_\u53f3\u5c4f\u77aa\u773c\u8865\u767d",
    "group": "90_expressions",
    "file": "layers/192_expr_fear_eye_r_wide.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u6050\u60e7_\u5c0f\u5f00\u53e3",
    "group": "90_expressions",
    "file": "layers/193_expr_fear_mouth_small_open.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u6050\u60e7_\u8138\u90e8\u51b7\u9634\u5f71",
    "group": "90_expressions",
    "file": "layers/194_expr_fear_face_shadow.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u60ca\u8bb6_\u5de6\u5c4f\u5706\u773c",
    "group": "90_expressions",
    "file": "layers/195_expr_surprise_eye_l_round.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u60ca\u8bb6_\u53f3\u5c4f\u5706\u773c",
    "group": "90_expressions",
    "file": "layers/196_expr_surprise_eye_r_round.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u60ca\u8bb6_O\u5f62\u53e3",
    "group": "90_expressions",
    "file": "layers/197_expr_surprise_mouth_o.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u60ca\u8bb6_\u773c\u9ad8\u5149\u589e\u5f3a",
    "group": "90_expressions",
    "file": "layers/198_expr_surprise_highlight_pop.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u538c\u6076_\u5de6\u5c4f\u76b1\u7709",
    "group": "90_expressions",
    "file": "layers/199_expr_disgust_brow_l.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u538c\u6076_\u53f3\u5c4f\u76b1\u7709",
    "group": "90_expressions",
    "file": "layers/200_expr_disgust_brow_r.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u538c\u6076_\u6b6a\u5634",
    "group": "90_expressions",
    "file": "layers/201_expr_disgust_mouth_skew.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u538c\u6076_\u9f3b\u6881\u76b1\u8936",
    "group": "90_expressions",
    "file": "layers/202_expr_disgust_nose_wrinkle.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u8f7b\u8511_\u5de6\u5c4f\u8f7b\u6311\u7709",
    "group": "90_expressions",
    "file": "layers/203_expr_contempt_brow_l.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u8f7b\u8511_\u53f3\u5c4f\u534a\u772f\u773c",
    "group": "90_expressions",
    "file": "layers/204_expr_contempt_eye_r_half_lid.png",
    "visibleDefault": false
  },
  {
    "name": "\u8868\u60c5_\u8f7b\u8511_\u5355\u8fb9\u7b11",
    "group": "90_expressions",
    "file": "layers/205_expr_contempt_smirk.png",
    "visibleDefault": false
  },
  {
    "name": "\u672a\u5206\u914d\u53ef\u89c1\u50cf\u7d20_\u68c0\u67e5\u7528",
    "group": "99_review",
    "file": "layers/230_unassigned_visible_recovery_review.png",
    "visibleDefault": true
  }
];
  var expectedWidth = 1484;
  var expectedHeight = 1060;

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
