import type { CSSProperties } from "react";
import petHitboxConfig from "../../../pet-hitbox.json";

const petShortcutButtonSize = 34;
const petShortcutButtonGap = 7;
const petShortcutButtonCount = 5;
const petShortcutColumnCount = 1;

export const petHitboxStyle = {
  "--pet-model-hit-width": `${petHitboxConfig.hitboxes.model.width}px`,
  "--pet-model-hit-height": `${petHitboxConfig.hitboxes.model.height}px`,
  "--pet-model-hit-bottom": `${petHitboxConfig.hitboxes.model.bottom}px`,
  "--pet-input-dock-hit-width": `${petHitboxConfig.hitboxes.inputDock.width}px`,
  "--pet-input-dock-hit-height": `${petHitboxConfig.hitboxes.inputDock.height}px`,
  "--pet-input-dock-hit-bottom": `${petHitboxConfig.hitboxes.inputDock.bottom}px`,
  "--pet-chat-bubble-hit-width": `${petHitboxConfig.hitboxes.chatBubble.width}px`,
  "--pet-chat-bubble-hit-height": `${petHitboxConfig.hitboxes.chatBubble.height}px`,
  "--pet-chat-bubble-hit-bottom": `${petHitboxConfig.hitboxes.chatBubble.bottom}px`,
  "--pet-shortcut-bar-width": `${petHitboxConfig.hitboxes.shortcutBar.width}px`,
  "--pet-shortcut-bar-height": `${petHitboxConfig.hitboxes.shortcutBar.height}px`,
  "--pet-shortcut-bar-right": `${petHitboxConfig.hitboxes.shortcutBar.right}px`,
  "--pet-shortcut-bar-bottom": `${petHitboxConfig.hitboxes.shortcutBar.bottom}px`,
} as CSSProperties;

export const petShortcutButtonStyles = buildPetShortcutButtonStyles();

function buildPetShortcutButtonStyles(): CSSProperties[] {
  const modelCenter = {
    x: petHitboxConfig.window.width / 2,
    y:
      petHitboxConfig.window.height -
      petHitboxConfig.hitboxes.model.bottom -
      petHitboxConfig.hitboxes.model.height / 2,
  };
  const shortcutBarLeft =
    petHitboxConfig.window.width -
    petHitboxConfig.hitboxes.shortcutBar.right -
    petHitboxConfig.hitboxes.shortcutBar.width;
  const shortcutBarTop =
    petHitboxConfig.window.height -
    petHitboxConfig.hitboxes.shortcutBar.bottom -
    petHitboxConfig.hitboxes.shortcutBar.height;
  const rowCount = Math.ceil(petShortcutButtonCount / petShortcutColumnCount);
  const stackWidth =
    petShortcutColumnCount * petShortcutButtonSize +
    (petShortcutColumnCount - 1) * petShortcutButtonGap;
  const stackHeight =
    rowCount * petShortcutButtonSize +
    (rowCount - 1) * petShortcutButtonGap;
  const stackLeft = shortcutBarLeft + (petHitboxConfig.hitboxes.shortcutBar.width - stackWidth) / 2;
  const stackTop = shortcutBarTop + (petHitboxConfig.hitboxes.shortcutBar.height - stackHeight) / 2;

  return Array.from({ length: petShortcutButtonCount }, (_, index) => {
    const column = index % petShortcutColumnCount;
    const row = Math.floor(index / petShortcutColumnCount);
    const buttonCenter = {
      x: stackLeft + petShortcutButtonSize / 2 + column * (petShortcutButtonSize + petShortcutButtonGap),
      y: stackTop + petShortcutButtonSize / 2 + row * (petShortcutButtonSize + petShortcutButtonGap),
    };
    return {
      "--pet-shortcut-origin-x": `${Math.round(modelCenter.x - buttonCenter.x)}px`,
      "--pet-shortcut-origin-y": `${Math.round(modelCenter.y - buttonCenter.y)}px`,
    } as CSSProperties;
  });
}
