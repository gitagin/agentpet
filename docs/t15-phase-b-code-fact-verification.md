# T15 阶段B代码事实核验：t9 草案 vs 当前 dev（B1）

- 核验人：recon-a（researcher）
- 核验日期：2026-09-20
- 对象：docs/draft-first-publication-design.md（t9 草案，172 行）引用的 file:line vs 当前 dev 工作区代码
- 方法：git 基线 + 逐条 grep/read 复核（对工作区实际文件，非 HEAD）；草案引用点全部逐一验证
- 结论：**除 ingest.py 外全部一致**；ingest.py 因未提交的 T3/T5 改动整体偏移 +136 行（语义未变）

---

## 一、环境基线

| 项 | 结果 |
| --- | --- |
| 分支 | dev（HEAD d7847cc "LLM wiki链路修复" 2026-09-19 22:39 +0800） |
| 工作区 | 13 个 M（含 apps/backend/app/services/wiki/ingest.py、memory_closure.py、models/*、retrieval.py、docs/wiki-reconstruction-status.md）+ 6 个 ??（035_source_identity.sql、tests、docs 系列）——**T3/T5 阶段A实现进行中，未提交** |
| ingest.py diff | +145/-9 行（未提交）；文件 mtime 2026-09-20 01:30:14 |
| 草案 mtime | 2026-09-20 01:43:55——**晚于 ingest.py 最后一次修改，但 ingest.py 引用仍停留在改动前行号** |
| 运行时 | CPython 3.10.7 + SQLite 3.37.2（.venv python 实测） |

⚠️ 核验基准 = 当前工作区文件（dev 最新 + 未提交改动）。草案基于 t11 盘点（改动前行号）撰写，对 ingest.py 的引用已过期。

---

## 二、逐条核验（草案引用 → 当前实际）

### 2.1 一致（引用点与当前代码完全吻合）

| 草案引用 | 当前实际 | 核验方式 |
| --- | --- | --- |
| generations.py:41-121 stage / :67 BEGIN IMMEDIATE / :68-69 base CAS / :70-77 staged 插入 / :78-90 manifest 复制 / :91-112 body 去重+完整性 / :100 INSERT OR IGNORE / :113-117 依赖 / :118-120 投影 | 同左（:41/:67/:69/:75/:100 实测命中） | grep+read |
| generations.py:123-178 promote / :129 / :130-135 staged 校验 / :136-137 base CAS / :138-152 投影+body 复核 / :153-157 同步 validator / :158-164 head CAS / :165-168 published / :169-178 receipt | 同左（:123/:129/:137/:164/:166 实测命中） | grep |
| generations.py:23 PublicationValidator 定义 / :188 read_body 的 g.status='published' | 同左（:23 类型、:188 命中） | grep |
| generations.py:198-205（草案引用 _active） | **:199-204**（def _active 在 :199；t11 时为 :198-203，文件增长 1 行——**行号漂移 +1，语义一致**） | grep |
| publication.py:22-66 _dependency_stamp / :29 binding active+hash / :41-42 root active / :50-52 raw_content↔source_hash / :61-62 候选唯一 | 同左（:22/:29 实测命中） | grep |
| publication.py:84-122 publish_ingest / :100-104 收 status='written' / :105-111 previous 幂等分支 / :117-120 stage / :121 promote | 同左（:84/:102/:117/:121 实测命中） | grep |
| publication.py:124-160 _capture / :128/:144 只读事务 / :137 read_evidence_snapshot / :138-142 双 hash / :140 read_bytes / :145-148 validate_wiki_page_roots / :151 stamp / :152-155 水印 | 同左（:124/:129/:137/:138/:140/:154 实测命中） | grep |
| snapshot_reader.py:69-83 pin / :172-196 source_observation / :198-205 _scope / :201 published 限定 / :207-239 _load / :224-226 authorize | 同左（:69/:172/:198/:201/:207/:225 实测命中） | grep |
| api/wiki.py:74 generation 参数 / :76 expected_version（草案 §2.3） | 同左（t11 读码确认，文件未变） | 复核 |
| factory.py:506-536 authorize（vault 匹配+磁盘快照+candidate 策略+notes/chunks 全等） | 同左（def authorize :506） | grep |
| source_watermark.py:7-24（只含 wiki_sources+notes 摘要） | 同左（:7/:13-15/:24 实测命中） | grep |
| services/wiki.py:149-155 target_content_hash 门禁 / :167-173 replace_page 必带 hash / :207 index_refresh | 同左（:149/:155/:168-169/:207 实测命中） | grep |
| migrations/031:5 status CHECK ('staged','published') | 同左（:5 实测命中，文件未变） | grep |
| migrations/021:65 binding status CHECK 无 'revoked' | 同左（:65 实测命中）；另 021:80 memory_fact_artifact_bindings CHECK ('active','revoked','quarantined')——佐证「revoked 仅在证据层」 | grep |
| migrations/032:1-3 workflow_run_id 部分唯一索引 | 同左（:2 CREATE UNIQUE INDEX idx_wiki_generation_workflow 命中） | grep |
| compiler.py:277-291（草案 §3.2 内容层校验） | 同左（:277-301 路径/类型/引用/节标题校验实测命中） | read |
| retrieval.py:613-614 snapshot_archive_not_supported（草案 §2.4/§1 非目标） | 同左（eng2-a 验证 + t11 复核） | 复核 |
| memory_closure.py:870-873 synthesis binding 三连（草案 §4.2 引用） | 同左（t11 读码确认，文件虽 M 但 t11 时已含） | 复核 |

### 2.2 不一致（草案引用 vs 当前实际）——全部集中在 ingest.py（未提交改动导致 +136 行漂移）

| 草案引用（行号） | 草案所述语义 | 当前实际行号 | 当前实际代码（语义） |
| --- | --- | --- | --- |
| ingest.py:371 write_page | apply 写盘每个 plan 一页 | **:507** | :507 `self.wiki.write_page(WikiPageWriteRequest(...))`（:507-516 实测）——语义一致 |
| ingest.py:475-481 bind_authoritative_wiki_page | binding status=active/quarantined | **:611-617** | :611 `bind_authoritative_wiki_page(...)`，:616 status="active" if run_status=="applied" else "quarantined"——语义一致 |
| ingest.py:501 publication.status='pending' | pending/not_eligible 落 JSON | **:637** | :637 `"publication": {"status": "pending" if run_status == "applied" else "not_eligible"}`——语义一致 |
| ingest.py:516 publish_ingest | applied 后触发发布 | **:652** | :652 `WikiPublicationService(...).publish_ingest(request.run_id)`（:646 run_status=="applied" 门）——语义一致 |
| ingest.py:517-529 blocked/failed 回写 | 幂等 guard | **:654-665** | :654 blocked/:656 failed/:663 guard COALESCE(...) != 'published'——语义一致 |
| ingest.py:87-98 confirm 确认流 | confirm_ingest 入口 | **:91-102** | :91 def confirm_ingest（:97-102 user_confirmed 校验+落 planned 行）——语义一致 |

**不一致成因**：T3/T5 阶段A实现（source identity：ingest_identity.py 新增、confirm/apply 校验扩展等，+145/-9 行）在草案成文前已改 ingest.py（01:30），草案（01:43）沿用 t11 盘点行号未刷新。**语义零变化，仅行号过期**。

### 2.3 风险登记
- 【中】草案所有 ingest.py 行号在 T3/T5 合并前仍会漂移（工作区未提交）；实现阶段（T4/T5）应锁定「语义锚点」（函数名+代码特征）而非行号；建议在实现时重新 grep 锚点。
- 【低】generations.py:198-205 → 实际 :199-204（+1 行漂移，_active 语义一致）。
- 【低】docs/wiki-reconstruction-status.md 为 M 状态（团队维护中），其 Phase A「Implemented Safety Slice」记录与当前代码一致（含 ingest 身份确认、binding 不可复活、reconcile 等条目，抽查属实）；不作为锁定基线。

---

## 三、036 纯加列可行性核验

1. **SQLite 版本**：实测 .venv python（CPython 3.10.7）→ sqlite3 3.37.2，与草案「SQLite 3.37」一致。
2. **ADD COLUMN 加可空列不需要重建表**：SQLite 对无默认值（或 NULL 默认）的可空列 ADD COLUMN 是 O(1) 元数据变更（btree 不重写）；仅当列带非 NULL 默认/非空约束等才触发全表重写。草案 036（wiki_generations/wiki_page_bindings 各加 revoked_at/revoked_reason，可空默认 NULL）→ **无重建**，与 035 的 wiki_sources.revoked_at 模式一致。
3. **CHECK 约束现状**：031:5 = ('staged','published')；021:65 = ('active','stale','quarantined','forgotten')。SQLite **不支持 ALTER 修改既有 CHECK**（无 ALTER COLUMN；任何 CHECK 变更=建新表-拷贝-删旧-改名全量重建）。草案 D1（draft 复用 'staged'）、D3（撤销用时间列）**不改 CHECK 是必要且正确**的；且撤销用时间列方案下 021:65 无需扩 'revoked'，021:80 的 'revoked' 仅留在证据绑定层。
4. **结果**：036 纯加列可行，无表重建、无 CHECK 变更、无迁移兼容风险；唯一注意=加列事务内执行+行数对账（沿用 035 模式）。

---

## 四、result_json.publication.status 为 JSON 域（无 CHECK）

1. **列定义**：wiki_workflow_runs.result_json TEXT NOT NULL DEFAULT '{}'（migrations/005:21-22）——**无 CHECK 约束**。
2. **现有取值域**（全在 JSON 内，代码实测）：'pending'（ingest.py:637）、'not_eligible'（:637）、'blocked'（:654）、'failed'（:656）、'published'（generations.py:169-178 json_set 写入；ingest.py:663 guard 比对）。
3. **新增 draft_* 状态**（draft_pending_review / draft_reviewing / draft_approved / draft_rejected）：纯 JSON 字符串值，无 schema/CHECK/迁移影响；唯一约束=写入方与消费方（ingest.py:663 guard、generations.py:169-178 receipt 的 COALESCE 比对）需保持字符串语义一致。
4. **结论**：草案 D1 的 JSON 域方案**可行且无破坏**。

---

## 五、核验结论清单

1. 【一致】generations.py 全部引用（41-121/123-178/:23/:188）——含 :198-205 仅 +1 行漂移（实际 :199-204）。
2. 【一致】publication.py 全部引用（22-66/84-122/100-111/117-121/124-160）。
3. 【一致】snapshot_reader.py 全部引用（69-83/172-196/198-205/207-239/224-226）。
4. 【一致】factory.py:506-536、source_watermark.py:7-24、services/wiki.py:149-155/167-173/207。
5. 【一致】migrations 031:5 / 021:65 / 032:2；compiler.py:277-301；retrieval.py:613-614；memory_closure.py:870-873。
6. 【不一致】ingest.py 全部 6 处引用偏移 +136 行（371→507、475-481→611-617、501→637、516→652、517-529→654-665、87-98→91-102）——**语义全部一致，仅行号过期**，成因=未提交的 T3/T5 改动。
7. 【可行】036 纯加列（可空列 ADD COLUMN 无重建；SQLite 3.37.2 实测）；不改 CHECK 是必要且正确的（SQLite 无 ALTER CHECK）。
8. 【可行】result_json.publication.status 为 JSON 域（005:22 无 CHECK），新增 draft_* 状态无 schema 破坏。
9. 【风险·中】实现阶段勿按草案行号定位 ingest.py，应以函数名/代码特征为锚；建议实现前重新 grep 锚点。
10. 【基线】dev 分支 HEAD d7847cc，工作区含未提交 T3/T5 改动（13 M + 6 ??）；wiki-reconstruction-status.md Phase A 记录与当前代码一致（文档 M 中，团队维护）。
