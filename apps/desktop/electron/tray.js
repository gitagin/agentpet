const { app, Menu, Tray, nativeImage } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

function createTrayManager({ createPetWindow, showControlWindow, quitApp }) {
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
        { label: "显示桌宠", click: () => createPetWindow() },
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
