# 复用独立导航浮窗修正计划

## 目标
- 撤销刚才“窗口内部嵌入导航”的实现，避免主舞台出现两个导航栏。
- 复用原来的独立透明导航窗口 `stage-nav`。
- 导航浮窗不再只绑定主舞台，而是跟随当前激活页面窗口：陪伴 / 对话 / 记忆 / 世界 / Agent / 设置。
- 页面窗口尺寸统一为主舞台尺寸：860 × 660，最小 720 × 560。

## 实施步骤
1. 移除内嵌导航
   - 从 `StageView.tsx` 删除 `BottomNav` 引用和渲染，把聊天输入/模型区域位置恢复到适合外部浮窗的布局。
   - 从 `FeatureWindowShell.tsx` 删除 `BottomNav` 引用和渲染，恢复为内容窗口，不在内部占底部导航空间。
   - 保留 `BottomNav.tsx` 文件暂不删除也可以，但不再使用；如确认无用可删除。

2. 改造 Electron 导航浮窗跟随逻辑
   - 在 `windows.js` 增加当前导航锚点窗口 `navigationHostWindow`。
   - `positionStageNavWindow()` 不再固定读取 `stageWindow`，改为读取 `navigationHostWindow`。
   - `stageNavWindow` 创建时不再设置 `parent: stageWindow`，避免只能跟随主舞台。
   - 当前页面窗口移动/缩放/显示/恢复时重新定位导航浮窗。
   - 当前页面最小化/隐藏/关闭时隐藏导航浮窗或切回陪伴页。

3. 页面切换时更新导航锚点
   - `showStageWindow()`：当前锚点设为 `stageWindow`，显示导航浮窗。
   - `showFeatureWindow(mode)`：隐藏其他页面窗口，当前锚点设为该 feature window，显示导航浮窗。
   - `showAgentWindow()`：把 Agent 改为与主舞台同尺寸的独立窗口，当前锚点设为 `agentWindow`，显示导航浮窗。

4. 同步导航激活态
   - 主进程在切换页面时向 `stageNavWindow` 发送当前 tab：陪伴 / 对话 / 记忆 / 世界 / Agent / 设置。
   - preload 暴露订阅函数。
   - `StageNavView` 监听该事件，保证通过桌宠快捷入口打开窗口时导航高亮也正确。

5. 验证
   - 运行 `npm --prefix apps/desktop run typecheck`。
   - 运行 `npm --prefix apps/desktop run build`。

## 说明
这次会恢复你想要的“独立固定导航栏窗口”体验，而不是把导航嵌入每个页面内部。
