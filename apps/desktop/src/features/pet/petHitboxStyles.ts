import type { CSSProperties } from "react";
import petHitboxConfig from "../../../pet-hitbox.json";

// pet-hitbox.json 的 layout.anchors 是主进程命中计算（electron/windows.js）与
// 渲染端样式共同遵守的布局锚定声明。这里的 CSS 变量/样式按下面的锚点书写；
// 若 json 改了锚点而 CSS 没跟上，这个断言会在模块加载时立刻炸出来，
// 避免"主进程按新锚点算命中、渲染端还按旧位置画"的静默错位。
const rendererImplementedAnchors: Record<string, { horizontal: string; vertical: string }> = {
  model: { horizontal: "center", vertical: "bottom" },
  inputDock: { horizontal: "center", vertical: "bottom" },
  chatBubble: { horizontal: "center", vertical: "bottom" },
  shortcutBar: { horizontal: "right", vertical: "bottom" },
};

for (const [name, expected] of Object.entries(rendererImplementedAnchors)) {
  const anchor = petHitboxConfig.layout.anchors[name as keyof typeof petHitboxConfig.layout.anchors];
  if (anchor?.horizontal !== expected.horizontal || anchor?.vertical !== expected.vertical) {
    throw new Error(
      `pet-hitbox.json layout.anchors.${name} 与渲染端样式实现不一致：` +
        `渲染端按 ${expected.horizontal}/${expected.vertical} 定位。` +
        "修改锚点需同步更新 petHitboxStyles.ts 与对应 CSS。",
    );
  }
}

const petShortcutButtonSize = 30;
const petShortcutButtonGap = 6;
const petShortcutButtonCount = 5;
const petShortcutColumnCount = 1;
const petShortcutButtonDelayMs = 28;

const petShortcutBarCenterOffset = {
  x:
    petHitboxConfig.window.width -
    petHitboxConfig.hitboxes.shortcutBar.right -
    petHitboxConfig.hitboxes.shortcutBar.width / 2 -
    petHitboxConfig.window.width / 2,
  y:
    petHitboxConfig.window.height -
    petHitboxConfig.hitboxes.shortcutBar.bottom -
    petHitboxConfig.hitboxes.shortcutBar.height / 2 -
    petHitboxConfig.window.height / 2,
};

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
  "--pet-shortcut-bar-center-offset-x": `${petShortcutBarCenterOffset.x}px`,
  "--pet-shortcut-bar-center-offset-y": `${petShortcutBarCenterOffset.y}px`,
  "--pet-shortcut-button-size": `${petShortcutButtonSize}px`,
  "--pet-shortcut-button-gap": `${petShortcutButtonGap}px`,
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
      "--pet-shortcut-open-delay": `${index * petShortcutButtonDelayMs}ms`,
      "--pet-shortcut-close-delay": `${index * petShortcutButtonDelayMs}ms`,
    } as CSSProperties;
  });
}
