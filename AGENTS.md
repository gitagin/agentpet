# AGENTS.md

本文件给在本仓库根目录工作的编码 Agent 使用。除非子目录里存在更近的 `AGENTS.md`，否则这些约定适用于整个仓库。

## TL;DR

1. 不要修改 `node_modules/`、`dist/`、`release/`、`*.db`、`logs/` 等生成物或本地状态文件。
2. 实现没验证就不要把状态改成 `Covered`。
3. 回复里必须列出所有实际运行过的命令和结果。
4. 私人桌宠默认低风险自动整理；高风险 Vault/Markdown/状态操作必须确认，且确认不可关闭。
5. Renderer 能力只走 contextBridge IPC，不得直接调用 Node/FS。

## 项目概览

Agent Pet 是本地优先的 Windows 桌面 AI 伴随应用，使用 Obsidian/Markdown Vault 与 SQLite 保存可审计长期记忆。

| 模块路径 | 职责 |
| --- | --- |
| `apps/backend` | Python FastAPI sidecar，负责 API、SQLite、FTS5、Agent runtime、记忆、任务、Wiki 工作流 |
| `apps/backend/app/api` | FastAPI 路由，除 health 外统一受 bearer token 保护 |
| `apps/backend/app/agents` | LangGraph Agent runtime、意图、事件、工具适配 |
| `apps/backend/app/services` | 业务服务：检索、记忆、Wiki、任务、设置、审计、模型调用 |
| `apps/backend/app/storage` | SQLite 连接、Vault 路径校验、Markdown 读写 |
| `apps/backend/migrations` | SQLite schema migration，按文件名顺序执行 |
| `apps/backend/tests` | 后端 pytest 契约、持久化、安全、Agent、Wiki 测试 |
| `apps/desktop` | Electron + React + TypeScript + Vite 桌面端 |
| `apps/desktop/electron` | Electron main/preload、sidecar 管理、窗口、托盘、IPC |
| `apps/desktop/src` | React 控制台、桌宠 UI、API/SSE/Live2D 服务 |
| `apps/desktop/public/live2d` | 开发期 Live2D 资源与 Cubism SDK |
| `apps/desktop/scripts` | Electron、Live2D、气泡、打包校验脚本 |
| `scripts` | Windows PowerShell 启动、预检、smoke、验收脚本 |
| `docs` | runbook、验收矩阵、安全审查、迁移说明 |

## 事实来源

1. `apps/backend`、`apps/desktop` 当前代码 — 最高 — 运行时行为由入口、路由、服务、Electron main/preload 与测试直接定义
2. `apps/backend/migrations` — 最高 — SQLite schema 由 migration 文件与 `schema_migrations` 表共同定义
3. `apps/backend/tests`、`apps/desktop/scripts` — 高（客观） — 自动化测试和校验脚本体现当前契约，跑过即 Covered
4. `docs/mvp-acceptance-coverage.md` — 高（人工） — 记录 `Covered` / `Partial` / `Gap` 边界；与测试结果冲突时以测试为准
5. `docs/runbook.md`、`docs/v0.1-validation.md` — 中高 — 记录 Windows 试运行命令、环境变量和受限环境坑
6. `progress.md` — 中 — coordinator 进度日志可能落后于代码，使用前要核对当前实现与校验输出
7. `Development_Documentation.md` — 中低 — 原始工程规格存在中文 mojibake 和历史阶段内容
8. `README.md` — 中低 — 只给出项目定位和模块摘要
9. 当任何文档与当前代码冲突时，以代码为准

## 工作环境

- Shell：Windows PowerShell
- 工作目录：仓库根目录
- Git：不要假设 Git 一定可用；使用 Git 状态前先检查当前工作区，且不要只依赖 `git status`、`git diff`、`git history` 判断状态

禁止修改的路径列表：

- `apps/desktop/node_modules/` （原因：依赖安装目录，手工编辑会污染可复现构建）
- `apps/desktop/dist/` （原因：Vite 构建产物，内容由 `npm run build` 生成）
- `apps/desktop/release/` （原因：electron-builder 输出目录，内容由打包命令生成）
- `pytest-of-*/` （原因：pytest 临时数据库与测试工件，手工编辑不能修复源代码问题）
- `.tmp/` （原因：本地 smoke 和手工试运行临时状态，内容可被脚本重建）
- `.idea/` （原因：本地 IDE 配置，不属于运行时行为）
- `.codex/` （原因：本地 Agent 元数据，项目逻辑不读取它）

### 已知环境坑

- 当前 checkout 的 Git 可用性以当前工作区检查结果为准 （原因：状态判断要依赖文件检查、测试、进度日志，不能只依赖 Git 历史）
- PowerShell 可能出现 `[Console]::OutputEncoding` / ConstrainedLanguage 警告 （原因：该运行环境限制控制台编码设置，命令退出码和实际输出才是判断依据）
- `Development_Documentation.md` 存在中文 mojibake （原因：补丁要锚定 ASCII 或当前可读片段，避免破坏周边内容）
- `npm run build` 在 Codex sandbox 里可能报 Vite/esbuild `spawn EPERM` （原因：受限环境阻止子进程生成，不等同于源码错误，普通 Windows PowerShell 复跑确认）
- `progress.md` 可能滞后于代码 （原因：实现文件和测试会先变化，进度日志只由 coordinator 追加）

## 后端约定

### 入口与结构

- 入口文件：`apps/backend/app/main.py`
- 路由目录：`apps/backend/app/api`
- 路由聚合：`apps/backend/app/api/__init__.py`
- 模型目录：`apps/backend/app/models`
- 服务目录：`apps/backend/app/services`
- 存储目录：`apps/backend/app/storage`
- migration 目录：`apps/backend/migrations`

### 数据库

改 schema → 新增 `apps/backend/migrations/NNN_description.sql`、更新模型/仓库/服务、增加 pytest 覆盖、运行 `python -m pytest -q` （原因：`MigrationRunner` 按文件名顺序执行 SQL 并写入 `schema_migrations`，跳过任何一步会导致本地状态文件与代码不兼容）

### 网络

- Sidecar 不得监听 `0.0.0.0` （原因：本地 bearer token、Vault 文件访问和 Electron sidecar 模型只面向本机，公网暴露等同于无认证访问）
- Electron 管理的后端端口固定为 `127.0.0.1:8765` （原因：`apps/desktop/electron/main.cjs` 以该地址做健康检查和 API 转发）
- Vite 开发服务器使用 `127.0.0.1:5173` 起步 （原因：CORS 只允许本地开发源和 `file://` 桌面源）

### 环境变量

```text
AGENT_PET_SESSION_TOKEN       # required  — 受保护 API 的本地 bearer token
AGENT_PET_DATA_DIR            # optional  — 默认 SQLite 和图存储所在目录
AGENT_PET_SQLITE_PATH         # optional  — 指定隔离 SQLite 文件
AGENT_PET_MODEL_BASE_URL      # optional  — 开发期聊天模型 base URL 后备值
AGENT_PET_CHAT_MODEL          # optional  — 开发期聊天模型名称后备值
AGENT_PET_EMBEDDING_BASE_URL  # optional  — embedding 服务 base URL 后备值
AGENT_PET_EMBEDDING_MODEL     # optional  — embedding 模型名称后备值
AGENT_PET_EMBEDDING_DIMENSIONS # optional — embedding 向量维度
AGENT_PET_MODEL_TIMEOUT_SECONDS # optional — 模型调用超时秒数
AGENT_PET_BACKEND_DIR         # optional  — Electron sidecar 后端目录覆盖
AGENT_PET_PYTHON              # optional  — Electron sidecar Python 可执行文件覆盖
AGENT_PET_DEBUG_HITBOX        # optional  — 桌宠命中区域调试开关
LIVE_MODEL_BASE_URL           # optional  — live model acceptance gate 的 provider base URL
LIVE_CHAT_MODEL               # optional  — live model acceptance gate 的聊天模型名
LIVE_MODEL_API_KEY            # optional  — live model acceptance gate 的 provider key
```

### Fallback 原则

- 向量索引或图镜像不可用 → 保留 SQLite、FTS5、Markdown Vault 主路径 （原因：Qdrant/Kuzu/embedding 是加速镜像，不是用户可见真相，缺失不得导致核心启动失败）
- 模型 key 未配置 → 后端不创建 live model client，保留检索、任务、记忆和 fake-runtime 测试路径 （原因：本地开发和验收不能被外部 provider 阻塞）
- 未设置 `AGENT_PET_SQLITE_PATH` → 使用 `AGENT_PET_DATA_DIR\agent_pet.sqlite3` （原因：Electron 管理 sidecar 时会把状态固定到 userData）
- `127.0.0.1:8765/api/health` 已响应 → Electron 可复用现有后端 （原因：避免重复启动 sidecar；若 protected API 401，重启使 token 一致）

## 前端/桌面端约定

### 入口与结构

- Electron main：`apps/desktop/electron/main.cjs`
- Electron preload：`apps/desktop/electron/preload.cjs`
- 开发启动器：`apps/desktop/electron/dev.mjs`
- React 入口：`apps/desktop/src/main.tsx`
- 主 UI：`apps/desktop/src/App.tsx`
- API 客户端：`apps/desktop/src/services/apiClient.ts`、`apps/desktop/src/services/desktopApi.ts`
- SSE 客户端：`apps/desktop/src/services/sse.ts`
- Live2D runtime：`apps/desktop/src/services/live2dRuntime.ts`
- 桌宠命中区域：`apps/desktop/pet-hitbox.json`

### 权限边界

- Renderer 不得直接调用 Node、FS、`child_process` API，所有桌面能力必须通过 contextBridge IPC 暴露 （原因：防止 renderer 进程越权访问本地文件和启动进程）
- Renderer 不得读取或暴露 `AGENT_PET_SESSION_TOKEN`、`Authorization`、`Bearer` 字符串 （原因：session token 只属于 Electron main 与后端进程边界）
- Preload 不得导入 `fs` 或 `child_process` （原因：preload 只暴露最小 `contextBridge` IPC 能力）
- Renderer 不得使用 `localStorage` （原因：Electron 迁移校验禁止持久化状态绕过 main/preload 管理）
- Electron `webPreferences` 不得关闭 `contextIsolation`、`sandbox`、`webSecurity` 或打开 `nodeIntegration` （原因：这些开关是 renderer 权限隔离基线，关闭任何一项等同于取消沙箱）
- 外部 URL 不得从 renderer 直接打开 （原因：跳转和外链必须经过 Electron main 的窗口与导航控制）

### UX 约束

- 桌宠气泡命中区是 `214x58`，位置来自 `apps/desktop/pet-hitbox.json` （原因：当前 UI 和验证脚本围绕紧凑气泡设计）
- 长回复通过 `petBubblePagination.ts` 做语义分页 （原因：当前实现保留完整回复，同时只在紧凑气泡中展示当前页）
- 输入区默认隐藏，通过双击桌宠打开 （原因：`App.tsx` 的桌宠交互把输入 dock 作为显式唤起面板）
- 等待/状态文本与实际 streamed reply 分离 （原因：SSE 生命周期要区分请求状态、工具事件、token、done）
- 桌宠点击穿透要遵守 `pet-hitbox.json` （原因：Electron `setIgnoreMouseEvents(..., { forward: true })` 依赖命中区域）

### 构建限制

- ⚠ `npm run build` 在 Codex sandbox 中出现 Vite/esbuild `spawn EPERM` 时，用普通 Windows PowerShell 复跑同一命令 （原因：sandbox 子进程限制会误报构建失败，不代表源码有问题）
- 不得手工编辑 `apps/desktop/dist/` （原因：生产 renderer bundle 必须由 `npm run build` 生成）
- 不得把 SQLite、`.db`、`.sqlite3` 打进桌面包资源 （原因：`validate-electron-packaging.mjs` 校验后端资源过滤规则）
- `node scripts/validate-electron-migration.mjs` 不得失败后继续提交 Electron 权限改动 （原因：该脚本保护 `localStorage`、preload、token、webPreferences 基线）

## 数据与存储

### 写入安全边界

- 默认产品方向是私人桌宠自动整理模式：普通聊天只需要用户输入自然语言；低风险日记归档、结构化日记、长期记忆、Wiki 新建/补充/归档/报告和低风险体检报告可以自动执行并记录到 `agent_actions` 活动账本。
- 普通聊天完成后应形成闭环：回答前按意图检索日记、长期记忆和 Wiki；回答后写每日聊天日记和结构化日记；高价值、非敏感、可复用的回答总结可自动沉淀到 `Wiki/Companion/Summaries/*.md`。
- 自动整理必须经过策略判定并产生可追踪记录：`action_type`、来源消息、风险级别、目标文件、摘要、状态、是否可撤销；可逆 Markdown 写入要保存回滚快照，撤销要生成新的活动记录。
- 自动 Wiki 写入仍受 Vault 路径安全限制：只能写 Vault 内 Markdown，Wiki 页面只能落在 `Wiki/*.md` 家族，不允许绝对路径、`..`、隐藏目录、symlink/reparse point 或越界路径。
- Wiki 知识页必须遵守维护契约：原始来源只读；保留 8 章模板；用 Obsidian 双链标明原文出处和触发来源；区分原文事实与整理推断；包含页面更新日志和 7 项自检；集中日志写入 `Wiki/log.md`；术语和格式陷阱由 lint 检查。
- 高风险或不确定操作必须取得用户确认后才能执行，确认开关不可关闭。

以下操作必须取得用户确认后才能执行：

- 初始化、绑定或切换真实知识库目录 （原因：会改变后端 active Vault）
- 删除、移动、批量重写 Vault Markdown、SQLite、migration 文件 （原因：这些操作有数据丢失或 schema 不兼容风险）
- 覆盖用户原文、执行不可逆大范围替换、批量清理 local-state/schema （原因：自动化策略不能代替用户对破坏性变更的授权）
- 写入或保存敏感凭据、API key、token、私钥或疑似 credential 内容 （原因：`memory_policy.py` 会判为敏感内容，不能进入普通记忆/Vault）
- 处理重大矛盾事实、身份/关系连续性、低置信度记忆提升或冲突合并 （原因：这些会影响桌宠长期人格/关系状态）
- 修改 SQLite schema （原因：schema 变化会影响已有本地状态文件）
- 运行会清理进程或端口占用的命令 （原因：可能终止用户正在使用的 uvicorn/Electron 进程）

### 核心文件路径

**关键入口**（优先验证）：

```text
apps/backend/app/main.py
  # 验证（PowerShell）：Test-Path apps/backend/app/main.py
  # 验证（bash）：test -f apps/backend/app/main.py
apps/desktop/electron/main.cjs
  # 验证（PowerShell）：Test-Path apps/desktop/electron/main.cjs
apps/desktop/electron/preload.cjs
  # 验证（PowerShell）：Test-Path apps/desktop/electron/preload.cjs
apps/backend/app/agents/graph_runtime.py
  # 验证（PowerShell）：Test-Path apps/backend/app/agents/graph_runtime.py
```

**服务与存储层**（以目录为单位验证，路径漂移时用目录确认模块存在）：

```text
apps/backend/app/api/
  # 验证（PowerShell）：Test-Path apps/backend/app/api
apps/backend/app/services/
  # 验证（PowerShell）：Test-Path apps/backend/app/services
apps/backend/app/storage/
  # 验证（PowerShell）：Test-Path apps/backend/app/storage
apps/backend/migrations/
  # 验证（PowerShell）：Test-Path apps/backend/migrations
```

**桌面 UI 与运行时**：

```text
apps/desktop/src/App.tsx
  # 验证（PowerShell）：Test-Path apps/desktop/src/App.tsx
apps/desktop/src/services/sse.ts
  # 验证（PowerShell）：Test-Path apps/desktop/src/services/sse.ts
apps/desktop/src/services/petBubblePagination.ts
  # 验证（PowerShell）：Test-Path apps/desktop/src/services/petBubblePagination.ts
apps/desktop/pet-hitbox.json
  # 验证（PowerShell）：Test-Path apps/desktop/pet-hitbox.json
```

**文档与进度**：

```text
docs/mvp-acceptance-coverage.md
  # 验证（PowerShell）：Test-Path docs/mvp-acceptance-coverage.md
progress.md
  # 验证（PowerShell）：Test-Path progress.md
```

> 以上路径以当前 checkout 为准，使用前先运行验证命令确认文件存在。

## 常用命令

### 测试

```powershell
Push-Location apps\backend; python -m pytest -q; Pop-Location
# 后端全量测试

Push-Location apps\backend; python -m pytest -q tests/test_wiki_workflows.py tests/test_wiki_services.py; Pop-Location
# Wiki 工作流聚焦测试

Push-Location apps\backend; python -m pytest -q tests/test_storage_paths.py tests/test_security_hardening_mvp.py; Pop-Location
# 路径安全与安全策略测试

Push-Location apps\backend; python -m pytest -q tests/test_live_model_chat_acceptance.py -m live_model; Pop-Location
# live provider 验收（需要 LIVE_* 环境变量）

Push-Location apps\desktop; npm run typecheck; Pop-Location
# 桌面端 TypeScript 检查
```

### 启动

```powershell
.\scripts\dev-backend.ps1 -Port 8765
# 启动 FastAPI sidecar

.\scripts\dev-frontend.ps1 -Port 5173
# 启动 Vite renderer

Push-Location apps\desktop; npm run electron:dev; Pop-Location
# 启动 Electron 桌面壳

.\scripts\check-trial-processes.ps1
# 检查 leftover uvicorn/Electron 与默认端口
```

### 构建

```powershell
Push-Location apps\desktop; npm run build; Pop-Location
# 生产 renderer 构建  # ⚠ 受限环境可能误报，普通终端复跑确认

Push-Location apps\desktop; npm run package:check; Pop-Location
# Electron 打包契约检查

Push-Location apps\desktop; npm run live2d:check:public; Pop-Location
# 开发期 Live2D 资源检查

Push-Location apps\desktop; npm run live2d:sdk:check; Pop-Location
# 开发期 Cubism SDK 检查

Push-Location apps\desktop; npm run live2d:check:dist; Pop-Location
# 构建后 Live2D 资源检查

Push-Location apps\desktop; npm run live2d:sdk:check:dist; Pop-Location
# 构建后 Cubism SDK 检查

Push-Location apps\desktop; npm run pet:bubble:check; Pop-Location
# 桌宠气泡分页契约检查
```

### 验收

```powershell
.\scripts\preflight-windows.ps1
# Windows 依赖、端口、进程、token 预检  # ⚠ 受限环境可能误报，普通终端复跑确认

.\scripts\runbook-smoke.ps1 -Port 8766
# 一键后端 smoke，自动启动并停止隔离 sidecar

.\scripts\check-mvp-acceptance-gap.ps1
# MVP 验收矩阵与实现信号一致性检查

.\scripts\smoke-backend.ps1
# 手工后端 smoke（需要已运行 sidecar）
```

## 验证原则

```
后端 Python 代码           → Push-Location apps\backend; python -m pytest -q; Pop-Location
后端 API/路由契约          → Push-Location apps\backend; python -m pytest -q tests/test_api_wiring_mvp.py tests/test_e2e_backend_mvp.py tests/test_security_contracts_api.py; Pop-Location
数据库 schema/migration    → Push-Location apps\backend; python -m pytest -q tests/test_persistence_mvp.py tests/test_api_wiring_mvp.py; Pop-Location
Vault/Markdown 路径安全    → Push-Location apps\backend; python -m pytest -q tests/test_storage_paths.py tests/test_storage_markdown.py tests/test_security_hardening_mvp.py; Pop-Location
Wiki 工作流                → Push-Location apps\backend; python -m pytest -q tests/test_wiki_workflows.py tests/test_wiki_services.py; Pop-Location
Agent runtime/检索路由     → Push-Location apps\backend; python -m pytest -q tests/test_agent_runtime.py tests/test_retrieval_fts.py tests/test_memory_graph_services.py; Pop-Location
桌面 TypeScript/React      → Push-Location apps\desktop; npm run typecheck; Pop-Location
Electron main/preload      → Push-Location apps\desktop; node --check electron/main.cjs; node --check electron/preload.cjs; npm run package:check; Pop-Location
Electron migration/state   → Push-Location apps\desktop; node scripts/validate-electron-migration.mjs; Pop-Location
Live2D assets/runtime      → Push-Location apps\desktop; npm run live2d:check:public; npm run live2d:sdk:check; Pop-Location
宠物气泡分页               → Push-Location apps\desktop; npm run pet:bubble:check; Pop-Location
端到端 smoke/验收文档       → .\scripts\check-mvp-acceptance-gap.ps1; .\scripts\runbook-smoke.ps1 -Port 8766
文档-only 状态变更          → .\scripts\check-mvp-acceptance-gap.ps1
任何改动                   → 在回复末尾列出所有实际运行过的命令和完整输出
```

## 进度记录

- 只有 Coordinator 角色有权写 `progress.md` （原因：该文件是 coordinator-owned，避免并发写入冲突）
- subagent 只读 `progress.md` 并向上汇报，不直接写进度文件 （原因：多 agent 并行时共享写入会覆盖或打乱状态）
- 新进度记录要包含 Agent 名称、状态、事实、验证命令和结果 （原因：后续状态审计依赖可追溯证据）
- 时间戳命令：`Get-Date -Format "yyyy-MM-dd HH:mm:ss K"` （原因：项目进度使用系统时区时间）

## 安全约束

### 禁止记录的内容

- `AGENT_PET_SESSION_TOKEN` 的真实值 （原因：该值可访问受保护本地 API）
- `Authorization: Bearer ...` 完整 header （原因：该 header 等同于本地 API 凭据）
- 以 `sk-`、`pk-`、`rk-`、`ghp_`、`gho_`、`ghu_`、`github_pat_`、`xoxb-`、`AKIA` 开头的 key/token （原因：`memory_policy.py` 将这些模式判为敏感凭据）
- `password=...`、`passwd=...`、`pwd=...`、`secret=...`、`token=...`、`api_key=...` 形式的赋值 （原因：这些赋值会被策略识别为 credential）
- `-----BEGIN ... PRIVATE KEY-----` 私钥块 （原因：私钥写入日志或 Vault 会造成凭据泄露）
- `apps/backend/**/*.credentials/*.dpapi` 文件内容 （原因：该目录保存本地 credential 服务密文）
- `LIVE_MODEL_API_KEY` 的真实值 （原因：live provider key 属于外部模型服务凭据）

### Vault 内部路径校验要求

以下限制仅针对 **Vault 内部 Markdown 文件访问**，不影响项目工作目录下的其他文件操作：

- 禁止把 Vault root 设为 UNC 或扩展 Windows 路径 （原因：`canonical_root()` 明确拒绝 `\\` 和 `\\?\` 前缀）
- 禁止使用绝对路径、盘符路径、`..`、`.`、隐藏目录、`.git`、`.obsidian`、短文件名样式路径访问 Vault 内部文件 （原因：`resolve_vault_path()` 只允许 Vault 内 `.md` 相对路径）
- 禁止通过 symlink 或 Windows reparse point 访问 Vault 内容 （原因：路径看似在 Vault 内但实际可跳出授权目录）
- 禁止把 Wiki 页面写到 `Wiki/` 之外 （原因：`resolve_wiki_path()` 将 Wiki 写入限定在 `Wiki/*.md`）
- 禁止把用户真实 Vault 当作 smoke `-WorkDir` （原因：smoke 会创建、写入、索引测试数据）

### 需要用户确认的操作

- 初始化、绑定或切换真实知识库目录 （原因：会改变后端 active Vault）
- 确认高风险或低置信候选长期记忆；普通高置信记忆默认进入自动整理与活动账本 （原因：私人桌宠不应让日常记忆都变成待审核提案）
- 应用高风险 Wiki ingest plan、破坏性 query archive、破坏性 synthesize 或 lint repair；普通低风险 Wiki 新建/补充/归档/报告默认可自动执行并可追踪/可撤销 （原因：普通整理不应打断对话，高风险写入仍需用户授权）
- 删除、移动、批量改写 Markdown、SQLite、migration 文件 （原因：这些操作有数据丢失或 schema 不兼容风险）
- 安装、升级、删除 Python 或 npm 依赖 （原因：会改变开发环境和可复现测试结果）
- 停止占用端口的非本次启动进程 （原因：可能终止用户正在使用的服务）

## 提交前自查

- [ ] 是否改动了禁止修改路径？→ 阻塞提交
- [ ] 是否改 schema 但没有新增 migration 和 pytest？→ 阻塞提交
- [ ] 是否改 Vault 内部文件写入路径但没有路径安全和活动账本/撤销测试？→ 阻塞提交
- [ ] 是否改 renderer 权限边界但没有运行 Electron migration 校验？→ 阻塞提交
- [ ] 是否把 `Covered` / `Partial` / `Gap` 写成未被证据支持的状态？→ 阻塞提交
- [ ] 是否只看 `progress.md` 而未核对当前代码？→ 阻塞提交
- [ ] 是否缺少手动 Electron 视觉验证？→ 记录 Partial Gap 后继续
- [ ] 是否有命令因 Codex sandbox `EPERM` 失败？→ 说明原因后继续
- [ ] 是否无法运行 live provider gate 因缺少 `LIVE_*` 环境变量？→ 记录 Partial Gap 后继续
- [ ] 是否在回复末尾列出了所有实际运行过的命令和完整输出？→ 阻塞提交
