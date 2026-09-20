# B4 036 迁移设计与契约预检（T18）

- 作者：eng2-a（AgentTeams）
- 日期：2026-09-20
- 输入：t9 草案（docs/draft-first-publication-design.md，D1/D2/D3/§5/§6）、t15 核验报告（docs/t15-phase-b-code-fact-verification.md）、t11 盘点（docs/t11-phase-b-recon.md）、代码复核（migrations 005/008/021/031/032/033、ingest.py、publication.py、generations.py、snapshot_reader.py）
- 状态：设计草稿（B4 仅设计，不实现业务代码；036 由 B5 落地）

---

## 1. 036 迁移设计：generation 级 + binding 级撤销（D3 落地）

### 1.1 方案确认（ADD COLUMN 纯加列）

| 项 | 结论 | 依据 |
| --- | --- | --- |
| 表 | wiki_generations、wiki_page_bindings 各加 2 列 | t9 §6（D3） |
| 列 | `revoked_at TEXT`（可空）、`revoked_reason TEXT`（可空），默认 NULL | t9 §4.2-2 |
| 重建 | 不需要——SQLite 3.37.2（CPython 3.10.7 实测）可空列 ADD COLUMN 无重建 | t15 ③ |
| CHECK | 不改——generation status 保持 ('staged','published')；binding status 保持 ('active','stale','quarantined','forgotten')，撤销用时间列表达 | t9 D1/D3、t15 ③（SQLite 无 ALTER CHECK） |
| 外键 | 不涉及——新列无 REFERENCES，无需 PRAGMA foreign_keys OFF | 035 机制不适用 |
| 语义 | 撤销是状态事件：置列即撤销，正文/body/审计保留，不删行 | t9 §4.2-2、D3 |

### 1.2 036_source_revocation.sql 草稿

```sql
-- 036_source_revocation.sql —— 版本化权限：generation/binding 级撤销时间列
-- 设计:docs/draft-first-publication-design.md §4.2(D3)/§6;事实:t11 §3.3、t15 ③
-- 目标:以可空时间列表达「撤销」状态事件,不扩展状态枚举、不重建表、不改 CHECK——
--   generation 级撤销(置 revoked_at)→ 读路径 _scope 增加 revoked_at IS NULL,该版本整体不可读;
--   binding 级撤销(置 binding.revoked_at)→ 读路径 authorize 拒绝(与 status='active' 同点判定);
--   正文与审计保留:不删行、不删 body、不写 dependency stamp。
-- 执行机制:纯 ADD COLUMN(可空、默认 NULL),SQLite 3.37 无需 12 步重建、无需关外键;
--   单事务执行(035 模式)+ 行数/列数对账,失败整体回滚。
-- 注释内不使用 ASCII 分号(迁移语句切分器按分号切分)。

ALTER TABLE wiki_generations ADD COLUMN revoked_at TEXT;
ALTER TABLE wiki_generations ADD COLUMN revoked_reason TEXT;

ALTER TABLE wiki_page_bindings ADD COLUMN revoked_at TEXT;
ALTER TABLE wiki_page_bindings ADD COLUMN revoked_reason TEXT;

-- 对账:四列全部落地,且存量行新列均为 NULL(纯增量、无数据迁移)
CREATE TEMP TABLE _m036_reconcile (ok INTEGER CHECK (ok = 1));
INSERT INTO _m036_reconcile(ok)
SELECT CASE WHEN
  (SELECT COUNT(*) FROM pragma_table_info('wiki_generations')
    WHERE name IN ('revoked_at','revoked_reason')) = 2
  AND (SELECT COUNT(*) FROM pragma_table_info('wiki_page_bindings')
    WHERE name IN ('revoked_at','revoked_reason')) = 2
  AND (SELECT COUNT(*) FROM wiki_generations
    WHERE revoked_at IS NOT NULL OR revoked_reason IS NOT NULL) = 0
  AND (SELECT COUNT(*) FROM wiki_page_bindings
    WHERE revoked_at IS NOT NULL OR revoked_reason IS NOT NULL) = 0
THEN 1 ELSE 0 END;
DROP TABLE _m036_reconcile;
```

### 1.3 索引考虑

- **不新增索引（推荐）**：读路径查询量级小且已有索引覆盖——
  - generation 读：`_scope` 按 (id, vault_id, status) 精查（snapshot_reader.py:198-205），表小；
  - binding 读：既有 `idx_wiki_page_bindings_path(vault_id, wiki_relative_path, status)`（021:71-72）覆盖路径+状态查询；
  - 撤销筛选（`revoked_at IS NULL`）为低选择性过滤，索引无收益。
- 若后续 revoked 行量级增长：追加部分索引（如 `(vault_id, wiki_relative_path) WHERE revoked_at IS NULL`）作为独立增量迁移，ADD 可逆。

### 1.4 回滚说明

- 主路径：迁移前备份 vault DB 文件，恢复备份即回滚（035 同策略）。
- 技术备选：SQLite 3.35+ 支持 DROP COLUMN（3.37.2 可用），可 `ALTER TABLE ... DROP COLUMN revoked_at/revoked_reason`；但代码库惯例为备份恢复，DROP COLUMN 仅作运维备注。
- 迁移幂等：MigrationRunner 按文件名 + schema_migrations 记录，天然幂等；对账失败 → CHECK 中止 → 单事务整体回滚，无部分应用态。

---

## 2. 契约预检

### 2.1 result_json.publication.status 新增 draft_* 值（兼容性）

- **存储域**：`wiki_workflow_runs.result_json TEXT NOT NULL DEFAULT '{}'`（005:22），**无 CHECK/约束**，publication 为纯 JSON 域 → 新增 `draft_pending_review / draft_reviewing / draft_approved / draft_rejected`（t9 D1）无 schema 破坏。
- **现有值域**：pending / not_eligible（ingest.py:637）、blocked（:654）、failed（:656）、published（generations.py:175）。
- **唯一读取点**：ingest.py:663 幂等 guard——`COALESCE(json_extract(result_json,'$.publication.status'),'') != 'published'` 才允许覆盖回执。draft_* 值永不为 'published'，guard 不拦截、语义兼容（draft 运行被 promote 后才写 published，写后 guard 生效）。
- **测试读取点**：test_wiki_publication.py:12-15 publication_record 只断言 status 字段值——draft 用例按新值断言即可，无破坏。
- **结论**：纯增量 JSON 值，无迁移、无 schema 风险；新读者按前缀 `draft_` 判定，旧读者（不读该字段）不受影响。

### 2.2 OpenAPI / 类型生成影响

- 036 无新 API 字段：revoked_at/revoked_reason 为 DB 内部列（不进模型）；publication.status 不进响应模型（WikiIngestPreviewResponse 的 status 是 run 状态，非 publication 状态）。
- 若 B5 需向客户端暴露 draft 状态：按 035 模式新增**可选**字段（默认 None），届时再 `python -m app.openapi_export` + 契约测试显式更新（test_openapi_snapshot）。
- **结论**：当前 036 不触发 openapi.json / types.gen.ts 任何变更。

### 2.3 wiki_ingest_reviews 复用（review 门）

- **表结构**：008 无 CHECK（status TEXT、summary/findings_json 自由域）；run_id 外键仅引用 wiki_workflow_runs(id)，与 workflow_type 无关 → draft review 行可直接复用。
- **workflow_type 域**：自由 TEXT（005:17），现仅 'ingest' 被 3 处过滤使用（publication.py:89、generations.py:174、ingest.py:383）。
- **推荐（零 schema 变更）**：draft 流程沿用 `workflow_type='ingest'`（D1 生命周期写在 result_json.publication.status），review 门复用 review_ingest / _insert_review（ingest_review.py:7）；draft-review 与 ingest-review 的区分用 `run.status`（staged/applied）+ publication.status 前缀（draft_*）判定。
- **备选（不推荐）**：新增 `workflow_type='draft'` 需同步更新上述 3 处过滤点，列入 B5 改动面。
- **review 门字段兼容**：reviewer_agent_id/status/summary/findings_json/recommended_targets_json 全部可复用；rejected 的 draft 保留行与审计（t9 §3.3）。

---

## 3. 测试脚手架：B3 可复用 fixture 清单

| 来源 | fixture/helper（文件:行） | 用途 |
| --- | --- | --- |
| tests/test_wiki_workflows.py | `_workflow_service`(:1665)、`_confirm_ingest`(:1623)、`_ingest_source_page`(:1601)、`_assert_apply_rejected_without_writes`(:1630)、`_vault_file`(:1661) | 服务构造/全链路 ingest/落盘断言 |
| tests/test_wiki_ingest_source_identity.py | `confirm`(:19)、`source_record`(:27)、`service` fixture(:34)、`request_data`(:40) | 确认流 + 来源行快照断言 |
| tests/test_wiki_source_scope.py | `services` 双 vault fixture(:29)、`confirm`(:42)、`ingest_request`(:38) | 跨 vault 场景 |
| tests/test_wiki_generations.py | storage fixture + SQL abort 注入模式（伪造 body/投影缺失/并发单胜） | G1/G2 故障注入（t9 §5 用例 1/2/7/8） |
| tests/test_wiki_publication.py | `published` fixture(:18)、`publication_record`(:12) | 已发布态基底 + 回执断言 |
| tests/test_wiki_snapshot_reader.py | `reader_for`(:10)（published 复用）、test_wiki_snapshot_api.py | pin/search/read 可见性断言（t9 §5 用例 3/6） |
| tests/test_wiki_compilation.py | CompilerModel、compile_preview、apply_preview、service_for | 编译流 draft 输入构造 |
| tests/test_wiki_synthesis_roots.py | `compiled_sources` fixture、`authority`(:20) | 根来源/证据断言 |
| tests/_schema.py | migrate_db、migrate_db_with_vault、migrated_connection | 迁移级用例 |
| tests/wiki_fixtures.py | indexed_citation | 纯文件+索引场景 |
| tests/conftest.py | client_factory、auth_headers、clear_settings_cache | API 层用例 |

B3 建议落点：`tests/test_draft_first_faults.py`（t9 §5 的 8 用例），以 `published` fixture + SQL abort 注入组合，核心断言「G1 pin 读取在 G2 构造失败前后字节级一致」。

---

## 4. 关键结论

1. **036 = 4×ADD COLUMN 纯加列**：wiki_generations + wiki_page_bindings 各加 revoked_at/revoked_reason（可空）；无重建、无 CHECK 变更、无 FK 涉及、无索引新增；单事务 + 对账 guard（035 模式）；回滚=备份恢复。
2. **契约预检全部通过**：draft_* 为纯 JSON 增量值（唯一 guard ingest.py:663 兼容）；无 OpenAPI/类型生成影响；wiki_ingest_reviews 零 schema 变更可复用（workflow_type 沿用 'ingest'，按 run.status + draft_* 前缀区分）。
3. **B5 实现面提示**：读路径收紧（factory.py:506-536 补 binding 检查、snapshot_reader._scope 补 revoked_at IS NULL、watermark 加 binding 维度）是行为变更，须按 t9 §4.3 登记（状态文档 + 测试锚点）；行号定位以函数名/代码特征为锚（t15 ⑥，ingest.py 已 +136 行漂移）。
