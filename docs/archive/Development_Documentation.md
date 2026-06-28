# 已归档，不再维护

归档日期：2026-06-20

当前生效规格见 `docs/current-specification.md`。本文件仅保留历史方案和旧验收条目；
不得再作为当前产品、架构、数据模型或验收状态的权威依据。

---

# 当前实现快照（2026-05-11）

本节只补充当前实现方向，不重写下方旧规格。下方历史规格保留原样；若与当前代码、自动化验证或进度日志冲突，以当前实现核对结果为准。

- 事实源：`apps/backend`、`apps/desktop` 当前代码和迁移/测试脚本是运行时事实源；`progress.md` 是 coordinator 进度事实源，但使用前要再核对代码和验证输出。
- 桌面端主流程：用户先通过 Agent chat 发起检索、整理和写入计划；长期记忆或 Vault 页面写入必须走可审查、可确认的 proposal/plan 流程。
- Wiki 命名：现有 `Wiki` API、类型和部分内部字段是内部/历史命名；面向用户的产品语义应表述为 Vault 维护、长期记忆维护或查询归档。
- 当前已实现：Agent Wiki/Obsidian 请求会走 `plan_wiki_ingest`，产出 `wiki_proposal` 预览/审查事件；该路径不直接写入 Markdown。`apply_ingest` 在写文件前要求用户已确认审查、提供匹配的 `review_id`，并显式批准本次 run 内的目标文件。
- 当前 UI 状态：桌面端会展示 `Vault 维护提案`；原手工 Wiki/Vault 面板已降级为默认折叠的“高级 Vault 维护”，保留预览、审查、应用、归档、综合整理和检查按钮供手工维护使用。
- 当前缺口：聊天里已经能看到 proposal，但从 proposal 卡片直接确认并应用写入的完整 UX 还需要继续实现；查询归档、综合整理和 lint 也还没有完全统一到 Agent proposal/confirmation 模式。

---

# Agent 桌宠与 Obsidian 记忆 Wiki 项目开发设计文档

| 文档项 | 内容 |
| --- | --- |
| 项目名称 | Agent 桌宠与 Obsidian 记忆 Wiki |
| 文档类型 | 工程开发规格文档 |
| 文档版本 | v1.3 |
| 目标平台 | Windows MVP|
| 编写日期 | 2026-04-26 |
| 修订目标 | 将宏观方案收敛为可拆解、可实现、可验收的工程规格 |

---

## 0. 文档目标

本文档用于指导桌面端 Agent 桌宠项目从需求拆解、架构设计、接口约定、数据建模、安全约束、测试验收到版本交付的全过程。

本项目不是简单聊天机器人，而是一个本地优先的桌面 Agent 应用。它通过 Obsidian Vault 保存透明、可编辑、可审计的长期记忆，通过本地 Python sidecar 提供 Agent、检索、任务和提醒能力，通过 Electron + React 提供桌面窗口、聊天面板、设置面板和桌宠体验。

本文档的关键原则：

- MVP 必须先形成闭环：启动应用、配置模型、绑定 Vault、聊天、检索记忆、确认写入记忆、创建提醒。
- 技术架构必须可演进：MVP 可以先使用内部 service，Beta 再抽象 MCP 工具层，正式版再完善插件化。
- 所有 P0 功能必须具备触发条件、输入输出、失败行为、权限要求和验收标准。
- 所有写入用户文件的行为必须可预览、可确认、可追踪、可拒绝。

### 0.1 严格评审修订记录

本节记录严格评审中的工程级修订点，避免后续实现团队误读。

| 问题位置 | 问题 | 修订结论 |
| --- | --- | --- |
| 5.5 任务和提醒 | F-402 写到 `unscheduled`，但 reminders 表状态枚举没有该值 | 将 reminders.status 明确定义为 `scheduled / unscheduled / triggered / cancelled / failed` |
| 14.3 Chat API | 文档要求 SSE 带 Authorization，但原生 EventSource 不能设置自定义 header | 规定 MVP 使用 fetch streaming 消费 SSE 格式；如使用 EventSource，必须改用一次性 stream token |
| 11.2 messages | assistant 流式消息在生成前可能没有完整 content，原表缺少消息状态 | 增加 messages.status 和 updated_at，允许流式生成期间记录 partial 状态 |
| 13.3 增量索引 | 原文没有明确 FTS5 更新删除必须与 chunks 同事务 | 补充索引替换事务，避免 note_chunks 与 note_fts 不一致 |
| 17.4 写入安全 | “原子写入”没有说明 Windows 文件占用、换行和备份问题 | 补充同卷临时文件、备份、换行保持、文件占用失败处理 |
| 17.1 路径安全 | 仅写 canonical path，不足以覆盖 Windows 大小写、短路径、UNC 和符号链接细节 | 补充 Windows 路径归一化和 reparse point 校验要求 |
| 1.1 / 9 技术范围 | MVP 写入 embedding model，但语义检索和 LanceDB 又定义为 Beta | MVP 只要求 Chat Model；Embedding Model 移到 Beta |
| 11.2 memory_proposals | 约束要求校验目标文件 hash，但表结构没有保存 hash | 增加 `target_content_hash` 和 `source_message_id` |
| 14.2 Health API | 无鉴权 health 返回 active_vault_id，暴露不必要状态 | health 仅返回服务健康；Vault 状态通过鉴权接口读取 |
| 17.2 API 安全 | session token 允许通过启动参数注入，Windows 进程列表可能泄露 | 禁止通过命令行参数传递 token，改用环境变量或 stdin |

## 1. 版本范围

### 1.1 MVP 必选范围

MVP 目标是验证本地优先 Agent 桌宠的核心闭环，不追求完整插件市场、复杂 Live2D 表现或云同步。v0.1 可以提供桌宠模型展示区和基础动作壳，用于验证客户端可见性与状态联动；真实 Live2D Cubism SDK、正式授权模型资源、物理效果、口型同步和复杂动作编排属于 Beta/后续增强。

MVP 必选技术：

- Electron + React + TypeScript + Vite。
- Python FastAPI sidecar。
- SQLite + SQLite FTS5。
- Obsidian Vault Markdown 文件读写。
- LangChain ChatModel 集成，OpenAI-compatible provider 作为首个模型配置。
- LangGraph 用于核心 Agent 状态流和多 Agent 编排。
- APScheduler 用于本地提醒。

MVP 必选能力：

- Windows 桌面应用可启动、退出、托盘驻留。
- 本地 FastAPI sidecar 可由 Electron main process 启动和关闭。
- 用户可配置模型 API Key。
- 用户可创建或绑定一个授权 Obsidian Memory Vault。
- 系统可扫描 Markdown、建立 FTS5 索引、返回来源引用。
- 用户可聊天，Agent 可基于 Vault 片段回答。
- Agent 可生成候选长期记忆，用户确认后写入指定 Markdown。
- 用户可创建一次性提醒，到期触发系统通知。
- 关键操作写入结构化日志。

### 1.2 Beta 增强范围

Beta 目标是提升体验和扩展性。

- Live2D Cubism SDK for Web 接入，支持待机、思考、说话、提醒等基础状态。
- LanceDB 向量检索接入，形成 FTS5 + semantic hybrid retrieval。
- MCP 工具层抽象，优先覆盖 memory、search、task、pet 四类工具。
- 文件监听增量索引。
- 每日总结和复习提醒。
- 日志导出、错误诊断面板。

### 1.3 正式版与后续扩展

正式版及后续版本可以扩展：

- 自动更新。
- 多角色 Live2D 资源管理。
- 本地模型模式，支持 Ollama 和本地 embedding。
- 语音输入、语音输出和口型同步。
- 插件市场。
- 云同步、账号体系、多设备同步和端到端加密。

## 2. 项目背景与定位

### 2.1 背景问题

当前个人 AI 助手常见问题：

- 记忆不可见，用户无法确认 AI 记住了什么。
- 跨会话上下文弱，长期体验不连续。
- 纯聊天形态缺少陪伴感和主动提醒能力。
- 本地知识、个人偏好、任务提醒与 AI 对话割裂。
- 用户数据隐私和文件访问边界不透明。
- Agent 工具能力分散，难以扩展和审计。

### 2.2 产品定位

本项目定位为：

> 一个以 Obsidian 为长期记忆 Wiki 的本地优先桌面 Agent 桌宠。它能够陪伴用户、理解偏好、检索记忆、管理提醒，并在用户确认后维护长期记忆。

核心差异化：

- 长期记忆不保存在黑盒数据库中，而是写入用户可查看、可编辑的 Obsidian Markdown Vault。
- Agent 不直接改写用户文件，所有长期记忆写入必须先进入预览和确认流程。
- 桌宠不是单轮聊天窗口，而是具备状态、任务提醒和长期记忆的桌面伴随应用。
- 工具能力先以内部 service 落地，再通过 MCP 标准化，降低首版复杂度。

## 3. 目标用户

### 3.1 核心用户

- 使用 Obsidian 进行个人知识管理的用户。
- 希望 AI 拥有长期记忆，但要求隐私、透明和可控的用户。
- 需要桌面陪伴、任务提醒、学习监督和知识整理的用户。
- 对 AI Agent、个人 Wiki、桌面效率工具感兴趣的开发者、学生和知识工作者。

### 3.2 非目标用户

MVP 不面向以下场景：

- 企业多人协作知识库。
- 移动端优先用户。
- 医疗、法律、金融等高风险专业建议场景。
- 需要云端多设备实时同步的用户。

## 4. 业务目标

### 4.1 MVP 产品目标

- 用户在 Windows 上安装后可以启动桌宠应用。
- 用户可以绑定或创建 Obsidian Memory Vault。
- 用户可以进行自然语言聊天。
- Agent 可以基于 Vault 中的 Markdown 内容回答，并展示引用来源。
- Agent 可以提出候选长期记忆，用户确认后写入 Vault。
- 用户可以创建提醒，到期收到系统通知。

### 4.2 MVP 技术目标

- Electron main process 负责桌面生命周期、托盘、窗口、通知和 sidecar 管理。
- React 前端负责聊天、设置、记忆确认、任务面板。
- Python FastAPI sidecar 负责 Agent、检索、任务、调度和本地 API。
- SQLite 保存应用状态、任务、会话、索引元数据和审计日志。
- FTS5 支持关键词检索和来源引用。
- LangGraph 负责核心 Agent 流程。
- 所有 API 调用必须携带启动时生成的 session token。

### 4.3 成功指标

- 首次启动后 10 分钟内，用户可以完成 Vault 初始化和第一轮聊天。
- 1000 篇 Markdown 文件内，FTS5 检索 P95 小于 300 ms。
- 普通聊天请求首个流式事件 P95 小于 3 秒，不含模型供应商排队时间。
- 未授权路径访问、路径穿越、缺失 token、敏感信息自动记忆必须被拒绝。
- 用户确认写入长期记忆后，Markdown 文件、SQLite 元数据和检索索引保持一致。

## 5. 功能需求

优先级定义：

- P0：MVP 必须实现，否则核心闭环不成立。
- P1：Beta 增强，提升体验或完整度。
- P2：正式版或后续扩展。

### 5.1 桌面与应用生命周期

| 编号 | 功能 | 优先级 | 触发条件 | 输入输出 | 失败行为 | 权限要求 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-001 | 应用启动 | P0 | 用户打开应用 | 输出主窗口和 sidecar 健康状态 | sidecar 启动失败时展示错误和重试按钮 | 无 | Windows 上双击应用后 10 秒内显示可操作 UI |
| F-002 | Python sidecar 管理 | P0 | Electron 应用启动或退出 | 输入 sidecar 路径，输出进程状态 | 启动失败写入日志并阻止聊天功能 | 本机进程权限 | 应用退出时 sidecar 被正常关闭 |
| F-003 | 托盘菜单 | P0 | 用户右键托盘图标 | 输出打开主面板、设置、退出菜单 | 菜单失败时保留主窗口关闭能力 | 系统托盘权限 | 托盘可打开窗口并退出应用 |
| F-004 | 设置页 | P0 | 用户打开设置 | 输入模型配置、Vault 配置 | 保存失败展示字段级错误 | 本地配置读写 | 配置保存后重启仍有效 |
| F-005 | 透明悬浮桌宠窗口 | P1 | 用户启用桌宠模式 | 输出可拖拽、置顶窗口 | 不支持透明时回退普通窗口 | 窗口管理权限 | 桌宠窗口可移动并保持位置 |
| F-006 | Live2D 状态 | P1 | Agent 状态变化 | 输入 emotion，输出动作/表情 | 模型加载失败时回退静态形象 | Live2D 授权资源 | 支持 idle/thinking/speaking/reminding |
| F-007 | 开机启动 | P2 | 用户启用开机自启 | 输出系统启动项 | 设置失败提示原因 | 系统启动项权限 | 重启系统后应用自动启动 |

v0.1 验收 F-005/F-006 时要求主界面中的桌宠展示区可见，并能随健康检查、聊天、搜索、记忆提案、任务和诊断等状态提供基础反馈。当前已推进到单模型 Cubism idle 渲染路径：只覆盖一个已导入模型的 manifest、SDK 文件、canvas 宿主和 idle 渲染，不代表口型同步、复杂动作编排或多角色资源管理已经实现。

当前 Live2D 资源识别与渲染入口使用 `apps\desktop\public\live2d\UG\ugofficial.model3.json`，前端 URL 为 `/live2d/UG/ugofficial.model3.json`。官方 Cubism SDK 已导入到 `apps\desktop\public\live2d\CubismSdkForWeb-5-r.5`，并通过 `npm run live2d:sdk:check` 校验 `Core`、`Framework` WebGL renderer、官方 TypeScript 示例入口和许可证文件。当前 runtime 路径通过 React/Electron canvas 挂载单个 `UG` 模型，加载 model3、moc3、贴图、物理配置和首个 idle motion，并提供静态封面回退。物理效果、口型同步、复杂动作映射和多角色切换仍归入后续增强。

### 5.2 对话与 Agent

| 编号 | 功能 | 优先级 | 触发条件 | 输入输出 | 失败行为 | 权限要求 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-101 | 创建会话 | P0 | 用户首次发送消息 | 输入 message，输出 conversation_id | 数据库失败时返回 500 和错误码 | session token | 会话和首条消息写入 SQLite |
| F-102 | 流式聊天 | P0 | 用户发送消息 | 输入 conversation_id/message，输出 SSE 事件 | 模型失败时输出 error 事件并落库 | session token、模型 Key | 前端可以逐字或分块展示回复 |
| F-103 | 意图识别 | P0 | Chat API 收到消息 | 输出 chat/search_memory/create_task/propose_memory | 低置信度时进入普通聊天 | 无额外权限 | 典型查询、记忆、提醒指令可正确路由 |
| F-104 | 记忆检索问答 | P0 | 意图为 search_memory 或聊天需要上下文 | 输出 answer + citations | 检索失败时回复降级说明 | 授权 Vault | 回答展示至少文件路径和片段 |
| F-105 | 候选记忆提取 | P0 | 用户显式说“记住”或 Agent 判定高价值信息 | 输出 memory proposal | 敏感或不确定信息进入拒绝或 pending | 用户确认写入 | 未确认前不得写入正式记忆 |
| F-106 | 对话摘要 | P1 | 会话超过阈值或关闭会话 | 输出 summary | 摘要失败不影响聊天 | session token | 长会话可生成短摘要 |
| F-107 | 取消生成 | P1 | 用户点击停止 | 输出 cancel_ack | 模型不支持取消时停止前端消费 | session token | 取消后不会继续向 UI 追加正文 |

### 5.3 Obsidian 记忆 Wiki

| 编号 | 功能 | 优先级 | 触发条件 | 输入输出 | 失败行为 | 权限要求 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-201 | Vault 初始化 | P0 | 用户选择创建或绑定 Vault | 输入本地路径，输出 vault_id | 路径非法或不可写时拒绝 | 用户显式选择路径 | 生成默认目录和模板文件 |
| F-202 | Vault 授权边界 | P0 | 任意文件读写前 | 输入 path，输出 allow/deny | 非授权路径直接拒绝并审计 | canonical path 校验 | `../` 和符号链接越界被拒绝 |
| F-203 | Markdown 读取 | P0 | 检索或记忆面板请求 | 输出 Markdown 正文和元数据 | 文件不存在返回 404 | 授权 Vault | 只能读取授权 Vault 内 `.md` 文件 |
| F-204 | 记忆预览 | P0 | Agent 生成候选记忆 | 输出 preview_markdown、target_path、diff | 目标文件冲突时要求用户选择 | 用户确认 | 前端展示内容、目标文件和来源 |
| F-205 | 确认写入 | P0 | 用户点击确认 | 输入 proposal_id，输出写入结果 | 写入失败回滚 proposal 状态 | 授权 Vault 写权限 | 文件写入后索引更新并记录日志 |
| F-206 | 拒绝记忆 | P0 | 用户点击拒绝 | 输入 proposal_id/reason | 数据库失败返回错误 | session token | 被拒绝 proposal 不再自动写入 |
| F-207 | Pending Memories | P0 | 候选需延后确认 | 输出 Inbox/Pending Memories.md 条目 | 写入失败保留 SQLite pending | 授权 Vault 写权限 | 未确认记忆可在面板中继续处理 |
| F-208 | 记忆整理 | P1 | 用户触发整理 | 输出去重建议和冲突提示 | 不自动改写文件 | 用户二次确认 | 所有改写必须展示 diff |
| F-209 | 每日总结 | P1 | 每日定时或用户触发 | 输出 Daily Summary Markdown | 模型失败记录日志 | 授权 Vault 写权限 | 总结文件可被检索 |

### 5.4 检索与索引

| 编号 | 功能 | 优先级 | 触发条件 | 输入输出 | 失败行为 | 权限要求 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-301 | 初始扫描 | P0 | Vault 初始化或用户重建索引 | 输入 vault_id，输出 index_job_id | 单文件失败不终止全量任务 | 授权 Vault 读权限 | Markdown 文件被写入 notes/note_chunks |
| F-302 | Markdown 解析 | P0 | 扫描文件 | 输出标题、标签、frontmatter、双链、chunks | 解析失败降级为纯文本 | 无额外权限 | 标题、标签、正文 chunk 可检索 |
| F-303 | FTS5 索引 | P0 | chunk 生成或更新 | 输出 FTS rows | 写入失败标记 index_job failed | SQLite 写权限 | 关键词搜索能返回匹配片段 |
| F-304 | 来源引用 | P0 | 检索回答 | 输出 path、heading、snippet、score | 无来源时明确说明 | 无额外权限 | 回答显示引用文件和片段 |
| F-305 | 增量索引 | P1 | 文件变更监听事件 | 输出更新结果 | 监听失败时提示手动重建 | 文件监听权限 | 修改文件后索引自动刷新 |
| F-306 | LanceDB 向量索引 | P1 | 启用 semantic search | 输出 embedding rows | embedding 失败不影响 FTS | 模型 Key | 语义搜索可召回同义内容 |
| F-307 | 混合检索 | P1 | mode=hybrid | 输出合并排序结果 | LanceDB 不可用时回退 FTS | 模型 Key 可选 | 返回去重后的 top_k |

### 5.5 任务和提醒

| 编号 | 功能 | 优先级 | 触发条件 | 输入输出 | 失败行为 | 权限要求 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-401 | 创建任务 | P0 | 用户自然语言创建待办 | 输入 title/due_at，输出 task_id | 时间不明确时要求确认 | session token | 任务写入 SQLite |
| F-402 | 创建提醒 | P0 | 任务带 due_at/remind_at | 输出 reminder_id | 调度失败标记为 unscheduled 并允许重试 | 系统通知权限 | 到期触发通知；调度失败时任务不丢失 |
| F-403 | 今日任务 | P0 | 用户打开任务面板 | 输出今日任务列表 | 查询失败显示错误 | session token | 可看到 pending/done 状态 |
| F-404 | 完成任务 | P1 | 用户标记完成 | 输出 done 状态 | 更新失败回滚 UI | session token | 完成时间写入 SQLite |
| F-405 | 习惯追踪 | P2 | 用户创建习惯 | 输出 habit log | 调度失败提示 | session token | 支持每日打卡 |

### 5.6 设置与安全

| 编号 | 功能 | 优先级 | 触发条件 | 输入输出 | 失败行为 | 权限要求 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-501 | API Key 配置 | P0 | 用户保存模型配置 | 输入 key，输出 masked value | 验证失败不保存 | 系统凭据存储 | UI 只显示掩码 |
| F-502 | 聊天模型选择 | P0 | 用户选择模型 | 输出 chat_model | 不支持模型提示原因 | session token | 配置被后端读取 |
| F-503 | 权限控制 | P0 | 任意文件工具调用 | 输出 allow/deny | deny 记录 audit log | Vault 授权 | 越权访问不可执行 |
| F-504 | Diff 审核 | P0 | 修改已有 Markdown | 输出 unified diff | 无法生成 diff 时禁止写入 | 用户确认 | 用户确认前不改文件 |
| F-505 | 禁止删除 | P0 | Agent 请求删除文件 | 输出 denied | 记录安全事件 | 无 | 默认永远拒绝删除 |
| F-506 | 日志导出 | P1 | 用户点击导出 | 输出 zip/jsonl | 导出失败提示路径 | 本地文件写权限 | 可导出诊断日志 |
| F-507 | Embedding 模型选择 | P1 | 用户启用语义检索 | 输出 embedding_model | 不支持模型时禁用 semantic search | session token | LanceDB 检索可读取配置 |

## 6. 非功能需求

### 6.1 性能

- 应用冷启动到主 UI 可操作：P95 小于 10 秒。
- Python sidecar 启动并通过 `/api/health`：P95 小于 8 秒。
- 普通聊天首个 SSE 事件：P95 小于 3 秒，不含模型供应商排队时间。
- 1000 篇 Markdown、平均每篇 2000 字内，FTS5 搜索 P95 小于 300 ms。
- 1000 篇 Markdown 内，全量索引 P95 小于 90 秒。
- 空闲状态 CPU 平均小于 3%，内存小于 500 MB；索引期间允许短时升高但必须结束后回落。

### 6.2 可靠性

- sidecar 异常退出时，前端必须显示断连状态并允许重启。
- 索引任务必须可重复执行，重复执行不得生成重复 chunk。
- 写入 Markdown 时必须先写临时文件或采用原子替换策略，避免半写入。
- 任务提醒调度失败时必须保留 SQLite 记录，并允许用户手动重试。

### 6.3 安全

- FastAPI 只能监听 `127.0.0.1`。
- Electron main process 启动 sidecar 时生成随机 session token，并通过环境变量或 stdin 注入 sidecar。
- 禁止通过命令行参数传递 session token，避免 Windows 进程列表、崩溃报告或诊断工具泄露 token。
- 前端每个 API 请求必须携带 `Authorization: Bearer <session_token>`。
- Electron renderer 必须启用 `contextIsolation`，禁用 `nodeIntegration`，并通过 preload 暴露最小 IPC 白名单。
- Vault 路径必须由用户显式选择并持久化为 canonical absolute path。
- 所有文件读写必须校验目标 canonical path 是否位于授权 Vault 内。
- API Key 必须存储在 Windows Credential Manager、系统 keyring 或等效安全存储中，不得明文写入 SQLite 和日志。
- Agent 默认不得删除、移动、批量改写用户文件。

### 6.4 可维护性

- React renderer、Electron main/preload、Python API、Agent、Service、Repository、Storage 分层清晰。
- Agent 节点、Markdown 解析、路径校验、检索合并、时间解析必须可单元测试。
- API schema 使用 Pydantic 定义，前端类型通过 OpenAPI 或共享类型生成。
- SQLite schema 必须具备版本号和迁移记录。
- 日志必须包含 `request_id`、`conversation_id`、`agent_run_id`、`tool_call_id`。

## 7. 用户核心场景

### 7.1 首次启动

1. 用户启动应用。
2. Electron main process 启动 Python sidecar，并生成 session token。
3. 前端请求 `/api/health`，显示连接状态。
4. 用户选择创建或绑定 Vault。
5. 后端校验路径并生成默认模板。
6. 用户配置模型 API Key。
7. 系统执行首次索引。
8. 用户进入聊天界面。

### 7.2 询问记忆

用户输入：

```text
你还记得我为什么想做这个项目吗？
```

系统流程：

1. Chat API 创建 agent_run。
2. Router 判断需要检索长期记忆。
3. Retrieval Service 调用 FTS5 搜索。
4. Agent 基于 top_k 片段生成回答。
5. SSE 返回 token、citation、done 事件。
6. 前端展示回答和来源引用。

### 7.3 创建长期记忆

用户输入：

```text
记住，我更喜欢 Python 后端，因为我想用 LangGraph 和 MCP。
```

系统流程：

1. Router 判断为 propose_memory。
2. Memory Agent 生成候选记忆。
3. Safety Check 判断不属于敏感信息。
4. 后端创建 `memory_proposals` 记录。
5. 前端展示目标文件、预览 Markdown 和 diff。
6. 用户确认后写入 `00_Profile/Preferences.md` 或 `Inbox/Pending Memories.md`。
7. 系统更新 notes、note_chunks、note_fts。

### 7.4 创建提醒

用户输入：

```text
明天下午三点提醒我整理 Agent 项目文档。
```

系统流程：

1. Router 判断为 create_task。
2. Task Agent 抽取 title 和 due_at。
3. 时间明确时写入 tasks 和 reminders。
4. Scheduler 注册提醒。
5. 到期后触发系统通知。
6. 通知事件写入 audit log。

## 8. 总体架构

系统采用本地优先桌面架构。MVP 先使用内部 service 调用，Beta 再引入 MCP 工具层。

```text
Electron Desktop App
├─ React Renderer Process
│  ├─ Chat Panel
│  ├─ Memory Review Panel
│  ├─ Task Panel
│  └─ Settings Panel
│
├─ Electron Main Process
│  ├─ Window / Tray / Notification
│  ├─ Secure Token Generation
│  ├─ Python Sidecar Lifecycle
│  ├─ Preload IPC Bridge
│  └─ OS Integration
│
└─ Python FastAPI Sidecar
   ├─ API Layer
   ├─ Agent Runtime
   ├─ Internal Services
   │  ├─ Memory Service
   │  ├─ Retrieval Service
   │  ├─ Task Service
   │  └─ Scheduler Service
   ├─ Repositories
   ├─ Storage Adapters
   │  ├─ Obsidian Vault Adapter
   │  ├─ SQLite / FTS5
   │  └─ LanceDB, Beta
   └─ MCP Servers, Beta
```

### 8.1 进程边界

| 组件 | 进程 | 职责 | 通信方式 |
| --- | --- | --- | --- |
| React Renderer | Electron renderer | UI 渲染、用户输入、SSE 展示 | HTTP/SSE 到 sidecar；通过 preload 暴露的最小 IPC 调用主进程 |
| Electron Main | Node.js 主进程 | 窗口、托盘、通知、sidecar 管理、token 生成 | Electron IPC；启动 sidecar |
| Electron Preload | 隔离桥接脚本 | 暴露受控桌面能力，不暴露 Node.js 全量能力 | `contextBridge` + 白名单 IPC channel |
| Python Sidecar | 子进程 | API、Agent、检索、任务、调度 | 监听 `127.0.0.1` |
| SQLite/FTS5 | 本地文件 | 应用状态、索引和审计 | Python sqlite driver |
| Obsidian Vault | 用户目录 | 长期记忆正文 | Python 文件系统访问 |
| MCP Server | Beta，可进程内或 stdio 子进程 | 标准化工具能力 | MCP client/server |

### 8.2 MVP 调用链

```text
User
  -> React UI
  -> FastAPI /api/chat
  -> LangGraph Agent
  -> Internal Service
  -> SQLite / FTS5 / Obsidian Vault
  -> SSE Events
  -> React UI
```

### 8.3 Beta MCP 调用链

```text
LangGraph Agent
  -> MCP Client
  -> Memory/Search/Task/Pet MCP Server
  -> Internal Service
  -> Storage Adapter
```

MCP 不应在 MVP 阻塞核心闭环。MVP 中的 service 接口必须保持清晰，以便 Beta 阶段包装为 MCP tool。

## 9. 技术栈选型

| 模块 | MVP 方案 | Beta/后续 | 关键约束 |
| --- | --- | --- | --- |
| 桌面壳 | Electron main/preload/renderer | electron-builder 或 Electron Forge；后续接入签名更新 | Windows 优先验证打包 |
| 前端 | React + TypeScript + Vite | shadcn/ui 增强 | TypeScript strict |
| 状态管理 | Zustand | 可替换 | 不保存敏感 Key |
| 桌宠表现 | 可运行展示壳、静态/简化状态图、基础动作壳；已导入并可校验 `public\live2d\CubismSdkForWeb-5-r.5` | 单模型 Live2D Cubism idle 渲染接入，之后再扩展动作和多角色 | 本轮只准备单模型 idle 渲染验收；口型同步、复杂动作、多角色和完整 WebGL 表现不纳入 |
| 本地 API | Python FastAPI + Uvicorn | 无 | 仅监听 127.0.0.1 |
| Agent 编排 | LangGraph | 多 Agent 扩展 | 节点必须可测试 |
| 模型集成 | LangChain ChatModel + OpenAI-compatible provider | Anthropic/Gemini/Ollama、本地 embedding | 模型 provider 通过 LangChain 封装；MVP 不强制 embedding |
| 长期记忆正文 | Obsidian Markdown Vault | 模板可配置 | 不自动删除用户文件 |
| 应用状态 | SQLite | 无 | 使用 migration |
| 关键词检索 | SQLite FTS5 | 无 | 支持 rebuild |
| 语义检索 | 暂不强制 | LanceDB | FTS 可独立工作 |
| 调度 | APScheduler | 系统日历集成 | 重启后恢复 pending reminders |
| 工具协议 | 内部 service | MCP Python SDK | Beta 引入 |

## 10. 工程目录规划

```text
agent-pet/
├─ apps/
│  ├─ desktop/
│  │  ├─ src/
│  │  ├─ electron/
│  │  │  ├─ main/
│  │  │  └─ preload/
│  │  └─ package.json
│  └─ backend/
│     ├─ app/
│     │  ├─ api/
│     │  ├─ agents/
│     │  ├─ services/
│     │  ├─ repositories/
│     │  ├─ storage/
│     │  ├─ scheduler/
│     │  ├─ models/
│     │  └─ config.py
│     ├─ migrations/
│     ├─ tests/
│     └─ pyproject.toml
├─ docs/
├─ scripts/
├─ README.md
└─ Development_Documentation.md
```

分层规则：

- API Layer 只处理 HTTP、鉴权、请求校验和响应格式。
- Agent Layer 只处理状态流、节点路由和模型调用。
- Service Layer 处理业务流程，如记忆确认、索引、提醒。
- Repository Layer 处理 SQLite 数据访问。
- Storage Layer 处理 Obsidian 文件、FTS5、LanceDB。
- Electron main process 不直接访问 Obsidian 业务文件，除非用于系统文件选择器；Obsidian 文件读写仍由 Python sidecar 统一校验和执行。

## 11. 数据设计

### 11.1 通用约定

- 所有主键使用 UUID string。
- 所有时间使用 ISO 8601 UTC 存储，前端按本地时区展示。
- 所有状态字段必须使用枚举值。
- 所有 JSON 字段存储为 TEXT，但必须由 Pydantic schema 校验。
- SQLite 开启 foreign key。
- 每次 migration 写入 `schema_migrations`。

### 11.2 SQLite 表

#### schema_migrations

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| version | INTEGER | PRIMARY KEY | schema 版本 |
| applied_at | TEXT | NOT NULL | 应用时间 |

#### settings

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| key | TEXT | PRIMARY KEY | 配置键 |
| value_json | TEXT | NOT NULL | JSON 配置值，不包含明文 API Key |
| updated_at | TEXT | NOT NULL | 更新时间 |

#### vaults

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | Vault ID |
| name | TEXT | NOT NULL | Vault 名称 |
| root_path | TEXT | NOT NULL UNIQUE | canonical absolute path |
| status | TEXT | NOT NULL | active / disconnected |
| created_at | TEXT | NOT NULL | 创建时间 |
| updated_at | TEXT | NOT NULL | 更新时间 |

#### conversations

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | 会话 ID |
| title | TEXT |  | 标题 |
| summary | TEXT |  | 摘要 |
| status | TEXT | NOT NULL | active / archived |
| created_at | TEXT | NOT NULL | 创建时间 |
| updated_at | TEXT | NOT NULL | 更新时间 |

#### messages

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | 消息 ID |
| conversation_id | TEXT | NOT NULL REFERENCES conversations(id) | 会话 ID |
| role | TEXT | NOT NULL | user / assistant / tool / system |
| content | TEXT | NOT NULL | 消息内容 |
| metadata_json | TEXT | NOT NULL DEFAULT '{}' | citations、tool events 等 |
| status | TEXT | NOT NULL | partial / completed / failed / cancelled |
| created_at | TEXT | NOT NULL | 创建时间 |
| updated_at | TEXT | NOT NULL | 更新时间 |

索引：

```sql
CREATE INDEX idx_messages_conversation_created ON messages(conversation_id, created_at);
```

#### notes

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | 笔记 ID |
| vault_id | TEXT | NOT NULL REFERENCES vaults(id) | Vault ID |
| relative_path | TEXT | NOT NULL | Vault 内相对路径 |
| title | TEXT | NOT NULL | 标题 |
| content_hash | TEXT | NOT NULL | 内容 hash |
| modified_at | TEXT | NOT NULL | 文件修改时间 |
| indexed_at | TEXT | NOT NULL | 索引时间 |
| status | TEXT | NOT NULL | indexed / deleted / failed |

约束：

```sql
CREATE UNIQUE INDEX idx_notes_vault_path ON notes(vault_id, relative_path);
```

#### note_chunks

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | chunk ID |
| note_id | TEXT | NOT NULL REFERENCES notes(id) ON DELETE CASCADE | 笔记 ID |
| heading | TEXT |  | 所属标题 |
| content | TEXT | NOT NULL | chunk 内容 |
| start_line | INTEGER | NOT NULL | 起始行 |
| end_line | INTEGER | NOT NULL | 结束行 |
| chunk_hash | TEXT | NOT NULL | chunk hash |

#### note_fts

```sql
CREATE VIRTUAL TABLE note_fts USING fts5(
  chunk_id UNINDEXED,
  note_id UNINDEXED,
  title,
  relative_path,
  heading,
  content,
  tags
);
```

#### memory_proposals

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | proposal ID |
| conversation_id | TEXT | REFERENCES conversations(id) | 来源会话 |
| source_message_id | TEXT | REFERENCES messages(id) | 来源消息 |
| type | TEXT | NOT NULL | preference / fact / event / goal / rule |
| content | TEXT | NOT NULL | 结构化摘要 |
| target_path | TEXT | NOT NULL | Vault 内目标文件 |
| target_content_hash | TEXT |  | 创建 proposal 时目标文件 hash；新文件为空 |
| preview_markdown | TEXT | NOT NULL | 待写入 Markdown |
| diff_text | TEXT |  | 修改已有文件时的 unified diff |
| confidence | REAL | NOT NULL | 0 到 1 |
| status | TEXT | NOT NULL | pending / confirmed / rejected / failed |
| rejection_reason | TEXT |  | 拒绝原因 |
| created_at | TEXT | NOT NULL | 创建时间 |
| updated_at | TEXT | NOT NULL | 更新时间 |

约束：

- `target_path` 必须是 Vault 内相对路径，不允许绝对路径。
- `diff_text` 必须基于 `target_content_hash`；确认时目标文件 hash 不一致必须拒绝写入并要求重新预览。

#### tasks

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | 任务 ID |
| title | TEXT | NOT NULL | 任务标题 |
| description | TEXT |  | 描述 |
| due_at | TEXT |  | 截止时间 |
| time_parse_timezone | TEXT |  | 自然语言时间解析所用 IANA timezone |
| status | TEXT | NOT NULL | pending / done / cancelled |
| source_message_id | TEXT | REFERENCES messages(id) | 来源消息 |
| completed_at | TEXT |  | 完成时间 |
| created_at | TEXT | NOT NULL | 创建时间 |
| updated_at | TEXT | NOT NULL | 更新时间 |

#### reminders

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | 提醒 ID |
| task_id | TEXT | NOT NULL REFERENCES tasks(id) ON DELETE CASCADE | 任务 ID |
| remind_at | TEXT | NOT NULL | 提醒时间 |
| status | TEXT | NOT NULL | scheduled / unscheduled / triggered / cancelled / failed |
| triggered_at | TEXT |  | 实际触发时间 |
| error | TEXT |  | 错误信息 |
| created_at | TEXT | NOT NULL | 创建时间 |
| updated_at | TEXT | NOT NULL | 更新时间 |

索引：

```sql
CREATE INDEX idx_reminders_status_time ON reminders(status, remind_at);
CREATE INDEX idx_tasks_status_due ON tasks(status, due_at);
```

#### index_jobs

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | 任务 ID |
| vault_id | TEXT | NOT NULL REFERENCES vaults(id) | Vault ID |
| type | TEXT | NOT NULL | full / incremental |
| status | TEXT | NOT NULL | queued / running / success / failed |
| total_files | INTEGER | NOT NULL DEFAULT 0 | 总文件数 |
| processed_files | INTEGER | NOT NULL DEFAULT 0 | 已处理数 |
| error | TEXT |  | 错误 |
| started_at | TEXT |  | 开始时间 |
| ended_at | TEXT |  | 结束时间 |

#### agent_runs

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | Agent run ID |
| conversation_id | TEXT | NOT NULL REFERENCES conversations(id) | 会话 ID |
| intent | TEXT | NOT NULL | chat / search_memory / propose_memory / create_task |
| status | TEXT | NOT NULL | running / success / failed / cancelled |
| error | TEXT |  | 错误 |
| started_at | TEXT | NOT NULL | 开始时间 |
| ended_at | TEXT |  | 结束时间 |

#### tool_calls

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | 工具调用 ID |
| agent_run_id | TEXT | NOT NULL REFERENCES agent_runs(id) | Agent run |
| tool_name | TEXT | NOT NULL | 工具名称 |
| input_json | TEXT | NOT NULL | 输入 |
| output_json | TEXT |  | 输出 |
| status | TEXT | NOT NULL | running / success / failed / denied |
| error | TEXT |  | 错误 |
| created_at | TEXT | NOT NULL | 创建时间 |
| ended_at | TEXT |  | 结束时间 |

#### audit_logs

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | TEXT | PRIMARY KEY | 审计 ID |
| action | TEXT | NOT NULL | 操作 |
| actor | TEXT | NOT NULL | user / agent / system |
| resource | TEXT | NOT NULL | 资源 |
| result | TEXT | NOT NULL | allowed / denied / failed |
| detail_json | TEXT | NOT NULL DEFAULT '{}' | 详情 |
| created_at | TEXT | NOT NULL | 创建时间 |

### 11.3 LanceDB Schema, Beta

集合：`memory_chunks`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| chunk_id | string | chunk ID |
| note_id | string | 笔记 ID |
| vault_id | string | Vault ID |
| title | string | 标题 |
| relative_path | string | 文件路径 |
| heading | string | 所属标题 |
| content | string | chunk 内容 |
| embedding | vector | 向量 |
| content_hash | string | chunk hash |
| updated_at | timestamp | 更新时间 |

## 12. Obsidian Vault 设计

### 12.1 默认目录

```text
PetMemoryVault/
├─ 00_Profile/
│  ├─ User.md
│  ├─ Pet.md
│  └─ Preferences.md
├─ 01_Memories/
│  ├─ Important Events.md
│  ├─ Conversations.md
│  └─ User Goals.md
├─ 02_Tasks/
│  ├─ Todos.md
│  └─ Reminders.md
├─ 03_Knowledge/
│  └─ Topics.md
├─ 04_Reflections/
│  ├─ Daily Summary/
│  └─ Weekly Summary/
├─ 05_Agent/
│  ├─ Personality.md
│  ├─ Rules.md
│  └─ Memory Policy.md
└─ Inbox/
   └─ Pending Memories.md
```

### 12.2 写入规则

- 新增长期偏好默认写入 `00_Profile/Preferences.md`。
- 用户目标默认写入 `01_Memories/User Goals.md`。
- 重要事件默认写入 `01_Memories/Important Events.md`。
- 不确定或需延后处理的候选写入 `Inbox/Pending Memories.md`。
- 修改已有文件必须展示 diff。
- Agent 不允许删除 Markdown 文件。
- Agent 不允许写入 `.obsidian` 配置目录，除非用户后续显式授权。

### 12.3 模板

#### User.md

```markdown
# User

## Stable Facts

## Preferences

## Goals

## Work Style

## Communication Style

## Avoid
```

#### Pending Memories.md

```markdown
# Pending Memories

## YYYY-MM-DD

### Memory Candidate
- Content:
- Type:
- Confidence:
- Source:
- Status: pending
```

#### Memory Policy.md

```markdown
# Memory Policy

## Should Remember
- Long-term preferences explicitly approved by the user
- Important project decisions
- Recurring habits
- User goals
- Stable personal facts explicitly approved by the user

## Should Not Remember
- One-off casual statements
- Sensitive information without explicit approval
- Credentials, API keys, passwords, tokens
- Unverified assumptions
```

## 13. 检索与索引设计

### 13.1 Markdown 解析规则

- 仅索引授权 Vault 内的 `.md` 文件。
- 忽略 `.obsidian/`、隐藏目录、二进制文件和超过配置大小上限的文件。
- frontmatter 使用 YAML parser 解析；解析失败时将其作为正文处理并记录 warning。
- 标题使用 Markdown heading 提取；无 H1 时使用文件名作为标题。
- 标签来源包括 frontmatter tags 和正文 `#tag`。
- 双链 `[[Page]]` 和 `[[Page|Alias]]` 作为 metadata 保存，MVP 不要求反向链接图谱。

### 13.2 Chunk 策略

- 优先按 heading 分块。
- 单 chunk 目标长度 300 到 800 汉字或等价 token。
- 超长 heading section 按段落继续切分。
- 每个 chunk 保留 `title`、`relative_path`、`heading`、`start_line`、`end_line`。
- chunk_id 基于 note_id、start_line、end_line 和 chunk_hash 生成。

### 13.3 增量索引

MVP 可手动重建索引；Beta 增加文件监听。

增量流程：

1. 监听到新增、修改、删除事件。
2. 将路径转换为 canonical path 并校验是否在 Vault 内。
3. 删除事件将 notes.status 标记为 deleted，并删除 note_chunks、note_fts、LanceDB 对应记录。
4. 新增或修改事件计算 content_hash。
5. hash 未变化则跳过。
6. hash 变化则重建该 note 的 chunks、FTS rows 和 vector rows。

索引一致性要求：

- 单个 note 的 `notes`、`note_chunks`、`note_fts` 更新必须在同一个 SQLite transaction 内完成。
- 重建某个 note 前，必须先删除该 note 的旧 `note_chunks` 和旧 `note_fts` rows，再插入新 rows。
- 如果 FTS5 写入失败，必须回滚本次 note 更新，不能留下新 chunks + 旧 FTS 的混合状态。
- 删除文件时，`notes.status` 标记为 `deleted`，同时删除对应 chunks、FTS rows 和 LanceDB rows；删除动作必须可重复执行。
- 全量重建索引时不得直接清空用户 Vault，只能重建 SQLite/FTS/LanceDB 中的索引数据。

### 13.4 FTS5 搜索

- 查询字段：title、relative_path、heading、content、tags。
- 默认 top_k 为 8，最大 top_k 为 20。
- 返回 snippet 必须限制长度，避免把整篇笔记发送给模型。
- 结果必须包含 `note_id`、`chunk_id`、`relative_path`、`heading`、`snippet`、`score`。

### 13.5 混合检索, Beta

混合检索排序：

1. 分别执行 FTS5 和 LanceDB。
2. 对两路结果做 score normalization。
3. 按 chunk_id 去重。
4. 默认权重：FTS 0.55，semantic 0.45。
5. 相同分数优先选择更新时间更近、heading 更具体的 chunk。
6. LanceDB 不可用时回退到 FTS5，并在响应 metadata 中标记 `semantic_available=false`。

## 14. API 设计

### 14.1 通用约定

Base URL：

```text
http://127.0.0.1:{port}
```

鉴权：

```http
Authorization: Bearer <session_token>
```

错误响应：

```json
{
  "error": {
    "code": "vault_path_denied",
    "message": "Path is outside the authorized vault.",
    "request_id": "uuid",
    "details": {}
  }
}
```

常用状态码：

- `400`：请求字段无效。
- `401`：缺少或错误的 session token。
- `403`：权限拒绝。
- `404`：资源不存在。
- `409`：状态冲突，例如 proposal 已处理。
- `422`：请求 schema 通过 JSON 解析但业务字段校验失败，例如时间不明确。
- `500`：未预期服务端错误。

分页约定：

- 列表接口默认 `limit=50`，最大 `limit=100`。
- 游标字段使用 `cursor`，响应中返回 `next_cursor`。
- MVP 至少对 `GET /api/memory/proposals`、`GET /api/tasks/today` 的未来扩展保留分页参数；今日任务默认返回当日全部 pending/done 项。

### 14.2 Health API

```http
GET /api/health
```

该接口用于 sidecar 存活检测，允许无鉴权访问，但不得返回 Vault 路径、active_vault_id、模型供应商、用户名等状态信息。需要读取业务状态时必须调用已鉴权的 `/api/vaults/status` 或 `/api/settings`。

响应：

```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "ok"
}
```

### 14.3 Chat API

```http
POST /api/chat
```

请求：

```json
{
  "conversation_id": "string|null",
  "message": "string"
}
```

响应：

```json
{
  "conversation_id": "string",
  "message_id": "string",
  "agent_run_id": "string",
  "stream_url": "/api/chat/runs/{agent_run_id}/events"
}
```

流式协议统一使用 SSE 格式，但 MVP 前端必须使用 `fetch` 读取 streaming response，以便携带 `Authorization` header。不得直接使用原生 `EventSource` 连接受保护接口，因为浏览器 EventSource 不能设置自定义 Authorization header。

```http
GET /api/chat/runs/{agent_run_id}/events
```

如后续必须使用 EventSource，则 `POST /api/chat` 必须返回一次性、短 TTL 的 `stream_token`，并使用只允许读取该 `agent_run_id` 的查询参数鉴权。该方案不得复用全局 session token。

SSE 事件：

```text
event: token
data: {"text":"..."}

event: citation
data: {"relative_path":"00_Profile/Preferences.md","heading":"Preferences","snippet":"..."}

event: memory_proposal
data: {"proposal_id":"uuid","preview_markdown":"..."}

event: task_created
data: {"task_id":"uuid","title":"...","due_at":"2026-04-27T07:00:00Z"}

event: error
data: {"code":"model_error","message":"..."}

event: done
data: {"message_id":"uuid"}
```

取消：

```http
POST /api/chat/runs/{agent_run_id}/cancel
```

### 14.4 Vault API

```http
POST /api/vaults/init
GET /api/vaults/status
POST /api/vaults/{vault_id}/index
GET /api/index-jobs/{job_id}
```

初始化请求：

```json
{
  "mode": "create",
  "path": "%USERPROFILE%/PetMemoryVault",
  "name": "PetMemoryVault"
}
```

初始化响应：

```json
{
  "vault_id": "uuid",
  "root_path": "%USERPROFILE%/PetMemoryVault",
  "created_files": [
    "00_Profile/User.md",
    "Inbox/Pending Memories.md"
  ]
}
```

### 14.5 Memory API

```http
POST /api/memory/search
GET /api/memory/proposals
POST /api/memory/proposals
POST /api/memory/proposals/{proposal_id}/confirm
POST /api/memory/proposals/{proposal_id}/reject
```

搜索请求：

```json
{
  "query": "string",
  "top_k": 8,
  "mode": "fts"
}
```

搜索响应：

```json
{
  "results": [
    {
      "note_id": "uuid",
      "chunk_id": "uuid",
      "relative_path": "00_Profile/Preferences.md",
      "title": "Preferences",
      "heading": "Work Style",
      "snippet": "string",
      "score": 0.87
    }
  ],
  "metadata": {
    "semantic_available": false
  }
}
```

创建 proposal 请求：

```json
{
  "type": "preference",
  "content": "User prefers Python backend for LangGraph and MCP work.",
  "target_path": "00_Profile/Preferences.md",
  "source_message_id": "uuid"
}
```

确认响应：

```json
{
  "proposal_id": "uuid",
  "status": "confirmed",
  "written_path": "00_Profile/Preferences.md",
  "index_job_id": "uuid"
}
```

拒绝请求：

```json
{
  "reason": "not_relevant"
}
```

### 14.6 Task API

```http
POST /api/tasks
GET /api/tasks/today
PATCH /api/tasks/{task_id}
POST /api/tasks/{task_id}/complete
POST /api/tasks/{task_id}/cancel
```

创建请求：

```json
{
  "title": "整理 Agent 项目文档",
  "description": "",
  "due_at": "2026-04-27T07:00:00Z",
  "remind_at": "2026-04-27T07:00:00Z",
  "timezone": "北京时间",
  "source_text": "明天下午三点提醒我整理 Agent 项目文档"
}
```

时间规则：

- API 存储 `due_at` 和 `remind_at` 时必须转换为 UTC ISO 8601。
- 自然语言时间解析必须使用前端传入 timezone；客户可见默认显示“北京时间”，底层 IANA 标识仍按 `Asia/Shanghai` 存储；未传入时使用系统本地 timezone，并在响应 metadata 中返回实际使用值。
- 时间不明确时不得猜测创建提醒，必须返回需要确认的候选时间。

响应：

```json
{
  "task_id": "uuid",
  "reminder_id": "uuid",
  "status": "pending"
}
```

### 14.7 Settings API

```http
GET /api/settings
POST /api/settings/model-key
PUT /api/settings/model-config
DELETE /api/settings/model-key
```

API Key 保存请求：

```json
{
  "provider": "openai",
  "api_key": "sk-..."
}
```

响应不得返回明文 Key：

```json
{
  "provider": "openai",
  "status": "saved",
  "masked": "sk-...abcd"
}
```

模型配置保存请求：

```json
{
  "provider": "openai-compatible",
  "base_url": "https://api.example.com/v1",
  "model": "model-name"
}
```

响应：

```json
{
  "provider": "openai-compatible",
  "base_url": "https://api.example.com/v1",
  "model": "model-name",
  "status": "saved"
}
```

`GET /api/settings` 必须返回模型与知识库配置状态：

```json
{
  "model_provider": "openai-compatible",
  "model_base_url": "https://api.example.com/v1",
  "chat_model": "model-name",
  "model_configured": true,
  "vault_configured": true
}
```

## 15. Agent 设计

### 15.1 LangGraph State

```python
class AgentState(TypedDict):
    request_id: str
    agent_run_id: str
    conversation_id: str
    user_message: str
    intent: Literal["chat", "search_memory", "propose_memory", "create_task"]
    retrieved_chunks: list[dict]
    citations: list[dict]
    tool_results: list[dict]
    draft_response: str
    memory_proposals: list[dict]
    task_draft: dict | None
    safety_flags: list[str]
    stream_events: list[dict]
    final_response: str
    error: dict | None
    cancelled: bool
```

### 15.2 节点

- `route_intent`：判断意图；低置信度进入 chat。
- `semantic_analysis_agent`：判断是否需要上下文，并输出检索范围。
- `memory_retrieval_agent`：检索个人记忆和每日聊天记录。
- `knowledge_retrieval_agent`：检索知识库文档并产出 citations。
- `run_companion_agent`：基于已收集 citations 生成普通陪伴对话。
- `run_memory_proposal_agent`：生成 memory proposal，不直接写入文件。
- `run_task_agent`：抽取任务和提醒时间。
- `run_safety_check`：检查越权、敏感信息、删除/移动/批量改写。
- `persist_outputs`：落库消息、proposal、task。
- `emit_response`：产生 SSE 事件。

### 15.3 失败处理

- 工具调用失败：记录 tool_calls.failed，Agent 回复降级说明。
- 模型调用失败：SSE 输出 error，agent_run 标记 failed。
- 用户取消：agent_run 标记 cancelled，停止继续写入 assistant 正文。
- 记忆安全拒绝：创建 rejected proposal 或直接返回拒绝原因，不写 Markdown。
- 检索为空：明确说明未找到相关记忆，不编造引用。

### 15.4 Memory Proposal 生命周期

```text
created pending
  -> confirmed -> write markdown -> update index
  -> rejected
  -> failed
```

约束：

- pending 不等于已记住。
- confirmed 之后才允许写入正式目标文件。
- failed 必须保留错误信息，允许用户重试或拒绝。
- rejected 不得被 Agent 自动重新提交，除非用户再次明确要求。

## 16. MCP 工具设计, Beta

MVP 不强制实现 MCP。Beta 阶段将内部 service 包装为 MCP tools。

### 16.1 工具通用约定

- 每个工具必须有 JSON schema。
- 每次调用必须写入 tool_calls。
- 工具必须检查权限，不信任 Agent 输入。
- 默认超时 30 秒。
- 返回错误时使用 `{ "error": { "code": "...", "message": "..." } }`。

### 16.2 首期工具

| 工具名 | 内部 service | 权限 | 说明 |
| --- | --- | --- | --- |
| memory.search | RetrievalService.search | Vault read | 搜索记忆 |
| memory.read | VaultStorage.read_note | Vault read | 读取指定 Markdown |
| memory.propose | MemoryService.create_proposal | session | 创建候选记忆 |
| memory.write_confirmed | MemoryService.confirm_proposal | Vault write + user confirmation | 写入已确认记忆 |
| task.create | TaskService.create | session | 创建任务提醒 |
| task.list_today | TaskService.list_today | session | 今日任务 |
| task.complete | TaskService.complete | session | 完成任务 |
| pet.set_emotion | PetEventService.emit | UI channel | 设置桌宠状态 |

## 17. 安全设计

### 17.1 路径安全

所有文件访问必须使用以下流程：

1. 将用户选择的 Vault root 转换为 canonical absolute path。
2. 将目标 path 与 Vault root 拼接后再次 canonicalize。
3. 判断目标 canonical path 是否以 Vault root canonical path 为前缀。
4. 拒绝 `..` 越界、符号链接越界、绝对路径注入、隐藏配置目录写入。
5. 所有拒绝写入 audit_logs。

Windows 额外要求：

- 比较路径前必须统一大小写规则、路径分隔符和尾部分隔符。
- 必须拒绝通过 short path、UNC path、junction、symlink、reparse point 绕过 Vault root 的访问。
- 用户输入的相对路径只允许使用 Vault 内部相对路径，API 不接受任意绝对目标路径。
- 写入 `.obsidian/`、`.git/`、隐藏目录和应用索引目录默认拒绝。

### 17.2 API 安全

- sidecar 只监听 `127.0.0.1`。
- session token 每次应用启动重新生成。
- token 不写入日志、不写入 SQLite。
- CORS 仅允许 Electron renderer 开发/生产所需来源；同时不能仅依赖 CORS，必须校验 Authorization。
- Electron BrowserWindow 必须启用 `contextIsolation: true`、`nodeIntegration: false`，preload 只暴露选择 Vault、读取连接状态、获取临时 API 配置等白名单能力。
- renderer 不得直接访问 Node.js `fs`、`child_process`、环境变量或任意 IPC channel。
- 所有非 health API 都必须鉴权。

### 17.3 记忆安全

默认拒绝自动保存：

- API Key、密码、token、密钥。
- 身份证、银行卡、住址、手机号等高敏感个人信息。
- 医疗、法律、金融等高风险结论。
- 未经用户明确确认的推测。

允许进入候选但必须确认：

- 长期偏好。
- 项目决策。
- 学习目标。
- 工作方式。
- 用户显式要求记住的非敏感事实。

### 17.4 写入安全

- 新文件写入需要展示 preview。
- 修改已有文件需要展示 unified diff。
- 写入失败不得更新 proposal 为 confirmed。
- 写入成功后必须记录 audit_logs。
- 删除文件默认拒绝，即使 Agent 生成了删除请求。

Markdown 写入实现要求：

- 修改已有文件前必须重新读取磁盘内容并校验 proposal 基于的 content_hash；hash 不一致时要求重新生成 diff。
- 写入同一文件时必须串行化，避免两个 proposal 同时覆盖。
- Windows 上如 Obsidian 或同步软件占用文件，必须返回可重试错误，不得静默失败。
- 写入应使用同卷临时文件 + flush + replace/rename；无法安全替换时保留原文件并返回失败。
- 必须尽量保持原文件编码、换行风格和末尾换行；无法识别时使用 UTF-8。
- 修改已有文件前创建 `.bak` 或等效回滚记录；备份位置必须仍在授权 Vault 或应用数据目录内。

### 17.5 模型隐私

- 不发送整个 Vault 给云模型。
- 只发送当前用户消息、必要会话摘要和 top_k 检索片段。
- 设置页必须说明哪些内容可能发送到模型供应商。
- 本地模型模式作为后续隐私增强，不阻塞 MVP。

## 18. 日志与可观测性

### 18.1 日志字段

```text
timestamp
level
request_id
conversation_id
agent_run_id
tool_call_id
module
event
message
duration_ms
error_code
error
```

### 18.2 日志类型

- 应用启动和 sidecar 生命周期。
- API 请求和错误。
- Agent run 状态。
- 工具调用。
- 索引任务。
- 模型调用，不记录完整 prompt 中的敏感内容。
- 文件写入审计。
- 安全拒绝事件。

### 18.3 导出

Beta 支持导出诊断日志。导出内容必须自动脱敏 API Key、token、Authorization header。

## 19. 开发阶段规划

### 阶段 1：工程骨架和本地 API

目标：应用可启动，前后端可通信。

任务：

- 初始化 Electron + React + TypeScript。
- 初始化 Python FastAPI sidecar。
- 实现 Electron main process 启动和关闭 sidecar。
- 实现 session token 注入和 API 鉴权。
- 实现 `/api/health`。
- 建立 SQLite migration 框架。
- 实现设置页基础 UI。

交付物：

- Windows 上应用可启动和退出。
- sidecar 健康检查可用。
- 缺失 token 的 API 请求被拒绝。

### 阶段 2：Vault、SQLite 和 FTS5 检索

目标：完成 Obsidian 记忆读取和搜索。

任务：

- 实现 Vault 创建/绑定。
- 生成默认目录和模板。
- 实现 canonical path 校验。
- 建立 notes、note_chunks、note_fts、index_jobs。
- 实现 Markdown 解析和 chunk。
- 实现全量索引和 FTS5 搜索。
- 实现来源引用。

交付物：

- 可初始化 PetMemoryVault。
- 可搜索 Markdown 内容。
- 路径穿越和未授权路径访问被拒绝。

### 阶段 3：聊天和 Agent MVP

目标：完成基于记忆的聊天闭环。

任务：

- 实现 conversations、messages、agent_runs。
- 实现 Chat API 和 SSE。
- 实现 LangGraph 基础状态流。
- 实现意图识别、记忆检索、回答生成。
- 实现 citations 展示。
- 实现模型配置和 API Key 安全存储。

交付物：

- 用户可以聊天。
- Agent 可以基于 Vault 片段回答。
- 回复包含来源引用。

### 阶段 4：记忆确认写入和提醒

目标：完成长期记忆和任务提醒核心闭环。

任务：

- 实现 memory_proposals。
- 实现候选记忆生成、预览、确认、拒绝。
- 实现 Markdown 原子写入和索引刷新。
- 实现 tasks、reminders。
- 实现自然语言创建提醒。
- 接入 APScheduler 和系统通知。

交付物：

- 用户确认后长期记忆写入 Obsidian。
- 拒绝的候选不会写入。
- 到期提醒可触发系统通知。

### 阶段 5：桌宠体验增强

目标：增强桌面陪伴感。

任务：

- 实现透明悬浮窗口、拖拽、置顶。
- 接入单模型 Live2D Cubism idle 渲染或静态角色回退。
- 先保证 idle 状态可持续渲染；thinking/speaking/reminding 映射、口型同步、复杂动作和多角色切换后续实现。
- 实现聊天气泡和提醒状态。

交付物：

- 桌宠窗口可显示和移动。
- 单模型 idle 渲染可见；聊天和提醒时可保留基础状态反馈，但不要求口型同步或复杂动作。

### 阶段 6：MCP 工具层和向量检索

目标：标准化工具能力，提升检索质量。

任务：

- 将 Memory/Search/Task/Pet service 包装为 MCP tools。
- 记录 MCP tool_calls。
- 接入 LanceDB 和 embedding。
- 实现 hybrid retrieval。
- 增加文件监听增量索引。

交付物：

- Agent 可通过 MCP 调用核心工具。
- 混合检索可用，LanceDB 不可用时可回退 FTS。

### 阶段 7：产品化和发布

目标：形成可分发版本。

任务：

- 配置 electron-builder 或 Electron Forge 打包。
- 打包 Python sidecar。
- 完成安装、启动、退出测试。
- 增加日志导出。
- 验证 Windows 兼容性。
- 后续接入自动更新。

交付物：

- Windows 安装包。
- 用户可安装、启动、配置、聊天、检索、写入记忆、创建提醒。

## 20. 开发规范

### 20.1 Git 分支

```text
main：稳定发布分支
develop：集成开发分支
feature/*：功能分支
fix/*：缺陷修复分支
release/*：发布准备分支
```

### 20.2 Commit 规范

```text
feat: 新功能
fix: 修复问题
docs: 文档更新
refactor: 重构
test: 测试
chore: 工程配置
build: 构建相关
```

示例：

```text
feat(memory): add pending memory workflow
fix(search): handle deleted markdown files during indexing
```

### 20.3 前端规范

- TypeScript strict。
- 组件使用 PascalCase。
- hooks 使用 `useXxx`。
- API 调用集中在 services。
- 不在 Zustand 或 localStorage 保存明文 API Key。
- UI 必须展示 loading、error、empty 状态。

### 20.4 后端规范

- Python 使用类型标注。
- API schema 使用 Pydantic。
- Service 不直接依赖 FastAPI Request。
- Repository 不包含业务判断。
- Storage 不调用模型。
- Agent 节点保持单一职责并可单元测试。

## 21. 测试策略

### 21.1 单元测试

必须覆盖：

- canonical path 校验。
- Windows short path、UNC path、junction、symlink、reparse point 越权校验。
- Markdown frontmatter、标签、双链、heading 解析。
- chunk 切分。
- FTS5 查询参数、结果映射、删除同步和事务回滚。
- 记忆 proposal 状态流。
- 时间解析。
- API token 校验。
- session token 不得通过命令行参数传递。
- fetch streaming 鉴权失败和取消生成。
- 敏感记忆拒绝规则。
- 自然语言时间解析必须使用明确 timezone。

### 21.2 集成测试

必须覆盖：

- 初始化 Vault 并生成模板。
- 全量索引 Markdown 文件。
- 搜索返回引用片段。
- Chat API 创建会话并通过带 Authorization 的 fetch streaming 产生 SSE 格式事件。
- Health API 无鉴权但不返回 active_vault_id、Vault path 或模型配置。
- 确认 proposal 后写入 Markdown 并刷新索引。
- proposal 确认前目标文件 hash 变化时拒绝写入并要求重新预览。
- 创建提醒并写入 tasks/reminders。
- 自然语言提醒解析后以 UTC 存储，并保留 time_parse_timezone。
- reminder 调度失败时进入 unscheduled，重启后允许重试。
- sidecar 重启后恢复 pending reminders。

### 21.3 端到端测试

必须覆盖：

- 应用启动。
- 设置模型 Key。
- 创建或绑定 Vault。
- 发送记忆查询。
- 创建候选记忆并确认。
- 创建提醒并触发通知。

### 21.4 安全测试

必须覆盖：

- `../` 路径穿越。
- 符号链接越界。
- Windows junction/reparse point 越界。
- 未授权 Vault 访问。
- 缺失或错误 session token。
- Agent 请求删除文件。
- 敏感信息自动写入尝试。
- 写入已有文件前未展示 diff 的路径。
- Obsidian 占用文件时写入失败必须保留原文件并返回可重试错误。

## 22. 验收标准

### 22.1 MVP 验收

| 场景 | 操作 | 预期结果 |
| --- | --- | --- |
| 首次启动 | 双击应用 | 10 秒内显示 UI，sidecar health 为 ok |
| 鉴权 | 不带 token 调用 `/api/vaults/status` | 返回 401 |
| 健康检查 | 不带 token 调用 `/api/health` | 返回 ok，但不包含 active_vault_id、Vault path、模型配置 |
| Vault 初始化 | 选择空目录创建 Vault | 生成默认目录和模板 |
| 路径安全 | 请求读取 Vault 外文件 | 返回 403，并写 audit log |
| 索引 | 对含 20 个 Markdown 的 Vault 建索引 | notes、note_chunks、note_fts 有对应数据 |
| 检索 | 搜索已存在关键词 | 返回包含 relative_path 和 snippet 的结果 |
| 聊天 | 询问 Vault 中已有信息 | SSE 返回 token、citation、done |
| 流式鉴权 | 不带 token 请求流式接口 | 返回 401，不产生事件 |
| 候选记忆 | 输入“记住……” | 创建 pending proposal，不直接写入正式文件 |
| 确认写入 | 确认 proposal | Markdown 更新，proposal 变 confirmed，索引刷新 |
| 写入冲突 | proposal 创建后手动修改目标 Markdown 再确认 | 返回 409，要求重新生成 diff |
| 拒绝写入 | 拒绝 proposal | proposal 变 rejected，Markdown 不变 |
| 提醒 | 创建一分钟后的提醒 | 到期触发系统通知并标记 triggered |
| 时间解析 | 用自然语言创建“明天下午三点”提醒 | 按前端 timezone 解析，数据库存 UTC，响应返回使用的 timezone |
| 提醒调度失败 | 禁用通知权限后创建提醒 | reminder 标记 unscheduled，任务仍保留 |
| 敏感信息 | 要求记住 API Key | 默认拒绝或要求明确安全确认，不写入 Vault |
| 日志 | 执行聊天和写入 | 日志包含 request_id 和 agent_run_id |
| 桌宠展示区 | 启动后执行健康检查、聊天、搜索、记忆提案、任务和诊断操作；runtime 完成后观察 `UG` 单模型 canvas | 展示区可见，基础状态随页面操作变化；runtime 完成后单模型 idle 画面持续渲染；不要求口型同步、复杂动作或多角色 |

### 22.2 Beta 验收

- Live2D 状态可随 Agent 状态切换。
- LanceDB hybrid retrieval 可用，且 LanceDB 不可用时自动回退 FTS。
- MCP tool_calls 可审计。
- 文件修改后增量索引自动刷新。
- 日志导出自动脱敏。

### 22.3 正式版验收

- Windows 安装包可安装、启动、升级和卸载。
- Python sidecar 打包稳定，应用退出无残留进程。
- 1000 篇 Markdown 下检索性能满足非功能指标。
- 自动更新流程可验证。

## 23. 风险分析

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| MVP 范围过大 | 交付延期 | 严格区分 MVP、Beta、正式版 |
| Electron + Python sidecar 打包复杂 | 发布受阻 | 阶段 1 就验证 sidecar 生命周期，阶段 7 专项打包 |
| Live2D 授权不清 | 商业化受限 | MVP 可用静态角色，Beta 仅使用授权明确资源 |
| LangGraph 流程过复杂 | 调试困难 | MVP 只实现核心节点和明确状态 |
| MCP 过早引入 | 架构成本过高 | MVP 使用内部 service，Beta 包装 MCP |
| 向量索引失败 | 检索不稳定 | FTS5 作为必选能力，LanceDB 可回退 |
| Agent 误写记忆 | 用户信任下降 | proposal + preview + diff + confirm |
| API Key 泄露 | 严重安全问题 | 使用系统凭据存储，日志脱敏 |
| 路径越权 | 用户文件风险 | canonical path 校验和审计 |
| 提醒调度丢失 | 用户错过任务 | reminders 持久化，sidecar 启动时恢复 |

## 24. 运维与发布

### 24.1 本地数据路径

```text
应用配置：系统 AppData
SQLite 数据库：系统 AppData
日志：系统 AppData/logs
LanceDB 数据：系统 AppData, Beta
Obsidian Memory Vault：用户选择路径
API Key：系统凭据存储
```

### 24.2 打包

- 使用 electron-builder 或 Electron Forge 打包桌面应用。
- Python sidecar 使用 PyInstaller 或独立 Python runtime 打包。
- 应用启动时由 Electron main process 启动 sidecar。
- 应用退出时关闭 sidecar。
- 打包流程必须在 Windows CI 或专用打包机器验证。

### 24.3 自动更新, 正式版

- 使用 Electron 生态更新方案，优先评估 electron-updater 或 Electron Forge updater。
- 更新源可使用 GitHub Releases 或对象存储。
- 更新包必须签名。
- 更新前提示用户。
- 更新不得修改用户 Vault 内容。

## 25. 后续扩展规划

### 25.1 语音交互

- 语音输入：Whisper API 或本地 Whisper。
- 语音输出：系统 TTS、OpenAI TTS 或 Azure TTS。
- Live2D 口型同步。

### 25.2 本地模型模式

- Ollama Chat Model。
- 本地 embedding。
- 隐私模式下不调用云端模型。

### 25.3 插件生态

- Calendar MCP Server。
- File Organizer MCP Server。
- Browser MCP Server。
- Email MCP Server。
- GitHub MCP Server。

### 25.4 云同步

- 账号系统。
- 多设备同步。
- 端到端加密。
- 云端向量索引。

## 26. 总结

修订后的项目路线是：

```text
MVP:
Electron + React
Python FastAPI Sidecar
SQLite + FTS5
Obsidian Vault
LangGraph Core Agent
APScheduler

Beta:
Live2D
LanceDB
MCP
Incremental Indexing
Diagnostics Export

Future:
Auto Update
Voice
Local Models
Plugin Marketplace
Cloud Sync
```

本项目的工程成败不取决于技术名词数量，而取决于核心闭环是否可靠、安全、可验收。MVP 必须优先保证本地启动、授权 Vault、记忆检索、确认写入和提醒能力稳定，再逐步扩展 Live2D、MCP、向量检索和插件生态。
