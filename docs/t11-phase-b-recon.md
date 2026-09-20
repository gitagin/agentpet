# T11 阶段B预研盘点：generation 存储与发布流水线代码事实

- 调研人：recon-a（researcher）
- 调研日期：2026-09-20
- 方式：只读代码盘点（未修改任何代码/业务文件）；文件均位于 apps/backend/app/services/wiki/ 与 apps/backend/migrations/
- 交叉核对：2026-09-20 与 eng2-a 的 T11 断点笔记逐条核对（抽查全部 file:line 均属实），其独有发现已并入相应小节
- 用途：为 T9 Draft-first 设计草案提供代码事实
- 结论标记：【事实】= 代码事实（file:line）；【缺口】= 版本化权限缺口；【建议】= 对 T9 的最小改动面建议

---

## 一、当前发布流水线形态：POST-APPLY SNAPSHOT INTEGRATION

### 1.1 调用链（apply 写盘在前，generation 捕获在后）
【事实】流水线顺序为「先写工作 Markdown 与 bindings → 再 capture generation」：

1. apply 阶段写工作文件：ingest.py:371 `self.wiki.write_page(WikiPageWriteRequest(...))`（每个 plan 一个页面）；
2. 写 binding：ingest.py:475-481 `bind_authoritative_wiki_page(graph, vault_id, relative_path, parsed, status="active" if run_status=="applied" else "quarantined")`；
3. run 状态落库：ingest.py:484-508 更新 wiki_workflow_runs.status='applied'，result_json.publication.status='pending'（ingest.py:501）；
4. 触发发布：ingest.py:510-516 `WikiPublicationService(...).publish_ingest(request.run_id)`（仅 run_status=='applied' 时）；
5. capture 读回工作文件：publication.py:124-160 `_capture` 对每个 target 调 `read_evidence_snapshot`（:137）、`resolve_markdown_path(path).read_bytes()`（:140）、双重 hash 校验 working_copy_changed（:138-142）、`validate_wiki_page_roots`（:145-148）、`_dependency_stamp`（:151），收集依赖+水印（:152-155）；
6. stage：publication.py:117-120 → generations.py:41-121；
7. promote：publication.py:121 → generations.py:123-178。

### 1.2 stage / promote / base-generation CAS 的位置与事务边界
【事实】
- stage（generations.py:41-121）单事务（:66-120 一个 session）：`BEGIN IMMEDIATE`（:67）→ base_generation CAS 校验 `self._active(conn, vault_id) != base_generation → wiki_generation_base_conflict`（:68-69）→ 插入 generation 行 status='staged'（:70-77）→ 从 base 复制 pages/dependencies（:78-90）→ 逐页 body 去重入库 + 完整性校验（:91-112）→ 依赖 json 入库（:113-117）→ build_generation_projection（:118-120）。
- promote（generations.py:123-178）单事务（:128-178）：`BEGIN IMMEDIATE`（:129）→ 校验 generation 存在且 status=='staged'（:130-135）→ 再次 base CAS（:136-137）→ require_generation_projection（:138-140）→ body 全量 hash 复核（:145-152）→ 调用外部 validator（:153-157，同步、无模型调用——PublicationValidator 类型约束在 :23）→ active_generation CAS（:158-164，`WHERE active_generation IS ?`，rowcount!=1 → base_conflict）→ status='published'+published_at（:165-168）→ workflow receipt 回写（:169-178，要求 run 仍 status='applied'）。
- capture（publication.py:124-160）是多个只读事务（每个 path 一个 `conn.execute("BEGIN")`，:128/:144），不在 stage/promote 事务内——**工作文件→快照的一致性靠捕获时的双 hash 校验（:138-142）保证，而非锁**。
- 错误分支：ingest.py:517-529 将 publish 失败写为 result_json.publication={status:'blocked',reason}（WikiGenerationError 等）或 {status:'failed'}（其他异常），回写 guard 为 `COALESCE(json_extract(...,'$.publication.status'),'') != 'published'`（:527）——幂等，已 published 不覆盖。

### 1.3 表结构（migrations 031-033）
【事实】
- 031：wiki_generations（id, vault_id, base_generation, status CHECK IN ('staged','published'), created_at, published_at, UNIQUE(vault_id,id), FK(vault_id,base_generation) 自引用，:1-10）；wiki_generation_heads（vault_id PK, active_generation，:12-16）；wiki_page_bodies（PK(vault_id, content_hash)，body BLOB，:18-23）；wiki_generation_pages（PK(vault_id,generation,relative_path)，FK body，:25-33）。
- 032：wiki_generations.workflow_run_id + 唯一索引（:1-3）；wiki_generation_dependencies（PK(vault_id,generation,relative_path)，dependency_json，ON DELETE CASCADE，:5-13）。
- 033：wiki_body_projection（:1-9）、wiki_body_fts（fts5，:11-19）、wiki_generation_links（:21-31）、wiki_generation_projection（:36-43）。
- 005：wiki_sources（source_hash TEXT NOT NULL UNIQUE，:3-14）；wiki_workflow_runs（:16-25）；wiki_workflow_page_updates（含 status、error 列，:27-42）。
- 030：wiki_sources 加 vault_id + 索引（:1-4）——注意 source_hash 仍 UNIQUE（005:5），T3/T5 的迁移目标。

---

## 二、「构造 N+1 时 N 继续可读」的保证机制

【事实】三层机制：
1. **manifest 复制**：stage 时把 base_generation 的 wiki_generation_pages / wiki_generation_dependencies 整表复制进新 generation（generations.py:78-90），N+1 未显式变更的页面天然继承 N 的版本条目；
2. **body 共享去重**：wiki_page_bodies 以 (vault_id, content_hash) 为主键（031:18-23），stage 用 `INSERT OR IGNORE`（generations.py:100）——相同内容跨 generation 共享同一 body 行；完整性靠三处 hash 复核（generations.py:103-108 stage 写入、:145-152 promote、:193-195 read_body）；
3. **active_generation CAS 单点切换**：promote 只在 base 未变时把 head 从 N 切到 N+1（generations.py:158-164）；N 的 generation 行 status 仍是 'published'（永不降级），任何显式 pin 到 N 的读取继续有效（snapshot_reader.py:69-83 pin、:198-205 _scope 只要求 status='published'）。read_body 也显式限定 g.status='published'（generations.py:188）。

【事实】版本固定读取入口：WikiSnapshotReader.pin(generation=None)（snapshot_reader.py:69-83，None 时取 head）；read/search/source_observation/_neighbors 全部携带 pin；api/wiki.py:65-93 POST /wiki/pages/read 暴露显式 generation 参数（:74 pin(page_request.generation)）+ expected_version 校验（:76）。
【边界·eng2-a 验证】「N 继续可读」的成立前提是 **binding 状态未变**：_load 每次读取都会重算依赖 stamp（snapshot_reader.py:236 → validate_snapshot_dependency → _dependency_stamp 比对 binding.content_hash，publication.py:29-30）；若工作副本被外部改写且 reconcile 将 binding 标 stale（wiki_reconciler.py:119-125），旧 generation 的读取同样失败（wiki_publication_dependency_changed）。测试佐证：test_head_switch_does_not_change_existing_query_pin、test_pinned_search_read_and_links_ignore_working_copy（binding 未变时工作副本改写不影响 pinned 读）。

---

## 三、forgotten / revoked / privacy 的阻断点清单

### 3.1 写路径/发布路径阻断（binding 检查点）
【事实】
1. compiler.py:197-203：related_pages 目录只列 `binding.status='active'` 的页面（:200）——forgotten/stale 页面不再进入编译上下文；
2. memory_closure.py:863-878：synthesis 源 binding 三连检查——binding 存在（:864-869）、status=='active'（:870-871）、content_hash == parsed.content_hash（:872-873，否则 synthesis_source_binding_hash_mismatch），并取 page_entity_id（:878）；
3. publication.py:22-66 _dependency_stamp：每页 binding 必须 status='active' 且 content_hash==manifest 期望值（:29-30，否则 wiki_publication_dependency_changed）；root entity 必须 status='active'（:41-42）；wiki_sources 行必须存在（:47-48）且 raw_content 的 sha256==source_hash（:50-52）；provenance candidate 必须唯一且 status in candidate/active（:61-62）；
4. publication.py:69-75 validate_snapshot_dependency：依赖 stamp 重算比对（页面级 + 全依赖指纹）；
5. publication.py:177-178：manifest 与 dependencies 集合必须完全一致（wiki_publication_dependencies_missing）；
6. memory_entity_graph.py:503-549：update_entity_status 原子级联——forgotten/rejected 时 facts 级联降级（:537-546）+ `revoke_fact_artifacts`（:1862-1871）把 memory_fact_artifact_bindings.status 置 'revoked'；
7. memory_entity_graph.py:1747-1751 / 1799-1800：binding 一旦 forgotten 不可 reactivate（forgotten_wiki_page_cannot_be_reactivated）；wiki_reconciler.py:117 对 forgotten 行直接跳过（外部文件不能复活被遗忘页）。

### 3.2 读路径阻断
【事实】
8. snapshot_reader._load：每个页面及其依赖父页都过 `self.authorize(pin.vault_id, parent) is not True → wiki_snapshot_access_denied`（snapshot_reader.py:224-226）；
9. authorize 回调实现（factory.py:506-536）：vault_id==active_vault_id（:507）+ read_evidence_snapshot 实时读工作文件（:509）+ candidate_filter 策略（:510-512）+ notes 表校验（status != deleted 且 content_hash 与磁盘全等，:514-520）+ note_chunks 逐 chunk hash 全等（:521-528）+ _candidate_policy_allows（:534）；
10. api/wiki.py:79-91：读取失败记录 audit（wiki.snapshot.read denied）并映射为 403/409/422。

### 3.3 【缺口】版本化权限的具体位置
【缺口】**已发布 generation 的读取不检查 binding status**：
- snapshot_reader._load（:207-239）只校验 generation status='published'（_scope :198-205）+ 依赖 stamp（:236）+ authorize 回调；而 authorize（factory.py:506-536）基于 notes 表与 candidate 策略，**不查 wiki_page_bindings.status**。因此一个页面被 forget（binding→forgotten）后，只要 candidate 策略放行，旧快照仍可经 /wiki/pages/read 读出——「旧内容版本稳定」（不可变 generation 保证）与「旧权限失效」（依赖读路径实时策略）在此脱节。
【缺口】binding hash 与 generation page hash 的耦合点（两处）：
- publication.py:29：_dependency_stamp 要求 binding.content_hash == 生成时 manifest hash——发布时强耦合；
- memory_closure.py:872：synthesis 要求 binding.content_hash == 当前解析 hash——使用时强耦合；
- 但这两处都是「发布/合成时刻」检查，**不是「读取时刻」检查**；wiki_reconciler.py:119-125 外部改文件→binding 变 stale（revision+1），已发布快照仍持旧 hash 可读。
【缺口】source_watermark（source_watermark.py:7-24）只含 wiki_sources(id,source_hash,source_type,updated_at)+notes(id,relative_path,content_hash,status) 摘要，**不含 binding status 与 generation 版本**——snapshot_reader.source_observation（:172-196）能报 changed_since_capture，但感知不到「binding 被遗忘」。
【缺口·eng2-a 验证】binding 状态机没有 'revoked' 状态：migrations/021:65 CHECK IN ('active','stale','quarantined','forgotten')；'revoked' 只存在于证据状态集（evidence_policy.py:12-18 INACTIVE_EVIDENCE_STATUSES 含 revoked；memory_fact_artifact_bindings.status，memory_entity_graph.py:1862-1871）。「遗忘」只能表达为 binding forgotten，且无法表达「某版本被撤销、其他版本仍有效」。
【缺口·eng2-a 验证】generation-aware 归档恢复缺失：retrieval.py:613-614 对 wiki_generation / wiki_snapshot 引用一律拒绝恢复（snapshot_archive_not_supported）——版本化引用的存档恢复适配器尚未实现。

---

## 四、Draft-first 落地的最小改动面

### 4.1 compiler 输出进入 draft 的入口点
【建议】compiler.compile_source（compiler.py:237-290）产出的 plans（result.pages 校验后 :277-287，含 source_is_immutable 检查 :283-284）目前直接进入 apply 写盘（ingest.py:371）。最小改动：在 compile 产物与 write_page 之间插入「draft stage」分支——store.stage（generations.py:41-121）已接受任意 changes dict（路径→body 字节）且不触碰工作文件（SafeMarkdownWriter 仅校验路径，:51-59），可原样承载 compile 产物；把 write_page 推迟到 promote 成功之后。

### 4.2 validate / review / promote 的现成设施
【建议·可复用】
- stage→promote 的 validator 接口已存在：PublicationValidator（generations.py:23）+ promote 内校验点（:153-157）——draft 校验可直接挂；
- ingest 工作流的 pending/blocked/failed publication 状态机（ingest.py:501, 517-529）与 wiki_workflow_runs.status（005:16-25）可复用为 draft 生命周期（如 pending_draft/reviewing/draft_published），仅需在 CHECK 约束或代码层扩展状态集合（031:5 目前 CHECK IN ('staged','published')）；
- wiki_workflow_page_updates.status='written'（publication.py:100-104 按此收集 target）可扩展 draft 标记（如 'drafted'），避免 capture 误收未批准内容；
- promote 的 workflow receipt（generations.py:169-178）要求 run status='applied'——draft promote 需放宽该条件或新增 run 状态。

### 4.3 editable Markdown 同步时机
【建议】现有时序是「写盘→capture」（publication.py:137-142 读回文件并做 working_copy_changed 双 hash 校验）。Draft-first 两种方案：
- 方案A（推荐，改动最小）：draft 阶段只写 DB（stage 不入盘），review 通过后 promote 前的最后一步「写盘→re-capture→promote」，把 write_page 从 apply（ingest.py:371）移到 promote 事务前，保持现有双 hash 校验不变；
- 方案B：promote 后异步落盘——但会破坏 _capture 的 working_copy_changed 校验语义（:138-142），且 read_evidence_snapshot（factory.py:509）依赖磁盘文件，需同步补偿，不推荐。
【建议】版本化权限补丁点：读路径 authorize（factory.py:506-536）增加 binding status 检查（status='active' 才放行，复用 memory_closure.py:870-872 的判定）；watermark 扩展加入 binding status 维度（source_watermark.py:12-16 查询处）——使「遗忘」能被 source_observation 感知。

---

## 五、15 条最关键代码事实（含 file:line）

1. POST-APPLY SNAPSHOT INTEGRATION 全链：ingest.py:371（write_page）→ ingest.py:475-481（bind binding）→ ingest.py:501（publication.pending）→ ingest.py:516（publish_ingest）→ publication.py:124-160（capture）→ generations.py:41-121（stage）→ generations.py:123-178（promote）。
2. stage 与 promote 各自独立单事务（BEGIN IMMEDIATE：generations.py:67 / :129），base_generation CAS 在 stage（:68-69）与 promote（:136-137）双重执行，active_generation CAS 在 :158-164。
3. N+1 构造时 N 继续可读：manifest 复制（generations.py:78-90）+ body 共享去重（031:18-23；generations.py:100）+ head 单点 CAS（:158-164）+ 已发布 generation 永不降级（status CHECK 只含 staged/published，031:5；_scope 仅查 published，snapshot_reader.py:198-205）。
4. 版本固定读取：WikiSnapshotReader.pin（snapshot_reader.py:69-83，generation=None 取 head），read/search 全程携带 pin；api/wiki.py:74 暴露显式 generation + expected_version（:76）。
5. body 完整性三处复核：stage 写入（generations.py:103-108）、promote 全量（:145-152）、read_body（:193-195）。
6. 发布 validator 同步约束：PublicationValidator = Callable[[sqlite3.Connection, str, str, Mapping[str,str]], None]（generations.py:23），promote 内同步调用且拒绝协程（:126-127, :153-157）。
7. capture 与 stage/promote 事务分离，工作文件一致性靠双 hash 校验（publication.py:138-142：expected_bytes_hash + read_bytes 与 content_hash 比对）而非锁。
8. 发布失败状态机：ingest.py:517-529 blocked/failed 回写，guard 幂等（:527 已 published 不覆盖）。
9. binding 生命周期状态：active/stale/quarantined/forgotten（memory_entity_graph.py:1790），forgotten 终态不可复活（:1747-1751, :1799-1800；wiki_reconciler.py:117 跳过）。
10. binding 检查点（写/发布路径）：compiler.py:200（目录仅 active）、memory_closure.py:870-873（synthesis 三连）、publication.py:29-30（stamp：active+hash 全等）、publication.py:41-42/47-52/61-62（root entity/source/candidate）。
11. 读路径唯一权限闸：authorize 回调（snapshot_reader.py:224-226）→ factory.py:506-536（vault 匹配+磁盘快照+candidate 策略+notes/chunks 全等），**不查 binding status**。
12. 【缺口】binding 被遗忘后旧快照仍可读（见 3.3）：读路径与 binding 状态解耦，版本化权限（per-version ACL）尚未实现。
13. 【缺口】binding hash 与 generation page hash 耦合点：publication.py:29（发布时）与 memory_closure.py:872（合成时），均非读取时刻。
14. watermark（source_watermark.py:12-16）仅覆盖 wiki_sources+notes 摘要，不含 binding status/generation 版本；source_observation（snapshot_reader.py:172-196）可感知内容变化但感知不到遗忘。
15. Draft-first 最小改动面：draft stage 复用 store.stage（不落盘，generations.py:51-59 仅路径校验）；promote 前写盘→re-capture→promote（方案A）；publication 状态机（ingest.py:501/517-529）与 page_updates.status（005:27-42）可扩展 draft 态；promote receipt（generations.py:169-178）需放宽 'applied' 条件；读路径 authorize 补 binding 检查（factory.py:506-536）。

---

## 六、与 eng2-a 断点笔记交叉核对（合并补充，2026-09-20）

eng2-a 的 T11 断点笔记逐条核对通过（抽查 file:line 均属实）；以下为其独有、已并入正文相应小节外的补充事实：

### 6.1 write_page 写盘门禁与索引同步（services/wiki.py）
【事实·eng2-a 验证】
- services/wiki.py:149-155：`target_content_hash` 写前门禁——期望 hash 与实际不符抛 WikiConflictError（WIKI_TARGET_ABSENT_HASH 表示期望不存在 :151）；
- services/wiki.py:167-173：replace_page 必须携带 target_content_hash（否则 WikiConflictError :168-169），写盘整体走 SafeMarkdownWriter（:173/:184/:196-201）；
- services/wiki.py:207：写盘后 `index_refresh(relative_path)` 触发异步索引任务（index_job_id）——editable Markdown 的索引同步时机。

### 6.2 editable Wiki 权威检查（evidence_policy.py）——被遗忘页在「编辑/证据路径」的阻断
【事实·eng2-a 验证】wiki_page_rejection_reason（evidence_policy.py:93-140）逐级判定：
- 无 binding 行 → unverified_wiki_page（:119-120）；
- binding status != 'active' → inactive_wiki_{status}（:121-122，forgotten 页在此被拒）；
- 索引 hash 与 binding 不符 → stale_wiki_index（:125-126）；
- 期望 hash 与 binding 不符 → unverified_wiki_edit（:127-128）；
- 磁盘文件 hash 与 binding 不符 → unverified_wiki_edit（:134-136）。
- 文档级预检 wiki_document_rejection_reason（:69-79）：report/companion 摘要类路径必须 verified roots。
- INACTIVE_EVIDENCE_STATUSES（evidence_policy.py:12-18）含 'revoked'——证据层撤销已有，binding 层没有。

### 6.3 binding 状态机缺 'revoked'（migrations/021:65）
【事实·eng2-a 验证】wiki_page_bindings.status CHECK IN ('active','stale','quarantined','forgotten')（021:58-69），**无 'revoked'**；'revoked' 仅存在于 memory_fact_artifact_bindings.status（memory_entity_graph.py:1862-1871）。语义缝隙：无法表达「页面的某个旧版本被撤销而新版本仍有效」——这正是版本化权限要补的模型位。

### 6.4 generation-aware 归档恢复缺失（retrieval.py:613-614）
【事实·eng2-a 验证】restore_citations 对 wiki_generation / wiki_snapshot 引用一律 reject('snapshot_archive_not_supported')（:613-615）——版本化引用无法从归档恢复，generation-aware archive adapter 是未来工作。

### 6.5 Draft-first 可复用的 review/confirm 设施
【事实·eng2-a 验证】
- ingest_review.py（app/services/wiki/ingest_review.py）review_ingest + wiki_ingest_reviews 表（migrations/008）——现成的 review 门；
- confirm_ingest（ingest.py:87-98）确认流写 planned 行 + target_content_hash——approve 后 apply 的入口；
- compiler.compile_source 产物 plans 在 compiler.py:314-319 组装（含校验），ingest.py:87-113 先落 planned 行、apply 时（ingest.py:256-538）才写盘——planned→written 已有状态位（wiki_workflow_page_updates.status），draft 可映射为 planned 的扩展；
- reconcile 触发点：api/memory/graph.py:250 与 memory_graph_kuzu.py:297（reconcile_all_vaults）——外部编辑→binding stale 的闭环入口。

