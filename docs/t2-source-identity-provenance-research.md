# T2 外部经验联网调研：source identity / provenance / draft-first

- 调研人：webre（researcher）
- 调研日期：2026-09-19（所有访问日期同此）
- 方式：web_search 中英文关键词（约 35 次检索），来源以官方文档、工程博客、论文、GitHub issue/PR 为准
- 标记说明：【可借鉴】= 建议引入本项目的模式/结论；【仅参考】= 只作背景理解，不引入依赖

---

## 一、Content hash 作为 source identity 的问题

### 1.1 核心结论：内容哈希标识的是「内容」而非「来源事件」，两者必须分离
- 【可借鉴】新闻/语料库行业对此问题的定义最清晰：**重复 = 来自同一底层源头（同一通讯社电讯/同一 syndicate 稿件），与文本相似度无关**。一篇电讯被 50 家媒体照搬，内容哈希完全相同，却是 50 个不同的来源实例，必须保留 50 条记录及各自的出处。参见 "Noise-Robust De-Duplication at Scale"（定义 duplicates 为 same underlying news wire/syndicate source, regardless of textual similarity）：https://ar5iv.labs.arxiv.org/html/2210.04261v2
- 【可借鉴】推论：**content_hash 只应作为「疑似重复召回键」（非唯一索引），来源身份（source instance id）才是唯一键**。同一 hash 命中多个来源时是正常状态而非脏数据。
- 【可借鉴】Zotero 的去重实践印证：Zotero 不按内容哈希去重，而是按**元数据字段（标题/DOI/作者/年份等）做相似度匹配**，检出后由用户裁决合并；同一篇论文可合法存在于多个条目（不同来源/不同渠道导入）。https://www.zotero.org/support/duplicate_detection ；高校指南（Caltech FAQ）：https://libanswers.caltech.edu/faq/203894
- 【可借鉴】Evernote 官方对重复笔记的解释：重复主要来自**多设备同步与导入通道**（同一内容经不同通道各建一份），处理方式是「查找→人工合并」。https://evernote.com/ko-kr/learn/the-real-reason-you-have-duplicate-notes-and-how-to-fix-it （中文同理，官方多语言页面同一主题）
- 【仅参考】Notion 导入 Evernote 的已知缺陷（导入产生重复/合并冲突）——第三方导入器是重复的高发源，说明「导入 provenance（来自哪个通道）」应记入身份。https://www.zdnet.com/home-and-office/work-life/notions-evernote-import-has-some-unfortunate-design-flaws/

### 1.2 版本与身份分离的成熟先例
- 【可借鉴】Git：blob 内容寻址（SHA-1 = 内容指纹，内容变则 hash 变，blob 不可变），而**可变身份由 branch/tag/ref 提供**——内容层与身份层显式分离。https://git-scm.com/book/zh/v2/Git-%E5%86%85%E9%83%A8%E5%8E%9F%E7%90%86-Git-%E5%AF%B9%E8%B1%A1 （Git 对象模型：https://mintlify.wiki/git/git/internals/object-model ）
- 【可借鉴】IPFS/IPNS：CID 内容寻址导致「同一文档改一个字就是新对象」，为此引入 IPNS 可变指针层提供稳定名字。教训：**不能把内容指纹当稳定身份用**；需要一层「稳定逻辑身份 → 当前内容」的指针。https://docs.ipfs.tech/concepts/ipns/
- 【可借鉴】Stanford SDR 数字保存系统 Moab 设计：数字对象版本化——每个版本不可变、版本 id 独立、对象级稳定标识符指向版本序列；这是「对象身份 ≠ 内容 ≠ 版本」在学术保存领域的权威实践。https://purl.stanford.edu/vt105qd7230 （Code4Lib Journal 21 刊载：https://journal.code4lib.org/articles/8482 相关条目 https://openurl.ebsco.com/results?sid=ebsco:ocu:record&bquery=IS+1940-5758+AND+IP+21）
- 【可借鉴】Logseq/Anki 同步插件的变更检测经验：用 hash 检测「内容变了」触发重同步，但**身份始终是块级 UUID**，hash 只做变更检测不做身份。https://deepwiki.com/debanjandhar12/logseq-anki-sync/4.2-change-detection-and-hashing

### 1.3 对本项目（解除 content_hash UNIQUE）的直接启示
- 身份三要素分离：`source_id`（稳定 UUID，来源实例）+ `content_hash`（内容指纹，可重复）+ `canonical/source kind`（内容类型/权威性）。
- dedupe 用「hash 召回 + 相似度排序 + 人工/规则裁决」，绝不自动合并不同来源。
- 「相同内容不同来源」是合法状态：UNIQUE(content_hash) 应降级为非唯一索引（见主题四的迁移做法）。

---

## 二、Provenance 数据建模

### 2.1 W3C PROV（PROV-DM / PROV-O）——最成熟的 provenance 本体
- 【可借鉴】PROV 核心三元素：**Entity / Activity / Agent**；核心关系：`prov:wasDerivedFrom`（派生）、`prov:wasGeneratedBy`（生成）、`prov:wasAttributedTo`（归属）、`prov:wasInvalidatedBy`（失效）；**实体带显式的生成时刻与失效时刻（`prov:invalidatedAtTime`）**——这直接对应本项目的 `verification_status / revocation / expiry`：失效是实体的生命周期事件，不是删除。
  - PROV-DM: https://www.w3.org/TR/prov-dm/
  - PROV-O: https://www.w3.org/TR/2013/REC-prov-o-20130430
- 【可借鉴】映射建议：`provenance_kind` ≈ PROV 中 Entity 的类型化（文档/摘录/人工笔记/自动抓取/模型生成）；`derived_from` ≈ prov:wasDerivedFrom 链；`root_sources` ≈ 沿派生链回溯到的源头 Entity 集合；`verification_status` ≈ 实体上的断言状态（PROV 不内置，需扩展，见 2.3）。

### 2.2 多来源并列：Wikidata 模型是「相同内容不同来源」的标准答案
- 【可借鉴】Wikidata：**同一事实可有多个 statement（每条绑定自己的 qualifier + reference）**；qualifier 记录时间点、测量方法等上下文，reference 指向来源；多来源并列保留、不互相覆盖。这正是「同内容多来源」在知识图谱界的处理范式——每个来源一条记录，验证状态各算各的。https://www.wikidata.org/wiki/User:Markus_Schepke （qualifiers provide context for a Claim's value, such as a point in time, a method of measurement）
- 【仅参考】Europeana EDM 通过 OAI-ORE Aggregation 记录原始数据来源（数字遗产领域做法）：https://export.arxiv.org/pdf/2605.22093

### 2.3 verification / revocation / expiry 的成熟做法
- 【可借鉴】PKI/X.509 是「内容不可变但有效性可变」的经典模型：**证书（内容）长期不变，但「当前有效性」是独立、可变的运行时状态**——通过 CRL/OCSP 查询吊销状态，证书本身不修改；另有过期时间做自动失效。IETF Web PKI 运维草案明确区分「签发有效」与「当前状态」。https://datatracker.ietf.org/doc/html/draft-wpkops-revocation-00
  → 借鉴：`verification_status` 应是「当前状态表/字段」而非内容的一部分；revocation = 状态变更事件（保留历史），expiry = 时间触发的自动状态迁移。
- 【可借鉴】知识库内容过期治理（中文实践丰富）：
  - 阿里云：知识库过期内容如何治理（标记→通知→复审→下线 闭环）：https://developer.aliyun.com/article/1750481
  - WPS Comate：**为知识条目配置 TTL，自动管控与健康度监测**（知识失效提醒）：http://365.wps.cn/content/8b3e9968e122483b9a212fdec9fa4b90.html
  - 达观：内置「知识运维机器人」自动处理过期知识：https://www.datagrand.com/blog/%e8%be%be%e8%a7%82%e7%9f%a5%e8%af%86%e5%ba%93%e5%86%85%e7%bd%ae%e7%9f%a5%e8%af%86%e8%bf%90%e7%bb%b4%e6%9c%ba%e5%99%a8%e4%ba%ba%ef%bc%8c%e8%87%aa%e5%8a%a8%e5%a4%84%e7%90%86%e8%bf%87.html
  - Knowledge Freshness Loop 模式（定期复审循环）：https://huggingface.co/datasets/cy0307/awesome-loop-engineering/blob/main/patterns/knowledge-freshness-loop.md
  - 德文工程博客：陈旧 AI 知识库是定时炸弹（veraltete KI-Wissensbasen）：https://bbv-software.de/insights/blog/die-tickende-zeitbombe-veraltete-ki-wissensbasen/
  → 借鉴：每条验证过的内容带 `reviewed_at / reviewed_by / expires_at`；过期后 verification_status 自动降级（如 verified → stale），内容本身保留。
- 【仅参考】SLSA / in-toto 供应链 provenance：attestation 把「产物→构建过程→源码」绑定并签名，验证链支持失效（intoto 撤销/过期）。这是重密码学方案，知识库场景不引入，但其「验证状态独立于产物」思想可参考。https://kusari.cloud/blog/from-provenance-to-enforcement-slsa-in-toto-and-kubernetes-admission-control/ ；NIST code provenance 标准讨论：https://www-test.ct.nist.gov/system/files/documents/2021/11/19/06-Dan%20Lorenc-Criteria%20and%20Attestation%20Approaches%20for%20Code%20Provenance.pdf

### 2.4 RAG 中的 provenance 实践
- 【可借鉴】RAG 引用链标准形态：**回答 → 证据 chunk → 源文档/源 URL**（两级 derived_from），检索结果必须携带 chunk 级来源标识；Microsoft Learn RAG 检索模式模块把「引用/引文」作为把 RAG 从黑盒变透明研究工具的核心。https://learn.microsoft.com/zh-cn/training/modules/implement-vector-search-azure-database-postgresql/6-implement-retrieval-patterns-rag-pipelines （多语言页面同内容）
- 【可借鉴】阿里云工程文章：RAG 回答如何提供引用证据链（企业本地化部署实践）。https://developer.aliyun.com/article/1750498
- 【可借鉴】Microsoft Foundry 讨论：知识图谱 + 来源归因使 Agent 可解释（source attribution 映射到 chunk）。https://github.com/orgs/microsoft-foundry/discussions/449
- 【仅参考】FalkorDB GraphRAG 可靠性文档（引用 chunk 级 grounding 减少幻觉；embedding 变化/内容删除需重建）：https://docs.falkordb.com/graphrag/reliability-and-grounding
- 【可借鉴】AI2（Allen Institute）实践：2025 年 GeekWire 报道 AI2 将模型输出与训练数据关联（"glass box" 透明化）；其 OpenSciLM（Nature 论文）用检索增强语言模型生成带引用的科学文献综述；Semantic Scholar 开放数据平台提供论文级出处。这说明机构级实践就是把「输出→证据」做成可追溯链。
  - https://www.geekwire.com/2025/from-black-box-to-glass-box-ai2-links-ai-outputs-to-data-in-breakthrough-for-transparency/
  - https://allenai.org/blog/nature-openscilm
  - Semantic Scholar Open Data Platform: https://arxiv.org/abs/2301.10140 （检索到 html 版本 https://arxiv-org.ezproxy.obspm.fr/html/2301.10140v2 ）
- 【仅参考】Data Cards / Model Cards（Google PAIR 及 NeurIPS 论文）：面向 ML 数据集/模型的 provenance 文档化规范（数据来源、资助方、数据主体），与本项目形态差异大，只参考其「每个资产自带出处文档」的思路。https://datacentricai.org/neurips21/papers/112_CameraReady_Data_Cards.pdf ；https://zenodo.org/records/13796279/files/data-and-model-cards-rdm%40ki2024.pdf

---

## 三、Draft-first / staged publication（草稿→审阅→发布）

### 3.1 企业知识管理平台：显式内容状态机是事实标准
- 【可借鉴】Microsoft Dynamics 365 知识文章生命周期：**Draft → Approved → Scheduled → Published → Expired**，过期是内置状态。https://learn.microsoft.com/zh-cn/training/modules/creating-and-designing-knowledge-management-solutions/3-knowledge-article-lifecycle
- 【可借鉴】TeamDynamix 文章工作流与状态管理（Draft / Under Review / Approved / Published）：https://solutions.teamdynamix.com/TDClient/1965/Portal/KB/Article/163882/Article-Workflow-and-Status-Management
- 【可借鉴】Freshservice 知识库文章生命周期增强（Draft/Internal/Published/Archived，含审查日期）：https://support.freshservice.com/support/solutions/articles/50000013972-knowledge-base-article-lifecycle-enhancements
- 【可借鉴】Aha! 文档状态与工作流（自定义状态机 + 转移权限）：https://support.aha.io/aha-knowledge/support-articles/customizations/document-statuses-and-workflows~7538553731535336709
- 【仅参考】企业 Wiki 合规审批框架（ONES）：https://ones.com/blog/enterprise-wiki-approval-a-compliance-framework-guide/ ；Confluence 技术文档生命周期指南：https://confluence.atlassian.com/pages/viewpage.action?pageId=407721921

### 3.2 Docs-as-code：草稿分支 + 审阅合并 = 版本化发布流水线
- 【可借鉴】ReadMe 官方实践：「像发布功能一样发布文档」——**分支即草稿环境，review 后合并发布**；分支评审（branch reviews）让 API 文档变更走 PR 审阅。https://readme.com/blog/branches ；https://readme.com/blog/branch-reviews
- 【可借鉴】Directus content versioning：草稿版本与发布版本并存，随时新建草稿、发布后保留历史版本。https://directus.com/docs/guides/content/content-versioning
- 【仅参考】Sanity 程序化发布（MDP gate stack：多级门禁后才发布）：https://metaflow.life/blog/sanity-programmatic-blog-publishing

### 3.3 「旧内容稳定，但旧权限/旧验证不永久有效」的处理
- 【可借鉴】这是「内容不可变 + 有效性状态可变」的组合：**已发布版本只读、长期可访问（读权限/内容稳定），而 verification/approval 状态绑定复审周期**——状态过期后内容仍保留但降级标记（verified → stale/expired），并触发重新审阅。见 2.3 的 TTL/复审机制（WPS Comate TTL、阿里云过期治理、Freshservice 审查日期、Knowledge Freshness Loop）。
- 【可借鉴】发布即快照：发布动作把内容复制为不可变版本（版本号+时间戳），后续草稿改动不影响已发布版本——Directus/Git/ReadMe 分支模型均如此。权限模型上：**版本级 ACL 永久有效；状态级「已验证」有有效期**。
- 【仅参考】GitHub 类 Draft PR 工作流（draft-first PR workflow with iterative review cycles）作为协作层参考：https://github.com/costajohnt/oss-autopilot/issues/59

### 3.4 RAG/知识库编译流水线的门禁
- 【可借鉴】中文工程指南提出「质量门禁不只是测试通过率」——发布流水线应有内容质量门禁概念：https://github.com/yeasy/forward_deployed_engineering_guide/releases/download/preview-pdf/forward_deployed_engineering_guide.pdf
- 【仅参考】ContentFlow（AI 内容营销平台：策划→RAG 生成→审核→发布对账→可观测）展示「内容编译流水线」全链路形态：https://github.com/heee000/ContentFlow

---

## 四、数据库迁移：解除 UNIQUE 约束、向后兼容、fail-closed；SQLite 注意事项

### 4.1 SQLite 解除约束的机制约束
- 【可借鉴】SQLite 长期不支持 `ALTER TABLE ... DROP CONSTRAINT`，标准做法是 **12 步重建表流程**（建新表→拷贝数据→删旧表→改名→重建索引/触发器/视图），Stack Overflow 经典问答即此答案。https://stackoverflow.com/posts/1884893/revisions
- 【可借鉴】**SQLite 3.53.0（2026-04-09 发布）新增 DROP CONSTRAINT 能力**，NOT NULL / CHECK 等约束不再需要整表重建（Django 已据此优化迁移逻辑）——若项目可用新版本 SQLite，解除约束成本大降；否则走重建表。https://www2.sqlite.org/releaselog/3_53_0.html ；https://code.djangoproject.com/ticket/37068
- 【可借鉴】嵌入式 SQLite 迁移规范：用 `PRAGMA user_version` 记录 schema 版本、逐版本顺序迁移、每个迁移独立测试（OneUptime 博客有完整教程；drift/peekMyAgent 等项目的迁移文档同此模式）。https://oneuptime.com/blog/post/2026-09-08-version-migrate-embedded-sqlite-schema/view ；https://github.com/fengjikui/peekMyAgent/blob/main/docs/database-migrations.md ；https://github.com/tachyon-beep/skillpacks/blob/main/plugins/axiom-embedded-database/skills/using-embedded-database/schema-migrations.md
- 【可借鉴】SQLite 迁移坑：`PRAGMA foreign_keys` 在事务外关闭/恢复（否则重建表时外键校验干扰）；重建表期间旧客户端并发写会丢数据——需要应用层锁或维护窗口。https://pub.dev/documentation/drift/2.34.1/internal_versioned_schema/VersionedSchema/runMigrationSteps.html ；MySQL→SQLite 迁移问题记录（中文）：https://developer.aliyun.com/article/1528330

### 4.2 解除 UNIQUE 的存量数据处理（真实事故）
- 【可借鉴】**先清重复，再删约束**：meshmonitor 真实事故——迁移 103 时用户对 dup 和 keeper 通道都有权限，触发 UNIQUE 约束崩溃，修复 PR 专门在迁移中先合并重复行。https://github.com/Yeraze/meshmonitor/pull/3805 ；同类 issue：https://github.com/Yeraze/meshmonitor/issues/4119
- 【可借鉴】顺序：① 找出全部存量重复（按 hash 分组）→ ② 业务规则裁决保留项（如 keep 最早/最新/来源可信度最高）→ ③ 合并引用/重写外键 → ④ 才允许删约束；迁移脚本须幂等且对重复行报错即失败（fail-closed）。

### 4.3 向后兼容与 fail-closed
- 【可借鉴】Expand/Contract（并行变更）模式是解除约束的标准零停机路径：**expand 阶段**新增普通索引/新列保持双写兼容 → 等所有旧客户端升级（兼容窗口）→ **contract 阶段**删除旧唯一约束/旧索引。Bytebase 零停机迁移文档与 PGDay UK 2025 演讲均以此为正统做法。
  - https://www.bytebase.com/blog/zero-downtime-database-schema-migration/
  - https://pgday.uk/events/pgdayuk2025/sessions/session/201/slides/10/PGDay%20UK%202025%20-%20Expand_Contract%20Migrations.pdf
- 【可借鉴】fail-closed 要点：迁移在事务内执行、任一语句失败整体回滚；迁移后校验（行数、采样对比、约束存在性）；保留回滚路径（备份 + 旧 schema 快照）。Langflow 的 Alembic 迁移指南是现成范本（含回滚与校验要求）：https://github.com/langflow-ai/langflow/blob/5f7b3305d9a67a7de972f905fe188bd9693a0ff8/src/backend/base/langflow/alembic/DB-MIGRATION-GUIDE.MD
- 【可借鉴】性能兼容：把 UNIQUE 索引改为「非唯一索引」可保留按 hash 查询的性能（去重召回仍快），只是允许重复——这是解除约束时最平滑的落点。
- 【仅参考】商用数据库在线 DDL 对唯一约束的注意事项（长事务阻塞在线 DDL、升级观察期不支持在线 DDL 等，GaussDB 文档）：https://support.huaweicloud.com/intl/zh-cn/centralized-devg-v8-gaussdb/centralized-devg-v8-gaussdb.pdf ；金仓 Oracle 迁移避坑：https://www.kingbase.com.cn/explore/tech-blog/%e9%87%91%e4%bb%93%e6%95%b0%e6%8d%ae%e5%ba%93%e4%bb%8e-oracle-%e8%bf%81%e7%a7%bb%e7%9a%84%e5%ae%8c%e6%95%b4%e6%96%b9%e6%a1%88%e4%b8%8e%e9%81%bf%e5%9d%91%e6%8c%87%e5%8d%97/

---

## 五、10-15 条最关键要点

1. **内容哈希 ≠ 身份**：哈希标识内容字节/语义，来源身份是独立事件；「同内容多来源」是合法状态（新闻去重领域定义：重复=同源头，与文本相似度无关）。
2. **身份三要素分离**：稳定 source_id（UUID）+ content_hash（可重复指纹，非唯一索引）+ provenance（来源通道/事件）；hash 只做疑似重复召回。
3. **版本与身份分离有成熟先例**：Git（blob 内容寻址 + ref 可变身份）、IPFS/IPNS（CID + 可变指针）、Stanford Moab（对象标识符 + 不可变版本序列）。
4. **Zotero 模式**：按元数据相似度召回重复 + 人工裁决合并，绝不自动按内容合并不同来源。
5. **PROV-O 是 provenance 本体标准**：Entity/Activity/Agent + wasDerivedFrom/wasGeneratedBy + invalidatedAtTime；derived_from/root_sources/revocation/expiry 都能在 PROV 语义中找到对应。
6. **Wikidata 多来源并列模型**：同一事实多条 statement，各自带 qualifier（时间/方法）与 reference（来源），互不覆盖——root_sources 是集合而非单值。
7. **验证状态独立于内容**（X.509 启示）：内容不可变 + verification_status 作为可变当前状态；revocation 是状态事件（留历史），expiry 是时间触发的自动降级。
8. **知识过期治理是成熟工程**：TTL/复审日期/reviewed_at/expires_at 字段 + 自动生成复审任务（WPS Comate、阿里云、Freshservice、Knowledge Freshness Loop）。
9. **RAG provenance 两级链**：回答 → 证据 chunk → 源文档/URL；chunk 级来源标识是行业标准形态（Microsoft Learn、阿里云、AI2 OpenSciLM、Foundry KG attribution）。
10. **Draft-first 状态机是 KM 平台事实标准**：Draft → Review → Published → Expired/Archived，状态转移带权限（Dynamics 365、TeamDynamix、Freshservice、Aha!）。
11. **Docs-as-code 即草稿-审阅-发布流水线**：分支=草稿环境、PR review=审阅、合并=发布、版本历史=已发布快照（ReadMe、Directus）。
12. **「旧内容稳定但旧验证不永久有效」= 内容版本不可变 + 有效性状态有生命周期**：发布版只读长期可访问，verified 状态按复审周期过期降级为 stale，不删除内容。
13. **SQLite 解除约束**：3.53.0（2026-04）起支持 DROP CONSTRAINT；旧版本走 12 步重建表；用 PRAGMA user_version 管版本，foreign_keys 需在事务外处理。
14. **先清重复再删约束**：迁移前必须合并存量重复行（meshmonitor 事故教训），否则 UNIQUE 崩溃；迁移脚本幂等 + fail-closed。
15. **Expand/Contract 是解除唯一约束的零停机正道**：先加普通索引/双写兼容 → 旧客户端升级窗口 → 再删旧约束；事务内执行 + 迁移后校验 + 备份回滚路径。

---

## 附录：主要来源清单（均访问于 2026-09-19）

| # | 来源 | URL |
|---|------|-----|
| 1 | Noise-Robust De-Duplication at Scale（新闻去重定义） | https://ar5iv.labs.arxiv.org/html/2210.04261v2 |
| 2 | Zotero 重复检测官方文档 | https://www.zotero.org/support/duplicate_detection |
| 3 | Evernote 重复笔记原因与修复 | https://evernote.com/ko-kr/learn/the-real-reason-you-have-duplicate-notes-and-how-to-fix-it |
| 4 | Git 内部原理（内容寻址） | https://git-scm.com/book/zh/v2/Git-%E5%86%85%E9%83%A8%E5%8E%9F%E7%90%86-Git-%E5%AF%B9%E8%B1%A1 |
| 5 | IPFS IPNS 概念（可变指针） | https://docs.ipfs.tech/concepts/ipns/ |
| 6 | Stanford Moab 数字对象版本化设计 | https://purl.stanford.edu/vt105qd7230 |
| 7 | W3C PROV-DM | https://www.w3.org/TR/prov-dm/ |
| 8 | W3C PROV-O | https://www.w3.org/TR/2013/REC-prov-o-20130430 |
| 9 | Wikidata qualifiers（多来源并列模型） | https://www.wikidata.org/wiki/User:Markus_Schepke |
| 10 | IETF Web PKI Revocation and Status | https://datatracker.ietf.org/doc/html/draft-wpkops-revocation-00 |
| 11 | 阿里云：知识库过期内容治理 | https://developer.aliyun.com/article/1750481 |
| 12 | WPS Comate 知识失效提醒/TTL | http://365.wps.cn/content/8b3e9968e122483b9a212fdec9fa4b90.html |
| 13 | Knowledge Freshness Loop | https://huggingface.co/datasets/cy0307/awesome-loop-engineering/blob/main/patterns/knowledge-freshness-loop.md |
| 14 | SLSA/in-toto 与准入控制 | https://kusari.cloud/blog/from-provenance-to-enforcement-slsa-in-toto-and-kubernetes-admission-control/ |
| 15 | Microsoft Learn：RAG 检索模式与引用 | https://learn.microsoft.com/zh-cn/training/modules/implement-vector-search-azure-database-postgresql/6-implement-retrieval-patterns-rag-pipelines |
| 16 | 阿里云：RAG 引用证据链 | https://developer.aliyun.com/article/1750498 |
| 17 | Microsoft Foundry：KG + source attribution | https://github.com/orgs/microsoft-foundry/discussions/449 |
| 18 | GeekWire：AI2 glass box 输出溯源 | https://www.geekwire.com/2025/from-black-box-to-glass-box-ai2-links-ai-outputs-to-data-in-breakthrough-for-transparency/ |
| 19 | AI2 OpenSciLM（Nature） | https://allenai.org/blog/nature-openscilm |
| 20 | Dynamics 365 知识文章生命周期 | https://learn.microsoft.com/zh-cn/training/modules/creating-and-designing-knowledge-management-solutions/3-knowledge-article-lifecycle |
| 21 | TeamDynamix 文章工作流与状态 | https://solutions.teamdynamix.com/TDClient/1965/Portal/KB/Article/163882/Article-Workflow-and-Status-Management |
| 22 | Freshservice 知识库文章生命周期 | https://support.freshservice.com/support/solutions/articles/50000013972-knowledge-base-article-lifecycle-enhancements |
| 23 | Aha! 文档状态与工作流 | https://support.aha.io/aha-knowledge/support-articles/customizations/document-statuses-and-workflows~7538553731535336709 |
| 24 | ReadMe：分支发布文档 | https://readme.com/blog/branches |
| 25 | ReadMe：分支评审 | https://readme.com/blog/branch-reviews |
| 26 | Directus 内容版本化 | https://directus.com/docs/guides/content/content-versioning |
| 27 | SQLite DROP CONSTRAINT 经典问答 | https://stackoverflow.com/posts/1884893/revisions |
| 28 | SQLite 3.53.0 发布日志 | https://www2.sqlite.org/releaselog/3_53_0.html |
| 29 | Django ticket 37068（3.53 免重建表） | https://code.djangoproject.com/ticket/37068 |
| 30 | OneUptime：嵌入式 SQLite schema 迁移 | https://oneuptime.com/blog/post/2026-09-08-version-migrate-embedded-sqlite-schema/view |
| 31 | meshmonitor PR #3805（UNIQUE 迁移事故修复） | https://github.com/Yeraze/meshmonitor/pull/3805 |
| 32 | Bytebase 零停机迁移（expand/contract） | https://www.bytebase.com/blog/zero-downtime-database-schema-migration/ |
| 33 | PGDay UK 2025 Expand/Contract 演讲 | https://pgday.uk/events/pgdayuk2025/sessions/session/201/slides/10/PGDay%20UK%202025%20-%20Expand_Contract%20Migrations.pdf |
| 34 | Langflow Alembic 迁移指南 | https://github.com/langflow-ai/langflow/blob/5f7b3305d9a67a7de972f905fe188bd9693a0ff8/src/backend/base/langflow/alembic/DB-MIGRATION-GUIDE.MD |
| 35 | 质量门禁不只是测试通过率 | https://github.com/yeasy/forward_deployed_engineering_guide/releases/download/preview-pdf/forward_deployed_engineering_guide.pdf |
