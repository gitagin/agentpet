# T12 补充调研：版本化权限与内容失效模型

- 调研人：recon-a（researcher）
- 调研日期：2026-09-20（文中所有 URL 访问日期同此；web_search 中英文约 20 次检索）
- 主题：「旧内容版本稳定 ≠ 旧权限永久有效」的工程实现——版本化访问控制、读租约/墓碑与发送时引用复核、快照+实时策略双通道、TTL 与 freshness watermark
- 标记说明：【可借鉴】= 建议引入本项目的模式/结论；【仅参考】= 只作背景理解，不引入依赖

---

## 一、版本化访问控制：历史版本可见性随权限/撤销/遗忘变化

### 1.1 MediaWiki / Wikipedia：历史修订的分字段隐藏与监督层
- 【可借鉴】MediaWiki 的 **RevisionDelete（修订版本删除）**：对历史修订可按「正文文本 / 编辑者用户名 / 编辑摘要」三个维度**分别**隐藏，隐藏后普通用户与一般管理员均不可见；Oversight（监督）层还可把修订对管理员也隐藏。要点：历史版本的可见性不是整页二值开关，而是**分字段、分层级的撤销通道**，删除单个修订不需要删除整页或重写历史。
  - https://www.mediawiki.org/wiki/Manual:RevisionDelete
  - 中文政策页「维基百科:修订版本删除（RVDL）」：https://zh.wikipedia.org/wiki/Wikipedia:RVDL
- 对项目启示：wiki_sources 若存历史版本，撤销粒度应为「source 行 + 分字段可见性」，而非整库清理。

### 1.2 GitHub：私有仓库泄露后的历史清理与「删除≠清零」
- 【可借鉴】GitHub 官方指南「Removing sensitive data from a repository」：用 `git filter-repo` / BFG 重写历史删除敏感内容，但官方明确警告——**重写历史后旧 commit 仍存在于所有 clone、fork、PR、依赖缓存与 GitHub 自身缓存（CDN）中**；必须假定内容已泄露并轮换密钥/凭证；重写是破坏性操作，需全协作者协调 rebase。
  - https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
- 【可借鉴】GitHub「修正存储库中泄露的机密」指南：即使重写历史删除 secret，也**必须在密钥管理侧轮换密钥**——内容删除只是降险，不是风险清零；「撤销」必须覆盖所有已传播副本。
  - https://docs.github.com/zh/code-security/tutorials/remediate-leaked-secrets/remediating-a-leaked-secret
- 对项目启示：曾被写入 wiki/被检索过的旧内容可能已被下游（嵌入缓存、编译产物、上下文）吸收，撤销主库行不等于撤销全部副本。

### 1.3 云文档历史版本权限：跟随当前权限 vs 版本级权限
- 【可借鉴】Google Docs 版本历史：查看「文件中的更改（version history）」要求**当前文档的 Editor 权限**；撤销共享后，旧版本也随之不可见——实现为「旧版本可见性跟随当前权限」，无需逐版本回收。
  - https://support.google.com/docs/answer/190843
- 【仅参考】Atlassian Jira CONFSERVER-1316「not permitted to view previous versions of page」：Confluence 的历史版本查看受独立权限位控制，曾长期与当前页权限不一致（有当前页查看权也看不了旧版本）——说明企业 wiki 中「当前权限模型」与「历史版本权限模型」一旦双轨并存就产生缝隙。
  - https://jira.atlassian.com/browse/CONFSERVER-1316
- 对项目启示：历史版本可见性模型必须二选一（跟随当前 source 权限 / 版本级独立权限），不要两套并存。

### 1.4 GDPR 遗忘权与审计留存：crypto-shredding 与折中模式
- 【可借鉴】Crypto-Shredding 论文（2025，金融系统场景）：用「**加密 + 丢弃密钥**」在**不可变审计日志**上实现可证明删除——正文密文可继续留存以满足审计链完整性，密钥销毁即达到有效删除（erasure）。这是「正文不可读、审计可验证」两全的标准工程答案。
  - https://zenodo.org/records/17946987/files/VCP_Crypto_Shredding_Paper_v7.pdf （记录页：https://zenodo.org/records/17946987 ）
- 【可借鉴】AppMaster 综述「Privacy deletion vs audit needs: practical compromise patterns」（2026-01）：实用折中模式 = 软删除+受限访问、假名化（pseudonymization）替代硬删、**审计日志只保留元数据不保留正文**、按保留期分层（hot/warm/cold）。
  - https://appmaster.io/blog/privacy-deletion-audit-compromise-patterns （中文版：https://appmaster.io/zh/blog/yinsi-shanchu-yu-shenji-xuqiu-de-zhezhong-moshi ）
- 【仅参考】Redgate「为什么数据库仍在 GDPR 审计中失败」（2026）：主要失败模式是**删除声明与实现不一致**——声称已 erasure，但备份、副本、日志仍含数据；删除必须覆盖备份链与所有副本。
  - https://www.red-gate.com/simple-talk/data-security-privacy-compliance/its-2026-why-are-databases-still-failing-gdpr-compliance-audits/

---

## 二、读租约（read lease）与 tombstone（墓碑），以及发送时引用复核

### 2.1 读租约：缓存内容可用性有明确上限时间
- 【可借鉴】Gifford 1989 经典论文「Leases: An Efficient Fault-Tolerant Mechanism for Distributed File Cache Consistency」：**lease = 带 TTL 的读缓存授权**；租约期满后客户端必须重新向服务端续租，服务端撤销的传播延迟被租约上限封顶。核心思想：任何「已缓存的旧内容」其可用性都应有明确时间上限。
  - https://courses.cs.vt.edu/cs5204/fall05-gback/presentations/Leases.pdf
- 对项目启示：检索缓存/已入上下文的内容携带 lease 时间戳，超过 TTL 的引用在发送前强制 revalidation（与 2.4 配合）。

### 2.2 Tombstone：删除 = 标记 + 读路径过滤 + 延迟物理回收
- 【可借鉴】Cassandra（CMU 案例课）的删除模型：删除不是物理移除，而是写入 **tombstone（墓碑）标记**，读路径合并时把墓碑之后的旧值视为不存在；墓碑保留 `gc_grace_seconds` 后才物理清理。三段式：标记 → 读路径过滤 → 延迟回收。
  - https://learn.microsoft.com/en-us/training/modules/cmu-case-study-nosql-databases/3-apache-cassandra
- 对项目启示：被撤销的 source 行写 `revoked_at` 墓碑而非物理删除，检索/编译读路径按墓碑过滤，物理清理延后以保审计与恢复能力。

### 2.3 实证：Agent 记忆系统的「撤销标签」在读取路径上几乎不被执行
- 【可借鉴】arXiv 2609.08258「Revoked but Still Authoritative: An Empirical Study of Revocation Enforcement in Agent-Memory Systems」（2026）：实证研究发现 agent 记忆系统的撤销**只写存储层标记，读取路径基本不强制执行**——检索/上下文注入时仍可能引用被撤销内容；配套解读「revoked memory is not deleted memory — the label is enforced by nothing on your read path」；另一解读「revoked policies survive where agent decisions begin」：撤销只影响后续检索，**已注入上下文/已生成内容不会自动撤回**。
  - 论文：https://arxiv.org/pdf/2609.08258 （导出：https://export.arxiv.org/pdf/2609.08258 ）
  - 解读：https://www.hotmolts.com/post/-revoked-memory-is-not-deleted-memory-the-label-is-f48994d3-3ea6-43aa-ad87-a56d95b0ddae ；https://www.hotmolts.com/post/-revoked-policies-survive-where-agent-decisions-be-e0613f03-e5fb-4648-b4c0-f21362cdd0f4
- 对项目启示：这是本项目缝隙的直接实证——仅撤销数据库标记不够，必须在「上下文组装 → 发送」之间加权威性复核层。

### 2.4 发送时引用复核（citation revalidation at send time）
- 【可借鉴】Robust-GAP（2025）：分层 RAG 维护 **citation provenance（出处链）**，输出前对引用做 grounded 校验，失效/幻觉引用在生成管线内被拦截。
  - https://zenodo.org/records/21436390/files/robust_gap_preprint.pdf （记录页：https://zenodo.org/records/21436390 ）
- 【可借鉴】WueRAG @ TREC RAGTIME 2025：检索-融合-引用生成全链路建模「生成句子 → 来源段」映射，使发送时校验引用 = 校验该映射仍然有效（来源仍在、权限仍在、内容未变）。
  - https://trec.nist.gov/pubs/trec34/papers/WueRAG.ragtime.pdf
- 【仅参考】LRT-ReviChain（ITIIS 2026）：面向生成式 AI 服务的轻量编排，把**时效性复核**编排进服务调用链（recency in generative AI services）。
  - https://itiis.org/journals/tiis/digital-library/manuscript/file/106295/TIIS%20Vol%2020,%20No%204-24.pdf

### 2.5 存储与使用分离的遗忘模型
- 【可借鉴】「What Should an Agent Forget? Separating What Is Stored from What Is Used」（arXiv 2609.10263，2026）：主张存储层（长期保留）与使用层（上下文注入）分离，**遗忘发生在使用一侧**——被撤回想继续存储但不再被使用，成本更低、可审计。
  - https://export.arxiv.org/pdf/2609.10263
- 【仅参考】「Selective Forgetting: A Graph-Based Memory Framework for Long-Term LLM Agents」（arXiv 2608.28978）：图结构记忆按相关性/时效做选择性遗忘，边带 TTL 化生命周期。
  - https://browse-export.arxiv.org/pdf/2608.28978

---

## 三、快照读取 + 实时权限联合检查（双通道）

### 3.1 OWASP AISVS / RAG 安全基线：撤销新鲜度与文档级 ACL
- 【可借鉴】OWASP AISVS C08-01「Access Controls — Memory/RAG」（AI 安全验证标准）：把 **revocation freshness（撤销新鲜度）** 列为验证项——要求「从记忆/索引撤销的访问权限在**读取路径立即生效**，而非仅在下一次索引重建时生效」；即检索时联合实时策略检查。
  - https://github.com/OWASP/AISVS/blob/main/1.0/research/chapters/C08-Memory-and-Embeddings/C08-01-Access-Controls-Memory-RAG.md
- 【可借鉴】OWASP RAG Security Cheat Sheet：RAG 安全基线之一 = **retrieval 阶段实施文档级 ACL 过滤**，不能只依赖索引构建时的权限快照。
  - https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html

### 3.2 TOCTOU / 不完整中介（CWE-638）
- 【可借鉴】CWE-638「Not Using Complete Mediation」：授权只在请求路径的某一环节（登录时、缓存填充时）检查，后续访问不再复核——正是「快照权限 vs 实时权限」缝隙的经典定义；缓解 = 每个读取入口都做完整中介（complete mediation）。
  - https://www.plexicus.ai/cwe/cwe-638-not-using-complete-mediation/

### 3.3 双通道架构与「元数据可读、正文不可读」边界
- 【可借鉴】腾讯云「企业 RAG 知识库验收架构：引用、权限与失败恢复」：企业 RAG 验收三要点 = 引用可溯（citation）+ 权限一致（检索结果按**当前用户 ACL** 实时过滤）+ 失败恢复——先取快照候选，再按实时权限过滤后注入上下文。
  - https://cloud.tencent.com.cn/developer/article/2739073
- 【可借鉴】阿里云「大模型企业本地化部署与数据安全实践：知识库过期内容如何治理」：过期/越权内容治理 = **数据层标记 + 检索层过滤 + 输出层提示**三层，而非只改数据。
  - https://developer.aliyun.com/article/1750481
- 边界结论（元数据 vs 正文）：
  - 【可借鉴】GitHub 泄漏清理经验（1.2）：commit 元数据（作者/时间/message）与正文暴露面不同；正文可从 CDN/缓存获取——**清理与权限控制必须区分元数据与正文两个暴露面**。
  - 【可借鉴】GDPR 审计折中（1.4 AppMaster / crypto-shredding）：审计日志保留元数据（谁/何时/什么操作）但正文假名化或不可读——这是「**过期权限下元数据仍可读、正文不可读**」的合规标准形态。
  - 对项目启示：AgentPet 的 provenance 元数据（source_id、时间线、来源关系）与正文（raw_content）分权：撤销后元数据行保留以维护图谱完整性，正文从所有读路径过滤。

---

## 四、内容过期 TTL 与 freshness watermark（新来源相关性水位线）

### 4.1 RAG 新鲜度研究
- 【可借鉴】「Solving Freshness in RAG: A Simple Recency Prior and the Limits of Heuristic Trend Detection」（arXiv 2509.19376，2025）：给检索结果加 **recency prior（半衰期先验）**——位置/价格/政策类事实随时间衰减；并指出启发式趋势检测有极限，新鲜度应建模为**时间衰减**而非二值新旧。
  - https://export.arxiv.org/pdf/2509.19376
- 【可借鉴】「Temporal Validity in Retrieval Memory: Eliminating Stale-Fact Errors for AI Agents over Evolving Knowledge」（arXiv 2606.26511，2026）：为记忆中的事实附加**时间有效性窗口（temporal validity）**，过期窗口的事实不参与生成，消除 stale-fact 错误——与项目里 source_version 的「版本有效性」直接对应。
  - https://browse-export.arxiv.org/pdf/2606.26511
- 【可借鉴】JISEM 2026「Measuring Retrieval Freshness and Accuracy Degradation in Continuous ETL-Driven RAG Systems」：在连续 ETL 下度量检索新鲜度与精度退化，把 freshness 作为**可度量 SLO** 而不是口头要求。
  - https://jisem-journal.com/index.php/journal/article/download/14454/6951

### 4.2 知识库落地案例（中文）
- 【可借鉴】深信服「RAG 长期运行不稳定？别光优化向量检索，知识数据治理是核心」：知识治理 = 源数据去重 / 版本管理 / **过期标记**，检索层配合 freshness 过滤，防止旧文档长期占据召回。
  - https://www.sangfor.com.cn/knowledgecenter/d007642adb8f428f86106cd1b178d396
- 【可借鉴】阿里云「企业知识库资料越多，Agent 为什么反而越容易答错？」：资料增长引入互相矛盾/过期内容，需要冲突检测与**时效排序（新覆盖旧）**——新来源水位线 = 同一事实以更新来源为准。
  - https://developer.aliyun.com/article/1760025
- 【仅参考】WFGY knowledge_expiry.md：企业知识治理的过期策略清单（expiry policy 设计：TTL、复核周期、过期动作）。
  - https://github.com/onestardao/WFGY/blob/3f55558c1bbfe398922fc97e775d59902bd5d347/ProblemMap/GlobalFixMap/Enterprise_Knowledge_Gov/knowledge_expiry.md

### 4.3 基础设施级 TTL 与 freshness 一等公民
- 【可借鉴】Azure Cosmos DB **文档级 TTL**（秒级粒度、到期自动删除）被微软多 agent 记忆架构模式列为会话级记忆过期的标准模式（工作记忆 TTL、长期记忆保留）。
  - https://learn.microsoft.com/zh-cn/training/modules/aaai-design-multi-agent-memory-azure-cosmos-db/2-examine-memory-architecture-patterns
- 【仅参考】freshcontext-mcp RESEARCH.md：把 freshness 作为 MCP 上下文管理的一等概念（freshness-aware context 注入）。
  - https://github.com/PrinceGabriel-lgtm/freshcontext-mcp/blob/181c2b570e06d3aa9a9eebfe9f7d8f363c6bad1b/RESEARCH.md

---

## 五、综合结论（对 AgentPet 的落点）

1. **核心范式**：「旧内容稳定 ≠ 旧权限永久有效」的标准工程解法不是删除旧版本，而是「**读路径实时策略检查 + 发送时引用复核**」双保险（OWASP AISVS C08-01、CWE-638、Revoked-but-Still-Authoritative 实证）。
2. **双通道架构**：快照/索引保存内容（不可变），权限与有效性以实时查询为准（live policy）；每次读取（检索 → 组装 → 发送）都做 complete mediation，权限检查不放缓到索引重建周期。
3. **元数据/正文分级**：撤销后 provenance 元数据行保留（审计、图谱完整性），正文从所有读路径过滤；需要硬删除时用 crypto-shredding（加密+弃钥）保住审计链。
4. **tombstone + lease**：删除行写 `revoked_at` 墓碑、读路径过滤、物理回收延后；已缓存/已入上下文的引用带 lease TTL，超期强制 revalidate。
5. **freshness watermark**：来源内容带时间有效性窗口与版本号，检索按 TTL/半衰期加权，同一事实以新来源覆盖旧来源（新内容水位线）。
6. **发送时引用复核**：引用 = 「生成句子 → 来源段」映射，发送前校验映射中的来源仍在、权限仍有效、内容未变（Robust-GAP / WueRAG 模式）。
