# Agent Pet — Claude Code 任务指令集

> **使用方式**：在项目根目录启动 Claude Code，每次只执行一个 TASK，等验收通过后再执行下一个。
> **已拍板决策**：Agent 工作空间 = 独立 BrowserWindow；指令格式 = Claude Code CLI；代码库可直接读取。

---

## 前置：每次执行任务前必读

```
执行本任务前，请先阅读以下文件，理解现有代码结构，不要凭空生成：
- apps/desktop/electron/main.cjs       （Electron 主进程）
- apps/desktop/src/App.tsx             （React 入口）
- apps/desktop/src/services/           （现有 API/IPC 封装，列出所有文件）
- apps/desktop/package.json            （确认现有 scripts 和依赖）

阅读完成后，再开始执行任务。如果文件不存在，停下来告诉我，不要自行创建替代结构。
```

---

## SPRINT 1：三窗口骨架

### TASK-01 — 读取并摘要现有 Electron 窗口结构

```
目标：理解现有 main.cjs 的窗口创建逻辑，不做任何修改。

执行步骤：
1. 读取 apps/desktop/electron/main.cjs 全文。
2. 列出：
   a. 当前创建了哪些 BrowserWindow，各自的配置（transparent/frameless/alwaysOnTop 等）。
   b. 现有的 IPC 频道名称和用途。
   c. 现有的鼠标穿透逻辑（setIgnoreMouseEvents 调用位置）。
   d. 现有 URL 路由或 loadURL 参数。
3. 输出一份摘要，不修改任何文件。

验收：输出摘要，确认没有文件被修改（git status 干净）。
```

---

### TASK-02 — 读取并摘要现有 React 路由结构

```
目标：理解现有 App.tsx 和路由入口，不做任何修改。

执行步骤：
1. 读取 apps/desktop/src/App.tsx 全文。
2. 读取 apps/desktop/src/views/ 或 apps/desktop/src/pages/ 下所有文件列表。
3. 列出：
   a. 当前路由方案（react-router / 自定义 / 无路由）。
   b. 现有顶层页面组件名称和路径。
   c. 窗口模式识别方式（URL param / window.__MODE__ / 其他）。
4. 输出摘要，不修改任何文件。

验收：输出摘要，git status 干净。
```

---

### TASK-03 — 在 main.cjs 新增三个窗口工厂函数

```
目标：在现有 main.cjs 中新增三个窗口创建函数，不改动现有窗口逻辑。

已拍板决策：
- Agent 工作空间 = 独立 BrowserWindow（非 Panel）。
- 三个窗口通过 URL hash 区分：/#/stage、/#/agent、/#/companion。

执行步骤：
1. 读取 apps/desktop/electron/main.cjs（从 TASK-01 摘要确认结构）。
2. 在文件中新增以下三个函数，插入位置：现有窗口创建函数之后。

函数规格：

createStageWindow()
  - 尺寸：1100 x 720，minWidth 900，minHeight 600。
  - 普通窗口（有标题栏、有任务栏图标）。
  - loadURL：现有 devURL + '#/stage'（生产同理）。
  - 返回 BrowserWindow 实例。

createAgentWindow()
  - 尺寸：420 x 680，可调整大小。
  - 普通窗口，alwaysOnTop: false（用户可自己置顶）。
  - loadURL：现有 devURL + '#/agent'。
  - 初始隐藏（show: false），通过 IPC 显示。
  - 返回 BrowserWindow 实例。

createCompanionWindow()
  - 尺寸：200 x 320。
  - transparent: true，frame: false，alwaysOnTop: true，skipTaskbar: true。
  - resizable: false。
  - loadURL：现有 devURL + '#/companion'。
  - 复用现有 setIgnoreMouseEvents 逻辑（如已有则直接引用，没有则新增）。
  - 返回 BrowserWindow 实例。

3. 在 app ready 事件中，调用 createStageWindow() 和 createCompanionWindow()。
   AgentWindow 在 ready 时创建但不 show。

4. 注册以下 IPC 频道（使用 ipcMain.handle）：
   - 'window:open-agent'   → agentWindow.show()
   - 'window:close-agent'  → agentWindow.hide()
   - 'window:open-stage'   → stageWindow.focus() 或重新创建
   - 'companion:set-ignore-mouse' (event, ignore: boolean) → setIgnoreMouseEvents

约束：
- 不删除或修改现有任何窗口创建逻辑。
- 不改变现有 IPC 频道名称。
- 如果 loadURL 逻辑与现有结构差异较大，停下来告诉我，不要自行重构。

验收命令：
  cd apps/desktop && npm run typecheck
  确认 main.cjs 中三个函数存在，git diff 只包含新增内容。
```

---

### TASK-04 — 在 App.tsx 新增路由分发逻辑

```
目标：根据 URL hash 渲染不同的顶层视图，不改动现有视图逻辑。

执行步骤：
1. 读取 apps/desktop/src/App.tsx 当前全文。
2. 在文件顶部新增路由读取逻辑：
   const mode = window.location.hash.replace('#/', '') || 'stage'
   // 可能的值：'stage' | 'agent' | 'companion'

3. 根据 mode 渲染对应组件：
   - 'stage'     → <StageView />
   - 'agent'     → <AgentWorkspaceView />
   - 'companion' → <CompanionView />
   - 其他        → 保持现有默认渲染逻辑不变

4. 新建以下三个占位文件（每个文件只包含最简单的占位内容）：

apps/desktop/src/views/StageView.tsx
  export default function StageView() {
    return <div style={{padding: 24, color: '#333'}}>主舞台 — 占位中</div>
  }

apps/desktop/src/views/AgentWorkspaceView.tsx
  export default function AgentWorkspaceView() {
    return <div style={{padding: 24, color: '#333'}}>Agent 工作空间 — 占位中</div>
  }

apps/desktop/src/views/CompanionView.tsx
  export default function CompanionView() {
    return <div style={{padding: 24, color: '#333', background: 'transparent'}}>桌面陪伴体 — 占位中</div>
  }

约束：
- 不删除或移动现有组件。
- 如果 App.tsx 当前有复杂的 Provider 或 Context 包裹，保持原有包裹结构，只在最内层做路由分发。
- 占位组件不引入任何新依赖。

验收命令：
  cd apps/desktop && npm run typecheck
  cd apps/desktop && npm run build
```

---

### TASK-05 — SPRINT 1 集成验收

```
目标：确认三个窗口能在开发模式下正常打开。

执行步骤：
1. 运行 cd apps/desktop && npm run typecheck，确认零错误。
2. 运行 cd apps/desktop && npm run build，确认构建成功。
3. 输出以下检查清单的状态（逐条确认，不能跳过）：

检查清单：
[ ] main.cjs 中存在 createStageWindow、createAgentWindow、createCompanionWindow 三个函数。
[ ] IPC 频道 window:open-agent / window:close-agent / window:open-stage / companion:set-ignore-mouse 已注册。
[ ] App.tsx 根据 hash 路由到三个 View 组件。
[ ] 三个 View 文件存在于 apps/desktop/src/views/。
[ ] typecheck 零报错。
[ ] build 成功。

如果任何一项不通过，停下来列出具体问题，不要自动修复后继续。
```

---

## SPRINT 2：主舞台 UI

### TASK-06 — 读取现有聊天和 Live2D 组件

```
目标：摘要现有聊天入口和 Live2D 组件的接口，为主舞台组合做准备。

执行步骤：
1. 列出 apps/desktop/src/components/ 下所有文件和目录。
2. 找到现有聊天相关组件（关键词：chat、message、input），读取并摘要其 props 接口。
3. 找到现有 Live2D 相关组件，读取并摘要：
   a. 组件名和文件路径。
   b. 需要哪些 props。
   c. 是否有副作用（加载 SDK、全局变量等）。
4. 读取 apps/desktop/src/services/ 下所有文件，列出可用的 API 调用方法名称和参数。
5. 输出摘要，不修改任何文件。

验收：输出摘要，git status 干净。
```

---

### TASK-07 — 新增主题变量文件

```
目标：建立视觉 token 文件，供后续所有组件引用。

执行步骤：
新建 apps/desktop/src/styles/theme.css，内容如下（不增不减）：

:root {
  /* 背景 */
  --bg-stage: linear-gradient(135deg, #fdf6f0 0%, #fce8e8 50%, #f0e8fd 100%);
  --bg-companion: transparent;
  --bg-agent: #f8f5ff;

  /* 卡片 */
  --card-bg: rgba(255, 255, 255, 0.65);
  --card-blur: blur(16px);
  --card-radius: 20px;
  --card-border: 1px solid rgba(255, 255, 255, 0.8);
  --card-shadow: 0 8px 32px rgba(180, 140, 160, 0.12);

  /* 主色 */
  --color-primary: #f4a0b5;      /* 粉色：陪伴 */
  --color-success: #7ec8a0;      /* 绿色：运行/通过 */
  --color-active: #f4a96a;       /* 橙色：活力/进行中 */
  --color-text: #3d2c35;
  --color-text-soft: #8a7080;

  /* 间距 */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 40px;

  /* 字体 */
  --font-sans: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif;
}

新建 apps/desktop/src/styles/glass.css，内容如下：

.glass-card {
  background: var(--card-bg);
  backdrop-filter: var(--card-blur);
  -webkit-backdrop-filter: var(--card-blur);
  border-radius: var(--card-radius);
  border: var(--card-border);
  box-shadow: var(--card-shadow);
}

.glass-pill {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.9);
  padding: 4px 12px;
  font-size: 12px;
  color: var(--color-text-soft);
}

在现有样式入口文件（通常是 index.css 或 App.css）中追加：
@import './styles/theme.css';
@import './styles/glass.css';

约束：
- 不修改现有样式规则，只追加 import。
- 不引入任何新 npm 包。

验收命令：
  cd apps/desktop && npm run build
```

---

### TASK-08 — 实现主舞台骨架布局

```
目标：用真实布局替换 StageView 的占位内容，暂用静态 mock 数据。

执行步骤：
1. 读取 TASK-06 的摘要，确认 Live2D 组件名称和 props。
2. 读取 apps/desktop/src/views/StageView.tsx 当前内容。
3. 用以下结构替换 StageView.tsx（使用 CSS Grid/Flex，不引入 UI 库）：

布局结构（从上到下）：
┌──────────────────────────────────────────┐
│  TopBar（状态条）                         │  高度 44px
├────────┬─────────────────┬───────────────┤
│        │                 │               │
│ Left   │   Live2D        │  Right        │
│ Card   │   （居中）       │  Card         │  flex-1
│        │                 │               │
├────────┴─────────────────┴───────────────┤
│  ChatInput + BottomNav                   │  高度 auto
└──────────────────────────────────────────┘

各区域内容（全部用静态 mock，加 // TODO: 接真实接口 注释）：

TopBar：
  - 左：角色名（mock："小艾"）、情绪标签（mock："开心 😊"）
  - 右：桌面在线状态（mock：绿点 + "在线"）、当前时间（new Date()）

LeftCard（.glass-card 样式）：
  - 今日日期和问候语（mock）
  - 身体状态进度条（mock：精力 80%、心情 90%）
  - 记忆数量（mock：42 条）
  - 今日互动（mock：7 次）

Live2D 区域：
  - 如果 TASK-06 找到了现有 Live2D 组件，直接引用，保持原有 props。
  - 如果没有，放一个 200x300 的圆角占位 div，加注释 // TODO: 替换为 Live2D 组件。

RightCard（.glass-card 样式）：
  - 标题"当前场景"（mock 文字）
  - 快捷动作按钮列表（mock：查天气、记录日记、打开 Agent）
  - "打开 Agent 工作空间"按钮，点击时调用 window.electronAPI?.openAgent?.() 或 ipcRenderer.invoke('window:open-agent')

ChatInput 区域：
  - 文本输入框（受控组件，placeholder："和小艾说点什么..."）
  - 发送按钮
  - 语音入口占位图标（disabled，加 // TODO 注释）
  - 发送逻辑：调用现有聊天 service（从 TASK-06 摘要中确认方法名），如果不确定，停下来告诉我。

BottomNav：
  - 6 个 tab：陪伴 / 对话 / 记忆 / 世界 / Agent / 设置
  - 当前只有"陪伴"高亮，其余 tab 点击时 console.log 对应名称即可，加 // TODO 注释。

约束：
- 不引入任何新 npm 包。
- 所有 mock 数据必须加 // TODO: 接真实接口 注释。
- Live2D 组件的现有 props 不做任何改动。
- 如果 electronAPI 暴露方式不确定，停下来告诉我，不要猜测。

验收命令：
  cd apps/desktop && npm run typecheck
  cd apps/desktop && npm run build
```

---

### TASK-09 — 主舞台视觉打磨

```
目标：给 StageView 应用 theme.css / glass.css 变量，达到玻璃拟态效果。

执行步骤：
1. 读取 apps/desktop/src/views/StageView.tsx 当前内容。
2. 为各区域补充样式（使用 CSS modules 或 inline style，与现有项目保持一致）：

背景：整个 StageView 容器使用 background: var(--bg-stage)，全屏覆盖。
TopBar：height 44px，padding 0 16px，flex，align-items center，
        背景 rgba(255,255,255,0.4)，backdrop-filter blur(8px)。
LeftCard / RightCard：应用 .glass-card 类，宽度固定 220px，padding 20px。
Live2D 区域：flex 1，display flex，justify-content center，align-items flex-end。
ChatInput：背景 rgba(255,255,255,0.7)，border-radius 16px，
           padding 12px 16px，margin 12px 16px，
           input 无边框、背景透明、font-family var(--font-sans)。
BottomNav：height 56px，display flex，justify-content space-around，
           background rgba(255,255,255,0.8)，backdrop-filter blur(12px)。
           激活 tab 用 color: var(--color-primary)，未激活用 var(--color-text-soft)。

约束：
- 不改动任何组件逻辑，只加样式。
- 样式方案与现有项目保持一致（如项目用 CSS modules，则用 CSS modules；如用 styled-components，则用 styled-components）。

验收命令：
  cd apps/desktop && npm run typecheck
  cd apps/desktop && npm run build
  cd apps/desktop && npm run live2d:check:public   （如果改动了 Live2D 相关文件）
```

---

## SPRINT 3：Agent 工作空间

### TASK-10 — 读取现有任务和 Agent 接口

```
目标：摘要后端任务/Agent 相关接口，为工作空间 UI 准备数据契约。

执行步骤：
1. 列出 apps/backend/app/api/ 下所有文件，找到任务相关路由。
2. 读取任务相关路由文件，列出：
   a. 端点路径、HTTP 方法、请求参数、响应结构。
   b. 是否有步骤状态、审批/拒绝、执行日志相关端点。
3. 读取 apps/backend/app/agents/runtime.py，列出：
   a. 高影响动作的定义和触发条件。
   b. 提案/确认流程的当前实现方式。
4. 读取 apps/desktop/src/services/ 下已有的任务相关封装。
5. 输出摘要，标明"现有能力"和"需要新增"的接口清单，不修改任何文件。

验收：输出摘要，git status 干净。
```

---

### TASK-11 — 实现 AgentWorkspaceView 骨架

```
目标：用真实布局替换 AgentWorkspaceView 的占位内容。

前提：先阅读 TASK-10 的摘要，确认可用的数据结构。

执行步骤：
1. 读取 apps/desktop/src/views/AgentWorkspaceView.tsx 当前内容。
2. 用以下结构替换（窄窗口，宽度适配 420px）：

布局（从上到下）：
┌─────────────────────────────┐
│  Header：当前任务名称 + 状态  │  56px
├─────────────────────────────┤
│  TaskCard（当前任务详情）     │  auto
├─────────────────────────────┤
│  StepList（工具步骤列表）     │  flex-1，可滚动
├─────────────────────────────┤
│  ApprovalBar（审批操作栏）   │  条件渲染
├─────────────────────────────┤
│  LogPanel（执行日志）        │  固定高度，可滚动
└─────────────────────────────┘

各区域规格：

TaskCard（.glass-card）：
  - 任务名称（粗体）
  - 任务描述（一行文字）
  - 状态标签：进行中（橙色）/ 等待审批（粉色）/ 完成（绿色）/ 失败（红色）
  - 数据来源：// TODO: 接 TASK-10 摘要中确认的任务接口

StepList：
  - 每个步骤显示：序号、工具名称、状态图标、耗时
  - 状态图标：✓ 完成 / ⏳ 进行中 / ✕ 失败 / ○ 待执行
  - 数据来源：// TODO: 接步骤状态接口

ApprovalBar（仅当 task.needsApproval === true 时渲染）：
  - 说明文字："即将执行：[动作描述]"
  - 拒绝按钮（红色边框）
  - 批准按钮（绿色填充）
  - 按钮点击：调用现有 service 中对应方法，如无则加 // TODO

LogPanel：
  - 高度 160px，overflow-y auto
  - 每行日志：时间戳 + 内容
  - 背景 rgba(0,0,0,0.04)，monospace 字体，字号 12px
  - 数据来源：// TODO: 接日志接口

约束：
- 所有 mock 数据加 // TODO 注释。
- 不实现轮询，数据获取留 TODO，本任务只做 UI 结构。
- 不调用任何后端接口（留给 TASK-12）。

验收命令：
  cd apps/desktop && npm run typecheck
  cd apps/desktop && npm run build
```

---

### TASK-12 — 接入 Agent 任务数据

```
目标：将 AgentWorkspaceView 的 mock 数据替换为真实接口调用。

前提：先阅读 TASK-10 的摘要，确认接口路径和响应结构。

执行步骤：
1. 读取 apps/desktop/src/services/ 下现有封装，确认调用约定（ApiClient / ipcRenderer）。
2. 在现有 service 文件中新增（不新建文件，追加到最合适的现有文件）：

   fetchCurrentTask(): Promise<Task>         → GET /api/tasks/current（或 TASK-10 确认的路径）
   fetchTaskSteps(taskId): Promise<Step[]>   → GET /api/tasks/:id/steps
   fetchTaskLogs(taskId): Promise<Log[]>     → GET /api/tasks/:id/logs
   approveTask(taskId): Promise<void>        → POST /api/tasks/:id/approve
   rejectTask(taskId): Promise<void>         → POST /api/tasks/:id/reject

   如果 TASK-10 摘要中接口路径不同，以摘要为准。
   如果某个接口后端不存在，停下来告诉我，不要自行创建后端代码。

3. 在 AgentWorkspaceView.tsx 中：
   - 用 useEffect + useState 替换 mock 数据，调用上述 service 方法。
   - 每 5 秒轮询一次 fetchCurrentTask 和 fetchTaskSteps。
   - 审批/拒绝按钮点击时调用对应方法，完成后刷新任务状态。
   - 所有请求加 loading 和 error 状态处理。

约束：
- 不修改后端代码（如后端接口不足，在此任务中停下，等 TASK-12b 补后端）。
- bearer token 从现有 ApiClient 封装中获取，不在组件里硬编码。

验收命令：
  cd apps/desktop && npm run typecheck
  cd apps/desktop && npm run build
  cd apps/backend && python -m pytest
```

---

## SPRINT 4：桌面陪伴体

### TASK-13 — 实现 CompanionView UI

```
目标：实现透明桌面陪伴体的 React 界面。

执行步骤：
1. 读取 apps/desktop/src/views/CompanionView.tsx 当前内容。
2. 读取 TASK-06 摘要中的 Live2D 组件信息。
3. 用以下结构替换 CompanionView.tsx：

布局（200x320px，透明背景）：
┌───────────────────┐
│   Live2D 角色      │  flex-1
│                   │
├───────────────────┤
│   气泡文字         │  条件渲染，绝对定位在角色右上角
├───────────────────┤
│   快捷按钮行       │  4 个小圆形按钮，固定在底部
└───────────────────┘

快捷按钮（从左到右）：
  - 🏠 打开主舞台：调用 ipcRenderer.invoke('window:open-stage')
  - ❤️ 互动：console.log('互动') + // TODO
  - 🤖 任务：调用 ipcRenderer.invoke('window:open-agent')
  - ⋯ 更多：console.log('更多') + // TODO

气泡（bubble）：
  - 绝对定位，右上角。
  - .glass-pill 样式。
  - 从 props 或全局状态读取 message，为空时不渲染。
  - // TODO: 接陪伴状态聚合接口。

整体样式：
  - background: transparent。
  - 无内边距，无边框。
  - 整个窗口可拖拽（-webkit-app-region: drag），快捷按钮区域 -webkit-app-region: no-drag。

约束：
- Live2D 组件如有轻量配置选项，加注释说明但不修改，留给 TASK-14 处理。
- ipcRenderer 调用方式与现有项目一致（preload 暴露 / 直接 require）。

验收命令：
  cd apps/desktop && npm run typecheck
  cd apps/desktop && npm run build
```

---

### TASK-14 — 确认 Live2D 在两个窗口的复用策略

```
目标：调研 Live2D 组件在主舞台和陪伴体同时运行时的性能表现，输出结论。

执行步骤：
1. 读取现有 Live2D 组件代码，确认：
   a. SDK 加载方式（script tag / import / CDN）。
   b. 是否有全局单例限制。
   c. 是否有性能配置参数（帧率、分辨率、模型质量）。
2. 输出以下三个问题的答案：
   a. 两个窗口同时运行 Live2D 是否会冲突？
   b. 陪伴体是否需要降级配置（如降帧率）？
   c. 推荐的复用方案是什么？

3. 根据结论，如果需要为陪伴体创建轻量配置，修改 CompanionView.tsx 中的 Live2D 引用，
   传入降级 props（如 fps: 15, quality: 'low'）。
   如果组件不支持这类 props，加 // TODO 注释，不强行修改 Live2D 组件内部。

验收：
  cd apps/desktop && npm run live2d:check:public
  cd apps/desktop && npm run live2d:sdk:check
```

---

### TASK-15 — main.cjs 补全 companion 窗口行为

```
目标：完善 createCompanionWindow 的拖拽、穿透、位置持久化。

执行步骤：
1. 读取 apps/desktop/electron/main.cjs 当前全文（从 TASK-03 改动后的版本）。
2. 在 createCompanionWindow 函数中补充：

位置持久化：
  - 使用 electron-store 或 app.getPath('userData') + JSON 文件记录窗口位置。
  - 窗口创建时读取上次位置，如无则默认右下角（screen.getPrimaryDisplay().workAreaSize）。
  - 窗口 moved 事件触发时保存新位置。
  - 如果现有项目已有 settings service，使用已有方案，不另起炉灶。

穿透 IPC 完善：
  'companion:set-ignore-mouse' 已在 TASK-03 注册，确认实现为：
  companionWindow.setIgnoreMouseEvents(ignore, { forward: true })

3. 确认 companion 窗口在主窗口关闭时的行为（跟随关闭 or 独立存活），
   与现有应用生命周期保持一致，不改变现有 window-all-closed 逻辑。

约束：
- 不引入新 npm 包，除非项目已依赖 electron-store。
- 不改变现有托盘行为。

验收命令：
  cd apps/desktop && npm run typecheck
  cd apps/desktop && npm run build
```

---

## SPRINT 5：最终验收

### TASK-16 — 全量验收检查

```
目标：确认所有功能通过验收，输出完整检查报告。

执行步骤，逐条运行并记录结果：

1. cd apps/desktop && npm run typecheck
2. cd apps/desktop && npm run build
3. cd apps/desktop && npm run package:check
4. cd apps/desktop && npm run live2d:check:public
5. cd apps/desktop && npm run live2d:sdk:check
6. cd apps/backend && python -m pytest

逐条确认以下检查项（每项输出 ✅ 通过 / ❌ 失败 + 原因）：

窗口与路由：
[ ] /#/stage 渲染 StageView
[ ] /#/agent 渲染 AgentWorkspaceView
[ ] /#/companion 渲染 CompanionView
[ ] IPC window:open-agent 能打开 Agent 窗口
[ ] IPC window:open-stage 能聚焦主舞台
[ ] companion:set-ignore-mouse 能切换穿透

主舞台：
[ ] TopBar 显示时间（实时更新）
[ ] LeftCard 显示 mock 状态数据（有 TODO 注释）
[ ] Live2D 区域正常渲染
[ ] ChatInput 能发送消息（调用现有聊天 service）
[ ] BottomNav 6 个 tab 正常显示，陪伴 tab 高亮

Agent 工作空间：
[ ] 显示任务卡、步骤列表、执行日志
[ ] 有审批/拒绝按钮（needsApproval 为 true 时显示）
[ ] bearer token 未硬编码在组件中

桌面陪伴体：
[ ] 窗口透明无边框
[ ] 快捷按钮能触发 IPC
[ ] 可拖拽移动

代码质量：
[ ] 所有 mock 数据有 // TODO 注释
[ ] 没有临时 fetch 散落在 React 组件中
[ ] 没有引入计划外的新 npm 包

如有任何 ❌，列出具体错误信息，不自动修复，等待人工确认后再处理。
```

---

## 附录：常用约束提示词（每次任务可附加）

```
【通用约束，每次执行任务前附加】
1. 先读文件，再修改。不要凭空生成代码。
2. 如果现有代码与任务描述冲突，停下来告诉我，不要自行决策。
3. 不引入计划外的新 npm 包。如需引入，先列出并等待确认。
4. 不删除或重构现有功能代码，只新增。
5. 所有 mock / 占位内容加 // TODO: 描述 注释。
6. 每个任务结束时运行 typecheck 和 build，确认零报错再结束。
7. 不确定的地方宁可停下来问，不要猜测后继续。
```
