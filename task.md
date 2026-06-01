# Agent Pet Product Hardening Task Set

本任务集用于把当前项目从“能用的本地 AI 桌宠”打磨成“用户愿意长期使用的本地 AI 伴随 + 第二大脑”。执行时按任务编号推进；每个任务都必须先阅读相关代码，再做最小必要改动，并在回复中列出实际运行的命令和结果。

## Product Thesis

用户选择本产品的原因不是模型比 ChatGPT 更强，而是它能长期常驻桌面、理解用户、可信地记忆、自动整理，并把所有重要信息沉淀为用户可查看、可迁移、可撤销的本地资产。

核心护城河：

1. 记忆可信：用户知道它记了什么、从哪里来、为什么记、如何撤销。
2. 本地资产：日记、任务、Wiki、长期记忆能落到本地 Markdown/Vault，不被黑盒锁定。
3. 低摩擦陪伴：桌宠是日常入口，随口聊天也能沉淀价值。
4. 长期复利：7 天、30 天、90 天后，用户能看到自己累积出的个人知识和生活/工作轨迹。
5. 隐私可控：敏感内容不进普通记忆；高风险操作必须确认。

## Global Execution Rules

- 不要修改 `progress.md`。
- 不要修改 `apps/desktop/node_modules/`、`apps/desktop/dist/`、`apps/desktop/release/`、`apps/backend/pytest-of-ASUS/`、`.tmp/`、`.idea/`、`.codex/`。
- Renderer 不得直接访问 Node、FS、`child_process`；桌面能力必须通过 preload/contextBridge IPC。
- 不得暴露、记录或保存真实 token、API key、Authorization/Bearer header。
- 绑定真实 Vault、删除/移动/批量重写 Markdown、修改 SQLite schema、清理本地状态等高风险操作必须取得用户确认。
- 如果改 schema，必须新增 migration、更新模型/仓库/服务，并增加 pytest。
- 如果改 Electron 权限边界，必须运行 Electron migration 校验。
- 每个任务完成后，至少运行该任务列出的验证命令；无法运行时必须说明原因。

## Priority

优先级从高到低：

1. TASK-00 到 TASK-04：直接决定用户是否信任和继续使用。
2. TASK-05 到 TASK-08：强化桌宠入口、长期留存和迁移成本。
3. TASK-09 到 TASK-10：补齐可验证体验和产品证据。

---

## TASK-00 - 记忆可信中心 v1

**Goal**

让用户清楚看到“AI 记住了什么、为什么记、来源是哪条对话或文件、写到了哪里、是否可撤销”。这是对抗优秀竞品时最重要的独立优势。

**Relevant areas**

- `apps/backend/app/services/agent_actions.py`
- `apps/backend/app/services/chat_auto_memory.py`
- `apps/backend/app/services/long_term_memory.py`
- `apps/backend/app/services/diary_memory.py`
- `apps/backend/app/services/chat_answer_wiki_summary.py`
- `apps/backend/app/api/agent.py`
- `apps/desktop/src/views/MemoryWindowView.tsx`
- `apps/desktop/src/features/chat/handlers/agentActionHandler.ts`
- `apps/desktop/src/services/desktopApi.ts`

**Implementation requirements**

- 后端活动账本必须能表达每次自动整理的核心信息：`action_type`、风险级别、状态、来源消息、目标路径、摘要、是否可撤销、撤销状态。
- 如果现有字段已覆盖，不要重复加字段；优先补 UI 和缺失的序列化。
- 桌面端在“整理/记忆”视图中增加“AI 记住了什么”分组：
  - 长期记忆
  - 聊天日记
  - 结构化日记
  - Wiki 摘要
  - 任务/提醒
  - 被跳过的敏感或低价值内容
- 每条记录显示来源、目标路径、风险级别和状态；可撤销记录提供撤销入口。
- 撤销必须走现有 backend API，不允许 renderer 直接改文件。
- 敏感内容只显示安全摘要，不显示原始凭据。

**Acceptance**

- 用户完成一次普通聊天后，可以在 UI 中看到本次自动整理结果。
- 用户能区分“已写入”“已跳过”“需要确认”“可撤销”。
- 撤销一条可逆 Markdown 写入后，活动账本出现新的撤销记录。

**Validation commands**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_agent_actions.py tests/test_chat_auto_memory_services.py tests/test_api_wiring_mvp.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
Push-Location apps\desktop; node scripts/validate-electron-migration.mjs; Pop-Location
```

---

## TASK-01 - 首次使用 5 分钟 Aha Flow

**Goal**

让新用户在 5 分钟内感受到“它真的开始理解我，并把我说的话整理成资产”。不要让首次体验卡在配置、空页面或技术概念上。

**Relevant areas**

- `apps/desktop/src/App.tsx`
- `apps/desktop/src/views/*`
- `apps/desktop/src/services/desktopApi.ts`
- `apps/desktop/electron/preload.cjs`
- `apps/desktop/electron/main.cjs`
- `apps/backend/app/api/vaults.py`
- `apps/backend/app/api/chat.py`
- `apps/backend/app/services/memory_policy.py`

**Implementation requirements**

- 增加首次使用引导，但不要做营销落地页。
- 引导只问 3 个问题：
  - 最近主要在忙什么？
  - 希望我长期记住什么偏好或背景？
  - 主要想让我帮你做什么：陪聊、日记、任务、知识整理、项目复盘？
- 首次引导状态通过 Electron main/preload 管理，不使用 `localStorage`。
- 如果没有 active Vault，引导必须允许用户先进入聊天；不得偷偷绑定真实 Vault。
- 如果已有 active Vault，用户提交后可以触发一次低风险 profile/diary/memory 自动整理，并在 TASK-00 的可信中心可见。
- 高风险、敏感或低置信内容仍必须进入确认或拒绝流程。

**Acceptance**

- 全新本地状态下，用户能在一个紧凑流程里完成首次设置并开始聊天。
- 首次问答后至少产生一个可见的“已记住/已整理/已跳过”结果。
- 关闭重开应用后，不重复弹出已完成的首次引导。

**Validation commands**

```powershell
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
Push-Location apps\desktop; node --check electron/main.cjs; node --check electron/preload.cjs; node scripts/validate-electron-migration.mjs; Pop-Location
Push-Location apps\backend; python -m pytest -q tests/test_agent_runtime.py tests/test_memory_services.py tests/test_security_hardening_mvp.py; Pop-Location
```

---

## TASK-02 - 对话后自动整理闭环可视化

**Goal**

把“聊天之后自动沉淀价值”做成用户能感知的闭环，而不是后台静默发生。用户每次聊完都要知道这次对话留下了什么。

**Relevant areas**

- `apps/backend/app/api/chat.py`
- `apps/backend/app/services/chat_auto_memory.py`
- `apps/backend/app/services/chat_answer_wiki_summary.py`
- `apps/backend/app/services/agent_actions.py`
- `apps/desktop/src/features/chat/*`
- `apps/desktop/src/components/ChatCitationSummary.tsx`
- `apps/desktop/src/App.tsx`

**Implementation requirements**

- SSE/前端消息中展示“本轮整理结果”：
  - 写入日记
  - 生成结构化记忆
  - 保存长期记忆
  - 生成 Wiki 摘要
  - 创建任务或提醒
  - 因敏感/低价值/重复而跳过
- 不要求每轮都必须写入，但必须解释“没有写入”的原因。
- 整理结果应连接到 TASK-00 可信中心里的活动记录。
- 不得编造引用、分数或模型判断；没有证据时明确显示“未产生可保存内容”。

**Acceptance**

- 普通聊天结束后，消息下方出现简洁的整理摘要。
- 用户可以从摘要跳到对应的活动详情或目标路径。
- 敏感内容不会出现在摘要原文中。

**Validation commands**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_api_wiring_mvp.py tests/test_chat_auto_memory_services.py tests/test_security_hardening_mvp.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
Push-Location apps\desktop; npm run pet:bubble:check; Pop-Location
```

---

## TASK-03 - 7/30/90 天长期回顾

**Goal**

让用户看到“记忆复利”。当用户使用一段时间后，产品主动汇总最近 7 天、30 天、90 天沉淀出的主题、任务、偏好、知识和变化。

**Relevant areas**

- `apps/backend/app/services/diary_memory.py`
- `apps/backend/app/services/long_term_memory.py`
- `apps/backend/app/services/tasks.py`
- `apps/backend/app/services/wiki.py`
- `apps/backend/app/api/*`
- `apps/desktop/src/views/MemoryWindowView.tsx`
- `apps/desktop/src/views/AgentWorkspaceView.tsx`

**Implementation requirements**

- 增加一个 deterministic 的本地回顾服务，优先不用外部模型：
  - 最近高频主题
  - 新增长期记忆
  - 完成/未完成任务
  - 新增 Wiki 页面或摘要
  - 反复出现的用户偏好或关注点
- 提供 7 天、30 天、90 天三个时间窗口。
- 回顾结果必须带来源统计或引用路径，不做无来源推断。
- UI 增加“回顾”入口，展示本地资产累计情况。
- 可以提供“一键生成 Markdown 回顾报告”，但写入 Vault 前必须走现有低风险写入策略和活动账本。

**Acceptance**

- 有历史数据时，回顾页能展示按时间窗口聚合的资产和变化。
- 无历史数据时，显示空态和下一步行动，不报错。
- 生成报告后可在活动账本中追踪和撤销。

**Validation commands**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_memory_services.py tests/test_tasks_services.py tests/test_wiki_services.py tests/test_agent_actions.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
```

---

## TASK-04 - 引用与检索信任升级

**Goal**

让用户相信回答不是凭空编造。每次回答都要清楚表达检索了哪些范围、命中了哪些来源、哪些内容没有依据。

**Relevant areas**

- `apps/backend/app/services/companion_retrieval.py`
- `apps/backend/app/services/retrieval.py`
- `apps/backend/app/agents/nodes/retrieval.py`
- `apps/backend/app/models/memory.py`
- `apps/desktop/src/components/ChatCitationSummary.tsx`
- `apps/desktop/src/features/chat/handlers/statusHandler.ts`

**Implementation requirements**

- 保留并强化现有 citation 透明度：`relative_path`、`snippet`、`source_scope`、`retrieval_mode`。
- UI 增加“检索范围”说明：
  - 长期记忆
  - 每日聊天日记
  - 结构化日记
  - Wiki/知识库
- 如果检索未命中，回答中必须避免假装知道用户历史。
- 不展示伪造分数；如果没有真实 score，不要显示 score。
- 增加针对中文口语问题的检索回归测试。

**Acceptance**

- 用户能看到回答引用了哪个本地文件或记忆来源。
- 无引用时 UI 明确显示“本轮未找到可引用记忆/知识”。
- 后端测试覆盖有命中、无命中、多范围聚合三类情况。

**Validation commands**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_retrieval_fts.py tests/test_agent_runtime.py tests/test_memory_graph_services.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
```

---

## TASK-05 - 桌宠快速捕获入口

**Goal**

让桌宠不只是显示回复，而是成为日常输入入口。用户应该能用最低成本记录想法、任务、偏好、知识片段。

**Relevant areas**

- `apps/desktop/src/App.tsx`
- `apps/desktop/src/services/petBubblePagination.ts`
- `apps/desktop/electron/tray.js`
- `apps/desktop/electron/windows.js`
- `apps/desktop/electron/preload.cjs`
- `apps/desktop/electron/main.cjs`
- `apps/backend/app/api/chat.py`
- `apps/backend/app/services/tasks.py`
- `apps/backend/app/services/memory.py`
- `apps/backend/app/services/wiki.py`

**Implementation requirements**

- 在桌宠输入面板加入模式切换：
  - 聊天
  - 记一下
  - 新任务
  - 整理成 Wiki
  - 今日复盘
- 模式只是生成明确意图，不绕过后端策略。
- 右键菜单或托盘增加快速打开这些入口的命令。
- 所有写入都通过 chat/API/IPC 安全边界完成。
- 紧凑气泡不应因模式标签或长文本破坏 `pet-hitbox.json` 约束。

**Acceptance**

- 用户能从桌宠快速创建任务、记忆或 Wiki 整理请求。
- 高风险内容仍进入确认流程。
- 桌宠气泡分页和点击穿透校验仍通过。

**Validation commands**

```powershell
Push-Location apps\desktop; npm run typecheck; npm test; npm run pet:bubble:check; Pop-Location
Push-Location apps\desktop; node --check electron/main.cjs; node --check electron/preload.cjs; node scripts/validate-electron-migration.mjs; Pop-Location
Push-Location apps\backend; python -m pytest -q tests/test_agent_runtime.py tests/test_tasks_services.py tests/test_wiki_workflows.py; Pop-Location
```

---

## TASK-06 - 记忆纠错、遗忘与导出

**Goal**

让用户有控制感。长期记忆系统必须支持“这条记错了”“不要再用这条”“导出我自己的记忆资产”。

**Relevant areas**

- `apps/backend/app/services/long_term_memory.py`
- `apps/backend/app/services/memory.py`
- `apps/backend/app/services/memory_policy.py`
- `apps/backend/app/api/memory.py`
- `apps/backend/migrations/`
- `apps/desktop/src/views/MemoryWindowView.tsx`
- `apps/desktop/src/services/desktopApi.ts`

**Implementation requirements**

- 提供记忆状态控制：
  - active
  - archived
  - rejected/wrong
  - sensitive_blocked
- 如果当前 schema 不支持，新增 migration 和测试。
- UI 提供“标为不准确”“归档”“复制/导出”操作。
- 删除或批量重写 Vault Markdown 属于高风险，不能默认执行。
- 导出优先生成用户可读 JSON/Markdown 预览；真正写入文件必须走安全路径或用户确认。
- 被归档/错误的记忆不应继续参与默认检索。

**Acceptance**

- 用户能在 UI 中标记一条长期记忆不准确。
- 被标记的记忆不再作为默认聊天上下文。
- 导出内容不包含敏感凭据原文。

**Validation commands**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_memory_services.py tests/test_retrieval_fts.py tests/test_security_hardening_mvp.py tests/test_persistence_mvp.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
```

---

## TASK-07 - 周报/月报 Markdown 资产

**Goal**

把留存从“我还会回来聊天”提升到“这里有我的长期记录和复盘资产”。周报/月报是用户看见长期价值的关键。

**Relevant areas**

- `apps/backend/app/services/diary_memory.py`
- `apps/backend/app/services/tasks.py`
- `apps/backend/app/services/wiki.py`
- `apps/backend/app/services/agent_actions.py`
- `apps/backend/app/api/*`
- `apps/desktop/src/views/MemoryWindowView.tsx`
- `apps/desktop/src/views/AgentWorkspaceView.tsx`

**Implementation requirements**

- 增加手动触发的周报/月报生成能力。
- 报告内容包含：
  - 本周/本月主要主题
  - 重要对话和日记摘要
  - 任务完成与延迟
  - 新增知识页
  - 值得回顾的问题
- 报告必须包含来源链接或相对路径。
- 默认写入 `Wiki/Companion/Reports/` 或既有安全约定路径；路径必须经过 Vault 校验。
- 写入报告必须记录 agent action，并支持可逆写入撤销。

**Acceptance**

- 用户可以从 UI 手动生成周报/月报。
- Markdown 报告包含来源路径和更新时间。
- 报告写入后可在 Obsidian/Vault 中查看。

**Validation commands**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_wiki_services.py tests/test_wiki_workflows.py tests/test_agent_actions.py tests/test_storage_paths.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
```

---

## TASK-08 - 本地资产仪表盘

**Goal**

让用户看到自己已经沉淀了多少资产，从而形成正向留存和迁移成本，但不制造封闭锁定。

**Relevant areas**

- `apps/backend/app/api/*`
- `apps/backend/app/services/diary_memory.py`
- `apps/backend/app/services/long_term_memory.py`
- `apps/backend/app/services/tasks.py`
- `apps/backend/app/services/wiki.py`
- `apps/desktop/src/views/*`
- `apps/desktop/src/App.tsx`

**Implementation requirements**

- 增加本地资产统计：
  - 已记录聊天日记天数
  - 长期记忆数量
  - Wiki 页面数量
  - 任务数量和完成数
  - 最近一次整理时间
  - 可撤销操作数量
- 所有统计都来自本地数据库或 Vault，不上传远程。
- UI 用紧凑工作台方式展示，避免营销页。
- 空状态应引导用户进行一次聊天、记忆或复盘。

**Acceptance**

- 用户能一眼看到自己的本地第二大脑积累情况。
- 没有数据时不报错，并提供清晰下一步入口。
- 不引入远程 telemetry。

**Validation commands**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_api_wiring_mvp.py tests/test_memory_services.py tests/test_tasks_services.py tests/test_wiki_services.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
```

---

## TASK-09 - Obsidian/Vault 可迁移体验

**Goal**

把“本地 Markdown 可迁移”从技术事实变成用户能感知的产品优势。

**Relevant areas**

- `apps/backend/app/storage/*`
- `apps/backend/app/api/vaults.py`
- `apps/backend/app/services/wiki.py`
- `apps/desktop/electron/main.cjs`
- `apps/desktop/electron/preload.cjs`
- `apps/desktop/src/services/desktopApi.ts`
- `apps/desktop/src/views/*`

**Implementation requirements**

- 在 UI 中显示当前 active Vault 的安全摘要：
  - 是否已绑定
  - 根路径只显示必要信息，避免泄露完整敏感路径时可脱敏
  - 最近索引时间
  - Markdown/Wiki/Diary 大致数量
- 提供“打开目标文件/在文件夹中显示”的能力时，必须通过 Electron main IPC，并限制在 active Vault 内。
- 不得允许 renderer 直接打开任意外部 URL 或任意本地路径。
- 提供“导出/备份说明”文案和只读预览；实际批量复制或写备份文件需要用户确认。

**Acceptance**

- 用户能理解自己的数据保存在本地 Vault。
- 用户能从活动记录打开对应 Markdown 文件或所在目录。
- 任意越界路径请求会被拒绝并有测试覆盖。

**Validation commands**

```powershell
Push-Location apps\backend; python -m pytest -q tests/test_storage_paths.py tests/test_security_hardening_mvp.py tests/test_api_wiring_mvp.py; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; node scripts/validate-electron-migration.mjs; Pop-Location
```

---

## TASK-10 - 产品留存 Smoke 脚本

**Goal**

把核心产品价值做成可复跑的验收脚本：首次使用、聊天、引用、自动整理、活动账本、撤销、回顾。

**Relevant areas**

- `scripts/`
- `apps/backend/tests/`
- `apps/desktop/scripts/`
- `docs/runbook.md`
- `docs/v0.1-validation.md`

**Implementation requirements**

- 增加或扩展一个本地 smoke 脚本，使用隔离临时目录，不碰用户真实 Vault。
- 脚本至少验证：
  - sidecar health
  - 初始化隔离 Vault
  - 创建一条可检索 Markdown
  - 发起一次 chat
  - 返回 token/done/citation
  - 自动整理产生 agent action
  - 可逆 action 能撤销
  - 回顾/资产统计 API 可用
- 文档写清楚如何运行，不要求用户配置 live provider。
- 如果某项能力还没实现，脚本应明确标记 skipped/pending，不假装通过。

**Acceptance**

- 一条命令可以跑通本地核心价值链路。
- 脚本不会修改用户真实 Vault。
- 失败信息能定位到具体阶段。

**Validation commands**

```powershell
.\scripts\runbook-smoke.ps1 -Port 8766
.\scripts\check-mvp-acceptance-gap.ps1
Push-Location apps\backend; python -m pytest -q; Pop-Location
Push-Location apps\desktop; npm run typecheck; npm test; Pop-Location
```

---

## Definition of Done Per Task

每个任务完成时必须满足：

- 相关代码已实现，或明确说明该任务只产生文档/脚本。
- 安全边界没有降低。
- 低风险自动整理仍可追踪；高风险操作仍需确认。
- 相关自动化验证已运行并通过，或清楚说明为什么无法运行。
- 回复中列出实际执行的命令和结果。
- 不把 `docs/mvp-acceptance-coverage.md` 中的状态改成没有证据支持的 `Covered`。
