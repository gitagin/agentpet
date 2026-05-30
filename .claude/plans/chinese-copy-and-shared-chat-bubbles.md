# 中文文案与跨窗口聊天气泡修复计划

## 目标

解决用户提出的三项问题：

1. 将项目中面向用户的英文提示替换为中文，优先覆盖桌面端可见 UI、错误提示、窗口标题/眉标、诊断标签。
2. 对话窗口发送消息时，pet 桌宠窗口也要显示“思考中”和 Agent 回复气泡。
3. 陪伴窗口底部输入框要真正接入与对话窗口相同的对话能力；输入后陪伴窗口 Live2D 模型旁显示气泡，思考中显示“思考中”，Agent 返回内容继续显示在气泡中。同时 pet 窗口与陪伴窗口的 Live2D 模型都需要显示气泡。

## 当前问题定位

- [apps/desktop/src/App.tsx](../../apps/desktop/src/App.tsx) 中 `messages`、`streaming`、`conversationId`、`petChat.bubble` 都是单个 renderer 进程内存状态。
- Electron 多窗口分别加载独立 React 实例：pet、chat、stage 是不同 BrowserWindow，因此 chat 窗口内发送时只更新 chat 窗口自己的 `petChat.bubble`，pet 窗口不会收到。
- [apps/desktop/src/views/StageView.tsx](../../apps/desktop/src/views/StageView.tsx) 的输入框会调用 `onSendChat`，但 StageView 没有渲染聊天气泡/消息输出，并且状态也不会同步到 pet/chat 窗口，所以看起来像“摆设”。
- [apps/desktop/src/features/chat/PetChatOverlay.tsx](../../apps/desktop/src/features/chat/PetChatOverlay.tsx) 已有输入相关 props 和 CSS，但组件实际只渲染 bubble，没有渲染输入 dock。
- 可见英文集中在 `ChatWindowView`、`MemoryWindowView`、`WorldWindowView`、`SettingsWindowView`、`Live2DStage`、`WikiWorkflowPanel`、`apiClient/sse/proxy` 等处。

## 实施方案

### 1. 新增跨窗口聊天状态 IPC

在 Electron 主进程维护轻量共享聊天快照，而不是把聊天请求逻辑迁到主进程，保持改动最小且可回滚。

修改文件：

- [apps/desktop/electron/windows.js](../../apps/desktop/electron/windows.js)
  - 增加 `broadcastChatState(state, sender?)`，向 pet、stage、control、agent、所有 feature windows 广播 `agent-pet:chat-state-changed`。
  - 增加 `requestChatSubmit(text, sender?)`，广播 `agent-pet:chat-submit-requested` 给 pet 窗口优先处理；如果 pet 不存在/未加载，则广播给 stage 或 chat 窗口兜底。
  - 增加 `requestChatStop(sender?)`，广播停止请求。
  - 导出上述方法。
- [apps/desktop/electron/ipc.js](../../apps/desktop/electron/ipc.js)
  - 注册 `agent-pet:chat-state-update`、`agent-pet:chat-submit`、`agent-pet:chat-stop`。
- [apps/desktop/electron/preload.cjs](../../apps/desktop/electron/preload.cjs)
  - 暴露 `updateChatState`、`submitSharedChat`、`stopSharedChat`、`onChatStateChanged`、`onChatSubmitRequested`、`onChatStopRequested`。
- [apps/desktop/src/types.ts](../../apps/desktop/src/types.ts)
  - 增加共享聊天快照类型与 `window.agentDesktop` 方法声明。

设计原则：

- 真实请求仍由 renderer 的现有 `sendChatText` 执行，复用已有 `api.startChat`、SSE、`applyStreamEvent` 和气泡分页逻辑。
- pet 窗口作为优先聊天执行者，这样对话窗口/陪伴窗口发起的消息天然能让 pet 气泡实时更新。
- 执行者每次 `messages`、`streaming`、`conversationId`、`petChat.bubble` 变化后广播快照；其他窗口接收后只展示，不重复请求后端，避免双发。

### 2. App 接入共享聊天执行/展示

修改 [apps/desktop/src/App.tsx](../../apps/desktop/src/App.tsx)：

- 增加 `sharedChatState` 本地状态，用于非执行窗口接收共享气泡/消息。
- 在 `messages`、`streaming`、`conversationId`、`petChat.bubble` 变化时调用 `window.agentDesktop.updateChatState(...)`。
- 订阅 `onChatStateChanged`：
  - 如果当前窗口不是执行者，使用共享 `messages/streaming/bubble` 显示。
  - 避免用过期快照覆盖当前执行窗口自己的状态。
- 订阅 `onChatSubmitRequested`：pet 窗口优先调用现有 `sendChatText(text, noop)`；如果 pet 不可用则 stage/chat 兜底。
- 修改 ChatWindow 和 Stage 的发送逻辑：Electron 多窗口下调用 `submitSharedChat(text)`，本地立即清空输入；没有 Electron bridge 时保留直接 `sendChatText`。
- 修改停止按钮：Electron 多窗口下调用 `stopSharedChat()`，执行窗口收到后调用现有 `stopStreaming()`。
- `recentControlMessages` 和 `streaming` 展示值改为优先使用共享快照，保证对话窗口能看到 pet/stage 发起的同一段对话。

### 3. 陪伴窗口显示 Live2D 气泡并可对话

修改 [apps/desktop/src/views/StageView.tsx](../../apps/desktop/src/views/StageView.tsx)：

- 扩展 props，接收 `bubble`、`onAdvancePage`、`onPausePaging`、`onResumePaging`、`onStopStreaming`。
- 在 Live2D 模型区域上方/侧上方渲染与 pet 同源的气泡 UI（可复用 `PetChatOverlay` 或抽出共享 `ChatBubbleOverlay`）。
- 输入提交时：
  - 有连接、非 streaming、非空才发送。
  - streaming 时显示“停止”或禁用发送，状态文案用中文。
- 保持底部输入框样式，但让提交路径走共享聊天。

### 4. 修复 pet 窗口输入 dock

修改 [apps/desktop/src/features/chat/PetChatOverlay.tsx](../../apps/desktop/src/features/chat/PetChatOverlay.tsx)：

- 恢复渲染 `inputVisible` 对应的 `.pet-input-dock` 表单。
- 支持中文 placeholder：连接可用时“和桌宠说点什么...”，未连接时“正在等待本地助手连接...”。
- streaming 时按钮显示停止/发送图标或中文 aria-label，触发 `onStopStreaming`。
- 确保表单点击/指针事件 `stopPropagation`，不影响桌宠拖动。

同时在 [apps/desktop/src/App.tsx](../../apps/desktop/src/App.tsx) 中：

- pet 右键菜单“对话”按钮优先 `petChat.showInput()` 或打开聊天窗口（二选一：建议显示输入 dock，同时保留双击打开陪伴窗口）。
- `sendPetMessage` 仍复用 `sendChatText`，但也广播共享状态。

### 5. 中文化用户可见英文

优先修改：

- [apps/desktop/src/views/ChatWindowView.tsx](../../apps/desktop/src/views/ChatWindowView.tsx)：`Agent Pet` -> `桌面助手`。
- [apps/desktop/src/views/MemoryWindowView.tsx](../../apps/desktop/src/views/MemoryWindowView.tsx)：`Memory` -> `记忆`。
- [apps/desktop/src/views/WorldWindowView.tsx](../../apps/desktop/src/views/WorldWindowView.tsx)：`World` -> `世界`。
- [apps/desktop/src/views/SettingsWindowView.tsx](../../apps/desktop/src/views/SettingsWindowView.tsx)：`Settings` -> `设置`。
- [apps/desktop/src/components/Live2DStage.tsx](../../apps/desktop/src/components/Live2DStage.tsx)：
  - `Manifest URL` -> `模型清单地址`
  - `Runtime 状态` -> `运行时状态`
  - `Manifest` -> `模型清单`
  - `Runtime` -> `运行时`
  - `MOC` -> `模型文件`
  - `Live2D runtime canvas 宿主区域` -> `Live2D 运行时画布区域`
  - `CSS 回退展示壳` -> `样式回退展示壳`
  - `Cubism runtime/WebGL canvas/dist` 等保留专有名词，但中文化整句。
- [apps/desktop/src/features/wiki/WikiWorkflowPanel.tsx](../../apps/desktop/src/features/wiki/WikiWorkflowPanel.tsx)：用户可见 `Wiki API`、`Companion` 改为“资料库接口”“陪伴上下文”等。
- [apps/desktop/src/services/apiClient.ts](../../apps/desktop/src/services/apiClient.ts)、[apps/desktop/src/services/sse.ts](../../apps/desktop/src/services/sse.ts)、[apps/desktop/electron/proxy.js](../../apps/desktop/electron/proxy.js)：将可能外显的英文 Error message 改为中文。

不把 TypeScript 类型名、内部枚举值、provider 名（如 OpenAI/openai-compatible/API Key，如为模型供应商/字段名）强行改掉；若在 UI 中作为说明句出现，会改成中文说明加保留专有名词。

### 6. 验证

运行桌面端现有门禁：

- `npm run typecheck`
- `npm run build`

如时间允许补充/更新针对 App、StageView 或 PetChatOverlay 的组件测试，验证：

- StageView 输入提交调用共享发送。
- pet overlay 能显示输入 dock 和 bubble。
- ChatWindow 接收共享消息后显示最近对话。

## 风险与取舍

- 这是最小侵入方案：不迁移完整聊天流到 Electron 主进程，只做状态/请求广播。优点是复用现有稳定代码；缺点是如果 pet 窗口未加载，需要兜底窗口执行请求。
- 若后续要彻底统一多窗口聊天，建议把聊天流状态放到主进程或后端统一管理；本次先满足用户可见行为。
