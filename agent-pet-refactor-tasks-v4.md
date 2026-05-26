# Agent Pet 重构任务指令集（第四批）

> **使用方式：** 按照下方编号顺序执行，每次只给 Agent 一个 Task，附上对应的源代码文件，完成并验收后再执行下一个。

---

### Task 1 — 为 12 处静默异常吞没添加日志

**前置条件：** 附上以下文件：
- `apps/backend/app/agents/graph_runtime.py`（重点：第 135 行）
- `apps/backend/app/agents/runtime_helpers.py`（重点：第 28、37、46 行）
- `apps/backend/app/agents/nodes/retrieval.py`（重点：第 90、110、253、278 行）
- `apps/backend/app/services/long_term_memory.py`（重点：第 428 行）
- `apps/backend/app/api/services/factory.py`（重点：第 321 行）

**背景：** 上述位置存在 `except Exception` 后直接 `return ""`、`return None`、`return []` 且零日志的静默吞没，导致语义分析模型失败、检索失败、continuity 上下文获取失败完全不可见。

**你的任务：**

按以下规范逐一改写每处静默吞没：

```python
# 禁止（零日志静默吞没）
except Exception:
    return []

# 要求（至少记录 warning，保留原返回值）
except Exception:
    logger.warning("检索节点异常，降级返回空结果", exc_info=True)
    return []
```

每个文件顶部如果没有 `logger = logging.getLogger(__name__)`，补上。

**关键约束：**
- 本 Task 只加日志，不改异常处理策略和返回值
- 不引入新的异常类型
- `graph_runtime.py:135` 必须加日志，这是最高优先级的盲点

**验收标准：**

- [ ] 全局搜索 `except Exception` 后紧接 `return` 且无 `logger` 调用的组合，在上述五个文件中结果为零
- [ ] 每个涉及文件顶部有 `logger = logging.getLogger(__name__)`
- [ ] `pytest` 全部通过，无新增失败

---

### Task 2 — 统一重复工具函数，消除多处重复定义

**前置条件：** 附上以下文件：
- `apps/backend/app/services/memory.py`（重点：第 67-68 行）
- `apps/backend/app/services/tasks.py`（重点：第 107-108 行）
- `apps/backend/app/services/vector_index.py`（重点：第 211 行）
- `apps/backend/app/services/companion_retrieval.py`（重点：第 435、438-461 行）
- `apps/backend/app/agents/tools.py`（重点：第 588-641 行）

**背景：** `utc_now_iso()` 在两个文件中逐字相同地定义；`hashlib.sha256().hexdigest()` 在两处各自实现；4 个 JSON 序列化 helper 和 9 个 `_coerce_*` 函数结构完全相同但分散在不同文件中。

**你的任务：**

创建以下三个工具模块，将重复实现迁移进去，再从原文件中删除重复定义并改为 import：

```
apps/backend/app/utils/
├── __init__.py
├── time.py          # utc_now_iso()
├── hash.py          # sha256_hex(text: str) -> str
└── coerce.py        # _coerce_str、_coerce_int 等泛化版本
```

`tools.py` 中 9 个结构相同的 `_coerce_*` 函数泛化为：

```python
def coerce_field(value: Any, expected_type: type, default: Any = None) -> Any:
    if isinstance(value, expected_type):
        return value
    try:
        return expected_type(value)
    except (TypeError, ValueError):
        return default
```

**关键约束：**
- 所有原调用方改为从 `app.utils.*` 导入，不改调用签名
- `memory_graph.py` 从 `memory.py` 导入 `utc_now_iso` 的路径需同步更新

**验收标准：**

- [ ] 全局搜索 `def utc_now_iso`，只在 `app/utils/time.py` 中出现
- [ ] 全局搜索 `hashlib.sha256`，只在 `app/utils/hash.py` 中出现
- [ ] `pytest` 全部通过，无新增失败

---

### Task 3 — 拆分 `App.tsx` 的 `applyStreamEvent`（267 行）

**前置条件：** 附上 `apps/desktop/src/App.tsx`（重点：第 583-850 行）

**背景：** `applyStreamEvent` 是 267 行的巨型事件分发函数，内含 10+ 个 if/else 分支处理 done、error、status、agent_action、continuity_signal、memory_proposal、wiki_proposals、task 等 SSE 事件，每增加一种事件类型都要修改这个函数。

**你的任务：**

将 `applyStreamEvent` 提取为独立模块，每种事件类型一个 handler 函数：

```
apps/desktop/src/features/chat/
├── streamDispatcher.ts      # 主分发入口，替换原 applyStreamEvent
└── handlers/
    ├── doneHandler.ts
    ├── errorHandler.ts
    ├── statusHandler.ts
    ├── agentActionHandler.ts
    ├── continuityHandler.ts
    ├── memoryProposalHandler.ts
    ├── wikiProposalHandler.ts
    └── taskHandler.ts
```

`streamDispatcher.ts` 结构：

```typescript
export function applyStreamEvent(
  event: StreamEvent,
  dispatch: AppDispatch,
): void {
  switch (event.type) {
    case "done": return doneHandler(event, dispatch)
    case "error": return errorHandler(event, dispatch)
    case "agent_action": return agentActionHandler(event, dispatch)
    // ...
  }
}
```

`App.tsx` 中原来的 `applyStreamEvent` 函数体删除，改为从 `streamDispatcher.ts` 导入。

**关键约束：**
- 不改变任何 SSE 事件的处理逻辑，只做搬移
- App.tsx 行数在本 Task 完成后必须减少至少 200 行

**验收标准：**

- [ ] `App.tsx` 中不再有 `applyStreamEvent` 的函数体定义
- [ ] `streamDispatcher.ts` 存在且包含主分发逻辑
- [ ] `handlers/` 下每个文件对应一种事件类型
- [ ] `npm run typecheck` 无报错
- [ ] `npm run build` 成功

---

### Task 4 — 将 `useWiki.ts` 的 30 个 useState 改为 useReducer

**前置条件：** 附上 `apps/desktop/src/features/wiki/useWiki.ts`（858 行）

**背景：** 同项目中 `useSettings`、`useTasks`、`useMemory` 全部使用 `useReducer`，唯独 `useWiki` 使用 30 个 `useState`，状态转换缺乏原子性保证（例如 ingest preview 完成后需同时更新多个状态，但每个 `setXxx` 是独立触发）。

**你的任务：**

参照同项目其他 feature hooks 的模式，将 30 个 `useState` 重构为单一 `useReducer`：

```typescript
// wikiReducer.ts
interface WikiState {
  // 将现有 30 个 useState 的类型合并为一个 state 接口
}

type WikiAction =
  | { type: "PREVIEW_INGEST_START" }
  | { type: "PREVIEW_INGEST_SUCCESS"; payload: WikiPreviewResult }
  | { type: "CONFIRM_INGEST_SUCCESS" }
  // ... 覆盖所有状态转换场景

function wikiReducer(state: WikiState, action: WikiAction): WikiState {
  switch (action.type) { ... }
}
```

**关键约束：**
- reducer 必须是纯函数，不包含任何副作用
- 所有原有的状态转换语义必须保留，不改功能
- 提取为独立文件 `features/wiki/wikiReducer.ts`，可单独测试

**验收标准：**

- [ ] `useWiki.ts` 中 `useState` 调用数量为零
- [ ] `wikiReducer.ts` 文件存在且是纯函数（无 API 调用、无副作用）
- [ ] `npm run typecheck` 无报错
- [ ] 有对应的 `wikiReducer.test.ts`，覆盖至少 5 个主要 action 的状态转换

---

### Task 5 — 拆分 `models/api.py`（914 行）按域分文件

**前置条件：** 附上 `apps/backend/app/models/api.py`

**背景：** 914 行的单文件涵盖约 25 个 API 域的 Pydantic 模型，每增加一个新域就继续膨胀，域间引用关系越来越难追踪。

**你的任务：**

按以下结构拆分，一次只输出一个文件，输出完等确认再继续：

```
apps/backend/app/models/
├── __init__.py          # 聚合所有导出，保持外部 import 路径不变
├── chat.py              # 聊天相关模型
├── memory.py            # 记忆、continuity 相关模型
├── wiki.py              # Wiki page/schema/index/ingest/synthesis/archive/lint 相关模型
├── tasks.py             # 任务、提醒相关模型
├── config.py            # ModelConfig、EmbeddingConfig、AutomationSettings 相关模型
└── diagnostics.py       # 诊断、health check、审计相关模型
```

**关键约束：**
- 所有外部调用方的 `from app.models.api import Xxx` 通过 `__init__.py` 保持不变
- 拆分完成后删除原 `api.py` 文件

**验收标准：**

- [ ] `models/api.py` 原文件已删除
- [ ] 每个新文件行数 ≤ 200
- [ ] 全局搜索 `from app.models.api import`，所有调用方正常工作
- [ ] `pytest` 全部通过，无新增失败

---

### Task 6 — 修复非 Windows 平台凭据明文存储

**前置条件：** 附上 `apps/backend/app/services/settings.py`（重点：第 161-170、756-759、763 行）

**背景：** `_dpapi_available()` 在非 Windows 平台返回 `False`，导致凭据以 base64（可逆明文）存储，文件扩展名为 `.secret`。同时 `mask_secret()` 泄露 API Key 的前 2 和后 2 个字符（对 OpenAI key 等于泄露 `sk` + 末尾 2 位）。

**你的任务：**

**改动一：凭据存储 fail-closed**

```python
def store(self, key: str, value: str) -> None:
    if not _dpapi_available():
        raise CredentialStoreError(
            "当前平台不支持安全凭据存储（仅支持 Windows DPAPI）。"
            "API Key 未被保存。如需在非 Windows 平台运行，"
            "请通过环境变量 AGENT_PET_API_KEY 传入凭据。"
        )
    # 原有 DPAPI 加密逻辑保持不变
```

**改动二：修复 `mask_secret()`**

```python
def mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    # 只保留最后 4 位，不暴露前缀
    return f"****{secret[-4:]}"
```

**关键约束：**
- DPAPI 可用时（Windows）的存储逻辑完全不变
- 新增 `CredentialStoreError` 异常类
- 设置界面收到 `CredentialStoreError` 时需展示明确的错误提示，不能静默失败

**验收标准：**

- [ ] Mock `_dpapi_available()` 返回 `False`，调用 `store()` 抛出 `CredentialStoreError`
- [ ] `mask_secret("sk-abcdefghijklmnopqrstuvwxyz123456")` 返回 `****3456`，不再返回 `sk...56`
- [ ] Windows 正常路径行为不变
- [ ] 有对应测试覆盖上述两个场景

---

### Task 7 — 修复 API Key 可能被路由到错误端点

**前置条件：** 附上以下文件：
- `apps/backend/app/services/settings.py`（重点：第 529 行附近的 fallback 链）
- `apps/backend/app/config.py`（重点：第 24、27、29、32 行）
- `apps/backend/app/models/api.py`（重点：第 551-553、569-571 行）

**背景：** `settings.py` 的 fallback 链在用户未保存配置时，将非 OpenAI provider 的 API Key 路由到硬编码的 `https://api.openai.com/v1`，造成数据外泄。同一组默认值在 `config.py` 和 `models/api.py` 中重复定义了三次。

**你的任务：**

1. 将所有默认值集中到 `config.py`，`models/api.py` 中的默认值改为从 `config.py` 导入：

```python
# config.py 保持为唯一真相源
DEFAULT_CHAT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
```

2. 修复 fallback 链，当用户配置了 API Key 但 `base_url` 为空时，必须抛出错误而不是 fallback 到 OpenAI：

```python
# settings.py fallback 链
if api_key and not base_url:
    raise ConfigurationError(
        "已配置 API Key 但未配置 Base URL，无法安全路由请求。"
        "请在设置中填写对应的 Base URL。"
    )
```

**验收标准：**

- [ ] 全局搜索 `"https://api.openai.com/v1"`，只在 `config.py` 中出现
- [ ] 全局搜索 `"gpt-4o-mini"`，只在 `config.py` 中出现
- [ ] 有测试：配置了非空 API Key 但空 Base URL → 抛出 `ConfigurationError`
- [ ] `pytest` 全部通过

---

### Task 8 — 拆分 `chat.py`（741 行）的后处理管道

**前置条件：** 附上 `apps/backend/app/api/chat.py`

**背景：** `chat.py` 混合了 HTTP 路由、数据库 CRUD、4 条后处理管道（long-term memory 写入、chat diary 归档、diary memory 提取、wiki answer 总结），`_create_chat_records()` 执行 4 张表的 INSERT 但无事务包裹，`_archive_chat_memory()` 236 行内含 5 个串行 try/except 块。

**你的任务：**

1. 将 4 条后处理管道提取为独立服务方法：

```
apps/backend/app/services/chat_pipeline/
├── __init__.py
├── diary.py           # chat diary 归档逻辑
├── long_term.py       # long-term memory 写入逻辑
├── diary_memory.py    # diary memory 提取逻辑
└── wiki_summary.py    # wiki answer 总结逻辑
```

2. `_create_chat_records()` 的 4 张表 INSERT 用事务包裹：

```python
async with database.transaction():
    await _insert_conversation(...)
    await _insert_message(...)
    await _insert_agent_run(...)
    await _insert_agent_action(...)
```

3. `chat.py` 只保留路由定义和管道调度，不包含具体业务逻辑。

**关键约束：**
- 不改变任何 HTTP 路由路径和响应结构
- 后处理管道仍然异步执行（`asyncio.create_task`）

**验收标准：**

- [ ] `chat.py` 行数 ≤ 300
- [ ] `_archive_chat_memory` 函数不再存在于 `chat.py`
- [ ] `_create_chat_records` 内部有事务包裹
- [ ] `pytest` 全部通过，无新增失败

---

### Task 9 — 统一 events.py 和 models/api.py 的重复模型

**前置条件：** 附上以下文件：
- `apps/backend/app/agents/events.py`
- `apps/backend/app/models/api.py`（重点：第 749-770、132-136、111-116、706-718 行）
- `apps/backend/app/services/companion_retrieval.py`（重点：第 469-481 行）

**背景：** SSE 事件模型（`events.py`）和 API 响应模型（`models/api.py`）存在 6 对字段级重复，没有任何机制保证两者同步，一旦有人只改其中一个，前端收到的 SSE 事件就会缺字段。

**你的任务：**

对每一对重复模型，提取共享字段为基类，事件模型和响应模型分别继承：

```python
# 示例：AgentAction 对
class AgentActionBase(BaseModel):
    action_type: str
    description: str
    status: str
    # ... 共享字段

class AgentActionEvent(AgentActionBase):
    # SSE 专有字段
    event: str = "agent_action"

class AgentActionResponse(AgentActionBase):
    # API 响应专有字段
    action_id: str
    created_at: str
```

需要处理的 6 对：
- `AgentActionEvent` ↔ `AgentActionResponse`
- `AgentTaskEvent` ↔ `TaskCreateResponse`
- `AgentMemoryProposalEvent` ↔ `MemoryProposalActionResponse`
- `AgentContinuityProposalEvent` ↔ `ContinuityProposalResponse`
- `AgentContextBudgetEvent` ↔ `CompanionContextBudgetTelemetry`
- `AgentWikiProposalEvent` ↔ 相关 wiki 响应模型

**关键约束：**
- 不改变任何字段名和类型，只做继承关系重组
- 现有的序列化/反序列化行为必须保持不变

**验收标准：**

- [ ] 上述 6 对模型之间存在显式的继承关系或共享基类
- [ ] 全局搜索重复字段名（如 `action_type`），在基类中只定义一次
- [ ] `pytest` 全部通过

---

### Task 10 — 为 `tools.py` 补充独立单元测试

**前置条件：** 附上 `apps/backend/app/agents/tools.py`（641 行）

**背景：** `AgentToolSet` 的 8 个 tool 方法和 9 个 `_coerce_*` 函数目前只被 agent node 的集成测试间接覆盖，没有直接的单元测试，tool schema 验证和错误处理路径完全没有测试。

**你的任务：**

创建 `apps/backend/tests/unit/agents/test_tools.py`，覆盖以下场景：

```python
# 每个 tool 方法的直接调用测试
async def test_memory_search_tool_returns_results(): ...
async def test_memory_search_tool_returns_empty_on_no_results(): ...
async def test_memory_search_tool_when_service_is_none(): ...  # 错误处理

# coerce 函数测试（Task 2 完成后改为测试 coerce.py）
def test_coerce_field_with_correct_type(): ...
def test_coerce_field_with_convertible_type(): ...
def test_coerce_field_with_unconvertible_type_returns_default(): ...

# tool schema 验证
def test_tool_schema_has_required_fields(): ...
def test_tool_schema_rejects_extra_fields(): ...
```

**关键约束：**
- 所有外部依赖（service、数据库）必须 mock，不依赖真实环境
- 每个 tool 方法至少有 3 个测试：正常路径、空结果、service 为 None

**验收标准：**

- [ ] `tests/unit/agents/test_tools.py` 文件存在
- [ ] 8 个 tool 方法各有至少 3 个测试
- [ ] `coerce_field` 有独立测试
- [ ] `pytest tests/unit/agents/test_tools.py` 全部通过

---

### Task 11 — CI 加入 linting 和覆盖率

**前置条件：** 附上 `.github/workflows/ci.yml` 和 `apps/backend/pyproject.toml`

**背景：** 当前 CI 无 linting（后端无 ruff，前端无 eslint），mypy 只检查 2 个文件，无代码覆盖率量化，无法知道改动后覆盖率变化方向。

**你的任务：**

1. 后端 CI 加入 ruff 和 pytest-cov：

```yaml
- name: Lint
  run: |
    cd apps/backend
    ruff check app/

- name: 测试（含覆盖率）
  run: |
    cd apps/backend
    pytest -m "not live_model" --cov=app --cov-report=term-missing --cov-fail-under=60
```

2. 扩展 mypy 覆盖范围，从 2 个文件扩展到全部 `app/`：

```toml
# pyproject.toml
[tool.mypy]
files = ["app/"]
strict = false          # 先用非严格模式全覆盖，再逐步收紧
ignore_missing_imports = true
```

3. 前端 CI 加入 eslint（如项目已有 eslint 配置）或至少启用 TypeScript 的 `noUnusedLocals` 和 `noUnusedParameters`：

```yaml
- name: Lint
  run: npm run lint
  working-directory: apps/desktop
```

**关键约束：**
- 覆盖率门槛从 60% 开始，不要设置过高导致 CI 立即失败
- mypy 先用非严格模式，保证 CI 能通过，后续逐步收紧

**验收标准：**

- [ ] CI 中 ruff 步骤存在且会在 lint 错误时使 CI 变红
- [ ] CI 中覆盖率报告存在，低于 60% 时 CI 失败
- [ ] mypy 检查范围覆盖 `app/` 而不只是 2 个文件
- [ ] push 后 CI 全部通过
