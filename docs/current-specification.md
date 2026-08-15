# 当前生效规格

发布日期：2026-08-14

状态：本地个人 LLM Wiki 与记忆图谱 MVP 的唯一产品/工程规格入口。

版本边界：桌面端和后端仍标记为 `0.0.1-alpha` / `0.0.1a0`。本文只描述当前
代码、迁移、测试和已保存验证产物能证明的行为。`修改task.md` 是执行计划，
不是运行时事实来源；历史任务号、旧截图和 ignored 数据库不能替代当前证据。

## 1. 产品定义

### 1.1 要解决的问题

个人项目的上下文分散在会话、Markdown 和临时记忆里，导致新会话重复解释、
错误记忆无法追溯、纠正不能传播、资料页不能稳定复用。产品目标是让一个本地
用户完成：

```text
输入/导入 -> 候选与证据 -> 用户确认 -> 实体/事实/关系 -> Wiki 综合
       -> 新会话一至二跳召回 -> 引用 -> 纠正/忘记 -> 权限撤销
```

### 1.2 用户与非目标

- 目标用户：在 Windows 上管理个人项目、偏好、边界、决策和本地资料的知识工作者。
- 内部试点：一名员工使用隔离的 SQLite/Vault，按固定任务记录 7 天匿名聚合；不描述团队协作。
- 非目标：企业租户、RBAC、多人知识库、云端同步、跨平台承诺、关机/睡眠期间在线、普遍业务 uplift。

### 1.3 产品价值判断

普通聊天可以走单模型流式快路径，所以“聊天回复”本身不是差异化证据。差异化
来自可追溯的记忆/Wiki 生命周期：来源不可变、候选可审查、事实有权限、关系有
证据、纠正会 supersede、忘记会退出召回；当前已由 focused gate 覆盖的任务与
post-reply memory/Wiki 副作用还有 claim/receipt 和恢复状态。
如果只演示聊天，本项目的表现接近 API 直连；演示必须同时展示一次记忆纠正、
一次无证据拒答和一次失败恢复。

## 2. AI 与确定性代码的分工

### 2.1 AI 允许做什么

模型用于自然语言抽取、实体消歧建议、查询规划和基于已接受 evidence 的综合。
LangChain 负责模型/工具适配；LangGraph 负责有状态路由和有界流式事件。
启用协作时，Orchestrator 每轮最多顺序调用一个只读 Retrieval Agent，再由
Synthesizer 生成唯一自然语言出口。普通聊天不强制进入该路径。

### 2.2 AI 不得决定什么

确定性组件负责认证、敏感策略、权限、状态迁移、实体唯一性、受控关系、写入、
幂等、回滚、引用校验、删除、Kuzu 降级和指标分子/分母。模型输出只能是候选或
结构化提案；非法输出、过期事实、冲突事实和无召回权限内容不得进入 prompt。

## 3. 数据权威与生命周期

### 3.1 权威归属

| 数据 | 唯一权威 | 说明 |
| --- | --- | --- |
| 实体、别名、事实、关系、evidence、生命周期、召回权限 | SQLite | 可事务更新，可按 idempotency key 恢复 |
| 原始来源字节和 SHA-256 | Markdown/source 表 | 来源不可被摘要覆盖；新 hash 先进入复核 |
| 用户可读 Wiki 正文 | Markdown Vault | 保留 frontmatter、revision、source、lint 状态 |
| FTS5、Qdrant、Kuzu | 派生投影 | 可删除重建，不得反向写权威状态 |
| claim、receipt、verification 和指标事件 | SQLite | 不保存原始秘密；receipt 通过权威 reader 验证 |

### 3.2 实体和关系本体

实体限定为：`self`、`person`、`project`、`preference`、`boundary`、`goal`、
`event`、`concept`、`source`、`wiki_page`、`decision`。

关系限定为：`prefers`、`avoids`、`works_on`、`knows`、`related_to`、
`occurred_in`、`supports`、`contradicts`、`supersedes`、`derived_from`、
`documented_in`。自动关系必须带 evidence、confidence、lifecycle 和召回权限；
共享关键词不能生成 `related_to`。

### 3.3 LLM Wiki 页面类型

Wiki 页面按 `source`、`entity`、`concept`、`synthesis`、`comparison`、
`decision`、`report` 生成。每页 frontmatter 必须包含 `wiki_id`、`page_type`、
`entity_ids`、`fact_ids`、`revision`、`confidence`、`disputed`、`sources`、
`updated_at`；没有来源的页不能标为已验证。可选段落内容缺失时省略，不写空
占位符。唯一规则来源是 `apps/backend/app/resources/wiki/AGENTS.md`。

### 3.4 记忆闭环

1. 从对话或来源创建候选和 evidence；普通模型抽取默认不激活。
2. 明确的低风险“请记住”声明可按策略进入 active；敏感、关系、冲突或低置信内容留在 candidate/quarantined。
3. 新会话召回前按状态、过期时间、敏感级别、Vault 范围和 recall permission 过滤。
4. 用户纠正创建新 claim 和 `supersedes` 关系，旧 claim 失效；用户忘记会撤销事实、实体和派生 artifact 的召回权限。
5. 通过固定回归证明“记住 -> 新会话召回 -> 纠正 -> 旧事实不再召回”；缺少真实试用数据时不能推导效率提升。

## 4. 副作用生命周期

实际 API 使用的 `agent_runtime(request)` 创建一个 `ActionLifecycleCoordinator`，并将其
提供给 task、memory、continuity、Wiki、reminder 和 metrics adapters/readers，关闭
`allow_ephemeral_lifecycle`。当前 focused gate 和隔离 L3 action journey 证明
primary task、checkpoint 与 post-reply memory/Wiki 写入遵守以下生命周期；
这不是“所有领域写入都已统一”的证明：

```text
claim -> effect -> authoritative read-back -> receipt -> verification
```

重复请求先查稳定 `idempotency_key`，已有 verified receipt 直接返回；只有 claim
时先读取目标，唯一匹配才重建 receipt；零匹配、多匹配或 hash 不确定进入
`failed_recovery`/`manual_review`，不得盲目重放。高风险 checkpoint 保存原始
proposal、policy、canonical payload hash 和批准决定；批准后重新校验同一 proposal，
拒绝零副作用，不把确认改写成新目标。

证据入口：`apps/backend/tests/test_action_lifecycle_wiring.py`、
`test_production_checkpoint_resume.py`、`test_production_action_recovery.py` 和
`output/verification/LLMWIKI-002/action-journey-report.json`。当前 action journey
为 `5 Passed / 0 Failed / 0 Partial`，包含拒绝零副作用、批准执行原目标、重启回放
同一 receipt，以及 effect 后 receipt 前真实子进程退出后的权威读回。
memory feedback、profile actions、hygiene actions、retrospective reports 和
continuity proposal creation 仍存在 direct mutation 路径，必须在后续门中单独收敛。

## 5. 检索与图谱

- FTS5 是默认检索和故障 fallback；它解决“本机无额外服务也能按词找回来源”的问题。
- 图摘要 API 提供节点、claim、edge、evidence、lifecycle、allowed actions 和
  projection degradation；前端的证据链轨道按实体 -> 关系 -> 原始来源 -> Wiki 页 -> 生命周期展示。
- 图遍历最多一至二跳，按 prompt 字符/条目预算裁剪；敏感、冲突、候选和过期关系不进入回答上下文。
- Kuzu 从 SQLite 一致快照重建为只读代次；代次不一致、缺失或损坏时自动返回 SQLite，并公开 `source` 与 `fallback_reason`。
- Qdrant 仅是可选向量候选实验。当前合成评测没有证明向量或混合检索优于 FTS，不把它写成默认能力，也不把 RAG 改名为“没有检索”。

产品主叙事使用“本地个人 LLM Wiki 与记忆图谱”。Wiki 指完整的来源、实体、事实、
综合和决策生命周期，不是把 RAG 术语改名；所有回答仍然经过有界检索和 evidence 过滤。

## 6. 桌面与常驻边界

Electron main/preload 负责托盘、自启、sidecar 生命周期、通知和 bearer 注入；
Renderer 不接触 Node、FS、token 或原始 checkpoint。resident runtime 可以在登录后
启动、有限重启并追赶持久任务，但睡眠/关机期间不在线。通知状态区分
`triggered`、`display_attempted` 和 `display_unknown`；权限拒绝只保留任务并提供
手工重试。

BrowserWindow 必须保持 `contextIsolation: true`、`sandbox: true`、
`webSecurity: true`、`nodeIntegration: false`。Renderer 只能通过 preload
`contextBridge` 调用 allowlist 能力，不得使用 `localStorage` 绕过 main/preload
的令牌和数据目录管理。后端只监听 loopback，普通错误不返回绝对路径、SQL、
prompt、token 或内部数据库主键。

本地隐私模式只覆盖当前敏感内容策略命中的消息：命中后走本地 FTS/关键词查询，
跳过模型调用和模型驱动的后台记忆工作。它不是操作系统级断网，也不能保证未被
检测器命中的普通消息不会访问已配置 provider；界面必须把这条边界写清楚。

## 6.1 稳定 API 契约

图谱 API 的公开读面是图摘要、节点详情、claim/edge 详情、evidence/lifecycle
详情和 degradation 状态；写面是节点/claim/edge 的 confirm、correct、forget、
archive 等受控操作，均要求认证、64 位幂等键、payload hash 和可重放响应。派生
图重建是诊断动作，失败返回 fallback 原因而不是伪装健康。指标 API 只返回本地
匿名聚合的 numerator、denominator、sample size、window 和 evidence status。
OpenAPI、Renderer 类型和 Electron proxy allowlist 必须由同一生成链更新。

## 7. 失败契约

| 场景 | 必须保持的事实 | 面向用户的动作 |
| --- | --- | --- |
| 模型离线、超时、限流、额度耗尽 | 稳定 error code；不写候选/receipt；本地浏览可用 | 重试只读请求或打开 Wiki/FTS |
| 无 evidence | 空证据响应；不生成确定性答案 | 提供来源或手工记录 |
| 非法结构化输出 | 丢弃候选，保留原来源 | 重试抽取 |
| 关系冲突/身份歧义 | 并排隔离，不进入 prompt | 选择实体或纠正关系 |
| Markdown hash 冲突 | 停写，保留 snapshot/claim | 查看差异、重试或放弃 |
| effect 后 receipt 前崩溃 | reader 先查；唯一匹配重建原 receipt | 等恢复或人工复核，不重放 |
| Kuzu 损坏/代次落后 | SQLite 仍是 authority，显示 degraded | 继续查询，安排 rebuild |
| sidecar 崩溃 | 有界退避，超过上限停止自动重启 | 手动重试并查看日志 |
| 通知权限拒绝/未知 | reminder 不丢，送达不冒充成功 | 查看任务并手工重试 |
| 敏感输入/提示注入来源 | 阻止远程泄露和图写入 | 脱敏、本地处理或放弃 |

最新组合故障矩阵为 `15 Passed / 0 Failed / 3 Partial`：4 项通过来自真实隔离 sidecar/API，另外 11 项来自确定性后端故障 harness。3 个 Partial 是打包 Electron sidecar 崩溃路径、真实 Windows 睡眠恢复和 Windows 通知权限拒绝。runner 因仍有 Partial 返回退出码 `2`；Partial 不是成功证据，后端 harness 通过也不能外推为打包 Electron 或 Windows 人工验证通过。

## 8. 验证、指标和发布门

当前可引用的产物：

- `output/verification/LLMWIKI-011/eval-20260814/report.json`：生产 FTS evaluator 在 60 个合成案例上得到 Recall@5 宏平均 `24.8/50 = 0.496`（`Failed`）；no-evidence accuracy 为 `10/10 = 1.00`、false activation 为 `0/10 = 0`，两项均 `Passed`。该 evaluator 只检索候选、不生成或评审答案，所以 citation coverage 为 `0/0`、`insufficient_sample`。独立图谱夹具中，SQLite 图遍历、Kuzu 图遍历和缺失投影时的 SQLite fallback 均为 `21/21 Passed`；确定性图基线为 `37/37`，模型调用和外部请求均为 `0`。这些只是 L2 合成证据，不能证明 Kuzu 改善语义检索、生产稳定性或业务结果。correction propagation 为 `3/3`，但最低样本要求是 `20`，仍为 `insufficient_sample`；LLM extraction/synthesis 为 `not_run`。组合 evaluator 退出码 `1`，仍是失败基线，不是发布通过证据。
- `output/verification/LLMWIKI-013/migration/migration-report.json`：空库、旧库和重复迁移 smoke；旧库的 `memory_graph_facts` 与 `memory_candidates` 均由 `1` 保留为 `1`，外键错误为 `0`，重复执行新增迁移版本数为 `0`。
- `output/verification/LLMWIKI-002/action-journey-report.json`、`LLMWIKI-004/journey-report.json` 和 `LLMWIKI-006/journey/wiki-journey-report.json`：分别证明真实隔离 sidecar/API 下的动作恢复、跨重启记忆召回/纠正/忘记，以及 source-to-decision Wiki 生命周期。抽取使用版本化确定性 fixture，只证明生命周期接线，不证明 live-model 质量。
- `output/verification/LLMWIKI-013/quality/backend-full-20260814-sharded.json`：当前 checkout 的四个不重叠 shard 共收集 `1195` 个后端测试，得到 `1193 passed, 2 skipped, 0 failed`；Mypy 通过 213 个源文件，Ruff 通过。桌面 Vitest 为 `61 files / 481 passed`，typecheck、OpenAPI 契约检查和 Vite build 通过。该结果不等于打包 Electron、Windows 人工门、24 小时、7 天、业务 KPI 或 Kuzu 生产负载已经证明；memory feedback/profile/hygiene/retrospective/continuity 的 direct mutation 边界仍需单独收口。
- `output/verification/LLMWIKI-013/visual/visual-report.json`：开发态 Vite + Chrome 下，`390x844`、`1280x720`、`1366x768`、`1920x1080` 的图谱/时间线/来源共 12 个状态自动截图、水平溢出、焦点、对比度和 reduced-motion 检查通过（exit code `0`）；打包 Electron、Windows 100/125/150% DPI 和失败/冲突态人工审阅仍为 `Partial`。
- `output/verification/packaged-app-smoke.json`：本机打包 smoke，不是干净 VM 或物理 DPI 证据。

冻结审计基线是 `57/100`。最近一次完成独立评分的快照仍是 2026-08-11 的 raw/reported `62/100`：问题/用户 `8`、流程/AI `7`、Agent `9`、LLM Wiki/图谱 `10`、稳定性 `9`、指标 `5`、前端 `7`、文档 `7`。2026-08-14 新增的三条 L3 旅程和全量自动化证据尚未完成独立整档复评分，因此不能仅按测试数量提高分数。全副作用生命周期、3 个 OS 故障、物理 DPI、真实 24 小时 soak 和至少 7 天试用仍为 Partial；reported score 上限仍为 `84`。没有真实用户分母时，只报告 baseline、sample size 和 evidence status，不报告业务百分比。上一次评分证据见 `output/verification/LLMWIKI-013/final-score-20260811.md`。

## 9. 当前明确限制

- 本地单用户；没有团队、企业租户、RBAC、云端同步或跨平台承诺。
- 普通聊天直连快路径仍存在，模型输出质量受 provider 影响。
- 没有 live-provider quality campaign、真实 24 小时 soak、7 天纵向数据、干净 Windows VM、物理 DPI 矩阵或完整视觉人工验收。
- Kuzu/Qdrant 是否带来业务增量尚未证明；不因技术栈数量加分。
- 任何对外简历或演示必须以 `docs/portfolio/claim-evidence-index.md` 为索引，并先运行声明扫描器。
