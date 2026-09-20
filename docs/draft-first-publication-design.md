# Draft-first Publication 设计草案（T9 阶段 B 预研）

- 作者：review（AgentTeams）
- 日期：2026-09-20
- 状态：**草案，仅预研、不实现、不碰自动写入**
- 输入：t11 阶段 B 盘点（docs/t11-phase-b-recon.md，代码事实+缺口定位）、t12 版本化权限调研（docs/t12-versioned-authority-research.md）、t8 阶段 A 记录（已知限制决策①）、generations.py / publication.py / snapshot_reader.py / compiler.py 代码复核

---

## 1. 目标与非目标

**目标**：把当前「先写 Markdown 再 capture generation」的 POST-APPLY 流水线改为「Draft Generation → Validate → Review → Promote → 同步 Editable Markdown」：
1. compiler 产物先进入 draft（数据库内），**对正式查询不可见**；
2. review 通过后才 promote，旧 generation（N）在构造 N+1 期间与构造失败后**继续可读**；
3. forgotten / revoked / privacy 变化**立即使对应事实不可用**（修复版本化权限：旧内容版本稳定 ≠ 旧权限永久有效）；
4. **拆开「历史版本正文」与「实时来源权限」**：正文层不可变、权限层读取时实时判定。

**非目标**：不实现任何代码；不做 generation 清理/租赁/GC；不做 generation-aware 归档恢复（retrieval.py:613-614 现状保留）；privacy 全模型（memory_permissions 扩展）仅给原则，列为后续。

**边界（本草案的硬约束）**：
1. **不引入新常驻服务**：draft/validate/review/promote 全部沿用现有同步调用链与既有事务模式（BEGIN IMMEDIATE 单事务、同步 PublicationValidator），不新增调度器/守护进程/队列；
2. **不重建检索**：FTS（unicode61 + _bigram_cjk）、向量索引、wiki_body_fts 与投影（033）全部不动——draft 不可见由 _scope 的 published 限定保证，不依赖检索层改动；
3. **不改 API 契约**：既有 API 路径、JSON/SSE 字段名、错误码、枚举值、Tool 名称全部保留；仅允许新增可选字段（如 draft review 状态字段，默认值缺省兼容）；
4. 既有读入口行为除「forgotten/revoked 旧 generation 拒绝」这一明确的收紧（4.3 登记）外保持不变。

---

## 2. 现状代码事实（t11 交叉核对 + 代码复核）

### 2.1 当前流水线：POST-APPLY SNAPSHOT INTEGRATION

链路（先写工作 Markdown 与 binding，再 capture generation）：
- apply 写盘：ingest.py:371 write_page（每个 plan 一个页面）；ingest.py:475-481 bind_authoritative_wiki_page（status=active/quarantined）；ingest.py:501 result_json.publication.status='pending'；ingest.py:516 publish_ingest；
- capture：publication.py:124-160 读回工作文件（:137 read_evidence_snapshot、:140 read_bytes、:138-142 双 hash 校验 working_copy_changed、:145-148 validate_wiki_page_roots、:151 _dependency_stamp、:152-155 水印）；
- stage：publication.py:117-120 → generations.py:41-121；promote：publication.py:121 → generations.py:123-178。

### 2.2 stage / promote / base-generation CAS（已有机制）

- stage 单事务（BEGIN IMMEDIATE，generations.py:67）：base_generation CAS（:68-69）→ 插 staged 行（:70-77）→ manifest 复制（:78-90）→ body 去重入库 + 完整性校验（:91-112）→ 依赖 json（:113-117）→ 投影（:118-120）；
- promote 单事务（:129）：staged 校验（:130-135）→ 再次 base CAS（:136-137）→ 投影与 body 全量 hash 复核（:138-152）→ 同步 validator（:153-157，PublicationValidator 定义 :23，拒绝协程）→ active_generation CAS（:158-164）→ published（:165-168）→ workflow receipt（:169-178，要求 run status='applied'）；
- capture 是多个只读事务（publication.py:128/:144），不在 stage/promote 事务内——一致性靠捕获时双 hash 校验而非锁；
- 失败状态机：ingest.py:517-529 blocked/failed 回写，guard 幂等（:527 已 published 不覆盖）。

### 2.3 「N 构造 N+1 时继续可读」的三层保证（已有）

1. **manifest 复制**：stage 复制 base 的 pages/dependencies（generations.py:78-90），N+1 未变更页面继承 N 条目；
2. **body 共享去重**：wiki_page_bodies 以 (vault_id, content_hash) 为键（031:18-23），INSERT OR IGNORE（:100）；完整性三处复核（:103-108/:145-152/:193-195）；
3. **head 单点 CAS + published 永不降级**：promote 仅在 base 未变时切换（:158-164）；031:5 status CHECK 只有 staged/published；_scope 只认 published（snapshot_reader.py:198-205）；显式 pin 旧 generation 继续有效（:69-83，API :74 暴露 generation 参数 + expected_version :76）。

### 2.4 版本化权限缺口（t11 §3.3，本草案要修的核心）

- **读路径不查 binding status**：snapshot_reader._load（:207-239）→ authorize 回调（:224-226）→ factory.py:506-536（vault 匹配 + 磁盘快照 + candidate 策略 + notes/chunks 全等）——**不查 wiki_page_bindings.status**，binding forgotten 后旧快照仍可读；
- **binding 状态机无 revoked**：021:65 CHECK IN ('active','stale','quarantined','forgotten')；'revoked' 仅存在于证据层（evidence_policy.py:12-18、memory_fact_artifact_bindings 1862-1871）——无法表达「某版本被撤销、其他版本仍有效」；
- **watermark 不含 binding 维度**：source_watermark.py:7-24 只含 wiki_sources+notes 摘要，source_observation（snapshot_reader.py:172-196）感知不到遗忘；
- **binding hash 与 generation hash 强耦合**：publication.py:29（发布时）+ memory_closure.py:872（合成时），均非读取时刻；
- **generation-aware 归档恢复缺失**：retrieval.py:613-614 拒绝 wiki_snapshot 引用（后续独立）。

---

## 3. 目标流程：Draft Generation → Validate → Review → Promote → 同步 Editable Markdown

### 3.1 Draft stage（compile 产物入 draft，不写盘）

- **复用 store.stage 承载 compile 产物**（t11 4.1）：stage 的 changes 接受路径→body 字节（generations.py:41-46），SafeMarkdownWriter 仅路径校验（:51-59），**不触碰工作文件**——draft 天然不落盘；write_page 从 apply（ingest.py:371）推迟到 promote 前；
- **draft 对正式查询不可见**：_scope（snapshot_reader.py:198-205）只认 status='published' → staged（draft）行天然不可见；需回归确认 pin/search/read 全部经 _scope 与 read_body 的 published 限定（generations.py:188）；
- **生命周期状态决策（关键决策 D1）**：**复用 'staged' 态承载 draft**，不扩展 031:5 的 CHECK（SQLite 3.37 避免重建表）——draft 生命周期（pending_review / reviewing / approved / rejected）写在 wiki_workflow_runs.result_json.publication.status（现有 JSON 域，ingest.py:501/:517-529 状态机模式），如 'draft_pending_review' / 'draft_reviewing' / 'draft_approved' / 'draft_rejected'；
- **target 收集门**：publication.py:100-104 只收 status='written' 的 page_updates——draft 期间 target 保持 'planned'（写盘成功后才置 'written'），draft 内容不会被 capture 误收，**无需新枚举**；
- **幂等**：032 已有 workflow_run_id 唯一索引；同一 run 重复 stage 复用既有 staged 行（参照 publication.py:105-111 previous 分支）。

### 3.2 Validate（两层校验）

- **内容层（draft stage 时即可做）**：compiler 已校验路径/类型/数量/引用（compiler.py:277-291）；stage 内 body UTF-8 解码（:63）与完整性（:103-108）已有；
- **权威层（写盘后、promote 前做）**：binding 创建/更新后跑 validate_wiki_page_roots + _dependency_stamp（复用 publication.py:145-151 的 capture 校验），并复用 promote 的同步 validator 点（generations.py:153-157，无模型调用、无提交）；
- 决策：权威校验不在 draft 阶段跑（此时 binding 尚不存在），**校验点 = 写盘步骤内 + promote 事务内**，保持现有语义。

### 3.3 Review（人工/审批门）

- 复用 ingest_review 模式（wiki_ingest_reviews 表 008、review_ingest 入口）与 confirm 确认流（ingest.py:87-98）：draft → review → approved / rejected；
- rejected 的 draft：保留行与审计（不删除、不写盘、不影响 G1）；
- 决策：review 状态存 result_json.publication（见 D1），review_id 复用 wiki_ingest_reviews 既有表（workflow_type 区分）。

### 3.4 Promote（写盘 → re-capture → promote）

**方案 A（推荐，t11 4.3）**——写盘时机移到 promote 前最后一步：
1. review approved 后：write_page 写工作 Markdown（带 target_content_hash 门禁，wiki.py:149-155/:167-173）→ bind（active）→ index_refresh（wiki.py:207）；page_updates.status 置 'written'；run status 置 'applied'（现有语义不变，仅触发点从 apply 移到此处）；
2. re-capture：读回磁盘双 hash 校验（publication.py:138-142）——保证 editable 文件与待发布 generation 内容一致；若外部编辑导致冲突 → wiki_publication_working_copy_changed → 写盘回滚/标记冲突（**人工修改保留**），draft 保留待重试；
3. promote：现有逻辑不变（body 复核、validator、head CAS、receipt）；receipt guard（generations.py:169-178 要求 status='applied'）与新时序兼容（写盘步骤已置 'applied'）；
4. 失败状态机复用：ingest.py:517-529 blocked/failed 回写，已 published 幂等不覆盖（:527）。

**方案 B（不推荐）**：promote 后异步落盘——破坏 _capture 的 working_copy_changed 语义（publication.py:138-142）且 read_evidence_snapshot（factory.py:509）依赖磁盘文件，需同步补偿。

### 3.5 同步 Editable Markdown

- 时序：**DB stage（draft）→ review → 写盘（editable md + binding + index）→ re-capture → promote**；
- promote 后 editable 文件与 published generation 一致（re-capture 保证）；用户/模型读 editable（factory.py:509）或 pinned generation（snapshot_reader）都看到同一权威内容；
- 外部修改保护：写盘 target_content_hash 门禁 + capture 双 hash + 写后 hash 复核（既有）；reconcile（api/memory/graph.py:250、memory_graph_kuzu.py:297）外部编辑→binding stale 的闭环保留。

---

## 4. 版本化权限修复（历史版本正文 vs 实时来源权限）

### 4.1 两层分离原则

**决策（关键决策 D2）**：彻底拆开两层，**权限判定永不信任 generation 内快照的权限字段**：
- **历史版本正文层**：wiki_page_bodies + wiki_generation_pages/manifest（内容寻址、不可变）→ 只回答「某版本正文是什么」；
- **实时来源权限层**：binding/source/候选/隐私状态 + 读取时实时查询 → 只回答「当前这个版本是否仍可被此用户/此用途使用」。

### 4.2 修复点（对应 t11 §3.3 缺口）

1. **读路径 authorize 补 binding 检查（P0）**：factory.py:506-536 authorize 增加 `wiki_page_bindings.status == 'active'` 判定（复用 memory_closure.py:870-873 的判定），forgotten/stale/quarantined → 拒绝（复用 wiki_snapshot_access_denied 映射 403）——binding 被遗忘后，**旧 generation 任一读入口立即不可用**（含 /wiki/pages/read、pin 读取、_neighbors）；
2. **revocation 落地（关键决策 D3）**：**不扩展 binding/generation 状态枚举，用可空时间列表达撤销**——036 迁移为 wiki_generations 与 wiki_page_bindings 各加 `revoked_at` / `revoked_reason`（纯加列，SQLite 3.37 无需重建表，与 035 的 wiki_sources.revoked_at 模式一致）：
   - generation 级撤销：置 wiki_generations.revoked_at → _scope 增加 `revoked_at IS NULL` 条件，该版本整体不可读（其他版本不受影响）；
   - 页面级撤销：置 binding.revoked_at → authorize 拒绝（同 P0 检查）；
   - 撤销是状态事件：保留正文与审计，不删行不删 body；
3. **privacy 实时判定**：读取时按 vault + 来源身份 + 隐私标记（既有 memory_permissions / RecallPermissions 管线）过滤；privacy 撤销后旧 generation 读取同样拒绝（同一实时判定点）；draft 阶段本身不可见；
4. **watermark 扩展**：source_watermark 查询（source_watermark.py:12-16）加入 binding status / revoked_at 维度 → source_observation 能感知遗忘与撤销；
5. **generation 内权限字段禁止**：manifest/依赖 stamp 只存正文哈希与根身份，不存权限状态；authorize 每次读取现查（deny-by-default）。

### 4.3 行为收紧声明

authorize 补 binding 检查是**行为收紧**：此前 binding forgotten 的旧快照仍可读（缺口），修复后拒绝。此语义变更须与 t8 已知限制决策①的落地对应，并在状态文档与测试锚点（test_wiki_archive_authority 等）显式登记。

---

## 5. 故障测试设计（G1 构造 G2 失败时 G1 继续可读）

**目标断言**：G1 published 后，任何 G2 构造失败（stage 失败 / promote 失败 / base 冲突 / 写盘冲突）都不破坏 G1 的可读性，且构造期间 G1 持续可读。

建议新测试文件 `tests/test_draft_first_faults.py`（沿用 test_wiki_generations 的 SQL abort 注入与 fixture 模式）：

| # | 用例 | 注入 | 断言 |
| --- | --- | --- | --- |
| 1 | test_g1_promote_then_g2_stage_fails_keeps_g1_readable | stage 内 body 完整性失败（伪造 body）或投影缺失 | stage 抛 wiki_generation_* 且事务回滚（无 G2 残留）；G1 pin 读取结果与失败前一致 |
| 2 | test_g2_promote_base_conflict_keeps_g1_head | 构造 base=G1 的 G2 与 G2'，先 promote G2' 再 promote G2 | G2 promote 抛 wiki_generation_base_conflict；head=G2'；G1 显式 pin 仍可读 |
| 3 | test_draft_invisible_to_queries_until_promoted | stage draft（含新页面），不 promote | search/read/pin(head) 均不含 draft 页面；promote 后可见 |
| 4 | test_draft_rejected_does_not_touch_working_copy | draft review=rejected | 工作目录无新文件；wiki_sources/binding 未变；rejected 行保留审计 |
| 5 | test_promote_write_collision_keeps_g1_and_manual_edit | 写盘前外部修改目标文件 | 写盘门禁或 capture 双 hash 失败 → publication blocked；人工修改保留；G1 可读 |
| 6 | test_forgotten_binding_revokes_old_generation_reads | G1 published 后 binding forgotten（及 revoked_at 场景） | pin G1 读取被拒（403 / wiki_snapshot_access_denied）；正文行与 body 保留 |
| 7 | test_g2_stage_mid_failure_rolls_back_manifest_copy | stage 中途 SQL abort（沿用 test_wiki_generations 注入模式） | 单事务回滚；无 staged 残留；G1 manifest/依赖未变 |
| 8 | test_concurrent_stage_same_base_only_one_promotes | 并发两个 promote（同 base） | 一个成功一个 base_conflict（复用/强化既有并发用例） |

失败注入方式：monkeypatch store.stage/promote 内部写点 + SQL abort 注入（既有模式）；断言核心 =「G1 的 pin 读取在失败前后字节级一致」。

---

## 6. 迁移与兼容（036_draft_first.sql 草案）

- **纯加列**：wiki_generations 加 `revoked_at` / `revoked_reason`；wiki_page_bindings 加 `revoked_at` / `revoked_reason`（可空，默认 NULL）；
- **不改 CHECK**：generation status 保持 ('staged','published')（draft 复用 staged，D1）；binding status 保持 ('active','stale','quarantined','forgotten')（撤销用时间列，D3）——避开 SQLite 3.37 的 CHECK 重建；
- 事务内执行 + 行数对账（035 模式）；回滚 = 恢复备份（加列可逆）；
- **兼容**：旧客户端/旧读取路径不变；authorize 收紧与 _scope revoked 检查是行为变更（见 4.3），按「明确登记 + 测试锚点」推进；draft 行对旧查询不可见（_scope 已保证）。

---

## 7. 关键决策摘要

1. **D1（draft 状态）**：复用 'staged' 承载 draft + result_json.publication.status 表达 draft 生命周期（pending_review / reviewing / approved / rejected），不改 031 CHECK；
2. **D2（两层分离）**：历史正文层（bodies/manifest，不可变）与实时权限层（binding/source/privacy，读取时实时判定）彻底分离；权限永不信任 generation 内快照字段；
3. **D3（revocation）**：用可空时间列 revoked_at / revoked_reason（generation 级 + binding 级）表达撤销，不扩展状态枚举，避开 CHECK 重建；撤销是状态事件，正文保留；
4. **写盘时机**：方案 A——promote 前最后一步「写盘 → re-capture → promote」，保持双 hash 校验语义与 run status='applied' 语义不变；
5. **读路径修复**：authorize（factory.py:506-536）补 binding status='active' 检查 + _scope 补 revoked_at IS NULL + watermark 加 binding 维度——forgotten / revoked / privacy 立即使旧 generation 不可用；
6. **故障测试**：8 用例以「G1 在 G2 构造失败前后读取一致」为核心断言；
7. **不做**：不清理 generation、不做归档恢复适配、不做自动写入；draft 保留期/配额与隐私全模型列为后续。

---

## 8. 引用

- t11 报告（docs/t11-phase-b-recon.md）：流水线事实 §1-2、阻断点清单 §3.1-3.2、缺口定位 §3.3（factory.py:506-536、snapshot_reader.py:207-239/224-226、source_watermark.py:7-24、021:65）、最小改动面 §4；
- t12 报告（docs/t12-versioned-authority-research.md）：版本化权限与内容失效模型；
- t8 阶段 A 记录（wiki-reconstruction-status.md Phase A 2026-09-20）：已知限制决策①（revocation 执行层 = 阶段 B 核心项）；
- T3 设计（docs/source-identity-migration-design.md）：§5 兼容层、§7 风险。
