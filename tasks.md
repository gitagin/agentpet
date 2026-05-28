# Agent 可执行任务指令集：三窗口整改

## 执行目标

将当前桌面端窗口体系整改为三个用户可见窗口：

1. 主舞台窗口：中央直接渲染 Live2D 模型，作为主体验窗口。
2. Agent 工作空间窗口：负责任务、审批、执行日志和 Agent 操作。
3. pet 桌面陪伴体窗口：作为唯一桌面常驻陪伴体，透明置顶，保留可点击按钮区域，其余区域鼠标穿透。

必须移除功能重复的独立 companion 窗口，并把 companion 中有价值的可视化按钮能力迁移到 pet 窗口。

## 约束

- 不要新增第四个用户可见窗口。
- 不要保留独立 companion 窗口的启动入口。
- 不要让 pet 继续依赖右键菜单作为主要交互方式。
- 不要破坏现有 Agent 工作空间窗口。
- 不要绕过现有 Electron preload / IPC 结构直接在 renderer 中调用 Node 能力。
- 不要让 pet 全窗口都变成不可穿透；透明空白区域仍应鼠标穿透。
- 不要让按钮、气泡、输入等交互区域鼠标穿透。
- 修改后必须运行桌面端校验命令。

## Task 1：停止创建独立 companion 窗口

### 目标

启动应用后不再出现右侧独立 companion 窗口，只保留 pet、stage、agent 三类窗口。

### 需要检查的文件

- `apps/desktop/electron/main.cjs`
- `apps/desktop/electron/windows.js`
- `apps/desktop/src/App.tsx`

### 执行步骤

1. 在 `apps/desktop/electron/main.cjs` 中找到启动时创建窗口的流程。
2. 移除或停用 `createCompanionWindow` 的调用。
3. 确认启动流程仍会创建：
   - pet 窗口
   - stage 主舞台窗口
   - agent 工作空间窗口
4. 在 `apps/desktop/electron/windows.js` 中检查 companion 窗口相关导出、窗口引用、位置保存和 IPC 控制逻辑。
5. 删除不再使用的 companion 主进程逻辑，或至少保证它不会被启动路径调用。
6. 在 `apps/desktop/src/App.tsx` 中移除 companion 独立路由入口，或保留组件但确保主进程不会加载该 hash。
7. 清理由于移除 companion 引起的 TypeScript 或 lint 报错。

### 验收标准

- 应用启动时不再创建 companion BrowserWindow。
- 右侧不会再出现固定且点击不了的 companion 窗口。
- stage、agent、pet 仍可正常创建或打开。

## Task 2：把 companion 可视化按钮迁移到 pet 窗口

### 目标

pet 窗口成为唯一桌面陪伴体，并提供可点击的可视化按钮，替代原 companion 窗口和 pet 右键菜单中的常用操作。

### 需要检查的文件

- `apps/desktop/src/views/PetView.tsx`
- `apps/desktop/src/views/CompanionView.tsx`
- `apps/desktop/src/styles.css`
- `apps/desktop/electron/preload.cjs`
- `apps/desktop/electron/windows.js`

### 执行步骤

1. 阅读 `CompanionView.tsx` 中已有按钮布局和交互逻辑。
2. 在 `PetView.tsx` 中新增桌面陪伴体按钮区。
3. 至少提供以下按钮：
   - 打开主舞台
   - 打开 Agent 工作空间
   - 互动或对话
   - 更多或设置
4. 按钮点击必须通过 preload 暴露的安全 API 调用主进程 IPC。
5. 如果 preload 中缺少所需 API，补充最小必要 API。
6. 如果主进程中缺少对应 IPC，补充最小必要处理逻辑。
7. 不要在 renderer 中直接访问 Electron 或 Node 全局对象。
8. 给 pet 按钮增加样式，视觉上类似右侧竖向悬浮按钮或底部轻量快捷操作区。
9. 确认按钮不会遮挡 Live2D 模型主体。
10. 删除或减少不再需要的 companion 专用样式，避免死代码。

### 验收标准

- pet 窗口中可以看到可视化操作按钮。
- 点击“打开主舞台”可以显示或聚焦 stage 窗口。
- 点击“打开 Agent 工作空间”可以显示或聚焦 agent 窗口。
- pet 的按钮区可以点击。
- pet 的透明空白区域仍然鼠标穿透。

## Task 3：调整 pet 鼠标穿透 hitbox

### 目标

pet 透明区域继续鼠标穿透，但模型交互区、气泡、输入区、可视按钮区必须可以点击。

### 需要检查的文件

- `apps/desktop/electron/windows.js`
- `apps/desktop/src/views/PetView.tsx`
- `apps/desktop/src/styles.css`
- pet hitbox 相关 JSON 或 IPC 数据结构

### 执行步骤

1. 找到 pet 窗口当前鼠标穿透逻辑。
2. 找到 hitbox 数据来源，例如 `pet-hitbox.json` 或 renderer 上报的交互区域。
3. 将新增 pet 按钮区域纳入可交互 hitbox。
4. 保留透明区域穿透能力。
5. 保证气泡、输入栏、按钮区、模型必要交互区不会被 `setIgnoreMouseEvents(true)` 错误穿透。
6. 如果当前 hitbox 是固定坐标，更新坐标计算逻辑以适配新增按钮。
7. 如果当前 hitbox 由 renderer 上报，更新 renderer 上报内容。

### 验收标准

- 点击 pet 可视按钮有响应。
- 点击 pet 气泡或输入区域有响应。
- 点击 pet 透明空白区域会穿透到桌面或下层窗口。
- 不再出现整个 pet 窗口完全不可点击的问题。

## Task 4：移除 pet 右键菜单依赖

### 目标

pet 不再通过右键菜单提供主要功能，常用功能改由可视化按钮承载。

### 需要检查的文件

- `apps/desktop/electron/windows.js`
- `apps/desktop/src/views/PetView.tsx`
- `apps/desktop/electron/preload.cjs`

### 执行步骤

1. 在 `windows.js` 中找到 `showPetContextMenu`。
2. 找到 pet 窗口绑定 `context-menu` 事件的位置。
3. 移除或停用 pet 的右键菜单绑定。
4. 将右键菜单中的必要能力迁移到 pet 可视化按钮或更多按钮中。
5. 至少保留这些能力中的可用入口：
   - 打开主舞台
   - 打开 Agent 工作空间
   - 设置或更多
   - 退出或隐藏应用
6. 如果“退出应用”属于破坏性或高影响操作，应保留明确可见入口并避免误触。

### 验收标准

- 右键 pet 不再弹出旧菜单。
- 用户仍能通过可视化按钮完成常用操作。
- 应用仍有合理的退出或隐藏入口。

## Task 5：让主舞台中央真实渲染 Live2D 模型

### 目标

主舞台窗口中央直接显示真实 Live2D 模型，不再只是数据面板或静态预览。

### 需要检查的文件

- `apps/desktop/src/views/StageView.tsx`
- `apps/desktop/src/components/Live2DStage.tsx`
- `apps/desktop/src/styles.css`

### 执行步骤

1. 阅读 `StageView.tsx` 中当前主舞台布局。
2. 阅读 `Live2DStage.tsx` 中真实 Live2D renderer 的挂载条件。
3. 修改 `Live2DStage`，让 stage 模式也能挂载真实 Live2D renderer。
4. 如果当前只有 `variant === "pet"` 才挂载 renderer，改为允许 `variant === "stage"` 也挂载。
5. 在 `StageView.tsx` 中明确传入 stage 模式，例如 `variant="stage"`。
6. 为 stage 模式设置独立布局和尺寸，确保模型位于主舞台中央。
7. 保留必要状态信息，但不要让数据卡片喧宾夺主。
8. 确保主舞台底部输入框、导航和侧边状态卡片不会遮挡模型主体。
9. 如果 Live2D 加载失败，沿用现有错误展示或诊断信息，不要引入新的复杂兜底。

### 验收标准

- 主舞台中央可以看到真实 Live2D 模型。
- 主舞台仍保留必要状态卡片、输入框和导航。
- 主舞台不再表现为“只列出一堆数据”的界面。
- pet 窗口的 Live2D 渲染不受影响。

## Task 6：清理 companion 视图和样式残留

### 目标

移除或隔离不再使用的 companion 代码，避免未来维护时误以为它仍是一个独立窗口。

### 需要检查的文件

- `apps/desktop/src/views/CompanionView.tsx`
- `apps/desktop/src/App.tsx`
- `apps/desktop/src/styles.css`
- `apps/desktop/electron/windows.js`
- `apps/desktop/electron/preload.cjs`

### 执行步骤

1. 确认 companion 独立窗口已经不再创建。
2. 如果 `CompanionView.tsx` 已完全无引用，删除该文件并清理 import。
3. 如果暂时保留 `CompanionView.tsx`，在代码结构上确保它不会作为独立窗口入口使用。
4. 删除未使用的 companion CSS class。
5. 删除未使用的 companion IPC、preload API 和窗口控制逻辑。
6. 运行 TypeScript 检查，清理未使用变量、类型和导入。

### 验收标准

- 没有未使用 import 或 TypeScript 报错。
- companion 不再作为独立窗口存在。
- pet 已承担桌面陪伴体职责。

## Task 7：验证桌面端构建和运行

### 目标

确认三窗口整改没有破坏桌面端类型检查、构建和打包检查。

### 执行命令

在仓库根目录执行：

```powershell
Push-Location E:\agentproject\apps\desktop
npm run typecheck
npm run build
npm run package:check
Pop-Location
```

如使用 bash 环境，也可以等价执行：

```bash
cd /e/agentproject/apps/desktop
npm run typecheck
npm run build
npm run package:check
```

### 验收标准

- `npm run typecheck` 通过。
- `npm run build` 通过。
- `npm run package:check` 通过。
- 如果有失败，必须修复与本次改动相关的问题。
- 不要修复与本次任务无关的历史问题，除非它阻塞验证。

## Task 8：手动运行验证窗口行为

### 目标

确认实际运行效果符合三窗口目标，而不是只通过静态构建。

### 执行步骤

1. 启动桌面端开发环境。
2. 观察启动后窗口数量。
3. 验证只存在以下用户可见窗口：
   - 主舞台窗口
   - Agent 工作空间窗口
   - pet 桌面陪伴体窗口
4. 确认不会出现右侧独立 companion 窗口。
5. 在主舞台确认中央显示真实 Live2D 模型。
6. 在 pet 窗口确认按钮可点击。
7. 在 pet 透明区域点击，确认鼠标事件可以穿透。
8. 从 pet 打开主舞台。
9. 从 pet 打开 Agent 工作空间。
10. 从主舞台打开 Agent 工作空间。

### 验收标准

- 实际运行窗口数量符合目标。
- 主舞台视觉中心是 Live2D 模型。
- pet 是唯一桌面陪伴体。
- pet 不依赖右键菜单。
- pet 的可视化按钮可用。
- pet 透明区域鼠标穿透正常。

## 最终完成条件

只有同时满足以下条件，才算任务完成：

1. 独立 companion 窗口已停用或移除。
2. pet 窗口拥有可视化操作按钮。
3. pet 右键菜单已移除或不再作为主要交互方式。
4. pet 鼠标穿透只作用于透明非交互区域。
5. 主舞台中央真实渲染 Live2D 模型。
6. Agent 工作空间仍能正常打开。
7. 桌面端 typecheck、build、package:check 均通过。
8. 已进行一次实际运行验证，并确认窗口行为符合预期。

## 建议提交说明

如果需要提交 git commit，建议提交信息使用：

```text
调整桌面端三窗口结构
```

提交前请确认没有把临时日志、构建产物或本地配置文件加入版本控制。