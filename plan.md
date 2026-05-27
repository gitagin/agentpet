# Agent Pet 架构演进计划

> 编写日期：2026-05-26
> 目标：解决 Alpha 阶段 Agent 配置过载问题，并设计多轮协商架构路线

---

## 0. 当前状态诊断

### 0.1 Agent 数量与编排

当前系统定义了 **9 个 AgentId**，其中 7 个在 LangGraph 图中作为节点运行，2 个在后台服务中独立运作：

| Agent | 运行位置 | 实际调用 LLM |
|---|---|---|
| `chat_agent` | 图节点 → finish | 是 |
| `semantic_analysis_agent` | 图节点 → 条件路由 | 是（有确定性回退） |
| `memory_retrieval_agent` | 图节点 → 条件路由 | 是 |
| `knowledge_retrieval_agent` | 图节点 → chat_agent | 是 |
| `wiki_manager_agent` | 图节点 → finish | 是 |
| `memory_proposal_agent` | 图节点 → finish | 是 |
| `task_agent` | 图节点 → finish | 是 |
| `diary_memory_extractor_agent` | 后台 `DiaryMemoryService` | 是 |
| `continuity_agent` | 后台 `ContinuityService` | 是 |

编排拓扑是**纯线性/分支 DAG**，边在 `graph_runtime.py:78-107` 硬编码：

```
START → route → semantic → [chat | memory_retrieval → knowledge_retrieval → chat
                            | wiki → finish
                            | memory_proposal → finish
                            | task → finish]
```

没有 agent 间的多轮调用、没有动态重入、没有 review/refine 闭环。

### 0.2 核心痛点

1. **UX 过载**：前端设置页将 9 个 agent 以完全相同的表单展示，每个都要独立配置 provider/base_url/model/api_key。全局模型 fallback 链（agent-specific → global → env defaults）后端已实现，但前端完全没有暴露全局配置入口。

2. **降级隐性**：语义分析 LLM 失败 → 静默回退到正则，continuity 失败 → 静默返回空字符串。用户不知道质量下降了。

3. **编排僵化**：`memory_retrieval → knowledge_retrieval → chat_agent` 这条路径是硬编码的。如果 memory search 结果不够，agent 无法自行决定"再搜一次知识库"或"换个 query 重搜"。

4. **高 stakes 操作无 review 闭环**：memory proposal 和 wiki 编辑在 agent 生成后直接交给用户确认，没有"生成 → 自我审查 → 修正 → 再提交"的质量内循环。

5. **配置健康度不可观测**：没有 API 告诉前端"当前有几个 agent 在用硬编码默认值"。

---

## 1. Phase 1：Alpha 配置简化（立即执行，预计 400 行改动）

### 1.1 目标

将用户面对的配置复杂度从 9 个 agent 独立配置降低为 1 个全局配置 + 可选的高级细分配置。

### 1.2 后端改动

#### 1.2.1 模型配置健康检查 API

新增 `GET /api/settings/model-health`，返回：

```python
class ModelHealthResponse(BaseModel):
    global_configured: bool           # 全局模型是否已配置（非硬编码默认值）
    agents_configured: int             # 有独立配置的 agent 数
    agents_fallback_to_global: int     # 走全局 fallback 的 agent 数
    agents_fallback_to_default: int    # 走硬编码默认值（OpenAI gpt-4o-mini）的 agent 数
    agent_details: list[AgentModelHealth]  # 每个 agent 的配置来源
```

实现位置：`apps/backend/app/api/settings.py`，新增一个路由函数，调用 `settings_service` 查询 `agent_model_configs` 表并与全局模型配置比较。

#### 1.2.2 全局模型配置 API 增强

现有的 `PATCH /api/settings` 已经支持全局 `chat_model` 更新。确认以下行为：
- 当全局模型被更新时，所有 `enabled=False` 或无独立配置的 agent 自动继承
- API 响应中明确标注"当前有 N 个 agent 正在使用全局配置"

### 1.3 前端改动

#### 1.3.1 新增全局模型配置卡片

在设置面板顶部（`AgentConfigForm.tsx` 之上）添加"全局模型"卡片，包含：
- provider / base_url / model / api_key 四个字段
- "测试连接"按钮
- 保存后自动应用到所有未独立配置的 agent

#### 1.3.2 9 个 agent 配置收入"高级设置"

将现有的"智能体独立模型"面板改为折叠面板：
- 默认收起
- 标题："独立智能体模型配置（高级）"
- 副标题："留空则使用全局模型。你可以为不同智能体分配不同模型以优化成本和性能。"
- 每行增加"使用全局模型"开关，开启时该行字段 disabled 并显示继承值

#### 1.3.3 模型健康状态 Banner

在设置页顶部根据 `/api/settings/model-health` 的返回值展示 Banner：
- 全部用默认值（0 个已配置）：橙色警告 "你还没有配置任何模型，请先配置全局模型以开始使用。"
- 部分配置：蓝色提示 "N 个智能体使用全局模型，M 个有独立配置。"
- 全部配置：绿色 "所有智能体已独立配置。"

### 1.4 AgentToolSet 分级超时

当前所有工具共用全局 30 秒超时（`Settings.model_timeout_seconds`）。改为每个工具声明自己的超时：

| 工具 | 超时 | 理由 |
|---|---|---|
| `search_memory` | 5s | FTS5 查询应在毫秒级完成 |
| `propose_memory` | 10s | 需要内容安全校验 |
| `plan_wiki_ingest` | 15s | 涉及文件扫描 |
| `plan_wiki_query_archive` | 10s | 查询归档分析 |
| `plan_wiki_synthesis` | 15s | 综合整理可能较慢 |
| `plan_wiki_lint` | 20s | Lint 扫描全量文件 |
| `manage_wiki_page` | 10s | 单页写入 |
| `create_task` | 10s | 提醒创建 |

实现方式：在 `AgentToolSet` 的每个工具函数中使用 `asyncio.wait_for()` 并传入工具级超时，超时抛出 `AgentToolTimeoutError`（已有异常层次可扩展）。

### 1.5 验收标准

- [ ] 新用户只需填写全局模型配置即可开始聊天
- [ ] 高级设置折叠面板默认收起
- [ ] 配置健康 API 返回正确的 agent 配置来源分布
- [ ] Banner 在未配置、部分配置、全配置三种状态下显示正确
- [ ] 每个工具有独立超时，超时错误信息包含工具名称
- [ ] `pytest` 全部通过（当前 489 passed / 2 skipped / 1 failed），`reminder_scheduler` 那个挂掉的测试修掉
- [ ] `npm run typecheck` 通过
- [ ] `npm run build` 通过

---

## 2. Phase 2：Agent 多轮协商架构（v0.3 核心 Feature）

### 2.1 设计目标

将 agent 编排从**硬编码线性 DAG** 演进为**带协商闭环的动态图**，使 agent 能够：

1. **动态选择工具/子 agent**：chat_agent 根据对话需要自行决定调用哪些子 agent、以什么顺序调用
2. **多轮检索**：搜索结果不够时，自动换 query 重搜或切换到知识库
3. **生成-审查-修正闭环**：memory proposal 和 wiki 编辑先生成草案、再自我审查、修正后提交用户确认
4. **置信度门控**：每个决策点有置信度评估，低于阈值触发回溯或人工介入
5. **可观测**：每一步的调用链、耗时、置信度对用户透明（通过 SSE 事件暴露）

### 2.2 架构：Orchestrator + Agent-as-Tool 模式

#### 2.2.1 为什么选 Orchestrator 而不是 Peer-to-Peer

| 模式 | 优点 | 缺点 | 适合场景 |
|---|---|---|---|
| **Orchestrator** | 集中决策、易控成本、可审计 | 单点瓶颈 | 任务可分解、有明确主次的场景 |
| **Peer Debate** | 多视角、鲁棒性高 | 成本高、收敛慢 | 高风险决策需多方制衡 |
| **Hierarchical** | 适合复杂任务分解 | 过度工程化 | 多步骤依赖的复杂 workflow |

Agent Pet 的场景是**用户发起对话 → 系统理解意图 → 调用工具 → 合成回复**，主次分明，Orchestrator 是最佳匹配。Peer Debate 可以作为 Phase 3 的高风险操作增强。

#### 2.2.2 新图拓扑

```
START
  │
  ▼
route (regex intent ── 不变)
  │
  ▼
semantic_analysis (LLM ── 不变，增加 confidence 字段)
  │
  ▼
orchestrator ◄─────────────────────────────┐
  │                                         │
  │  [评估当前状态，决定下一步]              │
  │                                         │
  ├── confidence ≥ threshold ──→ synthesizer → finish → END
  │
  ├── need retrieve ──→ memory_retrieval ──→ knowledge_retrieval ──┐
  │                                                    │            │
  │                                                    ▼            │
  │                                            orchestrator ◄──────┘
  │
  ├── need wiki ──────→ wiki_planner ──→ orchestrator
  │                           │
  │                     (生成 plan)
  │                     (用户确认后)
  │                           │
  │                           ▼
  │                      wiki_executor ──→ orchestrator
  │
  ├── need memory ─────→ memory_proposer ──→ memory_reviewer ──→ orchestrator
  │                           │                    │
  │                     (生成草案)           (自我审查)
  │                           │                    │
  │                           └──── 修正 ─────────┘
  │
  ├── need task ───────→ task_creator ──→ orchestrator
  │
  └── max_rounds ──────→ synthesizer (with fallback flag)
```

#### 2.2.3 核心组件

**Orchestrator 节点** (`agents/nodes/orchestrator.py`)

```python
class OrchestratorDecision(BaseModel):
    action: Literal["invoke_agent", "synthesize", "escalate_to_user"]
    agent: AgentId | None          # 要调用的 agent
    agent_input: str | None        # 传给 agent 的精炼输入
    reasoning: str                 # 为什么做这个决策
    confidence: float              # 当前累积置信度
    expected_outcome: str          # 期望从这个 agent 得到什么

class OrchestratorNode:
    def __init__(self, model, agent_registry, max_rounds=5, confidence_threshold=0.8):
        ...

    async def __call__(self, state: NegotiationState) -> dict:
        # 1. 检查是否达到最大轮次
        if state.round >= self.max_rounds:
            return {"decision": "synthesize", "fallback": True}

        # 2. 构建 orchestrator prompt（包含当前已收集的所有结果）
        prompt = self._build_context(state)

        # 3. LLM 决策下一步
        decision = await self._decide(prompt, state)

        # 4. 置信度足够 → 进入合成
        if decision.confidence >= self.confidence_threshold:
            return {"decision": "synthesize"}

        # 5. 置信度不够 → 调用下一个 agent
        return {"decision": "invoke_agent", "next_agent": decision.agent, ...}
```

**协商状态** (`agents/state.py` 扩展)

```python
class AgentInvocationResult(BaseModel):
    agent_id: AgentId
    round: int
    input_query: str
    output: Any
    confidence: float
    latency_ms: int
    tool_calls: list[str]

class NegotiationState(AgentState):
    round: int = 0
    max_rounds: int = 5
    confidence_threshold: float = 0.8
    invocation_history: list[AgentInvocationResult] = Field(default_factory=list)
    orchestrator_decisions: list[OrchestratorDecision] = Field(default_factory=list)
    collected_context: str = ""          # 聚合所有检索结果的文本
    pending_proposals: list[dict] = Field(default_factory=list)
    fallback_triggered: bool = False
```

**Agent 注册表** (`agents/registry.py`)

```python
@dataclass
class AgentCapability:
    agent_id: AgentId
    description: str          # 给 orchestrator 看的能力描述
    input_schema: str         # 期望的输入格式
    output_schema: str        # 产出的输出格式
    typical_latency_ms: int   # 典型耗时（用于 orchestrator 规划）
    can_retry: bool           # 失败后是否可以重试
    max_retries: int

class AgentRegistry:
    """所有 agent 的统一注册表，orchestrator 据此做调度决策"""
    def __init__(self):
        self._capabilities: dict[AgentId, AgentCapability] = {}
        self._handlers: dict[AgentId, Callable] = {}

    def register(self, capability: AgentCapability, handler: Callable): ...

    def describe_for_orchestrator(self) -> str:
        """生成给 orchestrator LLM 看的 agent 能力清单"""
        ...
```

**Synthesizer 节点** (`agents/nodes/synthesizer.py`)

```python
class SynthesizerNode:
    """聚合所有收集到的上下文，生成最终回复"""
    async def __call__(self, state: NegotiationState) -> dict:
        # 1. 按优先级排列 invocation_history 中的结果
        # 2. 压缩超长上下文（复用已有的压缩逻辑）
        # 3. 生成最终回复（使用 chat_agent 的模型）
        # 4. 如果 fallback_triggered，在回复末尾添加隐性质量标记
        ...
```

### 2.3 三个协商场景详解

#### 场景 A：多轮检索

用户问："我上次提到的那个关于 Python 性能优化的方案后来怎么样了？"

```
Round 0: route → SEARCH_MEMORY, semantic → needs_context=True
Round 1: orchestrator → invoke memory_retrieval("Python 性能优化方案")
         → 找到 3 条相关记忆，confidence=0.5
Round 2: orchestrator → 评估：记忆不够具体，需要查知识库
         → invoke knowledge_retrieval("Python 性能优化 方案 进展")
         → 找到 1 篇 Wiki 页面，confidence=0.75
Round 3: orchestrator → 置信度达到阈值 → synthesize
         → chat_agent 基于检索结果生成回复
```

#### 场景 B：记忆提案自我审查

用户说："帮我记一下，我不喜欢喝咖啡。"

```
Round 0: route → PROPOSE_MEMORY
Round 1: orchestrator → invoke memory_proposer("用户不喜欢喝咖啡")
         → 草案: {title: "饮食偏好", content: "用户不喜欢喝咖啡"}
         → confidence=0.6
Round 2: orchestrator → invoke memory_reviewer(草案)
         → review 结果: "内容正确，但建议归类到 Preferences/ 而非 Inbox/
            并检查是否与已有记忆冲突"
         → 检查已有偏好记忆，发现无冲突
Round 3: orchestrator → 修正草案，confidence=0.9 → synthesize
         → 用户看到的是已经过自我审查和修正的 proposal
```

#### 场景 C：Wiki 编辑质量内循环

用户说："把刚才讨论的部署流程整理到 Wiki。"

```
Round 0: route → MANAGE_WIKI
Round 1: orchestrator → invoke wiki_planner → 生成 ingest plan
         → plan: {target: "Wiki/Deploy/流程.md", sections: [...]}
Round 2: orchestrator → invoke wiki_executor(plan)
         → 生成页面草稿
Round 3: orchestrator → invoke wiki_reviewer(草稿)
         → 检查：缺少 frontmatter、有一个外链失效、section 顺序建议调整
Round 4: orchestrator → wiki_executor 修正 → wiki_reviewer 复检
         → confidence=0.9
Round 5: orchestrator → synthesize → 提交用户最终确认
```

### 2.4 SSE 事件扩展

为了让协商过程对用户透明，扩展 SSE 事件类型：

```python
class NegotiationStepEvent(BaseModel):
    """每一步协商都推送给前端"""
    event: Literal["negotiation_step"]
    agent_run_id: str
    round: int
    agent: str                    # 当前调用的 agent 名称
    action: str                   # "invoking" | "reviewing" | "revising" | "synthesizing"
    reasoning: str                # orchestrator 的决策理由（中文）
    confidence: float
    message: str                  # 用户可读的状态描述

class NegotiationDoneEvent(BaseModel):
    """协商完成，汇总统计"""
    event: Literal["negotiation_done"]
    total_rounds: int
    agents_invoked: list[str]
    total_latency_ms: int
    final_confidence: float
    fallback: bool
```

前端 `features/chat/` 的 SSE 分发器新增对这两个事件的处理，在聊天气泡中展示可折叠的"思考过程"（类似 ChatGPT 的 thinking 展开）。

### 2.5 成本控制

多轮协商意味着更多 LLM 调用。控制策略：

1. **硬上限**：`max_rounds=5`（可在设置中调整，范围 2-10）
2. **语义分析跳过**：regex intent 高置信度时跳过 LLM 语义分析（已有，保留）
3. **小模型优化**：orchestrator 决策和 reviewer 审查使用轻量模型（如 `gpt-4o-mini` 或 `deepseek-chat`），只有 chat_agent 最终合成使用主力模型
4. **缓存复用**：同一轮对话内，相同 query 的检索结果缓存
5. **成本统计**：每次协商完成后在 `agent_actions` 表中记录总 token 消耗和延迟，可通过 diagnostics API 查询

### 2.6 向后兼容

- 保留原有硬编码路由作为 **fast path**：当 semantic confidence ≥ 0.9 且 intent 为简单 CHAT 时，跳过 orchestrator，直接走 `chat_agent → finish`
- 新增 `use_negotiation` 设置项（默认开启），关闭后退化为原有 DAG 行为
- 原有测试全部保留，新增测试覆盖协商路径

### 2.7 实施步骤

#### Step 1：NegotiationState + AgentRegistry（2-3 天）

- 扩展 `AgentState` → `NegotiationState`
- 创建 `AgentRegistry` 和 `AgentCapability`
- 注册现有 7 个图节点 + 2 个后台 agent
- 不改图拓扑，纯基础设施

#### Step 2：Orchestrator 节点（3-4 天）

- 实现 `OrchestratorNode`
- 实现 orchestrator prompt（中文，包含 agent 能力清单和决策规则）
- 实现 `_select_agent_node` 的协商版本
- 单元测试覆盖各种决策路径

#### Step 3：Agent 包装为 Tool（2-3 天）

- 将 `_run_model_agent_with_tools` 泛化，使任意 agent 都可被 orchestrator 调用
- 统一 agent 输入输出格式
- 每个 agent 返回 `AgentInvocationResult`（含置信度）

#### Step 4：Review 闭环（2-3 天）

- 实现 `memory_reviewer` 节点（复用 chat_agent 模型 + 审查 prompt）
- 实现 `wiki_reviewer` 节点（复用 wiki_lint 的部分逻辑）
- 修改 memory_proposer 和 wiki_executor 支持 revision 参数

#### Step 5：图编译 + SSE 事件（2-3 天）

- 用新的协商图替换 `_build_graph()` 中的硬编码边
- 新增 `NegotiationStepEvent` 和 `NegotiationDoneEvent`
- 前端 SSE 分发器新增对应 handler
- 前端聊天气泡增加可折叠的"思考过程"

#### Step 6：成本与监控（1-2 天）

- `agent_actions` 表新增 `negotiation_rounds`、`total_tokens`、`total_latency_ms` 列
- diagnostics API 新增协商统计端点
- 设置页新增 `max_rounds` 和 `use_negotiation` 配置项

#### Step 7：测试与文档（2-3 天）

- 协商路径集成测试（模拟多轮检索、自我审查、fallback 场景）
- 成本控制测试（max_rounds 边界、fast path 走原有路由）
- 更新 `Development_Documentation.md` 和 `progress.md`

### 2.8 验收标准

- [ ] 用户问"我上次提到的 X 后来怎么样了"→ agent 自动执行多轮检索 → 合成回复
- [ ] 用户说"帮我记住 Y"→ agent 生成草案 → 自我审查 → 修正 → 提交确认
- [ ] 用户说"把 Z 整理到 Wiki"→ agent 生成 plan → 执行 → 审查 → 修正 → 提交确认
- [ ] 简单对话（"你好"）走 fast path，不触发协商
- [ ] 到达 max_rounds 后优雅终止，返回已有信息
- [ ] orchestrator 失败时退化到原有硬编码路由
- [ ] SSE 事件在前端显示可折叠的思考过程
- [ ] 协商统计可通过 diagnostics API 查询
- [ ] `use_negotiation=False` 时行为与当前版本完全一致
- [ ] 后端全量 `pytest` 通过
- [ ] 前端 `typecheck` + `build` + `package:check` 通过
- [ ] `runbook-smoke.ps1` 通过

---

## 3. Phase 3：未来方向（不纳入当前计划）

以下方向在 Phase 2 稳定后评估：

1. **Peer Debate 增强**：对高风险操作（删除记忆、覆盖 Wiki 页面），启动 2 个独立 agent 分别审查，结果不一致时升级到用户
2. **用户参与协商**：orchestrator 可以在 mid-loop 暂停并向用户提问（"我找到了 3 条相关记忆，你想看哪一条？"）
3. **协商策略学习**：记录用户对协商结果的确认/拒绝/修改行为，未来用这些数据微调 orchestrator 的决策偏好
4. **跨会话上下文继承**：跨对话的记忆检索结果可以预热下一轮对话的 orchestrator 上下文

---

## 4. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 多轮调用导致延迟显著增加 | 高 | 用户感知回复变慢 | fast path 保留；小模型做 orchestration；SSE 实时展示进度 |
| LLM 调用成本翻倍 | 高 | API 费用增加 | max_rounds 硬上限；小模型做 reviewer；成本统计面板 |
| orchestrator 决策质量不稳定 | 中 | 调错 agent 或死循环 | max_rounds 兜底；confidence_threshold 门控；回退到原有路由 |
| 前端复杂度增加 | 低 | 维护成本 | 协商事件只在 chat bubble 内折叠展示，不新增面板 |
| 与现有测试冲突 | 中 | 重构期间测试大面积挂 | Step 7 的兼容性测试；fast path 保证原有行为不变 |
