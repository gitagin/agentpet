const { app, Menu, Tray, nativeImage } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

function createTrayManager({
  createPetWindow,
  showControlWindow,
  showStageWindow,
  showAgentWindow,
  showFeatureWindow,
  showPetInputMode,
  quitApp,
}) {
  let tray = null;

  function findTrayIconPath() {
    const candidates = [
      path.join(app.getAppPath(), "dist", "live2d", "UG", "icon.png"),
      path.join(app.getAppPath(), "public", "live2d", "UG", "icon.png"),
    ];

    return candidates.find((candidate) => fs.existsSync(candidate)) || null;
  }

  function createTray() {
    if (tray) {
      return;
    }

    const iconPath = findTrayIconPath();
    if (!iconPath) {
      return;
    }

    const icon = nativeImage.createFromPath(iconPath);
    if (icon.isEmpty()) {
      return;
    }

    tray = new Tray(icon.resize({ width: 16, height: 16 }));
    tray.setToolTip("桌面记忆助手");
    tray.setContextMenu(
      Menu.buildFromTemplate([
        {
          label: "桌宠输入入口",
          submenu: [
            { label: "聊天", click: () => showPetInputMode("chat") },
            { label: "记一个", click: () => showPetInputMode("note") },
            { label: "新任务", click: () => showPetInputMode("task") },
            { label: "整理 Wiki", click: () => showPetInputMode("wiki") },
            { label: "今日复盘", click: () => showPetInputMode("review") },
          ],
        },
        { type: "separator" },
        { label: "显示桌宠", click: () => createPetWindow() },
        { label: "打开主舞台", click: showStageWindow },
        { label: "打开聊天窗口", click: () => showFeatureWindow("chat") },
        { label: "打开任务工作台", click: showAgentWindow },
        { label: "打开记忆整理", click: () => showFeatureWindow("memory") },
        { label: "打开成长记录", click: () => showFeatureWindow("growth") },
        { label: "打开知识库", click: () => showFeatureWindow("world") },
        { label: "打开设置", click: () => showFeatureWindow("settings") },
        { label: "打开控制台", click: showControlWindow },
        { type: "separator" },
        {
          label: "退出应用",
          click: quitApp,
        },
      ]),
    );
    tray.on("click", () => createPetWindow());
  }

  return {
    createTray,
  };
}

module.exports = {
  createTrayManager,
};
