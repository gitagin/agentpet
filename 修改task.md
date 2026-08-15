# Agent Pet：本地个人 LLM Wiki 与记忆图谱完整修复任务书

**强制执行顺序（不可跳过）**：`$grill-me` `/grilling` → `$pristine` 根因实现 → API 契约稳定后 `$frontend-design` 两轮设计与视觉验收。

## 0. 文档身份

- **执行对象**：后续接手本仓库的 Codex 协调者与实现 Agent。
- **仓库根目录**：`E:\agentproject`。
- **任务编号**：`LLMWIKI-001` 至 `LLMWIKI-013`。
- **当前基线**：`dev` 分支，基线提交 `53d7c7d`。执行前必须重新读取实时 `HEAD` 和工作树，代码与新验证输出永远优先于本文记录的快照事实。
- **最终目标**：把 Agent Pet 收敛为可运行、可解释、可修正、可长期验证的本地个人 LLM Wiki 与记忆图谱产品，而不是通过增加名词或页面数量伪装成复杂 Agent。
- **执行范围**：后端运行时、记忆领域模型、Wiki 生命周期、图遍历、API、Electron 常驻能力、桌面端体验、失败恢复、指标、评测和事实文档。
- **产品边界**：Windows、本地优先、单用户。不得新增或宣称企业租户、组织、RBAC、团队共享知识治理或云端全天在线。

本文是本轮升级的唯一执行入口。旧文档只能作为待核查线索，不能覆盖当前代码和测试。每完成一个任务，应更新现有事实文档，不得再创建平行的规划说明、临时规格或第二份任务清单。下文的基线事实冻结于 `53d7c7d` 的干净提交；工作树中的未提交改动只有在对应任务的验证证据留存后才能改写为已实现事实。

每个任务的 `### 完成定义` 章节就是该任务的 DoD（Definition of Done）；没有满足全部 DoD 和证据产物，状态不得标记为 `Completed`。

---

## 1. 强制技能与执行顺序

本任务书必须按以下本地技能文件执行，顺序不可调换：[$grill-me](C:\Users\ASUS\.codex\skills\grill-me\SKILL.md) → [$pristine](C:\Users\ASUS\.codex\skills\pristine\SKILL.md) → [$frontend-design](C:\Users\ASUS\.codex\skills\frontend-design\SKILL.md)。

### 1.1 第一阶段：`$grill-me`

开始改代码前必须调用 `$grill-me` 并运行一次 `/grilling`。该阶段只允许读代码、运行非破坏性检查和记录结论，不允许实施功能。至少回答以下问题，并将结果保存到 `output/verification/LLMWIKI-001/grilling.md`：

1. 当前主用户是谁，最频繁、最昂贵的记忆问题是什么？
2. 用户从输入信息到再次使用信息，真实路径经过哪些界面、服务和存储？
3. 哪些步骤必须使用 LLM，哪些步骤使用确定性代码更可靠？
4. 普通聊天快速路径为什么保留，它怎样参与长期记忆闭环而不是沦为模型直连？
5. 自动记忆、图关系、Wiki 综合各自在哪些条件下可以进入回答上下文？
6. 模型、Kuzu、Markdown、SQLite、sidecar、提醒或系统通知失败时，用户仍能完成什么？
7. 当前公开文案中，哪些说法没有生产路径或验证证据？
8. 本轮改造完成后，哪些指标能真实测量，哪些仍需要长期或多人试用？

若 `/grilling` 得出的事实与本文冲突，只能用当前代码、迁移、测试或真实运行证据推翻本文，并在 `LLMWIKI-001` 的证据中记录冲突。不得仅凭偏好改变产品边界。

### 1.2 全阶段规则：`$pristine`

从第一次编辑开始启用 `$pristine`：

- 找到行为的权威入口并一次修正，不在调用方堆叠特例。
- 每种行为只能有一个事实来源；删除被新实现替代的旧路径、旧选择器、旧类型、旧文档和死代码。
- 不创建备份文件、草稿文件、注释掉的旧实现或永久兼容开关。
- 注释只解释业务约束或不可见的取舍，不叙述代码正在做什么。
- 复用现有 `@xyflow/react`、迁移器、生命周期服务、活动账本、检查点、OpenAPI 生成器和验证框架。
- Alpha 内部 API 可以同步修改后端与桌面端并删除旧接口，不保留双路由残留。
- 所有涉及用户数据的迁移必须向前兼容、非破坏、可在备份副本上复跑；Kuzu 属于可删除并重建的派生物。
- 每个非平凡行为至少留下一个可运行的回归检查。

### 1.3 前端阶段：`$frontend-design`

只有 `LLMWIKI-008` 的 API 契约稳定后才能开始 `LLMWIKI-009`。开始 UI 编辑前调用 `$frontend-design`，完成两轮设计：

1. 第一轮输出主题、用户、页面单一任务、颜色、字体、布局草图和标志性交互。
2. 第二轮逐项批判是否像通用 AI 仪表盘；删除不服务个人记忆理解的装饰和说明文字。
3. 将最终设计决策保存到 `output/verification/LLMWIKI-009/design-direction.md`，实现必须与该决策一致。
4. 实现后用截图再次批判并修正，不允许只凭组件测试宣布视觉完成。

### 1.4 环境、验证等级与状态映射

- 所有命令默认从 `E:\agentproject` 执行；任务执行 Agent 必须先运行 `scripts/preflight-windows.ps1`，保存退出码和版本摘要，再进入功能测试。后端要求 Python `3.10+`，从 `apps/backend` 使用 `python -m pip install -e ".[dev]"`；桌面端使用仓库锁文件执行 `npm ci`。没有可用 Windows 打包环境时，相关人工门只能记为 `Partial`，不能用开发服务器代替。
- `kuzu` 和 `qdrant` 属于 `apps/backend` 的可选加速依赖。每个图任务必须各运行一次“依赖存在”和“依赖缺失/损坏”路径；缺失路径应验证 SQLite fallback，而不是为了通过测试强行安装或把导入失败吞掉。模型调用必须使用脱敏 fixture 或明确的离线 stub；证据中不得出现 API key、token、原始私密文本或绝对用户路径。
- 依赖矩阵必须写明解释器、`kuzu`/`qdrant` 版本和路径：`.[dev]` 环境用于 dependency-present；dependency-missing 的 L2/L3 证据必须来自不含 optional extra 的隔离虚拟环境，并确认真实服务在导入失败后仍能启动。仅测试 import hook 只能算 L1，默认关闭且不得进入打包产物。两种结果分别保存，不得在同一共享环境中临时卸载造成不可复现状态。
- `docs/verification-policy.md` 是仓库的验证等级和证据记录权威：L1 是单元/组件，L2 是契约/集成，L3 是隔离状态上的真实产品路径，L4 是人工可用性/真实时间验证。本文件只补充本轮任务的依赖和 DoD，不覆盖该政策的证据优先级。
- 本文件的执行状态与仓库验证状态映射如下：`Pending` = 未开始；`In Progress` = 正在实现；`Partial` = 机制存在但必需证据未齐，对应 policy 的 `Partial` 或 `Implemented (unverified)`；`Skipped` = 明确跳过且记录原因；`Blocked` = 外部前置条件连续三次无法满足；`Failed` = 已运行且未达到阈值；`Completed` = 所有 DoD 在要求的 L1-L4 级别均有证据。状态改变必须同时更新 `docs/current-specification.md`、`docs/mvp-acceptance-coverage.md`、`docs/portfolio/claim-evidence-index.md` 中相关事实之一和对应的 `output/verification/LLMWIKI-XXX/` 证据摘要，不得创建不存在的 `progress.md`，也不得只改本文件。
- 每项任务的“允许修改范围”自动包含本文件中该任务的状态元数据，以及它自己的 `output/verification/LLMWIKI-XXX/` 证据目录；该例外不授权修改其他任务状态、其他任务证据或新建第二份进度文档。
- PowerShell 测试块必须采用 fail-fast 语义：每个 `python`、`npm`、`node`、`git` 或脚本进程之后立即检查非零退出码，路径切换放在 `try/finally` 中。不得让后续成功命令覆盖先前失败，也不得只保留整段最后一个 `$LASTEXITCODE`。
- **仅创建或审阅本任务书时**，Coordinator 应先把 `git status --porcelain=v1` 保存到仓库外的临时快照；该阶段结束时逐项比较，本轮新增/修改只能是本文件，用户在快照前已有的条目保持不变。**进入 `LLMWIKI-001` 至 `013` 的实现阶段后**，每个任务改用自己的“允许修改范围”和证据目录作为边界，并为该任务单独保存 before/after 快照。没有相应编辑前快照时必须报告“无法证明该阶段的文件边界”，不得回退或覆盖既有用户改动。

### 1.5 计划产物与基线缺失路径

下列路径是在基线提交 `53d7c7d` 上规划、当时缺失或待核实的产物；执行时必须重新检查当前工作树。若路径已经由未提交改动创建，只能先审阅其来源、范围、最小自检和非零失败语义，不能重复创建第二份实现，也不能把文件存在写成能力已验证：`scripts/run-llmwiki-migration-smoke.ps1`、`scripts/run-llmwiki-fault-matrix.ps1`、`scripts/run-agentpet-soak.ps1`、`scripts/verify-llmwiki-visual.mjs`、`scripts/verify_llmwiki_metrics.py`、`scripts/check-task-file-boundary.ps1`、`apps/backend/tests/test_action_lifecycle_wiring.py`、`apps/backend/tests/test_prompt_injection_memory_boundary.py`、`apps/desktop/electron/resident.test.cjs` 和 `apps/desktop/electron/ipc.test.cjs`。在对应任务完成实现、自检和证据前，状态只能是 `Pending`、`In Progress` 或 `Partial`，不能把“命令尚不存在”或“文件已存在”写成验证通过。

---

## 2. 当前事实与评分基线

本章冻结任务开始时可由提交 `53d7c7d` 复核的产品事实、评分方法和对外边界。它用于区分“基线已有”“本轮目标”和“需要长期证据”，后续不得把计划内容倒写成基线能力。

### 2.1 基线快照事实（执行前必须重读）

以下事实来自基线提交 `53d7c7d` 和 `LLMWIKI-001` 的只读 grilling，不是对当前脏工作树的永久断言。每个任务开始前必须以当前代码、测试和生成物重读；若已实现，应在事实文档中更新证据，而不是继续把基线缺口写成现状。

1. 项目不是纯 API 套壳：基线已有 Electron 桌面进程、FastAPI sidecar、SQLite/Markdown 持久化、FTS、提醒调度、检查点、审批、活动账本和 Wiki 工作流。
2. 普通聊天在非协作模式下可走直接模型流式快速路径。保留快速路径本身不是缺陷；缺陷是尚未用稳定的跨会话记忆闭环证明它服务于产品核心。
3. 当前协作路径是有界的 Orchestrator、顺序单一 Retrieval Agent 和 Synthesizer，不存在真实 Supervisor、独立全局 Reviewer 或并行专家群。
4. `ActionLifecycleCoordinator` 和独立测试存在，但生产 `_execute_action_plan` 仍使用 `AgentState.executed_action_keys` 做进程内去重，生产 `AgentRuntimeServices` 没有注入该协调器。
5. 动作副作用可能先发生，活动账本与 receipt 后写；进程在两者之间崩溃时，恢复可能重复创建任务、提醒或 Wiki 写入。
6. 当前高风险 planner 会把原目标动作压缩为 `confirmation_only` checkpoint；批准恢复后生产路径只再次记录 pending，不会执行原始目标 adapter。现有批准恢复测试替换了执行函数，不能证明真实高风险闭环。
7. 自动长期记忆会写 `memory_candidates` 和 `memory_evidence`；显式偏好/边界可进入稳定画像，但通用事实没有统一完成候选、图事实、后续召回、纠正和忘记闭环。
8. `memory_graph_facts` 保存主谓宾事实，但没有权威规范化实体表。当前桌面图谱会从共享关键词生成大量 `related_to`，不能作为真实关系证据。
9. Kuzu 仅镜像 `Entity -> MemoryFact -> Source`，写入失败后停用；产品主查询没有依赖 Kuzu 图遍历。
10. LLM Wiki 原型真实存在：不可变来源、Markdown Wiki、索引、日志、引用、冲突和自检规则已实现；但通用八段模板容易制造填充内容，部分“综合”只是格式化调用方内容。
11. 基线 SQLite 已是现有图事实、候选、生命周期和动作状态的权威存储，但尚未拥有规范化实体权威表；`LLMWIKI-003` 完成后，规范实体、别名和关系也以 SQLite 为权威。Markdown 是不可变来源和维护 Wiki 正文的权威存储；FTS、向量和 Kuzu 只能是可重建读取层。
12. 历史审计曾记录 `MemoryWindowView.tsx` 约 2810 行和覆盖式 CSS 约 16062 行；基线提交的可复测行数应由任务开始命令重新记录。390px 截图存在横向裁切，错误文案会暴露 `8765` 等实现细节。拆分后的行数下降只能由当前文件统计证明，不能把目标行数写成质量证据。
13. 设置页把两轮协作描述成“最多调用两个子 Agent”，且前端离线默认协作开启、后端默认关闭，展示与真实行为不一致。
14. 当前没有真实 24 小时稳定性报告、7 天留存/使用证据、通用业务指标提升、干净 Windows VM 和完整物理 DPI 矩阵证据。

### 2.2 任务开始基线评分：57/100

| 维度 | 满分 | 当前分 | 主要缺口 |
| --- | ---: | ---: | --- |
| 问题与目标用户 | 12 | 8 | 定位存在，但核心痛点、单一主流程和非目标仍未在所有页面统一 |
| 用户流程与 AI 必要性 | 12 | 7 | 功能很多，缺少完整“采集到复用再到纠正”的可验证旅程 |
| Agent 实质性 | 14 | 9 | 有真实运行时与工具边界，但普通路径的产品闭环和生产执行协调器未闭合 |
| LLM Wiki 与记忆图谱 | 18 | 10 | Wiki 原型真实，实体权威、图遍历、Wiki 绑定和决策生命周期不完整 |
| 稳定性与失败恢复 | 16 | 9 | 有检查点、调度和审计，但崩溃后 exactly-once、sidecar 自动恢复和常驻语义不足 |
| 业务指标与长期证据 | 10 | 2 | 没有可归因的实际提升和长期样本 |
| 前端完成度与边界展示 | 10 | 7 | 首页视觉资产完整，但记忆 IA、窄屏、失败状态和维护性仍有明显问题 |
| 文档与对外证据 | 8 | 5 | 有证据索引，但部分生产能力表述超过真实接线 |
| **合计** | **100** | **57** | 代码复杂度已经较高，主要失分来自闭环、可信度和证据，而不是技术数量 |

### 2.2.1 基线评分证据锚点

基线分不是“技术数量乘系数”，而是按下表从满分扣除当前能证明的缺口；计划、仅测试能力、ignored 输出和历史报告不给分。另一位 Reviewer 只要按同一提交、同一证据层级和同一扣分规则复核，就应能得到相同的 57，或明确指出哪一条证据改变了分数。

| 维度 | 基线证据 | 扣分锚点 |
| --- | --- | --- |
| 问题与目标用户 | `PRODUCT.md`、`docs/current-specification.md`、grilling 记录 | 多页面仍有不同主叙事，非目标和单一主流程未统一 |
| 用户流程与 AI 必要性 | `apps/backend/app/agents/graph_runtime.py`、`docs/architecture/verified-system.md` | 普通聊天快速路径与跨会话记忆闭环没有同一条可复验旅程 |
| Agent 实质性 | `apps/backend/app/agents/nodes/action.py`、`nodes/executor.py`、动作测试 | 协调器存在但基线生产接线、高风险批准后原目标执行和恢复证据不完整 |
| Wiki 与图谱 | `apps/backend/app/services/wiki.py`、`memory_graph.py`、Kuzu 投影和图 UI | 规范实体、证据遍历、Wiki binding 和决策生命周期未闭合；关键词边不能计分 |
| 稳定性与恢复 | `apps/desktop/electron/sidecar.js`、提醒 scheduler、checkpoint 测试 | 没有真实 soak、睡眠恢复、MTTR/SLO，副作用与 receipt 窗口存在风险 |
| 业务指标 | `docs/portfolio/claim-evidence-index.md` 与当前指标代码 | 没有真实用户分母、before/after 或可归因 uplift，目标值不给分 |
| 前端与边界 | 基线 `MemoryWindowView.tsx`/CSS 行数、已有失败态测试和截图审阅 | 窄屏裁切、默认值漂移、实现细节暴露和维护性债务扣分 |
| 文档证据 | README、architecture/portfolio claim index | 公开声明曾超过生产接线，历史/ignored 证据不能当发布证据 |

基线扣分按本次冻结审计的整数项记录：问题与用户 `-4`、流程与 AI `-5`、Agent 实质 `-5`、Wiki/图谱 `-8`、稳定性 `-7`、业务证据 `-8`、前端 `-3`、文档 `-3`，总扣 `43`，所以 `100-43=57`。这些整数是当前审计结论，不是从更细公式自动推导的客观常数；独立 Reviewer 可以依据更强证据调整某一维度，但必须逐项说明差异。某项证据变为真实通过时，只能重算该项，不能把新增技术数量直接换分。

### 2.2.2 可复算评分档位

Reviewer 对每个维度只能选择“所有条件均满足”的最高档，不允许凭印象插值。某档任一证据缺失时退回前一档；`Partial`、跳过、历史报告和未跟踪旧产物不能满足晋档条件。先将八个维度档位直接相加得到 raw score，再应用时间证据上限：真实 24 小时、7 天和本文件的 85+ 发布门任一未通过时，reported score 为 `min(raw score, 84)`；全部通过后 reported score 才等于 raw score。评分报告必须同时列 raw score、reported score、提交、证据路径、命令、日期和残余风险。

| 维度 | 基线档 | L3 工程档 | 本地长期证据档 | 满分附加条件 |
| --- | --- | --- | --- | --- |
| 问题与目标用户（12） | `8`：已识别个人用户和问题，但页面叙事未统一 | `10`：产品文案、主旅程、非目标和两类单用户语境一致，主旅程有 L3 | `11`：7 天试点证明同一用户能完成旅程并记录失败 | `12`：10-20 名参与者、2-4 周的一致任务验证，不再只是单人假设 |
| 用户流程与 AI 必要性（12） | `7`：有模型与工具，但采集、复用、纠正未闭环 | `10`：记住、跨会话召回、纠正、忘记均通过 L3，固定 ablation 可重跑 | `11`：7 天数据包含实际调用、人工负担和失败分母 | `12`：多人研究仍显示 AI 步骤相对 deterministic baseline 有净增益 |
| Agent 实质性（14） | `9`：有状态运行时，但生产协调器和批准恢复不完整 | `12`：生产 claim/receipt、原目标批准、高风险拒绝和崩溃读回通过 L3 | `14`：真实故障矩阵与 24 小时运行中无重复业务效果和未解释 claim | `14`：不因增加 Agent 数量继续加分 |
| LLM Wiki 与记忆图谱（18） | `10`：Wiki 原型存在，实体、图遍历和生命周期不完整 | `15`：来源到决策、实体绑定、证据遍历、纠正/忘记和 SQLite fallback 通过 L3 | `18`：图增量门通过，7 天记录包含 Wiki 复用、来源回看和纠正传播 | `18`：Kuzu 是否默认不单独加分 |
| 稳定性与失败恢复（16） | `9`：有 checkpoint/调度，但副作用窗口和常驻恢复不足 | `13`：sidecar、睡眠、通知、Markdown/Kuzu/模型故障矩阵通过 L3 | `16`：打包产物、登录态人工门和真实 24 小时阈值全部通过 | `16`：开发服务器或加速时间测试不能替代 |
| 业务指标与长期证据（10） | `2`：没有可归因的真实提升 | `5`：匿名事件、固定评测、分子分母和 before/after 协议可重算 | `7`：单用户 7 天达到预注册本地试点门，只能报告个案信号 | `10`：10-20 名参与者、2-4 周配对研究支持一般化结论 |
| 前端完成度与边界展示（10） | `7`：主要界面存在，但窄屏、失败态和维护性有缺口 | `9`：四视口、键盘、对比度、reduced-motion、失败/空状态和三个 DPI 通过 | `10`：7 天试点没有阻断主旅程的可用性缺陷，操作回执可理解 | `10`：页面数量和装饰不加分 |
| 文档与对外证据（8） | `5`：有索引，但部分声明超过生产接线 | `7`：公开声明通过上下文扫描并指向当前 L2/L3 证据 | `8`：README、case study、简历和真实时间报告使用同一证据边界 | `8`：目标值、截图或历史报告不能补分 |

按该档位，基线为 `8+7+9+10+9+2+7+5=57`；完成当前定义的 L3 工程档时 raw score 和 reported score 都应为 `10+10+12+15+13+5+9+7=81`，这就是当前任务书的可复算工程目标，位于计划区间 `80-84`。只有真实 24 小时、7 天和 85+ 发布门完成后，reported score 才可能超过 84；满分还要求多人证据，单用户 MVP 不应为了追求 100 分伪造外推结论。

完成 L1-L3 自动化和真实路径验证后，只能暂定为 `80-84/100`。取得真实 24 小时 soak 和至少 7 天纵向使用证据后，才能根据结果争取 `85+`。没有足够样本时，不得用目标值替代实际值。

### 2.2.3 2026-08-11 当前证据复评分：62/100

按上表整档规则，当前 raw score 与 reported score 均为 `62/100`：问题与目标用户 `8`、用户流程与 AI 必要性 `7`、Agent 实质性 `9`、LLM Wiki 与记忆图谱 `10`、稳定性与失败恢复 `9`、业务指标与长期证据 `5`、前端完成度与边界展示 `7`、文档与对外证据 `7`，即 `8+7+9+10+9+5+7+7=62`。

在 2026-08-11 评分快照中，指标维度因匿名事件、固定评测、明确分子分母和 before/after 协议可重算而进入 `5` 分机制档；文档维度因公开声明门和当时证据索引通过而进入 `7` 分档。当时核心重启闭环、完整 source-to-decision、全副作用生命周期、OS 故障和物理 DPI 仍有 Partial，因此未进入 L3 档。完整评分、命令、日期、证据路径和残余风险见 `output/verification/LLMWIKI-013/final-score-20260811.md`；2026-08-14 新证据必须另行按整档规则复核，不能直接把 `81/100` 目标写成当前结果。

### 2.3 产品定义

**用户**：经常使用 AI、在 Windows 上保存个人资料和长期项目上下文、重视本地控制与可纠正性的个人知识工作者。

**核心问题**：普通聊天历史把信息埋在对话列表中，用户需要重复解释偏好、边界、项目和决定；当助手声称“记得”时，用户又无法知道来源、置信度、冲突和怎样纠正。

**核心价值**：把聊天和本地来源中的长期信息转成带证据、可审查、可修正、可忘记并能跨会话复用的个人 Wiki 与记忆图谱。

**唯一主流程**：

1. 用户聊天或导入本地来源。
2. 系统保留不可变来源并抽取实体、事实和关系候选。
3. 确定性策略按风险、证据、冲突和用户意图决定激活、隔离或请求确认。
4. 已激活事实更新实体页、综合页或决策页，并绑定来源。
5. 后续查询通过 Wiki、图关系和原始来源组成有引用的上下文。
6. 用户能确认、纠正、忘记或归档；旧事实立即退出召回，变更保留生命周期记录。

**为什么使用 AI**：LLM 只承担自然语言意图识别、非结构化来源抽取、别名建议、跨来源综合、冲突解释和查询规划。精确搜索、权限、状态迁移、文件写入、图约束、幂等、读回验证、提醒调度和删除不需要 LLM，必须由确定性代码负责。

**套壳判断**：基线不是纯 API 套壳，因为本地状态、权限、任务/提醒、Wiki 文件、图投影和恢复边界都在产品代码中；但非协作普通聊天仍接近模型直连，不能用“已有桌面和很多框架”把它包装成成熟自治 Agent。只有记住→跨会话召回→纠正/忘记、真实副作用回执和可重复证据闭合后，才可提高 Agent 实质性评分。

**不是本轮目标**：通用聊天平台、无限多 Agent、开放式本体、自动创造关系类型、企业共享知识库、云端服务、默认向量检索、无人工边界的自治写入、为了简历而接入更多框架。

### 2.4 目标使用路径与数据边界（待真实试用确认）

| 使用者 | 目标使用路径（待试用证据确认） | 数据边界 | 不支持的结论 |
| --- | --- | --- | --- |
| 外部个人用户 | 在自己的 Windows 账号安装；登录后选择是否驻留；聊天或导入自己的来源；在图谱/时间线/来源页确认、纠正、忘记；按引用回到 Wiki 原文 | 单一 active Vault、单一本机 SQLite、用户自己的本地通知；模型调用受本机隐私策略控制 | 不承诺多人共享、跨设备同步、云端托管或关机期间在线 |
| 公司内部单员工试点 | 由员工在个人 Windows 账号建立隔离试点 Vault；先记录基线，再按 7 天 runbook 使用同一主流程；结束时导出匿名指标并执行本地数据清理 | 试点数据只属于该员工和该本机；报告只上传脱敏聚合，不上传聊天原文、来源正文、凭据或绝对路径 | 不把单员工试点写成团队知识库、组织记忆、RBAC 或普遍业务提升 |

两行是同一单用户产品的两种部署语境，不是两个租户模式。第二个用户登录同一台机器时不会自动获得第一个用户的 Vault、图谱或回答上下文；跨用户共享必须另立产品和安全设计，本轮不实现。

### 2.5 主要技术难点与失败后的用户动作

1. **跨 SQLite/Markdown 的副作用一致性**：难点不是调用模型，而是 effect、claim、receipt 和文件 hash 可能跨进程崩溃。失败时用户看到 `failed_recovery`，可查看差异、重试或放弃；系统不能把未知状态显示为成功。
2. **实体身份与关系证据**：同名人物不能靠相似度合并，共享关键词不能造边。消歧失败时保留候选并要求选择，冲突时隔离两条事实。
3. **Wiki 正文和事实生命周期**：外部编辑、纠正、supersedes 和忘记必须同时影响回答权限、引用和派生图；失败时保留原始来源和 snapshot，不静默覆盖。
4. **派生图和降级**：Kuzu 只改变遍历性能，代次或权限不一致时回退 SQLite；用户仍可浏览和纠正，诊断区记录降级原因。
5. **常驻与通知的现实边界**：登录态驻留可追赶任务，但睡眠/关机不在线，OS 通知只能证明 display attempt；崩溃窗口显示 unknown 并提供手工重试。
6. **业务价值归因**：找回耗时、重复说明和 Wiki 复用必须来自固定任务、用户主动反馈和明确分母；没有对照就只报告基线，不把模型调用次数或页面数量当提升。

---

## 3. 不可变架构决策

本章定义跨任务共享的数据权威、受控本体、恢复语义和安全边界。实现可以优化内部结构，但任何任务若要改变这些决策，必须先更新本章并给出迁移、兼容和证据影响，不能在局部代码中悄悄形成第二套规则。

### 3.1 权威关系

- SQLite：实体、别名、事实/关系、候选、证据引用、生命周期、动作 claim/receipt、指标事件和派生代次的权威状态。
- Markdown Vault：不可变原始来源和可由用户直接阅读、迁移、修订的 Wiki 正文。
- Kuzu：从 SQLite 和 Wiki 绑定生成的可重建图投影；不能成为唯一数据源。
- FTS/向量：候选检索机制；不能决定事实是否有效，也不能替代引用和生命周期。

### 3.2 受控实体类型

`self`、`person`、`project`、`preference`、`boundary`、`goal`、`event`、`concept`、`source`、`wiki_page`、`decision`。

模型不得创建新的实体类型。无法归类的抽取必须拒绝或保留为未激活候选，不能塞进最相近类型。

### 3.3 受控关系类型

`prefers`、`avoids`、`works_on`、`knows`、`related_to`、`occurred_in`、`supports`、`contradicts`、`supersedes`、`derived_from`、`documented_in`。

`related_to` 只能在来源明确表达关系或用户确认时创建；共享关键词、同一分类、时间接近或模型主观判断都不能单独生成该边。

关系端点必须按类型校验：

- `prefers`、`avoids`、`works_on`、`knows`、`related_to`、`occurred_in`：实体到实体。
- `supports`：来源实体或上游事实到被支持事实。
- `contradicts`：事实到事实；持久化时按 fact id 规范化端点顺序并建唯一约束，查询/UI 按对称关系处理。
- `supersedes`：替代事实到旧事实；它是事实版本链的唯一权威，不再把 `metadata_json.superseded_by` 当作第二事实来源。
- `derived_from`：实体或事实到来源实体或上游事实。
- `documented_in`：实体或事实到 `wiki_page` 实体。

端点类型不匹配时整条关系拒绝写入。模型只能提出 `prefers`、`avoids`、`works_on`、`knows`、`related_to`、`occurred_in`、`supports` 和 `contradicts` 候选，不能改变方向、端点类型或生命周期。`supersedes` 只能由用户纠正触发的确定性生命周期服务创建；`derived_from` 和 `documented_in` 只能由 evidence/Wiki binding 的确定性写入创建，模型不得伪造 provenance。

### 3.4 候选优先策略

- 普通模型抽取默认写为 `candidate`，不得进入回答上下文。
- 明确用户声明可先写候选，再在同一事务中记录激活生命周期；条件是低风险、无冲突、结构有效且用户意图明确。
- 非明确声明只有在至少两个不同消息证据、至少两个不同会话、置信度不低于 `0.85`、低风险且无冲突时才可自动激活。
- 人物身份、重大关系、敏感信息和冲突事实始终要求用户确认。
- 纠正创建新事实并用 `supersedes` 连接旧事实；旧事实立即失去召回权限，但保留证据和历史。
- 忘记将目标及派生关系标记为不可召回，并重建派生图；不得只从当前 UI 隐藏。

### 3.5 LLM Wiki 与检索的关系

对外产品类别是“本地个人 LLM Wiki 与记忆图谱”。查询时仍会使用检索，这是内部实现机制。不得把所有 RAG 字样机械替换成 LLM Wiki，也不得声称产品完全不做 retrieval。只有真实图遍历进入主查询并通过评测后，才允许描述为图增强检索；在此之前禁止使用 GraphRAG 成熟产品措辞。

### 3.6 SQLite、Markdown 与外部编辑的裁决规则

- SQLite 对实体、事实、关系、生命周期、权限、claim/receipt 和 Wiki binding 拥有最终状态权；Markdown 对不可变来源文件和用户可读 Wiki 正文拥有文件内容权。两者不是同一字段的双写真相。
- 不可变来源被外部修改时，原 `source_hash` 保留为历史；新 hash 先进入 `source_changed`/候选状态，旧事实和引用暂时撤销回答权限，直到用户重新导入或确认。系统不得静默把编辑后的正文当作已确认事实。
- active Wiki 正文被外部编辑、删除或路径移动时，reconciler 必须先记录旧/新 hash、标记 binding 需要复核、推进 `graph_source_state.revision` 并使旧 Kuzu generation stale。查询回退 SQLite 时也必须过滤该 binding；用户可打开差异、恢复 snapshot 或重新生成候选。
- SQLite claim 已提交但 Markdown effect/receipt 未完成时，动作进入 `failed_recovery`，保持 claim 和 snapshot；恢复流程先 quiesce 同一目标的并发写入，再按 hash 比较决定补写、回滚派生页或转人工，不得用备份覆盖未核对的并发数据。
- 权威读回返回零个或多个无法唯一匹配的业务对象时，状态为 `failed_recovery`/`manual_review`，不猜测、不重复调用 adapter。每个分支都必须有用户可执行的“查看差异、重试或放弃”入口和审计记录。

同一 `(vault_id, target_ref)` 的写入使用 SQLite `BEGIN IMMEDIATE` 加短租约，默认等待 `5s`；超时返回 `write_busy` 并保留提案，不在调用方循环重试。生命周期状态只能按 `claimed → markdown_reserved → markdown_written → sqlite_committed → verified` 前进，或进入 `failed_recovery`/`manual_review`；恢复时先读当前 revision/hash，只有当前状态仍等于 claim 记录的目标才可补写。执行前备份只用于迁移/灾难恢复，不能覆盖更高 revision 的新提交。

### 3.7 模型与流式失败契约

- 抽取、查询规划、综合分别使用配置化 timeout（默认 `30s`、`20s`、`60s`）和最多一次只读重试；写动作、记忆激活和 Wiki 落盘不得因网络重试再次调用副作用 adapter。
- provider timeout、rate limit、quota exhausted、取消和部分 SSE 都产生稳定错误码与可重试/不可重试标记；已发送的部分文本不能被写成事实、receipt 或成功答案，客户端显示已中断并提供本地浏览、重试或手工录入。
- 每种模型故障都记录调用次数、耗时和未完成状态，不记录 prompt/原文；连续失败触发有界冷却，不把 fallback 的规则结果冒充模型完成。

所有崩溃注入必须使用仅测试可启用的命名 hook（例如 `after_claim_before_effect`、`after_effect_before_receipt`、`after_reservation_before_os`、`after_os_before_delivery_receipt`），默认关闭、只接受隔离测试 run id，并在报告中记录 hook 和进程退出时间。不得给生产用户暴露任意 crash 开关，也不得用 monkeypatch 替代真实进程退出。

### 3.8 Agent registry 与增量交付边界

`LLMWIKI-002` 的 registry schema、版本、adapter allowlist 和 reader 协议由 Coordinator/后端 owner 单独维护。后续任务只能提交带版本的 adapter、reader 和契约测试，通过同一 registry 扩展；不得在 API handler、Wiki service、图服务或指标服务另建第二个注册表。每个扩展必须先能在旧 adapter 集合下启动，再以独立 feature slice 合并；某个后续任务失败时，已验证的前置 slice 仍可运行，不能以未定义的空 adapter 占位。

---

## 4. 执行任务

以下 13 项任务按依赖顺序推进。Coordinator 每次只能将一项任务标记为 `In Progress`；任务达到全部 DoD 并留下对应证据后才能标记为 `Completed`，时间型或人工门未完成时必须保留为 `Partial`。

## LLMWIKI-001：事实冻结、评分基线与公开声明止血

- **状态**：Partial
- **优先级**：P0
- **依赖**：无
- **验证层级**：L2
- **执行所有者**：Coordinator 与证据审计 Agent
- **独立复核**：只读产品/代码证据 Reviewer
- **人工门**：无
- **允许修改范围**：现有产品、架构、作品集和验收文档、设置页纯展示文案，以及 `scripts/check-portfolio-claims.ps1`、`scripts/check-task-file-boundary.ps1` 的声明/边界扫描规则；不得修改设置语义或其他运行时代码。

### 目标

建立当前代码到文档的逐项证据矩阵，立即移除会误导实现者或面试官的完成声明。

### 实施步骤

1. 运行 `$grill-me` 的 `/grilling` 并保存结论。
2. 对照 `apps/backend/app/agents/graph_runtime.py`、`nodes/action.py`、`nodes/executor.py`、`agents/checkpointer.py`、`api/services/adapters.py` 和批准恢复测试，确认快速路径、协调器、生产接线及高风险 checkpoint 是否保留并执行原目标动作。
3. 对照记忆候选、图事实、Wiki 写入、Kuzu 镜像和 prompt 装配代码，分别标注“生产使用”“仅测试”“派生可选”“未接通”。
4. 对照桌面设置默认值和后端设置默认值，记录每个不一致；只修正“两个子 Agent”等错误展示文案，默认值和加载语义归 `LLMWIKI-009` 修复。
5. 扩展 `scripts/check-portfolio-claims.ps1` 的 forbidden-claim allowlist，覆盖生产执行回执、exactly-once、GraphRAG、24×7/24x7、无限多 Agent、业务百分比和“已接入”变体；扫描器必须把“当前限制/未实现/不得宣称”上下文视为否定说明，只对未经否定的公开断言失败。
6. 在功能实现完成前，把文档中的生产 Executor/Verifier、高风险批准后执行、多 Agent、自动通用长期记忆、图遍历、全天在线和业务提升表述改为真实边界。
7. 运行 `scripts/check-task-file-boundary.ps1 -BaselinePath <仓库外快照> -TaskPath (Resolve-Path .\修改task.md).Path`，确认本轮文档创建没有改动其他路径；没有快照时记录无法证明，不伪造通过。
8. 保留本文件的 57 分作为基线，不因文案收窄而提前加分。

### 完成定义

- 每条公开能力都能指向生产入口和至少 L2 证据。
- 测试中存在但生产未调用的能力明确标记为未接通。
- 设置页面与文档不再把两轮协作说成两个子 Agent。
- 不存在业务百分比、全天在线或图检索质量的无样本结论。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
Push-Location .
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-portfolio-claims.ps1
    if ($LASTEXITCODE -ne 0) { throw "PUBLIC_CLAIM_GATE_FAILED" }
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-task-file-boundary.ps1 -BaselinePath $env:TEMP\agentproject-status-before-task.txt -TaskPath (Resolve-Path .\修改task.md).Path
    if ($LASTEXITCODE -ne 0) { throw "TASK_FILE_BOUNDARY_GATE_FAILED" }
    python -m pytest apps/backend/tests/test_agent_runtime_negotiation.py apps/backend/tests/test_agent_action_lifecycle.py -q
    if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_001_PYTEST_FAILED" }
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-mvp-acceptance-gap.ps1
    if ($LASTEXITCODE -ne 0) { throw "MVP_ACCEPTANCE_GATE_FAILED" }
}
finally {
    Pop-Location
}
```

### 失败回滚

文档修正必须基于当前代码重写原段落。若证据不足，恢复为更窄的事实描述，不恢复未经证实的宣传。

### 证据产物

`output/verification/LLMWIKI-001/grilling.md`、`claim-crosswalk.md`、命令日志和文档差异。现有目录中的 53d7c7d 快照只能证明基线审计；当前工作树的声明扫描和边界快照重新通过前，任务保持 `Partial`。

### 禁止事项

- 不得用计划中的能力解释当前状态。
- 不得为了保留简历措辞而虚构生产接线。
- 不得新建第二份架构真相文档。

---

## LLMWIKI-002：接通生产动作 claim、receipt 与崩溃恢复

- **状态**：Partial
- **优先级**：P0 Stop-line
- **依赖**：`LLMWIKI-001`
- **验证层级**：L3
- **执行所有者**：后端动作生命周期与持久化 Agent
- **独立复核**：只读并发/崩溃恢复 Reviewer
- **人工门**：无
- **允许修改范围**：Agent services、action/executor/checkpointer、API service factory/adapters、动作账本、任务/记忆/Wiki 服务、迁移和相关测试；可新增只验证生产接线的 `test_action_lifecycle_wiring.py`，不得新增第二套执行器。

### 目标

让现有 `ActionLifecycleCoordinator` 成为生产副作用的唯一执行入口，消除“副作用已发生但 receipt 未写入”导致的重复执行。

### 实施步骤

1. 定义最小 `ActionLifecycleCoordinatorProtocol`，在 `AgentRuntimeServices` 增加唯一的 `action_lifecycle` 依赖。
2. 将协调器从具体长连接实现中解耦。生产使用无连接泄漏的请求绑定账本门面，每次账本操作通过统一数据库 session 打开、提交并关闭。
3. 在 `agent_runtime(request)` 注入真实协调器，只注册当前已有且能权威读回的 `task.create`（含其持久 reminder row）、`memory.proposal` 和 `wiki.*` adapter；把实时枚举和 reader 覆盖写入测试。`memory.graph.*`、`graph.rebuild`、`metrics.feedback` 分别由 `LLMWIKI-004`、`007`、`011` 在同一 registry 扩展，002 不预注册未定义效果。
4. `_execute_action_plan` 不再直接调用各副作用函数；它把 `ActionProposal` 和 `PolicyDecision` 交给协调器，并从 outcome 投影 `ActionPlan`、SSE 事件和用户文案。
5. 协调器成为动作生命周期记录的唯一所有者。删除执行后再调用 `_record_planned_action` 造成的第二份活动记录。
6. 新增 `020_action_execution_idempotency.sql`，给 `agent_actions` 增加独立 `idempotency_key` 列及唯一部分索引；新动作不得扫描 `metadata_json` 查重。
7. 为本地副作用保存可权威读回的幂等键。任务和提醒使用由动作幂等键导出的稳定标识；记忆提案和 Wiki workflow 保存动作幂等键或稳定目标哈希。
8. 恢复算法固定为：已有 verified receipt 直接返回；仅有 claim 时先读目标；唯一匹配则重建 receipt 并验证；无匹配才执行；多匹配或结果不确定进入 `failed_recovery`，不得重放。
9. 高风险 checkpoint 必须保存原始 `ActionProposal`、原始 policy、canonical payload hash、幂等键和待授权范围；不得再把目标压缩成只含 `confirmation_only` 的占位动作。批准时记录不可变 approval decision，并由同一协调器对原 proposal 重新校验当前权限和目标状态后 claim/执行/读回/写 receipt；拒绝产生零副作用。若用户修改 payload，必须生成新的 proposal 和幂等键，旧批准不得授权新内容。
10. 增加生产接线回归：从真实 `agent_runtime(request)` 构造服务，断言 registry 中的 adapter、reader 和 lifecycle coordinator 来自同一实例；静态检查只作为辅助，不能用 grep 命中/未命中代替运行时断言。
11. 逐一迁移 `apps/backend/app/services/chat_pipeline/wiki_summary.py`、`apps/backend/app/services/chat_answer_wiki_summary.py`、`apps/backend/app/agents/nodes/wiki.py` 等 direct Wiki 写入调用方；它们只能提出 proposal，不能绕过 registry 直接写 Markdown、activity 或 receipt。

### 完成定义

- 生产 runtime 明确实例化并调用协调器。
- 每个 SQLite/Markdown 权威副作用在执行前已有持久化 claim。
- 每个完成动作包含 proposal、policy、claim、receipt 和 verification 的绑定引用。
- 同一幂等键在并发、重试、进程重启和检查点恢复中最多产生一个可权威读回的本地业务效果。
- 真实生产 planner 生成的高风险 task、memory 或 Wiki 动作在批准后执行原目标一次，拒绝后执行零次；验证不得 monkeypatch `_execute_action_plan` 或手工伪造生产不会产生的 pending payload。
- Electron/Windows 通知等不可与 SQLite 原子提交的外部效果不宣称 exactly-once；其单独语义由 `LLMWIKI-010` 定义。
- 权威读回失败时显示可恢复失败，不把动作显示为成功。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_agent_action_lifecycle.py apps/backend/tests/test_agent_interrupt_resume.py apps/backend/tests/test_agent_checkpoint_integration.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_002_LIFECYCLE_TEST_FAILED" }
python -m pytest apps/backend/tests/test_production_action_recovery.py apps/backend/tests/test_production_checkpoint_resume.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_002_PRODUCTION_RECOVERY_FAILED" }
python -m pytest apps/backend/tests/test_tasks_services.py apps/backend/tests/test_wiki_workflows.py apps/backend/tests/test_memory_services.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_002_SIDE_EFFECT_TEST_FAILED" }
python -m pytest apps/backend/tests/test_action_lifecycle_wiring.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_002_WIRING_TEST_FAILED" }
```

### 必测场景

- claim 后、effect 前崩溃：恢复后执行一次。
- effect 后、receipt 前崩溃：恢复后读回既有结果，不再执行。
- receipt 后、SSE 前崩溃：恢复后返回原 receipt。
- 两个并发请求使用相同幂等键：一个创建，一个返回 duplicate outcome。
- reader 返回多个候选：进入人工恢复，不猜测目标。
- 真实高风险请求：生产 planner 创建包含原 proposal 的 checkpoint；批准后经协调器产生一次业务效果，拒绝后无效果，批准响应前崩溃后重试仍不重复。

### 失败回滚

执行前备份 SQLite。代码回滚后保留新增幂等列和 claim 记录；新增列允许旧版本忽略，不删除动作历史。

### 证据产物

`output/verification/LLMWIKI-002/` 下保存故障注入日志、数据库 before/after 查询、重复计数和真实 API 路径记录。

### 禁止事项

- 不得保留进程内 set 作为生产幂等事实来源。
- 不得通过 catch 后再次调用 adapter 处理不确定结果。
- 不得把本地 claim/receipt 的 exactly-once 结论外推到 OS 通知或其他不可事务化效果。
- 不得以 `confirmation_only` 占位覆盖原始目标动作，也不得用 monkeypatch executor 的测试声称高风险生产闭环完成。
- 不得让 Renderer 获得原始 checkpoint、令牌或内部 receipt 快照。

---

## LLMWIKI-003：建立权威实体、证据绑定与派生图代次

- **状态**：Partial
- **优先级**：P0
- **依赖**：`LLMWIKI-002`
- **验证层级**：L2
- **执行所有者**：后端数据模型与迁移 Agent
- **独立复核**：只读迁移/数据完整性 Reviewer
- **人工门**：真实用户库迁移前由用户确认备份路径可读取；隔离测试库无需人工门
- **允许修改范围**：新增迁移 `021_llm_wiki_memory_graph.sql`、记忆模型/仓储/服务、Kuzu 投影和迁移测试。

### 目标

在不删除现有候选、事实、证据和 Wiki 页面数据的前提下，为个人记忆图谱建立规范化实体层。

### 数据契约

新增 `memory_entities`：

- `id`、`entity_key`、`lookup_fingerprint`、`entity_type`、`canonical_name`、`normalized_name`。
- `status` 复用现有记忆生命周期语义。
- `risk_tier`、`confidence`、`metadata_json`、`created_at`、`updated_at`。
- `id`/`entity_key` 是创建后不可变的 opaque identity，均全局唯一；除固定 `self` 外，不得从名称推导身份。
- `lookup_fingerprint` 由实体类型和规范化名称生成，只建非唯一索引，用于返回消歧候选；同类型同名人物必须允许并存。
- `self` 只有一个固定 entity key，并由数据库唯一约束保证。

新增 `memory_entity_aliases`：

- `id`、`entity_id`、`alias`、`normalized_alias`、`status`、`created_at`。
- `(entity_id, normalized_alias)` 唯一。
- 同类型别名冲突不能静默合并。

新增 `memory_entity_evidence`：

- `entity_id`、`evidence_id`、`role`、`created_at`。
- `role` 只允许 `names`、`describes`、`supports`、`contradicts`。
- `(entity_id, evidence_id, role)` 唯一。

新增 `wiki_page_bindings`：

- `id`、`vault_id`、`page_entity_id`、`wiki_relative_path`、`content_hash`、`revision`、`status`、`updated_at`。
- `vault_id` 外键指向现有 Vault；`(vault_id, page_entity_id)` 和 `(vault_id, wiki_relative_path)` 分别唯一，禁止把不同 Vault 的同名路径合并。
- 路径只能位于 `Wiki/`，且必须经过现有安全路径解析。
- 普通查询只使用请求绑定的 active Vault；全局诊断可以列出其他 Vault 的脱敏计数，但跨 Vault 来源或 Wiki 页面不得进入回答上下文。
- 实体身份和不属于 Vault 的显式聊天事实可保持用户级全局；由 Vault 来源支持的事实只有在存在 active Vault evidence 时才能进入当前回答，其他 Vault 的 evidence、路径和正文全部过滤。

新增 `memory_fact_artifact_bindings`：

- `id`、`fact_id`、`vault_id`、`artifact_type`、`artifact_ref`、`status`、`created_at`、`updated_at`。
- `artifact_type` 只允许 `source`、`wiki_page`、`fts_chunk`；`(fact_id, vault_id, artifact_type, artifact_ref)` 唯一。
- 该表只绑定事实与可召回 artifact，不复制正文；忘记或 supersede 时在同一事务中撤销绑定的回答权限。
- 旧 artifact 只有在能用现有 fact id、citation 或 binding 确定映射时才回填；无法确定的内容仍可作为普通文档搜索，但不得作为个人记忆进入 prompt。

新增 `graph_projection_generations`：

- `id`、`backend`、`schema_version`、`source_revision`、`status`、`built_at`、`error_code`。
- `backend` 首版只允许 `kuzu`。
- 只有代次与 SQLite source revision 一致时才允许使用派生结果。

新增单行 `graph_source_state`：

- 固定主键、单调递增 `revision`、`updated_at`。
- 实体、别名、事实、关系、evidence 权限、生命周期或 Wiki binding 在同一事务中发生有效变更时递增一次；事务回滚不得递增。
- Markdown 正文由产品写入或外部编辑后，必须先完成 hash reconcile 并更新 `wiki_page_bindings`，再递增 revision。
- Kuzu generation 只保存构建开始时读取的 revision；构建结束时若当前 revision 已变化，该 generation 标记 stale，不得晋升 active。

扩展 `memory_graph_facts`：

- 增加可空 `statement_kind`，非空时只允许 `claim` 或 `relation`；增加可空 `subject_entity_id`、`subject_fact_id`、`object_entity_id`、`object_fact_id` 和 `relation_type`。所有迁移后的新写入必须提供非空 `statement_kind`；仅迁移时无法可靠分类的旧行允许保持 `NULL`，只供审计并强制退出激活、召回、图遍历和 Kuzu 投影。
- `claim` 必须绑定一个 `subject_entity_id`，并把 literal value 保存在现有 `object` 可读字段；`subject_fact_id`、两个 object ref 和 `relation_type` 必须为空。
- `relation` 必须在 subject 和 object 两侧各绑定且只绑定一个 typed endpoint，`relation_type` 必须属于受控关系集合并符合 3.3 的端点矩阵。
- `memory_evidence.fact_id` 同时为 claim 和 relation 提供证据；自动关系没有 evidence 时只能保持 candidate/quarantined，不能进入回答。
- 将现有 `metadata_json.superseded_by` 保守迁移为 `supersedes` relation；迁移完成后删除生产读写该 metadata key 的路径，版本链只查询受控关系。
- 将现有 `conflicts_with` 保守迁移为 `contradicts` relation；旧列保留为只读迁移快照，生产服务不再读写。`conflict_key` 只能用于候选分组，不能单独证明冲突。
- 对 active `supersedes.object_fact_id` 建唯一部分索引，禁止同一旧事实同时出现两个当前替代事实；纠正事务必须原子写关系、旧事实状态和生命周期事件。
- 旧 `subject`、`predicate`、`object` 文本保留为可读快照和迁移兼容字段，不再作为实体唯一性来源。

### 实施步骤

1. 规范化使用 Unicode NFKC、`casefold`、连续空白折叠和首尾标点清理；不把中文转拼音。
2. 新实体使用持久化 opaque ID；名称 fingerprint 只查候选。旧数据仅按明确 durable origin 回填，同名且来源不能证明同一身份时分开保留并等待消歧。
3. 对旧事实执行保守回填：只映射明确的类型和已知关系；不能确定类型或关系的行保持未绑定并退出图遍历，不进行模型猜测。
4. 将现有 `self`/用户中心映射为固定实体，而不是每次投影创建临时中心节点。
5. 按 Vault 回填 Wiki 和 artifact binding；路径相同但 Vault 不同的记录保持分离，缺少 owning Vault 的绑定进入 quarantined。
6. 把旧 supersede/conflict 指针迁移为受控 relation，随后删除生产 metadata/`conflicts_with` 读写路径和重复规则。
7. 迁移可以重复检测当前结构，不可重复插入实体、别名、关系或绑定。
8. 在领域仓储的同一事务出口维护 `graph_source_state.revision`，禁止由 API handler、Kuzu writer 或时间戳各自推算代次。
9. Kuzu schema 改为从权威实体、关系、来源和 Wiki 绑定重建，不在业务写事务中承担唯一写入。

### 完成定义

- 空库、现有迁移 019 库和包含旧事实的库都能升级。
- 旧表数据数量不减少，旧事实仍可审计。
- 同一身份的中英文大小写/空白变体可通过别名解析，同类型同名但身份不同的人不会被自动合并。
- 不确定旧关系不会被伪装成 `related_to`。
- 事实纠正只产生一条权威 `supersedes` 版本链，旧 metadata 路径不再参与读取。
- 冲突只由 `contradicts` relation 决定，旧 `conflicts_with` 不再是生产事实来源。
- 两个 Vault 的相同相对路径各自绑定，查询不会跨 active Vault 泄露来源。
- 每次权威图输入变更都使 source revision 恰好递增一次；无效写入和回滚不递增。
- 删除整个 Kuzu 目录后可从 SQLite 与 Markdown 绑定完整重建。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_dual_track_memory_schema.py apps/backend/tests/test_memory_graph_services.py apps/backend/tests/test_memory_graph_projection.py apps/backend/tests/test_memory_graph_migration.py apps/backend/tests/test_memory_entity_graph.py apps/backend/tests/test_memory_graph_kuzu.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_003_GRAPH_TEST_FAILED" }
python -m pytest apps/backend/tests/test_persistence_mvp.py apps/backend/tests/test_security_hardening_mvp.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_003_PERSISTENCE_TEST_FAILED" }
```

### 失败回滚

迁移前通过 SQLite backup API 创建一致性备份，并记录 Vault 内容哈希；迁移期间暂停写入并记录活动连接，避免用旧备份覆盖并发提交。失败时只在确认 quiesce 后恢复备份；不得编写向下迁移删除用户表。Kuzu 失败直接删除派生目录并重新构建。

### 证据产物

`output/verification/LLMWIKI-003/` 下保存三类数据库迁移前后 schema、行数、外键检查、重复检查和 Kuzu 重建报告。

### 禁止事项

- 不得创建平行的 `graph_edges` 事实表；关系继续由 `memory_graph_facts` 统一承载。
- 不得让 Kuzu ID 替代 SQLite ID。
- 不得用自由字符串扩展本体。

---

## LLMWIKI-004：完成记忆激活、召回、纠正与忘记闭环

- **状态**：Partial
- **优先级**：P0
- **依赖**：`LLMWIKI-002`、`LLMWIKI-003`
- **验证层级**：L3
- **执行所有者**：后端记忆生命周期 Agent
- **独立复核**：只读召回权限/污染 Reviewer
- **人工门**：无
- **允许修改范围**：memory consolidation/lifecycle/permissions/feedback/profile/retrieval、Agent prompt assembly、API 和相关测试。

### 目标

让用户能在一个会话中明确保存事实，在新会话中带来源召回，并通过纠正或忘记可靠改变后续行为。

### 实施步骤

1. 将候选到实体和图事实的转换收敛进记忆生命周期服务，API、后台 job 和 Agent 节点不得各自实现状态分支。
2. 显式用户声明先创建候选和 evidence，再按候选优先策略激活实体/关系并写 lifecycle event。
3. 普通抽取只创建候选。重复证据达到阈值时，由确定性服务检查不同消息、不同会话、置信度、风险和冲突后激活。
4. 为所有 active 通用事实提供统一的 `MemoryItem` 读取模型，至少包含 id、kind、status、score、permissions、provenance、entity refs 和 evidence refs。
5. prompt 组装只接受 active、未过期、未 supersede、未 forgotten、权限允许且存在 evidence 的事实。
6. 纠正事务创建替代事实、唯一的 `supersedes` 关系和 lifecycle event；同一事务撤销旧事实的回答权限，禁止同时写 metadata 版本链。
7. 忘记事务撤销目标实体/事实、派生关系和 `memory_fact_artifact_bindings` 的回答权限，安排 Wiki 正文审查和 Kuzu 重建；不可变原始来源仍可由用户主动查看，但不能作为该事实进入回答。
8. FTS/Wiki 检索先解析 artifact binding，再与统一事实权限相交；无法绑定到 active fact 的个人记忆内容不得进入 prompt，普通文档搜索结果必须保持“来源材料”身份。
9. 搜索、稳定画像、图遍历和主动提醒全部调用同一权限判断，不允许各自写过滤条件。
10. 在 `LLMWIKI-002` 的唯一 registry 注册 `memory.graph.confirm/correct/forget/archive` adapter 与权威 reader，并覆盖重复请求和 effect 后 receipt 前恢复。
11. review queue 按风险、证据数量和最近更新时间排序，提供确认、纠正、忘记、仅本地保留和忽略入口；记录队列长度与确认耗时，超过人工容量时保持候选而不是自动放宽激活门槛。

### 完成定义

- “Remember this: my favorite editor is VS Code” 会产生可追溯实体/事实，而不只是候选行。
- 新 conversation 能召回该事实并展示来源，不依赖上一会话 state。
- 用户改为 JetBrains 后，旧事实仍可审计但不能作为当前答案。
- 用户忘记后，FTS 个人记忆通道、画像、图遍历、Wiki 回答上下文和 prompt 都不能再次激活该事实；历史来源若保留，只能作为用户主动打开的审计材料。
- 一次情绪、玩笑、模型总结和自动动作文本不会变成长期事实。
- 同名实体或敏感候选必须显示消歧/确认理由和可撤销操作；用户拒绝后不会在下一轮重复弹出同一候选，除非来源或 payload 发生变化。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_memory_consolidation.py apps/backend/tests/test_memory_lifecycle.py apps/backend/tests/test_memory_permissions.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_004_LIFECYCLE_TEST_FAILED" }
python -m pytest apps/backend/tests/test_memory_feedback_api.py apps/backend/tests/test_memory_pollution_regression.py apps/backend/tests/test_prompt_memory_assembler.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_004_RECALL_TEST_FAILED" }
python -m pytest apps/backend/tests/test_api_wiring_mvp.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_004_API_TEST_FAILED" }
```

### 必测真实路径

1. 明确保存低风险偏好。
2. 结束进程并重启 sidecar。
3. 新建 conversation 并询问偏好。
4. 检查回答 citation、激活事件和来源。
5. 纠正偏好并再次重启。
6. 证明旧值退出、新值进入。
7. 忘记新值并证明所有召回通道均为空。

### 失败回滚

新生命周期代码失败时恢复数据库备份。已经写入的候选和证据不得删除；将错误激活项转为 quarantined 并保留审计。

### 证据产物

`output/verification/LLMWIKI-004/` 下保存请求、脱敏 SSE、数据库查询、引用结果和重启前后对比。

### 禁止事项

- 不得为通过测试直接把所有候选设为 active。
- 不得只在 UI 隐藏旧事实。
- 不得把无 evidence 的模型输出放入稳定画像。

---

## LLMWIKI-005：受控实体抽取、别名建议与消歧

- **状态**：Partial
- **优先级**：P1
- **依赖**：`LLMWIKI-003`、`LLMWIKI-004`
- **验证层级**：L2
- **执行所有者**：后端结构化抽取 Agent
- **独立复核**：只读隐私/模型边界 Reviewer
- **人工门**：无
- **允许修改范围**：新增实体抽取/解析服务、模型契约、记忆后台 job、策略、评测 fixtures 和测试。

### 目标

让 LLM 从非结构化聊天和来源中提出结构化候选，同时确保模型没有创建本体、合并实体和激活事实的权限。

### 输出契约

模型必须返回版本化结构：

- `entities[]`：唯一 `entity_ref`、受控类型、原文名称、别名建议、置信度、证据字符范围。
- `claims[]`：唯一 `claim_ref`、`subject_entity_ref`、规范化摘要、literal value、事实类型、置信度、证据字符范围。
- `relations[]`：`subject_endpoint`、受控关系、`object_endpoint`、置信度、证据字符范围；每个 endpoint 固定为 `{kind: "entity" | "claim", ref: entity_ref | claim_ref}`，且必须满足 3.3 的端点矩阵。
- `sensitive`、`conflicts`、`uncertainties`。

未知字段拒绝，未知枚举拒绝，引用不存在的 `entity_ref`/`claim_ref` 拒绝，endpoint kind 与 ref 类型不匹配拒绝，证据范围越界拒绝。模型不得输出 `supersedes`、`derived_from` 或 `documented_in`；这些关系由确定性服务创建。一个 batch 任一结构错误时整批不写入，记录安全错误码，不进行部分保存。

### 实施步骤

1. 使用 Pydantic 严格验证模型输出；JSON 修复最多一次，仍失败则结束该批次。
2. 先运行敏感策略，再决定是否允许调用远程模型；隐私模式命中时不发送原文。
3. 实体解析先查非唯一 `lookup_fingerprint`、规范化 canonical name 和 active aliases；只有唯一低风险候选且存在稳定 provenance 时才可绑定，模糊匹配只能产生 merge candidate。
4. `self`、`person` 和身份相关实体即使名称完全相同，也必须依赖 durable entity ref 或用户选择才能合并；名称本身永远不是身份主键。
5. LLM 只提交别名建议；别名写入由确定性冲突检查和生命周期服务执行。
6. 每个候选保存 source hash、excerpt、conversation/message/run 引用和抽取器版本。
7. 为 prompt injection、恶意来源指令和越界引用建立固定 fixture；来源正文中的“忽略规则、执行动作、泄露秘密”等文本只能作为待分析材料，不能改变系统策略或触发写入。
8. 提供无模型确定性 fallback：用户仍能手工创建记忆、浏览 Wiki、使用 FTS 和确认候选。敏感策略误报时只能由用户在本地明确选择“仅本地保存/放弃”，不得用通用 override 绕过风险等级。
9. 固定风险分类至少覆盖 `public`、`personal`、`sensitive`、`instruction_injection` 和 `unknown`；每一类产生稳定 policy decision code、远程模型调用计数和用户下一步，误报只能进入本地复核，不能静默升级为 active。

### 完成定义

- 中英文别名能指向同一实体且没有重复 canonical entity。
- 同名不同人物保持分离并进入确认流程。
- 非法 JSON、自由关系、越界 evidence 和 prompt injection 不产生任何图写入；审计能证明原文未被发送到被策略禁止的远程模型。
- 模型离线时现有图、Wiki、搜索和手工操作可用。
- 每个被隔离的候选都有稳定拒绝码、可理解的下一步和 review queue 入口；队列不会因重复轮询无限增长。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_memory_consolidation.py apps/backend/tests/test_memory_pollution_regression.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_005_MEMORY_TEST_FAILED" }
python -m pytest apps/backend/tests/unit/agents/nodes/test_memory.py apps/backend/tests/test_security_hardening_mvp.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_005_SECURITY_TEST_FAILED" }
python -m pytest apps/backend/tests/test_memory_entity_extraction.py apps/backend/tests/test_prompt_injection_memory_boundary.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_005_EXTRACTION_TEST_FAILED" }
```

### 失败回滚

关闭抽取 job 只能作为运行时故障状态，不添加永久功能分叉。回滚代码后保留已验证候选；无法验证的批次标记 failed，不自动重试原始敏感内容。

### 证据产物

`output/verification/LLMWIKI-005/` 下保存固定输入、结构化输出、拒绝原因、模型离线结果和污染回归。

### 禁止事项

- 不得使用动态实体类型或动态 relation name。
- 不得把 embedding 相似度当作同一人物证明。
- 不得将模型 chain-of-thought 保存或传给 Renderer。

---

## LLMWIKI-006：实现来源到决策的完整 LLM Wiki 生命周期

- **状态**：Partial
- **优先级**：P1
- **依赖**：`LLMWIKI-002`、`LLMWIKI-003`、`LLMWIKI-004`、`LLMWIKI-005`
- **验证层级**：L3
- **执行所有者**：后端 Wiki 生命周期 Agent
- **独立复核**：只读证据链/lint Reviewer
- **人工门**：无；decision fixture 必须包含显式用户决定，不能由 Reviewer 补写
- **允许修改范围**：Wiki schema/resource、services/wiki 包、Wiki Agent 节点、Vault seed、绑定服务、lint、测试和打包资源。

### 目标

让 Wiki 成为由证据维护的长期知识层，而不是把用户原文追加进 Markdown 或把检索改名为 Wiki。

### 单一规范来源

1. 将 canonical Wiki 规则移到随 sidecar 打包的唯一资源文件 `apps/backend/app/resources/wiki/AGENTS.md`。
2. `WikiService.ensure_core_files()` 从该资源播种用户 Vault；删除 Python 中重复的长字符串规范。
3. `vault/Wiki/AGENTS.md` 是当前示例 Vault 的运行副本，不再与代码各自手写维护。
4. 打包和测试校验资源存在、hash 可读、首次初始化可复制。

### 页面类型模板

- `source`：来源信息、不可变原文摘录、可验证主张、关联实体、引用。
- `entity`：定义、已确认事实、关系、冲突与过期信息、来源、更新记录。
- `concept`：定义、核心要点、案例、误区、关系、来源、更新记录。
- `synthesis`/`comparison`：问题、结论、支持证据、反证与不确定性、影响、来源、更新记录。
- `decision`：决策、背景、依据、替代方案、风险、后续检查、来源、更新记录。
- `report`：范围、结果、失败项、证据、后续动作、生成信息。

只生成页面类型要求的部分。没有内容的可选部分应省略，禁止插入空标题、占位句或虚构经典案例。

### 生命周期

1. 保存不可变来源、source hash 和安全元数据。
2. 创建 source page 和 source entity。
3. 抽取实体、事实和关系候选并绑定 evidence。
4. 只有 active 事实才能更新 entity/concept 页面。
5. 综合页必须至少引用两个独立 evidence；只有一个来源时标记为单来源摘要，不称综合。
6. 决策页必须区分事实、模型推断、用户决定和仍未解决的问题。
7. 冲突事实并排保留；未解决冲突不能进入确定性结论。
8. 每次写入同步页面 frontmatter、index、页面日志、中央日志、Vault-scoped binding、fact-artifact binding、hash 和 lint 状态。
9. 所有写入通过 `LLMWIKI-002` 的协调器，保留快照和权威读回。

### Frontmatter 契约

至少包括 `wiki_id`、`page_type`、`entity_ids`、`fact_ids`、`revision`、`confidence`、`disputed`、`sources`、`updated_at`。`sources` 不能为空；推断页必须显式标记 inference。

### 实施步骤

1. 把 canonical 规则和按页面类型的 schema 收敛到打包资源，删除 Python 内嵌长模板和通用八段生成路径。
2. 以 source hash 作为导入幂等边界：先保存不可变来源，再创建 source page/entity，重复导入只返回原 receipt。
3. 调用 `LLMWIKI-005` 抽取候选，并通过 `LLMWIKI-004` 的生命周期服务激活允许写入的实体、事实和关系；Wiki service 不自行决定激活。
4. 单一来源只生成 source/entity/concept 或明确标记的单来源摘要；至少两个独立 evidence 才允许生成 synthesis/comparison。
5. 只有用户明确确认了一个选择时才生成 decision page；没有用户决定时流程停在综合或未决问题，不伪造决策。
6. 使用页面类型 renderer 省略空的可选段落，并在落盘前校验 claim、citation、frontmatter 和安全相对路径。
7. 所有 Markdown 与 SQLite binding 写入经协调器执行，按 snapshot、目标 hash、写入、权威读回、receipt 的顺序完成；每个可召回 claim 同步写入 `fact_ids` 和 `memory_fact_artifact_bindings`。
8. 实现确定性 Markdown reconciler，并固定在 sidecar 启动、Wiki 回答上下文查询前和 Kuzu rebuild 前运行。外部编辑、删除或 hash 漂移必须更新 binding 状态并推进 `graph_source_state.revision`；文件 watcher 只能用于提早唤醒，不能成为唯一正确性机制。
9. 扩展 lint 和 repair，使孤立页、断链、空来源、日志失配、无证据结论和绑定 hash 漂移成为可复现错误。

### 完成定义

- 单一固定来源能稳定停在 source/entity/单来源摘要，不被伪装成综合或决策。
- 两个独立固定来源加一项用户确认决定能走完 source → entity → fact/relation → synthesis → decision。
- 每个重要主张可追到原始 source hash 和 excerpt。
- 重复导入同一来源不创建重复页面或关系。
- 更新事实会递增 revision，不静默覆盖冲突历史。
- 外部修改 active Wiki 页面后，下一次启动、查询或 rebuild 会在使用旧 Kuzu generation 前完成 reconcile，使旧 generation 失效并回退 SQLite。
- lint 能发现孤立页、断链、空来源、缺日志、失配绑定和无证据结论。
- 外部编辑的正文不能直接提升为 active fact：删除、hash 漂移和 citation 失配分别产生可区分的 binding 状态、用户操作和审计事件。
- `wiki_summary`、`chat_answer_wiki_summary` 和 Wiki Agent 节点没有任何绕过协调器的直接副作用调用；静态扫描和真实 API 故障注入都能证明这一点。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_wiki_services.py apps/backend/tests/test_wiki_workflows.py apps/backend/tests/test_agent_runtime_wiki.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_006_WIKI_TEST_FAILED" }
python -m pytest apps/backend/tests/test_wiki_lint_repairs.py apps/backend/tests/test_api_wiring_mvp.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_006_LINT_TEST_FAILED" }
```

### 失败回滚

写入前保存 Markdown snapshot。跨 SQLite/Markdown 失败时由动作状态标记 failed_recovery；重试先比较目标 hash。不得删除原始来源。派生 Wiki 页面可以从 snapshot 回滚并记录新日志事件。

### 证据产物

`output/verification/LLMWIKI-006/` 下保存隔离 Vault、来源 hash、生成页面、图绑定、lint 报告和回滚前后 diff。

### 禁止事项

- 不得继续维护 Python 内嵌规范和 Markdown 规范两份真相。
- 不得把模型推断写成来源原话。
- 不得在无引用时自动生成综合或决策。

---

## LLMWIKI-007：证据图遍历、召回融合与 Kuzu 降级

- **状态**：Partial
- **优先级**：P1
- **依赖**：`LLMWIKI-003`、`LLMWIKI-004`、`LLMWIKI-006`
- **验证层级**：L3
- **执行所有者**：后端检索与图查询 Agent
- **独立复核**：只读权限/检索质量 Reviewer
- **人工门**：无
- **允许修改范围**：graph query/projection、retrieval、prompt assembly、Kuzu mirror/rebuild、API service adapter、评测和测试。

### 目标

让真实实体关系参与查询，同时保证每条进入回答的图上下文都有 evidence、生命周期权限和可解释路径。

### 查询算法

1. 用 deterministic alias exact match、当前 citation 和 Wiki binding 识别起始实体；LLM 只能提出查询实体候选。
2. 默认一跳，最多两跳；每次查询最多 4 条路径、12 条事实、4000 个 prompt 字符。
3. 只遍历 active、未过期、未 supersede、未 forgotten、非敏感且 `can_answer_context` 为真的关系；Vault-derived evidence 还必须属于当前 active Vault。
4. 每条路径至少包含一个可呈现 evidence；没有 evidence 的边只可在诊断中出现。
5. 排序由确定性分数组成：实体精确匹配、relation confidence、独立 evidence 数、recency 和 hop penalty；两跳乘 `0.75`，不得让共享关键词直接加边。
6. `contradicts` 路径进入冲突区，不进入确定性回答区；回答必须说明存在冲突并要求确认。
7. 图结果与 FTS/Wiki 结果转为统一 `MemoryItem`，按来源配额融合，避免单一通道吃完 `top_k`。
8. Prompt 中展示最小事实、关系和 citation id，不暴露数据库 ID、本机绝对路径或原始敏感 excerpt。

### Kuzu 使用条件

- Kuzu generation 的 schema version 和 source revision 必须与 SQLite 一致。
- Kuzu 查询结果必须经过 SQLite 权限和 evidence 再验证。
- 初始化失败、更新失败、损坏、代次落后或依赖不存在时自动使用 SQLite traversal。
- 降级写入结构化诊断和指标；普通用户只看到“关系加速暂不可用，已使用本机索引”，技术详情位于诊断区。
- 提供可重复的全量 rebuild，禁止业务写入时靠一次尽力 mirror 维持正确性。

### 对照评测与晋升门槛

- 固定 query set 必须有人工标注的 gold entities、允许关系、引用来源和冲突标签；同一批 query 先跑 FTS/Wiki-only baseline，再跑 SQLite traversal、Kuzu acceleration 和损坏后的 fallback。
- 任何 backend 的授权实体、事实、冲突分区和 citation 集合必须与 SQLite baseline 100% 等价；不等价即 `Failed`，不能用更低延迟抵消。
- 固定集最低质量门：no-evidence accuracy `100%`，敏感/未知候选 false activation `0`，纠正传播 `100%`，citation coverage `>=95%`。Recall@K 只能在样本数和 gold 定义同时存在时报告。
- Kuzu 只有在图关系子集 Recall@K 至少比 FTS/Wiki-only 提高 `10` 个百分点，且 P95 延迟不高于 baseline 的 `1.2x` 时才允许作为加速默认；未达到时保留 SQLite traversal，不能把 Kuzu 的存在写成业务价值。
- 上述数字是本轮运行前冻结的工程验收门，不是已经取得的业务结果；改变门槛必须在运行前记录理由和新版本号。

### 实施步骤

1. 实现唯一的 SQLite traversal service，以实体 exact alias、citation 和 Wiki binding 解析起点，并应用统一生命周期与权限过滤。
2. 在该 service 中实现有界一跳/两跳、路径去重、冲突分区、确定性评分和 prompt 字符预算；禁止 API 与 prompt assembler 各自遍历。
3. 把图、FTS 和 Wiki 命中转换成统一 `MemoryItem`，按固定通道配额融合，并在最终 prompt 装配前再次校验 evidence 与权限。
4. 删除关键词共享生成 `related_to` 的生产代码、类型和测试 fixture；只保留有原始 evidence 或用户确认的关系。
5. 让 Kuzu adapter 接收同一查询计划，并用 SQLite 结果做授权和 evidence 复核；Kuzu 只能改变性能，不能改变允许返回的语义集合。
6. 查询和 rebuild 在读取 generation 前调用 `LLMWIKI-006` reconciler；再使用 `graph_source_state.revision` 选择 active generation，缺失、损坏、stale 或构建中一律回退 SQLite，并记录稳定降级 code。
7. 实现可取消、互斥、可重跑的全量 rebuild；构建期间继续服务 SQLite，完成时原子晋升 generation。
8. 在 `LLMWIKI-002` 的唯一 registry 注册 `graph.rebuild` adapter 与 generation 权威 reader；重复请求返回原 job/receipt，不启动第二个构建。
9. 用同一固定语料比较 SQLite、Kuzu 和损坏后 fallback 的授权结果、引用、延迟与路径数量，并覆盖外部 Markdown 编辑使 generation 立即 stale 的场景；若未达到晋升门槛，删除默认 Kuzu 选择而保留可重建 adapter。

### 完成定义

- 两个有明确 evidence 的实体能通过一跳/两跳关系回答并显示来源。
- 仅共享关键词的记忆之间没有边。
- 候选、冲突、敏感和 forgotten 事实不能进入答案。
- 删除/损坏 Kuzu 后，SQLite fallback 返回语义等价的授权结果。
- Kuzu 恢复并 rebuild 后代次一致，UI 不需要重启。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_memory_graph_services.py apps/backend/tests/test_memory_graph_projection.py apps/backend/tests/test_memory_graph_migration.py apps/backend/tests/test_memory_entity_graph.py apps/backend/tests/test_memory_graph_kuzu.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_007_GRAPH_TEST_FAILED" }
python -m pytest apps/backend/tests/test_agent_runtime_retrieval.py apps/backend/tests/test_prompt_memory_assembler.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_007_RETRIEVAL_TEST_FAILED" }
python -m pytest apps/backend/tests/test_retrieval_grounding.py apps/backend/tests/test_retrieval_quality_eval.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_007_QUALITY_TEST_FAILED" }
```

### 失败回滚

查询实现回滚时保留 SQLite 实体/事实。Kuzu 目录可删除重建。任何降级都必须回到 SQLite/FTS，不回到无 evidence 的模型常识回答。

### 证据产物

`output/verification/LLMWIKI-007/` 下保存固定语料、SQLite/Kuzu 对照、权限排除、冲突回答、性能和降级日志。

### 禁止事项

- 不得让 Kuzu 失败导致记忆主路径不可用。
- 不得将字符相似或关键词共现描述为知识关系。
- 不得先拼 prompt 再过滤权限。

---

## LLMWIKI-008：收敛图 API、操作契约与生成代码

- **状态**：Partial
- **优先级**：P1
- **依赖**：`LLMWIKI-003`、`LLMWIKI-004`、`LLMWIKI-006`、`LLMWIKI-007`
- **验证层级**：L2
- **执行所有者**：后端 API 契约 Agent
- **独立复核**：只读 API/Renderer 安全边界 Reviewer
- **人工门**：无
- **允许修改范围**：FastAPI models/routes/services、OpenAPI、desktop API client/types、Electron proxy allowlist generator 和契约测试。

### 目标

为图谱、详情、用户操作和派生图重建提供单一、稳定、可生成的本地 API，删除旧投影和重复动作接口；效果指标 API 由拥有其存储语义的 `LLMWIKI-011` 实现。

### 公共接口

1. `GET /api/memory/graph`
   - 查询参数：`query`、`status`、`entity_type`、`limit`，limit 范围 `5..80`。
   - 从当前绑定的 active Vault 解析 scope，不接受任意本机路径；未绑定 Vault 返回可操作的 `vault_not_bound`。
   - 返回：`schema_version`、vault scope、nodes、edges、clusters、summary、generation、degraded_mode、redaction_note。
2. `GET /api/memory/graph/nodes/{node_id}`
   - 返回安全详情、active/历史 claims 与关系、evidence summaries、Wiki bindings、lifecycle 和 allowed actions；每条 claim 包含可继续读取的 public `claim_id`。
3. `POST /api/memory/graph/nodes/{node_id}/actions`
   - action 只允许 `confirm`、`correct`、`forget`、`archive`。
   - node `correct` 只修改实体 canonical name、受控实体类型或 aliases，replacement 固定为 `{canonical_name, entity_type, aliases}`；不得借 node action 猜测或批量修改其 claims。实体类型变化前必须重新校验所有 active incident relations；只要任一端点约束将失效，整次请求返回 `409 entity_type_change_breaks_relation`，不得自动改边或留下非法关系。破坏性动作需要 `confirmed=true`。
4. `GET /api/memory/graph/edges/{edge_id}`
   - 返回关系两端、受控 relation type、evidence summaries、来源、Wiki bindings、lifecycle、版本链和 allowed actions。
5. `POST /api/memory/graph/edges/{edge_id}/actions`
   - action 只允许 `confirm`、`correct`、`forget`、`archive`；`correct` 必须提交受控 relation 和合法 typed endpoints。
   - 操作目标是该 edge 对应的权威 relation fact，不得通过 node action 猜测关系。`correct` 必须创建新的 relation fact，以唯一 `supersedes` 关系连接旧 relation，立即撤销旧 relation 的召回权限并保留其 evidence/lifecycle；不得原地覆盖旧边。
6. `GET /api/memory/graph/claims/{claim_id}`
   - 返回 subject node、安全 literal value、fact type、evidence summaries、来源、Wiki bindings、lifecycle、版本链和 allowed actions。
7. `POST /api/memory/graph/claims/{claim_id}/actions`
   - action 只允许 `confirm`、`correct`、`forget`、`archive`；`correct` replacement 固定为 `{value, fact_type}`，subject 默认不可变。
   - 纠正必须创建新 claim 和唯一 `supersedes` 关系；忘记/归档只作用于该 claim 及其派生权限，不得隐式删除整个实体。
8. `POST /api/diagnostics/memory-graph/rebuild`
   - 只重建派生 Kuzu generation；返回 job/generation 状态，不修改权威事实。

### 工作区依赖契约

`LLMWIKI-008` 的稳定门不只覆盖图 canvas。开始 `LLMWIKI-009` 前，必须在 OpenAPI、生成类型和 Electron allowlist 中冻结或明确复用下列已有产品路径；若现有响应不能满足工作区，只能在 008 内补齐，不能等到 UI 实现时临时加接口：

- 时间线：动作 receipt/lifecycle、记忆候选列表及其 confirm/reject 操作；每项必须提供稳定 public id、状态、时间、来源摘要和 allowed actions。
- 来源：Wiki/source 列表与详情、ingest 流程、Wiki binding 和派生图 rebuild；不得把绝对本机路径直接暴露给 Renderer。
- 候选审查：`GET /api/memory/proposals` 与 confirm/reject 的请求、响应、错误码和幂等契约。
- 设置回读：`GET /api/settings`、`GET/PUT /api/settings/automation` 中协作开关、`max_rounds`、unknown/loading/error 语义；前端不得另设默认值。
- 009 的导入/导出按钮只能调用 008 已冻结的现有路径；不存在真实导出能力时删除按钮或显示明确不可用状态，不得放置无功能 CTA。

### 写请求幂等契约

- 上述所有 `POST` 强制要求 `Idempotency-Key`，格式为 64 位小写十六进制；桌面端为一次用户意图生成一次，网络重试复用原值。
- 服务端 claim 同时保存 method、canonical path、canonical payload hash 和本机主体；相同 key 与相同 payload 返回第一次的 HTTP status、响应体和 receipt id。
- 相同 key 携带不同 payload 返回 `409 idempotency_key_conflict`，不得执行第二次。
- node/claim/edge action 和 rebuild job 都必须覆盖“effect 后 response 前断线”的重复请求测试。
- 不允许用前端按钮 disabled、进程内 Set 或查询最近一条记录代替持久化幂等。

### 类型契约

- Node 包含稳定且不泄露数据库主键的 `node_id`、type、label、status、risk、confidence、evidence_count、updated_at、allowed actions。
- Claim 包含稳定 `claim_id`、subject public node id、fact type、安全 literal value、status、risk、confidence、evidence_count、updated_at 和 allowed actions。
- Edge 包含稳定 `edge_id`、relation type、source/target public id、status、confidence、evidence_count、updated_at 和 allowed actions；删除仅靠浮点 `strength` 的含糊语义。
- Detail 中 evidence 只返回用户安全摘要、时间、来源类型和可打开的相对路径。
- 内部错误使用稳定 code；普通 message 不包含端口、绝对路径、SQL、模型 payload 或内部 ID。

### 实施步骤

1. 删除 `/api/memory/graph-projection` 及其旧 response 类型和调用方。
2. 将现有多个 graph fact sibling action 路由收敛到共享 statement action service；claim 与 edge 都以权威 fact 为目标，node handler 只管理实体，避免 handler 调 handler。
3. 为 public node/claim/edge id 建立单一编码与解析边界，404 不泄露目标是否因敏感策略被隐藏。
4. 把所有 POST 接入持久化 claim/receipt，并实现 payload hash 冲突与原响应重放。
5. 先从当前 FastAPI app 运行 `scripts/generate-openapi.ps1`（或仓库规定的等价 exporter），再通过现有生成器生成 TypeScript 类型和 proxy allowlist；禁止拿旧 `openapi.json` 自洽生成下游文件。
6. Renderer 只通过 preload/proxy 调用；不得增加直接 bearer 或 Node 能力。
7. 为每个接口增加认证、limit、枚举、幂等、敏感 redaction 和 negative allowlist 测试。

### 完成定义

- 后端路由、OpenAPI、TypeScript 和 proxy allowlist 来自同一生成链。
- 新增或删除图接口后，未重新生成契约会使 CI 失败。
- 旧图投影路由、旧手写类型和旧正则不存在。
- 选中 node、literal claim 或 edge 都能取得证据链并执行允许动作；重复 POST 不产生重复事实或 rebuild job。
- API 错误对普通用户可操作，对诊断保留安全 code。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_api_wiring_mvp.py apps/backend/tests/test_renderer_allowlist_contract.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_008_API_TEST_FAILED" }
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\generate-openapi.ps1
if ($LASTEXITCODE -ne 0) { throw "OPENAPI_GENERATION_FAILED" }
python -m pytest apps/backend/tests/test_openapi_snapshot.py -q
if ($LASTEXITCODE -ne 0) { throw "OPENAPI_SNAPSHOT_FAILED" }
Push-Location apps\desktop
try {
    npm run generate:api-contracts
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_API_GENERATION_FAILED" }
    npm run check:api-contracts
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_API_CONTRACT_CHECK_FAILED" }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_TYPECHECK_FAILED" }
}
finally {
    Pop-Location
}
```

### 失败回滚

Alpha 客户端与后端必须在同一提交中回滚。不得恢复旧接口作为永久 alias；若生成失败，修复 OpenAPI 源或生成器。

### 证据产物

`output/verification/LLMWIKI-008/` 下保存 OpenAPI diff、生成检查、allowlist positive/negative 测试和 redaction 样例。

### 禁止事项

- 不得手工修改 `types.gen.ts` 或生成的 allowlist。
- 不得把内部 graph/Kuzu 健康细节放进普通节点详情。
- 不得留下两个功能相同的写操作端点。
- `edge`/`claim` 独立详情和 action 端点是证据链轨道所需的有意契约扩展；它们共享 statement action service，不构成第二套图写入 API。

---

## LLMWIKI-009：图谱优先的记忆工作区与证据链轨道

- **状态**：Partial
- **优先级**：P1
- **依赖**：`LLMWIKI-008`
- **验证层级**：L4
- **执行所有者**：桌面前端 Agent
- **独立复核**：只读设计/可访问性 Reviewer
- **人工门**：用户或 Windows 视觉验收员完成截图批判与 100%/125%/150% DPI 检查
- **允许修改范围**：Memory feature/view、导航、错误文案、设置文案、相关 hooks/types/tests/styles，以及一个只读视觉验收 runner；设置页只负责读取/展示后端状态，登录自启、托盘、IPC 和持久化语义归 `LLMWIKI-010`，不得改后端业务语义。

### 目标

把记忆页收敛为能查看、追踪和控制真实记忆证据链的桌面工作区，并系统修复窄屏、失败状态、默认值和样式维护问题。

### 主题与单一任务

- **主题**：个人记忆档案室，不是运维仪表盘，也不是营销落地页。
- **用户**：需要查看“系统记住了什么、为什么、与什么有关、怎样修正”的 Windows 个人用户。
- **页面单一任务**：理解并控制一条记忆从实体关系到原始来源和 Wiki 页面的一整条证据链。

### 视觉系统

下列色彩和产品语义是用户给定的验收约束，不是已经完成的设计答案。`$frontend-design` 第一轮仍必须比较至少两种信息布局和证据链展开方式，第二轮批判其是否像通用 AI 仪表盘；最终选择需说明为何更适合个人证据审查。

| Token | 颜色 | 用途 |
| --- | --- | --- |
| Graphite | `#111214` | 主背景，避免蓝黑单色感 |
| Carbon | `#1B1D21` | 工具面和 inspector |
| Warm white | `#F3F1EC` | 主文字 |
| Memory rose | `#D56F8A` | 用户控制和当前选择 |
| Evidence teal | `#68B8AD` | 已验证 evidence 和来源 |
| Review amber | `#D1A44B` | 候选、需确认和降级 |
| Conflict red | `#D75B5B` | 冲突、失败和危险操作 |

- Display：`Segoe UI Variable Display`，只用于页面标题和节点主名称。
- Body：`Microsoft YaHei UI` / `Segoe UI Variable Text`。
- Utility：`Cascadia Code`，只用于时间、revision 和安全诊断 code。
- 字号不随 viewport 宽度缩放；letter-spacing 固定为 `0`。

### 标志性交互

“证据链轨道”是唯一强调设计：选中节点或关系后，右侧按 `实体 → 关系 → 原始来源 → Wiki 页面 → 生命周期 → 纠正记录` 展开一条连续轨道。纠正记录必须显示旧值、新值、纠正时间和 `supersedes` 链；用户可从轨道执行确认、纠正、忘记和打开来源。其他区域保持平静，不增加装饰性光球、发光数字或渐变数据卡。

### 桌面布局

```text
┌ 搜索记忆 ────────────────────── 待确认数量 ┐
│ [图谱] [时间线] [来源]                       │
├──────────────────────────────┬─────────────┤
│                              │ 证据链轨道   │
│       大尺寸关系画布          │ 节点/关系    │
│                              │ 来源/Wiki    │
│                              │ 生命周期/动作│
└──────────────────────────────┴─────────────┘
```

### 窄屏布局

```text
┌ 搜索与待确认 ┐
│ [时间线] [图谱] [来源] │
│ 时间线列表为默认视图   │
│ 选中后打开底部详情面板 │
└───────────────────────┘
```

390px 视口默认时间线，图谱为二级视图。窄屏图谱不得强行同时显示 canvas 和 inspector；详情使用非嵌套的 bottom sheet。

### 实施步骤

1. 将现有十个记忆子标签收敛为 `图谱 / 时间线 / 来源`：搜索固定在 workspace 顶栏并作用于全部视图；图谱承载实体、literal claims、关系和选中项证据轨道；时间线承载 lifecycle、活动账本与候选审查队列；来源承载原始来源、Wiki bindings、导入/导出和派生图重建。重置等全局危险操作继续位于设置页，不塞入任一记忆视图。
2. 桌面宽度默认图谱，窄屏默认时间线；导航选择可以持久化，但 viewport 首次默认必须符合该规则。
3. 复用 `@xyflow/react`。节点使用权威实体；边使用受控 relation，显示关系标签和 evidence 状态。
4. candidate 使用虚线轮廓，active 使用实线，conflict 使用红色断线；颜色不能是唯一状态信号。
5. 节点、literal claim 和关系详情分别接入真实 detail/actions；证据轨道可对单条 claim 执行确认、纠正、忘记和归档，不再只显示不可操作的“只读”占位。
6. 空状态提供真实动作：`添加一条记忆` 打开并聚焦聊天输入，`导入来源` 打开导入流程，`重试` 重新请求。
7. 模型离线、sidecar 恢复、无 evidence、Kuzu 降级和写入冲突分别使用不同可操作文案；端口和内部实现折叠到诊断详情。
8. 将 `MemoryWindowView.tsx` 拆为 workspace shell、graph、timeline、sources、review queue 和 evidence rail；主 view 目标不超过 500 行。
9. 将记忆工作区样式放入归属明确的 feature stylesheet，删除 `desktop-polish.css` 中被替代的旧选择器；不得在文件末尾追加覆盖块。
10. 仅在选择关系时使用一次 160ms 证据轨道显现；reduced-motion 下无位移和路径动画。
11. 将后端 settings response 设为协作开关和 `max_rounds` 的唯一 UI 事实来源：初始状态为 unknown/loading，不再硬编码 `use_negotiation=true` 或轮数；读取失败时禁用控件并显示可重试状态，不伪装为已开启。
12. 设置文案按实际返回轮数描述“有界复核”，删除“两个子 Agent”；保存后必须再次从后端读回，UI 不保留与服务端冲突的乐观值。
13. 提供 `scripts/verify-llmwiki-visual.mjs`（或仓库已有等价 runner）的稳定命令契约：接收 `--base-url`、`--out` 和四个 viewport，输出每个截图的尺寸、非空像素比例、水平溢出节点、可见焦点、对比度和 reduced-motion 检查 JSON；runner 失败必须返回非零，不得只保存手工截图。
14. 自动可访问性门至少要求普通文字对比度 `>=4.5:1`、大号文字和非文字 UI 边界 `>=3:1`；键盘焦点在所有交互控件上可见且不被 sticky 区域遮挡。`prefers-reduced-motion` 下不得出现位移、缩放或路径绘制动画。

### 完成定义

- 390×844 无横向裁切、不可达按钮或正文被底部导航遮挡。
- 1280×720 能同时容纳画布和证据轨道，无超高内部滚动区。
- 每个空状态、错误状态和动作按钮都触发真实行为。
- 用户不需要理解 candidate、FTS、vector、Kuzu、agent_run_id 或端口。
- 设置加载前后、离线和保存失败时都不显示猜测默认值，前后端状态一致。
- 关系或事实发生纠正后，证据轨道能展示旧值、新值、纠正时间和可追溯的 `supersedes` 链。
- 键盘可以切换 tab、搜索、选择节点、打开来源和执行安全动作。
- `MemoryWindowView.tsx` 与全局 polish CSS 明显收敛，没有新增同等规模的替代文件。
- `MemoryWindowView.tsx` 不超过 500 行；记忆 feature stylesheet 不超过 2,000 行；`desktop-polish.css` 相对执行前基线至少减少记忆页面选择器的 80%，且不存在新的末尾覆盖块。行数和被删除选择器清单写入证据，不能以“看起来更少”通过。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
Push-Location apps\desktop
try {
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_TYPECHECK_FAILED" }
    npm test
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_TEST_FAILED" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_BUILD_FAILED" }
    npm run runtime:mojibake:check
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_MOJIBAKE_FAILED" }
}
finally {
    Pop-Location
}
```

### 视觉验证

- Playwright：`390×844`、`1280×720`、`1366×768`、`1920×1080`。
- Electron 人工矩阵：Windows 100%、125%、150% DPI。
- 每个尺寸保存图谱、时间线、来源、空状态、失败状态、候选详情和冲突详情截图。
- 检查无水平滚动、文本重叠、截断按钮、空白画布和 focus 丢失。
- 运行 `node scripts/verify-llmwiki-visual.mjs --base-url http://127.0.0.1:5173 --out output/verification/LLMWIKI-009/visual --viewports 390x844,1280x720,1366x768,1920x1080`；JSON 中任一 viewport 的非空像素比例低于 `0.01`、水平溢出、焦点丢失、对比度不足或 reduced-motion 仍移动即失败。
- runner 不负责偷偷启动第二个后端；启动前由 Coordinator 使用仓库现有开发命令确认唯一 frontend/backend session token，URL 不可达时返回前置失败并记录，不得把空白截图当通过。

### 失败回滚

UI 与 API 同提交回滚。不得恢复旧页面后再叠加新页面；若新 IA 未通过，修正新组件结构并继续删除旧选择器。

### 证据产物

`output/verification/LLMWIKI-009/` 下保存设计方向、截图矩阵、键盘记录、DPI 人工记录和 CSS/组件行数对比。

### 禁止事项

- 不得引入第二个图库。
- 不得使用装饰性 orb、嵌套卡片、营销式大数字或无数据进度环。
- 不得用可见教学文案解释拖拽、滚轮和技术实现；常规操作使用图标、tooltip 和自然反馈。

---

## LLMWIKI-010：登录态常驻、sidecar 恢复与真实 24 小时语义

- **状态**：In Progress
- **优先级**：P1
- **依赖**：`LLMWIKI-002`、`LLMWIKI-008`、`LLMWIKI-009`
- **验证层级**：L3，登录自启、真实睡眠恢复、DPI 与通知权限为 L4
- **执行所有者**：Electron/sidecar Agent
- **独立复核**：只读进程/IPC/恢复 Reviewer
- **人工门**：Windows 打包产物的退出登录/重新登录、真实睡眠恢复和通知权限检查
- **允许修改范围**：Electron main/preload/IPC/sidecar/tray、backend scheduler/diagnostics、设置 UI 中的 resident runtime card、新增迁移 `022_resident_runtime_delivery.sql` 和测试；不重做 `LLMWIKI-009` 的记忆 IA 或其视觉主题。

### 目标

把“常驻”定义为用户登录 Windows 且选择自启后，应用驻留托盘并维护提醒、后台整理、索引和恢复；睡眠和关机期间不宣称在线。

### 24 小时业务语义

Soak 只证明以下无人值守工作在“用户已登录、机器未关机、应用未被用户退出”的边界内持续可恢复：提醒状态 reconcile、过期任务追赶、待处理记忆/Wiki job 的状态恢复、sidecar health 和图 generation 检查。它不证明模型质量、用户已看到通知或业务效率提升。每个 workload 都必须能映射到用户结果：任务不静默消失、恢复后不重复创建、图谱降级仍可浏览；不能把 CPU/内存健康样本直接写成“生产力提升”。

### 实施步骤

1. 通过 Electron `app.setLoginItemSettings` 提供明确的“登录后启动”开关；状态由 main/preload 管理，Renderer 不直接调用 Node。
2. 关闭窗口时保持托盘运行；“退出 Agent Pet”才停止 sidecar 和后台任务。
3. sidecar 非预期退出后使用 `1s, 2s, 5s, 15s, 30s` 有界退避；10 分钟内最多 5 次，之后进入人工重试状态。
4. 每次重启先检查 managed process identity 和 session token，不复用不受信任的陌生本地服务。
5. 监听 Electron `powerMonitor` suspend/resume。resume 后执行 health、sidecar 恢复、reminder reconcile、过期 job catch-up 和图 generation 检查。
6. 将通知去重从 Renderer 进程内 Set 移到 SQLite。每个 `(reminder_id, trigger_at)` 在调用 OS 前先提交唯一 automatic dispatch reservation；调用返回后记录 `display_invoked_at`。重启遇到未完成 reservation 时标记 `unknown_after_crash`，不得自动重试；用户手工重试使用新的 attempt id/idempotency key。
7. 通知采用“最多一次自动 dispatch”而不是 exactly-once delivery：它避免自动重复，但在 reservation 后、OS 调用前崩溃可能漏显，在 OS 调用后、回执前崩溃只能标记结果未知。任务始终保留并提供手工重试。
8. 暂停、恢复和崩溃期间的后台记忆 job 使用持久状态或可重建队列；不能因进程内 task 丢失而静默消失。
9. 普通错误显示“本地助手未启动/正在恢复/需要手动重试”；端口、日志路径和退出码位于可展开诊断。

### 完成定义

- 用户可开启/关闭登录自启并读回真实系统状态。
- sidecar 连续异常不会无限重启或产生多个进程。
- 睡眠跨过提醒时间后，恢复只产生一个 automatic dispatch reservation；崩溃窗口显示 `unknown`，不会静默重试或伪装送达。
- sidecar 在记忆或 Wiki job 中途退出后，任务可恢复或明确 failed，不静默成功。
- 文档明确只有登录态驻留，不声称关机、睡眠或云端 24×7。
- 有界恢复的重启预算、健康采样和 backlog 结果由 `LLMWIKI-013` 的阈值表判定；本任务本身通过机制测试不能标记真实 24 小时完成。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_reminder_scheduler.py apps/backend/tests/test_tasks_services.py apps/backend/tests/test_reminder_delivery.py -q
if ($LASTEXITCODE -ne 0) { throw "REMINDER_BACKEND_TEST_FAILED" }
Push-Location apps\desktop
try {
    npm test -- electron/sidecar.test.cjs electron/tray.test.cjs electron/main.test.cjs
    if ($LASTEXITCODE -ne 0) { throw "ELECTRON_RESIDENT_TEST_FAILED" }
    npm test -- electron/resident.test.cjs electron/ipc.test.cjs
    if ($LASTEXITCODE -ne 0) { throw "ELECTRON_IPC_TEST_FAILED" }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_TYPECHECK_FAILED" }
    node scripts/validate-electron-migration.mjs
    if ($LASTEXITCODE -ne 0) { throw "ELECTRON_MIGRATION_FAILED" }
}
finally {
    Pop-Location
}
```

### 必测故障

- sidecar 启动失败、运行中退出、连续五次退出、用户手动重试。
- suspend 前创建近时提醒，resume 后 catch-up。
- 通知权限拒绝，任务保留且显示重试入口。
- Renderer 重载和应用重启不重复发起同一 automatic dispatch；在 reservation 后和 OS 调用后分别注入崩溃，验证 unknown 状态、可能漏显边界和手工重试新 attempt。

### 人工登录态验证

1. 使用 Windows 打包产物开启“登录后启动”，退出账号并重新登录，确认只启动一个托盘实例和一个 managed sidecar。
2. 关闭“登录后启动”并权威读回 disabled，再次退出账号并登录，确认应用不会自行启动。
3. 保存 Windows 版本、打包产物 hash、设置读回、登录时间、进程树和结果；开发服务器重启不能替代该证据。

### 失败回滚

登录自启改动通过 Electron API 恢复为关闭；保留用户原设置。通知 delivery 表保留历史。sidecar 恢复失败时停止重试并提供手动路径，不杀死不属于本应用的进程。

### 证据产物

`output/verification/LLMWIKI-010/` 下保存进程树、退避时间、resume 日志、通知 delivery 行和设置读回截图。

### 禁止事项

- 不得安装 Windows system service。
- 不得把开机自启默认强制开启。
- 不得把 OS display attempt 写成送达或阅读成功。
- 不得声称 SQLite 与 Windows Notification API 之间存在跨进程原子事务。

---

## LLMWIKI-011：本地效果指标、固定评测与真实试用协议

- **状态**：Partial
- **优先级**：P1
- **依赖**：`LLMWIKI-004`、`LLMWIKI-006`、`LLMWIKI-007`、`LLMWIKI-008`、`LLMWIKI-009`、`LLMWIKI-010`
- **验证层级**：指标实现 L2，真实使用 L4
- **执行所有者**：指标与评测 Agent
- **独立复核**：只读隐私/统计口径 Reviewer
- **人工门**：真实用户执行 7 天试用；未完成时只允许 L2 指标实现状态
- **允许修改范围**：新增迁移 `023_product_metrics.sql`、指标 service/API、OpenAPI/desktop client/proxy 生成物、反馈 UI、评测语料、报告器、runbook 和测试。

### 目标

用不保存原始私密文本的本地事件衡量记忆是否真的减少重复解释、提高有据回答并可靠传播纠正。

### 数据契约

新增 `product_metric_events`：

- `id`、`event_version`、`event_type`、`idempotency_key`、`subject_hash`、`value`、`dimensions_json`、`created_at`；`idempotency_key` 唯一。
- `idempotency_key` 是单个指标事件的去重键：内部事件由 `event_version + event_type + authoritative transition id` 确定性生成，feedback 使用公共写请求 key；同一业务对象的不同事件类型必须得到不同 event key。
- `subject_hash` 只允许对非内容型稳定 ID 使用安装级 256-bit 密钥做 HMAC-SHA256；密钥通过现有 DPAPI credential boundary 保存，不进入 SQLite、日志或导出，完整隐私重置时轮换。
- 需要计算 attempt/effect、trigger/display 或 unhealthy/ready 配对的事件用 `subject_hash` 关联同一 action、reminder 或 sidecar incident；聚合不能把 event idempotency key 当作业务关联键。
- 不需要跨事件关联的事件将 `subject_hash` 留空；禁止直接 hash 用户文本、姓名、路径、短枚举或其他可字典枚举内容。
- 不保存用户原文、source excerpt、API key、绝对路径、authorization 或模型 prompt。
- 只允许固定事件枚举：`candidate_created`、`activated`、`recalled`、`feedback_recorded`、`corrected`、`forgotten`、`grounded_answer`、`no_evidence`、`action_attempted`、`business_effect_committed`、`duplicate_prevented`、`duplicate_effect_detected`、`reminder_triggered`、`reminder_display_attempted`、`reminder_display_unknown`、`sidecar_unhealthy`、`sidecar_ready`、`wiki_lint_result`、`lookup_started`、`lookup_completed`、`context_repetition_reported`、`wiki_reused`。
- `duplicate_effect_detected` 只有在权威 reader 对同一 action idempotency key 发现两个不同业务对象 ID 时才能产生；传输重试、重复 claim 或 `duplicate_prevented` 不能充当实际重复效果。
- `lookup_started`/`lookup_completed` 只记录安全查询引用、耗时和是否有 citation；`context_repetition_reported` 只记录用户明确反馈的重复说明次数或“无需重复说明”选择。三者都不得保存用户原文，不能从 token 数或模型自报自动推断业务节省。

### 公共接口

1. `GET /api/metrics/local-impact?window_days=7|30`
   - 返回 metric version、numerator、denominator、sample size、window、evidence status 和不含个人内容的 failure counts。
2. `POST /api/metrics/recall-feedback`
   - `signal` 只接收 `helpful`、`incorrect`、`missing`、`context_repeated`、`context_not_repeated`、`wiki_reused`；可选 `duration_ms`、`repetition_count` 和安全回答/召回/Wiki public reference，不接收原始聊天正文。
   - 记忆页和回答页在用户主动结束一次固定任务时提供同一个轻量反馈入口；未选择反馈不计入分母，不弹窗追问。
   - 强制使用 `LLMWIKI-008` 的 `Idempotency-Key`/payload hash/原 receipt 重放语义；相同 key 不同 payload 返回 409。

### 指标定义

| 指标 | 计算方式 | 证据边界 |
| --- | --- | --- |
| 记忆召回成功率 | helpful / 有反馈的图辅助回答 | 没有用户反馈的回答不进入分母 |
| 错误记忆率 | incorrect / 有反馈的图辅助回答 | 样本量必须同时展示 |
| 纠正传播率 | 下一次固定查询中旧事实缺席且新事实出现 / 已纠正案例 | 必须由自动验证或用户确认 |
| 来源覆盖率 | 至少一个通过验证 citation 的本地事实回答 / 本地事实回答 | 模型常识不计入 |
| 重复业务效果率 | `duplicate_effect_detected` / 去重后的 `action_attempted` idempotency keys | reader 必须证明同一 key 对应多个不同效果 ID；duplicate prevented 不算重复效果 |
| 提醒显示尝试率 | 去重后的 `reminder_display_attempted` / `reminder_triggered` | 两类事件都由 scheduler/delivery 权威状态产生；`reminder_display_unknown` 单列且不算成功，不等于用户已看到 |
| 恢复时间 | sidecar 异常到 health ready 的毫秒数 | 报告 P50/P95 和失败数 |
| Wiki 健康度 | 通过 lint 的 active pages / active pages | 同时展示断链、孤立和冲突数量 |
| 找回耗时 | `lookup_completed` 的 P50/P95 `duration_ms` | 只在同一固定任务和相同起始条件下与基线比较 |
| 重复说明次数 | `context_repetition_reported` 的每次旅程计数 | 必须由用户明确记录；没有 before/after 对照时只显示样本，不写节省百分比 |
| 确认负担 | review queue 候选到用户决定的 P50/P95 时间、每日队列峰值和撤销数 | 只衡量人工成本，不把确认次数越少自动解释成更好的记忆 |
| AI 必要性差异 | LLM ablation 与 deterministic/FTS-only baseline 的质量差、耗时差、调用次数和成本 | 没有固定 gold 或预算记录时状态为 evidence insufficient，不得宣称 AI 必要 |
| Wiki 复用率 | 用户从回答或任务回到 Wiki/source 并完成一次可验证编辑或决策复核 / 有 Wiki 引用的固定任务 | 只统计用户明确操作和 binding revision，不把页面打开次数当作价值 |

### 固定评测

- 至少 20 个生命周期案例：偏好、边界、项目、目标、事件、重复证据、纠正、忘记、冲突、过期和敏感内容。
- 至少 10 个无 evidence 案例，要求明确拒绝本地事实结论。
- 同一语料分别验证 SQLite traversal、Kuzu acceleration 和 Kuzu fallback。
- 同一语料再做 deterministic/FTS-only 与 LLM extraction/synthesis 的 ablation，记录质量、端到端耗时、模型调用次数和估算成本；当规则已能完成任务或模型代价超过预注册预算时，必须证明系统选择不调用 LLM。
- 报告 Recall@K、citation coverage、no-evidence accuracy、false activation、correction propagation、latency、lookup duration 和 confirmation burden；不把字符哈希对比称为 semantic quality。

### 真实试用协议

1. 先记录现有版本基线：找回一条个人事实所需时间、需要重复说明次数、错误纠正后是否复发。
2. MVP 最低证据为同一真实用户连续 7 天使用，保留样本量和失败案例。
3. 只有实际完成 24 小时运行记录后才报告稳定性。
4. 面向一般用户的提升结论至少需要 10-20 名参与者、2-4 周和一致任务；没有该证据时只描述单用户案例。单用户 7 天的重复观测不能当作独立用户样本，也不能外推团队或行业结论。
5. UI 样本少于 20 条反馈时显示“证据不足”，不显示百分比趋势箭头。
6. LLM 与 deterministic baseline 的差异只报告固定语料和调用预算内的结果；没有反事实对照时不得说“AI 带来提升”。

### 实施步骤

1. 新增非破坏性指标迁移、固定事件枚举、维度 allowlist 和唯一 idempotency key；拒绝未知事件、未知维度和原始文本字段。
2. 复用现有 DPAPI 凭据边界生成本机 HMAC secret，提供不可导出的 subject token helper 和隐私重置轮换测试。
3. 在记忆生命周期、召回反馈、动作协调器、提醒、sidecar 状态和 Wiki lint 的权威状态迁移点各埋一次事件；按固定规则产生 action/实际效果/重复效果和 reminder 分子分母，禁止 UI 与 service 重复计数。
4. 实现按 7/30 天窗口重算的聚合 service，所有指标返回 numerator、denominator、sample_size、evidence_status 和版本。
5. 实现本任务拥有的 metrics API，在 `LLMWIKI-002` 的唯一 registry 注册 `metrics.feedback` adapter/reader，并覆盖断线重试、payload 冲突和重复事件不计数。
6. 先运行 `scripts/generate-openapi.ps1` 从当前 FastAPI 路由导出，再生成 desktop types 和 Electron allowlist；新增或漂移 metrics 路由必须使契约检查失败。
7. 建立版本化固定语料和一条命令评测 runner，分别运行 SQLite、Kuzu 与 fallback，输出 JSON 和 Markdown。
8. 在 `LLMWIKI-009` 已稳定的工作区加入最小反馈控件和本机指标视图，检查键盘、失败、空数据和重置后的状态，不重建第二套页面 IA。
9. 编写真实 7 天试用 runbook，先采基线，再记录每日样本、失败和退出；报告器不得自动填充尚未发生的数据。
10. 为候选 review queue 记录队列长度、确认耗时、撤销次数和 false activation；超出人工可处理容量时显示积压，不自动放宽激活策略。
11. 在回答结束和 Wiki/source 详情的真实用户动作之后接入 `context_repeated`/`context_not_repeated`/`wiki_reused` feedback；同一固定任务只能提交一次相同 signal，网络重试复用幂等键。
12. 将评测 runner 固定为 `scripts/verify_llmwiki_metrics.py` 的版本化入口；它必须接受 fixture 和输出目录，写入配置 hash、baseline/ablation 分组、样本数、分子/分母和退出码，不读取或输出原始文本。

### 完成定义

- 指标可从真实事件重算，分子、分母、窗口和样本量可检查。
- 重置本地记忆时按现有隐私契约清理相关指标。
- 指标 API 和 UI 不包含原始文本或可逆个人标识。
- 同一幂等键的重复 feedback 或恢复事件只计一次，不同 payload 复用 key 会被拒绝。
- 固定评测可以一条命令重跑并产生 JSON 与 Markdown 报告。
- 没有实际试用数据时文档只列目标和采集方法。
- 业务价值报告至少能重算找回耗时和重复说明次数的同任务 before/after 样本；样本不足时 API 返回 `evidence_insufficient`，不返回趋势结论。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
python -m pytest apps/backend/tests/test_memory_activation.py apps/backend/tests/test_memory_feedback_api.py -q
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_011_MEMORY_TEST_FAILED" }
python -m pytest apps/backend/tests/test_product_metrics.py -q
if ($LASTEXITCODE -ne 0) { throw "PRODUCT_METRICS_TEST_FAILED" }
python -m pytest apps/backend/tests/test_retrieval_quality_eval.py apps/backend/tests/test_retrieval_grounding.py -q
if ($LASTEXITCODE -ne 0) { throw "RETRIEVAL_EVAL_TEST_FAILED" }
python -m pytest apps/backend/tests/test_security_hardening_mvp.py apps/backend/tests/test_persistence_mvp.py -q
if ($LASTEXITCODE -ne 0) { throw "PERSISTENCE_SECURITY_TEST_FAILED" }
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\generate-openapi.ps1
if ($LASTEXITCODE -ne 0) { throw "OPENAPI_GENERATION_FAILED" }
python -m pytest apps/backend/tests/test_openapi_snapshot.py -q
if ($LASTEXITCODE -ne 0) { throw "OPENAPI_SNAPSHOT_FAILED" }
python scripts/verify_llmwiki_metrics.py --fixture apps/backend/tests/evals/retrieval/retrieval-corpus-v1.json --out output/verification/LLMWIKI-011/eval
if ($LASTEXITCODE -ne 0) { throw "LLMWIKI_METRICS_EVAL_FAILED" }
Push-Location apps\desktop
try {
    npm run generate:api-contracts
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_API_GENERATION_FAILED" }
    npm run check:api-contracts
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_API_CONTRACT_CHECK_FAILED" }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_TYPECHECK_FAILED" }
}
finally {
    Pop-Location
}
```

### 失败回滚

指标采集失败不得阻断聊天、记忆、提醒或 Wiki。回滚代码时保留匿名事件表；错误事件版本在报告中过滤，不重写历史。

### 证据产物

`output/verification/LLMWIKI-011/` 下保存评测配置 hash、JSON/Markdown 报告、隐私字段扫描、基线模板和真实试用记录模板。

### 禁止事项

- 不得生成虚构业务数据或预填成功百分比。
- 不得用合成评测替代真实 7 天使用。
- 不得把单用户结果推广为所有用户提升。

---

## LLMWIKI-012：重写产品、技术价值、失败边界与作品集证据

- **状态**：Partial
- **优先级**：P1
- **依赖**：`LLMWIKI-001` 至 `LLMWIKI-011`
- **验证层级**：L2，涉及真实试用结论时为 L4
- **执行所有者**：产品证据与文档 Agent
- **独立复核**：只读 claim-to-evidence Reviewer
- **人工门**：对外发布前由用户确认简历和案例研究中的最终声明
- **允许修改范围**：`README.md`、`PRODUCT.md`、现有 architecture/portfolio/runbook/acceptance 文档；不新建平行产品说明。

### 目标

让第一次看到项目的人能回答：它解决什么问题、谁怎样使用、为什么需要 AI、每个技术栈解决什么、技术难点是什么、失败怎样恢复、当前边界和证据是什么。

### README 固定结构

1. `Agent Pet`：本地个人 LLM Wiki 与记忆图谱。
2. 一句话问题：减少跨会话重复解释，同时让长期记忆可追溯、可纠正、可忘记。
3. 目标用户与非目标：明确 Windows 单用户边界，不把个人产品写成团队平台。
4. 外部个人用户怎样安装、输入/导入、确认、召回、纠正和忘记。
5. 公司内部单员工试点怎样隔离 Vault、记录基线、执行 7 天协议并导出脱敏聚合。
6. 一条可复验主旅程：输入/导入 → 候选 → 确认/激活 → Wiki/图 → 新会话召回 → 纠正/忘记。
7. 为什么是 AI，为什么权限和副作用不能交给 AI。
8. 架构图：模型角色、确定性控制、SQLite、Markdown、派生检索和 Electron 边界。
9. 技术难点：跨存储一致性、实体消歧、图代次、失败恢复、常驻/通知边界，以及采用当前方案而非更简单方案的理由。
10. 技术栈价值与边界表。
11. 失败矩阵和用户可执行下一步。
12. 指标与证据：实际值、样本量、命令和日期；缺失项明确缺失。
13. 24 小时语义和 7 天试用边界。
14. 当前限制和非目标。
15. 安装、运行和验证命令。

### 技术栈必须这样解释

| 技术 | 使用价值 | 不得夸大的边界 |
| --- | --- | --- |
| Electron | Windows 托盘、自启、通知、受控 preload 和 sidecar 生命周期 | 不是跨平台企业客户端；未验证平台不得宣称 |
| React/TypeScript | 组织桌面工作区、交互状态和生成 API 类型，让图谱、时间线、来源及失败状态共享可检查的 UI 契约 | 类型通过不等于真实交互、可访问性或视觉完成 |
| `@xyflow/react` | 承载可缩放的实体/事实关系画布、选择状态和证据轨道联动，复用已有图交互而不自建画布引擎 | 只负责可视化交互，不证明关系真实，也不能决定召回权限 |
| Vite | 提供桌面 Renderer 的开发、测试入口和可重复构建产物 | 只是构建工具，不构成业务能力或架构创新 |
| FastAPI/Pydantic | 本地 API 隔离、结构化契约、验证和错误边界 | 不等于企业后端或高并发服务 |
| Uvicorn | 在 Electron 管理的 sidecar 中承载本机 ASGI 服务，并提供可探测的进程与健康边界 | 本机进程可启动不等于云服务可用性或 24x7 在线 |
| LangChain | OpenAI-compatible 模型和工具接口适配 | 接入框架不等于 Agent 自治 |
| LangGraph | 有状态路由、有界协作和可恢复控制流 | 普通快速聊天可绕过；没有 Supervisor/并行群体 |
| SQLite | 权威实体、事实、生命周期、动作和本地指标 | 单机存储，不是团队数据库 |
| SQLAlchemy | 为 APScheduler 的 SQLite job store 提供提醒任务持久化 | 只服务调度持久化，不代表存在通用 ORM 领域层或分布式队列 |
| Markdown Vault | 用户可读、可迁移的来源和 Wiki 正文 | 跨存储写入需要回执与恢复 |
| FTS5 | 无额外服务的可靠全文召回和 fallback | 不是语义理解证明 |
| Kuzu | 可重建关系遍历加速和图查询实验 | 不是权威存储；故障时必须降级 |
| Qdrant | 可选向量候选实验 | 未通过晋升评测前不作为生产默认 |
| APScheduler | 提醒持久化和恢复后追赶 | PC 睡眠/关机时不是云端调度 |
| SSE | 流式状态、引用和动作事件 | 改善等待体验，不提高模型正确率 |

### 必须展示的失败案例

- 模型不可用但本地 Wiki/图/FTS 可浏览。
- 本地没有 evidence 时明确拒绝。
- 新旧事实冲突并排展示。
- 纠正后旧事实退出召回。
- Markdown hash 冲突停止写入。
- effect 后 receipt 前崩溃恢复不重复。
- Kuzu 损坏回退 SQLite。
- sidecar 异常有界恢复并最终需要人工重试。
- 通知权限拒绝但任务不丢失。

### 实施步骤

1. 从生产入口、API 契约、自动化测试、L3 记录和时间型证据生成 claim-to-evidence 矩阵；先删除无入口或只有计划的声明。
2. 按固定结构重写 `README.md` 和 `PRODUCT.md`，先写问题、用户和主旅程，再写 AI 分工、技术价值、失败和限制。
3. 更新现有架构文档，明确 SQLite/Markdown 权威边界、Kuzu/FTS/向量派生边界、Electron trust boundary 和动作生命周期。
4. 重写现有案例研究与演示脚本，使用“成功路径 + 对应失败路径 + 当前边界 + 证据命令”的统一格式。
5. 将每项技术映射到真实调用点、解决的问题、为何不用更简单方案和已知限制；无法指向调用点的技术从主技术栈删除。
6. 只从实际指标报告生成结果段落；样本不足时展示基线、样本量和 `证据不足`，不展示目标百分比为成果。
7. 更新简历证据和内部试点描述，限制为本地单用户；执行 `scripts/check-portfolio-claims.ps1` 的上下文感知扫描、链接检查和截图审阅后修正不一致。扫描器必须区分否定性限制句和未经限定的肯定宣传句。

### 完成定义

- 文档先讲业务问题和用户旅程，再讲技术。
- 每项功能都说明解决的具体问题，而不是只列“支持”。
- 每项技术都有价值、实际调用点和限制。
- 成功演示至少配一个失败/边界演示。
- case study 的 action、Wiki、图谱和指标描述与生产代码一致。
- 内部公司使用只描述为单员工本地试点，不描述团队协同。

### 测试命令

```powershell
$ErrorActionPreference = 'Stop'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-mvp-acceptance-gap.ps1
if ($LASTEXITCODE -ne 0) { throw "MVP_ACCEPTANCE_GATE_FAILED" }
python -m pytest apps/backend/tests/test_mvp_acceptance_gap_contract.py -q
if ($LASTEXITCODE -ne 0) { throw "MVP_ACCEPTANCE_CONTRACT_FAILED" }
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-portfolio-claims.ps1
if ($LASTEXITCODE -ne 0) { throw "PUBLIC_CLAIM_GATE_FAILED" }
```

### 失败回滚

文档只能回滚到当前代码能证明的更窄描述，不恢复营销化旧口径。过期内容在原文件中重写，不追加“旧版说明”。

### 证据产物

`output/verification/LLMWIKI-012/` 下保存 claim-to-code/test 索引、README 截图、失败演示记录和文档验证日志。

### 禁止事项

- 不得用技术列表代替技术价值。
- 不得把设计目标写成已实现结果。
- 不得只保留成功截图。

---

## LLMWIKI-013：全量验收、24 小时 soak、7 天证据与重新评分

- **状态**：Partial
- **优先级**：Release Gate
- **依赖**：`LLMWIKI-001` 至 `LLMWIKI-012` 的实现 slice 均已达到各自自动化门；允许仍等待本任务统一执行的 L3/L4、24 小时、7 天或 Windows 人工门保持 `Partial`
- **验证层级**：L3 + L4
- **执行所有者**：Release Coordinator
- **独立复核**：未参与实现的只读 Release Reviewer
- **人工门**：干净 Windows 包启动、DPI、退出登录/重新登录、真实 24 小时 soak 和真实 7 天使用
- **允许修改范围**：测试、验证脚本、当前事实文档和 `output/verification/LLMWIKI-013/`；发现缺陷时返回对应任务修根因。

### 目标

证明完整产品路径在当前源码、打包产物、故障条件和真实时间窗口中成立，并依据证据而不是实现数量重新评分。

### 状态门槛

- **Implementation-ready prerequisite**：`LLMWIKI-001` 至 `012` 的代码、迁移、契约、局部测试和任务内可执行验证均已通过。仅因统一故障矩阵、视觉人工门、24 小时或 7 天尚未由 013 执行而保持 `Partial` 的任务不阻止 013 启动；存在代码/迁移/契约失败的前置任务仍会阻止启动。
- **Implementation checkpoint**：前述实现 slice 已具备自动化、固定 E2E 和开发机 package smoke，但必需的 L3/L4 与时间型旅程尚未全部结束。2026-08-14 当前快照为后端四个不重叠 shard 共 `1193 passed, 2 skipped, 0 failed`（汇总：`output/verification/LLMWIKI-013/quality/backend-full-20260814-sharded.json`）、Mypy 213 个源文件和 Ruff 通过、桌面 Vitest `61 files / 481 passed`、typecheck/OpenAPI contract/Vite build 通过。action journey 为 `5 Passed / 0 Failed / 0 Partial`，记忆跨重启闭环与 Wiki source-to-decision journey 均为 `Passed`；故障矩阵仍为 `15 Passed / 0 Failed / 3 Partial`。最近一次独立整档评分仍是 2026-08-11 的 raw/reported `62/100`，新测试数量本身不加分；评分报告见 `output/verification/LLMWIKI-013/final-score-20260811.md`。3 个故障 Partial 是打包 Electron sidecar 崩溃路径、真实 Windows 睡眠恢复和 Windows 通知权限拒绝；FTS Recall@5 仍为 `0.496` 且 Failed。此时 `LLMWIKI-013` 必须保持 `Partial`，评分最高 84，只允许标记为本地单用户内部试用候选。
- **Full closure**：所有人工门、干净 Windows/登录态、真实 24 小时 soak 和真实 7 天使用均完成且达到阈值。此时 013 才能标记 Completed，任务集才可关闭，并按实际结果判断是否达到 85 以上。
- `Partial` 会阻止稳定发布、最终任务集关闭和 85+ 宣传；它不是失败伪装。某项已运行且不达标时状态为 Failed，必须修根因并重跑，不能降为“尚未验证”。

### 可重复判定阈值

这些是运行前冻结的本地 MVP 工程门，不是已取得的业务结果；每次运行必须把阈值版本写入报告。未运行是 `Partial`，运行后低于门槛是 `Failed`，环境缺失且连续三次无法补齐才是 `Blocked`。

| 门 | 通过条件 | 未通过处理 |
| --- | --- | --- |
| 迁移与一致性 | 空库、旧库和重复执行均成功；schema version 全部登记；用户表行数不减少；外键/唯一约束检查为 0 错误 | 回到 `LLMWIKI-003`，恢复备份并重跑迁移测试 |
| 固定记忆评测 | no-evidence accuracy `100%`；敏感/未知 false activation `0`；correction propagation `100%`；citation coverage `>=95%`；SQLite/Kuzu 授权结果 100% 等价 | `Failed`，不得用人工解释抵消自动门；修复后重跑受影响任务 |
| 图谱增量价值 | 图关系子集 Recall@K 比 FTS/Wiki-only baseline 高至少 `10` 个百分点，且 P95 延迟不超过 baseline `1.2x`；否则 Kuzu 保持可选 fallback | 不晋升 Kuzu 默认，不写图谱带来提升 |
| 24 小时 soak | 至少 `1,440` 个每 60 秒健康样本；ready 比例 `>=99.5%`；0 个重复本地业务效果；结束时 0 个未解释 claim、`failed_recovery` 或 backlog；每次故障恢复 P95 `<=60s`；预热后 RSS 和 handle 的线性增长不超过 `10%`；generation lag P95 `<=5min` 或有明确 fallback | 中断或任一硬门失败都重新计时；记录用户影响和根因 |
| 7 天真实使用 | 同一真实用户完成 7 个日历日，每天至少 1 次固定核心旅程；记录召回、纠正、忘记、重复说明和失败的实际分母；反馈少于 `20` 条只显示证据不足 | 保持 `Partial`，不得写效率/留存提升 |
| 85+ 发布门 | 前述所有工程门和人工门通过，所有 P0/P1 无 `Failed`；至少 `20` 个同任务 before/after 配对旅程分布在 7 个日历日；至少一个预注册价值指标按“先算日内配对差、再以日为 cluster 做固定种子 10,000 次 BCa bootstrap”的 95% 区间下界高于 0，并同时公开 7 个原始日聚合值 | 否则最高 84；只发布机制和基线 |

该 85+ 门只决定本地单用户项目的工程评分，不能被改写为统计学上的普遍业务提升。对外一般化 uplift 仍必须满足 `LLMWIKI-011` 的 10-20 名参与者、2-4 周和一致任务要求；单用户 bootstrap 次数再多也不会增加独立用户样本量。

### 实施步骤

1. 冻结待验收 commit、依赖锁、模型配置脱敏摘要、固定语料 hash 和 SQLite/Vault 一致性备份；后续修复必须重新开始受影响的门。
2. 创建并运行 `scripts/run-llmwiki-migration-smoke.ps1`：在临时空库、旧库副本和重复运行三种模式调用真实 `MigrationRunner`，输出 schema/行数/约束 JSON，非零退出码表示失败。
3. 依次运行迁移、后端质量门、前端契约/typecheck/test/build、Electron 迁移检查和 Windows 打包，不并行掩盖共享状态故障。
4. 创建并运行 `scripts/run-llmwiki-fault-matrix.ps1`，通过真实 API 与桌面路径执行固定端到端旅程，并逐项注入模型、证据、结构化输出、关系、Markdown、Kuzu、sidecar、睡眠、通知、敏感策略和副作用崩溃故障；脚本必须清理自己启动的进程和隔离数据，并以非零退出码汇总任一失败场景。
5. 使用 `$frontend-design` 的两轮批判结果完成四个 viewport 截图、键盘、对比度、reduced-motion 和三个 DPI 人工矩阵。
6. 在干净 Windows 环境启动目录包，记录 sidecar、Vault 初始化、托盘、退出和重启；缺少环境时保持 Partial。
7. 启动真实连续 24 小时 soak；中断即记录失败并重新计时，短时模式只用于调试脚本。
8. 按 runbook 完成至少一名真实用户的 7 天核心旅程；每天记录样本量、反馈、纠正、失败和主动重试。
9. 汇总通过、失败、Partial 和未运行证据，按八个维度重新评分；任何缺陷返回所属任务修根因，再重跑受影响门。

### 测试命令

以下质量门、真实路径、视觉矩阵和时间型验证共同组成验收，不能只选成功的命令。

#### 预检、迁移与故障矩阵

```powershell
$ErrorActionPreference = 'Stop'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\preflight-windows.ps1
if ($LASTEXITCODE -ne 0) { throw "PREFLIGHT_GATE_FAILED" }
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-llmwiki-migration-smoke.ps1 -OutputDir output\verification\LLMWIKI-013\migration
if ($LASTEXITCODE -ne 0) { throw "MIGRATION_GATE_FAILED" }
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-llmwiki-fault-matrix.ps1 -OutputDir output\verification\LLMWIKI-013\faults
if ($LASTEXITCODE -ne 0) { throw "FAULT_GATE_FAILED" }
```

`run-llmwiki-fault-matrix.ps1` 必须以真实 API/sidecar 进程和隔离数据库运行，不得用替换 executor、手工 receipt 或只测纯函数的模拟代替；每个场景输出 `scenario`, `injected_at`, `observed_state`, `user_next_step`, `duplicate_effects`, `exit_code` 字段。

#### 后端质量门

```powershell
$ErrorActionPreference = 'Stop'
Push-Location apps\backend
try {
    python -m ruff check app tests
    if ($LASTEXITCODE -ne 0) { throw "BACKEND_RUFF_GATE_FAILED" }
    python -m mypy app
    if ($LASTEXITCODE -ne 0) { throw "BACKEND_MYPY_GATE_FAILED" }
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "BACKEND_PYTEST_GATE_FAILED" }
}
finally {
    Pop-Location
}
```

触及的模块不得继续依赖 mypy 全模块 `ignore_errors`。如果全仓存量错误仍存在，必须至少将本轮修改模块从豁免列表删除并保持错误数不增加；报告剩余债务，不得把部分 typecheck 写成全量通过。

#### 桌面质量门

```powershell
$ErrorActionPreference = 'Stop'
Push-Location apps\desktop
try {
    npm run check:api-contracts
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_API_CONTRACT_GATE_FAILED" }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_TYPECHECK_GATE_FAILED" }
    npm test
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_TEST_GATE_FAILED" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_BUILD_GATE_FAILED" }
    npm run sprite-pet:check
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_SPRITE_GATE_FAILED" }
    npm run runtime:mojibake:check
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_MOJIBAKE_GATE_FAILED" }
    npm run pet:bubble:check
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_BUBBLE_GATE_FAILED" }
    npm run package:check
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_PACKAGE_CHECK_GATE_FAILED" }
    node scripts/validate-electron-migration.mjs
    if ($LASTEXITCODE -ne 0) { throw "DESKTOP_ELECTRON_MIGRATION_GATE_FAILED" }
}
finally {
    Pop-Location
}
```

#### Windows 打包门

```powershell
$ErrorActionPreference = 'Stop'
Push-Location apps\desktop
try {
    npm run package:win:dir
    if ($LASTEXITCODE -ne 0) { throw "WINDOWS_PACKAGE_GATE_FAILED" }
}
finally {
    Pop-Location
}
```

必须在没有依赖 PATH 中 Python 的干净 Windows 环境进行一次打包产物启动；若缺少可用环境，状态保持 Partial 并明确缺失，不得用开发机启动替代。

同一打包产物还必须执行 `LLMWIKI-010` 的自启人工门：开启后退出登录/重新登录只启动一个实例，关闭后再次退出登录/登录不自启。没有该记录时不能完成 Full closure。

#### 固定端到端场景

1. 新用户初始化本地 Vault。
2. 明确保存偏好、边界和项目事实。
3. 自动抽取一条普通候选，证明确认前不进入回答。
4. 新会话按实体关系召回并显示 evidence/Wiki。
5. 纠正事实，证明旧事实退出、新事实进入。
6. 忘记事实，证明所有读取通道不再召回。
7. 导入两份来源，生成 entity、synthesis 和 decision 页面。
8. 制造冲突，证明不确定回答和确认路径。
9. 在 task effect 后 receipt 前注入崩溃，恢复后无重复。
10. 通过真实生产 planner 发起高风险 task、memory 和 Wiki 动作，分别验证批准执行原目标一次、拒绝零次，以及批准后响应前崩溃不重复；不得替换 executor 或手工构造 checkpoint payload。
11. 损坏 Kuzu，证明 SQLite fallback；重建后结果一致。
12. 模型离线，证明本地浏览、搜索和手工控制可用。
13. sidecar 异常、睡眠恢复和提醒权限拒绝均有可操作状态。
14. 创建两个同名人物和两个含相同 Wiki 路径的 Vault，证明身份不误合并且查询不跨 active Vault。
15. 外部编辑 active Wiki 页面，证明查询前 reconcile 使旧 Kuzu generation stale 并回退，重建后恢复。
16. 在通知 reservation 后和 OS 调用后注入崩溃，证明 at-most-once 自动 dispatch、unknown 状态和手工重试边界。
17. 导入含 prompt injection、敏感字段和非法结构化输出的来源，证明策略版本、拒绝码、远程调用次数、候选状态和用户下一步均可审计，且没有任何未授权图写入。
18. 注入模型 timeout、rate limit、quota exhausted、用户取消和部分 SSE，证明只读重试有界、写副作用为零、片段不进入记忆/Wiki/receipt，并显示本地下一步。

#### 视觉门

- Playwright 截图：390×844、1280×720、1366×768、1920×1080。
- Electron 人工：100%、125%、150% DPI。
- 检查首页、图谱、时间线、来源、候选、冲突、无 evidence、模型离线、sidecar 恢复和设置。
- 使用截图像素检查确保 canvas 非空，文字与按钮无重叠，图片资源加载成功。
- 运行 `node scripts/verify-llmwiki-visual.mjs --base-url http://127.0.0.1:5173 --out output/verification/LLMWIKI-013/visual --viewports 390x844,1280x720,1366x768,1920x1080`；任一 viewport 非空像素比例低于 `0.01`、出现水平溢出、焦点不可达、对比度不足或 reduced-motion 仍产生位移时退出非零。

#### 24 小时 soak

在允许修改范围内先实现 `scripts/run-agentpet-soak.ps1`，再以 `-DurationHours 24 -IntervalSeconds 60 -OutputDir output/verification/LLMWIKI-013/soak` 真实连续运行至少 24 小时。脚本必须在启动前检查本机登录态、sidecar identity、数据库备份和输出目录；正常通过返回 `0`，前置条件不足返回 `2`，阈值失败返回 `1`。每 60 秒记录：

- health、sidecar PID 和重启次数。
- 进程内存、handle 数和 CPU 快照。
- post-reply job backlog 和失败数。
- action claimed/executing/failed_recovery 数量。
- 重复业务效果数量。
- reminder triggered/display-attempted/display-unknown 数量和自动重复 dispatch 数量。
- Kuzu generation lag 和 fallback 次数。
- SQLite locked/error 和 Wiki lint 结果。

允许另设短时故障注入模式验证脚本，但短时模式不能替代真实 24 小时结果。报告必须自动计算本节阈值的每个分子/分母、RSS/handle 预热基线和增长斜率；soak 中断时重新计时并记录中断原因。

#### 7 天真实使用

- 至少一名真实用户连续 7 天完成核心旅程。
- 记录召回反馈、纠正、忘记、来源覆盖、失败和主动重试。
- 报告实际样本量和未完成天数。
- 没有 7 天证据时，相关状态保持 Partial，最高评分不得超过 84。
- 7 天记录必须包含同一固定任务的基线和使用后数据、用户主动反馈及失败样本；报告器不能根据聊天内容猜测“节省时间”。

#### 重新评分规则

沿用本文件八个评分维度：

- L1/L2 只能证明局部和契约，不足以获得完整产品分。
- 核心跨会话流程需要 L3。
- 视觉、理解成本、DPI、24 小时和 7 天使用需要 L4 或真实时间证据。
- 代码完成且 L3 通过的合理目标为 80-84。
- 只有真实 24 小时和 7 天数据达到任务标准时才可评 85 以上。
- 任何分数必须附维度、证据路径、命令、日期和残余风险。

### 完成定义

- 所有自动化命令有保留日志和退出码。
- 所有固定 E2E 场景通过真实 API/桌面路径。
- 视觉矩阵无阻断缺陷。
- 24 小时、7 天和指定 Windows 人工门真实完成；未完成时只能记录 Implementation checkpoint，013 保持 Partial。
- README、case study、acceptance 和最终评分使用同一证据边界。
- 工作树中没有备份、临时补丁、死接口、旧样式覆盖或生成文件漂移。

### 失败回滚

任何失败返回拥有该行为的前置任务修根因。不得在验收任务中增加特殊判断绕过失败。用户数据从执行前 SQLite/Vault 备份恢复；Kuzu 从权威数据重建。

### 证据产物

`output/verification/LLMWIKI-013/` 下保存完整命令日志、E2E 数据、截图、DPI 记录、打包 smoke、24 小时报告、7 天报告和最终评分。

### 禁止事项

- 不得把跳过、模拟、短时或开发机结果写成更高层级证据。
- 不得为达到 85 分编造长期数据。
- 不得在失败时降低既定验收阈值。

---

## 5. 全局失败矩阵

| 故障 | 用户行为 | 系统行为 | 记录 |
| --- | --- | --- | --- |
| 模型不可用 | 可浏览、搜索、纠正和忘记已有内容；可进入连接设置 | 停止新模型抽取和综合，不执行无验证写入 | 安全错误码、恢复时间 |
| 本地无 evidence | 修改查询、导入来源或直接记录新信息 | 明确无本地证据，不用模型常识伪装个人事实 | no-evidence event |
| 模型结构非法 | 重试或手工录入 | 整批拒绝，不部分写入 | extraction failure |
| 关系冲突 | 查看双方来源并确认 | 隔离冲突，不进入确定回答 | conflict lifecycle |
| Markdown hash 冲突 | 查看差异并重新生成 | 停止写入，保留提案和 snapshot | failed_recovery |
| effect 后 receipt 前崩溃 | 等待恢复或查看人工恢复状态 | 权威读回，匹配则补 receipt，不重复执行 | claim/receipt/verification |
| 高风险动作等待确认 | 查看原目标摘要并批准、拒绝或修改 | checkpoint 保留原 proposal；批准后重新校验并进入同一协调器，拒绝零副作用，修改产生新 proposal | proposal/policy/approval/receipt |
| Kuzu 不可用 | 正常查询，看到轻量降级提示 | 使用 SQLite traversal，安排重建 | fallback + generation |
| SQLite 不可用/损坏 | 停止写入，进入恢复指引 | 不使用 Kuzu 反向覆盖权威库 | backup/restore audit |
| sidecar 崩溃 | 看到恢复状态；达到上限后手动重试 | 有界退避，避免多进程 | restart attempts |
| 通知权限拒绝 | 任务仍可查看并重试通知 | 保留 reminder，记录 display failure | delivery attempt |
| 通知 reservation 后崩溃 | 任务仍可查看；根据 unknown 状态决定手工重试 | 不自动重复 dispatch，不声称已送达，接受窄窗口可能漏显 | reservation/unknown/manual retry |
| 敏感内容 | 可选择本地记录或放弃 | 不发送远程模型，不进入普通图投影 | policy decision |
| 模型超时/限流/额度耗尽 | 等待冷却、重试只读查询或改为本地操作 | 不重试副作用；候选保持 pending/failed，部分 SSE 标记 interrupted | provider error code、attempt、cooldown |
| 用户取消/部分流 | 继续浏览或重新提交完整请求 | 丢弃未完成模型结构，不把片段写入记忆/Wiki/receipt | cancellation/interrupted |

---

## 6. 全局完成条件

Implementation checkpoint 可以在时间型证据未完成时交付供本地单用户试用，但不得称为任务集关闭。Full closure 只有在以下条件同时成立时成立：

1. 生产动作路径真实使用持久 claim、receipt 和权威读回。
2. 通用事实完成跨会话召回、纠正和忘记闭环。
3. 图节点和关系来自权威实体、受控本体和 evidence，不来自关键词共现。
4. LLM Wiki 完成 source、entity、fact/relation、synthesis、decision 生命周期。
5. Kuzu 可删除重建，故障时 SQLite fallback 正确。
6. 记忆页面采用图谱/时间线/来源 IA，桌面和窄屏均通过视觉验收。
7. 登录态常驻、sidecar 恢复、睡眠追赶和通知尝试有真实路径。
8. 指标展示分母、样本和证据状态，不包含原始隐私文本。
9. README 和作品集逐项说明问题、用户流程、AI 必要性、技术价值、失败和边界。
10. 所有自动化、E2E、打包、登录态、视觉、真实 24 小时和真实 7 天证据均完成并留存；任一未完成时 013 保持 Partial，任务集不关闭。
11. 最终评分依据证据重新计算，没有预设成功结论。
12. `$pristine` 最终检查通过：无补丁堆、重复事实来源、备份、死代码和本地/打包漂移。

---

## 7. Coordinator 执行协议

1. 状态只允许 `Pending`、`In Progress`、`Partial`、`Skipped`、`Blocked`、`Failed`、`Completed`；每次只把一个 `LLMWIKI-XXX` 标记为 In Progress。`Partial` 前置任务可以在 Coordinator 记录风险后继续修复其依赖的根因，但不得把依赖未完成写成当前任务 Completed，也不得跳过失败门。
2. 开始任务前记录 `git status --short`，遇到用户已有改动时保留并协作，不回退。
3. 先运行最小回归，再运行受影响子系统，最后运行发布门。
4. 实现 Agent 只能修改任务的允许范围；需要扩展时由 Coordinator 记录原因和风险。
5. 只读审查 Agent 不得修改代码；同一文件同一时间只能有一个写入所有者。
6. 每个任务的证据保存到对应 `output/verification/LLMWIKI-XXX/`，文档只保留摘要和边界。
7. 人工、24 小时和 7 天门槛不能由自动化代替。
8. 任务失败时返回根因所属任务，不在后续任务打补丁。
9. 所有生成文件使用仓库生成命令更新，禁止手改。
10. 最终运行 `git diff --check`、生成漂移检查和工作树卫生检查。

## 8. 任务书自身结构检查

创建或修改本文件后执行：

```powershell
$ErrorActionPreference = 'Stop'
$path = (Resolve-Path .\修改task.md).Path
$bytes = [System.IO.File]::ReadAllBytes($path)
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
try {
    $content = $utf8.GetString($bytes)
} catch {
    throw 'INVALID_UTF8'
}

$expectedIds = 1..13 | ForEach-Object { 'LLMWIKI-{0:D3}' -f $_ }
$taskPattern = '(?ms)^## (LLMWIKI-\d{3})：.*?(?=^## LLMWIKI-\d{3}：|\z)'
$tasks = [regex]::Matches($content, $taskPattern)
$actualIds = @($tasks | ForEach-Object { $_.Groups[1].Value })

if ($tasks.Count -ne 13) {
    throw "TASK_COUNT_INVALID:$($tasks.Count)"
}
if (($actualIds -join ',') -ne ($expectedIds -join ',')) {
    throw "TASK_IDS_INVALID:$($actualIds -join ',')"
}

$requiredMarkers = @(
    '- **状态**：',
    '- **优先级**：',
    '- **依赖**：',
    '- **验证层级**：',
    '- **执行所有者**：',
    '- **独立复核**：',
    '- **人工门**：',
    '- **允许修改范围**：',
    '### 目标',
    '### 实施步骤',
    '### 完成定义',
    '### 测试命令',
    '### 失败回滚',
    '### 证据产物',
    '### 禁止事项'
)
foreach ($task in $tasks) {
    $id = $task.Groups[1].Value
    foreach ($marker in $requiredMarkers) {
        if (-not $task.Value.Contains($marker)) {
            throw "TASK_SECTION_MISSING:${id}:${marker}"
        }
    }
    foreach ($field in @('状态', '优先级', '依赖', '验证层级', '执行所有者', '独立复核', '人工门', '允许修改范围')) {
        if ($task.Value -notmatch "(?m)^- \*\*$([regex]::Escape($field))\*\*：\S.*$") {
            throw "TASK_FIELD_EMPTY:${id}:${field}"
        }
    }
}

$allowedStatuses = @('Pending', 'In Progress', 'Partial', 'Skipped', 'Blocked', 'Failed', 'Completed')
$statusPattern = '(?m)^- \*\*状态\*\*：(.+)$'
$statuses = @([regex]::Matches($content, $statusPattern) | ForEach-Object { $_.Groups[1].Value.Trim() })
if ($statuses.Count -ne 13) {
    throw "TASK_STATUS_COUNT_INVALID:$($statuses.Count)"
}
$invalidStatuses = @($statuses | Where-Object { $_ -notin $allowedStatuses })
if ($invalidStatuses.Count -gt 0) {
    throw "TASK_STATUS_INVALID:$($invalidStatuses -join ',')"
}
if (@($statuses | Where-Object { $_ -eq 'In Progress' }).Count -gt 1) {
    throw 'IN_PROGRESS_TASK_COUNT_INVALID'
}

$placeholderPattern = '(?im)\bTO' + 'DO\b|\bTB' + 'D\b|待' + '定'
if ($content -match $placeholderPattern) {
    throw 'PLACEHOLDER_MARKER_FOUND'
}
if ($content -match '(?m)[ \t]+(?=\r?$)') {
    throw 'TRAILING_WHITESPACE_FOUND'
}
if ($content -match '(?m)^#{1,6}\s*$') {
    throw 'EMPTY_HEADING_FOUND'
}
$emptySections = [regex]::Matches($content, '(?ms)^#{2,3} [^\r\n]+\r?\n(?:[ \t]*\r?\n)*(?=#{2,4} |---|\z)')
if ($emptySections.Count -gt 0) {
    throw "EMPTY_SECTION_FOUND:$($emptySections[0].Value.Trim())"
}

git diff --check -- 修改task.md
if ($LASTEXITCODE -ne 0) {
    throw 'GIT_DIFF_CHECK_FAILED'
}

"PATH=$path"
"TASK_COUNT=$($tasks.Count)"
"TASK_IDS=$($actualIds -join ',')"
"TASK_STATUSES=$($statuses -join ',')"
"STRUCTURE_CHECK=PASS"
git -c core.quotepath=false status --short
```

期望结果：文件路径正确、任务数为 13、状态合法且至多一个 `In Progress`、没有缺失任务、没有尾随空格、没有空标题。PowerShell 正则是未跟踪文件的空白权威检查；`git diff --check -- 修改task.md` 仍按请求运行，但未跟踪文件不会被该 Git 命令单独检查。最后的 `git status --short` 必须与编辑前仓库外快照逐项比较；已有用户改动保持不变，本轮只允许新增或修改 `修改task.md`。没有编辑前快照时只能报告无法证明，不能回退未知改动。
