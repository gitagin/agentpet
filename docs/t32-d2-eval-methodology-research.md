# T32/D2 评测方法论调研：RAG 质量评测与安全计分（阶段 D 预研）

- 调研人：webre-a（researcher，AgentTeams）
- 调研日期：2026-09-19（所有条目访问日期同此）
- 方式：web_search 中英文关键词（约 15 次检索）；来源以论文（arXiv/ACL/ICLR）、官方文档、工程博客、GitHub 为准
- 标记说明：【可借鉴】= 建议引入阶段 D（评测）的模式/结论；【仅参考】= 只作背景理解，不引入依赖
- 关联输入：T1 盘点、T24/C2 调研（docs/t24-c2-freshness-context-deepread-research.md）、基线 f306676；项目既有评测基础设施：app/evals/（llmwiki_fault_scenarios.py、llmwiki_graph_eval.py、retrieval_eval.py、llmwiki_migration_smoke.py）、tests/evals/*.json 题集（graph-lifecycle-v1.json、retrieval-corpus-v1.json）、services/wiki/shadow.py 评估器、test_retrieval_quality_eval.py

---

## 一、RAG 评测基准与指标（借用定义，不引入依赖）

### 1.1 正确性与忠实度、答案相关
- 【可借鉴】**RAGAS 四件套是事实标准**：faithfulness（答案中每个声明是否被检索上下文支持，逐声明核对）、answer relevancy（答案对问题的相关度）、context precision/context recall（检索侧精确率/召回率）。官方文档（含指标定义与计算）：https://docs.ragas.io/en/v0.1.21/getstarted/evaluation.html ；Azure Databricks MLflow 集成页（第三方评分器说明）：https://learn.microsoft.com/zh-cn/azure/databricks/mlflow3/genai/eval-monitor/third-party-scorers/ragas
- 【可借鉴】**ARES（An Automated Evaluation Framework for RAG）**：合成训练集精调 LLM judge，并用 prediction-powered inference（PPI）给 judge 打分加统计置信区间——reference-free 评估的可靠性工程，解决「judge 自身可能不准」的问题。https://jonsaadfalcon.com/papers/ares
- 【可借鉴】**CRUD-RAG（中文基准，arXiv 2401.17043 / ACM TOIS）**：按 Create/Read/Update/Delete 四类操作组织中文评测，指标含准确率、忠实度、拒绝回答率、抗噪声；与本项目语义高度对应——Read=查询、Update=版本 bump、Delete=forgotten/revoked 后的拒绝语义。https://dl.acm.org/doi/pdf/10.1145/3701228 ；原文：https://huggingface.co/buckets/huggingchat/papers-content/tree/2401/2401.17043.md

### 1.2 引用质量（citation precision / recall）
- 【可借鉴】**ALCE benchmark（Enabling LLMs to Generate Text with Citations）**：定义句子级 citation precision（引用句确实被支持）与 citation recall（该引用的内容确实源于文档）——引用质量的两轴定义。https://collaborate.princeton.edu/en/publications/enabling-large-language-models-to-generate-text-with-citations/
- 【可借鉴】**生成时引用 vs 事后补引用**（Generation-Time vs. Post-hoc Citation, arXiv 2509.21557）：生成时引用（quote 来自检索上下文）比事后补引用更可靠、更可审计——本项目 gate_evidence/quote 白名单正是生成时引用校验。https://arxiv.org/abs/2509.21557v1
- 【可借鉴】**伪造引用必须确定性拦截**：verbatim-citation-gate（零 token 逐字门 + burden-of-proof judge）——引文逐字比对失败即拒绝，不交给模型判断；与本项目 wiki_assessment_unverified_quote（引用必须命中 gate_evidence 白名单）同构。https://github.com/tonydzi/verbatim-citation-gate
- 【仅参考】FACTUM（ECIR，citation hallucination 机制检测）与 CiteGuard（ICML 2026，conformal FDR 控制虚假引用率）——学术前沿，仅参考其「引用错误要控制错误发现率」的思想。https://dl.acm.org/doi/abs/10.1007/978-3-032-21289-4_18 ；https://icml.cc/virtual/2026/poster/64935

### 1.3 覆盖率 / needle / 多跳测试集设计
- 【可借鉴】**NovelHopQA（EMNLP 2025）**：长叙事多跳推理诊断基准——把答案关键事实分散在不同段落构造多跳问题，专门定位「检索到但推理失败」与「跳跃缺失」两类失败。https://aclanthology.org/2025.emnlp-main.1328/
- 【仅参考】**Haystack Engineering（arXiv 2510.07414）**：异构/智能体长上下文 needle 实验的上下文工程——干扰层级、信号插入密度可配置，避免 needle 测试过简失真。https://huggingface.co/papers/2510.07414
- 【仅参考】超越 haystack 的长上下文评测（EACL 2026）：单针测试不足，需多跳+多语言组合。https://aclanthology.org/2026.eacl-long.290.pdf
- 【可借鉴】覆盖率按子问题逐项判定：问题分解为 subquestions，逐项标 supported/missing（= 本项目 QuestionCoverage 结构，对应 RAGAS context recall 思路）。

---

## 二、LLM-as-judge vs 逐条人工核对

### 2.1 适用场景与坑
- 【可借鉴】**LLM judge 的已知偏差**：参考答案进入 prompt 会显著影响打分（Evaluating Scoring Bias in LLM-as-a-Judge, arXiv 2506.22316）；未言明的快捷偏差（The Silent Judge, arXiv 2509.26072）；榜单偏差/模型名影响（LLM-as-a-judge survey, ScienceDirect）。对策：盲评（不暴露路径名/模型名）、prompt 不含参考答案（或对错参考各一组交叉）、固定 rubrics、样例校准。https://ar5iv.labs.arxiv.org/html/2506.22316 ；https://export.arxiv.org/pdf/2509.26072 ；https://www.sciencedirect.com/science/article/pii/S2666675825004564
- 【可借鉴】**MLflow 工程指南「When Can an LLM Judge Another LLM's Output?」**：LLM judge 适合粗粒度/大规模筛选，不适合需要可解释依据的判定；结论是 judge + 抽样人工校准的组合。https://mlflow.org/articles/when-can-an-llm-judge-another-llms-output/
- 【可借鉴】**judge 赢不过两倍数据**（Limits to scalable evaluation at the frontier, ICLR 2025）：规模有限时，把预算花在人工标注上比花在 judge 上更值——固定题集人工逐条核对仍不可替代。https://proceedings.iclr.cc/paper_files/paper/2025/hash/4264ee4376776907c0b87ed70b959585-Abstract-Conference.html
- 【仅参考】人工核对协议可参照 KodeKloud Reliable Human Evaluation Protocol（盲评、双人、不一致仲裁）。https://notes.kodekloud.com/docs/NVIDIA-Generative-AI-LLMs-Associate-Certification/Experimentation/Reliable-Human-Evaluation-Protocol-for-LLM-Outputs

### 2.2 固定题集（golden set）的维护
- 【可借鉴】**golden set 会老化**：FutureAGI 归纳三种漂移——内容漂移（语料更新后旧题失效）、分布漂移（用户问题变化）、标准漂移（评判标准变化）；需定期审计 + 版本化题集。https://futureagi.com/blog/llm-eval-data-drift-detection-2026/
- 【可借鉴】**质量门会悄然失守**：LayerLens——回归测试门在基准分布变化后失去拦截力，门要带「题集新鲜度」元数据。https://layerlens.ai/blog/ai-regression-testing-quality-gate
- 【可借鉴】**RAG 回归测试实践**（QASkills）：固定题集 + 触发式回归（每次发布跑）+ 失败归因模板（failure mode → 根因 → 动作项）。https://qaskills.sh/blog/rag-regression-testing-guide

---

## 三、安全错误单独计分（一次即不过）

### 3.1 方法论：安全证明不了，只能证伪
- 【可借鉴】**What AI Red-Team Evaluations Can and Cannot Prove（arXiv 2607.21735）**：红队/安全评测只能证明漏洞存在，不能证明安全——「零失败」不等于「安全」；安全结论只能以「在 X 题集上未复现」的形式陈述。https://arxiv.org/html/2607.21735v2
- 【可借鉴】**安全错误不进入平均分**：越权读取/伪造引用/内容复活/Assistant Output 升级为事实这四类属于「一次即不过」的独立 gate——发布门禁脚本化（ship_gate.py：阈值=零容忍项 0 失败 + 质量项达线即可）：https://github.com/Autonoma-Tools/how-to-qa-an-ai-feature/blob/main/ship_gate.py ；zero-tolerance 验收模式（prevention_verification_and_gates）：https://github.com/daemon-blockint-tech/Agentic-Enteprises-Skill/blob/main/zero-tolerance-for-failure/references/prevention_verification_and_gates.md

### 3.2 四类安全错误的评测做法
- 【可借鉴】**越权读取**：角色×领域×查询矩阵系统性探测未授权泄露（trustNLP 2026 实测 584 queries、12 roles、9 domains，验证 retrieve-then-filter 会暴露未授权内容）：https://aclanthology.org/2026.trustnlp-main.pdf ；检索原位投毒/间接注入用 RIPE-II 评估：https://ieeexplore.ieee.org/document/11593453
- 【可借鉴】**内容复活（forgotten/revoked 后仍被用作事实）**：借用 machine unlearning 评测范式——构造 retain 组与 forget 组双题集，forget 组必须零召回（MUSE 基准的 forget quality 轴：https://ojs.aaai.org/index.php/AAAI/article/view/41156/45117 ）；更要测「记忆之外的泄漏」——membership inference beyond the forgotten set（遗忘集之外仍可推断泄露）：https://lyrie.ai/research/research/arxiv-cs-cr-revisiting-privacy-leakage-in-machine-unlearning-membership-inferenc
- 【可借鉴】**伪造引用**：逐字门确定性拦截（§1.2 verbatim gate/项目 quote 白名单），评测=引用逐字比对程序化计分，不存在「模型评估」环节。
- 【可借鉴】**Assistant Output 升级为事实**：评测=把 assistant_output 来源的引用混入题集，断言其不得进入事实性回答的证据链（回答必须可回溯到 RAW_SOURCE/USER_STATEMENT 类根证据）；对应本项目 synthesis 的 derived_source_requires_verified_roots 语义。
- 【仅参考】红队误报治理（promptfoo false positives 文档）——安全错误记分要高精确率，误报会稀释信号。https://promptfoo.org.cn/docs/red-team/troubleshooting/false-positives/


---

## 四、消融对照：old vs new 同题集对比的统计与呈现

### 4.1 统计方法
- 【可借鉴】**同题集逐题配对 + McNemar 检验**是双路径消融的标准统计：对每题记录 old/new 各自对错，形成 2x2 配对表，用 McNemar 检验「新路径显著优于旧路径」而非只看均分差（IEEE 消融研究范式明确应用 McNemar on paired per-instance predictions）。https://ieeexplore.ieee.org/document/11640855
- 【可借鉴】多样本时可用带重采样的配对方法（bootstrap/resampling-based paired comparison，NLE 论文）避免小样本假阳性：https://homsy-staging.cambridgecore.org/core/journals/natural-language-engineering/article/resamplingbased-method-to-evaluate-nli-models/36425029D22D619BF9ADB1FEF910D047
- 【仅参考】Nature 相关工作中的显著性检验表格式（作为呈现范本）：https://www.nature.com/articles/s41598-025-25311-x/tables/1

### 4.2 呈现：混淆矩阵四象限
- 【可借鉴】**四象限混淆矩阵**：以旧路径为基准，逐题分类入 (old错→new对=改进) / (old对→new对=保持) / (old错→new错=遗留缺陷) / (old对→new错=回归) 四象限；「回归」象限每一题都必须归因并修复（或显式豁免），「改进」象限给出证据链佐证。中文灰度发布实践同此分法（AB 测试+流量染色+效果归因）：https://blog.csdn.net/weixin_42581846/article/details/156560997
- 【可借鉴】**错误类别标签**：每象限内再按错误类型（忠实度/覆盖/引用/安全/预算截断）聚合，输出热力矩阵而非只给总数——便于定位是「哪类题受新路径影响」。与 QASkills 失败归因模板（failure mode → 根因 → action item）配套。https://qaskills.sh/blog/rag-regression-testing-guide

---

## 五、对阶段 D / 项目应用映射（复用既有 evals 基础）

1. **指标自实现不引依赖**：借用 RAGAS 四件套 + ALCE citation precision/recall 定义，在 app/evals/ 现有框架内实现（禁 pip 引入 RAGAS/ARES 等库）。
2. **题集形态**：沿用 tests/evals/*.json 模式，新增安全题集（安全/unauthorized/forged-citation/resurrection/assistant-output）与质量题集（faithfulness/relevancy/coverage/citation）分开存放、分开计分。
3. **安全一次即不过**：安全题集独立 gate（0 失败放行），不进入质量均分；与既有 P0 安全验收（T7/C7）合并为发布门禁脚本。
4. **内容复活题集**：retain/forget 双题组——forgotten/revoked 来源的关键事实题放 forget 组，断言零召回；另加「沿 documented_in 关系的复活路径」探测（find_candidate_entities_by_source 是否仍能经 legacy hash 键命中）。
5. **双路径消融 harness**：同一题集跑 old（开关关闭）与 new（开关打开）两路径，输出四象限表 + McNemar 显著性 + 错误类别热力矩阵；每轮迭代把回归题固化进题集。
6. **judge 使用规范**：LLM judge 仅用于质量打分粗筛（盲评、prompt 不含参考答案、rubrics 固定）；安全判定走确定性规则；golden set 版本化 + 定期漂移审计（内容/分布/标准三轴）。
7. **评测题集与 shadow.py 评估器衔接**：shadow 评估器（七日期限）做线上样例回流，golden set 做发布门禁，两者结果分开报告。

---

## 六、要点速览（15 条）

1. RAGAS 四件套（faithfulness/answer relevancy/context precision/context recall）是事实标准，借用定义、自实现、不引入依赖。【可借鉴】
2. ARES 用合成数据精调 judge + PPI 置信区间，解决 reference-free 评估「judge 自身不准」问题。【可借鉴】
3. CRUD-RAG（中文基准）按 Create/Read/Update/Delete 四类评测，与 wiki 查询/版本 bump/forgotten 拒绝语义对齐。【可借鉴】
4. 引用质量=ALCE 句子级 citation precision/recall；生成时引用优于事后补引用。【可借鉴】
5. 伪造引用必须确定性拦截（verbatim 逐字门），不交给模型判断；本项目 quote 白名单同构。【可借鉴】
6. 多跳测试集参考 NovelHopQA（分散事实构造多跳、诊断跳跃缺失）；needle 测试需分层干扰（Haystack Engineering）。【可借鉴】
7. LLM judge 的坑：参考答案入 prompt 影响打分、快捷偏差、模型名影响；对策=盲评+固定 rubrics+抽检人工。【可借鉴】
8. judge 赢不过两倍数据（ICLR 2025）：预算有限时人工逐条核对不可替代。【可借鉴】
9. golden set 会老化：内容/分布/标准三种漂移，需版本化题集+新鲜度元数据+定期审计（FutureAGI/LayerLens）。【可借鉴】
10. 红队评测只能证伪不能证明：零失败≠安全（arXiv 2607.21735），安全结论以「题集未复现」陈述。【可借鉴】
11. 安全错误单独计分：越权/伪造引用/复活/升级四类一次即不过，独立 gate 不混入均分（ship_gate 模式）。【可借鉴】
12. 越权读取评测=角色×领域×查询矩阵（trustNLP 584 queries/12 roles 实测）；间接注入用 RIPE-II。【可借鉴】
13. 内容复活评测=unlearning 范式：retain/forget 双题组、forget 组零召回（MUSE），再加遗忘集外泄漏探测。【可借鉴】
14. Assistant Output 升级评测：引用必须可回溯到根证据（RAW_SOURCE/USER_STATEMENT），否则判失败。【可借鉴】
15. 消融=同题集双路径配对 + McNemar 显著性 + 四象限（改进/保持/遗留/回归），回归题逐题归因固化进题集。【可借鉴】
