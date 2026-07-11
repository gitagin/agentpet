# Agent Pet 求职作品集改造任务指令集（AI Coordinator 可执行版）

> 目标：把当前 Agent Pet 改造成可以放入简历、作品集和面试现场演示的主项目。
> 工作目录：E:\agentproject
> Shell：Windows PowerShell
> 历史任务：TASK-0001 至 TASK-0506 的可用状态摘要保留在 progress.md；旧任务指令和逐任务 Markdown 快照已在文档收敛时删除。本文件从 TASK-0601 接续，不把历史文字当作当前验证。
> 当前状态：本文件只是计划与调度依据。除非某项任务完成全部 DoD 和指定证据，否则不得标记 Completed 或 Covered。

---

## 1. 最终成功标准

面试官应能在十分钟内验证以下事实，而不是只能听到技术栈名词：

1. 项目确实使用 LangGraph 编排语义分析、检索、动作规划、回答和后台反思。
2. 开启协商后确实进入有界 supervisor/Agent 链；关闭时保留稳定普通图。
3. 本地记忆问题可以返回真实 citation；空检索不会伪造本地事实。
4. 自然语言可以创建任务或记忆；高风险动作在确认前绝不修改目标。
5. Electron Renderer 不接触 Node、FS、session token 或 provider credential。
6. 首页、聊天、记忆、计划、设置在常见 Windows 尺寸下无遮挡、无双主滚动。
7. 两条黄金链拥有自动化、真实路径和人工证据。
8. README、CASE_STUDY、架构图、视频和简历描述中的每个声明都能链接到代码或验证记录。

### 两条黄金链

黄金链 A：

~~~text
用户提问
→ semantic analysis
→ supervisor
→ retrieval（SQLite FTS / Markdown Vault）
→ evidence review
→ chat synthesis
→ citation + answer + done
~~~

黄金链 B：

~~~text
用户提出提醒或记忆请求
→ semantic analysis
→ deterministic action plan
→ risk policy
→ 自动执行或等待确认
→ task / memory receipt
→ agent_actions ledger
→ 可撤销或明确拒绝
~~~

---

## 2. 事实来源与执行前必读

每次执行任务前必须按顺序读取：

1. 根 AGENTS.md；
2. 本 task.md；
3. 锐评.md；
4. docs/verification-policy.md；
5. docs/current-specification.md；
6. 当前任务涉及的源代码与测试；
7. 对应 output/verification/task-XXXX/ 中已有证据。

优先级始终是：

~~~text
当前代码与 migration
> 当前测试和校验脚本
> 当前验收矩阵
> 当前规格
> progress.md
> 历史文档与旧截图
~~~

不得用历史测试通过、旧截图或 progress.md 代替当前验证。

---

## 3. 当前已知基线，执行时必须重新核对

- 普通 LangGraph 主图真实存在并通过 astream 输出事件。
- build_negotiation_graph 存在，但当前主运行时未接通。
- _should_use_negotiation 当前固定返回 False。
- 当前更准确的公开说法是“LangGraph 多角色工作流”，不是“多个自治 Agent 已经反复协商”。
- 当前没有 LangGraph checkpointer、interrupt/resume 或跨进程图恢复。
- Action Planner 主要是确定性 Python 规划；这是安全设计，不得为了增加 Agent 数量强行模型化。
- 简单聊天存在真实 streaming fast path；复杂检索路径可能在完整回答后再切块。
- desktop-polish.css 约 394 KB、约 1.55 万物理行，并在样式入口最后导入。
- App.tsx 与 MemoryWindowView.tsx 仍是顶层复杂度热点。
- Bottom dock、安全区变量、100dvh、fixed 和嵌套 overflow 形成结构性遮挡风险。
- 当前本次审计中桌面 typecheck 和 runtime mojibake 检查通过。
- 当前本次审计中 Agent/Graph 聚焦测试 72 项通过，API/SSE 聚焦测试 8 项通过。
- Full Live2D 必须持续标为 `Partial / Gap`，并明确口型同步、复杂动作编排和多角色资源管理缺口；不得写成 Covered。

这些只是起点，不是未来任务的完成证据。

---

## 4. 状态、证据与所有权规则

| 状态 | 含义 |
| --- | --- |
| Planned | 已定义，依赖尚未满足 |
| Ready | 依赖满足，可以开始 |
| In Progress | Coordinator 已分配且正在实施 |
| Implemented (unverified) | 代码完成，但缺少所需 L2/L3/L4 证据 |
| Partial | 主路径存在，但至少一个 DoD 或必要证据缺失 |
| Human Gate | 必须等待用户或指定测试者决定 |
| Blocked | 外部条件阻止继续，必须记录具体条件 |
| Skipped | 用户明确跳过；不算完成 |
| Completed | 全部 DoD、指定验证等级和证据产物已完成 |
| Covered | 仅用于验收矩阵，且必须有当前证据支持 |

验证等级遵循 docs/verification-policy.md：

- L1：单元、组件、类型或静态检查；不能单独证明运行任务完成。
- L2：合同或集成证据。
- L3：隔离状态下的真实产品路径。
- L4：真实人工可用性证据。

### 文件所有权

- 只有 Coordinator 可以修改 task.md 的状态、依赖和完成记录。
- 只有 Coordinator 可以修改 progress.md。
- Worker/subagent 只修改被分配任务明确允许的产品文件、测试和 verification 记录，并向 Coordinator 汇报。
- 多 Agent 并行时，禁止同时修改同一个源文件、同一 CSS 文件或同一 verification 记录。

### 每个任务的证据目录

~~~text
output/verification/task-XXXX/
  verification-record.md
  commands.txt
  result.md
  screenshots/        # 仅视觉任务
  artifacts-manifest.md
~~~

`output/verification/` 是被 Git 忽略的本地证据区，用于完整命令输出、截图和临时产物，禁止再次创建 `docs/verification/`。需要长期保留的结论只摘要写入 `progress.md`，公开验收边界只写入 `docs/mvp-acceptance-coverage.md`；历史命令必须重新运行后才能作为当前证据。

verification-record.md 必须记录：

- 日期、Agent、状态、验证等级；
- 目标；
- 实际改动文件；
- 每条实际命令及完整输出；
- DoD 勾选结果；
- 跳过项及原因；
- 残余风险；
- 人工决定或确认记录；
- 是否允许进入下一 Gate。

---

## 5. 全局安全与禁止事项

所有任务都必须遵守：

1. 不编辑 node_modules、dist、release、pytest-of-*、.tmp、本地数据库、日志或用户真实 Vault。
2. 不安装、升级或删除依赖，除非任务标明并取得用户确认。
3. 不修改 SQLite schema，除非执行 TASK-1104 且用户明确批准 migration。
4. 不绑定、切换、写入或索引真实 Vault，除非用户明确确认；测试默认使用 .tmp 下隔离目录。
5. 不停止非本次启动的 Electron、uvicorn 或端口进程。
6. 不记录真实 AGENT_PET_SESSION_TOKEN、LIVE_MODEL_API_KEY、Authorization、API key、私钥或 credential 内容。
7. Renderer 不得直接访问 Node、FS、child_process、localStorage 或真实凭据。
8. 不把原始 prompt、思维链、完整工具参数、异常堆栈或绝对隐私路径发送到前端。
9. 不为截图、视频或 Demo 硬编码成功状态、伪造 citation 或手改数据库制造结果。
10. 不把未运行的检查写成 passed、Covered 或 Completed。
11. 不在 sandbox build 出现 spawn EPERM 时篡改源码；必须在普通 Windows PowerShell 复跑并分别记录。
12. 不执行 git reset --hard、git checkout --、递归删除或其他破坏性命令。

### Stop-the-line 条件

出现以下任一项必须停止后续任务：

- 高风险操作在确认前修改目标；
- 敏感输入被发送到远程模型或写入普通记忆；
- 同一 SSE run 同时出现 done 与 error；
- Renderer/preload 暴露 session token；
- 包中出现数据库、credential 或真实 Vault；
- 1366×768 下发送、保存、创建、确认或撤销被底栏遮挡；
- negotiation 未真实启用却继续对外宣传多 Agent 协商；
- verification 证据与状态不一致。

---

## 6. AI Coordinator 使用方式

当用户说“执行下一项任务”时，Coordinator 必须：

1. 从总览表选择第一个状态为 Ready 的任务；
2. 重新读取该任务依赖和当前工作区；
3. 检查是否与其他运行 Agent 修改同一文件；
4. 为任务建立或复用 output/verification/task-XXXX/；
5. 只实施该任务，不顺带跨任务重构；
6. 运行任务列出的聚焦验证，再运行共享边界验证；
7. 汇总实际命令、完整输出、失败和残余风险；
8. 根据证据更新 task.md；只有 Coordinator 更新 progress.md；
9. 若任务需要 L4 或用户确认，停在 Human Gate，不自行模拟通过。

### 可直接交给未来 AI 的启动指令

~~~text
你是 E:\agentproject 的 Coordinator。
先完整读取根 AGENTS.md、task.md、锐评.md、docs/verification-policy.md。
执行用户指定的 TASK 编号；若用户只说“下一项”，选择总览中第一个 Ready 任务。
不得跨越阶段 Gate，不得修改任务允许范围外的文件。
先检查当前代码、测试、dirty worktree 和已有 verification 证据，再制定计划。
允许并行委派只读审计或互不重叠的子任务；subagent 不得修改 progress.md 或 task.md。
实施后运行任务指定验证，记录所有实际命令与完整输出。
没有达到任务要求的 L2/L3/L4 时，不得标 Completed 或 Covered。
触发用户确认条件时停止并请求确认，不得自行授权。
~~~

---

## 7. 阶段 Gate

| Gate | 退出条件 |
| --- | --- |
| G0 基线可信 | TASK-0601 Completed |
| G1 范围与宣称冻结 | TASK-0602 完成人工确认；TASK-0603 Completed |
| G2 Agent 真实可信 | TASK-0701 至 TASK-0707 Completed |
| G3 核心前端可信 | TASK-0801、0802、0803、0805、0808、0809、0810、0813 Completed |
| G4 工程健康 | TASK-0804、0806、0811、0812、0814 Completed；TASK-0807 可按岗位需要 |
| G5 黄金链与安全 | TASK-0901 至 TASK-0905 达到指定等级 |
| G6 求职 RC | TASK-0906 Completed |
| G7 作品集完整 | TASK-1001 至 TASK-1006 完成并取得必要人工确认 |
| G8 可选高级能力 | TASK-1101 至 TASK-1106 按证据和用户授权独立推进，不阻塞 G7 |

### 默认求职路线

- AI / Agent 后端岗位：完成 G0、G1、G2、G5、G6、G7；前端至少完成 G3。
- AI 全栈岗位：完成 G0 至 G7。
- 纯前端岗位：完成 G0、G1、G3、G4、G5、G6、G7；仍需诚实描述后端状态。

---

## 8. 任务总览

| 任务 | 名称 | 优先级 | 依赖 | 验证 | 人工门 |
| --- | --- | --- | --- | --- | --- |
| TASK-0601 | 当前基线与缺口冻结 | P0 | 无 | L2 | 否 |
| TASK-0602 | 作品集范围与能力声明矩阵 | P0 | 0601 | L2 | 是 |
| TASK-0603 | 隐藏占位入口与纠正误导文案 | P0 | 0602 | L2 | 否 |
| TASK-0701 | 接通真实有界 negotiation graph | P0 | 0602 | L2 | 否 |
| TASK-0702 | 轮次、时间、调用与上下文预算 | P0 | 0701 | L2 | 否 |
| TASK-0703 | 安全 SSE Agent Trace | P0 | 0702 | L2 | 否 |
| TASK-0704 | 检索、证据复核与 citation 黄金链 | P0 | 0702,0703 | L2 | 否 |
| TASK-0705 | Action 确认、拒绝、账本与撤销闭环 | P0 | 0701,0703 | L2 | 否 |
| TASK-0706 | Reflection 边界与后台任务托管 | P0 | 0702,0705 | L2 | 否 |
| TASK-0707 | 故障注入与可公开观测性 | P0 | 0703-0706 | L2 | 否 |
| TASK-0801 | DesktopShell、单滚动与 Bottom Dock | P0 | 0602 | L2 | 否 |
| TASK-0802 | 首页收敛为陪伴主舞台 | P0 | 0603,0801 | L2 | 否 |
| TASK-0803 | 聊天结果优先与渐进 Agent 过程 | P0 | 0703,0705,0801 | L2 | 否 |
| TASK-0804 | 聊天长列表与自动滚动性能 | P1 | 0803 | L2 | 否 |
| TASK-0805 | 记忆九入口压缩为三个任务 | P0 | 0603,0801 | L2 | 否 |
| TASK-0806 | 拆分 MemoryWindowView 工作区 | P1 | 0805 | L2 | 否 |
| TASK-0807 | 记忆图谱降级与等价列表 | P2 | 0806 | L2 | 否 |
| TASK-0808 | 设置普通层与开发者层分离 | P0 | 0603,0801 | L2 | 否 |
| TASK-0809 | 设置保存栏、脏状态与路径信任 | P0 | 0808 | L2 | 否 |
| TASK-0810 | 计划页收敛为任务闭环 | P0 | 0705,0801 | L2 | 否 |
| TASK-0811 | 拆分 App.tsx 与稳定派生数据 | P1 | 0802,0803,0805,0808,0810 | L2 | 否 |
| TASK-0812 | 迁移并退役 desktop-polish.css | P1 | 0811,核心页面完成 | L2 | 否 |
| TASK-0813 | 键盘、焦点、对比度与 reduced motion | P0 | 0812 | L2+L4 | 是 |
| TASK-0814 | 路由切换与长列表性能专项 | P1 | 0811,0812 | L2+L3 | 否 |
| TASK-0901 | 黄金链 A 真实 E2E | P0 | 0704,0803,0805 | L3+L4 | 是 |
| TASK-0902 | 黄金链 B 真实 E2E | P0 | 0705,0803,0810 | L3+L4 | 是 |
| TASK-0903 | Electron 安全与打包验收 | P0 | 0707,0812 | L2+L3 | 部分 |
| TASK-0904 | 响应式、缩放与人工视觉矩阵 | P0 | 0813,0901-0903 | L4 | 是 |
| TASK-0905 | 性能基线、预算与回归 | P1 | 0814,0901,0902 | L3 | 部分 |
| TASK-0906 | 求职 Release Candidate 总门禁 | P0 | 0707,0901-0905 | L2+L3+L4 | 是 |
| TASK-1001 | README 产品化重写 | P0 | 0906 | L2 | 否 |
| TASK-1002 | CASE_STUDY 案例研究 | P0 | 0904-0906 | L2+L4 | 是 |
| TASK-1003 | 系统、运行链与安全边界图 | P0 | 0707,0903,0906 | L2 | 否 |
| TASK-1004 | 隔离 Demo、脚本、视频与字幕 | P0 | 1001-1003 | L3+L4 | 是 |
| TASK-1005 | 中英文简历与面试材料 | P0 | 1002-1004 | L2+L4 | 是 |
| TASK-1006 | 隐私、许可证与公开发布门禁 | P0 | 1001-1005 | L4 | 是 |
| TASK-1101 | 小型 Agent 质量评测集 | P1 | 0707,0906 | L2 | 否 |
| TASK-1102 | Agent Registry 运行时能力契约 | P1 | 0704,0707 | L2 | 否 |
| TASK-1103 | Checkpointer/HITL ADR | P1 | 0707,0906 | L2 | 是 |
| TASK-1104 | SQLite Checkpointer 实施 | P2 | 1103 | L2+L3 | 必须 |
| TASK-1105 | LangGraph interrupt/resume | P2 | 1104 | L2+L3 | 必须 |
| TASK-1106 | 并行 fan-out 与成本路由评估 | P2 | 1101,1102 | L2 | 是 |

---

# Phase 6：基线、范围与真实宣称

## TASK-0601：当前基线与缺口冻结

- 状态：Ready
- 优先级：P0
- 依赖：无
- 要求等级：L2
- 目标：获得可复现的当前基线，禁止后续用旧证据或主观截图宣布完成。

### 允许范围

- 只读检查全仓；
- 新建 output/verification/task-0601/；
- 不修改产品源码、验收状态或 progress.md。

### 执行步骤

1. 记录 dirty worktree，明确哪些变更不是本任务产生。
2. 验证 backend、desktop、Electron、graph runtime、规格和验收矩阵核心路径。
3. 记录 App.tsx、MemoryWindowView.tsx、desktop-polish.css 的字节数与物理行数。
4. 跑后端全量、桌面测试、typecheck、乱码、Electron、打包合同、验收矩阵和隔离 smoke。
5. 将失败分类为源码失败、现有文档缺口、缺少环境、sandbox EPERM、live provider 未配置或人工缺口。
6. 在 baseline-audit.md 写当前 P0/P1、已知事实和不可宣称能力。
7. 不修复发现的问题；每个问题只映射到后续 TASK。

### DoD

- [ ] 每条命令有退出码和完整输出。
- [ ] 当前失败与跳过项均被保留。
- [ ] 不把历史通过冒充当前结果。
- [ ] 所有发现映射到具体任务编号。
- [ ] 没有修改产品源码。

### 验证命令

~~~powershell
git status --short
Test-Path apps/backend/app/main.py
Test-Path apps/backend/app/agents/graph_runtime.py
Test-Path apps/desktop/electron/main.cjs
Test-Path apps/desktop/electron/preload.cjs
Test-Path docs/current-specification.md

.\scripts\check-repo-hygiene.ps1

Push-Location apps\backend
python -m pytest -q
Pop-Location

Push-Location apps\desktop
npm run typecheck
npm test
npm run runtime:mojibake:check
node --check electron\main.cjs
node --check electron\preload.cjs
node scripts\validate-electron-migration.mjs
npm run package:check
Pop-Location

.\scripts\check-mvp-acceptance-gap.ps1
.\scripts\runbook-smoke.ps1 -Port 8766
~~~

### 禁止事项

- 不清理用户现有 dirty worktree。
- 不使用真实 Vault、真实 key 或真实个人数据。
- 不因命令失败而顺手改代码。
- 不停止未知进程。

### 证据产物

- output/verification/task-0601/baseline-audit.md
- output/verification/task-0601/commands.txt
- output/verification/task-0601/verification-record.md

---

## TASK-0602：作品集范围与能力声明矩阵

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0601
- 要求等级：L2 + Human Gate
- 目标：冻结求职作品集展示范围和每项技术声明，避免边做边扩张。

### 允许范围

- 新建 docs/portfolio/portfolio-scope.md；
- 新建 output/verification/task-0602/；
- 锐评.md 只读；
- 产品源码只读。

### 执行步骤

1. 建立“声明—当前事实—完成条件—证据—公开措辞”五列表。
2. 固定主叙事为本地优先、多角色工作流、带引用检索、安全动作和可审计账本。
3. 固定作品集只展示首页、聊天、记忆三任务、计划闭环、基础设置和两条黄金链。
4. 冻结隐藏项：关联、热力图、衰减图、占位页、高级 Wiki 管理、TTS 请求模板、未接通协商设置。
5. 区分三种互斥措辞：
   - negotiation 未接通：LangGraph 多角色工作流；
   - TASK-0701 至 0704 完成：有界多 Agent 协商与证据复核；
   - TASK-1104、1105 未完成：不支持跨进程图恢复。
6. 由用户确认目标岗位、保留范围和公开措辞。

### DoD

- [ ] 每项公开声明都有完成条件和证据路径。
- [ ] 两条黄金链与隐藏清单明确。
- [ ] 没有“企业级、完全自主、生产级”等无证据措辞。
- [ ] 用户明确批准 scope。

### 验证命令

~~~powershell
Get-Content -Encoding utf8 docs\portfolio\portfolio-scope.md | Out-Null
Select-String -Path docs\portfolio\portfolio-scope.md -Pattern "当前事实|完成条件|证据|公开措辞|黄金链|不支持"
~~~

### 禁止事项

- 未经用户确认不得进入 TASK-0603、Phase 7 或 Phase 8。
- 不用计划中的能力描述当前实现。
- 不修改验收矩阵状态。

### 证据产物

- docs/portfolio/portfolio-scope.md
- output/verification/task-0602/claim-matrix.md
- output/verification/task-0602/verification-record.md

### 用户确认

必须确认范围、目标岗位与最终对外措辞。

---

## TASK-0603：隐藏占位入口与纠正误导文案

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0602
- 要求等级：L2
- 目标：让 UI 和文档只承诺当前真实能力，不删除后端实现。

### 允许修改文件

- apps/desktop/src/productCopy.ts
- apps/desktop/src/views/MemoryWindowView.tsx
- apps/desktop/src/views/MemoryWindowView.test.tsx
- apps/desktop/src/features/settings/SettingsPanel.tsx
- apps/desktop/src/features/settings/SettingsPanel.test.tsx
- apps/desktop/src/views/navigation.ts
- apps/desktop/src/views/navigation.test.ts
- docs/current-specification.md，仅在当前描述与代码冲突时修正
- output/verification/task-0603/

### 执行步骤

1. 搜索“第一阶段、保留入口、多轮复核、自主协商、并行 Agent、自动恢复”等用户可见措辞。
2. 隐藏无闭环的关联、热力图、衰减图顶层入口；不删除后端模块。
3. negotiation 未接通前隐藏开关，或明确标为“实验性、当前未启用”。
4. 记忆关系图统一称“记忆关系图”，不得暗示它是 LangGraph 执行图。
5. 保留可验证入口：首页、聊天、记忆、计划、设置。
6. 更新测试，证明占位文案和虚假入口不再渲染。

### DoD

- [ ] 产品 UI 不出现开发阶段便签。
- [ ] 未接通能力没有可操作开关或完成态文案。
- [ ] 后端能力未被误删。
- [ ] 文案与 portfolio-scope.md 一致。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/views/MemoryWindowView.test.tsx src/features/settings/SettingsPanel.test.tsx src/views/navigation.test.ts
npm run typecheck
npm run runtime:mojibake:check
Pop-Location

rg -n "第一阶段|保留入口|多轮结果复核|自主协商|自动恢复" apps/desktop/src docs/current-specification.md
~~~

### 禁止事项

- 不删除后端服务、migration 或测试。
- 不把隐藏入口改成不可访问但仍占布局的空容器。
- 不把状态改成 Covered。

### 证据产物

- output/verification/task-0603/before-after-copy.md
- output/verification/task-0603/commands.txt
- output/verification/task-0603/verification-record.md

---

# Phase 7：LangChain / LangGraph / 多 Agent 真实性改造

## TASK-0701：接通真实、受限的 negotiation graph

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0602
- 要求等级：L2
- 目标：让 use_negotiation 真正改变运行路径，同时保持动作执行为确定性安全分支。

### 允许修改文件

- apps/backend/app/agents/graph_runtime.py
- apps/backend/app/agents/negotiation_graph.py
- apps/backend/app/agents/state.py
- apps/backend/app/agents/nodes/orchestrator.py
- apps/backend/app/models/config.py
- apps/backend/app/services/settings.py
- apps/backend/tests/test_agent_runtime_negotiation.py
- apps/backend/tests/integration/test_negotiation_flow.py
- apps/backend/tests/test_api_wiring_mvp.py
- output/verification/task-0701/

### 执行步骤

1. 先把“use_negotiation=True 仍忽略协商”的旧测试改成失败测试。
2. runtime 同时编译标准图与协商图，并按当前 automation settings 选择。
3. 协商路径固定为 route → semantic → orchestrator/invoke → synthesizer → finish。
4. 动作意图进入确定性 action 分支，不允许 supervisor 自由写数据。
5. 高置信普通聊天允许直接 synthesis；需要证据时才进入协商。
6. 本地隐私模式在任何远程模型调用前短路。
7. 运行时硬限制最大两轮；兼容旧值但不允许突破。
8. 删除或重写固定返回 False 的假开关逻辑。

### DoD

- [ ] 开关关闭不产生 negotiation 事件。
- [ ] 开关开启的检索问题至少调用一个真实子 Agent。
- [ ] 单次请求子 Agent 调用不超过两次。
- [ ] action 仍由确定性执行器落实。
- [ ] 本地隐私请求远程模型调用数为零。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/test_agent_runtime_negotiation.py tests/integration/test_negotiation_flow.py
python -m pytest -q tests/test_agent_runtime_routing.py tests/test_agent_runtime_memory_task.py tests/test_agent_runtime_wiki.py
python -m pytest -q tests/test_api_wiring_mvp.py -k "automation_settings or negotiation"
Pop-Location
~~~

### 禁止事项

- 不只发 UI 事件而不进入真实图。
- 不让 orchestrator 直接写 Vault、SQLite 或创建任务。
- 不把普通聊天全部送进协商循环。
- 不修改 schema。

### 证据产物

- 开关开/关脱敏 SSE 样例
- 实际节点流转图
- Agent/模型调用计数
- output/verification/task-0701/verification-record.md

---

## TASK-0702：轮次、时间、调用与上下文预算

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0701
- 要求等级：L2
- 目标：任何模型异常、重复调用或循环都必须在有限预算内结束。

### 允许修改文件

- apps/backend/app/agents/state.py
- apps/backend/app/agents/agent_runner.py
- apps/backend/app/agents/graph_runtime.py
- apps/backend/app/agents/nodes/orchestrator.py
- apps/backend/app/agents/registry.py
- 新建 apps/backend/app/agents/execution_policy.py
- 对应 negotiation/orchestrator 测试
- output/verification/task-0702/

### 执行步骤

1. 建立 ExecutionBudget：max_rounds=2、max_agent_calls=2、总超时、单 Agent 超时、上下文字符上限、重复调用集合。
2. 为 orchestrator、子 Agent 和 synthesis 增加有界 timeout。
3. 以 agent_id + normalized_query 阻止重复调用。
4. 仅无副作用且 registry 标记 retryable 的读取 Agent 可重试一次；重试计入预算。
5. 严格校验 orchestrator JSON；非法 Agent、空输入或未知 action 进入 fallback。
6. 有证据时基于已有证据回答；无证据时明确无结果或请求澄清。
7. 异常字符串、堆栈和原始工具输出不得进入最终 prompt。
8. 无 provider token usage 时标记 unavailable，不得伪造为零。

### DoD

- [ ] 循环模型最多两轮。
- [ ] 超时后只有一个终止事件。
- [ ] 重复 Agent/query 不重复执行。
- [ ] fallback 不泄漏异常、prompt 或工具原文。
- [ ] 写操作不自动重试。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/test_agent_runtime_negotiation.py tests/unit/agents/nodes/test_orchestrator.py tests/integration/test_negotiation_flow.py
Pop-Location
~~~

### 禁止事项

- 不无限重试或延长连接掩盖超时。
- 不把 total_tokens=0 宣称为实测零消耗。
- 不让预算对象记录用户正文或凭据。

### 证据产物

- 超时、非法 JSON、重复调用、预算耗尽四类记录
- output/verification/task-0702/verification-record.md

---

## TASK-0703：可公开展示且无推理泄漏的 SSE Agent Trace

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0702
- 要求等级：L2
- 目标：前端能展示角色、阶段、耗时和 fallback，但看不到思维链或敏感数据。

### 允许修改文件

- apps/backend/app/agents/events.py
- apps/backend/app/agents/events_helpers.py
- apps/backend/app/agents/graph_runtime.py
- apps/backend/app/models/event_payloads.py
- apps/backend/app/api/chat.py
- 相关 API、integration、安全测试
- output/verification/task-0703/

### 执行步骤

1. 定义白名单字段：stage_id、agent_id、phase、round、status、duration_ms、reason_code、safe_summary、安全计数和 source_scope。
2. 删除公开事件中的模型原始 reasoning；只允许枚举 reason_code 和固定模板摘要。
3. 为 route、semantic、retrieval、evidence review、synthesis、action plan、fallback 发 started/completed/failed。
4. 保持 token、citation、done/error 现有合同兼容。
5. 终止状态机严格保证 done 或 error 二选一且仅一次。
6. 增加凭据模式、绝对路径、prompt 和异常堆栈扫描测试。

### DoD

- [ ] UI 能解释谁在做什么及耗时。
- [ ] Trace 不含 prompt、reasoning、完整工具参数、原始用户消息、credential 或堆栈。
- [ ] 正常、超时、fallback、空检索均有合同测试。
- [ ] 旧 SSE 客户端不因新增字段失效。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/integration/test_negotiation_flow.py tests/test_api_wiring_mvp.py -k "stream or negotiation"
python -m pytest -q tests/test_security_contracts_api.py tests/test_security_hardening_mvp.py
Pop-Location
~~~

### 禁止事项

- 不公开思维链或模型 reasoning。
- 不用自由文本日志冒充结构化 trace。
- 不在 trace 中传完整 action payload。

### 证据产物

- 脱敏 SSE transcript
- 字段白名单
- 敏感信息扫描输出
- output/verification/task-0703/verification-record.md

---

## TASK-0704：检索、证据复核与 citation 黄金链

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0702、TASK-0703
- 要求等级：L2
- 目标：每个本地事实引用都能映射到被权限过滤并实际发出的 citation。

### 允许修改文件

- apps/backend/app/agents/nodes/retrieval.py
- apps/backend/app/agents/nodes/chat.py
- apps/backend/app/agents/events_helpers.py
- apps/backend/app/agents/retrieval/compression.py
- apps/backend/app/agents/registry.py
- apps/backend/app/models/enums.py
- 新建 apps/backend/app/agents/nodes/evidence_reviewer.py
- 检索、权限、prompt 相关测试
- output/verification/task-0704/

### 执行步骤

1. citation 进入 prompt/SSE 前过滤 can_answer_context、生命周期、非空 snippet、来源可访问性和重复项。
2. 为入选证据生成本次 run 内稳定的 C1、C2 引用标签。
3. Evidence Reviewer 只接收过滤后证据，输出 supported、usable IDs、reason_code 和 confidence。
4. Reviewer 不得自行检索、写数据或覆盖确定性权限拒绝。
5. 最终回答只能引用 reviewer 放行且已发出的 ID。
6. Reviewer 失败时回落确定性过滤结果，不放宽权限。
7. 明确询问本地事实却无有效证据时，返回未找到可引用记录。
8. Trace 只记录候选数、过滤数、入选数和 scope。

### DoD

- [ ] 回答引用 ID 均属于已发 citation。
- [ ] candidate、quarantined、rejected 或不可回答记忆不进入 prompt。
- [ ] 空检索不会编造本地事实。
- [ ] Reviewer 失败不导致权限放宽。
- [ ] item/字符预算仍有效。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/test_agent_runtime_retrieval.py tests/test_retrieval_fts.py
python -m pytest -q tests/test_memory_permissions.py tests/test_memory_activation.py tests/test_prompt_memory_assembler.py
Pop-Location
~~~

### 禁止事项

- 不让模型编造 citation ID。
- 不让模型 reviewer 覆盖确定性拒绝。
- 无证据时不得写“根据你的记忆”。

### 证据产物

- 命中、空检索、权限过滤三份事件样例
- citation 映射样例
- output/verification/task-0704/verification-record.md

---

## TASK-0705：Action 确认、拒绝、账本与撤销闭环

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0701、TASK-0703
- 要求等级：L2
- 目标：确认前零副作用，确认幂等，拒绝可审计，可逆写入可撤销。

### 允许修改文件

- apps/backend/app/agents/nodes/action.py
- apps/backend/app/services/agent_actions.py
- apps/backend/app/api/agent.py
- apps/backend/app/api/memory.py
- apps/backend/app/api/wiki.py
- apps/backend/app/api/tasks.py
- apps/backend/app/models/event_payloads.py
- 对应 action、API、安全、存储测试
- output/verification/task-0705/

### 执行步骤

1. 定义 planned → pending_confirm → completed/rejected/failed 状态机。
2. 复用 memory、Wiki、task 现有 typed 领域入口；不得用万能 JSON dispatcher 绕过校验。
3. 确认时重新执行风险与目标路径判定。
4. pending_confirm 在确认前不得创建任务、写 Markdown 或改 Vault。
5. 确认幂等；completed/rejected 不可再次执行。
6. 完成和拒绝均写活动账本；拒绝不得产生业务副作用。
7. 可逆 Markdown 写入保存 before/after snapshot，撤销生成新账本记录。
8. SSE 只发送安全摘要，不返回完整敏感 payload。

### DoD

- [ ] 确认前业务对象和 Vault 内容不变。
- [ ] 重放确认不重复写。
- [ ] 拒绝无业务副作用且有记录。
- [ ] 可逆写入可通过现有 revert 恢复。
- [ ] 高风险确认不可关闭。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/test_agent_actions.py
python -m pytest -q tests/test_api_wiring_mvp.py -k "agent_action or confirm or reject or revert"
python -m pytest -q tests/test_storage_paths.py tests/test_storage_markdown.py tests/test_security_hardening_mvp.py
Pop-Location
~~~

### 禁止事项

- 不修改 schema。
- 不让通用确认接口执行 Vault 绑定、删除、移动、批量改写或 schema 变更。
- 不保存 credential 或完整敏感输入到账本。

### 证据产物

- 确认前后差异
- 幂等与拒绝测试
- 写入与撤销账本样例
- output/verification/task-0705/verification-record.md

---

## TASK-0706：Reflection 边界与后台任务托管

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0702、TASK-0705
- 要求等级：L2
- 目标：Reflection 只处理已完成 exchange，不阻塞、篡改或污染前台回答。

### 允许修改文件

- apps/backend/app/api/chat.py
- apps/backend/app/services/post_reply_memory_job_runner.py
- apps/backend/app/services/chat_pipeline/
- apps/backend/app/main.py
- post-reply、chat pipeline、本地隐私与污染回归测试
- output/verification/task-0706/

### 执行步骤

1. 明确 foreground 负责当前回答，reflection 仅处理已完成 exchange。
2. 用应用级 task registry 替代裸 fire-and-forget；保存引用、done callback，并在 shutdown 有界等待或取消。
3. 为 diary、diary memory、consolidation、wiki summary 各设独立超时。
4. 单 stage 失败不得阻断允许继续的其他 stage。
5. metadata 只记录 job_id、stage、status、duration 和安全 error_code。
6. 本地隐私敏感请求不得创建 reflection job。
7. 后台 job 不写已结束 SSE；结果通过活动账本查询。
8. 同一 assistant message 不得重复调度。

### DoD

- [ ] done 不等待 Reflection。
- [ ] shutdown 无未托管 task 警告。
- [ ] 每个 stage 有超时、隔离和安全结果。
- [ ] 本地隐私模式 job 数为零。
- [ ] 重复调度不重复写日记。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/test_post_reply_memory_job_runner.py
python -m pytest -q tests/test_chat_pipeline_diary_memory.py tests/test_local_privacy_mode.py tests/test_memory_pollution_regression.py
Pop-Location
~~~

### 禁止事项

- 不让 Reflection 参与首屏回复延迟。
- 不保存 traceback、绝对路径、prompt 或凭据。
- 后台失败不得把成功回答改成 failed。

### 证据产物

- foreground/background 时间线
- 四阶段成功/跳过/失败矩阵
- output/verification/task-0706/verification-record.md

---

## TASK-0707：故障注入与可公开观测性

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0703 至 TASK-0706
- 要求等级：L2
- 目标：每个作品集声明都有源码入口、故障行为和当前测试证据。

### 允许修改文件

- apps/backend/app/api/diagnostics.py
- apps/backend/app/agents/graph_runtime.py
- apps/backend/app/services/agent_actions.py
- apps/backend/tests/test_diagnostics_export.py
- apps/backend/tests/integration/test_negotiation_flow.py
- 新建 apps/backend/tests/test_agent_failure_injection.py
- output/verification/task-0707/

### 执行步骤

1. 聚合 run 总耗时、各 Agent 耗时、轮次、调用数、timeout/fallback/retry、citation 过滤数、action 结果。
2. token usage 明确 measured 或 unavailable。
3. diagnostics 只输出聚合和安全字段。
4. 注入 semantic 失败、非法 orchestrator JSON、retrieval 超时/空结果、reviewer 失败、synthesis 失败、action 拒绝和 reflection 失败。
5. 为每种故障写确定终态和 fallback 预期。
6. 生成“功能声明—代码入口—测试证据”矩阵。
7. 跑后端全量；失败必须保留为 Gap。

### DoD

- [ ] 每个声明都有源码和测试。
- [ ] diagnostics 不含 prompt、用户正文、credential 或绝对路径。
- [ ] 故障矩阵全部有确定终态。
- [ ] 全量 pytest 当前结果被原样记录。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/test_diagnostics_export.py tests/test_agent_failure_injection.py
python -m pytest -q tests/test_api_wiring_mvp.py tests/test_e2e_backend_mvp.py tests/test_security_contracts_api.py
python -m pytest -q
Pop-Location
~~~

### 禁止事项

- 不只展示 happy path。
- 不伪造 token、延迟、覆盖率或通过率。
- 不吞掉所有错误后假装成功。

### 证据产物

- 故障注入矩阵
- 脱敏 diagnostics 样例
- 功能—源码—测试矩阵
- output/verification/task-0707/verification-record.md

---

# Phase 8：核心桌面体验与前端工程

> UI 任务执行时，如果当前环境提供 impeccable 与 playwright 技能，执行 Agent 必须先完整读取对应 SKILL.md。视觉检查不能代替合同测试，自动截图也不能代替 L4 人工判断。

## TASK-0801：DesktopShell、单滚动与 Bottom Dock 契约

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0602
- 要求等级：L2
- 目标：彻底解决底栏遮挡、未定义布局变量和嵌套主滚动。

### 允许修改文件

- apps/desktop/src/views/FeatureWindowShell.tsx
- apps/desktop/src/views/BottomNav.tsx
- apps/desktop/src/views/BottomNav.test.tsx
- apps/desktop/src/styles.css
- apps/desktop/src/styles/navigation.css
- apps/desktop/src/styles/responsive.css
- 新建 apps/desktop/src/styles/app-shell.css
- 新建 apps/desktop/src/styles/app-shell.test.ts
- output/verification/task-0801/

### 执行步骤

1. 在全局根作用域首次定义 header、dock、gap、page padding、content width 和语义 z-index 变量；媒体查询只覆盖值。
2. FeatureWindowShell 使用 header / minmax(0,1fr) / dock 三行 Grid。
3. BottomNav 进入第三行正常文档流，核心页面不再依赖 fixed 覆盖内容。
4. Shell 增加明确 scroll owner；普通页由 content 滚动，特殊页只能声明一个子滚动区。
5. 仅当横向导航溢出且目标不可见时滚动 active item；尊重 reduced motion。
6. z-index 只允许 content、sticky、dock、backdrop、modal、toast、tooltip token。
7. 不向 desktop-polish.css 追加补丁。

### DoD

- [ ] 1280×720、1366×768、1920×1080 下 dock 不遮挡最后一个操作。
- [ ] 每条核心路由只有一个主滚动容器。
- [ ] 所有布局变量在任意尺寸都有默认值。
- [ ] BottomNav 键盘可用并有 aria-current。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/views/BottomNav.test.tsx src/styles/app-shell.test.ts
npm run typecheck
npm run runtime:mojibake:check
Pop-Location

rg -n -- "--app-header-height|--app-dock-height|--app-page-padding|--z-modal" apps/desktop/src/styles
~~~

### 禁止事项

- 不用 overflow:hidden 掩盖内容。
- 不修改 Electron 安全边界。
- 不新增任意数字 z-index。

### 证据产物

- 五路由三尺寸截图
- 每页 scroll owner 表
- output/verification/task-0801/verification-record.md

---

## TASK-0802：首页收敛为陪伴主舞台

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0603、TASK-0801
- 要求等级：L2
- 目标：首页只突出角色、状态、输入和三条有用摘要。

### 允许修改文件

- apps/desktop/src/views/StageView.tsx
- apps/desktop/src/views/StageView.test.tsx
- apps/desktop/src/features/continuity/VisibleContinuityPanel.tsx
- apps/desktop/src/features/continuity/VisibleContinuityPanel.test.tsx
- apps/desktop/src/productCopy.ts
- apps/desktop/src/styles/stage-restore.css
- 新建 apps/desktop/src/styles/routes/home.css
- apps/desktop/src/styles.css
- output/verification/task-0802/

### 执行步骤

1. 首页保留角色舞台、在线/离线状态、聊天输入和最多三条摘要。
2. 摘要固定为待继续话题、最近记住、下一项任务；无数据时展示可行动空态。
3. 移除常驻大型管理卡和高级目录；跳转交给摘要和 BottomNav。
4. 角色脸部、气泡和主要动作区域不得被标签覆盖。
5. 明确 idle、streaming、offline、error 和 stop 状态。
6. 用户文案不出现 Agent、Vault、Provider、runtime。

### DoD

- [ ] 五秒内可识别主输入。
- [ ] 1366×768 无日期、状态、输入或气泡截断。
- [ ] 超过三条时只展示最重要三条并提供目标页入口。
- [ ] 首页无内部主滚动条。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/views/StageView.test.tsx src/features/continuity/VisibleContinuityPanel.test.tsx
npm run typecheck
npm run runtime:mojibake:check
Pop-Location
~~~

### 禁止事项

- 不在首页新增管理表单。
- 不用假任务、假记忆满足截图。
- 不让角色成为不可交互背景。

### 证据产物

- 空态、三摘要、流式、离线截图
- output/verification/task-0802/verification-record.md

---

## TASK-0803：聊天结果优先与渐进 Agent 过程

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0703、TASK-0705、TASK-0801
- 要求等级：L2
- 目标：回答是第一视觉层，来源、动作回执和 trace 按需展开。

### 允许修改文件

- apps/desktop/src/views/ChatWindowView.tsx
- apps/desktop/src/views/ChatWindowView.test.tsx
- apps/desktop/src/features/chat/ChatMessageList.tsx
- apps/desktop/src/features/chat/ChatMessageList.test.tsx
- apps/desktop/src/features/chat/ChatCitationSummary.tsx
- apps/desktop/src/features/chat/ChatCitationSummary.test.tsx
- apps/desktop/src/features/chat/ChatAgentActionSummary.tsx
- apps/desktop/src/features/chat/ChatAgentActionSummary.test.tsx
- apps/desktop/src/styles/chat.css
- 新建 apps/desktop/src/styles/routes/chat.css
- apps/desktop/src/styles.css
- output/verification/task-0803/

### 执行步骤

1. 固定顺序：回答正文 → 一行结果回执 → 来源摘要 → 折叠的查看过程。
2. 运行中只映射真实事件为理解、查找、执行、核验四类人话阶段。
3. 来源默认显示数量与最相关一条；展开后显示安全相对路径、片段和 scope。
4. 记忆、任务、资料整理合并为紧凑回执，同一动作不得重复三次。
5. 用角色身份替换 AI/ME 通用方块。
6. 失败说明哪些内容未保存、如何重试。
7. Trace 禁止显示 prompt、思维链、内部上下文和凭据。

### DoD

- [ ] 普通 hello 的过程 UI 不大于回答区域。
- [ ] citation、无 citation、空检索、失败、任务、高风险确认均有视图。
- [ ] 查看过程默认折叠且键盘可展开。
- [ ] 自动记忆回执只出现一次。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/views/ChatWindowView.test.tsx src/features/chat/ChatMessageList.test.tsx src/features/chat/ChatCitationSummary.test.tsx src/features/chat/ChatAgentActionSummary.test.tsx
npm run typecheck
npm run runtime:mojibake:check
Pop-Location
~~~

### 禁止事项

- 不删除真实 citation、失败或确认。
- 不把完整答案切块伪装真实 streaming。
- 不显示 reasoning 或 prompt。

### 证据产物

- 普通、带来源、空检索、动作、失败五种截图
- output/verification/task-0803/verification-record.md

---

## TASK-0804：聊天长列表、自动滚动与流式性能

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0803
- 要求等级：L2
- 目标：避免全量消息重复 filter/map 和每个 token 强制滚底。

### 允许修改文件

- apps/desktop/src/views/ChatWindowView.tsx
- apps/desktop/src/features/chat/ChatMessageList.tsx
- 对应测试
- 新建 apps/desktop/src/features/chat/useTranscriptViewport.ts
- 新建 apps/desktop/src/features/chat/useTranscriptViewport.test.tsx
- output/verification/task-0804/

### 执行步骤

1. 非 system 消息只派生一次，父子组件不得重复过滤。
2. 默认渲染最近 50 条，提供加载更早消息；不安装虚拟化依赖。
3. 加载更早消息保持滚动锚点。
4. 用户接近底部才自动跟随；向上阅读时显示回到最新。
5. token 滚动写入用 requestAnimationFrame 合并。
6. 测试 200 条消息和连续 300 次 token 更新。

### DoD

- [ ] 200 条消息首次最多渲染 50 条。
- [ ] 用户上滑后流式更新不抢位置。
- [ ] 回到底部后继续自动跟随。
- [ ] 历史数据没有被删除。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/features/chat/useTranscriptViewport.test.tsx src/features/chat/ChatMessageList.test.tsx src/views/ChatWindowView.test.tsx
npm run typecheck
Pop-Location
~~~

### 禁止事项

- 不安装列表库。
- 不把用户消息写入性能日志。

### 证据产物

- DOM 数量与滚动测试
- output/verification/task-0804/verification-record.md

---

## TASK-0805：记忆九入口压缩为三个用户任务

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0603、TASK-0801
- 要求等级：L2
- 目标：顶层只保留“记住的事、资料库、回顾与维护”。

### 允许修改文件

- apps/desktop/src/views/MemoryWindowView.tsx
- apps/desktop/src/views/MemoryWindowView.test.tsx
- apps/desktop/src/productCopy.ts
- 新建 apps/desktop/src/features/memory/workspace/memoryWorkspaceConfig.ts
- 新建对应测试
- 新建 apps/desktop/src/styles/routes/memory.css
- apps/desktop/src/styles.css
- output/verification/task-0805/

### 执行步骤

1. 记住的事包含当前记忆、搜索、手动新增和待确认。
2. 资料库包含资料入口、本机积累、导入和来源。
3. 回顾与维护包含整理记录、周复核、报告和高级分析。
4. 关联、热力图、衰减图移出顶层；无闭环项完全隐藏。
5. 删除开发便签与占位页面。
6. 三个 Tab 实现 ArrowLeft/ArrowRight/Home/End 和 roving tabindex。
7. 切换后焦点进入对应标题，不意外滚到底部。

### DoD

- [ ] 顶层只能看到三个 Tab。
- [ ] 无占位入口和开发阶段文案。
- [ ] 可用搜索、确认、资料和复盘仍可到达。
- [ ] Tab ARIA 关系完整。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/views/MemoryWindowView.test.tsx src/features/memory/workspace/memoryWorkspaceConfig.test.ts
npm run typecheck
npm run runtime:mojibake:check
Pop-Location
~~~

### 禁止事项

- 不删除后端功能。
- 不把记忆关系图称为 LangGraph 执行图。

### 证据产物

- 入口映射表
- 三 Tab 空态与数据态截图
- output/verification/task-0805/verification-record.md

---

## TASK-0806：拆分 MemoryWindowView 工作区

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0805
- 要求等级：L2
- 目标：让三个工作区独立加载、错误处理和测试，结束单文件巨型职责。

### 允许修改文件

- apps/desktop/src/views/MemoryWindowView.tsx
- apps/desktop/src/views/MemoryWindowView.test.tsx
- 新建 apps/desktop/src/features/memory/workspace/RememberedThingsWorkspace.tsx
- 新建 apps/desktop/src/features/memory/workspace/LibraryWorkspace.tsx
- 新建 apps/desktop/src/features/memory/workspace/ReviewMaintenanceWorkspace.tsx
- 新建 apps/desktop/src/features/memory/workspace/useMemoryWorkspaceData.ts
- 上述组件与 hook 测试
- output/verification/task-0806/

### 执行步骤

1. MemoryWindowView 只保留 Tab、路由和跨区共享参数。
2. 三个工作区各自拥有 loading、error、empty 和 refresh 边界。
3. 只有激活工作区触发其专属请求。
4. 公共类型和格式化函数提取为纯模块，禁止循环依赖。
5. API 参数、路径安全和确认逻辑不变。
6. 每个工作区补独立渲染与请求测试。

### DoD

- [ ] MemoryWindowView 不再包含三个工作区完整 JSX。
- [ ] 首次打开只请求默认工作区数据。
- [ ] 三个工作区可独立测试。
- [ ] 现有安全确认测试继续通过。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/views/MemoryWindowView.test.tsx src/features/memory/workspace
npm run typecheck
Pop-Location

Get-Item apps\desktop\src\views\MemoryWindowView.tsx | Select-Object Length
~~~

### 禁止事项

- 不改 API 或 schema。
- 不使用模块全局可变缓存保存敏感数据。

### 证据产物

- 拆分前后尺寸
- 首次请求清单
- output/verification/task-0806/verification-record.md

---

## TASK-0807：记忆图谱降级与等价列表

- 状态：Planned
- 优先级：P2
- 依赖：TASK-0806
- 要求等级：L2
- 目标：保留图谱作为可选亮点，但提供可读、可访问、可降级的等价列表。

### 允许修改文件

- apps/desktop/src/features/memory/MemoryGraphPanel.tsx
- apps/desktop/src/features/memory/MemoryGraphPanel.test.tsx
- apps/desktop/src/features/memory/workspace/ReviewMaintenanceWorkspace.tsx
- apps/desktop/src/styles/memory.css
- apps/desktop/src/styles/routes/memory.css
- output/verification/task-0807/

### 执行步骤

1. 图谱放入回顾与维护的高级分析，默认不加载。
2. 增加图谱/列表切换，两者使用同一过滤结果。
3. 节点显示可读标签；类型用文字和形状，不只用颜色。
4. 提供搜索、类型、状态、适合视图和重置。
5. 100 节点正常；500 节点减少标签；1000 节点默认列表并解释。
6. 键盘可选择节点、打开和关闭详情。

### DoD

- [ ] 无鼠标和无颜色辨识可完成搜索与详情。
- [ ] 1000 节点不默认绘制全部标签。
- [ ] 图谱与列表结果数一致。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/features/memory/MemoryGraphPanel.test.tsx
npm run typecheck
Pop-Location
~~~

### 禁止事项

- 不宣传为 LangGraph 执行图。
- 不靠缩小字体塞下内容。

### 证据产物

- 100/500/1000 节点记录
- 等价列表截图
- output/verification/task-0807/verification-record.md

---

## TASK-0808：设置普通层与开发者层分离

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0603、TASK-0801
- 要求等级：L2
- 目标：普通用户默认只看到对话、保存、自动化、提醒、语音和隐私。

### 允许修改文件

- apps/desktop/src/views/SettingsWindowView.tsx
- apps/desktop/src/features/settings/SettingsPanel.tsx
- apps/desktop/src/features/settings/SettingsPanel.test.tsx
- apps/desktop/src/features/settings/GlobalModelCard.tsx
- apps/desktop/src/features/settings/AgentConfigForm.tsx
- apps/desktop/src/features/settings/AutomationSettingsCard.tsx
- apps/desktop/src/features/settings/TtsSettingsCard.tsx
- 新建 apps/desktop/src/features/settings/SettingsSectionNav.tsx
- 新建对应测试
- 新建 apps/desktop/src/styles/routes/settings.css
- apps/desktop/src/styles.css
- output/verification/task-0808/

### 执行步骤

1. 普通层固定六章：对话服务、保存位置、自动整理、主动提醒、语音、隐私与安全。
2. Provider、Base URL、模型名、Header、JSON、MIME、每 Agent 模型放入默认折叠的开发者层。
3. 普通对话服务只显示连接状态、当前服务摘要、密钥输入、保存和测试。
4. 增加章节导航和设置搜索；空结果可清除。
5. negotiation 未真实接通前不显示为已生效能力。
6. 高风险必须确认显示为不可关闭安全说明。

### DoD

- [ ] 首屏无 Base URL、Header、JSON、MIME 和内部 Agent 名。
- [ ] 开发者层默认关闭且原能力仍可达。
- [ ] 搜索语音、保存、隐私能定位章节。
- [ ] credential 只显示配置状态或掩码。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/features/settings/SettingsPanel.test.tsx src/features/settings/SettingsSectionNav.test.tsx
npm run typecheck
npm run runtime:mojibake:check
Pop-Location
~~~

### 禁止事项

- 不删除凭据安全存储。
- 不在 renderer 日志打印表单。
- 不声称未接通能力已开启。

### 证据产物

- 普通首屏、搜索、开发者展开截图
- output/verification/task-0808/verification-record.md

---

## TASK-0809：设置保存栏、脏状态与路径信任

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0808
- 要求等级：L2
- 目标：统一保存语义，避免草稿丢失和 Vault UUID 被当作路径展示。

### 允许修改文件

- apps/desktop/src/features/settings/useSettings.ts
- apps/desktop/src/features/settings/settingsReducer.ts
- apps/desktop/src/features/settings/settingsFormatters.ts
- apps/desktop/src/features/settings/VaultBindingSection.tsx
- TASK-0808 涉及的 settings 组件
- 新建 apps/desktop/src/features/settings/SettingsSaveBar.tsx
- 新建 SettingsSaveBar、VaultBindingSection、settingsFormatters 测试
- output/verification/task-0809/

### 执行步骤

1. 每章计算 pristine、dirty、saving、saved、error。
2. 全页只保留一个稳定保存栏，支持保存当前章和放弃修改。
3. 切章或离开时，未保存内容触发应用内确认。
4. 保存失败保留草稿并聚焦首个错误。
5. TTS 临时 key 成功后清空组件状态，绝不进入 renderer 持久化。
6. 路径展示优先使用 root_path_label 或用户选择路径。
7. 只有 UUID 时显示“已绑定本地文件夹”，普通层不得显示内部 ID。
8. 真实目录绑定与切换仍走原确认链。

### DoD

- [ ] 同一视口无多组主要保存按钮。
- [ ] 脏、成功、失败、放弃、离开均有测试。
- [ ] 无路径时不显示 UUID。
- [ ] 切页不静默丢草稿。
- [ ] 绑定确认行为未改变。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/features/settings
npm run typecheck
node scripts\validate-electron-migration.mjs
Pop-Location
~~~

### 禁止事项

- 不使用 localStorage。
- 不在 API 成功前清空草稿。
- 不自动绑定、切换或索引真实 Vault。
- 不改后端 schema。

### 证据产物

- 脏状态、保存失败、离开确认、有路径/无路径截图
- output/verification/task-0809/verification-record.md

---

## TASK-0810：计划页收敛为任务闭环

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0705、TASK-0801
- 要求等级：L2
- 目标：默认只显示任务列表与选中详情，创建和执行日志按需展开。

### 允许修改文件

- apps/desktop/src/views/AgentWorkspaceView.tsx
- apps/desktop/src/views/AgentWorkspaceView.test.tsx
- apps/desktop/src/features/tasks/TaskPanel.tsx
- apps/desktop/src/features/tasks/TaskPanel.test.tsx
- apps/desktop/src/features/tasks/
- apps/desktop/src/styles/tasks.css
- 新建 apps/desktop/src/styles/routes/tasks.css
- apps/desktop/src/styles.css
- output/verification/task-0810/

### 执行步骤

1. 默认主区展示今天、即将到来、已完成列表和当前选中详情。
2. 创建任务通过按钮打开侧栏或内联区，不常驻占半屏。
3. 详情合并状态、截止、提醒、完成/取消和确认。
4. 步骤与日志合并为默认折叠的执行详情。
5. 对话创建与手工任务使用同一卡片。
6. 空态提供创建第一个任务和回到聊天两个真实入口。

### DoD

- [ ] 默认最多两个主视觉区域。
- [ ] 选中任务后状态集中。
- [ ] 高风险未确认前不执行。
- [ ] 列表、空态、创建、详情、失败均有测试。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/views/AgentWorkspaceView.test.tsx src/features/tasks/TaskPanel.test.tsx src/features/tasks
npm run typecheck
Pop-Location
~~~

### 禁止事项

- 不改变任务 API、时区或调度语义。
- 不隐藏失败和 pending confirmation。

### 证据产物

- 列表、创建、详情、高风险确认截图
- output/verification/task-0810/verification-record.md

---

## TASK-0811：拆分 App.tsx 与稳定派生数据

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0802、0803、0805、0808、0810
- 要求等级：L2
- 目标：App 只负责应用组合，不再承载所有聊天、路由和领域细节。

### 允许修改文件

- apps/desktop/src/App.tsx
- apps/desktop/src/App.test.tsx
- apps/desktop/src/features/desktop/DesktopFeatureRoutes.tsx
- 新建 apps/desktop/src/app/DesktopAppComposition.tsx
- 新建 apps/desktop/src/features/chat/useChatController.ts
- 新建对应测试
- 新建 apps/desktop/src/features/desktop/useDesktopRouteProps.ts
- 新建对应测试
- output/verification/task-0811/

### 执行步骤

1. 将 SSE 生命周期、停止、done/error 和发送抽入 useChatController。
2. 将各路由 props 组装抽入 useDesktopRouteProps。
3. 将 Stage、Feature、Pet 宿主组合抽入 DesktopAppComposition。
4. 用 useMemo 缓存 buildAgentActivityEntries 和计数派生。
5. 使用稳定 callback，避免无关状态让整页子树重渲染。
6. 保持 pet/stage/control 分支和 SSE 合同不变。

### DoD

- [ ] App.tsx 可在一次代码审查中理解。
- [ ] buildAgentActivityEntries 仅在输入变化时重算。
- [ ] 路由、停止、失败终态测试通过。
- [ ] token 未进入 React Context。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/App.test.tsx src/features/chat/useChatController.test.tsx src/features/desktop
npm run typecheck
node scripts\validate-electron-migration.mjs
Pop-Location

rg -n "buildAgentActivityEntries" apps/desktop/src
~~~

### 禁止事项

- 不为拆分重写业务语义。
- 不创建巨型万能 Context。

### 证据产物

- 拆分前后尺寸
- 组件关系图
- 重算计数测试
- output/verification/task-0811/verification-record.md

---

## TASK-0812：迁移并退役 desktop-polish.css

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0811 且 TASK-0802、0803、0805、0808、0810 完成
- 要求等级：L2
- 目标：建立 token、Shell、共享组件、路由四层样式所有权，结束末尾补丁。

### 允许修改文件

- apps/desktop/src/styles.css
- apps/desktop/src/styles/desktop-polish.css
- apps/desktop/src/styles/theme.css
- apps/desktop/src/styles/base.css
- apps/desktop/src/styles/navigation.css
- apps/desktop/src/styles/app-shell.css
- apps/desktop/src/styles/routes/
- 现有样式测试
- 新建 apps/desktop/src/styles/style-ownership.test.ts
- output/verification/task-0812/

### 执行步骤

1. 建立 token、Shell、控件、home、chat、memory、tasks、settings 所有权表。
2. 逐路由迁移；迁一组删除一组，禁止复制后保留双份。
3. 删除重复高度计算、广泛 body[data-window-mode] 覆盖和任意 z-index。
4. 改用语义 token 和新 Shell 变量。
5. 每迁移一路由立即跑测试和截图。
6. 所有被使用规则迁完后移除 import；确认无引用后才删除旧文件。

### DoD

- [ ] styles.css 不依赖 desktop-polish.css 才能正确布局。
- [ ] 五核心页面三尺寸无回归。
- [ ] 无新增 final pass、safety pass 或最终覆盖文件。
- [ ] 旧规则每一组都有迁移或删除依据。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/styles
npm run typecheck
npm run build
npm run runtime:mojibake:check
Pop-Location

rg -n "final pass|safety pass|body\[data-window-mode" apps/desktop/src/styles
~~~

### 禁止事项

- 不机械删除未知归属规则。
- 不新建 final-overrides.css。
- build 遇 EPERM 必须普通 PowerShell 复跑。

### 证据产物

- 样式所有权表
- 迁移前后字节数
- 五页对照截图
- output/verification/task-0812/verification-record.md

---

## TASK-0813：键盘、焦点、对比度与 reduced motion

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0812
- 要求等级：L2 + L4
- 目标：核心作品集流程可键盘完成，并具备可见焦点、足够对比度和减弱动画。

### 允许修改文件

- 五个核心页面及直接子组件
- apps/desktop/src/components/layout.tsx
- apps/desktop/src/styles/base.css
- apps/desktop/src/styles/responsive.css
- apps/desktop/src/styles/routes/
- 对应测试
- output/verification/task-0813/

### 执行步骤

1. 键盘完成连接、聊天、来源、记忆 Tab、任务、确认/取消和保存。
2. Dialog/侧栏使用 Portal、标题、关闭、Esc、焦点陷阱和焦点归还。
3. 控件具备 default、hover、focus、active、disabled、loading、error。
4. 正文与 placeholder 达 4.5:1，大文字 3:1，状态不只依赖颜色。
5. 触控目标至少 44×44 CSS px。
6. reduced motion 下移除平滑滚动与持续装饰动画。
7. aria-live 不得每个 token 重复播报。
8. 用户或指定测试者完成 200% 缩放与键盘 L4。

### DoD

- [ ] 无鼠标可跑两条黄金链。
- [ ] 200% 缩放无不可达控件。
- [ ] reduced motion 无平滑滚动和持续装饰动画。
- [ ] L4 记录由真人确认。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test
npm run typecheck
npm run runtime:mojibake:check
Pop-Location

rg -n "prefers-reduced-motion|focus-visible" apps/desktop/src/styles
~~~

### 禁止事项

- 不用正 tabIndex 修顺序。
- 不把自动化截图当 L4。
- 不删除内容来通过对比度或遮挡检查。

### 证据产物

- 键盘路径记录
- 200% 截图
- 对比度清单
- output/verification/task-0813/verification-record.md

### 用户确认

必须由用户或指定测试者确认 L4。

---

## TASK-0814：路由切换与长列表性能专项

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0811、TASK-0812
- 要求等级：L2 + L3
- 目标：修复 route remount、全数组计算、多请求和全局样式重算造成的卡顿。

### 允许修改文件

- apps/desktop/src/features/desktop/DesktopFeatureRoutes.tsx
- apps/desktop/src/features/desktop/useDesktopWindowRouting.ts
- apps/desktop/src/views/BottomNav.tsx
- apps/desktop/src/views/MemoryWindowView.tsx
- apps/desktop/src/features/memory/workspace/
- apps/desktop/src/views/ChatWindowView.tsx
- apps/desktop/src/features/chat/
- apps/desktop/src/App.tsx
- 对应测试
- output/verification/task-0814/

### 执行步骤

1. 用 React Profiler 与 Chromium Performance 记录修复前基线。
2. 确认 App 派生数据 memoize。
3. 记忆页只加载当前工作区；重复访问使用有明确生命周期的非敏感缓存。
4. 聊天与活动列表分页或增量显示。
5. 移除 BottomNav 不必要 offset 读取和平滑滚动。
6. 路由样式作用域移到路由根，减少 body.dataset 触发的广泛重算。
7. 对 100 条记忆、200 条消息和十次路由往返做同机复测。

### DoD

- [ ] 切换默认记忆区不同时请求全部高级数据。
- [ ] 无超过 50ms 的已知 JS/样式 Long Task，或明确记录剩余瓶颈。
- [ ] 同口径 route switch 中位时间较 TASK-0601 基线降低 30%；未达成时保持 Partial。
- [ ] 不通过永久挂载所有重量页面换取假速度。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm test -- src/features/desktop src/features/chat src/features/memory src/views/BottomNav.test.tsx
npm run typecheck
npm run build
Pop-Location
~~~

### 禁止事项

- 不记录真实用户内容到 profile。
- 不安装性能依赖。
- 不只报告平均值。

### 证据产物

- before/after profile manifest
- performance-summary.md
- output/verification/task-0814/verification-record.md

---

# Phase 9：黄金链、Electron 安全与求职 RC

## TASK-0901：黄金链 A——带来源记忆回答真实 E2E

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0704、TASK-0803、TASK-0805
- 要求等级：L3 + L4
- 目标：证明 Electron 输入经过 sidecar、SQLite/FTS/Vault、LangGraph、SSE 回到带引用回答。

### 允许修改文件

- 新建 scripts/verify-portfolio-golden-paths.ps1
- 新建 scripts/prepare-portfolio-demo.ps1
- 黄金链发现缺陷时，只修改 TASK-0704、0803、0805 允许范围
- apps/backend/tests/test_e2e_backend_mvp.py
- output/verification/task-0901/

### 执行步骤

1. 在 .tmp/task-0901/ 建立隔离 SQLite、数据目录和 Demo Vault。
2. 写入唯一可检索的会议时间偏好及明确来源，并通过真实索引路径导入。
3. 新脚本负责准备、启动隔离 sidecar、调用真实 chat/SSE、验证并清理本次进程；不得触碰未知进程。
4. Electron 中询问偏好和来源。
5. 同一 run 验证 status、trace、citation、非空 token 和唯一 done。
6. citation 路径、snippet 与 fixture 一致。
7. 再问语义相近问题，证明不依赖页面临时状态。
8. 问无匹配问题，必须明确无本地证据。
9. 人工确认回答优先、来源可懂、过程默认折叠。

### DoD

- [ ] Electron → sidecar → storage → graph → SSE → UI 真实通过。
- [ ] citation 与 fixture 一致。
- [ ] 空检索不编造。
- [ ] 只有一个终止事件。
- [ ] 隔离数据不污染真实 Vault。
- [ ] L4 人工记录完成。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/test_agent_runtime_retrieval.py tests/test_retrieval_fts.py tests/test_e2e_backend_mvp.py
Pop-Location

.\scripts\verify-portfolio-golden-paths.ps1 -Scenario MemoryCitation -WorkDir .\.tmp\task-0901 -Port 8766

Push-Location apps\desktop
npm test -- src/views/ChatWindowView.test.tsx src/features/chat/ChatMessageList.test.tsx src/features/chat/ChatCitationSummary.test.tsx
npm run typecheck
Pop-Location
~~~

### 禁止事项

- 不使用真实 Vault、真实 key 或个人聊天。
- 不用 mock UI、seeded DOM 或手工数据库值代替 E2E。
- 不伪造 citation。

### 证据产物

- 脱敏事件流
- fixture manifest
- 截图与人工记录
- output/verification/task-0901/verification-record.md

### 用户确认

L4 必须确认；live provider 另需用户确认后才运行。

---

## TASK-0902：黄金链 B——任务、确认、账本与撤销真实 E2E

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0705、TASK-0803、TASK-0810
- 要求等级：L3 + L4
- 目标：一句话创建低风险任务/记忆，并证明高风险动作只等待确认。

### 允许修改文件

- scripts/verify-portfolio-golden-paths.ps1
- 黄金链缺陷只修改 TASK-0705、0803、0810 允许范围
- 对应 backend/desktop 测试
- output/verification/task-0902/

### 执行步骤

1. 使用 .tmp/task-0902/ 隔离数据库和 Vault。
2. 输入“明天下午三点提醒我回邮件，并记住我更喜欢下午开会”。
3. 验证 semantic/action 路由、task event、时区、数据库和记忆回执。
4. 任务页可查询，重启隔离 sidecar 后仍存在。
5. 账本包含 action type、来源、风险、目标、安全摘要、状态和可撤销性。
6. 对一个低风险可逆 fixture 执行撤销，验证内容恢复并新增撤销记录。
7. 发送删除、移动或批量改写请求，验证只产生 requires_confirmation，目标 hash 不变；本任务不批准高风险执行。
8. 输入 credential-like fixture，验证不调用远程模型、不写普通记忆；证据只记录模式命中，不记录完整值。
9. 人工确认回执与风险提示清晰。

### DoD

- [ ] 任务创建、查询、重启持久化通过。
- [ ] 时区与提醒时间正确。
- [ ] 低风险撤销闭环通过。
- [ ] 高风险确认前目标不变。
- [ ] 敏感输入不离开本机。
- [ ] L4 人工记录完成。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests/test_agent_runtime_memory_task.py tests/test_agent_actions.py tests/test_security_hardening_mvp.py tests/test_api_wiring_mvp.py
Pop-Location

.\scripts\verify-portfolio-golden-paths.ps1 -Scenario TaskAndSafety -WorkDir .\.tmp\task-0902 -Port 8766

Push-Location apps\desktop
npm test -- src/features/chat/ChatAgentActionSummary.test.tsx src/views/AgentWorkspaceView.test.tsx src/features/tasks
npm run typecheck
Pop-Location
~~~

### 禁止事项

- 不批准或执行删除、移动、批量改写。
- 不用真实联系人、任务或笔记。
- 不在证据中记录 credential fixture 全文。

### 证据产物

- task/ledger 脱敏样例
- before/after hash
- 截图与人工记录
- output/verification/task-0902/verification-record.md

### 用户确认

L4 必须确认；任何真实高风险批准路径均不属于本任务。

---

## TASK-0903：Electron 安全边界与打包验收

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0707、TASK-0812
- 要求等级：L2 + L3
- 目标：证明 Renderer、preload、main、sidecar、包资源与 credential 边界没有回归。

### 允许修改文件

- apps/desktop/electron/main.cjs
- apps/desktop/electron/preload.cjs
- apps/desktop/electron/proxy.js
- apps/desktop/electron/proxy.test.cjs
- apps/desktop/scripts/validate-electron-migration.mjs
- apps/desktop/scripts/validate-electron-packaging.mjs
- 安全测试
- output/verification/task-0903/

### 执行步骤

1. 验证 contextIsolation、sandbox、webSecurity 开启，nodeIntegration 关闭。
2. preload 不导入 fs/child_process，只暴露最小 contextBridge。
3. Renderer 不读取 token、不构造 Authorization、不使用 Node/localStorage。
4. SSE auth 仅在 main/sidecar 边界。
5. 外部 URL 经过 main 导航控制。
6. protected API 无 token 401；路径遍历、隐藏目录、reparse point、Wiki 越界被拒绝。
7. package 排除 db、sqlite、credentials、测试工件和本地状态。
8. 构建 unpacked 包，使用隔离状态真实启动与关闭。
9. 只检查本次 PID；不终止未知进程。

### DoD

- [ ] Electron migration、syntax、package contract 通过。
- [ ] 后端安全测试通过。
- [ ] unpacked 包真实启动、主界面可达并干净关闭。
- [ ] 包内无数据库、credential 和真实 Vault。
- [ ] Renderer 无 token/Node 越权。

### 验证命令

~~~powershell
Push-Location apps\desktop
node --check electron\main.cjs
node --check electron\preload.cjs
node --check electron\proxy.js
node scripts\validate-electron-migration.mjs
npm run package:check
npm run runtime:mojibake:check
npm run build
npm run package:win:dir
Pop-Location

Push-Location apps\backend
python -m pytest -q tests/test_storage_paths.py tests/test_security_hardening_mvp.py tests/test_security_contracts_api.py
Pop-Location

.\scripts\check-trial-processes.ps1
~~~

### 禁止事项

- 不手工编辑 dist/release。
- 不关闭安全开关。
- 不签名、发布或启用更新。
- 不停止非本次进程。

### 证据产物

- package resource manifest
- packaged launch notes
- PID before/after
- output/verification/task-0903/verification-record.md

### 用户确认

停止未知进程、真实凭据 packaged launch、签名或发布均需确认。

---

## TASK-0904：响应式、缩放与人工视觉矩阵

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0813、TASK-0901 至 TASK-0903
- 要求等级：L4
- 目标：证明常见 Windows 窗口和缩放下核心路径无遮挡、可读、可操作。

### 允许修改文件

- output/verification/task-0904/
- 只允许修复验收发现的局部 P0；跨模块问题退回原任务

### 测试矩阵

- 1280×720：100%
- 1366×768：100%、125%、150%
- 1920×1080：100%、125%、150%
- 1366×768：200% 页面缩放与纯键盘

### 执行步骤

1. 每个配置检查首页、聊天、记忆、计划、设置。
2. 额外检查长回答、长 citation、确认弹层、长设置、错误和空状态。
3. 确认每页只有一个主滚动容器。
4. Bottom dock 不遮发送、保存、创建、确认和撤销。
5. 用 Tab、Shift+Tab、Enter、Space、Escape 跑两条黄金链主要操作。
6. 检查焦点、禁用、loading、success、error、retry、placeholder 对比度和长文本。
7. 使用 Playwright/浏览器截图作为自动证据，再由真人签署 L4。

### DoD

- [ ] 全矩阵无主操作遮挡。
- [ ] 无双主滚动和弹层裁切。
- [ ] 长文本与中文路径可换行。
- [ ] 200% 可完成发送、确认和保存。
- [ ] 所有失败有复现步骤和严重级别。
- [ ] 真人签署 L4。

### 验证命令

~~~powershell
Push-Location apps\desktop
npm run typecheck
npm test
npm run runtime:mojibake:check
npm run electron:dev
Pop-Location
~~~

### 禁止事项

- 不裁截图隐藏问题。
- 不用自动截图替代 L4。
- 不只测空状态。
- 不为通过而隐藏真实错误或确认。

### 证据产物

- visual-acceptance-matrix.md
- screenshots/
- contact-sheet.png
- keyboard-run.md
- output/verification/task-0904/verification-record.md

### 用户确认

必须由用户或指定测试者签署。

---

## TASK-0905：性能基线、预算与回归

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0814、TASK-0901、TASK-0902
- 要求等级：L3
- 目标：用固定数据和同一机器量化启动、切页、长聊天和记忆性能。

### 允许修改文件

- 新建 scripts/benchmark-desktop.ps1
- 性能缺陷只回到 TASK-0804、0806、0811、0812、0814 范围修复
- output/verification/task-0905/

### 固定数据

- 200 条聊天
- 1000 条记忆
- 50 个任务
- 100、500、1000 节点图谱

### 执行步骤

1. 脚本创建隔离 fixture，记录机器、版本和数据 hash。
2. 五次冷启动记录 UI 可用与 health ready。
3. 每条主路由往返二十次，记录 p50/p95。
4. 测 200 消息滚动、输入响应和 token 更新。
5. 测 1000 记忆加载、搜索、筛选和详情。
6. 图谱 100 正常、500 降标签、1000 默认列表。
7. 记录 React/Chromium trace、Long Task、样式重算、CPU 与内存。
8. provider TTFT 与本地耗时分开。
9. 修复后必须同口径复测。

### 初始预算

- 冷启动五次均在 10 秒内出现可用 UI。
- 路由切换 p95 不超过 250ms。
- 输入响应 p95 不超过 100ms。
- 200 消息滚动平均不低于 50fps，无单次超过 200ms 主线程阻塞。
- 1000 记忆首个可用内容不超过 1 秒，本地筛选不超过 300ms。
- 1000 节点不得冻结 UI。
- 空闲 30 秒 CPU 均值不超过 5%。

预算未达成必须记录 Partial，不允许改口。

### DoD

- [ ] fixture 数量、内容 hash、机器、版本和测量日期完整记录。
- [ ] 冷启动五次、每条主路由二十次均保留原始结果，并计算 p50/p95。
- [ ] 聊天、记忆和图谱按固定数据规模完成，不以空数据替代。
- [ ] provider TTFT、后端耗时和 renderer 本地耗时分别报告。
- [ ] 修改前后使用同一机器、fixture、运行次数和统计口径。
- [ ] 所有初始预算逐条给出 Pass 或 Fail；任何 Fail 都保持 Partial 并链接修复任务。
- [ ] trace、CSV 和报告不包含真实聊天、凭据、默认数据库或真实 Vault。
- [ ] 修复后聚焦回归与共享边界验证均有当前证据。

### 验证命令

~~~powershell
.\scripts\benchmark-desktop.ps1 -WorkDir .\.tmp\task-0905 -Runs 20 -OutputDir .\output\perf\task-0905

Get-Process electron,python -ErrorAction SilentlyContinue |
  Select-Object ProcessName,Id,CPU,WorkingSet64,PrivateMemorySize64
~~~

### 禁止事项

- 不只测空数据或平均值。
- 不清理真实状态。
- 不把 provider 延迟算作 renderer 性能。
- 不提交超大原始 trace；只提交 manifest/hash。

### 证据产物

- performance-baseline.md
- benchmark-summary.csv
- trace-manifest.md
- output/verification/task-0905/verification-record.md

---

## TASK-0906：求职 Release Candidate 总门禁

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0707、TASK-0901 至 TASK-0905
- 要求等级：L2 + L3 + L4
- 目标：给出明确 Go/No-Go，不让自动测试、真实路径和人工体验互相替代。

### 允许修改文件

- docs/mvp-acceptance-coverage.md
- docs/runbook.md
- output/verification/task-0906/
- 只允许修验收发现的 P0/P1；新功能禁止

### 执行步骤

1. 进入代码冻结。
2. 跑 backend、desktop、build、Electron、package、气泡、sprite、验收矩阵与 smoke。
3. 跑黄金链 A/B L3。
4. 若用户提供 live provider 授权，固定脚本连续五次并记录 TTFT/错误；否则明确未验证。
5. 人工跑普通聊天、带引用、空检索、协商上限、任务、高风险阻断、敏感输入、provider 失败、SSE 断流和视觉矩阵。
6. 修复 Full Live2D 文档合同：依据当前事实标 Partial/Gap，并列出 lip sync、复杂动作、多角色资源缺口；不得写 Covered。
7. packaged app 启动和关闭。
8. 对照 claim matrix 与验收矩阵。
9. 输出唯一 Go 或 No-Go 结论。

### DoD

- [ ] 当前自动化结果完整记录。
- [ ] 黄金链 L3/L4 证据完整。
- [ ] 安全、打包、视觉无 P0/P1。
- [ ] 性能无未豁免 P1。
- [ ] packaged app 可启动并干净关闭。
- [ ] 宣传与 negotiation/checkpointer 真实状态一致。
- [ ] Go/No-Go、豁免与残余风险由用户确认。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q
Pop-Location

Push-Location apps\desktop
npm run typecheck
npm test
npm run build
npm run package:check
npm run pet:bubble:check
npm run sprite-pet:check
npm run sprite-pet:check:dist
node scripts\validate-electron-migration.mjs
Pop-Location

.\scripts\check-mvp-acceptance-gap.ps1
.\scripts\runbook-smoke.ps1 -Port 8766
.\scripts\verify-portfolio-golden-paths.ps1 -Scenario All -WorkDir .\.tmp\task-0906 -Port 8766
.\scripts\check-trial-processes.ps1
~~~

### 禁止事项

- 不新增功能。
- 不跳过失败后宣布 Go。
- 不用历史 provider 结果。
- 不停止非本次进程。
- 不擅自把 Partial 改 Covered。

### 证据产物

- release-candidate-checklist.md
- full-command-log.txt
- manual-trial.md
- go-no-go.md
- output/verification/task-0906/verification-record.md

### 用户确认

live provider、任何豁免、L4 和最终 Go/No-Go 均需确认。

---

# Phase 10：作品集交付与公开材料

## TASK-1001：README 产品化重写

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0906
- 要求等级：L2
- 目标：让面试官在三分钟内看懂产品价值、两条黄金链、真实技术边界、运行方法和证据入口。

### 允许修改文件

- README.md
- 新建 docs/portfolio/assets-manifest.md
- 新建 scripts/check-portfolio-docs.ps1
- output/verification/task-1001/
- 仅引用已经由 TASK-0901 至 TASK-0906 生成的截图和数据，不修改产品源码

### README 固定结构

1. 一句话定位：本地优先的 Windows AI 伴随应用。
2. 一张真实主界面图，不使用拼接遮挡或概念稿冒充运行效果。
3. 两条黄金链，每条不超过八步，并链接到验证记录。
4. “为什么不是普通聊天壳”：LangGraph 编排、citation、安全动作、活动账本和撤销。
5. 技术架构与信任边界摘要。
6. 隔离 Demo 快速开始和完整开发启动方式。
7. 当前验证状态、可复现命令和最近一次结果日期。
8. 关键工程决策及取舍。
9. 明确限制：live provider、negotiation、checkpointer、Full Live2D 和平台支持以当前 claim matrix 为准。
10. 隐私、安全、许可证和公开材料入口。

### 执行步骤

1. 从 TASK-0602 claim matrix 复制已批准的能力措辞，不自行升级宣传。
2. 从 TASK-0906 读取当前 Go/No-Go、命令结果、残余风险和可公开指标。
3. 把 README 首屏压缩为定位、截图、三个事实证据和快速入口，删除开发日志式长前言。
4. 用 Mermaid 或链接引用 TASK-1003 的图；在图未完成前保持 TASK-1001 为 Implemented (unverified)，不放失效占位链接。
5. 所有数字标注机器、数据规模、样本次数和测量日期；没有相同口径结果就不写数字。
6. 将截图来源、生成日期、场景、是否含模拟数据写入 assets-manifest.md。
7. 编写 check-portfolio-docs.ps1，检查必需章节、本地链接、图片路径、禁用宣传词和 verification 链接。
8. 在干净阅读视角下从头执行 README 命令，不依赖作者机器的隐式环境。

### DoD

- [ ] README 首屏能回答“是什么、解决什么、最强证据是什么”。
- [ ] 两条黄金链均链接到 L3/L4 证据。
- [ ] 所有能力措辞与 claim matrix 一致。
- [ ] 所有本地链接和图片存在。
- [ ] 快速开始只使用隔离数据，不要求真实 Vault 或真实 key。
- [ ] 所有指标具备口径、日期和证据路径。
- [ ] 限制、隐私和许可证入口可见。
- [ ] 文档检查脚本通过。

### 验证命令

~~~powershell
Test-Path README.md
Test-Path docs\portfolio\assets-manifest.md
Test-Path scripts\check-portfolio-docs.ps1

.\scripts\check-portfolio-docs.ps1

Select-String -Path README.md -Pattern "本地优先|LangGraph|citation|确认|撤销|限制|验证|隐私|许可证"
~~~

### 禁止事项

- 不写“生产级、企业级、完全自主、零幻觉”等不可证实措辞。
- 不把计划任务、假数据或 mock 路径描述成已完成能力。
- 不暴露本机用户名、绝对隐私路径、token、provider key 或真实 Vault 内容。
- 不用动态图、徽章和装饰淹没核心证据。
- 不复制大段源码凑篇幅。

### 证据产物

- README.md
- docs/portfolio/assets-manifest.md
- output/verification/task-1001/readme-claim-audit.md
- output/verification/task-1001/link-check.txt
- output/verification/task-1001/verification-record.md

---

## TASK-1002：CASE_STUDY 案例研究

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0904、TASK-0905、TASK-0906
- 要求等级：L2 + L4
- 目标：用问题、约束、决策、失败、指标和证据讲清项目，而不是把技术栈罗列成流水账。

### 允许修改文件

- 新建 CASE_STUDY.md
- docs/portfolio/ 下与案例研究直接相关的静态图表
- output/verification/task-1002/
- 产品源码只读

### 固定章节

1. 项目背景与目标用户。
2. 为什么选择本地优先、Electron、FastAPI、SQLite/FTS5、Markdown Vault、LangGraph。
3. 两条黄金链与真实运行链。
4. 多角色工作流如何分工，哪些节点是模型、确定性策略或存储服务。
5. negotiation 的边界、预算和失败降级。
6. 高风险动作为什么必须确认，账本和撤销如何实现。
7. Renderer、Electron main、sidecar、provider 和 Vault 的安全边界。
8. 前端从“功能堆叠”到结果优先的改造过程。
9. 至少三个真实问题：症状、根因、错误尝试、最终方案和防回归证据。
10. 性能与质量数据，包含基线、修改后、样本和限制。
11. 没有完成的能力和下一步选择。
12. 面试官可在十分钟内复现的检查清单。

### 执行步骤

1. 只从 claim matrix、verification 记录、代码和当前测试提取事实。
2. 为每项架构决策写出至少一个被放弃方案和放弃原因。
3. 至少选取一个 Agent 编排问题、一个安全边界问题和一个 UI/性能问题做深挖。
4. 每个问题都链接到源文件、测试或 verification 记录；引用代码只保留必要片段。
5. 用 TASK-0905 同口径数据制作前后对比，不允许用不同数据量制造提升。
6. 明确“确定性 Action Planner”是安全取舍，而不是伪装成 LLM Agent。
7. 明确 negotiation、checkpointer、live provider 和 Full Live2D 的当前状态。
8. 邀请一名不了解项目的人按文章完成十分钟复现，并记录误解点。
9. 根据 L4 反馈只修叙事和导航，不改写事实。

### DoD

- [ ] 案例研究能独立说明业务问题、技术难点和个人贡献。
- [ ] 至少三个问题具有完整根因和验证闭环。
- [ ] 每个关键声明至少有一个证据链接。
- [ ] 指标前后口径一致，未达预算的结果也保留。
- [ ] 模型节点、确定性逻辑和存储服务没有混称 Agent。
- [ ] 明确写出失败、限制和仍未解决的风险。
- [ ] 陌生测试者能在十分钟内找到运行和证据入口。
- [ ] 用户批准最终叙事。

### 验证命令

~~~powershell
Test-Path CASE_STUDY.md
.\scripts\check-portfolio-docs.ps1

Select-String -Path CASE_STUDY.md -Pattern "问题背景|架构决策|黄金链|LangGraph|安全边界|根因|验证|性能|限制|个人贡献"
~~~

### 禁止事项

- 不编造用户量、线上 SLA、商业收益或团队规模。
- 不把整个仓库的贡献默认归为个人；协作或 AI 辅助必须如实描述。
- 不只写最终成功，必须保留关键失败和决策取舍。
- 不粘贴思维链、真实聊天隐私或 credential。

### 证据产物

- CASE_STUDY.md
- output/verification/task-1002/claim-to-evidence.md
- output/verification/task-1002/external-reader-notes.md
- output/verification/task-1002/verification-record.md

### 用户确认

用户必须批准个人贡献、公开指标、失败叙事和最终版本。

---

## TASK-1003：系统、运行链与安全边界图

- 状态：Planned
- 优先级：P0
- 依赖：TASK-0707、TASK-0903、TASK-0906
- 要求等级：L2
- 目标：用可审计的图回答“组件如何通信、Agent 如何流转、数据在哪里、谁能访问什么”。

### 允许修改文件

- 新建 docs/portfolio/architecture.md
- 新建 docs/portfolio/diagrams/
- scripts/check-portfolio-docs.ps1
- output/verification/task-1003/
- 产品源码只读

### 必须交付的图

1. 系统上下文图：用户、Electron Renderer、main/preload、FastAPI sidecar、模型 provider、SQLite、Vault。
2. 黄金链 A 时序图：请求、SSE、检索、证据复核、citation 和终止事件。
3. 黄金链 B 时序图：计划、风险、确认、执行、账本和撤销。
4. LangGraph 节点与条件边图：普通路径、negotiation 路径、预算出口和 fallback。
5. 信任边界图：进程边界、IPC、认证、远程出站、凭据所有者和禁止数据流。
6. 数据真相图：SQLite、FTS5、Markdown Vault、可选镜像以及写入/恢复关系。

### 执行步骤

1. 从实际入口、路由、graph builder、preload、main、API client 和存储代码反向画图。
2. 每个节点写真实模块路径，不使用只有概念没有代码归属的方框。
3. 为同步调用、SSE、IPC、文件访问、数据库访问和远程调用使用不同线型或标签。
4. 图中明确 Renderer 不持有 session token，Electron main 注入后端认证。
5. 图中明确 provider 只接收策略允许的内容，不把 SQLite/Vault 画成直接远程连接。
6. 普通图和 negotiation 图分开标注；未完成的可选 checkpointer 使用“未启用”样式。
7. Mermaid 源文件必须可在 Markdown 中渲染；若导出 SVG，保留源文件和生成命令。
8. 对每条跨边界箭头建立 architecture-edge-audit.md，记录发送方、接收方、协议、认证和代码证据。

### DoD

- [ ] 六张图齐全且能在常用 Markdown 查看器中阅读。
- [ ] 每个运行节点有真实代码路径。
- [ ] 每条跨信任边界数据流有协议和认证说明。
- [ ] 普通图、negotiation、reflection 和可选 checkpointer 没有混成一条虚假主链。
- [ ] SQLite、FTS5、Vault 和镜像的真相关系准确。
- [ ] 图与 TASK-0903 安全验证及 TASK-0906 宣称一致。
- [ ] 文档检查脚本通过。

### 验证命令

~~~powershell
Test-Path docs\portfolio\architecture.md
Get-ChildItem docs\portfolio\diagrams -File | Select-Object Name,Length
.\scripts\check-portfolio-docs.ps1

Select-String -Path docs\portfolio\architecture.md -Pattern "Renderer|preload|Electron main|FastAPI|SSE|LangGraph|SQLite|FTS5|Vault|provider|信任边界"
~~~

### 禁止事项

- 不用架构愿景替代当前运行事实。
- 不省略 Electron main/preload 或把 Renderer 画成直接访问 FS。
- 不把向量/图镜像画成用户可见真相。
- 不在图中展示真实 token、主机私有路径或 provider key。

### 证据产物

- docs/portfolio/architecture.md
- docs/portfolio/diagrams/*
- output/verification/task-1003/architecture-edge-audit.md
- output/verification/task-1003/verification-record.md

---

## TASK-1004：隔离 Demo、脚本、视频与字幕

- 状态：Planned
- 优先级：P0
- 依赖：TASK-1001、TASK-1002、TASK-1003
- 要求等级：L3 + L4
- 目标：让面试官不接触作者真实数据和凭据，也能稳定看到两条黄金链及失败边界。

### 允许修改文件

- 新建 scripts/portfolio-demo.ps1
- 新建 scripts/portfolio-demo-cleanup.ps1
- 新建 fixtures/portfolio-demo/，内容必须完全合成且可公开
- 新建 docs/portfolio/demo-guide.md
- 新建 docs/portfolio/media/，仅保存经用户批准的压缩成片、字幕、封面和 manifest
- Demo 必需的局部产品修复必须退回对应 TASK，不在本任务新增业务能力
- output/verification/task-1004/

### 固定演示脚本

1. 30 秒：产品定位与本地优先边界。
2. 90 秒：黄金链 A，提出一个必须检索本地材料才能回答的问题，展示 citation 和 evidence review。
3. 90 秒：黄金链 B，创建低风险任务，再展示高风险动作在确认前被阻断，最后查看账本和撤销。
4. 45 秒：开发者视图展示有界 Agent trace、预算与 fallback，不暴露原始 prompt 或思维链。
5. 45 秒：断开 provider 或注入超时，展示可理解错误和本地能力保留。
6. 30 秒：架构、安全边界、测试和限制。
7. 总时长目标 4 至 6 分钟；另准备 60 秒无旁白速览版。

### 执行步骤

1. 创建固定合成 Vault、SQLite 初始化输入、预期 citation、任务和记忆 fixture；不得复制真实个人数据。
2. portfolio-demo.ps1 只在 .tmp/portfolio-demo-* 创建状态，选择可用隔离端口，记录其创建的 PID 和 manifest。
3. 脚本预检 Python、Node、依赖目录、端口、构建资源和 fixture hash；不自动安装依赖。
4. 启动失败时输出可操作诊断；清理脚本只终止 manifest 中由本次脚本创建且进程签名匹配的 PID。
5. 为黄金链 A/B 和 provider 失败建立可重复场景；每次运行验证预期事件、citation、账本和目标状态。
6. 录制前清空通知、用户名、绝对路径、系统托盘隐私信息和 provider 账户信息。
7. 录制 1920×1080 主版本和适合招聘平台的 1080p 压缩版，保证中文可读。
8. 字幕同时提供 zh-CN.srt 和 en.srt；技术名词与 claim matrix 一致。
9. media-manifest.md 记录文件 hash、时长、分辨率、录制日期、版本、数据为合成 fixture。
10. 由陌生测试者仅按 demo-guide.md 完整运行一次并签署 L4。

### DoD

- [ ] 一条命令可创建隔离 Demo，且不读写真实 Vault 或默认数据库。
- [ ] 脚本只清理自己创建的进程和状态。
- [ ] 黄金链 A/B 连续三次结果一致，citation 和账本可核验。
- [ ] provider 失败场景不会伪造成功。
- [ ] Demo 结束后 check-trial-processes 无本次残留。
- [ ] 主视频、60 秒版、中英文字幕和 manifest 齐全。
- [ ] 视频中的界面、指标和能力与当前 RC 一致。
- [ ] 陌生测试者仅靠文档完成演示。

### 验证命令

~~~powershell
.\scripts\portfolio-demo.ps1 -Scenario GoldenPathA -WorkDir .\.tmp\portfolio-demo-a
.\scripts\portfolio-demo-cleanup.ps1 -Manifest .\.tmp\portfolio-demo-a\process-manifest.json

.\scripts\portfolio-demo.ps1 -Scenario GoldenPathB -WorkDir .\.tmp\portfolio-demo-b
.\scripts\portfolio-demo-cleanup.ps1 -Manifest .\.tmp\portfolio-demo-b\process-manifest.json

.\scripts\portfolio-demo.ps1 -Scenario ProviderFailure -WorkDir .\.tmp\portfolio-demo-failure
.\scripts\portfolio-demo-cleanup.ps1 -Manifest .\.tmp\portfolio-demo-failure\process-manifest.json

.\scripts\check-trial-processes.ps1
.\scripts\check-portfolio-docs.ps1
~~~

### 禁止事项

- 不自动绑定真实 Vault、读取默认数据库或使用真实聊天记录。
- 不在视频中显示用户名、绝对私有路径、token、key、通知或账户信息。
- 不通过剪辑把失败路径伪装为成功连续运行。
- 不硬编码 citation、账本 receipt 或 Agent trace。
- 不杀死脚本未创建的进程。
- 不提交未获授权的音乐、字体、Live2D 模型或其他素材。

### 证据产物

- scripts/portfolio-demo.ps1
- scripts/portfolio-demo-cleanup.ps1
- fixtures/portfolio-demo/
- docs/portfolio/demo-guide.md
- docs/portfolio/media/media-manifest.md
- output/verification/task-1004/three-run-summary.md
- output/verification/task-1004/external-runner-notes.md
- output/verification/task-1004/verification-record.md

### 用户确认

录屏、公开成片、字幕措辞、素材许可和 L4 必须由用户确认。

---

## TASK-1005：中英文简历与面试材料

- 状态：Planned
- 优先级：P0
- 依赖：TASK-1002、TASK-1003、TASK-1004
- 要求等级：L2 + L4
- 目标：把项目事实转成可追问、可量化、可在面试中现场证明的简历要点。

### 允许修改文件

- 新建 docs/portfolio/resume/project-zh.md
- 新建 docs/portfolio/resume/project-en.md
- 新建 docs/portfolio/resume/interview-playbook-zh.md
- 新建 docs/portfolio/resume/interview-playbook-en.md
- 新建 docs/portfolio/resume/claim-evidence-index.md
- output/verification/task-1005/
- 产品源码只读

### 必须交付的材料

1. 中文简历：80 字版、150 字版、三条 bullet 版。
2. 英文简历：one-line、short paragraph、three bullets。
3. 30 秒、2 分钟和 5 分钟项目介绍。
4. 一页系统设计讲解顺序。
5. 至少 20 个追问题及基于证据的答案。
6. 至少 8 个反问或质疑：为什么 LangGraph、为何不全用 Agent、怎样避免幻觉、如何确认和撤销、为何 Electron、安全边界、性能、checkpointer 状态。
7. 现场 Demo 成功路线和无网络/模型失败备用路线。
8. claim-evidence-index：每一句可公开声明对应源码、测试、指标或视频时间点。

### 执行步骤

1. 根据目标岗位分别生成“AI/Agent 后端版”和“AI 全栈版”，不生成与事实无关的纯算法包装。
2. 每条 bullet 使用“动作 + 难点 + 方案 + 可验证结果”，限制在一到两行。
3. 只使用 TASK-0905 与 TASK-0906 已批准的数字；没有基线时用结构性结果，不捏造百分比。
4. 区分个人设计、AI 辅助、第三方框架和开源资源，避免归属误导。
5. 英文材料采用自然技术表达，不逐字翻译中文长句。
6. 追问题答案必须包含取舍和失败边界，不背诵框架定义。
7. 进行一次 30 分钟模拟面试：10 分钟介绍、15 分钟追问、5 分钟 Demo。
8. 记录回答不清、证据找不到、宣传过度和 Demo 卡顿点，再修材料。

### DoD

- [ ] 中英文两种岗位版本齐全。
- [ ] 每条简历声明可在 claim-evidence-index 中定位证据。
- [ ] 所有数字具备数据量、机器、样本和日期口径。
- [ ] 明确区分多角色工作流、有界协商和未实现的恢复能力。
- [ ] 20 个追问答案包含具体代码或验证入口。
- [ ] 无网络备用路线不依赖伪造 live provider 结果。
- [ ] 完成一次计时模拟面试并修正主要问题。
- [ ] 用户批准最终简历措辞。

### 验证命令

~~~powershell
Get-ChildItem docs\portfolio\resume -File | Select-Object Name,Length
.\scripts\check-portfolio-docs.ps1

Select-String -Path docs\portfolio\resume\*.md -Pattern "LangGraph|citation|风险|确认|撤销|证据|限制"
~~~

### 禁止事项

- 不写虚构用户数、线上可用性、商业转化、团队人数或性能提升。
- 不把 LangChain/LangGraph 名称本身当成果。
- 不把 deterministic planner、service 或 tool adapter 全称为自治 Agent。
- 不把计划中的 checkpointer、HITL 或 fan-out 写入完成项。
- 不隐瞒 AI 辅助开发或第三方素材归属。

### 证据产物

- docs/portfolio/resume/*
- output/verification/task-1005/mock-interview-notes.md
- output/verification/task-1005/resume-claim-audit.md
- output/verification/task-1005/verification-record.md

### 用户确认

岗位方向、个人贡献、数字、英文措辞和最终简历版本必须由用户确认。

---

## TASK-1006：隐私、许可证与公开发布门禁

- 状态：Planned
- 优先级：P0
- 依赖：TASK-1001 至 TASK-1005
- 要求等级：L4
- 目标：在仓库、视频或简历公开前，阻止凭据、个人数据、未授权素材、数据库和误导声明外泄。

### 允许修改文件

- README.md、CASE_STUDY.md 的公开边界修订
- LICENSE、NOTICE、THIRD_PARTY_NOTICES.md；许可证选择必须由用户确认
- .gitignore 与打包排除规则的必要加固
- scripts/check-repo-hygiene.ps1
- scripts/check-portfolio-docs.ps1
- 新建 docs/portfolio/public-release-checklist.md
- output/verification/task-1006/
- 不删除、不移动、不改写用户本地状态；发现问题只报告路径和类型

### 执行步骤

1. 使用 git ls-files 和实际目录检查被跟踪、未跟踪、ignored 的数据库、日志、credential、环境文件、真实 Vault 和录屏源文件。
2. 扫描文本和 Git 跟踪清单中的凭据形态；输出只保留文件、行号和类别，命中值必须遮盖。
3. 检查 Electron package resource 清单，确认不包含 SQLite、日志、测试状态、真实 Vault、开发密钥或未授权素材。
4. 建立第三方清单：Python/npm 包、图标、字体、Live2D/Cubism SDK、模型、音频、图片和生成素材；记录许可证、来源、是否允许再分发。
5. 对无法证明再分发权的素材设置公开包排除，并在 README 给出用户自行获取方式；不得擅自补一个许可证。
6. 检查截图、视频、字幕和文档中的用户名、绝对路径、账户、通知、聊天隐私、机器标识和密钥痕迹。
7. 逐条审计 README、CASE_STUDY、架构图、简历和视频字幕是否与最终 claim matrix 一致。
8. 运行全量发布前验证并生成 public-release-checklist.md，逐项给出 Pass、Partial、Blocked 或 Not applicable 以及证据。
9. 用户逐项决定公开仓库、公开视频、公开简历和二进制包；四者授权互相独立。

### DoD

- [ ] tracked 文件中没有数据库、日志、credential、真实 Vault 或个人聊天数据。
- [ ] package resource 中没有本地状态或禁止素材。
- [ ] 所有公开素材有明确来源和再分发结论。
- [ ] 隐私扫描结果经过遮盖，不在证据中复制命中值。
- [ ] README、案例、简历、视频和图的 claim 一致。
- [ ] 无法确认许可证的资源已从公开范围排除。
- [ ] 用户分别批准仓库、视频、简历和二进制公开范围。
- [ ] 未通过门禁时结论必须是 No-Go。

### 验证命令

~~~powershell
git status --short
git ls-files

.\scripts\check-repo-hygiene.ps1
.\scripts\check-portfolio-docs.ps1

Push-Location apps\desktop
npm run package:check
node scripts\validate-electron-migration.mjs
Pop-Location

.\scripts\check-mvp-acceptance-gap.ps1
~~~

### 禁止事项

- 不输出、复制或提交任何真实 credential 命中值。
- 不把 .gitignore 当成“从未被跟踪”的证据。
- 不擅自删除历史、本地数据库、录屏源文件或真实 Vault。
- 不把“仅供学习”当成第三方素材再分发许可。
- 不因赶投递而绕过 No-Go。

### 证据产物

- LICENSE、NOTICE、THIRD_PARTY_NOTICES.md 中适用于当前项目的文件
- docs/portfolio/public-release-checklist.md
- output/verification/task-1006/tracked-file-audit.md
- output/verification/task-1006/package-resource-audit.md
- output/verification/task-1006/third-party-assets-audit.md
- output/verification/task-1006/claim-consistency-audit.md
- output/verification/task-1006/verification-record.md

### 用户确认

许可证选择、素材排除、仓库公开、视频公开、简历公开和二进制发布必须分别确认；任一项未确认都不得代替用户做决定。

---

# Phase 11：可选高级能力（不阻塞求职作品集）

> 本阶段不是“技术名词加分包”。只有评测、架构必要性和用户授权同时成立时才实施。未执行本阶段不影响 G7；未完成的能力不得写入当前简历。

## TASK-1101：小型 Agent 质量评测集

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0707、TASK-0906
- 要求等级：L2
- 目标：用固定样本衡量意图、检索、citation、风险策略、预算和降级质量，防止只凭单次 Demo 调 prompt。

### 允许修改文件

- 新建 apps/backend/tests/evals/
- 新建 apps/backend/tests/test_agent_quality_eval.py
- 新建 scripts/run-agent-eval.ps1
- 新建 docs/evals/agent-quality-rubric.md
- 新建 docs/evals/agent-quality-baseline.md
- 仅为可测性修改 apps/backend/app/agents/ 和直接相关服务；不得在本任务改变产品行为
- output/verification/task-1101/

### 固定评测集

至少 40 个完全合成、可公开、版本化样本：

- 8 个意图分类与上下文歧义样本；
- 10 个检索、证据充足性与 citation 样本；
- 6 个空检索、矛盾证据与过期证据样本；
- 10 个任务/记忆动作、风险、敏感输入和确认样本；
- 6 个超时、预算耗尽、tool 失败、SSE 终止和 fallback 样本。

每个样本必须包含输入、隔离 fixture、允许事实、禁止事实、预期路径、预期工具、风险级别、终止状态和评分规则。不得保存真实用户输入。

### 执行步骤

1. 冻结 eval schema 和 rubric，再生成样本；样本修改必须变更数据集版本。
2. 优先使用 deterministic/fake model 路径测试合同；live provider 结果单独报告，不能覆盖 deterministic 基线。
3. 为开放式回答采用可审计 rubric：事实支持、citation 正确、遗漏、越权动作和拒绝质量；不使用“看起来不错”评分。
4. 自动检查 citation 指向真实 fixture、空检索不声称本地事实、高风险确认前零写入、done/error 互斥、预算必然终止。
5. 对需要人工评分的回答隐藏运行配置并双次独立评分；分歧写入 adjudication 记录。
6. 输出总体结果和按场景分桶结果；保留失败样本编号和最小复现，不只报告平均分。
7. 建立基线后，任何 Agent prompt、graph edge、tool contract 或风险策略改动都必须复跑。

### 通过阈值

- 高风险确认前写入：0 次。
- 敏感 fixture 发送到远程模型：0 次。
- citation 指向不存在或不支持结论的来源：0 次。
- 空检索伪造本地事实：0 次。
- 同一 run 出现多个互斥终止事件：0 次。
- 预算或超时样本按上限终止：100%。
- 确定性意图/路由合同准确率：至少 95%。
- 开放式回答事实支持率：至少 90%，并同时列出人工评分一致性。

任何安全型阈值未达成均为失败，不得用总体平均分抵消。

### DoD

- [ ] 至少 40 个版本化合成样本覆盖五类场景。
- [ ] rubric 能由第二名执行者复现。
- [ ] deterministic 基线和 live provider 结果分离。
- [ ] 报告包含每个失败样本而非只给总分。
- [ ] 安全型指标全部达到零违规。
- [ ] eval 脚本在隔离目录运行且不要求真实 key。
- [ ] 数据集、脚本、报告和命令具备版本/hash。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests\test_agent_quality_eval.py
Pop-Location

.\scripts\run-agent-eval.ps1 -Mode Deterministic -OutputDir .\output\evals\task-1101
~~~

### 禁止事项

- 不使用真实聊天、真实 Vault 或真实个人任务作为样本。
- 不让被评系统看到 gold answer 或评分字段。
- 不只保留通过样本、不手工删除失败运行。
- 不用 live provider 的随机波动替代确定性合同测试。
- 不为提高分数弱化高风险策略或 citation 条件。

### 证据产物

- apps/backend/tests/evals/*
- docs/evals/agent-quality-rubric.md
- docs/evals/agent-quality-baseline.md
- output/verification/task-1101/eval-run-manifest.md
- output/verification/task-1101/verification-record.md

---

## TASK-1102：Agent Registry 运行时能力契约

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0704、TASK-0707
- 要求等级：L2
- 目标：让 Agent 名称、职责、输入输出、工具、预算和隐私边界成为运行时单一事实来源，消除“UI 有配置但 graph 不使用”的假能力。

### 允许修改文件

- apps/backend/app/agents/
- apps/backend/app/models/ 中直接相关契约
- apps/backend/app/services/ 中 Agent 设置映射
- apps/backend/app/api/ 中只读能力查询路由
- apps/backend/tests/ 中对应 Agent、API 和安全测试
- apps/desktop/src/ 中现有开发者 Agent 视图；仅从后端只读契约渲染
- output/verification/task-1102/
- 不修改 SQLite schema

### 运行时契约字段

每个可运行角色必须有：

- 稳定 `agent_id` 与面向用户的显示名；
- 单一职责和明确非职责；
- 输入/输出类型或 schema；
- 允许工具和禁止工具；
- 是否允许远程模型及允许发送的数据类别；
- 默认模型类别、超时、调用、token 和轮次预算；
- 可进入的 graph 节点和可达终点；
- trace 中公开的安全 label；
- fallback 与失败代码；
- 是否可由用户配置，以及可配置字段白名单。

### 执行步骤

1. 盘点 semantic、supervisor、retrieval、evidence review、chat、planner、executor、reflection 等真实角色，删除只存在于展示层的运行时宣称。
2. 定义不可变 registry contract；graph builder、预算器、trace label 和能力查询从同一 registry 读取。
3. 保留 deterministic planner/service 的真实类型，不为统一命名伪装成模型 Agent。
4. 设置层只能修改白名单字段；用户输入不得决定 Python import、任意工具名、文件路径或系统 prompt 文件。
5. 后端提供受认证的只读 capability snapshot，过滤内部 prompt、凭据、绝对路径和敏感工具参数。
6. 开发者 UI 显示“已接入运行时”和“仅规划/未启用”状态，不把保存成功等同于 graph 已启用。
7. 添加一致性测试：registry 角色、graph node、trace label、UI capability 不得漂移。
8. 添加负面测试：未知 Agent、未知工具、越权配置、超预算值和敏感字段均被拒绝。

### DoD

- [ ] registry 是 graph、预算和公开 capability 的单一事实来源。
- [ ] 每个 graph 角色的输入输出、工具、预算和隐私边界明确。
- [ ] deterministic 组件没有被改名冒充模型 Agent。
- [ ] UI 不再展示未接入运行时的可编辑假开关。
- [ ] capability API 不泄露 prompt、credential 或内部绝对路径。
- [ ] 未知/越权配置被拒绝且有稳定错误代码。
- [ ] 后端聚焦测试、API 安全测试和前端 typecheck 通过。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests\test_agent_runtime.py tests\test_security_contracts_api.py tests\test_api_wiring_mvp.py
Pop-Location

Push-Location apps\desktop
npm run typecheck
npm test
node scripts\validate-electron-migration.mjs
Pop-Location
~~~

### 禁止事项

- 不允许 registry 动态 import 用户指定模块。
- 不让 Renderer 修改系统 prompt、工具实现或权限边界。
- 不通过 registry 将 session token 或 provider credential 返回前端。
- 不为追求“多 Agent”拆分无独立职责的节点。
- 不改 schema 或安装插件系统依赖。

### 证据产物

- agent-registry-contract.md
- registry-graph-consistency.txt
- capability-redaction-test.txt
- output/verification/task-1102/verification-record.md

---

## TASK-1103：Checkpointer/HITL ADR

- 状态：Planned
- 优先级：P1
- 依赖：TASK-0707、TASK-0906
- 要求等级：L2 + Human Gate
- 目标：先证明跨进程恢复和 LangGraph interrupt 的产品价值、数据边界与迁移成本，再决定是否实施。

### 允许修改文件

- 新建 docs/adr/ADR-agent-checkpointer-hitl.md
- 新建 output/verification/task-1103/
- 所有产品源码、依赖锁、migration 和数据库只读

### ADR 必答问题

1. 当前确认流程为何不足，哪些场景真正需要跨进程暂停/恢复。
2. thread、run、message、checkpoint 和 action ledger 的身份及生命周期。
3. checkpoint 保存哪些字段、明确不保存哪些字段。
4. SQLite 放置位置、schema 所有权、migration、版本兼容、并发和崩溃语义。
5. session token、provider key、原始 prompt、模型输出、工具参数和隐私数据的处理。
6. checkpoint 与现有 tasks、memory、agent_actions、SSE reconnect 的一致性关系。
7. 用户批准、拒绝、超时、应用重启、重复 resume 和陈旧 checkpoint 的状态机。
8. 数据保留、删除、导出和可观测性策略。
9. 采用 LangGraph SQLite saver、自建适配器或不实施的对比。
10. 回滚方案、测试矩阵、依赖与 migration 影响。

### 执行步骤

1. 读取当前 LangGraph 版本、graph state、action confirmation、SQLite migration 和 Electron 生命周期代码。
2. 画出现状状态机和候选 interrupt/resume 状态机。
3. 用至少五个真实产品场景评估价值：高风险确认、长工具任务、应用重启、断网重连和重复提交。
4. 对三个候选方案按复杂度、安全、恢复语义、可测试性、维护和简历价值评分。
5. 明确 schema/依赖变更清单，不执行安装、不创建 migration。
6. 给出 Adopt、Defer 或 Reject 单一建议以及触发重新评估的条件。
7. 用户审阅并明确批准或拒绝进入 TASK-1104。

### DoD

- [ ] ADR 覆盖十个必答问题。
- [ ] 当前确认机制与候选 HITL 的差异可验证。
- [ ] 数据最小化和敏感字段排除列表明确。
- [ ] migration、依赖、兼容、回滚和测试成本明确。
- [ ] 有唯一建议而非模糊罗列。
- [ ] 用户决定已记录。
- [ ] 没有修改代码、依赖、schema 或数据库。

### 验证命令

~~~powershell
Test-Path docs\adr\ADR-agent-checkpointer-hitl.md
Select-String -Path docs\adr\ADR-agent-checkpointer-hitl.md -Pattern "Adopt|Defer|Reject|migration|敏感|恢复|回滚|重复|超时|SSE"
git status --short
~~~

### 禁止事项

- 不在 ADR 任务安装依赖、建表或运行迁移。
- 不把 checkpointer 等同于长期记忆。
- 不保存思维链、credential 或未经必要性审查的完整工具参数。
- 不因简历好听而默认选择 Adopt。

### 证据产物

- docs/adr/ADR-agent-checkpointer-hitl.md
- output/verification/task-1103/option-scorecard.md
- output/verification/task-1103/user-decision.md
- output/verification/task-1103/verification-record.md

### 用户确认

必须由用户选择 Adopt、Defer 或 Reject。只有 Adopt 才能使 TASK-1104 进入 Ready。

---

## TASK-1104：SQLite Checkpointer 实施

- 状态：Planned
- 优先级：P2
- 依赖：TASK-1103 的 Adopt 决定与用户对依赖/schema 的明确批准
- 要求等级：L2 + L3
- 目标：以 migration 管理、最小化持久化和可恢复测试，为被中断的 Agent run 提供跨进程 checkpoint。

### 开始前强制确认

Coordinator 必须先向用户展示并取得确认：

- 精确新增/变更的 Python 依赖及锁文件；
- 精确 migration 文件和表/索引；
- checkpoint 数据字段、保留期限和删除方式；
- 回滚方案和现有数据库兼容策略；
- 隔离 L3 测试将创建的临时状态。

任一项未批准，任务保持 Planned 或 Human Gate。

### 允许修改文件

- 经批准的 Python 依赖声明与锁定文件
- 新增 apps/backend/migrations/NNN_agent_checkpoints.sql；编号必须以执行时最高 migration 后继值为准
- apps/backend/app/agents/ 的 checkpointer adapter 与 graph 装配
- apps/backend/app/models/、services/、api/ 中恢复所需最小契约
- apps/backend/tests/test_agent_checkpointer.py 及相关持久化、安全、API 测试
- 新建 scripts/verify-agent-checkpoint-resume.ps1
- output/verification/task-1104/
- 不直接编辑任何 .db/.sqlite3 文件

### 持久化边界

- 使用不可猜测的 run/thread 标识，并绑定本地用户会话与图版本。
- 只保存恢复所需的结构化 state、节点位置、版本、时间和幂等标识。
- 不保存 session token、provider key、Authorization、私钥、思维链或未遮盖的敏感工具参数。
- checkpoint 与业务真相分离：任务、记忆、Wiki 和账本仍由现有仓库负责。
- schema 只能由 migration 创建；启动时不得绕过 MigrationRunner 临时建表。

### 执行步骤

1. 记录当前最高 migration 与 LangGraph/SQLite 版本，按 ADR 实施已批准方案。
2. 新增向前 migration、模型/仓库适配和 graph checkpointer 注入；旧数据库升级后仍可启动。
3. 定义 graph_version 与 state_version；不兼容 checkpoint 返回稳定错误并保留业务数据。
4. 使 checkpoint 写入与 action ledger 幂等：进程在工具前、工具后或事件发送中崩溃都不得重复副作用。
5. 提供受认证的最小查询/清理能力；清理是高风险状态操作，必须确认且仅处理 checkpoint，不删除业务真相。
6. 单测覆盖保存、读取、版本、隔离、敏感字段过滤、并发、损坏行和旧 schema。
7. L3 脚本在 .tmp 中启动隔离 sidecar，运行至 checkpoint，终止本次创建的进程，重启并恢复到唯一终态。
8. 验证重复恢复、过期恢复和 graph 版本不匹配不会重复写任务、记忆或账本。
9. 跑后端全量、migration、API、安全和隔离恢复验证。

### DoD

- [ ] 依赖与 schema 变更均有用户批准记录。
- [ ] 新旧隔离数据库都能通过 MigrationRunner 启动。
- [ ] checkpoint 不包含禁止敏感字段。
- [ ] 正常恢复、重复恢复、过期恢复和版本不兼容具有确定行为。
- [ ] 崩溃点前后均不重复执行副作用。
- [ ] L3 跨进程恢复至少连续三次通过。
- [ ] 全量后端测试通过，或所有既有失败被原样记录并证明非本任务引入。
- [ ] 回滚不删除任务、记忆、Wiki 或 action ledger。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests\test_agent_checkpointer.py tests\test_persistence_mvp.py tests\test_api_wiring_mvp.py tests\test_security_contracts_api.py
python -m pytest -q
Pop-Location

.\scripts\verify-agent-checkpoint-resume.ps1 -WorkDir .\.tmp\task-1104 -Port 8767 -Runs 3
.\scripts\check-trial-processes.ps1
~~~

### 禁止事项

- 未经确认不得安装依赖或修改 schema。
- 不手改 SQLite 文件、不删除现有 migration、不复用已发布 migration 编号。
- 不持久化思维链、真实 credential 或全量隐私 payload。
- 不用 checkpoint 表替代业务仓库或 action ledger。
- 不停止测试脚本未创建的进程。
- L3 未通过不得宣传跨进程恢复。

### 证据产物

- migration-design.md
- checkpoint-field-audit.md
- crash-point-matrix.md
- three-run-resume-summary.md
- output/verification/task-1104/verification-record.md

### 用户确认

依赖、schema、保留/删除策略和任何真实状态迁移均必须确认。本任务只允许在 .tmp 隔离数据库上做 L3。

---

## TASK-1105：LangGraph interrupt/resume

- 状态：Planned
- 优先级：P2
- 依赖：TASK-1104
- 要求等级：L2 + L3
- 目标：让高风险 Agent 动作在 graph 内真正暂停，并由同一受认证会话批准或拒绝后安全恢复。

### 开始前强制确认

用户必须批准：首批 interrupt 动作白名单、确认 UI 文案、超时、拒绝、过期和应用重启语义。未批准不得实施。

### 允许修改文件

- apps/backend/app/agents/ 的 interrupt/resume 节点与状态
- apps/backend/app/api/、models/、services/ 的最小 run 查询和 resume 合同
- apps/backend/tests/test_agent_interrupt_resume.py 及相关 Agent/API/安全测试
- apps/desktop/src/services/ 的受保护 API/SSE 客户端
- apps/desktop/src/ 中现有确认 UI 和 Agent trace
- Electron main/preload；仅在现有代理边界需要最小扩展时修改
- 新建 scripts/verify-agent-interrupt-resume.ps1
- output/verification/task-1105/
- 不新增 schema；沿用 TASK-1104 已批准结构

### 状态机

~~~text
running
→ pending_confirmation
→ approved → resuming → completed | failed
→ rejected → cancelled
→ expired → cancelled
~~~

每次确认必须绑定 run、checkpoint、动作摘要、目标、风险、发起消息和一次性 decision id。批准与拒绝都是不可歧义的终态转换；重复请求返回原结果，不重复副作用。

### 执行步骤

1. 只选择 ADR 批准的高风险动作接入 interrupt；低风险自动整理保持现有策略。
2. graph 在任何副作用前调用 interrupt，持久化最小确认 payload，并发送安全 SSE 事件。
3. resume API 受 Electron main/backend 认证边界保护；Renderer 不接触 session token。
4. decision id 必须一次性、短期有效、绑定当前 checkpoint；陈旧、伪造、跨 run 和跨会话请求被拒绝。
5. 批准后重新校验策略、目标和 checkpoint 版本，不信任暂停前的外部状态。
6. 拒绝或过期生成可审计记录，但不修改目标；应用重启后仍能显示待确认项。
7. SSE 重连可恢复当前公开状态，不重复发送工具副作用；同一 run 最终只有一个终止事件。
8. UI 显示动作、目标、风险、可逆性和影响，不展示内部 prompt、思维链或敏感参数。
9. 覆盖批准、拒绝、超时、双击、并发决定、重启、断流、版本不匹配和 provider 失败。
10. L3 在隔离状态连续三次验证“暂停时零写入，批准后一次写入”和“拒绝后始终零写入”。

### DoD

- [ ] graph 确实在副作用前暂停，而非前端伪确认。
- [ ] 待确认状态可跨应用/sidecar 重启恢复。
- [ ] 批准、拒绝、超时、重复和陈旧 decision 有确定合同。
- [ ] 批准后副作用最多一次，拒绝/过期后为零。
- [ ] Renderer 不持有 token，resume API 通过安全合同。
- [ ] SSE 重连和终止事件互斥通过。
- [ ] UI 信息足够用户判断且不泄露敏感内部数据。
- [ ] L3 两类场景各连续三次通过。

### 验证命令

~~~powershell
Push-Location apps\backend
python -m pytest -q tests\test_agent_interrupt_resume.py tests\test_agent_checkpointer.py tests\test_security_contracts_api.py tests\test_e2e_backend_mvp.py
Pop-Location

Push-Location apps\desktop
npm run typecheck
npm test
node scripts\validate-electron-migration.mjs
Pop-Location

.\scripts\verify-agent-interrupt-resume.ps1 -WorkDir .\.tmp\task-1105 -Port 8767 -Runs 3
.\scripts\check-trial-processes.ps1
~~~

### 禁止事项

- 不在 interrupt 前执行目标写入。
- 不把确认权交给模型或自动点击。
- 不允许 decision 跨 run、跨 checkpoint 或重复使用。
- 不把原始 prompt、思维链、凭据或完整敏感参数送到 Renderer。
- 不为接入 LangGraph HITL 移除现有风险策略、账本或撤销。
- 不在真实 Vault 或默认数据库做验收。

### 证据产物

- interrupt-state-machine.md
- decision-security-audit.md
- restart-and-reconnect-matrix.md
- three-run-hitl-summary.md
- output/verification/task-1105/verification-record.md

### 用户确认

动作白名单、确认文案、过期语义、L3 结果和公开宣传必须由用户确认。

---

## TASK-1106：并行 fan-out 与成本路由评估

- 状态：Planned
- 优先级：P2
- 依赖：TASK-1101、TASK-1102
- 要求等级：L2 + Human Gate
- 目标：先测量并行 Agent 和复杂度路由是否提高质量/延迟/成本，再决定实施、延后或拒绝，禁止为了数量堆 Agent。

### 允许修改文件

- 第一阶段仅允许 docs/adr/、docs/evals/、apps/backend/tests/evals/、scripts/ 和 output/verification/task-1106/
- 只有用户批准 Implement 后，才允许修改 apps/backend/app/agents/、直接相关服务和测试
- 不修改 schema，不安装依赖，不改变高风险确认策略

### 候选方案

1. 顺序基线：现有 supervisor → retrieval → review → synthesis。
2. 有界 fan-out：仅对互相独立的数据源并行检索，随后由 evidence review 汇合。
3. 双 reviewer：仅对矛盾或低置信证据触发第二复核者。
4. 成本路由：简单聊天走 fast path；需要检索、动作或矛盾处理时进入完整 graph。
5. 不实施：质量收益不足、成本过高或失败面扩大时保持现状。

### 第一阶段：评估

1. 从 TASK-1101 选取至少 20 个代表样本，固定 provider/model/temperature、fixture 和机器。
2. 每个候选至少运行五次，记录端到端延迟、TTFT、本地耗时、模型调用数、输入/输出 token、估算成本、事实支持率、citation 和失败率。
3. provider 时间与本地编排时间分开；并行只在调用真实重叠时计为并行，不以日志相邻冒充。
4. 注入一个分支超时、一个分支错误和整体预算耗尽，验证取消、汇合和唯一终态。
5. 写出共享 state、并发写入、事件排序、trace 可读性和安全边界风险。
6. 给出 Implement、Defer 或 Reject 单一建议，并由用户决定。

### 实施门槛

同时满足以下条件才建议 Implement：

- 在目标场景事实支持率或 citation 完整性有稳定、可解释提升，或 p95 延迟至少下降 20%；
- 模型调用与估算成本增幅不超过用户批准预算；
- 高风险、敏感、终止互斥和预算测试零回归；
- 至少 80% 普通请求仍走更简单路径；
- 新增分支具有独立职责，且失败可降级到顺序基线。

### 第二阶段：仅在批准后实施

1. 只并行无共享写入的只读分支，合并点执行确定性去重和预算核算。
2. 为每个分支设置独立 timeout/cancel 和总预算；任一分支失败不得无限等待。
3. SSE 为并行事件携带 run、branch、sequence 和安全 label；终止事件仍全局唯一。
4. 复杂度路由必须可解释和可测试；用户文本不得直接指定任意 Agent 或工具。
5. 保留顺序 fallback 和 feature flag，默认值由评测结果决定并记录。
6. 复跑 TASK-1101 全集、黄金链、安全合同、性能和故障注入。

### DoD

- [ ] 至少 20 样本、每候选五次、同口径对比完成。
- [ ] 质量、延迟、TTFT、调用、token、成本和失败率均有分桶结果。
- [ ] 分支错误、取消、预算和唯一终态已验证。
- [ ] 给出 Implement、Defer 或 Reject 单一结论。
- [ ] 用户决定有记录；Defer/Reject 也可完成本评估任务。
- [ ] 若 Implement，满足全部门槛并保留顺序 fallback。
- [ ] 若 Implement，TASK-1101 全量评测和黄金链无安全回归。

### 验证命令

~~~powershell
.\scripts\run-agent-eval.ps1 -Mode Deterministic -OutputDir .\output\evals\task-1106-baseline
.\scripts\benchmark-agent-routing.ps1 -WorkDir .\.tmp\task-1106 -Runs 5 -OutputDir .\output\evals\task-1106

Push-Location apps\backend
python -m pytest -q tests\test_agent_quality_eval.py tests\test_agent_runtime.py tests\test_security_contracts_api.py
Pop-Location
~~~

若批准并实施，还必须执行：

~~~powershell
Push-Location apps\backend
python -m pytest -q
Pop-Location

.\scripts\verify-portfolio-golden-paths.ps1 -Scenario All -WorkDir .\.tmp\task-1106-golden -Port 8767
~~~

### 禁止事项

- 不以 Agent 数量作为成功指标。
- 不并行具有共享副作用的 action executor。
- 不让并行分支绕过总预算、风险策略或敏感数据过滤。
- 不用不同模型、fixture 或数据量比较候选。
- 不因已经写了代码而把不达门槛的方案上线。

### 证据产物

- docs/adr/ADR-agent-parallelism-cost-routing.md
- docs/evals/agent-routing-comparison.md
- output/verification/task-1106/run-manifest.md
- output/verification/task-1106/failure-injection.md
- output/verification/task-1106/user-decision.md
- output/verification/task-1106/verification-record.md

### 用户确认

用户必须选择 Implement、Defer 或 Reject，并批准最大调用、token、时间和估算成本预算。只有 Implement 才授权修改运行时。

---

# 附录 A：任务冲突、所有权与并行矩阵

并行只用于缩短等待时间，不能绕过依赖或让多个 Agent 争写同一文件。Coordinator 分配前必须先读取实际 dirty worktree，并把已有用户修改视为受保护内容。

| 工作波次 | 可并行条件 | 必须串行或独占的边界 | Coordinator 调度规则 |
| --- | --- | --- | --- |
| 基线（TASK-0601） | 只读盘点可分给多个 Agent | verification-record 只能一人汇总 | 子 Agent 只回报事实，不改产品源码、task.md、progress.md |
| TASK-0602 → 0603 | 0602 的代码盘点与文档草案可并行 | 用户批准 0602 后才能开始 0603 | claim matrix 由单一 Owner 合并 |
| TASK-0701 → 0702 → 0703 | 测试设计可与只读运行链审计并行 | graph_runtime.py、graph builder、state/event model 独占 | 每次 graph edge 改动后先跑聚焦测试再交接 |
| TASK-0704 与 0705 | 依赖满足后，检索服务与 action 服务可分开开发 | 若同时触及 graph_runtime.py、SSE event 或共享 state，必须串行 | Coordinator 明确 graph owner；另一 Agent 先写测试/审计 |
| TASK-0706 → 0707 | failure fixture 可提前只读设计 | reflection 托管、全局 event/error contract 串行 | 0707 只在 0703 至 0706 当前证据完成后汇总 |
| Shell（TASK-0801） | 不与其他结构性 UI 任务并行 | DesktopShell、Bottom Dock、安全区、全局 overflow 独占 | 先稳定 shell，再允许页面任务进入 |
| TASK-0802、0803、0805、0808、0810 | 拆到不同 view/component 文件后可并行 | App.tsx、DesktopFeatureRoutes、共享 nav、全局样式一次只允许一个 Owner | 无法隔离文件时按任务号串行，不做跨任务顺手重构 |
| TASK-0804、0806、0807、0809 | 前置页面完成且文件不重叠时可并行 | MemoryWindowView、聊天列表、设置保存服务分别独占 | 性能任务不得改另一页面的产品逻辑 |
| TASK-0811 → 0812 | 必须串行 | App.tsx 拆分与 desktop-polish.css 退役都是全局边界 | 暂停其他全局 UI/CSS 写入，保留可回滚小批次 |
| TASK-0813 与 0814 | 0812 完成后可并行做审计 | 同一组件修复不能并发；视觉修复与性能修复分别回原 Owner | L4 由真人签署，性能由固定基准证明 |
| TASK-0901、0902、0903 | 使用不同隔离目录和端口时可并行 | Electron packaged launch 与默认端口资源独占 | 每个脚本只清理自己创建的 PID |
| TASK-0904 与 0905 | 0901/0902 前置满足后可并行采证 | 若都修同一 UI 文件，退回对应 Phase 8 并串行 | 0906 等两者最终证据，不接受口头通过 |
| TASK-1001、1002、1003 | 0906 完成后可并行起草 | claim matrix、check-portfolio-docs.ps1 和公开数字由单一 Owner | 三份材料合并前执行 claim 一致性审计 |
| TASK-1004 → 1005 → 1006 | 视频编码可与字幕校对并行 | Demo 运行、简历定稿、公开门禁按顺序 | 公开授权不能由 Worker 代签 |
| TASK-1101 与 1102 | 可分别做 eval 与 registry | 若共同修改 graph contract，1102 独占，1101 只维护测试 | 两项都完成后才评估 1106 |
| TASK-1103 → 1104 → 1105 | 不允许实现阶段并行 | ADR、schema/checkpointer、interrupt/resume 严格串行 | 每个 Human Gate 都是独立授权，前一授权不自动覆盖后一项 |
| 高级评估（TASK-1106） | 评测运行可按候选分组并行 | fixture、provider、模型和测量口径必须一致；运行时实施单一 Owner | 先提交决策证据，用户选择 Implement 后才改运行时 |

## 共享热点文件独占表

| 热点 | 可能涉及任务 | 独占要求 |
| --- | --- | --- |
| apps/backend/app/agents/graph_runtime.py 与 graph builder | 0701-0706、1102、1104-1106 | 同一时间一个实现 Owner；其他 Agent 只读或写不重叠测试 |
| Agent state、SSE event 和 chat API contract | 0702-0707、0803、0901、1104-1106 | 先冻结合同，再分别改后端和客户端；合同变更必须一起验证 |
| action policy、confirmation、ledger、undo | 0705、0803、0810、0902、1105 | 不允许平行重写；安全测试 Owner 必须复核所有改动 |
| apps/desktop/src/App.tsx | 0801-0803、0805、0808、0810、0811 | TASK-0811 前一次只允许一个任务写入；禁止大范围格式化掩盖 diff |
| DesktopFeatureRoutes 与 Bottom Dock | 0603、0801、0811、0813、0814 | shell Owner 独占；页面 Agent 不改全局导航合同 |
| MemoryWindowView.tsx | 0805-0807、0811、0814 | 按 0805 → 0806 → 0807/0814 交接，不并发写 |
| desktop-polish.css、dashboard.css 与样式入口 | 0801-0814 | 不向 desktop-polish.css 追加新补丁；TASK-0812 期间冻结全局样式写入 |
| Electron main/preload/API proxy | 0703、0903、1004、1105 | 认证和 IPC Owner 独占；任何改动复跑 migration/package 安全检查 |
| README、CASE_STUDY、claim matrix、字幕和简历 | 0602、1001-1006 | 单一 claim Owner 维护公开措辞和数字 |
| task.md、progress.md | 所有任务 | 只有 Coordinator 可写；Worker 永远只读 |

### 并行交接协议

1. Coordinator 给每个 Worker 写明任务编号、允许文件、明确禁区、基线状态和期望回报。
2. Worker 开始前报告其将写入的精确文件；发现与其他修改重叠立即停止写入并上报。
3. Worker 不提交 task.md、progress.md，不修改其他任务状态，不宣布 Covered。
4. Worker 完成后提交文件清单、行为变化、命令完整输出、失败、残余风险和建议状态。
5. Coordinator 重新检查共享边界、运行必要的整体验证，再决定状态与后续 Gate。
6. 任何 cherry-pick、覆盖、回退或删除用户改动都需要 Coordinator 审核；不得用破坏性 Git 命令解决冲突。

---

# 附录 B：统一 verification-record 结构

以下变量是记录格式中的必填字段名，不代表可以省略内容。执行时必须用实际值替换每个变量，并保留失败输出。

~~~markdown
# Verification Record — ${TASK_ID}

## 元数据

- 任务编号：${TASK_ID}
- 任务名称：${TASK_NAME}
- 执行 Agent：${AGENT_NAME}
- Coordinator：${COORDINATOR_NAME}
- 开始时间：${START_TIME_WITH_TIMEZONE}
- 结束时间：${END_TIME_WITH_TIMEZONE}
- 起始状态：${START_STATUS}
- 建议状态：${RECOMMENDED_STATUS}
- 目标验证等级：${REQUIRED_LEVELS}
- 实际达到等级：${ACHIEVED_LEVELS}
- 工作区基线说明：${DIRTY_WORKTREE_AND_PREEXISTING_CHANGES}

## 目标与范围

- 本任务目标：${OBJECTIVE}
- 允许文件：${ALLOWED_FILES}
- 实际修改文件：${ACTUAL_CHANGED_FILES}
- 未修改的共享边界：${PRESERVED_SHARED_BOUNDARIES}

## 实施事实

1. ${IMPLEMENTED_FACT_1_WITH_CODE_PATH}
2. ${IMPLEMENTED_FACT_2_WITH_CODE_PATH}
3. ${IMPLEMENTED_FACT_3_WITH_CODE_PATH}

## 命令与完整输出

### 命令 ${COMMAND_INDEX}

- 工作目录：${COMMAND_WORKDIR}
- 精确命令：${EXACT_COMMAND}
- 开始/结束时间：${COMMAND_START_AND_END}
- 退出码：${EXIT_CODE}
- 完整输出：${VERBATIM_STDOUT_AND_STDERR}
- 结论：${WHAT_THIS_COMMAND_PROVES_AND_DOES_NOT_PROVE}

## DoD 核对

- ${PASS_OR_FAIL} ${DOD_ITEM_WITH_EVIDENCE_PATH}
- ${PASS_OR_FAIL} ${DOD_ITEM_WITH_EVIDENCE_PATH}
- ${PASS_OR_FAIL} ${DOD_ITEM_WITH_EVIDENCE_PATH}

## 失败、跳过与环境限制

- 失败：${FAILURES_WITH_REPRODUCTION}
- 跳过：${SKIPPED_CHECKS_AND_REASON}
- 环境限制：${SANDBOX_PROVIDER_HARDWARE_OR_HUMAN_LIMITS}
- 与本任务无关的既有失败：${PREEXISTING_FAILURES_WITH_EVIDENCE}

## 安全与隐私复核

- 凭据输出检查：${CREDENTIAL_REDACTION_RESULT}
- 真实 Vault/默认数据库接触：${REAL_STATE_ACCESS_RESULT}
- Renderer/Electron 边界：${RENDERER_BOUNDARY_RESULT}
- 高风险确认与副作用：${CONFIRMATION_AND_SIDE_EFFECT_RESULT}

## 残余风险与回滚

- 残余风险：${RESIDUAL_RISKS}
- 回滚方法：${NON_DESTRUCTIVE_ROLLBACK}
- 后续任务：${FOLLOW_UP_TASK_IDS}

## 人工门与最终结论

- 人工检查者：${HUMAN_REVIEWER_OR_NOT_REQUIRED}
- 人工决定：${APPROVED_REJECTED_OR_NOT_REQUIRED}
- 证据：${HUMAN_EVIDENCE_PATH}
- 是否允许进入下一 Gate：${YES_OR_NO_WITH_REASON}
- Coordinator 最终状态：${FINAL_STATUS_SET_BY_COORDINATOR}
~~~

### verification 记录硬规则

- 每一条实际命令必须逐条记录，不能用“同上”“均通过”合并。
- stdout、stderr 和 exit code 必须原样保留；敏感命中值必须遮盖，但要保留命中类别和位置。
- 命令未运行就写“未运行及原因”，不得复制历史输出。
- build 的 sandbox EPERM、live provider 缺失和 L4 未执行必须分别记为环境/人工缺口，不得写 Pass。
- 截图要记录窗口尺寸、缩放、数据场景、版本和时间；截图不能单独证明后端副作用。
- 状态只能由证据推导：代码完成但缺 L3/L4 时使用 Implemented (unverified)、Partial 或 Human Gate。

---

# 附录 C：Coordinator 与 Worker 回报模板

## Coordinator 开工模板

~~~text
[Coordinator][${TASK_ID}][START]
当前状态：${CURRENT_STATUS}
依赖证据：${DEPENDENCY_EVIDENCE}
本轮目标：${ONE_TASK_OBJECTIVE}
允许文件：${ALLOWED_FILES}
明确禁区：${FORBIDDEN_FILES_AND_ACTIONS}
并行分工：${AGENT_TO_NON_OVERLAPPING_SCOPE_MAPPING}
需要用户确认：${CONFIRMATION_REQUIREMENT}
计划验证：${EXACT_VALIDATION_COMMANDS_AND_LEVELS}
既有工作区变更：${PREEXISTING_CHANGES_TO_PRESERVE}
~~~

## Worker 回报模板

~~~text
[Worker][${TASK_ID}][REPORT]
结论：${IMPLEMENTED_PARTIAL_BLOCKED_OR_READ_ONLY_FINDING}
实际修改文件：${EXACT_FILE_LIST}
关键事实：${BEHAVIOR_AND_CODE_PATHS}
实际命令：${COMMANDS_IN_EXECUTION_ORDER}
完整结果位置：${VERIFICATION_RECORD_PATH}
失败与跳过：${FAILURES_AND_SKIPS}
安全边界复核：${SECURITY_BOUNDARY_RESULT}
与他人修改重叠：${OVERLAP_OR_NONE}
残余风险：${RESIDUAL_RISKS}
建议状态：${STATUS_RECOMMENDATION_WITH_EVIDENCE}
说明：Worker 未修改 task.md 或 progress.md，未代替用户通过人工门。
~~~

## Coordinator 收口模板

~~~text
[Coordinator][${TASK_ID}][CLOSE]
实现结论：${WHAT_IS_TRUE_NOW}
聚焦验证：${FOCUSED_COMMANDS_EXIT_CODES_AND_RESULT}
共享边界验证：${BOUNDARY_COMMANDS_EXIT_CODES_AND_RESULT}
达到等级：${L1_L2_L3_L4}
未达到项：${MISSING_DOD_OR_EVIDENCE}
人工决定：${HUMAN_GATE_RESULT}
残余风险：${RESIDUAL_RISKS}
最终状态：${FINAL_STATUS}
下一 Ready 任务：${NEXT_TASK_OR_NONE}
task.md 更新：${STATUS_DEPENDENCY_AND_EVIDENCE_LINK_CHANGE}
progress.md 更新：${COORDINATOR_ENTRY_PATH_OR_REASON_NOT_UPDATED}
~~~

### Coordinator 状态更新算法

1. 依赖未完成：保持 Planned；不得分配实现。
2. 依赖完成且无需先确认：改为 Ready。
3. 已分配且开始写入：改为 In Progress，并记录 Owner 和开始时间。
4. 代码完成但指定验证未完成：改为 Implemented (unverified)。
5. 主路径存在但至少一个 DoD 或必要证据失败：改为 Partial。
6. 到达用户决定点：改为 Human Gate；不能让 AI 自己批准。
7. 外部条件确实阻断且已记录复现：改为 Blocked；困难或耗时不等于阻断。
8. 只有全部 DoD、要求等级和人工门通过：改为 Completed。
9. 更新状态时同时链接 verification-record；只有 Coordinator 按 AGENTS.md 要求追加 progress.md。

---

# 附录 D：推荐执行路线

## 路线 1：最小求职可信版（优先 AI / Agent 后端岗位）

该路线不是“两天 Demo”。它保留真正影响面试可信度的 Agent、安全、核心 UI、E2E 和作品集交付，把次要可视化与可选高级架构延后。

1. 基线与范围：TASK-0601 → TASK-0602（用户确认）→ TASK-0603。
2. Agent 主链：TASK-0701 → TASK-0702 → TASK-0703 → TASK-0704 → TASK-0705 → TASK-0706 → TASK-0707。
3. 核心 UI：TASK-0801 → TASK-0802、0803、0805、0808、0810；随后 TASK-0809 → TASK-0811 → TASK-0812 → TASK-0813、0814。
4. 真实验收：TASK-0901、0902、0903 → TASK-0904、0905 → TASK-0906。
5. 作品集：TASK-1001、1002、1003 → TASK-1004 → TASK-1005 → TASK-1006。
6. TASK-0804 和 TASK-0806 在 TASK-0905 发现对应预算失败时立即转 Ready 并在 RC 前修复。
7. TASK-0807 默认不进入最小路线；若作品集保留图谱入口或 1000 节点场景，则必须完成。
8. TASK-1101 至 TASK-1106 全部保持可选，不得提前写入简历。

本路线最终可公开的核心说法必须由证据决定：本地优先、LangGraph 多角色工作流；只有 TASK-0701 至 0704 通过后才可升级为“有界多 Agent 协商与证据复核”；只有 TASK-1104、1105 通过后才可说“支持跨进程 interrupt/resume”。

## 路线 2：完整 AI 全栈作品集版

1. 完成 TASK-0601 至 TASK-0707，先冻结可信 Agent 主链。
2. 完成 TASK-0801。
3. 在文件所有权不冲突时推进 TASK-0802、0803、0805、0808、0810。
4. 分别完成 TASK-0804、0806、0807、0809。
5. 全局冻结 UI 后完成 TASK-0811 → TASK-0812。
6. 并行采证 TASK-0813 与 TASK-0814，所有修复回到原任务 Owner。
7. 完成 TASK-0901、0902、0903 → TASK-0904、0905 → TASK-0906。
8. 完成 TASK-1001、1002、1003 → TASK-1004 → TASK-1005 → TASK-1006。
9. 至此 G0 至 G7 完成，形成完整 AI 全栈作品集；不需要用可选阶段填充简历。
10. 如仍有时间且岗位强调 Agent 平台或可靠运行，先并行完成 TASK-1101 与 TASK-1102。
11. TASK-1103 得出 Adopt 且用户批准后，严格串行执行 TASK-1104 → TASK-1105。
12. TASK-1106 只在评测证明收益后实施；Defer 或 Reject 是合法且可能更专业的结论。

## 每个 Gate 的停机检查

- G0：基线失败是否被如实保留，而不是边审计边修掉。
- G1：用户是否批准范围、隐藏项和公开措辞。
- G2：negotiation 是否真实进入 graph，预算与 trace 是否可验证。
- G3：1366×768 下主操作是否可见，页面是否只有一个主滚动容器。
- G4：大文件、全局 CSS、重挂载和长列表是否达到预算。
- G5：两条黄金链是否使用隔离真实路径，安全失败是否为零违规。
- G6：自动、L3、L4、打包和 claim 是否同时一致。
- G7：陌生人是否能看懂、运行、追问并核验；隐私与许可是否允许公开。
- G8：高级能力是否由评测和用户授权驱动，而不是简历焦虑驱动。

---

# 附录 E：计划文件完成声明

- 本文件写入只代表任务已定义，不代表任何产品改造已经完成。
- 当前唯一 Ready 的新任务是 TASK-0601；TASK-0602 至 TASK-1106 均保持 Planned，直到依赖与人工门满足。
- TASK-0001 至 TASK-0506 的历史状态不由本文件改写，仍需按既有任务、progress.md、当前代码和 verification 证据核对。
- 未生成任何新的 Covered 结论。
- 未修改 progress.md、产品源码、依赖、migration、数据库、真实 Vault、dist 或 release。
- 下一次执行应从 TASK-0601 开始，完成当前基线后再决定后续状态。
