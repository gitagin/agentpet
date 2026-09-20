# T16/B2 外部经验调研：工作副本同步与草稿审批（阶段 B 预研）

- 调研人：webre-a（researcher，AgentTeams）
- 调研日期：2026-09-19（所有条目访问日期同此）
- 方式：web_search 中英文关键词（约 20 次检索）；来源以官方文档、工程博客、论文、GitHub issue/PR、Wikipedia 为准
- 标记说明：【可借鉴】= 建议引入本项目阶段 B（写盘→re-capture→promote + review 门）的模式/结论；【仅参考】= 只作背景理解，不引入依赖
- 关联输入：T3 设计（docs/source-identity-migration-design.md）、T1 盘点（.tmp/recon-source-identity-2026-09-19.md）、T2 调研（docs/t2-source-identity-provenance-research.md）、T12 调研（docs/t12-versioned-authority-research.md）

---

## 一、工作副本与版本库同步（git-like working copy sync）

### 1.1 双写一致性：数据库事务 + 磁盘文件是「两个资源」，必须消除第二提交点
- 【可借鉴】**事务性 Outbox（transactional outbox）是「DB 与外部存储双写」的标准解**：业务事务内只写 DB（含一张 outbox 表记录待发布意图），事务提交后由后台中继把意图投递到外部资源（文件/消息/索引）；中继可重试、可幂等重放，天然覆盖「写盘失败」的补偿。AWS Prescriptive Guidance 官方模式文档：https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
- 【可借鉴】推论：**「写盘→re-capture→promote」本身就是 outbox 形态**——DB 的 staged generation + 依赖戳是事务事实，磁盘文件是投递物；promote 前失败只影响投递物（可重试发布），promote 后失败只影响 DB 状态（可审计回滚）。本项目已有雏形：wiki_generations.status='staged' + WikiPublicationService.publish_ingest 幂等重试（T1 盘点 + tests/test_wiki_publication.py::test_failed_publication_can_resume_without_rewriting_working_copy），应显式按 outbox 语义加固：中继必须幂等、重试必须有界、投递物必须可重新生成。
- 【仅参考】Saga 补偿模式（面向跨服务长事务，比本项目重）：每个步骤配补偿动作，失败沿反向补偿。https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/saga.html
- 【仅参考】COM+ Compensating Resource Manager：把非事务资源（文件）包成可投票/可补偿的资源管理器参与两阶段提交——展示了「文件参与事务」的复杂度，本地单机场景不必走到这步，用 outbox 更简单。https://learn.microsoft.com/en-us/archive/msdn-magazine/2001/march/com-create-a-compensating-resource-manager-to-extend-your-app-s-transactional-features

### 1.2 变更检测：外部编辑 vs 内部写入（git stat-cache 模式）
- 【可借鉴】**Git 检测工作树外部修改 = 索引 stat cache**：索引记录每个文件的 (mtime, size, ctime, inode) 等 stat 快照，git status 先比 stat，命中才读内容做二次校验；这就是「外部编辑与内部写入冲突检测」的教科书实现。https://git-scm.com/docs/racy-git/2.5.6.html
- 【可借鉴】**racy-git 揭示了 stat 检测的竞态**：若外部修改发生且 mtime 与索引写入时间戳相同（文件系统时间粒度粗），stat 比对会漏报——Git 的解法是 racy 检测后强制内容重读（clean 校验）。教训：**stat 只能做快速通道，内容哈希才是权威判定**；本项目工作副本校验应保持「磁盘文件 content_hash ↔ DB 记录」双校验（T1 已确认 read_markdown 的 content_hash 与 wiki_page_bindings 即此机制），并注意 mtime 粒度竞态（Windows NTFS 时间戳精度高但缓存仍可能一致）。
- 【可借鉴】Git 的**锁文件协议（lockfile API）**：对索引等关键元数据先写 index.lock（新建独占），写完 rename 成正式名；任何读者看到 .lock 就认为写者未完成——「锁即事务标记」。https://git-scm.com/docs/api-lockfile/2.0.5.html
- 【可借鉴】Dolt（「Git for data」SQL 数据库）把 git 模型搬进数据库：**working set（未提交改动）/ staged set / branch（提交历史）三层分离**，表和行都可分支合并——证明「版本库 + 工作副本」双层模型在数据侧完全可行；其官方博客明确区分 **MVCC ≠ 版本控制**（多版本并发控制只保证读快照，不提供分支/提交/合并语义，阶段 B 若要版本化必须显式做提交层）。https://docs.dolthub.com:8443/ ；https://www.dolthub.com/blog/2025-07-01-things-that-arent-version-contolled-databases/#mvcc-is-not-version-control
- 【仅参考】Subversion wc-ng 工作副本重构笔记：工作副本元数据入 SQLite（wc.db），文件系统只保留文件本身 + pristine 副本；文件与元数据的一致性靠 wc.db 事务维持。https://svn.apache.org/repos/asf/subversion/branches/issue-3550-dev/notes/wc-ng/locking

### 1.3 DB 快照一致性
- 【可借鉴】SQLite 备份必须用一致性手段：**online backup API / VACUUM INTO / .backup 命令**，禁止直接拷贝 DB 文件（WAL 模式下裸拷贝会缺未 checkpoint 的日志）；备份后跑 PRAGMA integrity_check 验证。工程博客整理：https://raw.githubusercontent.com/OneUptime/blog/refs/heads/master/posts/2026-03-02-how-to-back-up-sqlite-databases-on-ubuntu/README.md ；备份/损坏恢复要点（含 integrity_check 时机）：https://github.com/tachyon-beep/skillpacks/blob/main/plugins/axiom-embedded-database/skills/using-embedded-database/backup-restore-and-corruption.md
- 【仅参考】SQLite 官方论坛关于 WAL 事务语义与 wal-index 一致性的讨论：https://www2.sqlite.org/forum/forumpost/b25a486ed6

---

## 二、草稿审批流：draft→review→approve 的权限模型与审计

### 2.1 企业 KM 平台：显式状态机 + 审批记录
- 【可借鉴】**Microsoft Dynamics 365 知识文章生命周期 = Draft → Approve → Publish →（Expire）**，且「已发布文章只有拥有 Publish 权限的用户才能修改」——状态转移与权限绑定（发布后内容冻结，改动走新草稿）。https://learn.microsoft.com/zh-cn/training/modules/creating-and-designing-knowledge-management-solutions/3-knowledge-article-lifecycle ；配套审批实操（指派审阅人、approve/reject、审阅备注）：https://learn.microsoft.com/zh-tw/dynamics365/customer-service/use/review-ka?view=op-9-0 ；第三方解读（Author→Approve→Publish→Reuse 全流程）：https://d365update.com/amp/knowledge-articles-in-dynamics-365-author-approve-publish-reuse/
- 【可借鉴】**审批即数据**：审批记录必须独立落库存**谁（approver identity）、何时（timestamp）、决定（approved/rejected）、意见（comments）**，且不可由文档 PDF 派生——Microsoft Q&A 有真实反例：审批「另存为 PDF」不携带审批人/时间/意见，导致合规审计缺证。https://learn.microsoft.com/en-us/answers/questions/5695154/approvals-save-as-pdf-function-not-capturing-date
- 【可借鉴】Power Automate 审批流的审计教训：默认审批历史不完整、approval 记录可能随流删除丢失——合规场景需**自建审计表**记录决策轨迹（traceability gap）；「auditor-ready」补法 = 每次审批动作显式追加一行不可变记录。https://www.m365.fm/your-power-automate-approval-flow-isnt-audit-proof/ ；https://www.m365.fm/blog/auditor-ready-power-automate-bridging-the-traceability-gap/
- 【可借鉴】SharePoint 文档审批用于 ISO 27001 合规：审批工作流 + 版本历史 + 权限最小化（草稿仅作者/审批人可见，发布后只读）；合规审计要能回答「谁批准了什么、何时」。https://canadiancyber.ca/policy-approval-workflow-sharepoint-iso-27001/
- 【可借鉴】ONES 企业 Wiki 审批合规框架：角色分离（作者≠审批人）、审批流绑定页面状态、审计日志贯穿；要点是**审批流不能是「可选的附加步骤」，而应是发布动作的前置门（gate）**。https://ones.com/blog/enterprise-wiki-approval-a-compliance-framework-guide/
- 【可借鉴】中文实践：致远（seeyon）知识库管理制度把「知识发布审批流程 + 权限治理」列为落地规范（文档分级审批、发布即归档）。https://wap.seeyon.com/article/A1x4Zi7W.html
- 【仅参考】Redmine Wiki Approval 插件：wiki 页作者→指定审阅人 approve/reject，审阅状态可见。https://www.redmine.org/plugins/redmine_wiki_approval
- 【仅参考】电子签核（e-signature）的「核准矩阵 + 稽核軌跡」设计（审批矩阵定义谁能批，稽核轨迹记录全程）：https://www.kdan.com/zh-tw/blog/the-complete-guide-to-esignature-workflows-for-enterprises

### 2.2 Docs-as-code：PR 审阅 = 审批 + Git 历史 = 审计
- 【可借鉴】**Mintlify 文档治理 = Git 分支保护 + required reviews**：分支即草稿环境，合并即发布；Git 提交历史天然是「谁批准、何时、改了什么」的不可变审计链，且与代码评审复用同一套权限模型。https://www.mintlify.com/library/documentation-governance-with-git-and-branch-protection
- 【可借鉴】docs-as-code 综述（分支工作流 + PR review + 发布流水线）：https://sourcegraph.com/blog/documentation-as-code ；Squarespace 工程博客落地经验（单一仓库、PR 评审、发布自动化）：https://engineering.squarespace.com/blog/2025/making-documentation-simpler-and-practical-our-docs-as-code-journey

---

## 三、写盘时序失败恢复（promote 前写盘失败的补偿模式）

### 3.1 崩溃一致性的文件系统协议（fsync 顺序）
- 【可借鉴】**SOSP'15 fscq 论文（All File Systems Are Not Created Equal）**：POSIX 崩溃一致性没有通用保证，应用必须显式编码依赖顺序——「写数据→fsync(文件)→rename→fsync(父目录)」才是可持久化的原子发布；只 rename 不 fsync 父目录，断电后 rename 可能丢失。https://dspace.mit.edu/bitstream/handle/1721.1/137412/fscq_sosp15.pdf
- 【可借鉴】真实事故佐证：ArcadeDB issue #7465——原子写实现缺父目录 fsync，发布后 rename 在断电时丢失。https://github.com/ArcadeData/arcadedb/issues/7465
- 【可借鉴】Git 锁文件 API 文档明确同款协议：commit 阶段 = 写临时文件→fsync→rename 为正式名（原子替换）。https://git-scm.com/docs/api-lockfile/2.0.5.html

### 3.2 Windows 特殊性（本项目运行在 Windows 上，必须处理）
- 【可借鉴】**Windows 上「原子替换」没有 POSIX rename 语义**：要用 MoveFileEx(REPLACE_EXISTING) 或 ReplaceFile；且 NTFS 上目标文件被其他进程打开时替换会失败（共享冲突）——真实项目两种处理：重试 os.replace（LightRAG PR：https://github.com/HKUDS/LightRAG/pull/3880 ）或降级为普通写（Zed PR：https://github.com/zed-industries/zed/pull/30222 ，注意降级会失去原子性，需接受「写坏可重生成」前提）。PostgreSQL 社区讨论 Windows 原子 rename 的不可靠性：https://www.postgresql.org/message-id/20200107161629.6555aiuhitlnoes5%40development ；StackOverflow 权威问答（ReplaceFile 语义与限制）：https://stackoverflow.com/questions/16471465/replace-file-with-another-in-an-atomic-operation-windows
- 【可借鉴】**原子写的三个硬性前提**：(1) 临时文件必须与目标同目录（同文件系统，rename 才原子）；(2) 用独占创建（O_CREAT|O_EXCL / 随机名）防 symlink 劫持；(3) 写完整后 rename 而非 truncate 原文件。Go 生态原子写库说明同款约定：https://pkg.go.dev/go.thesmos.sh/techne@v1.0.2/pkg/fs ；https://pkg.go.dev/latere.ai/x/pkg/atomicfile ；Rust 侧 grex-core atomic 模块（含 Windows 分支处理）：https://docs.rs/grex-core/1.0.0/x86_64-pc-windows-msvc/grex_core/fs/atomic/
- 【仅参考】「文件拷贝不可能是原子的」（只有同文件系统 rename 原子）：https://stackoverflow.com/posts/5086916b-1d56-42bd-83db-f9e11f538ac3/revisions

### 3.3 失败后的恢复语义
- 【可借鉴】**outbox 重放 + 幂等中继**（见 §1.1）：写盘失败 = outbox 中继失败 → 状态留在 staged、可重试；校验失败（磁盘内容与 DB 不符）→ 重新生成投递物再试，DB 事务不受影响。
- 【可借鉴】**原子 read-modify-write 模式**（JSON 文件等场景）：读→改→原子写整文件；并发写用锁文件（git lockfile 模式）或版本号 CAS（乐观锁 + 冲突检测见 §4.3）。https://github.com/bastani-inc/atomic/blob/91e365fe/research/docs/2026-02-16-atomic-json-patterns.md

---

## 四、已知坑（双写不一致、symlink/路径穿越、原子写）

### 4.1 双写不一致
- 【可借鉴】**双写不一致的根源 = 两个独立提交点没有共同事务边界**；对策按复杂度递增：(a) 消除第二副本（单一事实源，另一侧可重建——见 4.4）；(b) outbox 把外部投递变成可重放步骤（§1.1）；(c) 补偿事务（§1.1 仅参考）。AWS outbox 文档明确列出「先写文件再写 DB 失败→两侧不一致」正是 outbox 要消除的形态：https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
- 【仅参考】SQLite-Sync 的 block-level LWW（last-write-wins）同步语义：块级 LWW 会静默丢更新（后写覆盖先写），不适合「外部编辑 + 内部写入」并存场景，只适合单写者。https://docs-stage.sqlitecloud.io/docs/sqlite-sync-block-lww

### 4.2 symlink / 路径穿越
- 【可借鉴】**临时文件/写入路径被 symlink 劫持是真实漏洞类别**：攻击者把可写目录里的目标名预先替换为指向敏感文件的符号链接，程序跟随链接写穿。Fluid Attacks 漏洞库实例（FLAT-48DGV，symlink 写穿）：https://db.fluidattacks.com/vul/FLAT-48DGV/ ；TOCTOU 竞态类别（检查与使用之间被替换，CWE-367）：https://vulnerability.circl.lu/cwe/CWE-367
- 【可借鉴】对策：写入前 resolve 真实路径并校验在 vault 根内（禁跟随 symlink / 禁 symlink 目标逃逸）；临时文件用同目录独占创建；打开后用 fstat 校验 inode/路径一致。本项目已有先例：tests/test_wiki_source_scope.py::test_synthesis_rejects_link_outside_vault_before_reading 明确拒绝 vault 外 symlink 目录——阶段 B 写盘路径应把此检查做成写路径的强制门。

### 4.3 外部编辑冲突检测（乐观并发）
- 【可借鉴】**MediaWiki 编辑冲突协议**：保存时比对编辑基线 token，发现他人已改 → 不覆盖，进入冲突解决页（合并/放弃/覆盖三选一），保证「外部修改不被静默吞掉」。https://en.wikipedia.org/wiki/Help:Edit_conflict （并发编辑讨论：https://lists.wikimedia.org/hyperkitty/list/mediawiki-l@lists.wikimedia.org/thread/3JVUE22G7XWUMIWIDCGNO2SOBVKQEVVT/ ）
- 【可借鉴】**HTTP 语义的 ETag/If-Match 乐观锁**是通用做法：写请求必须带上次读取的版本标记，不匹配即 409 冲突（配合 content_hash 就是天然 ETag）。Microsoft Learn 并发控制文档（ETag 用法）：https://learn.microsoft.com/zh-cn/partner-center/marketplace-offers/cloud-partner-portal-api-concurrency-control ；CEDAR 元数据中心 ETag 并发指南：https://metadatacenter.readthedocs.io/en/latest/developer-guide/cedar-rest-apis/etag-concurrency/
- 【可借鉴】**文件监听器不可单独依赖**：Meteor 的文件监听效率文档——watcher（inotify/ReadDirectoryChangesW）会丢事件、批量事件风暴、平台差异；工程上要 watcher + stat 轮询 + 内容哈希三重结合。https://github.com/meteor/meteor/wiki/File-Change-Watcher-Efficiency ；中文共享目录同步踩坑实录（监听丢事件/缓存延迟）：https://developer.aliyun.com/article/1736918

### 4.4 单一事实源
- 【可借鉴】**DB 与 Markdown 双存储必须声明唯一事实源，另一侧是「可重建索引」**：WordPress 的 markdown-database-integration（SQLite 作机械层、markdown 作知识层，显式规定同步方向与重建语义）：https://github.com/Automattic/markdown-database-integration ；memex ADR-0003（markdown vault 为事实源、索引可重建）：https://github.com/Zenetusken/memex/blob/main/docs/adr/0003-markdown-vault-as-source-of-truth.md
- 【仅参考】sql-md-sync（SQL↔Markdown 双向同步库）暴露双向同步的方向/冲突处理复杂度，说明「双向自动同步」是高危设计：https://www.npmjs.com/package/sql-md-sync

---

## 五、对 AgentPet 阶段 B 的应用映射（写盘→re-capture→promote + review 门）

1. **阶段 B 流水线 = outbox 中继**（§1.1/§3.3）：DB 事务产出 staged generation（事实），磁盘写盘是投递物；promote 门 = outbox 幂等重试点。现有 wiki_generations.status='staged' 与 publish_ingest 重试已是雏形，补：写盘校验失败 → 重新生成投递物（不落半成品）、重试有界。
2. **re-capture 校验 = git stat-cache + 内容哈希双通道**（§1.2/§4.3）：磁盘文件 (mtime, size, hash) vs DB 记录；stat 快通道、hash 权威通道；mtime 竞态下强制 hash 复核。
3. **外部编辑冲突**：写盘前比对 binding content_hash（既有 bind_authoritative_wiki_page 机制）；不一致 → MediaWiki 式冲突处理（不静默覆盖），或 ETag/If-Match 语义拒绝。
4. **review 门审计**（§2.1）：审批记录独立表存 (approver, decided_at, decision, comment, review_id)，不可从发布产物派生；状态机 Draft→Review→Approved→Published 复用 T2 结论，发布后只读（改走新草稿）。
5. **原子写规范**（§3.1/§3.2/§4.2）：同目录临时文件 + 独占创建 + fsync(文件) + rename + fsync(父目录)；Windows 用 MoveFileEx/ReplaceFile，遇句柄占用重试，降级写仅在「可重生成」前提下允许；写路径强制真实路径校验防 symlink 逃逸。
6. **单一事实源**（§4.4）：DB 为权威、磁盘工作副本为可重建视图；文档化同步方向，不做双向自动同步。
7. **审计链**：发布/审批历史走 DB 账本（schema_migrations 式不可变追加），Git 式 commit 历史仅参考，不引入 Git 依赖。

---

## 六、要点速览（15 条）

1. 双写一致性标准解是 transactional outbox：DB 事务内记意图，外部投递可重试幂等（AWS 官方模式）。【可借鉴】
2. 阶段 B 的 staged→publish 已是 outbox 雏形，按「中继幂等 + 重试有界 + 投递物可再生成」加固。【可借鉴】
3. Git 用索引 stat cache 检测外部修改：stat 快通道 + 内容二次校验；racy-git 证明 mtime 竞态必须靠内容复核兜底。【可借鉴】
4. Git lockfile API：.lock 文件即事务标记，写完 rename 提交；读者见锁即知未完成。【可借鉴】
5. Dolt 证明「版本库 + working set」双层模型在数据侧可行；MVCC ≠ 版本控制，版本化需显式提交层。【可借鉴】
6. SQLite 备份必须 online backup API/VACUUM INTO/.backup，裸拷贝在 WAL 下不一致；备份后 integrity_check。【可借鉴】
7. Dynamics 365：Draft→Approve→Publish→Expire 状态机，发布后仅 Publish 权限可改（内容冻结，改动走新草稿）。【可借鉴】
8. 审批必须落库 (approver, timestamp, decision, comments)，不可由 PDF/发布产物派生；Power Automate 默认审批历史不完整是真实教训。【可借鉴】
9. Docs-as-code：分支=草稿、required reviews=审批、Git 历史=审计链（Mintlify/Sourcegraph/Squarespace）。【可借鉴】
10. 崩溃一致协议：写数据→fsync 文件→rename→fsync 父目录（SOSP'15 fscq；ArcadeDB #7465 事故佐证）。【可借鉴】
11. Windows 无 POSIX 原子 rename：MoveFileEx/ReplaceFile；句柄占用需重试或（可再生成前提下）降级写（LightRAG/Zed PR 实例）。【可借鉴】
12. 原子写三前提：同目录临时文件、独占创建防 symlink、写满再 rename；文件拷贝永不原子。【可借鉴】
13. symlink 写穿/TOCTOU 是真实漏洞类（FLAT-48DGV、CWE-367）；写路径必须 resolve 后校验在 vault 内，本项目已有拒绝 symlink 的测试先例。【可借鉴】
14. MediaWiki 编辑冲突协议：基线 token 比对 + 冲突页三选一，外部修改不被静默吞掉；ETag/If-Match 是通用乐观锁形态。【可借鉴】
15. 双存储必须声明单一事实源，另一侧可重建（WordPress markdown drop-in、memex ADR）；双向自动同步（sql-md-sync）是高危设计。【可借鉴】
