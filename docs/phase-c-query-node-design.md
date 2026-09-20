# 阶段 C 设计：新鲜度状态机 + 上下文替换 + 深读模式 + Evidence Gate 完整化（C3/T25）

- 作者：eng2-a（AgentTeams）
- 日期：2026-09-20
- 输入：c1 盘点（docs/t23-phase-c-query-gate-recon.md，20 条 file:line 事实）、c2 调研（docs/t24-c2-freshness-context-deepread-research.md，15 条结论）、代码复核（agents/nodes/wiki_retrieval.py、agents/retrieval/wiki_gate.py、agents/nodes/chat.py:205-265、agents/state.py:97、services/wiki/source_watermark.py、services/wiki/snapshot_reader.py:172-196、services/wiki/ingest.py:35-48）
- 状态：设计稿（C4 实现评审；字段名/数据落点按既有 schema 调整，不机械照搬）

---

## 0. 目标与非目标

**目标**：把恒 `unknown` 的 freshness 维度做成可判定状态机（fresh/unknown/stale），打通「新来源登记→相关性待检查→检查触发」链；引入证据价值函数（相关性×新鲜度×覆盖面）与预算满时的低价值替换，保证「预算满时高价值证据可读第九页」；参数化均衡/深读两档；Evidence Gate 五维中 freshness 成为独立确定性门。

**非目标**：不重建检索（FTS/向量/投影不动）；不切换默认聊天路由（仍 Shadow 路径）；不改 API 契约（仅新增可选字段/内部状态值，机器值英文、UI 映射中文）；隐私/权限门（authorize/RecallPermissions 管线）不受影响；不引入新常驻服务/后台队列守护进程（登记链以既有同步链 + 惰性检查落地，异步队列列为后续）。

---

## 1. 新鲜度状态机

### 1.1 机器值（英文，UI 映射中文）

| 机器值 | UI 文案 | 判定条件（按序短路） |
| --- | --- | --- |
| `fresh` | 资料为当前版本 | source 行验证记录有效（verification_status='verified'）且 expires_at 未过，且本次查询 source_observation ∈ {unchanged_since_capture, not_checked}，且无撤销（revoked_at IS NULL） |
| `unknown` | 新鲜度尚未确认 | 无验证记录（verification_status != 'verified'）或 freshness_reason=source_relevance_check_pending 尚未消解；**不假设无变化**（保留现有 ASSESSMENT_POLICY 语义 wiki_gate.py:77） |
| `stale` | 资料可能已经过时 | expires_at 已过，或查询期 source_observation=changed_since_capture，或该来源行/绑定在捕获后被遗忘/撤销/更新（watermark bindings 维度已可感知） |

- 落点（**内部状态，不进 API 模型**）：`WikiEvidenceGate.freshness: Literal["fresh","unknown","stale"]`（wiki_gate.py:52 由恒 "unknown" 扩展）；`freshness_reason` 字符串域在同一 enum 风格下扩展（既有 "new_source_relevance_watermark_unavailable" / "source_relevance_check_pending" 保留，新增 "source_verified_current" / "source_expired" / "source_changed_since_capture" / "source_observation_changed"）。
- **与 source_observation/watermark 的关系（复用 + 最小扩展，两维分离）**：
  - source_observation（三值，snapshot_reader.py:190-195）与 watermark（source_watermark.py:12-20，观测摘要）**保持原义不动**：水位线=查询开始快照，「变了」≠「过时」，只是新鲜度判定的输入之一（c2 #2）；
  - freshness 是**逐来源语义维度**：由 wiki_sources 既有列（035 已加 verification_status/verified_at/expires_at/revoked_at）+ 查询期 observation + binding 状态导出，**不新增表、不新增列**（最小扩展原则）；无验证记录 → unknown，expires 过期或观测变化 → stale。
- 来源级（非 vault 级）判定：freshness 计算按 citation 的根来源（citations 携带 wiki_generation/relative_path，经 binding→source 归属解析，复用 memory_closure 解析链），未来才需要来源级水印（c1 §3.2 缺口登记，C 阶段不建新表）。

### 1.2 新来源登记 → 相关性待检查 → 检查触发链

现状链**不存在**（c1 事实 15/19：compile 同步于 ingest.py:35-48，无队列/事件）。设计（最小可行链）：

1. **登记点** = ingest apply/publish 成功时（既有链）：新来源行已含 verification_status='unverified'（035 默认）；在 publish receipt（generations.py:169-178 / ingest.py:657-665 的 result_json.publication）写入 `freshness:"unknown"` + `freshness_reason:"source_relevance_check_pending"`——**复用现有 JSON 域，无新表**。
2. **待检查标记** = `verification_status='unverified'` + `expires_at IS NULL`（035 列作状态位）；查询期节点读取该标记并把 gate.freshness 置 unknown（现状 :111-112 已近似，仅需把 reason 语义从「有观察」改为「该来源登记待核」）。
3. **检查触发链（异步化，无新常驻服务）**：
   - **推荐：惰性 + 复用编译链**——查询遇 unknown 且预算允许时，对该来源执行**有界**相关性核查（单来源 read_source/read_snapshot 类轻量调用，预算上限 = 剩余字符/时间的一半，结果写 verification_status='verified' 或保留 unverified + 记录 last_checked_at）；核查结果在本轮 gate 生效（fresh→fresh / 依然无法判定→unknown 保持）。
   - **备选（后续）**：真正异步 compiler 队列（来源到达 → 队列 → 后台 compile_source），需要新常驻服务/调度，C 阶段明确不引入（边界 §5）。
4. **UI 映射落地（仅前端文案，机器值英文）**：gate JSON 注入已有字段 freshness/freshness_reason（chat.py:232-239 注入链不变）；前端/展示层按 1.1 表映射中文三文案；SSE 无新字段。

---

## 2. 上下文替换（价值函数 + 预算满时高价值证据可读第九页）

### 2.1 价值函数

`V(citation) = relevance(c) × freshness(c) × coverage(c)`

| 因子 | 计算 | 依据 |
| --- | --- | --- |
| relevance | 检索得分归一化（bm25/双路聚合得分，snapshot_reader.py:126-141 已有）；模型 assessment 判 supported 的引用额外 +0.15（评估是建议性，不改权威） | c2 #1（recency prior 思想扩展） |
| freshness | fresh=1.0；unknown=0.6（默认降级不信任，c2 #5）；stale=0.2（recency prior 半衰期风格，c2 #1/#8） | 最简三档权重，无连续半衰期复杂度 |
| coverage | citation 被 assessment 引用于 supported 问题=1.0；仅 partial=0.8；未被评估=0.7 | 与现有 coverage 赋值（apply_assessment :133-141）同源 |

- **token 记账**：字符预算（remaining=12000，wiki_retrieval.py:35）保持为**读预算**（读页字符）；新增**上下文预算**=注入预算（assessment_input 携带的全部 citations 序列化后的字符数，跨轮累计 additive :88-95）。两个预算独立计账，替换只发生在上下文预算侧。
- **与 12000 字符预算的关系**：12000 是「读」的上限；上下文预算 = min(注入预算上限, 读预算剩余) —— 保证已读高价值证据全部可入上下文；替换掉的是低价值 citation 的快照内容（不重读、不入下一轮 assessment_input）。

### 2.2 替换规则（子模打包，c2 #8/#9/#10）

- **触发**：上下文预算将满（注入 > 上限×0.9）且新验收候选 V ≥ 当前最低 V。
- **替换对象**：未进入 assessment 引用集的 citation（supported/conflict 引用**钉住不可替换**，与 parse_assessment 的 quote 校验 :117-121 一致）；同 (path,section) 去重后按 V 升序替换。
- **摆放**：替换后按 V 降序重排注入（高价值放开头/结尾，位置偏差缓解，c2 #10）。
- **保证「预算满时高价值证据可读第九页」**：搜索候选至多 24（top_k=24），首轮只读前 8（pending[:8] :53）；第 9 页仅在**其 V 高于已持有 8 页中最低 V 且上下文预算允许**时被读入——实现 = 阅读循环的 pending 准入改为「预算预检 + 价值预检」（:61-63 预算检查旁新增价值检查）；替换保证上下文预算不因第 9 页而挤掉高价值旧证据。验收测试 = 构造 8 份低价值 + 1 份高价值（bm25 高分 + fresh），断言第 9 页入上下文且低价值第 1 页被替换出注入（引用仍可被覆盖性问题追踪）。

---

## 3. 深读模式（均衡/深读参数化）

### 3.1 配置档位（参数对象，替代全部内联常量 :34-35/:47/:53/:55/:84-86）

```python
@dataclass(frozen=True)
class ReadProfile:
    mode: Literal["balanced", "deep"]
    max_pages: int          # 首轮 pending 上限
    max_depth: int          # 链接扩跳深度
    max_rounds: int         # 评估轮数
    deadline_sec: float     # 整体时间预算
    budget_chars: int       # 读字符预算
```

| 参数 | 均衡（默认，= 现状） | 深读（显式开启） |
| --- | --- | --- |
| max_pages | 8（:53） | 24（= top_k 上限） |
| max_depth | 2（:84-86） | 3 |
| max_rounds | 3（:55） | 6 |
| deadline_sec | 30（:34） | 90 |
| budget_chars | 12000（:35） | 32000 |

- 模式来源：查询请求显式深读标记（可选字段，默认 balanced **不进默认路由**）；或节点内升级路由（RASER 风格 c2 #11）：balanced 轮内出现未消解 conflict 或 coverage 缺口且时间/字符剩余 ≥ 40% → 升级一档（单次升级，不自动升级到 max）。

### 3.2 停止条件（综合时间/token/覆盖缺口/冲突）

- 保留既有 11 种 stop_reason（c1 事实 8）不变，新增语义：
  - `coverage_gap_requires_deep_read`：balanced 模式评估出现 missing 问题且允许升级 → 升级深读继续；不允许升级（非深读请求）→ 以该原因停止并保留 partial 状态；
  - `conflict_exhausted_escalation`：深读模式仍无法消解 conflict（disputed 保持）→ 停止（不无限扩展，防晒屏）；
  - token 记账（c2 #14）：深读档以「effective token 成本」约束评估轮次（max_rounds 之外再加注入累计预算上限，防止多轮 assessment_input 膨胀——现状 additive :88-95 无此上限，深读必须加）。
- 覆盖缺口驱动（c2 #12）：next_reads 由评估给出（模型输出，strict），节点只做预算/范围约束；深读档扩大 allowed_paths 同源（已知邻居深度≤3）。

---

## 4. Evidence Gate：freshness 独立门接入 AgentState

### 4.1 数据落点

- `AgentState.wiki_evidence_gate`（state.py:97）字段类型扩展：`freshness: Literal["fresh","unknown","stale"]`、`freshness_reason` 域扩展、新增内部字段 `freshness_checked_at`（可选，不进注入 JSON）。
- **freshness 与 authority 同级：确定性、模型不可设置**——模型 schema 仍只有 WikiAssessment 树（wiki_gate.py:44-47），GatePayload extra="forbid" 保证模型无法写入 freshness；赋值点仅节点（freshness 判定函数在节点内、与 authority :145/:148/:169/:174 同模式）。

### 4.2 门的行为变化（最小收紧）

| 场景 | 现状 | 设计后 |
| --- | --- | --- |
| freshness=unknown 且 coverage=complete 且无 conflict | supplement 跳过条件恒不满足（:245-246 因 unknown 恒走 fallback） | **保持走 fallback**（unknown 不能证明充分，c2 #5）；补充后 freshness 仍 unknown，回答提示语明确「新鲜度尚未确认」 |
| freshness=stale | 不存在 | 强制标注（gate JSON 注入已有名目）+ 对 stale 来源 citation 不再参与「model_assessed_complete」supplement 跳过（视为不足） |
| freshness=fresh | 不存在 | supplement 跳过条件恢复为可满足（coverage=complete 且无冲突时跳过 fallback）——这是未知→可确认后的唯一行为放宽，须在状态文档登记 |
| coverage/conflict | 模型输出 + 五重硬校验 | **不变**（strict 模型输出，wiki_gate.py:111-130 全套保留） |

### 4.3 回答组装注入（chat.py:218-257 不变式）

- gate JSON 注入（:232-239）自动携带新 freshness 值（model_dump_json 同字段名）；提示语中「unknown freshness」措辞扩展为三态（fresh="资料为当前版本"类限定语由模型按 gate 值生成；机器值与 UI 文案映射见 §1.1）；
- used_for_answer 一致性（:220-231）、assessment 详情注入（:240-257）不动。

---

## 5. 边界与不做什么

1. **不重建检索**：FTS/wiki_body_fts/向量/投影全不动；候选聚合（snapshot_reader.py:126-141）不动。
2. **不切换默认聊天路由**：仍 Shadow 路径（shadow.py:241-265 评测管线不变，ShadowMetrics 扩展 freshness 计数三个可观测字段：fresh/unknown/stale 出现次数与替换次数——纯内部指标）。
3. **不改 API 契约**：无新 API 字段（freshness 仅 gate 内部 JSON，gate 不属 API 响应模型）；如 C5 需暴露深读模式，按「可选字段默认缺省」模式新增，与阶段 A/B 同法。
4. **隐私/权限门不受影响**：authorize/factory.py:506-536、RecalcPermissions 管线、vault scope 门（:27-29）全部不动；freshness 只读这些门的结果，不改变它们。
5. **不引入常驻服务**：检查触发链 = 登记（复用 receipt JSON）+ 惰性查询期核查；异步编译器队列列为后续独立工作。
6. **状态机器值英文**（fresh/unknown/stale 及既有 observation 三值等），UI 映射中文（§1.1 表）；错误码/枚举/JSON key 零改动。

---

## 6. 测试锚点（复用 c1 §5 夹具，C4 落地）

| 用例 | 夹具/位置 | 断言 |
| --- | --- | --- |
| freshness 三态派生 | test_wiki_source_watermark.py 模式（水印+binding 维度） | unverified→unknown；expires_at 过去→stale；verified+未变→fresh |
| 新来源登记链 | published fixture + confirm/review/apply | apply 后 receipt.freshness=unknown+reason=source_relevance_check_pending；惰性核查后 verified |
| 第九页保证 | test_wiki_query_node.py graph() 构造 9+ 页 | 预算满场景下高价值第 9 页入上下文、低价值被替换且替换计数>0 |
| 深读档位 | test_wiki_query_node.py + shadow 评测 | balanced=8/2/3/30s/12000；deep=24/3/6/90s/32000；升级路由仅一次 |
| freshness 门不可模型设置 | test_wiki_gate.py 模式 | 模型输出含 freshness 键 → extra=forbid 拒绝；gate JSON 注入含三态文案对应机器值 |
| supplement 三态路径 | test_wiki_vault_fallback.py | unknown 恒 fallback（现状保持）；stale 同样 fallback 且标注；fresh+complete 跳过 fallback |
| 回归锚点 | test_wiki_shadow_*（ShadowMetrics 扩展） | 节点行为除上述外不变（11 种 stop_reason 全集回归） |

---

## 7. 核心决策摘要

1. **freshness 三态机器值**（fresh/unknown/stale）接管恒 unknown；来源级导出（035 既有列 + 查询期 observation + binding 状态），**不新增表/列**；source_observation/watermark 保持观测摘要原义，两维分离。
2. **登记链**：receipt JSON 复用（apply 即登记 unverified+source_relevance_check_pending）；检查 = 查询期惰性有界核查（复用编译链轻量调用）；异步队列明确后续。
3. **价值函数 V=相关性×新鲜度×覆盖面**（三档权重 1.0/0.6/0.2）；读预算 12000 与上下文注入预算分离；子模替换（supported/conflict 引用钉住）+ 价值降序摆放保证「预算满可读第九页」。
4. **参数化 ReadProfile**：均衡 8/2/3/30s/12000 = 现状；深读 24/3/6/90s/32000；一次升级路由（RASER 风格）+ 覆盖缺口/冲突停止语义新增 2 个 stop_reason。
5. **freshness 独立确定性门**：authority/freshness 模型不可设置（extra=forbid 不变）；coverage/conflict 维持 strict 模型输出；唯一行为放宽=fresh+complete 跳过 fallback（须登记）。
6. **边界**：检索/路由/API 契约/隐私权限零改动；机器值英文、UI 映射中文。
