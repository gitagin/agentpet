# T24/C2 外部经验调研：新鲜度 / 上下文替换 / 深读模式（阶段 C 预研）

- 调研人：webre-a（researcher，AgentTeams）
- 调研日期：2026-09-19（所有条目访问日期同此）
- 方式：web_search 中英文关键词（约 15 次检索）；来源以 arXiv/ACL/ICLR 论文、官方文档、工程博客、GitHub issue/PR 为准
- 标记说明：【可借鉴】= 建议引入阶段 C 四个功能点的模式/结论；【仅参考】= 只作背景理解，不引入依赖
- 关联输入：T1 盘点（.tmp/recon-source-identity-2026-09-19.md）、T12 调研（docs/t12-versioned-authority-research.md）、B 阶段产物（docs/t15/t16/t18）、基线 commit f306676

---

## 一、新鲜度状态机与相关性水位线（new-source relevance watermark）

### 1.1 Recency-aware retrieval：时间衰减 / recency prior
- 【可借鉴】arXiv 2509.19376 Solving Freshness in RAG: A Simple Recency Prior and the Limits of Heuristic Trend Detection：在 retrieval 中引入半衰期先验（recency prior）——事实按已知更新时间施加指数衰减权重（半衰期可扫参），专门对抗过期事实（position/price/policy 类知识）；结论是简单 recency prior 即可显著缓解 stale fact 问题，而启发式趋势检测有明确局限，不能替代时间先验。https://export.arxiv.org/pdf/2509.19376 （arxiv.org/pdf/2509.19376v2 同文）
- 【可借鉴】同一思路的工程化：Volatility-Driven Decay（波动驱动衰减，自适应记忆保留）——按知识实体的更新波动性自适应调衰减率，应对未知漂移（unknown drift）。https://github.com/abe238/volatility-driven-decay/blob/main/arxiv_submission/main.pdf
- 【仅参考】Temporal Shard RAG / Chronofy（时间分片、时序逻辑衰减架构）——时间建模的学院派方案，架构较重，仅参考其按时间分片存储便于按时间过滤的思路。https://zenodo.org/records/18010079/files/temporal-shard-rag.pdf ；https://browse-export.arxiv.org/pdf/2607.20560
- 【仅参考】Recency Distortion and Stale Knowledge（ACL 2026 Findings）：近期性扭曲现象——模型倾向过度采信近期信息。https://aclanthology.org/2026.findings-acl.92.pdf

### 1.2 Corpus change detection：hash / 观察点变化检测
- 【可借鉴】本项目已有观察水位线机制（与外部实践同构）：app/services/wiki/source_watermark.py 对 wiki_sources(id,source_hash,source_type,updated_at)、notes、wiki_page_bindings(status,revoked_at) 求 sha256 观察摘要，模块 docstring 明示 Database observation watermark, never a semantic freshness certificate——观察水印只证明查询期间数据未变，不证明内容语义新鲜；查询期变化即拒绝（wiki_sources_changed_during_query）。这是阶段 C new-source relevance watermark 的正确底座：水位线=查询开始的观察快照，语义新鲜度=另一维度，不可混为一谈。
- 【可借鉴】EviDex（ACM 3801489.3806899）：provenance-weighted evidence-path indexing for fresh and auditable retrieval under continuous updates——持续更新场景下按证据路径（provenance）加权索引，检索结果携带可审计的更新链。https://dlnext.acm.org/doi/pdf/10.1145/3801489.3806899
- 【可借鉴】Oracle 工程实践 Real-Time RAG: Live SQL, Incremental Indexing, and Freshness Tests：增量索引 + 显式 freshness tests（对索引新鲜度做自动化测试断言，过期即报警）。https://blogs.oracle.com/developers/real-time-rag-live-sql-incremental-indexing-and-freshness-tests
- 【可借鉴】Azure Cosmos DB change feed 触发 embedding 刷新：用数据库变更流驱动向量索引增量更新而非全量重建——变化检测 + 增量更新的标准云原生做法。https://learn.microsoft.com/fr-fr/training/modules/implement-vector-search-azure-cosmos-db/5-change-feed-trigger-embedding-refresh
- 【仅参考】ETL 持续更新下检索新鲜度与精度退化的度量研究（Measuring Retrieval Freshness and Accuracy Degradation in Continuous ETL-Driven RAG Systems）。https://jisem-journal.com/index.php/journal/article/download/14454/6951
- 【可借鉴】数据仓库侧的水位线回路：gbrain 实现 extract freshness watermark + doctor lag check（stale 标记、滞后检查）——水位线滞后即上报告警的运维模式与本项目观察快照可互补（周期性对账而非仅查询期检查）。https://github.com/garrytan/gbrain/pull/1755/files

### 1.3 unknown→stale 降级策略（X.509 TTL 经验复用）
- 【可借鉴】T2/T12 已确认：X.509 模型=内容不可变、有效性状态可变；035 已落地 verification_status=unverified/verified/stale/revoked/expired + expires_at/revoked_at/revoked_reason。外部补齐：阿里云知识库过期内容治理闭环（标记→通知→复审→下线）与知识新鲜度维护（T2 2.3 已引）。https://developer.aliyun.com/article/1750481
- 【可借鉴】unknown 的默认值必须是降级而非信任：本项目 wiki_gate.py 原则已写明 Unknown freshness cannot be resolved by assuming no changes（未知新鲜度不能靠假设无变化来消解）——与 trellis-ai ADR importance-score-freshness 一致，把新鲜度作为独立的、可降级的分值维度而非布尔。https://github.com/ronsse/trellis-ai/blob/feat/api-key-scopes/docs/design/adr-importance-score-freshness.md
- 【仅参考】LLM 缓存场景的 recency/freshness 信号综述（缓存命中与新鲜度折衷）。https://www.ranktracker.com/sk/blog/llm-caching-recency-freshness-signals/

---

## 二、上下文替换 / compaction（预算约束下的证据替换）

### 2.1 触发式压缩：Microsoft Agent Framework compaction
- 【可借鉴】Microsoft Agent Framework 的 compaction 是预算触发+摘要替换的业界标准形态：监听 token 用量，超过 CompactionTriggers 阈值时触发 SummarizationCompactionStrategy——把超出窗口的旧会话范围压缩为摘要，仅保留最近范围原文；触发条件、策略、保留范围全部可配置。https://learn.microsoft.com/agent-framework/concepts/agents/conversations/compaction
- 【可借鉴】要点：压缩是旧换新的预算机制而非理解机制——token 记账决定何时换；摘要策略决定怎么换；保留最近 N 轮原文 + 旧范围进摘要是默认值。对应本项目：remaining_chars/remaining_seconds 已进 EvidenceGate 记账，缺的是超出预算时把低价值旧引用替换为高价值新证据的显式替换规则。

### 2.2 证据级压缩与打包（上限满时如何读第九页）
- 【可借鉴】RECOMP（ICLR 2024）：RAG 长上下文的双模式压缩——抽取压缩（句子级选择）与抽象压缩（摘要生成）；压缩后的上下文显著低于原长且保持性能，选择性增强即先选后喂。https://proceedings.iclr.cc/paper_files/paper/2024/hash/bda88ed2892f5e61c9a9bf215c566913-Abstract-Conference.html
- 【可借鉴】What Survives Into Context（arXiv 2607.00725）：预算受限多跳 RAG 的诊断 + Submodular Evidence Packing——当上下文预算满时，用子模函数（价值近似度量：信息增益+去冗余）做证据打包，选取留下来进上下文的证据子集；这正是第九页怎么读的答案：不是按检索顺序截断，而是按边际价值打包。https://huggingface.co/buckets/huggingchat/papers-content/tree/2607/2607.00725.md （arXiv:2607.00725）
- 【可借鉴】When Knowledge Is Not Free（arXiv 2606.02245）：成本感知的证据选择——把证据成本（token/延迟）纳入选择函数，结论是没有统一最优的固定选择器（no fixed selector uniformly dominates），选择策略应随预算与任务动态调整——对应本项目均衡 vs 深读应参数化而非写死。https://export.arxiv.org/pdf/2606.02245
- 【可借鉴】位置偏差（lost in the middle）是替换排序的硬约束：LLM 对上下文中间位置记忆最差——替换后高价值证据必须位居开头/结尾。位置偏差在 RAG 中的复现研究（Lost in the Evidence）：https://dl.acm.org/doi/10.1145/3805712.3808569 ；缓解研究（Found in the Middle）：http://export.arxiv.org/pdf/2406.16008 ；输入端接近窗口上限时偏差漂移（Positional Biases Shift as Inputs Approach Context Window Limits）：https://ar5iv.labs.arxiv.org/html/2508.07479
- 【仅参考】结构化上下文驱逐（Beyond Compaction: Structured Context Eviction for Long-Horizon Agents）与 DAG 状态管理下的无损裁剪——长期代理的上下文内存管理前沿，阶段 C 单轮问题用不上，仅参考其逐出≠删除、是结构化归档的思想。https://browse-export.arxiv.org/pdf/2606.11213 ；https://browse-export.arxiv.org/pdf/2602.22402

### 2.3 KV cache 等价物在 RAG 中的做法
- 【仅参考】RAG 场景没有直接对应 KV cache 的机制（KV cache 无损），RAG 的缓存等价物就是证据缓存/检索结果缓存，其新鲜度治理与 1.2 观察水位线同构——缓存必须带新鲜度水位，否则缓存本身成为 stale 源。


---

## 三、深读模式（deep-read / multi-hop iterative retrieval）

### 3.1 均衡 vs 深读的参数化设计
- 【可借鉴】RASER（arXiv 2606.02488）：可恢复性感知的选择性升级路由——先把预算花在低成本单跳（one-shot RAG）上，根据当前答案的可恢复性估计决定是否升级到 bridge retrieval（额外跳数）；三种开销档位（不额外调用/桥接检索/全深读）动态切换。这是均衡→深读参数化的直接范本：升级条件 = 可恢复性（失败代价）x 剩余预算。https://arxiv-org.ezproxy.obspm.fr/html/2606.02488v1
- 【可借鉴】Step-DeepResearch Technical Report（arXiv 2512.20491）：让深研代理在真实约束（预算/时间/工具）下学习策略——预算即训练信号；报告明确覆盖 step budgets（分步预算）设计。https://ar5iv.labs.arxiv.org/html/2512.20491 ；分步预算通用讨论：https://export.arxiv.org/pdf/2608.02751
- 【可借鉴】Rerank Before You Reason（arXiv 2601.14224）：以 effective token cost（每步实际消耗）分析 deep search 代理中 rerank 的权衡——预算治理要按有效 token 成本记账而非按轮数。https://ar5iv.labs.arxiv.org/html/2601.14224
- 【可借鉴】STORM（Stanford，arXiv 2402.14207）：多轮大纲→提问→检索→写作的迭代范式，其预算=明确的问题数/轮数上限，每轮问题由大纲缺口驱动——覆盖缺口驱动下一跳的问题生成规则可直接借鉴。https://ar5iv.labs.arxiv.org/html/2402.14207

### 3.2 业界 deep research 的预算治理与失控防护
- 【可借鉴】循环守卫（loop guard）是深研系统的标准件：NVIDIA aiq PR loop guard middleware to bound researcher——中间件层强制研究代理的循环边界，不依赖模型自觉。https://github.com/NVIDIA-AI-Blueprints/aiq/pull/437 ；Claude Skills deep-research 亦内置深度/预算上限：https://mintlify.wiki/npow/claude-skills/skills/deep-research
- 【可借鉴】分层质量门（tiered protocol with quality gates）：Mercury PR——深研按层级推进、每层质量门校验后才升级（与 EvidenceGate 的 next_reads/coverage 门控同构）。https://github.com/392fyc/Mercury/pull/77
- 【可借鉴】失控教训（真实事故观察）：华为云博客记录——单任务搜索量达数十到上百次时，系统未触发任何用户确认与预算提醒，默认持续运行直至配额耗尽：预算提醒必须由系统强制（不可被模型关闭），超限即停。https://bbs.huaweicloud.com/blogs/480189
- 【可借鉴】工程教学实践：把深研探索硬性封顶（如 6 次工具调用/会话）作为默认防呆——封顶值可配，默认保守。https://github.com/iusztinpaul/designing-real-world-ai-agents-workshop/commit/5dbf6e3db62ef923cfa58109808dfc6ac16370c2
- 【仅参考】多代理深研架构综述（Zylos：multi-hour autonomous research systems，分阶段=规划/检索/验证/写作，各配预算）：https://zylos.ai/zh/research/2026-04-21-deep-research-agent-architectures/ ；中文深研技术原理与边界（古月居）：http://new.guyuehome.com/wap/detail?id=2061731213577580545

---

## 四、Evidence Gate 分维度判定：authority/freshness/coverage/conflict/budget

### 4.1 本项目现状（wiki_gate.py，基线 f306676）——分维门控已具雏形
- authority：Literal[not_checked, passed, denied]，确定性子系统（vault scope、binding 校验），模型不可设置。
- freshness：默认 unknown + source_observation（not_checked/baseline_unknown/changed_since_capture/unchanged_since_capture）+ 观察水位线（source_watermark.py）；unknown 不能靠假设无变化消解（fail closed）。
- coverage/conflict：模型评估（partial/model_assessed_complete；disputed/none_detected_by_model），但全部引用 quote 必须命中 gate_evidence 白名单校验（wiki_assessment_unverified_quote 拒绝未验证引文）；conflict 至少 2 条不同证据（wiki_assessment_duplicate_conflict_support）。
- budget：remaining_chars/remaining_seconds 双轴记账 + budget_exhausted + stop_reason 枚举（budget_exhausted/time_budget_exhausted/round_budget_exhausted）——已覆盖时间/token/轮数三轴。
- 设计原则（模块 docstring）：Evidence assessment is advisory; authority and read scope stay deterministic——模型可设置项=语义评估（coverage/conflict/questions/next_reads）；不可设置项=权威/作用域/引用校验/预算硬上限。

### 4.2 外部经验对照
- 【可借鉴】VG-RAG（Scientific Reports 2026）：verification-gated retrieval-augmented generation——生成前先过验证门（claims 必须由证据支持，否则 abstain），门控是生成流程的强制环节而非可选后处理。https://www.nature.com/articles/s41598-026-67853-8
- 【可借鉴】EviBound（arXiv 2511.05524）：Evidence-Bound Autonomous Research——治理框架把主张生成与证据验证解耦，未绑定证据的主张不得进入产出；覆盖缺口（coverage gap）显式记入治理状态。https://ar5iv.labs.arxiv.org/html/2511.05524
- 【可借鉴】LedgerRAG（MDPI Electronics 2026, 15(7), 1376）：governance-driven agentic chain of retrieval——检索链逐步走治理维度（来源账本、权限、审计），与 EvidenceGate 逐维门控同构。https://www.mdpi.com/2079-9292/15/7/1376/pdf
- 【可借鉴】Oracle 实时 RAG 的 freshness tests 与 Azure change feed（见 1.2）——freshness 维度的可测试化：新鲜度不是一次性评估而是可断言、可报警的运行时属性。
- 【仅参考】Sophia（provenance-aware verifier-gated reasoning layer，abstain 而非捏造）与 Truthfulness Assurance 架构（calibrated abstention + safe-default routing）：https://zenodo.org/records/21875756 ；https://zenodo.org/records/20259304 ；TRACE-Med（基于策略的弃答）：https://ieeexplore.ieee.org/document/11634785/authors

### 4.3 模型可设置 vs 不可设置的边界（结论）
- 【可借鉴】按外部实践与本项目 docstring 收敛为四条边界：1) 权威/作用域/密码学校验（authority、vault scope、quote 白名单、content_hash 校验）——模型不可设置；2) 语义评估（coverage/conflict/questions/next_reads）——模型可设置但必须可验证（每个引文可回溯）；3) 预算（char/time/round）——模型不可设置，系统记账、系统强制；4) 新鲜度状态——模型不可提升（只能报告 unknown/观察结果），降级是系统策略（T2 X.509 模型）。
- 【可借鉴】advisory 评估 + deterministic 门的分工与 EviBound/VG-RAG 一致：评估可以错，门不能松；模型输出在进门之前必须经过结构化校验（本项目 parse_assessment 的六道校验即此）。

---

## 五、对阶段 C 四个功能点的应用映射

1. 新鲜度状态机：035 已有 status+expires_at/revoked_at 骨架；补 recency prior（2509.19376 半衰期权重）进检索排序/引用选择；unknown 保持 fail-closed 降级（不与变化检测混用）。
2. 相关性水位线：source_watermark 已是正确底座（观察水印≠语义新鲜度）；new-source relevance watermark=查询开始快照比对；可补周期对账（gbrain doctor lag 模式）与 freshness tests（Oracle 模式）。
3. 上下文替换：token 记账（已有 remaining_chars）+ 触发式压缩（MS compaction）+ 证据子模打包（2607.00725）——预算满时按边际价值换入第九页，位置偏差约束摆放（2606.16008）。
4. 深读模式：RASER 升级路由（均衡→深读的可恢复性决策）+ 四轴预算（char/time/round/token-cost）+ 循环守卫与系统强制预算提醒（aiq PR、华为云事故教训）。
5. Evidence Gate 分维：保持 authority/scope/quote 校验/预算四类不可设置；coverage/conflict 模型评估但引文必须白名单可验证；补 freshness 的时间戳/版本在不可设置侧（引用必须带 content_hash/generation，与 EviBound/VG-RAG 对齐）。

---

## 六、要点速览（15 条）

1. Recency prior（半衰期衰减权重）是缓解 stale fact 的最简有效手段（arXiv 2509.19376）；启发式趋势检测不能替代时间先验。【可借鉴】
2. 观察水位线 ≠ 语义新鲜度证书：本项目 source_watermark.py 已确立此边界，阶段 C 应保持两维分离。【可借鉴】
3. 变化检测的云原生标准=数据库变更流驱动增量索引（Azure change feed）；Oracle 强调 freshness tests 可断言化。【可借鉴】
4. EviDex：provenance 加权索引支持连续更新下的新鲜+可审计检索。【可借鉴】
5. unknown 的默认行为是降级而非信任（项目原则不能假设无变化；trellis-ai ADR 把新鲜度当可降级分值）。【可借鉴】
6. MS Agent Framework compaction：token 阈值触发 + 旧范围摘要化 + 最近范围保留，是预算触发的引用替换标准形态。【可借鉴】
7. RECOMP（ICLR 2024）：抽取压缩+抽象压缩双模式，长上下文 RAG 先压后喂。【可借鉴】
8. 上限满时读第九页 = 子模证据打包（arXiv 2607.00725）：按边际价值选证据子集，而非按检索顺序截断。【可借鉴】
9. 成本感知证据选择（arXiv 2606.02245）：无统一最优固定选择器，选择策略应随预算动态调整。【可借鉴】
10. 位置偏差约束替换摆放：高价值证据放开头/结尾（lost in the middle 复现与 Found in the Middle 缓解）。【可借鉴】
11. RASER：均衡→深读的升级路由=可恢复性估计 x 剩余预算，动态切换单跳/桥接/深读档位。【可借鉴】
12. STORM 的覆盖缺口驱动下一跳提问生成 + Step-DeepResearch 的预算即训练信号。【可借鉴】
13. 深研预算治理=系统强制：loop guard 中间件（NVIDIA aiq）、分层质量门（Mercury）、默认硬封顶；华为云记录上百次搜索无提醒直到配额耗尽为失控教训。【可借鉴】
14. 深研记账按 effective token cost 而非轮数（Rerank Before You Reason）。【可借鉴】
15. Evidence Gate 边界：authority/scope/quote 白名单/预算=模型不可设置；coverage/conflict=模型评估但引文必须可验证；与 VG-RAG/EviBound 的评估可以错、门不能松一致。【可借鉴】
