# Agent Pet 项目深度评审报告

> 评审日期：2026-05-25 | 评审范围：`apps/backend` + `apps/desktop` + 工程基础设施 | 代码总行数：~25,000（不含 node_modules/vendor SDK）

---

## 一句话定性

**一个架构方向正确（本地优先、Vault/Markdown 记忆、Electron 桌面壳）、核心安全意识到位（DPAPI 加密、写策略、路径遍历防御），但正在被"上帝文件"膨胀、异常静默吞没、日志真空和重复实现侵蚀的 v0.2.0 原型——如果不从现在开始还技术债，6 个月后将无法安全迭代。**

---

## 最严重的问题（按危害程度排序）

### 1. [架构] App.tsx 是 2021 行的上帝组件，承载了所有跨切面状态

**文件**: [apps/desktop/src/App.tsx](apps/desktop/src/App.tsx)

**当前代码的问题**:
- 19 个 `useState` 调用管理核心状态（notice, conversationId, messages, streaming, diagnostics, agentActions, continuityProposals, windowMode 等）
- 10 个 `useEffect` 接线副作用
- `applyStreamEvent` 函数 267 行（第 583-850 行），内含 10+ 个 `if/else` 分支处理 SSE 事件分发：done、error、status、agent_action、continuity_signal、continuity_proposal、memory_proposal、wiki_proposals、task、token/citation 回退
- `sendChatText` 函数 145 行（第 373-518 行），内联数据库写入逻辑
- 6 个 feature hooks 全部在 App.tsx 中调用并解构，~80-100 个 props 通过 props drilling 向下传递

**为什么危险**: 新增任何一种事件类型（例如新的 Agent Action 或 Wiki 工作流步骤）都需要修改这个 2021 行的文件。`applyStreamEvent` 已经是 267 行的巨型 switch-case，每加一个新事件分支，合并冲突概率指数上升。props drilling 意味着任何子组件需要的任何数据都要经过 App.tsx 中转，改一个 prop 名可能波及十几层。这不是"可能会出问题"，而是"已经在出问题"——`useWiki` 已经膨胀到 858 行且没有使用 reducer（而其他三个 feature hooks 都用 reducer），正是因为把本该在 feature 层管理的事件分发逻辑留在了 App.tsx 里。

### 2. [代码质量] 49 处 `except Exception` 宽泛捕获，大量静默吞没

**统计**: 在 `apps/backend/app/` 下共发现 **49 处** `except Exception`（或 `except Exception as exc`），其中至少 12 处是静默吞没（无日志、无事件、无重抛）。

最危险的 5 处：

| 文件 | 行号 | 吞没方式 | 后果 |
|---|---|---|---|
| [agents/graph_runtime.py](apps/backend/app/agents/graph_runtime.py#L135) | 135 | `except Exception:` 后直接回退到预计算路由，**零日志** | 语义分析模型静默失败，用户得到降级回复但无人知晓 |
| [agents/runtime_helpers.py](apps/backend/app/agents/runtime_helpers.py#L28) | 28, 37, 46 | 三处 `except Exception: return ""` 或 `return None`，**零日志** | continuity 上下文块获取失败完全不可见 |
| [agents/nodes/retrieval.py](apps/backend/app/agents/nodes/retrieval.py#L90) | 90, 110, 253, 278 | 四处 `except Exception:` 静默回退 | 检索失败时用户被告知"没有找到"，而非"检索系统故障" |
| [services/long_term_memory.py](apps/backend/app/services/long_term_memory.py#L428) | 428 | `except Exception:` 后 `logger.warning` 记录但返回 `[]` | 有日志但上游调用者不知道模型提取失败，当作"没有可提取的记忆" |
| [api/services/factory.py](apps/backend/app/api/services/factory.py#L321) | 321 | `except Exception: return None` | `optional_writer` 在初始化失败时静默返回 None，整个文件写入链断裂 |

**为什么危险**: 这不是代码风格问题，这是**可观测性黑洞**。当用户报告"桌宠好像不记得我说过的话了"，你无法从日志中知道是语义分析模型挂了、continuity 上下文获取失败、还是检索节点静默回退了。`graph_runtime.py:135` 的那行 `except Exception:` 没有日志、没有 metrics、没有任何信号——这在生产环境中就是你半夜 3 点被叫起来却无从排查的那种 bug。

### 3. [安全] 非 Windows 平台凭据存储使用 base64 明文（无加密）

**文件**: [apps/backend/app/services/settings.py](apps/backend/app/services/settings.py#L161-L170)

**当前代码的问题**:
```python
# 第 161-170 行
data = _dpapi_unprotect(protected) if _dpapi_available() else protected
...
suffix = ".dpapi" if _dpapi_available() else ".secret"
```

`_dpapi_available()` 在第 763 行对非 Windows 平台直接返回 `False`。这意味着在 Linux/macOS 上：
- 文件扩展名变成 `.secret`
- 数据内容就是 **base64 原文，零加密**
- 任何能读文件系统的进程都能获取用户的 API Key

**为什么危险**: 用户配置 OpenAI/OpenAI-compatible 的 API Key 后，在非 Windows 系统上等同于明文存储。虽然当前项目定位是 Windows 桌面应用（`CLAUDE.md` 明确写了 "local-first Windows desktop agent pet"），但代码中已经存在 Linux/macOS 路径——`config.py` 的 `_default_data_dir()` 会读 `LOCALAPPDATA`/`APPDATA`，`electron/main.cjs` 里有 `process.platform !== "darwin"` 的判断。一旦有人尝试移植到 macOS，API Key 泄露是 100% 会发生的事件。

### 4. [架构] `api/chat.py` 741 行，混合了 HTTP 路由、数据库 CRUD、4 条后处理管道的编排逻辑

**文件**: [apps/backend/app/api/chat.py](apps/backend/app/api/chat.py)

**当前代码的问题**:
- `_persisting_stream()`（181-306 行）直接操纵数据库连接：`wiring.database(request).connect()` 在 5 个 helper 函数中被调用
- 4 条后处理管道全部内联在同一个文件中：long-term memory 写入（408-644 行）、chat diary 归档、diary memory 提取、wiki answer 总结
- `_create_chat_records()`（128-178 行）执行 4 张表的 INSERT 操作，没有任何事务包裹
- `_archive_chat_memory()`（408-644 行）长达 236 行，包含 5 个串行的 `try/except` 块，每个块内部又有数据库写入

**为什么危险**: 这不是架构洁癖问题。当这 4 条后处理管道中的任何一条抛出未被捕获的异常时（注意每个管道外层只有 `except Exception as exc` 的 warning 日志），整个流式响应会被打断。当前代码里后处理管道在流结束后异步执行（`asyncio.create_task`），但如果未来有人把某个管道改成同步、或者某个 `await` 被误删，就会变成**流式响应的阻塞点**。更现实的风险是：任何一个后处理步骤的数据库 schema 变更都会强迫修改这个 741 行的文件——这是一个典型的"所有路都通向罗马"的架构反模式。

### 5. [数据安全] 用户聊天内容流经 LLM 后才经过写策略检查

**文件**: [apps/backend/app/services/continuity.py](apps/backend/app/services/continuity.py#L99-L113)

**当前代码的问题**:
```python
# 第 99-113 行
# evaluate_memory_content 在发送给 LLM 之前做了检查
policy = evaluate_memory_content(source_text)
if not policy.allowed:
    return []
# 但如果 policy.allowed == True，完整的 user_message 原样发送给 model_client
```

`chat_auto_memory.py` 的 `append` 方法（164-172 行）将用户问题和助手回答**完整写入** Markdown 文件，但没有经过 `evaluate_markdown_write` 写策略检查。写策略（`write_policy.py` 的 credential regex）只能捕获 `sk-`/`pk-`/`AKIA` 等已知前缀的 API Key——任何自定义 provider 的 API Key 格式都会直接写入 Vault。

**为什么危险**: 用户可能在聊天中说"我的密码是 xxx"或粘贴包含 Bearer token 的请求日志。这些内容在经过 `evaluate_memory_content`（一个较宽松的内容策略）检查后，可能被判定为 allowed 并发送给 LLM（模型提供商的服务器），后续又被 `chat_auto_memory` 写入本地 Markdown。两条泄漏路径：一条到云端（模型提供商），一条到本地文件系统。写策略的 credential regex 只覆盖 OpenAI/GitHub/AWS 前缀——这是一个已知的覆盖盲区。

---

## 中等问题（会随时间恶化但不立即致命）

### 6. [代码质量] 日志覆盖率极低：30 个后端源文件中仅 10 个使用了 logging

**数据**: 
- 使用 `logging` 的源文件：10 个（`health.py`, `chat.py`, `factory.py`, `long_term_memory.py`, `memory_graph.py`, `settings.py`, `continuity.py`, `retrieval_factory.py`, `vector_index.py`, `diary_memory_extractor.py`）
- **完全无日志**的源文件：20 个，包括 `main.py`、`graph_runtime.py`、`tools.py`、`memory.py`、`database.py`、`wiki.py`、`wiki_lint.py`、`companion_retrieval.py`、`config.py`、`events.py`、所有 agent nodes 等核心模块
- 整个代码库无 `print()` 调用（这是好事），但 logging 也没有补上

**为什么危险**: 当前在本地开发机上可以通过 IDE debugger 或 `console.warn` 排查问题。但如果未来有人把后端部署为 Windows Service 或后台进程（无终端），或者用户报告了一个间歇性问题，你没有任何日志可以回溯。`main.py` 的 app 启动、`database.py` 的迁移应用、`graph_runtime.py` 的节点路由——这些都是出了问题时你需要第一时间看到日志的地方。

### 7. [代码质量] `utc_now_iso()` 在两个文件中各自定义，存在重复实现

**文件**: 
- [apps/backend/app/services/memory.py](apps/backend/app/services/memory.py#L67-L68)
- [apps/backend/app/services/tasks.py](apps/backend/app/services/tasks.py#L107-L108)

**当前代码**: 两份**逐字相同**的实现:
```python
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

`memory_graph.py` 从 `memory.py` 导入此函数，而 `chat.py` 从 `tasks.py` 导入。如果未来有人修改其中一个（例如改成 `isoformat(timespec='seconds')`），两个文件的行为会无声分化。

类似重复还包括：
- `_vector_id`（[vector_index.py:211](apps/backend/app/services/vector_index.py#L211)）和 `_hash_text`（[companion_retrieval.py:435](apps/backend/app/services/companion_retrieval.py#L435)）都实现了 `hashlib.sha256().hexdigest()`
- `companion_retrieval.py` 438-461 行的 4 个 JSON 序列化 helper 函数（`_json_list`, `_json_object`, `_json_list_value`, `_json_object_value`）是通用工具函数，但不属于任何共享模块
- `tools.py` 588-641 行的 9 个 `_coerce_*` 函数结构完全相同，可以泛化为一个泛型函数

### 8. [代码质量] `events.py` 中的 SSE 事件模型与 `models/api.py` 中的 API 响应模型存在大量字段级重复

**文件**: 
- [apps/backend/app/agents/events.py](apps/backend/app/agents/events.py)
- [apps/backend/app/models/api.py](apps/backend/app/models/api.py)

**重复清单**:
- `AgentContextBudgetEvent`（events.py:65-78）≈ `CompanionContextBudgetTelemetry`（companion_retrieval.py:469-481），相同字段 12 个
- `AgentActionEvent`（events.py:81-93）≈ `AgentActionResponse`（models/api.py:749-770）
- `AgentTaskEvent`（events.py:119-129）≈ `TaskCreateResponse`（models/api.py:132-136）
- `AgentMemoryProposalEvent`（events.py:35-41）≈ `MemoryProposalActionResponse`（models/api.py:111-116）
- `AgentContinuityProposalEvent`（events.py:43-52）≈ `ContinuityProposalResponse`（models/api.py:706-718）
- `AgentWikiProposalEvent`（events.py:95-116）合并了多个 wiki 响应模型

**为什么危险**: 任何人修改 API 响应模型时都必须记得同步修改 events 模型。当前没有任何编译时或运行时检查来保证两者一致。如果 `AgentActionResponse` 加了一个 `executed_at` 字段但 `AgentActionEvent` 没有加，前端收到的 SSE 事件就会缺字段——这种 bug 在手动测试中极难发现，因为只有特定操作触发特定事件时才暴露。

### 9. [安全] `mask_secret()` 泄露 API Key 的前 2 和后 2 个字符

**文件**: [apps/backend/app/services/settings.py](apps/backend/app/services/settings.py#L756-L759)

**当前代码**:
```python
def mask_secret(secret: str) -> str:
    if len(secret) <= 4:
        return "****"
    return f"{secret[:2]}...{secret[-2:]}"
```

OpenAI API Key 以 `sk-` 开头——这意味着 mask 结果一定是 `sk...` + 后两位。一个 51 字符的 OpenAI key 被 mask 后实际泄露了 4 个字符（`sk` + 末尾 2 字符）。这在 API 响应中返回给前端（通过 `ModelKeyStatus.masked` 字段）。4 个字符不足以直接破解，但结合其他信息（key 长度、提供商类型）可以辅助定向攻击。

### 10. [工程基础设施] models/api.py 914 行，覆盖 ~25 个 API 域，是"数据模型上帝文件"

**文件**: [apps/backend/app/models/api.py](apps/backend/app/models/api.py)

**问题**: 所有 API 的 Pydantic 模型全部塞在一个文件中：health check、chat、memory、tasks、wiki（page/schema/index/graph/log/ingest/synthesis/archive/lint/diagnostics）、model config、embedding config、automation settings、vault、continuity、agent actions、memory graph facts、companion reports、diagnostics。

**为什么是中等而非严重**: 当前 914 行还能勉强管理，但每增加一个新的 API 域就是 50-150 行，6 个月后轻松突破 1500 行。Pydantic 模型之间的引用关系会变得越来越难追踪（例如 `WikiIngestPagePlan` 和 `WikiPageWriteRequest` 共享字段设计但彼此独立定义）。

### 11. [工程基础设施] CI 只做 typecheck + build + pytest（跳过 live_model），无量化的代码覆盖率、无 linting

**文件**: [.github/workflows/ci.yml](.github/workflows/ci.yml)

**问题**:
- **无代码覆盖率**: 没有 `pytest-cov`，不知道改了代码后覆盖率是升还是降
- **无 linting**: 后端没有 ruff/flake8，前端没有 eslint。代码风格完全靠人工
- **mypy 只检查 2 个文件**: `strict = true` 但 `files = ["app/scheduler", "app/agents/services.py"]`（[pyproject.toml:32-35](apps/backend/pyproject.toml#L32-L35)），99% 的代码无静态类型检查
- **单一 Python 版本**: CI 只测 Python 3.11
- **无集成测试**: 前后端独立测试，没有端到端测试（无 Playwright）

### 12. [测试] `app/agents/tools.py`（641 行）无独立单元测试

**文件**: [apps/backend/app/agents/tools.py](apps/backend/app/agents/tools.py)

`AgentToolSet` 的 8 个 tool 方法只在 agent node 的单元测试中被间接触发（通过 `FakeToolCallingChatModel` 模拟 tool invocation），但：
- 没有对单个 tool `ainvoke` 方法的直接测试
- 没有对 tool schema 验证的测试
- 没有对 tool 错误处理的测试（例如当 service 为 None 时的行为）
- 9 个 `_coerce_*` 函数没有一个有独立的单元测试

### 13. [代码质量] `useWiki.ts`（858 行）使用 30 个 `useState` 而不使用 `useReducer`，与项目其他 feature hooks 不一致

**文件**: [apps/desktop/src/features/wiki/useWiki.ts](apps/desktop/src/features/wiki/useWiki.ts)

同一项目中的 `useSettings`（300 行）、`useTasks`（184 行）、`useMemory`（176 行）全部使用 `useReducer`。`useWiki` 拥有最多的状态（30 个）却使用最原始的状态管理方式。每次 `setXxx` 调用都是一个潜在的 re-render 触发器，多个 `useState` 之间存在隐式依赖（例如 ingest preview 完成后需要同时更新 preview 状态和 workflow draft），但没有 reducer 来保证状态转换的原子性。

### 14. [架构] `factory.py`（574 行）是依赖注入的上帝文件

**文件**: [apps/backend/app/api/services/factory.py](apps/backend/app/api/services/factory.py)

**问题**: 574 行的单文件涵盖：服务构建、vault 路径验证、审计记录、索引刷新调度、chat model client 组装、所有 Depends 生成器。第 67 行有一个懒加载 `from app.main import ensure_app_services` 来打破与 `main.py` 的循环依赖——这是 "code smell" 的标志。

### 15. [数据安全] 硬编码 OpenAI 默认值散落在 3 个文件中

**位置**:
- [config.py:24,27,29,32](apps/backend/app/config.py#L24): `model_base_url = "https://api.openai.com/v1"`, `chat_model = "gpt-4o-mini"`, `embedding_base_url = "https://api.openai.com/v1"`, `embedding_model = "text-embedding-3-small"`
- [models/api.py:551-553](apps/backend/app/models/api.py#L551-L553): `ModelConfigRequest` 的 `model = "gpt-4o-mini"`, `base_url = "https://api.openai.com/v1"`
- [models/api.py:569-571](apps/backend/app/models/api.py#L569-L571): `EmbeddingConfigRequest` 的相同默认值

三次重复的相同字符串。且 `settings.py:529` 的 fallback 链在用户未保存配置时将非 OpenAI provider 的 API key 路由到 `https://api.openai.com/v1`——这是一个潜在的**数据外泄**路径。

### 16. [代码质量] `companion_retrieval.py`（699 行）包含三种不相关的职责且零日志

**文件**: [apps/backend/app/services/companion_retrieval.py](apps/backend/app/services/companion_retrieval.py)

在一个文件中：检索编排（`CompanionRetrievalService`）、报告持久化（`CompanionRetrievalReportStore`）、上下文预算管理（`rerank_memory_context` + 相关 dataclasses）。两个不同的去重+打分实现在 `_rerank_and_dedupe`（331 行）和 `rerank_memory_context`（616 行）中各自维护，零日志覆盖。

---

## 如果不处理，N 个月后会发生什么

### 3 个月后（2026 年 8 月）
- **App.tsx 将突破 2500 行**。当前每个新功能平均给 App.tsx 增加 ~50-80 行（新的 SSE 事件分支 + 新的 state + 新的 useEffect + 新的 props drilling）。3 个月约等效于 6-8 个 feature PR——App.tsx 轻松突破 2500 行，`applyStreamEvent` 从 267 行增长到 400+ 行。
- **models/api.py 将超过 1100 行**，新增 2-3 个 API 域的模型使得文件内跨域引用变得足够复杂，以至于有人会为了避免冲突而新建 `models/api_v2.py`。

### 6 个月后（2026 年 11 月）
- **第一个"幽灵 bug"将出现**：由于 `graph_runtime.py:135` 和 `runtime_helpers.py:28/37/46` 的静默异常吞没，某个模型调用失败 3 周后才会被发现——因为用户以为是"桌宠记性不好"而不是"语义分析挂了 3 周"。
- **重复代码将开始分叉**：`utc_now_iso()` 的两个副本中的某一个会被修改（例如加上毫秒精度），另一个不会，导致数据库和 Markdown 文件中的时间戳格式不一致。
- **如果有人尝试在 macOS 上运行**，凭据以 base64 明文存储的问题会暴露。如果这个人恰好截了图或录了屏分享到社区，就会变成一次安全事故。

### 12 个月后（2027 年 5 月）
- **新人无法安全修改代码**。App.tsx 超过 3000 行，`applyStreamEvent` 500+ 行，`chat.py` 900+ 行——要加一个新功能需要读通 4 个巨型文件才能知道该改哪里。
- **代码覆盖率仍然未知**，重构没有安全网。
- **不处理 exception swallowing = 运维盲飞**。出现任何问题都需要连上 debugger 才能在本地复现——因为没有日志输出。

---

## 总体评分

| 维度 | 评分 | 理由 |
|---|---|---|
| **架构** | 5/10 | 方向正确（本地优先、Vault 记忆、双窗口桌面壳、feature-based 前端组织），但上帝文件（App.tsx, chat.py, factory.py, models/api.py）正在侵蚀模块边界。agent runtime 的 LangGraph 节点设计清晰，但工具层和事件层的重复抵消了这部分优势。 |
| **安全** | 6/10 | 安全基础扎实：DPAPI 加密（Windows）、写策略多层检查、路径遍历防御、Electron contextIsolation+sandbox、SSE payload 脱敏。但扣分项明确：非 Windows 明文存储、API Key 泄露到非 OpenAI 端点、写策略 credential regex 覆盖不全、`mask_secret` 过度泄露。 |
| **可维护性** | 4/10 | 日志覆盖率 ~33%（10/30 文件），49 处宽泛异常捕获，重复代码散落（`utc_now_iso`、coerce 函数族、hashing、JSON helpers、事件/API 模型重复），测试无覆盖率量化，CI 无 linting，mypy 局限在 2 个文件——这是 v0.2.0 原型该有的可维护性水平，但不是 v0.5.0+ 该有的。 |

### 综合评分：5.0/10

一个设计意图正确、安全意识在关键路径上到位、但**执行纪律不足**的原型。如果现在投入 2-3 周做结构性还债（拆分上帝文件、统一异常处理、补充日志、消除重复），这个项目可以在 v0.5.0 达到 7-8 分的工程水平。如果继续以当前节奏堆功能，v1.0 时将是一个无人敢动的遗留系统。

---

## 推荐优先处理清单（按投入产出比排序）

1. **【1-2 天】全局异常处理标准化**：为 12 处静默吞没点至少加上 `logger.warning(..., exc_info=True)`。不需要改异常处理策略，只需要让异常可见。
2. **【2-3 天】拆分 App.tsx 的 `applyStreamEvent`**：将 267 行的 SSE 事件分发提取为 `src/features/chat/streamDispatcher.ts`，每种事件类型一个 handler 函数。
3. **【1 天】统一重复的工具函数**：创建 `app/utils/time.py`（放 `utc_now_iso`）、`app/utils/hash.py`（放 hashing 辅助函数）、`app/utils/serialization.py`（放 JSON helpers），删除重复定义。
4. **【2-3 天】拆分 `models/api.py`**：按域拆分为 `models/chat.py`、`models/wiki.py`、`models/memory.py`、`models/config.py`、`models/diagnostics.py`。
5. **【1 天】为非 Windows 凭据存储加上明确的阻断或警告**：如果必须在非 Windows 运行，至少显式拒绝明文存储或要求用户设置 `AGENT_PET_CREDENTIALS_ENCRYPTION_KEY`。
6. **【1 天】CI 加入 linting 和覆盖率**：后端加 ruff + pytest-cov，前端加 eslint（或至少启用已有的 typecheck 覆盖所有文件）。
7. **【持续】每新增一个 feature 强制减少一处重复**：这是一种渐进式还债策略，防止重复积累。

---

*评审人：Claude (via Claude Code) | 评审基于 `dev` 分支 2026-05-25 代码快照*
