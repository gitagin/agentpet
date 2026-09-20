# Source Identity 迁移设计（T3）

- 作者：review（AgentTeams）
- 日期：2026-09-19
- 输入：recon 盘点报告（.tmp/recon-source-identity-2026-09-19.md，T1）、webre 调研报告（docs/t2-source-identity-provenance-research.md，T2）、dev @ d7847cc 代码核对
- 状态：设计稿（待 T4 实现评审）

---

## 0. 目标与设计原则

**目标**：把「内容哈希当身份」改为「稳定来源身份 + 内容指纹 + 来源版本」三者分离，使「来源 A 与来源 B 正文相同」成为合法状态，同时不重建检索、不新增证据库、不改动既有 API 字段名/错误码/枚举值。

**原则**（来自 T1/T2 结论）：
1. content_hash 标识内容，source_id 标识来源实例（新闻去重：重复=同源头，与文本相似度无关；Git blob/ref、IPFS CID/IPNS 同构）。
2. 内容不可变 + 有效性状态可变（X.509 模型）：验证/过期/吊销是状态事件，不是删除内容。
3. 多来源并列保留（Wikidata 模型），绝不自动合并不同来源。
4. fail closed：任何无法确定性判定身份的场景，拒绝静默复用/静默合并，交给确认流或报既有冲突错误。
5. 兼容层：旧字段（source_hash、legacy evidence ID、legacy 标记、legacy 页面路径）继续可读，双写过渡一个发布周期。
6. 字段名按已有 schema 调整，不机械照搬外部命名（已有 ProvenanceKind 枚举、metadata_json、vault_id 作用域模型直接复用）。

---

## 1. 目标 schema

### 1.1 wiki_sources 现状与目标

现状（migrations/005/007/030 合并视图）：
- `id TEXT PRIMARY KEY`（new_id() UUID）——**已经是稳定身份**，本设计将其确立为 source_id 的唯一载体，不再新造列。
- `source_hash TEXT NOT NULL UNIQUE`（005:5，34 个迁移从未放宽）——**全局唯一约束是本设计要解除的核心**。
- source_type/source_uri/metadata_json/raw_content/vault_id 等保持不变。

目标 schema（新迁移 `035_source_identity.sql`）：

| 概念 | 落点 | 说明 |
| --- | --- | --- |
| source_id（稳定身份） | 既有 `id` 列 | 不新增列；语义上=来源实例。同正文不同来源=不同 id 行 |
| content_hash（正文哈希） | 既有 `source_hash` 列 | **列名不变**（API/代码兼容），角色=正文 sha256 指纹；UNIQUE 降级为非唯一索引 |
| source_version（来源版本） | 新列 `source_version INTEGER NOT NULL DEFAULT 1` | 同一 id 的内容修订号；内容变更=同 id 版本 +1 |
| 验证状态 | 新列 `verification_status TEXT NOT NULL DEFAULT 'unverified'` | 取值风格对齐 evidence_policy 既有集合：unverified/verified/stale/revoked/expired |
| 验证元数据 | 新列 `verified_at / verified_by / expires_at / revoked_at / revoked_reason`（均 NULL 默认） | 状态是事件，保留历史（revoked 记录在版本账本/审计） |
| 版本账本 | 新表 `wiki_source_version_history` | 见 1.3 |

```sql
-- 035_source_identity.sql（要点；实际按 SQLite 12 步重建表流程落地）
PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;
CREATE TABLE wiki_sources_new (
  id TEXT PRIMARY KEY,
  source_hash TEXT NOT NULL,            -- 不再 UNIQUE
  title TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_uri TEXT,
  content_preview TEXT NOT NULL,
  raw_content TEXT,
  tags_json TEXT NOT NULL DEFAULT '[]',
  links_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  source_version INTEGER NOT NULL DEFAULT 1,
  verification_status TEXT NOT NULL DEFAULT 'unverified',
  verified_at TEXT, verified_by TEXT,
  expires_at TEXT, revoked_at TEXT, revoked_reason TEXT,
  created_at TEXT, updated_at TEXT,
  vault_id TEXT REFERENCES vaults(id)
);
INSERT INTO wiki_sources_new (id, source_hash, title, source_type, source_uri,
  content_preview, raw_content, tags_json, links_json, metadata_json,
  created_at, updated_at, vault_id)
  SELECT id, source_hash, title, source_type, source_uri, content_preview,
    raw_content, tags_json, links_json, metadata_json, created_at, updated_at, vault_id
  FROM wiki_sources;
DROP TABLE wiki_sources;
ALTER TABLE wiki_sources_new RENAME TO wiki_sources;
CREATE INDEX idx_wiki_sources_hash ON wiki_sources(source_hash);  -- 非唯一，保持查询性能
CREATE INDEX idx_wiki_sources_vault ON wiki_sources(vault_id);
CREATE TABLE wiki_source_version_history (
  source_id TEXT NOT NULL REFERENCES wiki_sources(id),
  source_version INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  content_preview TEXT,
  raw_content TEXT,
  reason TEXT,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (source_id, source_version)
);
COMMIT;
PRAGMA foreign_keys=ON;
```

执行注意（T2 §四）：
- 项目 SQLite 由 CPython 3.10.7 自带（3.37+），**不支持 3.53 的 DROP CONSTRAINT**，走 12 步重建表；`PRAGMA foreign_keys` 在事务外关闭/恢复。
- 迁移必须是单事务 + 行数校验（迁移后 count 对账 + 抽样比对），失败整体回滚。
- wiki_sources 的父子表（wiki_workflow_runs、wiki_ingest_reviews）外键在重建期间无写入窗口即可；本地单机应用，维护窗口=迁移事务本身。

### 1.2 版本语义（同一 id 内容变更）

- 同一来源实例（source_type + source_uri + 身份元数据完全一致）再次 ingest 且正文变化 → **同 id，source_version += 1**，source_hash/raw_content/content_preview 原地更新，旧内容快照写入 `wiki_source_version_history`（reason='content_updated'）。
- 证据/关系的版本区分**不依赖 ID 内嵌版本号**，沿用现有机制：`_evidence_ids_for_source` 用 `evidence.source_text_hash = input.source_hash OR metadata.source_hash = input.source_hash` 过滤——版本 bump 后旧证据的 hash 不再匹配，自然退出该来源的当前证据集；ID 保持稳定（见 §2.1）。即：**证据身份=（source_id, 目标），版本敏感靠内容哈希比较**。
- 快照体系（031-033，wiki_page_bodies 以 (vault_id, content_hash) 为体键）天然保存已发布页面的旧正文，与版本账本互补：账本存「来源原始内容」，快照存「编译后页面内容」。

### 1.3 版本账本边界（明确不是第二套证据库）

`wiki_source_version_history` 只是 **wiki_sources 自身的既往内容账本**：写入路径唯一（仅版本 bump 时由 ingest 确认流写入），读取仅用于审计/回滚（无检索、无证据引用、不参与图关系）。这不属于「第二套证据库」（证据库=memory_evidence/memory_candidates 体系，本设计不新增）。

---

## 2. 受影响点改造方案

### 2.1 Evidence ID（memory_closure.py:1366-1388、memory_entity_extraction.py:537-558）

现状：
- wiki 系五个前缀全部以 source_hash 参与键：`wiki-entity-source-evidence`、`wiki-fact-source-evidence`、`wiki-page-evidence`、`wiki-entity-page-evidence`、`wiki-fact-page-evidence`。
- 抽取系已双代并存：legacy `extract-evidence-{sha256(hash:ref)[:32]}` vs 新 `extract-evidence-{sha256(source_id:hash:ref)[:32]}`，复用需 metadata 双字段校验，否则 fail closed。

改造（沿用抽取系已验证的双代模式）：
- **存量 ID 一律不重写**（稳定、可解析、metadata 可回填 source_id），兼容层继续可读。
- **新写入**：wiki 系 ID 键改为 (source_id, 目标)，如 `_entity_source_evidence_id(source_id, entity_id)`；ID 不内嵌版本号（§1.2）。
- **复用规则**（fail closed）：生成新式 ID 前，检查同 (source_id, 目标) 是否已有 legacy ID；有则校验 metadata.source_id 一致 + metadata.source_hash 一致才复用，任一不符 → `source_evidence_identity_mismatch`（既有错误码，不改）。
- **回填**：迁移期把 `memory_evidence.metadata_json` 中只有 source_hash 的行，按 §3 回填 source_id（迁移时 hash 仍唯一，回填无歧义；若发现歧义行 → 保持 NULL 并计入迁移审计计数，后续操作遇 NULL source_id 走 legacy 路径或 fail closed）。

### 2.2 Graph relation（memory_closure.py:386/407/456/653/679/699）

- 现状：`documented_in` 的 `source_text=f"{source_hash}:{relative_path}"`；synthesis 系 `source_text=f"{':'.join(source_hashes)}:{target_path}"`。
- 改造：新关系 `source_text=f"{source_id}:{relative_path}"`；synthesis 系 `source_text=f"{':'.join(source_ids)}:{target_path}"`。
- 兼容：既有关系 source_text 不改写（可读）；任何按 source_text 前缀解析 hash 的读取点改为：先按 source_id 前缀，无法解析时按 legacy hash 前缀并校验唯一性（见 §2.5）。
- `_annotate_fact_provenance`（1237-1294）：attribution 增补 `source_version` 字段；既有「source_id 不一致即 mismatch」规则不变（版本变化不算身份冲突，允许覆盖 metadata.source_version）。

### 2.3 Candidate（memory_closure.py:1146-1186、memory_entity_extraction.py）

- 现状：新候选 normalized_value=`wiki-source-id:{source_id}`；legacy 候选裸 hash + summary='Wiki source provenance'，复用须 `_validate_source_candidate` 全等校验。
- 改造：新候选 metadata 增加 `source_version`；legacy 复用规则不变（metadata 全等 + fail closed）。
- 实体键（memory_closure.py:1102-1109）：`wiki-source-id:{source_id}` 已 ID 化，同 hash 两来源天然两个实体键，无需改动；legacy `wiki-source:{source_hash}` 歧义检查保留。

### 2.4 Source page path（compiler.py:243、ingest.py:310）

- 现状双轨：编译流 `Wiki/Sources/{slug}-{hash[:12]}.md`，普通流 `Wiki/Sources/{slug}.md`。
- 改造：**新写入统一**为 `Wiki/Sources/{slug}-{source_id[:12]}.md`（两流一致；source_id 稳定、同标题不同来源不撞名、文件名不含哈希语义）。
- 存量文件不重命名（避免破坏 artifact_ref/binding）；新增解析助手 `resolve_source_page_path(path)`：优先按文档内「来源标识」标记解析，否则按既有 binding/relation（路径→page entity→source entity）解析，文件名仅作兜底匹配（strip 掉 -{id12} 后缀）。所有读侧（read_evidence_snapshot 调用方、synthesis source_paths 校验 `_safe_wiki_source_path`）经此助手归一。

### 2.5 Synthesis lookup（memory_closure.py:757-804 `_direct_source_for_page`、markdown.py:6-21）

- 现状：只读 legacy 标记 `- 来源哈希：`{hash64}`（body 正则），仅作校验不能选择来源；来源解析经 documented_in 关系 JOIN source entity metadata.source_id → wiki_sources。
- 改造：
  - markdown 写入侧（markdown.py 来源摘要页）：**双标记**——新写 `- 来源标识：`{source_id}`（版本 {source_version}）`，同时**继续写** `- 来源哈希：`{hash64}`（兼容旧读者）。
  - 读侧：优先解析「来源标识」并校验「来源哈希」一致；只有旧标记时走 legacy 路径（hash 在 vault 内唯一才可解析，**出现同 hash 多行（迁移后新状态）且无来源标识 → `synthesis_source_identity_ambiguous` fail closed**，复用既有错误码）。
  - 多来源并列：synthesis 的 source_hashes 列表改为 source_ids 列表（权威数据），哈希仅作一致性校验。

### 2.6 Compiler dependency（publication.py:22-52）

- 现状：依赖戳 = binding 行 + documented_in 关系 + 候选行哈希指纹 + 来源行 raw_content→sha256 与 source_hash 比对（wiki_publication_root_changed）；按 source_id JOIN wiki_sources（vault 限定）。
- 改造：指纹输入加入 `source_version` 与 `verification_status`（版本/状态变化应触发依赖变化）；同 hash 多行场景下依赖解析已经按 source_id 走（无需改），补一条防御断言：JOIN 结果 >1 行 → 报既有错误码。

### 2.7 Archive restoration（retrieval.py:599-682 restore_citations）

- 现状：必须带 content_hash（version_required），chunk 双 hash 校验；**拒绝 wiki_snapshot 引用**（snapshot_archive_not_supported，generation-aware adapter 属未来工作，本设计不实现）。
- 改造（增量，不动拒绝快照的既有行为）：
  - 普通 note 引用的恢复逻辑不变（与来源身份正交）。
  - 当引用路径位于 `Wiki/Sources/` 下：恢复时经 §2.4 的路径解析得到来源行；同 content_hash 在 vault 内命中多行（迁移后新状态）且引用未携带 source_id → **复用既有 version_required/not_current 拒绝语义**（fail closed，不改错误码）。
  - MemorySearchResult 增补**可选**字段 `source_id`、`source_version`（默认 None，纯增量，见 §6 兼容面清单），写入侧在 wiki 检索结果上填充；恢复时若有则直接校验，无则走唯一性判定。

### 2.8 Migration 自身（含测试修复）

- **先修 stale 测试**（recon §0 根因）：`tests/test_wiki_source_scope.py:319` 断言 `apply() == ["030_wiki_source_vault_scope"]` 已过期（031-034 未同步）。与 035 同一 PR 落地：断言改为「030-035 全部记录且 030/035 行内容正确」。
- 035 迁移内做：schema 重建（§1.1）+ 版本账本建表 + evidence metadata 回填（§3）+ 迁移后对账（行数、唯一性抽样、回填计数、歧义行计数必须为 0 或显式清单）。
- 迁移幂等：MigrationRunner 按文件名顺序 + schema_migrations 记录，天然幂等；回填语句可重复执行（按「仅当 metadata.source_id 缺失时写入」条件）。

---

## 3. 持久 provenance 结构

落点：既有 `metadata_json`（wiki_sources / memory_evidence / memory_candidates / memory_graph_facts / memory_entities）JSON 字段 + wiki_sources 新列。**字段名沿用已有风格（snake_case，与 source_hash/source_id/wiki_extraction_provenance 同族），不机械照搬 PROV 命名**。

| 概念 | 落点字段 | 取值/语义 | 与既有代码对齐 |
| --- | --- | --- | --- |
| provenance_kind | metadata.provenance_kind | **复用 evidence_policy.ProvenanceKind 枚举**（RAW_SOURCE/USER_STATEMENT/COMPILED_WIKI/SYNTHESIS/QUERY_REPORT/ASSISTANT_OUTPUT），已存在不新增 | candidates 已写（memory_closure.py:1174） |
| source_id | metadata.source_id | 来源实例 id（= wiki_sources.id） | 已广泛使用 |
| source_version | metadata.source_version | 证据/候选落地时捕获的来源版本号 | 新增（本节主要增量） |
| derived_from | metadata.derived_from | 派生文档（synthesis/compiled）的直接父来源 id 数组 | 新增；等价 PROV wasDerivedFrom |
| root_sources | metadata.root_sources | 沿 derived_from 回溯（深度上限 5）得到的根来源 id 数组；**集合非单值**（Wikidata 多来源并列） | 新增；写入时机=合成/编译落盘时解析 |
| 来源性质 | metadata.provenance_kind + source_type | 已覆盖全部 6 类 | 现有 |
| verification_status | wiki_sources 列 | unverified/verified/stale/revoked/expired；**状态独立于内容**，revoke/expire 不删行 | 值风格对齐 evidence_policy 既有集合 |
| permission | **复用 vault_id 作用域** | 来源权限=其所属 vault；不新增 ACL 表；读取侧继续走 memory_permissions/RecallPermissions 管线 | 030 已实现 |
| validity/expiry/revocation | wiki_sources 列 expires_at/revoked_at/revoked_reason + 版本账本 | expiry=时间触发降级（维护任务把 verified→stale）；revocation=状态事件（留 revoked_at/reason，内容保留） | 与 T2 2.3 结论一致 |
| vault scope | wiki_sources.vault_id | 不变 | 030 已实现 |

回填规则（迁移期）：
- `memory_evidence`/`memory_candidates`/`memory_graph_facts` 的 metadata 中只有 source_hash 的行：按 source_hash JOIN wiki_sources（**迁移期 hash 仍全局唯一 → 无歧义**）回填 source_id + source_version=1；JOIN 失败（hash 不在 wiki_sources，例如 diary/companion 派生的第三套 hash）→ **不动**（它们本就不属于 wiki 来源身份体系，recon §4.8 已识别三套 hash 概念，防混淆）。
- 回填用 `json_set` 且条件 `json_extract(metadata_json,'$.source_id') IS NULL`，幂等。

---

## 4. 用户陈述权威区分（偏好事实 vs 外部事实）

复用现有两套枚举，不新增：
- write_policy.py：`EvidenceLevel.explicit_user_statement` vs `external_source`；`ContentCategory.preference` vs `fact/event/...`。
- evidence_policy.py：source_type `explicit_user`/`user_message` → `ProvenanceKind.USER_STATEMENT`（memory_closure.py:57 EXPLICIT_USER_SOURCE_TYPES 已存在）。

**设计（两轴正交）**：
1. **陈述权威轴**（谁说的）：用户陈述（USER_STATEMENT）> 外部来源（RAW_SOURCE/COMPILED_WIKI/...）。
2. **事实范畴轴**（关于什么）：偏好类（preference/identity/relationship/health/crisis）vs 外部事实类（fact/event/...）。

规则：
- **偏好事实**（用户陈述 + preference 类）：用户是唯一权威；外部来源与其冲突时用户陈述优先（合成/回答时按此排序），且外部来源不能「纠正」用户偏好。
- **外部事实**（用户陈述 + fact 类，或外部来源）：用户陈述只权威于「用户确实说过这话」（provenance 记录），**不**赋予外部事实权威；验证状态默认 unverified，需外部来源独立印证后才升 verified。**不互相覆盖**：冲突时按 synthesis 现状保留双方声明（「preserve BOTH claims」，compiler.py:258-260 既有行为）。
- 落点：事实/证据 metadata 增加 `statement_authority: "user"|"external"|"mixed"` 与 `content_category`（写入时由提取/确认流填）；权威排序逻辑放在证据门（wiki_gate.py EvidenceGate）与合成提示词组装层（prompt_memory_assembler），不新增表。
- 用户陈述本身（原始消息）仍走 diary/chat 通道，本设计只影响其进入 wiki_sources/图证据时的标注。

---

## 5. 增量迁移步骤与回滚

### 5.1 步骤清单（每步独立可验证，顺序即依赖序）

| # | 步骤 | 内容 | 验证 |
| --- | --- | --- | --- |
| 0 | 测试前置修复 | test_wiki_source_scope.py 断言随 031-035 更新 | 聚焦身份套件全绿（recon §0） |
| 1 | 迁移 035 | schema 重建（去 UNIQUE、加 source_version/验证列）、版本账本建表、evidence metadata 回填、对账 | 行数一致、回填歧义计数=0、全量 pytest |
| 2 | 功能开关 | `source_identity_v2`（settings 既有机制）；**默认关**，关=完全保持 legacy hash 复用行为 | 开关切换回归 |
| 3 | Ingest 身份规则 | preview：hash 召回→candidates；confirm（BEGIN IMMEDIATE 内）：唯一身份全等→复用；身份全等+内容变→版本 bump（写账本）；身份无匹配→**新建行**（同 hash 多行合法）；多候选命中同身份或 legacy 行身份不可判定→fail closed（复用 `wiki_ingest_source_identity_conflict`/`wiki_ingest_source_scope_unverified`，**不新增错误码**） | test_wiki_ingest_source_identity + 新用例（同文双源、版本 bump、歧义拒绝） |
| 4 | Evidence ID 双代 | wiki 系五前缀新键（source_id）写入；legacy 复用校验；metadata 回填确认 | test_wiki_source_binding_identity、test_wiki_evidence_policy |
| 5 | 图关系/候选 | documented_in source_text 新格式；candidate metadata + source_version；实体键不变 | test_llmwiki_memory_closure、test_wiki_provenance |
| 6 | 页面路径统一 | 新写入统一 `{slug}-{source_id[:12]}.md`；resolve_source_page_path 助手；双标记写入 | test_wiki_compilation、test_wiki_workflows |
| 7 | Synthesis lookup | 来源标识标记优先解析；legacy 标记仅校验；歧义 fail closed | test_wiki_synthesis_roots、test_wiki_snapshot_reader |
| 8 | 编译依赖/水印 | publication 指纹 + source_version/verification_status；source_watermark 输入 + source_version | test_wiki_publication、test_wiki_source_watermark |
| 9 | 归档恢复 | restore_citations 路径解析 + 同 hash 歧义拒绝；MemorySearchResult 可选字段 | test_wiki_archive_authority、test_wiki_archive_recovery |
| 10 | 契约/前端 | WikiIngestPreviewResponse/AgentWikiProposalFields 加可选 source_version；regenerate openapi.json + types.gen.ts；openapi snapshot 测试显式更新 | test_openapi_snapshot |
| 11 | 开启 v2 | 开关打开；同文双源 E2E、版本 bump E2E、水印/依赖变化 E2E | 聚焦身份套件 + 新 E2E 全绿 |
| 12 | 清理（下一发布周期） | 移除 legacy 只读路径（标记、文件名兜底）、回收开关 | 回归锚点全绿 |

### 5.2 回滚方案

- **Schema 回滚**：迁移前备份 vault DB 文件；035 为「去 UNIQUE + 加列」的可逆变更——回滚=恢复备份，或（已产生同 hash 多行时）先按 §5.1-3 的裁决规则合并重复行再重建 UNIQUE（存在重复行时**拒绝**回滚，fail closed）。
- **数据回滚**：版本 bump 可用 `wiki_source_version_history` 还原（取最新账本行写回，version 减回）；版本账本本身可删表。
- **代码回滚**：开关关闭即回到 legacy 行为（双代写入在前一周期内无害）；新页面路径/新证据 ID 均附加式，旧读者保留。
- **契约回滚**：可选字段删除即可，无破坏（前端按缺省处理）。

### 5.3 兼容层（旧字段继续可读）

1. `source_hash` 列与 API 字段名**永不改名**（角色=content_hash）。
2. 继续写 `- 来源哈希：` 标记（双标记一个发布周期）。
3. legacy evidence ID（hash 键）持续可读、可复用（metadata 校验后）。
4. 两种页面路径形式均可解析（resolve_source_page_path）。
5. legacy candidate（裸 hash）复用逻辑保留。
6. 无 source_id 的旧证据行：查询时走 legacy hash 路径，vault 内歧义即 fail closed。

---

## 6. 明确「不做什么」（Out of Scope）

1. **不新增第二套证据库**：不建新的 evidence 类表；`wiki_source_version_history` 仅是来源自身内容账本（§1.3）。
2. **不重建检索**：FTS（unicode61 + _bigram_cjk）、向量索引、wiki_body_fts 全部不动；hash 唯一索引→非唯一索引保持查询性能（T2 4.3）。
3. **不改 API 字段名/错误码/枚举值**：既有字段、错误码（wiki_ingest_source_identity_conflict / scope_unverified / synthesis_source_identity_ambiguous 等）、ProvenanceKind 枚举值全部保留；仅允许**新增可选字段**（source_version / source_id / source_version 于 MemorySearchResult 等，默认 None）。
4. **不重写存量证据/关系/候选的 ID 与键**（只回填 metadata，不动主键）。
5. **不自动合并同内容来源**：重复仅召回，裁决走人工确认流（Zotero 模式）。
6. **不实现 generation-aware archive adapter**（快照引用恢复仍拒绝，属后续独立工作）。
7. **不引入签名/密码学 provenance**（SLSA/in-toto 仅参考，不引入）。
8. **不动第三套 hash 概念**（chat trace message_hash 标签、companion diary 派生哈希，recon §4.8）——它们与 wiki 来源身份无关，命名上防混淆即可。

---

## 7. 回归锚点与风险

**回归锚点**：test_wiki_source_scope、test_wiki_ingest_source_identity、test_wiki_source_binding_identity、test_wiki_synthesis_roots、test_wiki_provenance、test_wiki_evidence_policy、test_wiki_source_watermark、test_wiki_publication、test_wiki_archive_authority、test_openapi_snapshot + 新增：同文双源、版本 bump、legacy 歧义 fail-closed 用例。

**风险与开放问题**：
1. 同标题来源页路径撞名（slug 相同、source_id 前缀相同概率极低但存在）——路径助手需处理「解析到多页」（fail closed）。
2. 版本 bump 与既有 watermark 的交互：bump 改变 updated_at 已触发 wiki_sources_changed_during_query（既有行为），版本号加入后变化更显式，确认查询期 bump 的拒绝语义符合预期。
3. evidence 回填依赖「迁移期 hash 唯一」，若历史数据已存在同 hash 行（理论上不可能，UNIQUE 约束保证；防御性检查若发现 → 迁移中止 fail closed）。
4. 开关默认关 + 双代写窗口长度（建议一个发布周期），避免永久双轨。
