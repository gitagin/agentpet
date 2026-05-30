# 主舞台导航独立窗口化计划

## 目标
- 主舞台导航中的“对话 / 记忆 / 世界 / 设置”不再打开控制台并滚动定位，而是各自打开独立窗口。
- 保留“陪伴”聚焦主舞台，“Agent”沿用现有 Agent 工作空间窗口。
- 保留旧控制台入口兼容现有代码，但主舞台导航和桌宠快捷入口改走独立窗口。

## 窗口规划
- 对话窗口 `chat`：560 × 720，最小 480 × 560。
- 记忆窗口 `memory`：720 × 760，最小 640 × 560。
- 世界窗口 `world`：920 × 760，最小 760 × 600。
- 设置窗口 `settings`：760 × 760，最小 680 × 560。

## 实施步骤
1. Electron 主进程新增功能窗口管理
   - 在 `apps/desktop/electron/windows.js` 增加 feature window 配置表和 `featureWindows` Map。
   - 新增 `showFeatureWindow(mode)`、`createFeatureWindow(mode)`、`getFeatureWindow(mode)`、`getFeatureWindows()`。
   - 复用现有 `loadAppWindow(window, mode)`，为窗口加载 `#/chat`、`#/memory`、`#/world`、`#/settings`。
   - 在窗口关闭时从 Map 清理，避免重复引用。

2. IPC / preload / 类型补齐
   - 在 `apps/desktop/electron/ipc.js` 增加 `window:open-feature` handler。
   - `get-window-mode` 匹配新增 feature windows。
   - 在 `apps/desktop/electron/preload.cjs` 暴露 `openFeatureWindow(mode)`。
   - 在 `apps/desktop/src/types.ts` 增加 `DesktopWindowMode` / `DesktopFeatureWindowMode` 类型，并补齐 `window.agentDesktop.openFeatureWindow`。

3. React 增加独立渲染模式
   - 在 `apps/desktop/src/App.tsx` 将窗口模式扩展为：`pet | control | stage | stage-nav | agent | chat | memory | world | settings`。
   - `detectDesktopWindowMode()` 支持新增 hash。
   - 在主 render 分支中新增：
     - `chat` → 独立对话窗口视图。
     - `memory` → 独立记忆活动窗口视图。
     - `world` → 独立世界/Vault 维护窗口视图。
     - `settings` → 独立设置窗口视图。

4. 拆分/复用窗口内容
   - 新增 `apps/desktop/src/views/FeatureWindowShell.tsx`：提供独立窗口统一背景、标题、滚动容器。
   - 新增 `ChatWindowView.tsx`：承载聊天输入、停止生成、最近消息列表。
   - 新增 `MemoryWindowView.tsx`：承载“最近自动整理活动”，复用现有活动渲染逻辑和卡片。
   - 新增 `WorldWindowView.tsx`：包裹现有 `WikiWorkflowPanel`。
   - 新增 `SettingsWindowView.tsx`：包裹现有 `SettingsPanel`。
   - 为降低风险，第一版复用 `App.tsx` 当前 hooks/state 和回调，不立即重构后端状态同步。

5. 修改入口映射
   - `apps/desktop/src/views/StageNavView.tsx`：
     - “对话” → `openFeatureWindow("chat")`
     - “记忆” → `openFeatureWindow("memory")`
     - “世界” → `openFeatureWindow("world")`
     - “设置” → `openFeatureWindow("settings")`
     - “陪伴” → `openStage()`
     - “Agent” → `openAgent()`
   - `apps/desktop/src/App.tsx` 桌宠快捷按钮：
     - “对话”改为打开 `chat` 窗口。
     - “设置”改为打开 `settings` 窗口。

6. 样式适配
   - 在 `apps/desktop/src/styles.css` 增加 `.feature-shell` / `.feature-window-panel` / 独立窗口滚动样式。
   - 避免沿用控制台 `.dashboard-grid` 导致内容挤压。
   - 对 chat 消息列表使用可伸缩高度，避免小窗口不可用。

7. 兼容与后续优化
   - 保留 `openControlWindow(targetId)`，不删除旧控制台。
   - `useWiki` 中将自动加载条件从仅 `control` 扩展到 `control || world`。
   - 注意多窗口第一版会各自维护 renderer 内的聊天状态；后续若需要完全同步，再把聊天历史统一落后端或加主进程广播。

## 验证
- 运行 `npm --prefix apps/desktop run typecheck`。
- 如类型检查通过，再运行 `npm --prefix apps/desktop run build`。
- 手动验证：主舞台导航点击四个功能分别打开独立窗口；桌宠快捷“对话/设置”打开对应独立窗口；旧控制台仍可打开。
