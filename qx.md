# 三窗口整改方案

## 目标效果

项目最终应只保留三类用户可见窗口：

1. 主舞台窗口：展示沉浸式 Live2D 主体验，中央直接渲染模型，并承载状态卡片、对话输入、底部导航等主界面。
2. Agent 工作空间窗口：作为受控工具层，用于任务执行、审批、日志和 Agent 操作。
3. 桌面陪伴体窗口：使用现有 pet 窗口作为桌面常驻陪伴体，透明置顶、支持有限交互，不再额外创建功能重复的 companion 窗口。

## 当前代码中的主要问题

### 1. 实际创建了四个窗口

入口在 `apps/desktop/electron/main.cjs`，当前启动流程会同时创建：

- pet 窗口
- stage 主舞台窗口
- agent 工作空间窗口
- companion 窗口

其中 `apps/desktop/electron/windows.js` 中有这些创建函数：

- `createPetWindow`
- `createStageWindow`
- `createAgentWindow`
- `createCompanionWindow`

这导致右侧独立 companion 窗口与 pet 窗口职责重复。

### 2. companion 窗口全窗口鼠标穿透，按钮不可点击

`createCompanionWindow` 当前调用了类似下面的逻辑：

```js
companionWindow.setIgnoreMouseEvents(true, { forward: true })
```

这会让整个 companion 窗口完全穿透鼠标事件，因此虽然 React 层显示了按钮，实际点击不到。

### 3. 主舞台中央没有直接渲染真实模型

主舞台入口是 `apps/desktop/src/views/StageView.tsx`，模型区域使用 `Live2DStage` 组件。

但 `apps/desktop/src/components/Live2DStage.tsx` 中真实 Live2D 渲染目前只在 `variant === "pet"` 时挂载，主舞台使用的 variant 没有真正挂载模型渲染器，所以主舞台更像数据面板，而不是图中那种中央直接出现角色模型的舞台。

### 4. pet 的右键菜单不符合目标交互

pet 窗口当前还有右键菜单，相关逻辑在 `apps/desktop/electron/windows.js` 的 `showPetContextMenu`。

目标效果里，桌面陪伴体不应依赖右键菜单，应该把常用操作可视化成按钮，例如：

- 打开主舞台
- 打开 Agent 工作空间
- 对话/互动
- 设置或更多
- 关闭/隐藏

这些能力可以参考现有 `apps/desktop/src/views/CompanionView.tsx`，把其中可视化按钮迁移到 pet 窗口里。

## 推荐修改顺序

### 第一步：去掉独立 companion 窗口

在 Electron 主进程里停止创建 companion 窗口。

重点检查：

- `apps/desktop/electron/main.cjs`
- `apps/desktop/electron/windows.js`
- `apps/desktop/src/App.tsx`

建议做法：

1. 从启动流程中移除 `createCompanionWindow` 调用。
2. 删除或暂时停用 companion 相关 IPC、窗口管理、位置保存逻辑。
3. `App.tsx` 不再需要渲染 `CompanionView` 路由，或者先保留组件但不再从主进程打开。
4. 保留 pet 窗口作为唯一桌面陪伴体。

这样可以先消除“右侧固定 companion 窗口点击不了且与 pet 重复”的问题。

### 第二步：把 companion 的可视按钮迁移到 pet 窗口

当前 `CompanionView.tsx` 里已经有类似目标效果的按钮设计，可以复用交互思路，但最终应落到 pet 视图。

重点检查：

- `apps/desktop/src/views/PetView.tsx`
- `apps/desktop/src/views/CompanionView.tsx`
- `apps/desktop/src/styles.css`
- `apps/desktop/electron/preload.cjs`
- `apps/desktop/electron/windows.js`

建议做法：

1. 在 `PetView.tsx` 中增加一组悬浮可视化按钮。
2. 按钮功能至少包括：打开主舞台、打开 Agent、互动、更多/设置。
3. 按钮点击通过 preload 暴露的 Electron API 调用主进程 IPC。
4. pet 窗口的鼠标穿透逻辑要保留，但交互区域必须不穿透。
5. 更新 pet hitbox，让按钮区域、输入区域、气泡区域可以点击，其他透明区域继续穿透。

这样 pet 就能承担桌面陪伴体职责，不需要额外 companion 窗口。

### 第三步：移除 pet 右键菜单

目标是所有常用操作都通过可视按钮完成，不再依赖右键。

重点检查：

- `apps/desktop/electron/windows.js`

建议做法：

1. 删除或停用 `showPetContextMenu`。
2. 移除 pet 窗口上的 `context-menu` 事件绑定。
3. 如果仍需要“退出”“重载模型”“保持置顶”等能力，放到 pet 的更多按钮里。

注意：不要直接丢失退出能力，至少应在主舞台、Agent 工作空间或 pet 更多菜单里保留关闭/退出入口。

### 第四步：让主舞台中央真实渲染 Live2D 模型

重点检查：

- `apps/desktop/src/views/StageView.tsx`
- `apps/desktop/src/components/Live2DStage.tsx`
- `apps/desktop/src/styles.css`

建议做法：

1. 调整 `Live2DStage` 的渲染条件，不要只在 `variant === "pet"` 时挂载真实 Live2D。
2. 给主舞台增加一个明确的 variant，例如 `variant="stage"`。
3. 当 variant 是 `stage` 时，也挂载 Live2D renderer。
4. 为 stage 模式设置独立尺寸和布局：模型应位于主舞台中央，而不是缩在卡片或诊断区域里。
5. 仅保留必要的状态浮层，把当前过多的数据卡片弱化为辅助信息。

核心原则：主舞台的视觉中心应该是模型，而不是数据列表。

### 第五步：整理三个窗口之间的职责

建议最终职责如下：

#### 主舞台窗口

负责：

- 中央 Live2D 模型展示
- 主对话输入
- 状态卡片
- 记忆/世界/设置等主导航
- 打开 Agent 工作空间

不负责：

- 透明桌宠常驻
- 后台任务审批细节

#### Agent 工作空间窗口

负责：

- 当前任务
- 待审批操作
- 执行日志
- Agent 工具调用状态
- 用户确认/拒绝

不负责：

- 桌宠展示
- 主舞台沉浸式 UI

#### pet 桌面陪伴体窗口

负责：

- 常驻桌面陪伴
- 轻量气泡
- 简单互动
- 快捷打开主舞台和 Agent
- 透明区域鼠标穿透

不负责：

- 完整主界面
- 完整 Agent 审批流
- 右键菜单交互

## 需要优先修改的文件清单

1. `apps/desktop/electron/main.cjs`
   - 停止创建 companion 窗口。
   - 确认启动时只创建 pet、stage、agent 三个窗口。

2. `apps/desktop/electron/windows.js`
   - 移除或停用 `createCompanionWindow`。
   - 移除 pet 右键菜单绑定。
   - 调整 pet 鼠标穿透和 hitbox，让可视按钮区域可点击。

3. `apps/desktop/src/App.tsx`
   - 不再把 companion 作为独立窗口入口。
   - 保留 stage、agent、pet 三个视图入口。

4. `apps/desktop/src/views/PetView.tsx`
   - 增加桌面陪伴体可视化按钮。
   - 迁移 `CompanionView.tsx` 中有用的按钮设计和交互。

5. `apps/desktop/src/views/CompanionView.tsx`
   - 如果不再需要独立 companion，可以删除。
   - 如果暂时不删，应确保不会被主进程打开。

6. `apps/desktop/src/views/StageView.tsx`
   - 调整主舞台布局，让模型成为中央主体。
   - 减少当前数据面板式展示。

7. `apps/desktop/src/components/Live2DStage.tsx`
   - 支持 stage 模式真实挂载 Live2D renderer。
   - 不要只允许 pet 模式渲染真实模型。

8. `apps/desktop/src/styles.css`
   - 增加 stage 模式模型布局。
   - 增加 pet 可视按钮样式。
   - 删除或弱化 companion 专用样式。

## 验收标准

完成后应满足：

1. 启动应用后只出现三个窗口：主舞台、Agent 工作空间、pet 桌面陪伴体。
2. 不再出现右侧固定且点击不了的 companion 窗口。
3. 主舞台中央直接显示 Live2D 模型。
4. pet 窗口不再依赖右键菜单。
5. pet 窗口上有可点击的可视化按钮。
6. pet 透明区域仍然鼠标穿透，但按钮、气泡、输入等交互区域可以点击。
7. Agent 工作空间仍能从主舞台或 pet 快捷打开。
8. 执行以下命令不应报错：

```powershell
Push-Location E:\agentproject\apps\desktop
npm run typecheck
npm run build
npm run package:check
Pop-Location
```

## 建议实现策略

建议不要一次性大改全部 UI。更稳妥的顺序是：

1. 先停用 companion 窗口，确认窗口数量变成三个。
2. 再把 companion 的按钮迁移到 pet。
3. 然后移除 pet 右键菜单。
4. 最后重构主舞台 Live2D 中央渲染。

这样每一步都可以单独验证，出现问题也更容易回滚。