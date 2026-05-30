# 统一窗口内导航计划

## 用户确认
采用“窗口内导航”：每个页面窗口底部都有同一套导航；切换在同一个 860×660 窗口中完成，而不是靠独立透明导航浮窗跟随。

## 目标
- 所有功能页窗口大小与陪伴/主舞台一致：860 × 660，最小 720 × 560。
- “主舞台”不再是总窗口概念，而是导航中的“陪伴”页。
- 每个页面底部都显示同一套导航：陪伴 / 对话 / 记忆 / 世界 / Agent / 设置。
- 点击导航应切换当前功能窗口内容，而不是不断打开多个独立窗口。

## 推荐实现
1. Electron 层统一功能窗口尺寸
   - 将 `chat/memory/world/settings` feature window 配置全部改为 `STAGE_WINDOW_WIDTH/HEIGHT/MIN_*`。
   - 简化切换：从底部导航调用 `openFeatureWindow(mode)` 时，隐藏其他 feature/agent，并显示目标窗口；尺寸一致。

2. 废弃独立 StageNav 浮窗在功能切换中的角色
   - 保留 `StageNavView` 和 `stage-nav` 窗口代码以免大改，但不再作为主要导航入口。
   - 新增 React 内嵌导航组件 `BottomNav`，在 `stage/chat/memory/world/settings/agent` 视图里显示。
   - 后续可再彻底删除 Electron 的 `stageNavWindow`。

3. 新增内嵌导航组件
   - 新文件 `apps/desktop/src/views/BottomNav.tsx`。
   - props：`activeTab`。
   - 映射：
     - 陪伴 → `window.agentDesktop?.openStage?.()`
     - 对话 → `openFeatureWindow("chat")`
     - 记忆 → `openFeatureWindow("memory")`
     - 世界 → `openFeatureWindow("world")`
     - Agent → `openAgent()`
     - 设置 → `openFeatureWindow("settings")`

4. 页面布局适配底部导航
   - `StageView` 底部留出导航区域，聊天输入上移，渲染 `<BottomNav activeTab="陪伴" />`。
   - `FeatureWindowShell` 增加 `activeTab`，底部统一渲染 `<BottomNav />`。
   - `AgentWorkspaceView` 如果当前结构允许，底部也加 `<BottomNav activeTab="Agent" />`；否则先保证 stage/feature 四页。

5. Electron 切换语义
   - `showStageWindow()`：隐藏 feature windows 和 agent，显示 stage。
   - `showFeatureWindow(mode)`：隐藏 stage? 这里有两种实现：
     - 最小改动：保持 stage 在后面，显示目标 feature 窗口；由于尺寸一致并聚焦，用户看到的是切换到目标页。
     - 更彻底：隐藏 stageWindow，但这会导致原 stageNav 子窗口逻辑受影响。当前先保守不隐藏 stage，只隐藏其他 feature/agent。
   - 点击“陪伴”回到 stageWindow。

6. 验证
   - `npm --prefix apps/desktop run typecheck`
   - `npm --prefix apps/desktop run build`
   - 手动验证每个页面底部都有导航，点击后窗口尺寸一致且视觉上是页面切换。

## 后续优化
- 如果用户确认不再需要独立透明 `stage-nav` 浮窗，可删除 `createStageNavWindow` 与相关 IPC/模式，减少窗口数量和层级问题。
