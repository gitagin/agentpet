# Agent Pet 修复清单（按优先级）

> 基于 2026-07-26 全量代码评审。每项附证据位置（文件:行号，行号对应当日快照）、修法与验收标准。
> 工作量估算：S ≤ 半天，M ≈ 1–3 天，L ≈ 1 周以上。
>
> 优先级定义：
> - **P0**：主路径上的正确性/稳定性缺陷，每次使用都在发生，本周修
> - **P1**：决定"产品能不能交付"与"同类问题会不会再犯"的结构项，1–2 周
> - **P2**：架构收敛，防止熵继续增长，一个月内
> - **P3**：口径、打磨与卫生

## 总览

| # | 项 | 优先级 | 工作量 | 一句话 |
| --- | --- | --- | --- | --- |
| 1 | 流式回复逐 token 写库 | P0 | S | 800 token = 800 次建连+commit，全在事件循环上 |
| 2 | SQLite 连接从不关闭 + 无超时 | P0 | S | 全项目 14+ 处泄漏 fd，靠 GC 兜底 |
| 3 | SettingsStore 绕开统一连接 | P0 | S | 同一个库两套完整性语义；每条消息跑一遍迁移探测 |
| 4 | Electron 代理白名单缺 18 条路由 | P0 | S | `reject` 等接口现在就 403，前端类型已就绪 |
| 5 | 后台 asyncio 任务无强引用 + 异常静默 | P0 | S | 记忆归档可能无声丢失 |
| 6 | 打包不含 Python 运行时 | P1 | L | zip 里只有源码，用户机器上跑不起来 |
| 7 | 桌宠命中框无 DPI 换算 | P1 | M | 125%/150% 缩放（国内笔记本默认）下点不准 |
| 8 | sidecar 生命周期（杀进程/端口/复用状态机） | P1 | M | 残留 uvicorn、端口冲突即死、"ready+error"自相矛盾 |
| 9 | 用 openapi.json 生成白名单与前端类型 + CI 断言 | P1 | M | 根治 #4 的病根：三份手工清单互不校验 |
| 10 | 让 mypy / ruff 真的生效 | P1 | M | 当前类型检查按构造不可能失败 |
| 11 | 死代码了断：supervisor/reviewer/角色契约 | P1 | M | 删掉或接通，二选一；同步改架构文档 |
| 12 | api/memory.py 瘦身与去重 | P2 | M | 29 端点 + 650 行私有业务逻辑 + 5 连复制 |
| 13 | 记忆子系统统一领域模型 | P2 | L | 6 套并行表示，"融合排序"是列表拼接 |
| 14 | settings 服务 4 份同构 CRUD 合并 + 别名 URL 收敛 | P2 | M | 1262 行里 400+ 行是复制 |
| 15 | App() 胖编排器拆分 + hooks 修正 | P2 | M | 58 个 hook、35 个 props、4 处依赖数组失真 |
| 16 | 检索模式口径统一 + 重依赖降级为可选 | P2 | S | 代码默认 hybrid 与文档"FTS 默认"打架；qdrant/kuzu 是硬依赖 |
| 17 | 评测口径与简历措辞对齐 | P3 | M | n-gram 哈希不能支撑"semantic"结论 |
| 18 | 命名统一（一个项目四个名字） | P3 | S | agentproject / Agent Pet / agentpet / 桌面记忆助手 |
| 19 | Electron/前端杂项打磨 | P3 | M | CSP、窗口工厂去重、hash 路由约定等 |
| 20 | 仓库卫生速修包 | P3 | S | .gitignore 坏行、遮蔽、未钳制 limit 等一小时级修复 |

---

## P0：本周修（主路径正确性）

### 1. 流式回复逐 token 写库

- **问题**：每收到一个 token 就 `_update_assistant_message`：新建连接 → 全文 `UPDATE` → `commit`，且在事件循环线程上同步执行。长回复产生 O(n²) 字符拷贝与每 token 一次 fsync，阻塞进程内所有 SSE 流。
- **证据**：`apps/backend/app/api/chat.py:350-353`、`:635-641`。
- **修法**：节流落库（每 200ms 或每 50 token 二者先到），流内复用同一连接；终态（完成/失败/取消）立即强制落一次。配合 #2 的连接管理。
- **验收**：一条 800 token 回复期间 `messages` 表写入次数 ≤ 20；并发两条 SSE 互不卡顿；杀进程后重启，最后一条消息状态不是 RUNNING/PARTIAL 悬空。

### 2. SQLite 连接从不关闭 + 无超时参数

- **问题**：`sqlite3` 的 `with conn` 只 commit 不 close，全项目 `with database(request).connect()` 无一显式关闭（api/memory.py 8 处、api/chat.py 6 处均无 `close()`）；`connect()` 无 `timeout`、无 `busy_timeout`，WAL 写竞争 5 秒即抛 `database is locked`。
- **证据**：`apps/backend/app/storage/database.py:20-26`；泄漏调用面见 `api/chat.py:110/228/311/625/636/648` 等。
- **修法**：`Database` 增加 `@contextmanager def session()`（负责 close、设置 `timeout` 与 `PRAGMA busy_timeout`），全仓把 `connect()` 调用点替换为 `session()`。`journal_mode=WAL` 是持久属性，移到初始化时设置一次，别每条连接重设。
- **验收**：跑一轮完整测试后 `lsof`/handle 数不随请求数增长；grep 全仓无裸 `connect()` 调用点（白名单除外）。

### 3. SettingsStore 绕开 Database，丢失 PRAGMA 与外键约束

- **问题**：`SettingsStore` 自己 `sqlite3.connect(db)`，没有 `foreign_keys=ON`（SQLite 外键是 per-connection 的）、没有 row_factory 统一；同库两种完整性语义。且每次构造都执行 `_run_data_migrations()`，而 chat 路径每条消息构造一次。
- **证据**：`apps/backend/app/services/settings.py:233`、`:241`；对照 `storage/database.py:22-26`；调用频率见 `api/chat.py:204`。
- **修法**：SettingsStore 改走 `Database.session()`；`_run_data_migrations` 移到应用启动的迁移阶段，只跑一次。
- **验收**：对 settings 相关表做一次违反外键的写入应报错；每条聊天消息不再触发 `sqlite_master` 探测（可用 SQL trace 验证）。

### 4. Electron 代理白名单缺 18 条后端路由（含 5 兄弟路由漏 1）

- **问题**：`proxy.js` 手写 61 条正则。`memory graph facts` 的 confirm/wrong/archive/sensitive-block 放行了，唯独漏 `reject`；另有 diary search/detail、feedback、hygiene preview/actions、chat 流别名、embedding 与 agent-model 系列共 18 条被拦。前端 `types.ts` 已为其中多数写好类型，调用即 `renderer_api_route_not_allowed`。这与 case-study 里记录过的 checkpoint 白名单事故同因。
- **证据**：`apps/desktop/electron/proxy.js:78`（`(confirm|wrong|archive|sensitive-block)`）；缺失路由对照 `api/chat.py:297/302`、`api/memory.py:158/183/390/454/691/704`、`api/settings.py:291/323/350/436/451/463/489/540/549/581`。
- **修法**：先手工补齐 18 条止血；根治见 #9。
- **验收**：为白名单增加"逐条后端路由 ∈ 清单 ∪ 显式豁免表"的测试（negative + positive），当前 18 条全部通过。

### 5. 后台任务无强引用 + 关键路径异常静默

- **问题**：`asyncio.create_task` 后只挂 done_callback，不持有强引用，任务可能被 GC 中途回收（表现为偶发记忆归档丢失）；continuity 提案生成 `except Exception` 只留 warning 且无 `exc_info`；`confirm_proposal` 失败被静默当作"未确认"继续执行，无日志。
- **证据**：`api/chat.py:487`、`:561-567`、`:580-582`。
- **修法**：模块级 `set` 持有任务引用，done 时移除；两处静默捕获补 `logger.exception`/`exc_info=True`，confirm 失败走显式失败分支。
- **验收**：注入异常的测试能在日志中看到堆栈；压测下归档任务完成数 == 提交数。

---

## P1：1–2 周（可交付性 + 防再犯）

### 6. 打包不含 Python 运行时（"桌面应用"目前不成立）

- **问题**：`extraResources` 拷贝后端源码并排除 `.venv`，sidecar 从用户 PATH 裸拉 `python`/`python3` 起 uvicorn；`win.target` 只有 dir/zip，无安装器。用户拿到 zip 需要自备 Python + 全部依赖（含 qdrant-client、kuzu）。失败提示引导用户"检查控制台日志"，而打包 GUI 没有控制台（stdio 为 inherit，不落文件）。
- **证据**：`apps/desktop/package.json:57-78`；`apps/desktop/electron/sidecar.js:283-296`、`:300`、`:337`。
- **修法**（三选一，按投入排序）：a) Windows embeddable Python + 预装依赖打进 resources；b) PyInstaller 把后端冻结成单 exe；c) 最低限度——README 顶部醒目声明前置要求 + 启动时检测并给出可操作的报错。无论选哪个：后端 stdout/stderr 落日志文件，失败提示指向该文件路径。
- **验收**：一台没有 Python 的干净 Windows 虚拟机上，解压（或安装）后双击可用；启动失败时用户能找到日志文件。

### 7. 桌宠命中框零 DPI 处理

- **问题**：命中判定把 `getCursorScreenPoint()`（DIP）、`getBounds()`（DIP）与 `pet-hitbox.json` 的 CSS px 常量直接混算，四个 Electron 文件搜不到 `scaleFactor`。目标平台仅 Windows，而中文笔记本默认 125%/150% 缩放。另外 `createCenteredPetHitRect` 把"水平居中、底部对齐"的布局假设硬编码在主进程，渲染层改布局会静默错位。
- **证据**：`apps/desktop/electron/windows.js:232-239`、`:241-271`。
- **修法**：用 `screen.getDisplayMatching(petWindow.getBounds()).scaleFactor` 参与换算；把布局锚定方式写进 `pet-hitbox.json` 由两端共同消费（几何单一来源这点已做对，补上布局假设即可）。
- **验收**：100%/125%/150%/200% 四档缩放 + 跨屏拖动下，命中区与可见桌宠逐像素对齐（可写一个渲染端描边调试开关人工核验）。

### 8. sidecar 生命周期三连

- **问题**：a) `child.kill()` 默认 SIGTERM、无超时无升级、无进程组，Windows 上杀不干净 uvicorn 树 → 8765 残留占用 → 下次启动 `PORT_IN_USE`；b) 端口 8765 硬编码，仅检测不搜索，且检测到 spawn 之间有 TOCTOU 窗口；c) 复用陌生后端时 `state: "ready"` 与非空 `error` 同置（错误文案自己承认会 401），前端 `hasConnection` 据此认为一切正常；d) 30 秒就绪死线硬编码，冷启动超时会把正在启动的后端杀掉；e) `deliveredReminderNotifications` 只增不清的无界 Set。
- **证据**：`sidecar.js:411-413`、`main.cjs:13`、`sidecar.js:117-135`、`:243-251`、`:138`、`:12/:98`；前端判定 `src/App.tsx:1171`。
- **修法**：Windows 用 `taskkill /pid /T /F` 或 spawn 时建 Job Object；端口探测失败时向上搜索备选并通过环境变量传给前后端；复用外部后端定义为独立状态 `degraded` 而非 `ready`；就绪超时可配置且超时不主动杀（给出"继续等待/重试"选择）；Set 加上限或按日清理。
- **验收**：连续启动-退出 20 次无残留 python 进程、无端口占用报错；8765 被外部进程占用时应用仍能启动。

### 9. 单一事实来源：openapi.json 生成白名单与前端类型 + CI 断言

- **问题**：同一份路由事实手工维护了三处——后端装饰器、proxy 61 条正则、`types.ts` 手抄的 208 个类型（其中 32 处 `status: string` 裸奔，字面量联合仅 8 处）。三处互不校验，#4 的 18 条缺口就是这么长出来的，也必然再长。
- **证据**：`proxy.js:56-123`；`src/types.ts`（208 个 `export type`，零 codegen 标记）。
- **修法**：FastAPI 自带 `/openapi.json`：a) `openapi-typescript` 生成 types，手写类型逐步迁移；b) 由 openapi 生成白名单数据文件（配一张显式豁免表：确不该暴露给渲染进程的路由）；c) CI 增加断言"后端路由 ⊆ 白名单 ∪ 豁免表"。
- **验收**：新增一个后端路由但不登记 → CI 红；`status` 枚举后端改名 → 前端 typecheck 红。

### 10. 让质量闸门真的闸

- **问题**：CI 的"类型检查"步骤中 mypy 配置为 `ignore_errors = true` + `follow_imports = "skip"`——按构造不可能失败；ruff 仅 `select = ["E9","F63","F7","F82"]`，只等于"能 parse"。与项目大张旗鼓的 verification 体系形成直接反差。
- **证据**：`apps/backend/pyproject.toml:36`、`:41-48`；`.github/workflows/ci.yml:32-37`。
- **修法**：mypy 去掉 `ignore_errors`，改为按模块渐进收紧（先 `app/storage`、`app/models` 等叶子模块清零，用 per-module override 白名单存量豁免）；ruff 扩到默认规则集 + `B`（bugbear）+ `A`（builtins 遮蔽，直接抓 #20 的 `status` 问题），存量用 `--add-noqa` 冻结后禁止新增。
- **验收**：故意引入一个类型错误/一处变量遮蔽，CI 必须红。

### 11. 死代码了断：supervisor / reviewer / 角色契约体系

- **问题**：`use_supervisor`、`use_parallel_supervisor`、`use_reviewer` 三个开关在设置存储、API、前端类型中均不存在，`getattr` 默认 False → 永久不可达；即便打开，`_supervisor_role_handlers()` 返回空字典、默认 registry 全部 handler 抛 `NotImplementedError`。受牵连的死重：7 个角色 ×9 项预算配置（registry.py 126 行）、contracts.py 约 30 个类中服务于此路径的大半、11 个从未接通的 `AgentToolId`、全 `Literal` 写死的 `GlobalExecutionBudget`。`verified-system.md` 仍把 Supervisor/Reviewer 画在"已验证架构"里。
- **证据**：`graph_runtime.py:737-753`、`:696-697`、`:600-601`；`registry.py:174-181`、`:284-410`；`contracts.py:23-30`、`:33-44`、`:504-517`；`docs/architecture/verified-system.md`。
- **修法**：二选一并执行到底。**推荐删**：移除三开关、supervisor/reviewer 图、7 角色配置、配套契约类与 `AgentToolId`，架构文档改为只描述真实运行的路径（fast path + negotiation）；简历/文档措辞同步收窄。若选接通：补 DB 列 + API + UI + 绑定真实 role handler + 至少一条端到端测试，工作量按 L 计。
- **验收**：删——`grep -r "use_supervisor\|use_reviewer\|IndependentAgentRoleId"` 零命中，测试全绿，架构文档与代码一致；接通——UI 打开开关后能观测到 supervisor 路径真实执行并产出。

---

## P2：一个月内（架构收敛）

### 12. api/memory.py 瘦身

- **问题**：1657 行、29 个端点，其中 650 行是私有业务逻辑（如 72 行的 `_apply_profile_action_to_target` 做完整编排；周回顾端点手写裸 SQL + 内存归并）。5 个 graph fact 动作端点逐字复制且枚举/字符串混用（`"active"`/`"rejected"`/`MemoryFactStatus.WRONG` 混在同构代码里）；同一组 action 的映射表重复 4 份，错误行为还不一致（一处 `KeyError`、三处静默降级）；端点直接 `await` 另一个端点导致同一操作双份审计。
- **证据**：`api/memory.py:374-451`、`:609-638`、`:1161/:1298/:1309/:1320`、`:662`、`:1224-1295`。
- **修法**：5 连击合并为一个参数化端点（action 枚举校验 + 单一映射表）；私有逻辑下沉到对应 service；按 graph/profile/diary/proposal 拆成 4 个 router；handler 间复用抽成 service 函数，审计只记一次。
- **验收**：api/memory.py ≤ 400 行；`grep -c "def _"` 接近 0；审计流中同一操作只出现一条。

### 13. 记忆子系统：从 6 套表示走向统一模型

- **问题**：diary object / graph fact / candidate / proposal / profile projection / companion consolidation 六套并行表示互不隶属，`/memory/search` 只能手工缝三条检索路径，"融合排序"实为 diary 无条件置顶 + 列表拼接截断（score 被忽略，`top_k` 可能被单一来源吃光）；"lifecycle"抽象对 fact 类型有绕过分支；同文件存在 5 种连接/服务获取方式，甚至要求调用方知道 service 内部还持有 graph_store 去手动双重 close。
- **证据**：`api/memory.py:120-155`（含 `:154` 拼接）、`:1243` 与 `:1235` 的并列分支、`:568-569`。
- **修法**：先别拆表——定义统一的 `MemoryItem` 读模型（id/kind/status/score/provenance），三条检索路径各自产出该模型后做真正的分数融合（可复用现成 RRF）；状态迁移收敛进 lifecycle 单一入口，fact 特例内化为策略而非调用方分支；资源获取统一为 `Depends` 一种。
- **验收**：`/memory/search` 中不再出现列表拼接排序；新增一种记忆类型只需实现读模型适配器，不改 API 层。

### 14. settings 服务与 API 去重

- **问题**：model/embedding/tts/agent 四份 key/config CRUD 逐行同构（约 400+ 行可归约）；4 个 `credential_ref_for_*`；API 层同一功能最多 4 个 URL（装饰器叠放 + 遗留别名只加不删）。另有三处密钥落地问题：非 Windows"加密"实为 base64 且靠环境变量放行、文件后缀 `.secret` 误导；加密方式按当前平台推断而非随文件自描述（跨平台迁移后静默报"未配置"）；masked 值被存进未加密的 `app_state` 表。
- **证据**：`services/settings.py:441-507/561-651/766-875`、`:1168-1186`、`:197-198`、`:213-223`、`:458-465`；`api/settings.py:462-463/488-489/540/549`。
- **修法**：抽 `CredentialSlot(table, ref_builder)` 参数化四份 CRUD；别名 URL 标记 deprecated 并在下个版本删除；凭据文件头部写入 `scheme=dpapi|plain` 自描述，明文方案后缀改 `.plaintext`；masked 展示值即算即用，不落库。
- **验收**：services/settings.py ≤ 700 行；每个功能恰好 1 个 URL；把 vault 从 Windows 拷到 mac，密钥状态报"平台不支持"而非"未配置"。

### 15. App() 胖编排器与 hooks 修正

- **问题**：单函数 58 次 hook 调用（22 useState/14 useEffect/11 useRef/11 自定义）+ 24 个内联函数；`useWiki` 解构 40 字段再原样拼回 40 字段传下去；`ControlDashboard` 35 props、`PetWindow` 30 props；4 处 useEffect 依赖数组失真（`loadContinuity` 等每渲染新引用却不在依赖里）；3 处 render 阶段副作用（ref 赋值、命令式 bind）；`pendingSettingsStatusVersion` 计数器是绕开设计缺陷的补丁；破坏性操作用 `window.confirm`。
- **证据**：`src/App.tsx:122-160`、`:298-349` 与 `:1292-1339`、`:1518-1579`、`:440-465/:823-830`、`:233/:246/:387`、`:128/:191-194/:412-419`、`:852/:1093`。
- **修法**：按域拆 3–4 个 Provider/Context（chat、pet、wiki、settings），`workflow` 对象直接由 `useWiki` 返回整体透传；开启 `eslint-plugin-react-hooks` 的 `exhaustive-deps` 并清零；render 副作用移入 effect；confirm 换应用内对话框。
- **验收**：App() ≤ 300 行且 hook 调用 ≤ 15；`exhaustive-deps` 零告警；任何子组件 props ≤ 12。

### 16. 检索口径统一 + 重依赖可选化

- **问题**：`RetrievalService.search` 默认参数 `mode="hybrid"`，与文档"FTS 是生产默认 / hybrid 未过闸（无证据准确率 0.000）"直接矛盾（agent 工具路径已硬编码 fts，API 路径取决于请求模型默认值）；`qdrant-client`、`kuzu` 是所有用户的硬依赖，却服务于未上线通道；每次向量查询在锁内做全集合 O(N) 扫描 + 逐条 SHA-256 校验。
- **证据**：`services/retrieval.py:136`；`pyproject.toml:16-19`；`services/vector_index.py:391/:400/:809-845`。
- **修法**：默认参数改 `"fts"`，hybrid 走显式 opt-in；qdrant/kuzu 移入 `[project.optional-dependencies] vector`，缺失时优雅降级（现有 health 探测已具备条件）；全量校验改为启动时/代次切换时一次 + 查询时抽样或基于 generation 戳的增量校验。
- **验收**：全新安装不带 vector extra 时功能完整、测试绿；开 vector 后单次查询 p95 不随集合大小线性增长。

---

## P3：打磨与口径

### 17. 评测与对外措辞对齐

- **问题**：104KB/2435 行自建评测框架里，"向量"是字符 n-gram 哈希（`deterministic-local-feature-hash-v1`），"keyword-free" 切片仅排除 ASCII 词重叠，中文 2/3-gram 照样命中——`+0.226667` 不能支撑"semantic"表述；reranker 实验对象是恒等函数（配 10000 次 bootstrap 得出 delta 0.000）；83 行 grounding 评分因 `observations=()` 从未执行；闸门要求 `no_evidence_accuracy ≥ 1.0` 且恒等 reranker 被判 adopt，按构造不可通过。核心实测数字（FTS Recall@10 0.496）本身也偏弱。
- **证据**：`evals/retrieval_eval.py:137/:1051-1071/:1384-1394/:2283/:227-229/:1196-1246/:616/:886/:1249/:60/:939-943`；数字见 `docs/portfolio/claim-evidence-index.md`。
- **修法**：措辞把"semantic delta"改为"词法/字符级检索对比基准"（报告内部其实已经写了实话，把对外文档拉齐即可）；要么接入真 embedding 模型重跑并重新谈 semantic，要么删除该措辞；恒等 reranker 实验从结论区移除；闸门阈值改为可达成的目标或明确标注 aspirational；顺手清理两对逐行复制的报表/校验函数。
- **验收**：portfolio 文档中每条量化宣称都能指到一个真实执行过的代码路径。

### 18. 命名统一

- **问题**：仓库 `agentproject`、README "Agent Pet"、CI 徽章 `gitagin/agentpet`、打包 productName "桌面记忆助手"——四个名字。
- **修法**：选定一个（建议 Agent Pet），仓库名、badge、productName、appId 一次改齐。工作量 S，但涉及 electron-builder 的 appId/产物名，改完跑一次打包验证。

### 19. Electron / 前端杂项

- **修法合集**（各自独立、可穿插进行）：a) 增加 CSP（`onHeadersReceived` 或 index.html meta）；b) 4 个窗口工厂与 `webPreferences` 提取公共构造器（消除 5 份复制，防"第 6 个窗口忘一行"）；c) `createControlWindow` 补 `isDestroyed()` 检查（与其余 3 处对齐，现状可致 `window.show()` 抛异常）；d) hash 路由统一约定（现存 `"pet"`/`"stage"`/`"/stage"` 三种写法，control 窗口加载的还是 stage）；e) 复用窗口切路由统一走 IPC，废除整页 reload 丢状态的分支；f) `will-navigate` 用 `new URL()` 比较 origin 而非 `startsWith`；g) 令牌比较改 `secrets.compare_digest`（后端 `auth.py`）；h) `retryableMethods` 里永远走不到的 `HEAD`、`attempts=12×delay(250)` 魔法数、`activeSseStreams` 不随窗口关闭清理——一并处理；i) 拖拽 16ms 主进程轮询与 80ms 常驻 hit-test 的耗电代价写进文档或降频。
- **证据**：`windows.js:517-520 等 5 处/:596-598/:567,639,688,725,805/:867-883 vs :769-773/:164/:980/:404-414`；`proxy.js:3/:166/:187/:211/:2`；`apps/backend/app/auth.py:19`。

### 20. 一小时级速修包（可今天顺手清掉）

| 修复 | 位置 |
| --- | --- |
| .gitignore 尾部两行带引号的字面 pattern（`""`、`"# Local agent..."`）删除 | `.gitignore:73-74` |
| 查询参数 `status` 遮蔽 `fastapi.status` 导入，重命名参数 | `api/memory.py:320/:336/:1446` |
| 三处未钳制的 `limit`（graph facts / export-preview / companion reports）加上限 | `api/memory.py:322/:338/:588` |
| `describeError` 双调用 + map 参数遮蔽外层 `message`，重命名 | `src/App.tsx:654-658` |
| 超时魔法数收敛为命名常量（12000/14000×3/10000/5000/11000） | `src/App.tsx:243/525/554/569/668/1021/1194` |
| 硬编码时区 `"Asia/Shanghai"` ×2 提取常量并允许跟随系统 | `src/App.tsx:99/:101` |
| 语义重复常量二合一（两个 200 上限） | `src/App.tsx:85-86` |
| `min(max(top_k * 4, 8), 40)` ×3 提取函数 | `services/retrieval.py:190/229/243` |
| `_MAX_NEGOTIATION_ROUNDS=2` 与 `max_planning_rounds: Literal[2]` 双处硬编码合一 | `graph_runtime.py:55` / `contracts.py:506` |
| 工具 schema 声明 `mode` 参数却被硬编码覆盖——从 schema 删除该参数 | `agents/tools.py:135-144/:379` |
| 未知 agent id 被静默记成 ORCHESTRATOR 的遥测改写，改为记 `unknown:<raw>` | `graph_runtime.py:1318-1330` |
| 隐私模式下检索异常被伪装成"0 条结果"，区分错误与空 | `graph_runtime.py:223-226` |
| `candidate_filter` 抛异常静默当"不允许"，补日志 | `services/retrieval.py:622-625` |
| 迁移器每次新迁移全库 `VACUUM`，改为显式维护命令 | `storage/database.py:83` |

---

## 建议执行顺序

1. **第 1 周**：#1–#5（P0 全部）+ #20 速修包。改动都小，收益立竿见影，且 #2 是 #1/#3 的地基，先做 #2。
2. **第 2–3 周**：#9（openapi 单一事实来源）先行——它决定 #4 的根治方式，也免得 #12/#15 重构时又手抄一轮类型；随后 #10（真闸门），让后面所有重构有回归保护；然后 #6（打包）与 #11（死代码了断），这两项决定对外叙事。
3. **第 4 周起**：#7、#8 收尾交付质量；#12–#16 按依赖顺序做（#13 依赖 #12 先把逻辑沉回 service）。
4. **随时**：#17、#18 在下一次更新简历/README 前完成即可，但**在 #11 完成前不要对外使用现有的多 Agent 措辞**。

一个提醒：P2 的每一项动手前，先确认 #10 的闸门已经收紧——在 mypy 静音、lint 只查语法的状态下做大重构，等于摸黑搬家。
