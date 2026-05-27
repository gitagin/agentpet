# Agent Pet 架构演进 — Agent 执行指令集

> 生成日期：2026-05-26
> 执行规则：按编号顺序执行，每条任务完成 VERIFY 后再执行下一条

---

## Task 1 · 新增模型健康检查 API

```
DEPENDS_ON: 无

FILES:
  MODIFY  apps/backend/app/api/settings.py
  MODIFY  apps/backend/app/services/settings_service.py
  CREATE  apps/backend/tests/api/test_model_health.py

INSTRUCTIONS:
  1. 在 settings.py 中新增路由 GET /api/settings/model-health，调用 settings_service.get_model_health_status()

  2. 在 settings_service.py 中实现 get_model_health_status()：
     - 查询 agent_model_configs 表，对每个 AgentId 判断配置来源：
         "agent_specific"    → 有独立配置且非默认值
         "global_fallback"   → 无独立配置但全局已配置
         "hardcoded_default" → 无独立配置且全局未配置
     - 返回 ModelHealthResponse：
         global_configured: bool
         agents_configured: int
         agents_fallback_to_global: int
         agents_fallback_to_default: int
         agent_details: list[AgentModelHealth]  # 每项含 agent_id / source / model

  3. 在 test_model_health.py 中编写：
     - test_health_all_default：无任何配置时 agents_fallback_to_default == 9
     - test_health_global_only：仅全局配置时 agents_fallback_to_global == 9
     - test_health_mixed：2 个独立配置时 agents_configured == 2

VERIFY:
  - [ ] GET /api/settings/model-health 返回 200
  - [ ] 响应包含上述所有字段
  - [ ] pytest test_model_health.py 全部通过
```

---

## Task 2 · 增强全局模型配置 API 响应

```
DEPENDS_ON: Task 1

FILES:
  MODIFY  apps/backend/app/api/settings.py
  MODIFY  apps/backend/app/schemas/settings.py

INSTRUCTIONS:
  1. 在 SettingsUpdateResponse schema 中新增字段：
       agents_using_global: int

  2. 修改 update_settings() 处理函数：
     - 完成更新后调用 get_model_health_status()
     - 将 agents_fallback_to_global 写入响应的 agents_using_global

VERIFY:
  - [ ] PATCH /api/settings 响应体包含 agents_using_global 字段
  - [ ] 值与 /api/settings/model-health 中的 agents_fallback_to_global 一致
  - [ ] 现有 settings 相关测试不回归
```

---

## Task 3 · 修复 reminder_scheduler 失败测试

```
DEPENDS_ON: 无（可与 Task 1、2 并行）

FILES:
  MODIFY  apps/backend/tests/  （定位具体文件后修改）

INSTRUCTIONS:
  1. 执行 pytest -x -q --tb=short 定位失败测试的完整路径和错误信息
  2. 阅读错误堆栈，判断是 fixture / mock / 逻辑 bug
  3. 修复根因（禁止用 pytest.mark.skip 绕过）

VERIFY:
  - [ ] pytest 全量运行 failed == 0
  - [ ] 不新增任何 skip 标记
```

---

## Task 4 · 前端：新增全局模型配置卡片

```
DEPENDS_ON: Task 1, Task 2

FILES:
  CREATE  apps/frontend/src/features/settings/components/GlobalModelCard.tsx
  MODIFY  apps/frontend/src/features/settings/SettingsPanel.tsx

INSTRUCTIONS:
  1. 创建 GlobalModelCard.tsx，包含：
     - 四个受控输入字段：provider / base_url / model / api_key
     - "测试连接"按钮：状态 idle → loading → success/error
     - "保存"按钮：调用 PATCH /api/settings，保存后 toast 提示
       "全局模型已更新，N 个智能体将使用此配置"（N 取自响应的 agents_using_global）
     - 使用项目现有的表单库，保持风格一致

  2. 修改 SettingsPanel.tsx：
     - 在 <AgentConfigForm /> 之前插入 <GlobalModelCard />
     - 两者之间添加分隔线

VERIFY:
  - [ ] 全局模型卡片在设置面板顶部正确渲染
  - [ ] 保存后 toast 中 N 值与后端一致
  - [ ] npm run typecheck 通过（0 新增错误）
```

---

## Task 5 · 前端：Agent 配置收入折叠面板

```
DEPENDS_ON: Task 4

FILES:
  MODIFY  apps/frontend/src/features/settings/components/AgentConfigForm.tsx
  MODIFY  apps/frontend/src/features/settings/SettingsPanel.tsx

INSTRUCTIONS:
  1. 在 AgentConfigForm.tsx 中，对每个 agent 配置行新增"使用全局模型"Toggle：
     - 开启时：四个字段设为 disabled，显示从全局配置继承的值
     - 开启时提交该 agent 配置为 null（后端解释为"使用全局"）

  2. 在 SettingsPanel.tsx 中用 Collapsible 包裹 <AgentConfigForm />：
     - defaultOpen={false}
     - 标题："独立智能体模型配置（高级）"
     - 副标题："留空则使用全局模型。你可以为不同智能体分配不同模型以优化成本和性能。"

VERIFY:
  - [ ] 设置面板首次加载时折叠面板处于收起状态
  - [ ] 点击标题可展开/收起
  - [ ] Toggle 开启后字段显示继承值且不可编辑
  - [ ] npm run typecheck 通过
```

---

## Task 6 · 前端：模型健康状态 Banner

```
DEPENDS_ON: Task 4

FILES:
  CREATE  apps/frontend/src/features/settings/components/ModelHealthBanner.tsx
  MODIFY  apps/frontend/src/features/settings/SettingsPanel.tsx

INSTRUCTIONS:
  1. 创建 ModelHealthBanner.tsx：
     - 挂载时调用 GET /api/settings/model-health
     - 根据返回值渲染对应状态（使用项目现有 Alert/Banner 组件）：

       条件 A：global_configured==false AND agents_configured==0
         → 橙色 "你还没有配置任何模型，请先配置全局模型以开始使用。"

       条件 B：global_configured==true AND agents_configured < 9
         → 蓝色 "${agents_fallback_to_global} 个智能体使用全局模型，
                  ${agents_configured} 个有独立配置。"

       条件 C：agents_configured==9
         → 绿色 "所有智能体已独立配置。"

     - 加载中显示 Skeleton，请求失败静默不渲染

  2. 修改 SettingsPanel.tsx：
     - 在面板最顶部（GlobalModelCard 之上）插入 <ModelHealthBanner />

VERIFY:
  - [ ] 三种状态下 Banner 颜色和文案正确
  - [ ] 网络失败时页面无报错
  - [ ] npm run typecheck 通过
```

---

## Task 7 · AgentToolSet 分级超时

```
DEPENDS_ON: 无（可与 Task 1-6 并行）

FILES:
  MODIFY  apps/backend/app/agents/tool_set.py
  MODIFY  apps/backend/app/agents/exceptions.py
  CREATE  apps/backend/tests/agents/test_tool_timeouts.py

INSTRUCTIONS:
  1. 在 exceptions.py 中新增：
       class AgentToolTimeoutError(AgentError):
           def __init__(self, tool_name: str, timeout_seconds: int):
               super().__init__(f"Tool '{tool_name}' timed out after {timeout_seconds}s")
               self.tool_name = tool_name
               self.timeout_seconds = timeout_seconds

  2. 在 tool_set.py 中定义超时映射：
       TOOL_TIMEOUTS = {
           "search_memory": 5,
           "propose_memory": 10,
           "plan_wiki_ingest": 15,
           "plan_wiki_query_archive": 10,
           "plan_wiki_synthesis": 15,
           "plan_wiki_lint": 20,
           "manage_wiki_page": 10,
           "create_task": 10,
       }

  3. 对每个工具函数，用以下模式包裹核心调用：
       timeout = TOOL_TIMEOUTS.get(tool_name, settings.model_timeout_seconds)
       try:
           result = await asyncio.wait_for(_execute_tool_logic(...), timeout=timeout)
       except asyncio.TimeoutError:
           raise AgentToolTimeoutError(tool_name, timeout)

  4. 在 test_tool_timeouts.py 中：
     - mock 工具逻辑 sleep 超出各自 timeout
     - 验证抛出 AgentToolTimeoutError 且 tool_name 字段正确

VERIFY:
  - [ ] pytest test_tool_timeouts.py 全部通过
  - [ ] 超时错误消息包含工具名称和超时秒数
  - [ ] 原有工具测试不回归
```

---

## Task 8 · Phase 1 验收检查

```
DEPENDS_ON: Task 1, 2, 3, 4, 5, 6, 7

INSTRUCTIONS:
  按顺序执行以下命令，全部通过后 Phase 1 完成：
  1. cd apps/backend && pytest --tb=short -q
  2. cd apps/frontend && npm run typecheck
  3. cd apps/frontend && npm run build

VERIFY:
  - [ ] pytest: 0 failed
  - [ ] typecheck: 0 errors
  - [ ] build: exit code 0
```

---

## Task 9 · 扩展 AgentState → NegotiationState

```
DEPENDS_ON: Task 8

FILES:
  MODIFY  apps/backend/app/agents/state.py
  CREATE  apps/backend/tests/agents/test_negotiation_state.py

INSTRUCTIONS:
  1. 在 state.py 中新增：

     class AgentInvocationResult(BaseModel):
         agent_id: AgentId
         round: int
         input_query: str
         output: Any
         confidence: float      # 0.0 ~ 1.0
         latency_ms: int
         tool_calls: list[str]

     class NegotiationState(AgentState):
         round: int = 0
         max_rounds: int = 5
         confidence_threshold: float = 0.8
         invocation_history: list[AgentInvocationResult] = Field(default_factory=list)
         orchestrator_decisions: list = Field(default_factory=list)
         collected_context: str = ""
         pending_proposals: list[dict] = Field(default_factory=list)
         fallback_triggered: bool = False

  2. AgentState 保持不变，NegotiationState 继承它，不破坏已有路径

  3. 在 test_negotiation_state.py 中验证：
     - 默认值正确
     - invocation_history 可 append AgentInvocationResult
     - NegotiationState 是 AgentState 的子类

VERIFY:
  - [ ] pytest test_negotiation_state.py 通过
  - [ ] 原有 state 相关测试不回归
```

---

## Task 10 · 实现 AgentRegistry

```
DEPENDS_ON: Task 9

FILES:
  CREATE  apps/backend/app/agents/registry.py
  CREATE  apps/backend/tests/agents/test_registry.py

INSTRUCTIONS:
  1. 创建 registry.py：

     @dataclass
     class AgentCapability:
         agent_id: AgentId
         description: str        # 中文，供 orchestrator LLM 理解
         input_schema: str
         output_schema: str
         typical_latency_ms: int
         can_retry: bool
         max_retries: int

     class AgentRegistry:
         def register(self, capability: AgentCapability, handler: Callable): ...
         def get_handler(self, agent_id: AgentId) -> Callable: ...
         def describe_for_orchestrator(self) -> str:
             # 返回所有 agent 能力的 Markdown 清单，供 orchestrator prompt 使用
             # 格式示例：
             # ## memory_retrieval_agent
             # 功能：检索用户记忆库，支持全文和语义搜索
             # 输入：搜索关键词字符串
             # 输出：相关记忆列表（title / content / relevance_score）
             # 典型延迟：800ms

  2. 在 registry.py 底部注册现有 9 个 agent，填写各自中文描述

  3. 在 test_registry.py 中验证：
     - 9 个 agent 都已注册
     - describe_for_orchestrator() 返回非空字符串且包含所有 agent_id

VERIFY:
  - [ ] pytest test_registry.py 通过
  - [ ] describe_for_orchestrator() 输出包含全部 9 个 AgentId 字符串
```

---

## Task 11 · 实现 OrchestratorNode

```
DEPENDS_ON: Task 10

FILES:
  CREATE  apps/backend/app/agents/nodes/orchestrator.py
  CREATE  apps/backend/tests/agents/nodes/test_orchestrator.py

INSTRUCTIONS:
  1. 创建 orchestrator.py：

     class OrchestratorDecision(BaseModel):
         action: Literal["invoke_agent", "synthesize", "escalate_to_user"]
         agent: AgentId | None
         agent_input: str | None
         reasoning: str
         confidence: float       # LLM 自评当前信息完整度 0.0~1.0
         expected_outcome: str

     class OrchestratorNode:
         def __init__(self, model, agent_registry, max_rounds=5, confidence_threshold=0.8): ...

         async def __call__(self, state: NegotiationState) -> dict:
             if state.round >= self.max_rounds:
                 return {"next": "synthesize", "fallback_triggered": True}
             prompt = self._build_prompt(state)
             decision = await self._call_llm(prompt)   # 要求 LLM 只返回 JSON
             if decision.confidence >= self.confidence_threshold:
                 return {"next": "synthesize", "orchestrator_decisions": [...]}
             return {"next": "invoke_agent", "next_agent": decision.agent,
                     "agent_input": decision.agent_input, "orchestrator_decisions": [...]}

         def _build_prompt(self, state) -> str:
             # 必须包含：
             # 1. 用户原始消息
             # 2. collected_context 摘要
             # 3. invocation_history（agent 名称 + 输出摘要 + confidence）
             # 4. agent_registry.describe_for_orchestrator() 能力清单
             # 5. 中文决策规则：
             #    "你是一个任务协调器。根据已有信息判断是否足够回复用户。
             #     如果信息足够（confidence >= 0.8），返回 action=synthesize。
             #     如果需要更多信息，选择最合适的 agent 并精炼输入 query。
             #     禁止用相同 query 重复调用同一 agent。
             #     只返回 JSON，不要有任何前缀或 markdown 代码块。"

  2. 在 test_orchestrator.py 中用 mock LLM 测试：
     - confidence=0.9 → next=="synthesize"
     - confidence=0.4 → next=="invoke_agent"
     - round >= max_rounds → next=="synthesize" + fallback_triggered==True
     - _build_prompt 输出包含 registry 中的 agent 名称

VERIFY:
  - [ ] pytest test_orchestrator.py 4 个用例全部通过
  - [ ] 达到 max_rounds 时 fallback_triggered==True
```

---

## Task 12 · 泛化 Agent 调用接口

```
DEPENDS_ON: Task 11

FILES:
  CREATE  apps/backend/app/agents/agent_runner.py
  CREATE  apps/backend/tests/agents/test_agent_runner.py

INSTRUCTIONS:
  1. 创建 agent_runner.py：

     async def run_agent(
         agent_id: AgentId,
         input_query: str,
         state: NegotiationState,
         registry: AgentRegistry,
     ) -> AgentInvocationResult:
         start = time.monotonic()
         handler = registry.get_handler(agent_id)
         try:
             output = await handler(input_query, state)
             confidence = output.get("confidence") or (0.6 if output.get("results") else 0.0)
         except Exception as e:
             output = {"error": str(e)}
             confidence = 0.0
         latency_ms = int((time.monotonic() - start) * 1000)
         return AgentInvocationResult(
             agent_id=agent_id, round=state.round, input_query=input_query,
             output=output, confidence=confidence, latency_ms=latency_ms, tool_calls=[]
         )

  2. 在 test_agent_runner.py 中：
     - mock handler 返回含 confidence 的 dict，验证 AgentInvocationResult 字段正确
     - mock handler 抛出异常，验证 confidence==0.0 且 output 包含 error 键

VERIFY:
  - [ ] pytest test_agent_runner.py 通过
  - [ ] AgentInvocationResult.latency_ms > 0
```

---

## Task 13 · 实现 memory_reviewer 节点

```
DEPENDS_ON: Task 12

FILES:
  CREATE  apps/backend/app/agents/nodes/memory_reviewer.py
  MODIFY  apps/backend/app/agents/nodes/memory_proposal_agent.py
  CREATE  apps/backend/tests/agents/nodes/test_memory_reviewer.py

INSTRUCTIONS:
  1. 创建 memory_reviewer.py：
     - 接受 draft: dict 和 existing_memories: list
     - 调用 LLM（复用 chat_agent 模型配置），审查四个维度：
         a. 内容准确性
         b. 分类合理性（归档路径是否合适）
         c. 冲突检查（与 existing_memories 是否重复或矛盾）
         d. 格式完整性（title / content / tags 是否齐全）
     - 返回 MemoryReviewResult：
         approved: bool
         revised_draft: dict | None
         review_notes: str
         confidence: float

  2. 修改 memory_proposal_agent.py：
     - 支持可选参数 revision_notes: str
     - 有 revision_notes 时追加到 prompt 要求据此修正草案

  3. 在 test_memory_reviewer.py 中：
     - mock LLM 返回 approved=True → revised_draft 为 None
     - mock LLM 返回 approved=False → revised_draft 包含修正内容

VERIFY:
  - [ ] pytest test_memory_reviewer.py 通过
  - [ ] memory_proposal_agent 传入 revision_notes 时 prompt 包含该内容
```

---

## Task 14 · 实现 wiki_reviewer 节点

```
DEPENDS_ON: Task 12

FILES:
  CREATE  apps/backend/app/agents/nodes/wiki_reviewer.py
  MODIFY  apps/backend/app/agents/nodes/wiki_manager_agent.py
  CREATE  apps/backend/tests/agents/nodes/test_wiki_reviewer.py

INSTRUCTIONS:
  1. 创建 wiki_reviewer.py：
     - 接受 draft_content: str 和 plan: dict
     - 复用现有 wiki_lint 逻辑，补充 LLM 审查：
         a. frontmatter 完整性（title / date / tags）
         b. 外链格式有效性（仅检测格式，不发网络请求）
         c. section 结构是否符合 plan 中的 sections 规划
         d. 内容与对话上下文的一致性
     - 返回 WikiReviewResult：
         approved: bool
         issues: list[str]
         revised_content: str | None
         confidence: float

  2. 修改 wiki_manager_agent.py（executor 部分）：
     - 支持可选参数 revision_issues: list[str]
     - 有 revision_issues 时在 prompt 中列出问题并要求逐一修正

  3. 在 test_wiki_reviewer.py 中：
     - mock 缺少 frontmatter 的草稿 → issues 包含 frontmatter 相关条目
     - mock 完整草稿 → approved=True，confidence >= 0.8

VERIFY:
  - [ ] pytest test_wiki_reviewer.py 通过
  - [ ] 缺少 frontmatter 的草稿触发对应 issue
```

---

## Task 15 · 编译协商图，替换硬编码 DAG

```
DEPENDS_ON: Task 11, 12, 13, 14

FILES:
  CREATE  apps/backend/app/agents/negotiation_graph.py
  MODIFY  apps/backend/app/agents/graph_runtime.py

INSTRUCTIONS:
  1. 创建 negotiation_graph.py，实现 build_negotiation_graph()：
     - 节点：route → semantic_analysis → orchestrator → [各 agent] → synthesizer → finish
     - orchestrator 通过条件边路由到各 agent，或直接到 synthesizer
     - 每个 agent 执行后回到 orchestrator（循环边）
     - synthesizer：聚合 collected_context，调用 chat_agent 模型生成最终回复

  2. 修改 graph_runtime.py：
     - 新增 _should_use_fast_path(state) → bool：
         条件：semantic_confidence >= 0.9 AND intent in (CHAT,) AND round == 0
     - fast_path=True → 走原有 chat_agent → finish（硬编码路由保留不动）
     - fast_path=False → 走 negotiation_graph
     - 读取 settings.use_negotiation（bool，默认 True）
       use_negotiation=False → 强制走原有硬编码路由

VERIFY:
  - [ ] use_negotiation=False 时原有全部测试通过（0 回归）
  - [ ] fast_path 场景不触发 orchestrator
  - [ ] orchestrator 最多被调用 max_rounds 次
```

---

## Task 16 · 新增 SSE 协商事件

```
DEPENDS_ON: Task 15

FILES:
  MODIFY  apps/backend/app/agents/events.py
  MODIFY  apps/backend/app/agents/graph_runtime.py
  MODIFY  apps/frontend/src/features/chat/hooks/useChatStream.ts
  MODIFY  apps/frontend/src/features/chat/components/MessageBubble.tsx

INSTRUCTIONS:
  1. 后端 events.py 新增事件类型：

     NegotiationStepEvent:
       event: "negotiation_step"
       agent_run_id: str
       round: int
       agent: str
       action: "invoking" | "reviewing" | "revising" | "synthesizing"
       reasoning: str    # 中文，orchestrator 决策说明
       confidence: float
       message: str      # 用户可读状态，如"正在检索记忆库…"

     NegotiationDoneEvent:
       event: "negotiation_done"
       total_rounds: int
       agents_invoked: list[str]
       total_latency_ms: int
       final_confidence: float
       fallback: bool

  2. 后端 graph_runtime.py：
     - orchestrator 每次决策后推送 NegotiationStepEvent
     - synthesizer 完成后推送 NegotiationDoneEvent

  3. 前端 useChatStream.ts：
     - 新增对 "negotiation_step" 和 "negotiation_done" 的 handler
     - 将事件数据存入当前消息的 negotiationSteps 字段

  4. 前端 MessageBubble.tsx：
     - 若消息有 negotiationSteps，渲染可折叠"思考过程"区域
     - 折叠时显示："已思考 N 步"
     - 展开时按 round 顺序列出：[agent 名称] · [action] · [message]
     - 显示 final_confidence 百分比

VERIFY:
  - [ ] 协商路径执行时前端收到 negotiation_step 事件
  - [ ] MessageBubble 折叠区域可展开/收起
  - [ ] fast_path 消息无"思考过程"区域
  - [ ] npm run typecheck 通过
```

---

## Task 17 · 数据库迁移：协商统计字段

```
DEPENDS_ON: Task 15

FILES:
  CREATE  apps/backend/alembic/versions/xxxx_add_negotiation_stats.py
  MODIFY  apps/backend/app/models/agent_action.py
  MODIFY  apps/backend/app/api/diagnostics.py

INSTRUCTIONS:
  1. 创建 Alembic migration，新增三列：
       ALTER TABLE agent_actions ADD COLUMN negotiation_rounds INTEGER DEFAULT 0;
       ALTER TABLE agent_actions ADD COLUMN total_tokens INTEGER DEFAULT 0;
       ALTER TABLE agent_actions ADD COLUMN total_latency_ms INTEGER DEFAULT 0;

  2. 修改 agent_action.py ORM model 新增对应字段

  3. 协商完成后将 NegotiationDoneEvent 统计数据写入 agent_actions

  4. 在 diagnostics.py 新增 GET /api/diagnostics/negotiation-stats，返回：
       avg_rounds: float
       avg_latency_ms: float
       fallback_rate: float          # fallback 次数 / 总协商次数
       top_agents_invoked: list[str] # 被调用最多的 3 个 agent

VERIFY:
  - [ ] alembic upgrade head 成功
  - [ ] GET /api/diagnostics/negotiation-stats 返回 200
  - [ ] 协商完成后 agent_actions 记录中 negotiation_rounds > 0
```

---

## Task 18 · 前端：设置页新增协商配置项

```
DEPENDS_ON: Task 5, Task 15

FILES:
  MODIFY  apps/backend/app/schemas/settings.py
  MODIFY  apps/backend/app/api/settings.py
  MODIFY  apps/frontend/src/features/settings/SettingsPanel.tsx

INSTRUCTIONS:
  1. 后端 Settings schema 新增：
       use_negotiation: bool = True
       max_rounds: int = Field(default=5, ge=2, le=10)

  2. PATCH /api/settings 支持更新这两个字段

  3. 前端在 Task 5 的折叠面板内新增：
     - "多轮协商" Toggle（对应 use_negotiation）
       描述："开启后 Agent 将自动执行多轮检索和自我审查，提升回复质量，但可能增加响应时间"
     - "最大协商轮次" 数字输入（范围 2-10，步长 1）
       仅在 use_negotiation==true 时可编辑

VERIFY:
  - [ ] use_negotiation=false 后图走原有路由
  - [ ] max_rounds 超出 [2,10] 范围时后端返回 422
  - [ ] npm run typecheck 通过
```

---

## Task 19 · Phase 2 集成测试

```
DEPENDS_ON: Task 9 ~ Task 18

FILES:
  CREATE  apps/backend/tests/integration/test_negotiation_flow.py

INSTRUCTIONS:
  编写以下 5 个集成测试（使用项目现有 test client 和 mock LLM fixtures）：

  test_multi_round_retrieval:
    - mock memory_retrieval 第一次返回 confidence=0.5
    - mock knowledge_retrieval 第二次返回 confidence=0.85
    - 验证最终响应包含两次检索的聚合内容
    - 验证 negotiation_rounds == 2

  test_memory_proposal_self_review:
    - mock memory_proposer 返回草案 + confidence=0.6
    - mock memory_reviewer 返回 approved=False + revised_draft
    - 验证最终 proposal 使用 revised_draft 内容
    - 验证 negotiation_rounds == 2

  test_wiki_edit_quality_loop:
    - mock 顺序：wiki_planner → wiki_executor → wiki_reviewer(有 issues) → wiki_executor(修正)
    - 验证最终提交给用户的是修正后内容

  test_max_rounds_fallback:
    - mock orchestrator 始终返回 confidence=0.3
    - 验证恰好在 max_rounds 轮后终止
    - 验证 fallback_triggered == True

  test_fast_path_bypasses_orchestrator:
    - 发送"你好"，mock semantic_analysis 返回 intent=CHAT + confidence=0.95
    - 验证 orchestrator 节点未被调用

VERIFY:
  - [ ] pytest test_negotiation_flow.py 5 个用例全部通过
```

---

## Task 20 · Phase 2 验收检查

```
DEPENDS_ON: Task 19

INSTRUCTIONS:
  按顺序执行以下命令：
  1. cd apps/backend && alembic upgrade head
  2. cd apps/backend && pytest --tb=short -q
  3. cd apps/frontend && npm run typecheck
  4. cd apps/frontend && npm run build
  5. cd apps/frontend && npm run package:check  （如命令存在）
  6. pwsh ./runbook-smoke.ps1  （如环境支持）

VERIFY:
  - [ ] pytest: 0 failed
  - [ ] typecheck: 0 errors
  - [ ] build: exit code 0
  - [ ] smoke test 通过
  - [ ] 思考过程气泡可正常折叠/展开
  - [ ] GET /api/diagnostics/negotiation-stats 返回有效数据
```
