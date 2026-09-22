# T31 D1 Shadow 现状盘点与评测环境可达性

- 盘点人：recon-a（researcher）
- 盘点日期：2026-09-20
- 基线：HEAD 3c4f46d「阶段C：新查询路径补全（freshness 三态 + 上下文替换 + 深读模式 + Gate 完整化）」2026-09-20 14:01:52 +0800；工作区仅 M docs/wiki-reconstruction-status.md（review 维护）
- 方式：只读盘点；Phase C 提交 11 文件（wiki_retrieval.py +193、wiki_gate.py +41、adapters.py +10、generations.py +9、tests/test_phase_c_query_node.py +309、docs/phase-c-query-node-design.md 等）——**未触及 shadow.py/api/services/wiki_shadow.py**
- 路径前缀相对 apps/backend/

---

## 一、Shadow 评估器完整现状

1. ShadowMetrics（services/wiki/shadow.py:26-44）：status(reserved/completed/failed/interrupted)/old_citation_count/candidate_count/page_read_count/note_read_count/evidence_chars/assessment_calls/latency_ms/authority/freshness/coverage/conflict/budget_exhausted/correctness/token_count；**correctness=Literal["unknown"]（:42，无答案正确性评估）**；**token_count=None（:43-44，注释：complete() 不暴露 provider usage，字符数≠token）**。
2. ShadowMetricStore（shadow.py:47-148）：app_state 键 wiki_shadow_metrics_v1（:23）；7 天滑窗（_load cutoff :56-57）；每日配额 20 条（reserve :66-81，:72 计数今日）；finish 在存储边界再 model_validate（:83-94）；summary 聚合（:102-148）：samples/today_samples/completed/failed/interrupted/unfinished/wiki_hits/note_fallbacks/authority_denied/coverage_complete/disputed/budget_exhausted/assessment_calls/evidence_chars/mean_latency_ms（:128-148）。
3. 入口接线：main.py:138 注册 WikiShadowRuntime(AppContext)；api/chat.py:579-581 _persisting_stream 开播前 foreground_started()（抢占进行中 shadow）；chat 完结后 foreground_finished（api/services/wiki_shadow.py:67-85）→ 满足条件建后台任务 _run（:100-108）→ evaluator.evaluate（:105）；配置/设置变化通过 model_config/model_keys/agent_model_configs 表 revisions 比对撤销旧客户端（:33-38）；shutdown（main.py:96）。
4. 资格门槛 shadow_eligible（shadow.py:151-166）：wiki_shadow_enabled + 非 local_privacy + 非 suppress_post_reply_automation + 无 action_plan(s) + semantic needs_context + source_scope==knowledge_base + 显式 scope 含 knowledge_base + agent_run_id + **agent_run_id 哈希 10% 采样（:165）**。
5. 隔离只读服务 _ReadOnlyServices（shadow.py:169-212）：仅暴露 search_pages/read_page/check_source_watermark/search_vault_notes/restore_vault_notes 与 RETRIEVAL_AGENT 模型（get :205-209 拒绝其他 agent）；每次调用前后 permitted() 复查（:180-188）；模型=chat_model_client(request, RETRIEVAL_AGENT)（wiki_shadow.py:91）。
6. 执行：隔离 AgentState（conversation_id/message_id/agent_run_id="shadow"，:241-245）；超时 35s（:248）；完整绕行 chat/archive/action graph（模块 docstring :1）；评价结果写入 ShadowMetrics（:252-264）并在 finally 记 latency_ms=整次 evaluate 墙钟（:275）；异常文本不落库（:269-271）。
7. **新旧路径对照现状**：仅 old_citation_count=len(前台账单 citations) 作基线（:231、api 层 :84 传参）；统计新路径 candidate/page_read/note_read/evidence_chars/assessment_calls + gate 五维；**不存在旧路径对照运行**（不重跑默认聊天/检索路径）；correctness 恒 unknown → 无新旧答案质量对比能力。

---

## 二、题集与夹具现状

8. 可复用夹具：wiki_fixtures.indexed_citation（tests/wiki_fixtures.py:13-42）；read_tools（tests/test_wiki_read_tools.py:16）；published（tests/test_wiki_publication.py）；graph()（tests/test_wiki_query_node.py:11-18）；test_wiki_shadow.py：eligible_state（:19-31，遍历 1000 个 run_id 找 10% 采样命中）与 metric_store（:34-37）；test_wiki_shadow_runtime.py：runtime_fixture（:18-27）。
9. Phase C 新增夹具：test_phase_c_query_node.py published_with_source_state（:38-63，apply 前写 verification_status/verified_at/expires_at，返回 AgentToolSet+数据库）+ StopModel（:67）/Model（:159）脚本模型；freshness 三态断言（:107-147：登记 unknown+source_relevance_check_pending→verified fresh→expired stale）。
10. **无固定题集文件**：tests/ 与 docs/ 下无 shadow 题集/数据集文件（无 questions-*.jsonl 之类）；shadow 以真实用户消息为语料（采样制），评测能力=统计而非题目脚本；evals/retrieval_eval.py 才有数据集 schema（retrieval-eval-dataset.v1，:31）与切片题集（PRIMARY_SLICE_MINIMUMS :36-45）。

---

## 三、评测驱动与度量采集

11. 入口：**shadow 无 CLI/脚本驱动**——仅两种途径：运行时 opt-in 后台评测（chat 请求完结后）+ pytest 测试（test_wiki_shadow.py / test_wiki_shadow_runtime.py / test_wiki_shadow_lifecycle.py / test_wiki_shadow_summary.py / test_wiki_shadow_runtime.py）；脚本化评测存在于其他子系统：app/evals/retrieval_eval.py（argparse，FINAL_GATES :50-63、GROUNDING_FINAL_GATES :64-69）、llmwiki_graph_eval.py、vector_query_scaling.py、soak_snapshot.py/soak_report.py。
12. 度量采集点：模型调用量=assessment_calls（节点 report，shadow.py:258）；延迟=executor 级墙钟（shadow.py:275，非模型延迟）；**无 token 计数**（shadow.py:43-44）；AgentState 本身无 token/耗时字段；agent_runner.py:50-57 有 invocation latency_ms、graph_runtime.py:858 有 invocation_history 汇总——但 shadow 路径不经过 agent_runner，无逐模型调用计时。

---

## 四、环境模型可达性

13. LLM 配置形态：provider="openai-compatible" + base_url + model + api_key（models/config.py:46-54 ModelConfigRequest；api_key 单独存储 :205）；设置存 model_config/model_keys/agent_model_configs 表（settings UI / sidecar 配置）；默认常量 DEFAULT_CHAT_BASE_URL/DEFAULT_CHAT_MODEL（config.py:8-11/:48-49）。
14. 当前环境事实：**本机 shell 无任何 AGENT_PET_* 环境变量**（AGENT_PET_MODEL_BASE_URL NOT set，实测）；仓库无 .env 文件（glob 无结果）→ **当前命令行/测试环境无真实模型端点，仅 scripted/mock 模型可达**：tests/agent_runtime_fakes.py FakeChatModel（:491）/FailingChatModel（:501）/FakeToolCallingChatModel（:506）等；test_phase_c_query_node.py StopModel/Model。运行时 shadow 在 model=None 时 evaluate 返回 skipped（shadow.py:226-227、:234-236）；真实模型接入方式=设置页面/env 配 base_url+api_key（本机需另行配置方可跑真模型评测）。
15. 【关键缺口-阶段C集成】**ShadowMetrics.freshness 字面量仅 "unknown"（shadow.py:38），与 Phase C gate 三态 fresh/unknown/stale（wiki_gate.py:53）不兼容**：metrics 构造直接拷贝 gate.freshness（shadow.py:260），finish 存储边界再校验（:85）——gate 为 fresh/stale（来源带 verification 元数据时，_apply_gate_freshness wiki_retrieval.py:105-110 会置）→ ShadowMetrics 构造 ValidationError → evaluate 走 except 返回 "failed"（:269-271）。Phase C 提交未同步 shadow.py（3c4f46d stat 无 shadow.py）——**shadow 评测与新 gate 脱节，D 阶段需迁移 ShadowMetrics.freshness 为三态并补测试**。

---

## 五、15 条关键事实速查

1. shadow.py:26-44 ShadowMetrics 字段集；correctness/token_count 为占位（无答案质量、无 token）。
2. 存储：app_state wiki_shadow_metrics_v1（shadow.py:23），7 天滑窗（:56-57），每日 20 条（:72），summary 聚合（:102-148）。
3. 入口：main.py:138 注册；chat.py:579-581 前台抢占；wiki_shadow.py:67-85 foreground_finished→后台 task→:105 evaluate。
4. 资格：shadow.py:151-166 九条件+10% 采样（:165）。
5. 隔离：_ReadOnlyServices（shadow.py:169-212）仅读工具+RETRIEVAL_AGENT 模型，调用前后权限复查。
6. 超时 35s（shadow.py:248）；latency=整次墙钟（:275）。
7. 新旧对照：仅 old_citation_count 基线（:231），无旧路径对照运行；correctness 恒 unknown。
8. 【缺口】ShadowMetrics.freshness 单值 Literal["unknown"]（shadow.py:38）不兼容 gate 三态（wiki_gate.py:53）→ fresh/stale 时 shadow 恒 failed（:252-264 构造、:85 再校验、:269-271 兜底）；Phase C 未改 shadow.py。
9. gate 三态来源：_apply_gate_freshness（wiki_retrieval.py:105-110）+ derive_source_freshness（wiki_gate.py:79，verification_status/expires_at/revoked_at/observation）；rank stale>unknown>fresh（wiki_retrieval.py:90）。
10. 夹具：read_tools/published/graph（test_wiki_query_node.py:11-18）/eligible_state（test_wiki_shadow.py:19-31）/metric_store（:34-37）/runtime_fixture（test_wiki_shadow_runtime.py:18-27）/published_with_source_state（test_phase_c_query_node.py:38-63）。
11. 无固定题集文件；shadow 语料=真实用户消息采样；数据集形态仅在 app/evals（retrieval-eval-dataset.v1）。
12. 无 shadow CLI；评测=运行时 opt-in + pytest；脚本评测=app/evals/*.py（argparse）。
13. 采集：assessment_calls（shadow.py:258）；latency=墙钟（:275）；无 token/逐调用耗时（shadow.py:43-44；AgentState 无 token 字段）。
14. 模型配置：openai-compatible（config.py:46-54）+ 表存储 + AGENT_PET_MODEL_BASE_URL/API_KEY/CHAT_MODEL env；本机实测无 env、无 .env → 仅 scripted/mock（agent_runtime_fakes.py:491+）。
15. summary 端点：api/settings.py:144（wiki_shadow_metrics）；配置变更经表 revisions 比对撤销旧客户端（wiki_shadow.py:33-38）。
