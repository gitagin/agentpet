# T23 阶段C代码事实盘点：查询节点 / Gate / 水印现状（C1）

- 盘点人：recon-a（researcher）
- 盘点日期：2026-09-20
- 基线：HEAD d2a73d1「阶段B：Draft-first Publication（036 迁移 + draft 生命周期 + 读路径权限门）」2026-09-20 12:40:38 +0800；工作区仅 M docs/wiki-reconstruction-status.md（review 维护中）
- 方式：只读盘点（未修改任何代码）；与状态文档 Phase B 记录逐项交叉核对一致（factory authorize 收紧 / snapshot_reader._scope revoked / source_watermark bindings 维度 / 036 均实测吻合）
- 路径前缀：app/agents/ 与 app/services/ 相对 apps/backend/app

---

## 一、wiki_knowledge_retrieval_node：候选发现→阅读循环→预算→停止

1. 入口与前置门：wiki_knowledge_retrieval_node（nodes/wiki_retrieval.py:24）；source_scope 门（:27-29，非 all/knowledge_base → stop_reason=source_scope_denied）；wiki_reader 门（:30-32 → reader_unavailable）。
2. 预算常量（全部内联，无常量模块）：deadline=time.monotonic()+30（:34）；remaining=12000 字符（:35）；search top_k=24（:47）；pending 取前 8 个候选（:53）；rounds=range(3)（:55）；深度<2 扩跳（:84-86，2 跳）；revalidate 读页 max_chars=min(32000,...)（:325）；shadow 隔离运行超时 35s（shadow.py:248）。
3. 候选发现：tools.search_wiki_pages(_retrieval_query(state, semantic), top_k=24)（:46-48，asyncio.wait_for 且剩余时间做超时）；known={path:(content_hash, depth)}（:51）；report["retrieved"] 记录候选路径（:52）。
4. 阅读循环：pending 前 8 条起步（:53）；attempted 集合防同 (path,section) 重读（:54-60）；每读前预算检查（:61-63 → budget_exhausted）；read_wiki_page(path, generation=candidates.generation, expected_version, section, max_chars=remaining)（:66-71）；TimeoutError → time_budget_exhausted（:72-74）；读失败计入 report["unread"]（:75-77）。
5. 版本一致性：page.generation≠candidates.generation 或 content_hash≠expected_version → raise ValueError("wiki_query_version_mismatch")（:78-81）；remaining -= len(page.content)（:82）。
6. **「阅读是 additive」的代码落点**（无该字面量，语义在此）：citations 跨轮累计 append（:88-95）；每轮 assessment_input 携带**全部**已读 citations（:118）；注释「Nothing is emitted until all accumulated content passes a fresh read.」（:140）；gate_evidence 压缩门只滤 eligibility、不减已读内容（:96）；每轮后用 gate_evidence(citations).accepted 而非清空（:96）。
7. 引用身份：wiki-page:{sha256(generation:path:content_hash:start_line:end_line)}（:87-95），retrieval_mode="wiki_snapshot"，lifecycle_status="active"，携带 generation/section/行号。
8. 停止条件全集（stop_reason）：candidates_exhausted（:40 默认）/ budget_exhausted（:62/:98）/ time_budget_exhausted（:73/:123/:197-199）/ assessment_unavailable（:101）/ no_usable_evidence（:104）/ assessment_failed（:128）/ assessment_no_further_reads（:136）/ round_budget_exhausted（:139/:193-196）/ read_or_authority_failed（:147/:177）/ source_scope_denied（:28）/ reader_unavailable（:31）。
9. 每轮评估：observation=revalidate_wiki_citations（:106-109）→ gate.source_observation=observation["status"]、freshness_reason="source_relevance_check_pending"（:110-112）；model.complete(ASSESSMENT_POLICY, assessment_input(...))（:115-120）；parse_assessment（:121）；apply_assessment（:130）；next_reads 转 pending（:131-134）。
10. 收尾：最终 revalidate（:141-144）；gate.authority="passed" if citations else "not_checked"（:145）；异常 → authority=denied 且清空 citations（:146-152）；supplement_vault_notes（:154，fallback 读 notes 补足）；assess_combined_evidence（:159，第 3 次模型评估封顶 :193-196）；最终 revalidate+gate 更新（:162-169）；_emit_tool_results 以 search_memory 工具名发出（:170-172）；update_budget+report["gate"]=gate.model_dump（:179-184）。

---

## 二、WikiEvidenceGate：五维数据流

11. 五维定义（retrieval/wiki_gate.py:50-65）：authority: Literal["not_checked","passed","denied"]="not_checked"（:51）；**freshness: Literal["unknown"]="unknown"——恒 unknown**（:52）；freshness_reason 默认 "new_source_relevance_watermark_unavailable"（:53）；source_observation: not_checked/baseline_unknown/changed_since_capture/unchanged_since_capture（:54-56）；coverage: not_assessed/partial/model_assessed_complete（:57）；conflict: not_assessed/disputed/none_detected_by_model（:58）；budget: remaining_chars=12000/remaining_seconds=30/budget_exhausted/stop_reason（:61-64）；used_for_answer（:65）。
12. **freshness 赋值现状**：节点从未写 gate.freshness（恒 "unknown"）；仅 observation 存在时置 source_observation + freshness_reason="source_relevance_check_pending"（wiki_retrieval.py:111-112、:166-168）；ASSESSMENT_POLICY 告知模型「Unknown freshness cannot be resolved by assuming no changes.」（wiki_gate.py:77）；supplement_vault_notes 因 freshness=="unknown" 恒不满足跳过条件（wiki_retrieval.py:245-246 → fallback 恒走）。
13. 模型可设置项（仅 assessment 树）：WikiAssessment{questions(≤16)/conflicts(≤16)/next_reads(≤8)}（wiki_gate.py:44-47）；parse_assessment 硬校验：输出≤64000（:112-113）、引用 quote 必须逐字命中 gate 接受片段的 permitted_excerpt（:117-121）、supported 必须有证据（:122-124）、conflict 至少 2 条不同引用（:125-127）、next_reads 限 allowed_paths（:128-129）；apply_assessment 把模型输出映射为 coverage（全 supported→model_assessed_complete 否则 partial）与 conflict（:133-141）。
14. 确定性维度：authority/freshness/budget 模型不可设置；authority 只在节点赋值（:145/:148/:169/:174）；budget 由 update_budget（:144-151）+节点 :179-180 赋值。
15. 门控在回答组装中的调用点（nodes/chat.py:218-257）：`gate.used_for_answer=[stable_citation_id(item) for item in grounding_results]`（:220）；assessment 引用的证据未全部入上下文 → coverage 降级 partial + reason（:221-231）；gate 全量 JSON（排除 assessment/used_for_answer）注入 system_prompt（:232-239）；assessment 详情（问题状态/冲突）追加到 prompt 尾部并标注「Untrusted advisory assessment」（:240-257）；回答前先 revalidate_wiki_citations（:214）。
16. 发送时复核实现（revalidate_wiki_citations，wiki_retrieval.py:300-338）：wiki_vault_fallback 项经 restore_vault_notes 恢复并比对 identity 全等（:301-313）；wiki_snapshot 项逐条重读页面对比 generation/content_hash/content/start_line/end_line（:314-332，不符 → wiki_query_evidence_changed）；最后 check_source_watermark（:333-338，仅当 reader 实现 WikiSourceWatermarkProtocol，agents/services.py:46）。适配器实现 adapters.py:161-172：首查记录水印、查询中途水印变化 → wiki_sources_changed_during_query。

---

## 三、新鲜度现状与「new-source relevance watermark」差距

17. 水印现状：source_watermark（services/wiki/source_watermark.py:7-29）三维摘要——wiki_sources(id,source_hash,source_type,updated_at)（:12-13）+ notes(id,relative_path,content_hash,status)（:14-15）+ **bindings(relative_path,status,content_hash,revoked_at,revoked_reason)——阶段B新增维度**（:16-20）；source_observation（snapshot_reader.py:172-196）→ baseline_unknown / changed_since_capture / unchanged_since_capture（:190-195）。
18. 与「new-source relevance watermark」的差距：水印是**观测摘要**（变了=内容/权限状态有变）不是**相关性水位线**（新来源登记→待检查→过/拒）；无新来源登记表、无 relevance 状态字段、无「新来源到达」事件；检测粒度是 vault 级 digest 而非来源级。
19. 「登记→相关性待检查→异步 compiler」链**不存在**：compile 同步触发于用户 preview 流（ingest.py:35-48 compile_ingest → compile_source，:46；compilation_status="compiled" :47 / "model_not_configured" :42）；无后台队列/调度/异步 compiler；唯一近似物=freshness_reason 字符串 "source_relevance_check_pending"（wiki_retrieval.py:112/:168，语义=「水印有观察结果」而非真正登记相关性检查）。C 阶段若做「新来源相关性水位线」，需新增：来源登记表/状态字段 + 检查触发链（当前完全缺失）。

---

## 四、检索候选扫描与结果聚合

20. 聚合与过滤：adapters.py:189-199 search_pages → reader.search（snapshot_reader.py:115-170）：FTS(MATCH)+LIKE 双路并集（:126-141）、bm25 排序、候选按路径+chunk 去重（:142-146）、每候选 _load 二次校验（:148-150、:164-168）；一处请求一个 pin（adapters.py:174-187，generation 显式不符 → wiki_snapshot_version_mismatch）。
21. 断链/同名/循环链接处理：投影期链接解析用「唯一性索引」防歧义边——by_title/by_slug/by_path 只取唯一匹配（projections.py:57-64），_resolve_graph_link 目标缺失返回 None（:68-71）→ 断链自然消失；邻居用 set 去重（snapshot_reader.py:249-251）；节点层 attempted 防同页重读（:54-60）、known.setdefault 防重复扩跳（:86）；同名页由 slug 唯一索引消歧（projections.py:60-61）。

---

## 五、测试夹具（可复用清单）

- tests/wiki_fixtures.py：indexed_citation(database, vault_root, relative_path, ...)（:13-42）——建笔记+可选 binding；
- tests/test_wiki_read_tools.py：read_tools fixture（:16，基于 published 树 + RuntimeWikiReadAdapter）——规划/只读/水印/无写权四用例；
- tests/test_wiki_publication.py：published fixture（generation 发布树）；
- tests/test_wiki_query_node.py：graph() 构造 AgentState（:11-18）；8 用例覆盖：真实页读取+快照引用传输（:21-31）、scope 拒绝（:34-41）、**回答期间撤销抑制输出**（:44-68，chat_node 拒绝生成）；
- tests/test_wiki_gate.py / test_wiki_vault_fallback.py / test_wiki_combined_assessment.py：gate 五维、fallback 补充、第 3 轮合并评估；
- tests/test_wiki_source_watermark.py：水印感知遗忘/撤销；
- tests/test_wiki_shadow.py / test_wiki_shadow_runtime.py / test_wiki_shadow_lifecycle.py / test_wiki_shadow_summary.py：shadow 评测（隔离 AgentState 跑 wiki_knowledge_retrieval_node，shadow.py:241-265 采集 candidate_count/page_read_count/evidence_chars/assessment_calls/authority/freshness/coverage/conflict/budget_exhausted 的 ShadowMetrics）；
- tests/test_wiki_snapshot_api.py / test_wiki_snapshot_reader.py：pin/read/search 层。

---

## 六、20 条关键事实速查（file:line）

1. 节点入口+scope/reader 门：wiki_retrieval.py:24/:27-32。
2. 常量全内联：30s（:34）/12000（:35）/top_k=24（:47）/前 8 候选（:53）/3 轮（:55）/2 跳（:84-86）。
3. additive 阅读：citations 跨轮累计（:88-95）+「all accumulated content passes a fresh read」（:140）+ gate_evidence 只滤不减（:96）。
4. 每读预检预算（:61-63），版本不符 → wiki_query_version_mismatch（:78-81）。
5. 停止条件 11 种（见事实 8）。
6. 发送前二次/三次 revalidate（:141-144/:162-165/:202-205/:233-236/:278-281，实现 :300-338）。
7. 引用身份 wiki-page:{sha256} + retrieval_mode=wiki_snapshot（:87-95）。
8. 输出经 search_memory 工具名发出（:170-172）。
9. Gate 五维定义：wiki_gate.py:50-65。
10. freshness 恒 unknown（wiki_gate.py:52），仅 freshness_reason/source_observation 被置（:111-112/:166-168）。
11. 模型可设置项仅 assessment 树（wiki_gate.py:44-47），parse_assessment 五重硬校验（:111-130）。
12. authority/budget 确定性：节点+update_budget（:144-151）赋值。
13. 门控注入回答组装：chat.py:218-257（used_for_answer 一致性 :220-231、policy 注入 :232-239、详情注入 :240-257）。
14. 水印三维含 bindings+撤销（source_watermark.py:12-20），观察状态三值（snapshot_reader.py:190-195）。
15. **新来源登记→相关性待检查→异步 compiler 链不存在**（compile 同步于 ingest.py:35-48）。
16. watermark 变化中断查询：adapters.py:161-172（wiki_sources_changed_during_query :168-169）。
17. 候选聚合：FTS+LIKE 双路+bm25（snapshot_reader.py:126-141），每候选二次 _load（:148-150）。
18. 断链/同名/循环：投影唯一性索引（projections.py:57-64）、空目标消链（:68-71）、set/attempted 去重（snapshot_reader.py:249-251、wiki_retrieval.py:54-60）。
19. 夹具清单：wiki_fixtures.indexed_citation、read_tools、published、graph()、shadow 评测（ShadowMetrics）。
20. Phase B 基线一致：HEAD=d2a73d1，状态文档 Phase B 记录与代码实测吻合（authorize 收紧/_scope revoked/watermark bindings/036）。
