# Agent Pet 效果图落地改造计划

目标：将当前 Agent Pet 改造成效果图所示的三层体验：主舞台窗口、Agent 工作空间、桌面陪伴体。整体保持本项目现有架构：Electron + React + Vite 负责桌面端体验，FastAPI 后端负责记忆、任务、设置、诊断与 Agent 运行时。

## 一、目标体验拆解

### 1. 主舞台窗口 Stage First

主舞台是用户主动打开应用时的主要沉浸式界面，包含：

- Live2D 角色居中展示。
- 柔和背景场景，可使用静态背景图或渐变背景先实现。
- 顶部状态条：Live2D 状态、开心/情绪、桌面在线、时间。
- 左侧信息卡：日期问候、身体状态、记忆数量、今日互动数量。
- 右侧上下文卡：当前背景说明、快捷动作。
- 底部输入框：与角色聊天，支持语音入口占位和发送按钮。
- 底部导航：陪伴、对话、记忆、世界、Agent、设置。

### 2. Agent 工作空间

Agent 工作空间是可控工具层，重点不是陪伴感，而是任务执行、审批和可观察性：

- 独立窄窗口或侧边面板。
- 展示当前任务，例如查天气、创建日程、搜索资料。
- 展示工具步骤，每一步必须有用户可审查的状态。
- 对高影响动作提供拒绝/批准按钮。
- 展示执行日志，便于用户理解 Agent 做了什么。
- 保持“受控、透明、可取消”的产品心智。

### 3. 桌面陪伴体 Always-on Companion

桌面陪伴体是常驻桌面的轻量形态：

- 透明、无边框、置顶或可切换置顶。
- 只显示 Live2D 角色和轻量气泡。
- 支持鼠标穿透/取消穿透切换。
- 提供悬浮快捷按钮：打开主舞台、喜欢/互动、任务、更多。
- 支持简单状态气泡，例如提醒、问候、任务完成提示。

## 二、推荐实施路线

建议按“先结构、再视觉、后动效”的顺序推进，避免一次性重构过大。

### 阶段 1：窗口形态与路由骨架

目标：先把三种形态跑起来。

需要修改：

- `apps/desktop/electron/main.cjs`
  - 增加或整理三个窗口：主舞台窗口、Agent 工作空间窗口、桌面陪伴体窗口。
  - 桌面陪伴体窗口使用 transparent、frameless、alwaysOnTop、skipTaskbar 等 Electron 能力。
  - 复用已有鼠标穿透逻辑，保证桌面陪伴体可在“可交互”和“穿透”之间切换。
  - 建立 IPC：打开/关闭 Agent 工作空间、打开主舞台、切换陪伴体置顶、切换穿透。

- `apps/desktop/src/App.tsx`
  - 根据窗口模式或 URL route 渲染不同入口。
  - 新增三个顶层页面组件：StageView、AgentWorkspaceView、CompanionView。

建议路径：

- `apps/desktop/src/views/StageView.tsx`
- `apps/desktop/src/views/AgentWorkspaceView.tsx`
- `apps/desktop/src/views/CompanionView.tsx`

验收标准：

- 应用启动后能打开主舞台。
- 能从主舞台打开 Agent 工作空间。
- 能显示独立透明桌面陪伴体。
- 窗口关闭、最小化、托盘行为不破坏现有桌面应用生命周期。

### 阶段 2：主舞台 UI 落地

目标：实现效果图左侧主舞台窗口的核心视觉。

需要修改：

- `apps/desktop/src/views/StageView.tsx`
  - 组合背景、状态条、Live2D 容器、信息卡、快捷动作、聊天输入、底部导航。

- `apps/desktop/src/components/`
  - 新增或整理可复用组件：StatusPill、GlassCard、BottomNav、ChatInput、MetricBars、QuickActions。

- `apps/desktop/src/styles/` 或现有样式入口
  - 增加玻璃拟态样式、柔和阴影、暖色背景、响应式布局。

数据来源：

- 角色状态：前端本地状态先实现，后续接后端设置/记忆统计。
- 记忆数量、今日互动数量：优先从已有记忆、会话或统计接口读取；如果接口不足，再补后端聚合接口。
- 聊天：继续走现有 ApiClient/IPC 封装，不直接在组件里写临时 fetch。

验收标准：

- 主舞台视觉结构与效果图一致：左侧信息卡、中间角色、右侧上下文卡、底部输入和导航。
- 用户可以在底部输入框发起对话。
- Live2D 模型仍能正常加载、显示和基础交互。

### 阶段 3：Agent 工作空间落地

目标：把 Agent 的任务执行变成可审查、可取消、可观察的工具面板。

需要修改：

- `apps/desktop/src/views/AgentWorkspaceView.tsx`
  - 当前任务卡片。
  - 工具步骤列表。
  - 拒绝/批准按钮。
  - 执行日志区域。

- `apps/desktop/src/services/` 中现有 API/IPC 封装
  - 补充任务列表、任务详情、工具步骤、审批动作、执行日志的调用。
  - 保持所有受保护接口携带 session bearer token。

- `apps/backend/app/api/`
  - 若现有任务接口不足，增加只读任务状态接口。
  - 若需要审批动作，增加明确的 approve/reject endpoint。

- `apps/backend/app/agents/runtime.py`
  - 对写入 Vault、创建任务、发送提醒等高影响动作继续走提案/确认流程。
  - 确保工具调用状态可被前端查询。

验收标准：

- Agent 工作空间能显示当前任务、步骤状态和执行日志。
- 用户可以批准或拒绝需要确认的动作。
- 长期记忆和 Vault/Markdown 写入不允许绕过预览/确认流程。

### 阶段 4：桌面陪伴体落地

目标：实现效果图右侧 Always-on Companion。

需要修改：

- `apps/desktop/electron/main.cjs`
  - 增加 companion window 的尺寸、透明、无边框、置顶、穿透、拖拽行为。
  - 提供 IPC 控制：显示/隐藏、切换穿透、打开主舞台、打开 Agent 工作空间。

- `apps/desktop/src/views/CompanionView.tsx`
  - 只渲染角色、气泡和快捷按钮。
  - 根据状态展示问候、提醒、任务完成等短消息。

- `apps/desktop/src/components/live2d/` 或现有 Live2D 组件
  - 确认 Live2D 容器可以在主舞台和陪伴体复用。
  - 避免重复加载导致性能过高；必要时为陪伴体使用轻量渲染配置。

验收标准：

- 桌面陪伴体透明显示，无普通窗口边框。
- 可在桌面上拖动或通过设置控制位置。
- 可切换鼠标穿透。
- 点击快捷按钮能打开对应窗口。

### 阶段 5：视觉系统统一

目标：让三种形态统一成效果图中的柔和、暖色、玻璃拟态风格。

建议设计变量：

- 背景：暖米色、浅粉、柔和光晕渐变。
- 卡片：半透明白色、模糊背景、圆角 20-28px。
- 主色：粉色用于陪伴，绿色用于运行/通过，橙色用于活力。
- 阴影：低透明度大半径阴影，避免硬边界。
- 字体：中文优先使用系统字体，保证 Windows 清晰度。

建议新增：

- `apps/desktop/src/styles/theme.css`
- `apps/desktop/src/styles/glass.css`

验收标准：

- 主舞台、Agent 工作空间、桌面陪伴体共享相同视觉变量。
- UI 文案保持中文为主。
- 内部历史名称 Wiki 不暴露到用户界面。

## 三、后端与数据接口建议

优先复用当前后端能力，不要为了 UI 另起一套状态系统。

可能需要的接口能力：

1. 陪伴状态聚合接口
   - 返回角色状态、今日互动、记忆数量、当前问候语、最近提醒。
   - 可放在 settings、diagnostics 或新建 companion/status 类接口中。

2. Agent 任务状态接口
   - 返回当前任务、步骤、是否需要审批、日志摘要。
   - 优先基于现有 task service 和 agent runtime 状态扩展。

3. UI 设置持久化
   - 记录桌面陪伴体位置、尺寸、置顶、穿透、显示状态。
   - 使用现有 settings service，不把这类状态写入 Vault。

4. 记忆统计接口
   - 返回长期记忆数量、待确认记忆数量、最近记忆摘要。
   - 只读接口即可；写入仍必须走预览/确认。

## 四、安全与产品约束

必须保留：

- 受保护 API 继续要求 Authorization bearer token。
- 生产环境 token 继续通过环境变量传递，不放在命令行参数中。
- 长期记忆和 Vault/Markdown 写入必须走预览、审查、确认。
- Agent 工作空间中的高影响动作必须清楚显示“将要做什么”。
- 用户界面文案以中文为主。
- `.tmp` 只用于临时试验，不作为用户知识库路径。

避免：

- 不要让聊天直接写用户 Markdown 文件。
- 不要在 React 组件里散落临时 fetch，统一走 ApiClient/IPC 服务。
- 不要为了效果图一次性替换现有主架构。
- 不要引入过重 UI 框架，除非现有样式体系无法支撑。

## 五、建议提交顺序

### 提交 1：三窗口骨架

- 新增 StageView、AgentWorkspaceView、CompanionView。
- Electron 支持打开三种窗口。
- IPC 打通基本窗口控制。

### 提交 2：主舞台 UI

- 完成主舞台布局和玻璃拟态样式。
- 接入现有聊天入口和 Live2D 组件。

### 提交 3：Agent 工作空间

- 完成任务卡、步骤列表、审批按钮、执行日志。
- 接入已有任务/Agent 接口，不足部分补后端只读接口。

### 提交 4：桌面陪伴体

- 完成透明悬浮窗口。
- 完成气泡、快捷按钮、穿透/置顶控制。

### 提交 5：状态聚合与体验打磨

- 增加陪伴状态聚合接口。
- 接入记忆统计、今日互动、提醒状态。
- 完成 typecheck、build、package check、Live2D 检查。

## 六、验证清单

桌面端：

- 在 `apps/desktop` 运行 `npm run typecheck`。
- 在 `apps/desktop` 运行 `npm run build`。
- 在 `apps/desktop` 运行 `npm run package:check`。
- 如果改动 Live2D 路径，运行 `npm run live2d:check:public` 和 `npm run live2d:sdk:check`。
- 启动 Electron 开发模式，手动验证主舞台、Agent 工作空间、桌面陪伴体。

后端：

- 在 `apps/backend` 运行 `python -m pytest`。
- 如果改动任务、记忆或 Agent runtime，补充运行相关单测。

手动验收：

- 主舞台能聊天。
- 桌面陪伴体能显示、移动、切换穿透、打开主舞台。
- Agent 工作空间能显示任务和日志。
- 需要确认的动作不会绕过用户审批。
- 关闭应用后没有残留异常后端进程。

## 七、优先级建议

最高优先级：

1. 三窗口骨架。
2. 主舞台视觉和聊天入口。
3. 桌面陪伴体透明置顶与穿透。

第二优先级：

1. Agent 工作空间任务状态。
2. 审批和日志可视化。
3. 陪伴状态聚合接口。

第三优先级：

1. 更细的 Live2D 动作、表情和动效。
2. 背景场景切换。
3. 更完整的世界/记忆/设置页面视觉统一。

## 八、最小可交付版本

如果只做第一版，建议范围控制为：

- 一个主舞台窗口。
- 一个透明桌面陪伴体窗口。
- 主舞台中可聊天、可看到 Live2D、可打开 Agent 工作空间占位面板。
- Agent 工作空间先显示当前任务和日志，审批按钮可以先接入已有提案/确认流程。
- 所有新增 UI 使用本地 mock 状态时，必须标清 TODO 并尽快替换为真实接口。

这样可以先把效果图的产品心智跑通，再逐步补齐 Agent 工作空间的深度能力。