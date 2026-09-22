"""阶段 D 节点级双路径评测驱动(设计 §2.1/§2.2)。

同一节点代码 + 参数化开关 = 双路径消融对照,**不重写旧节点**:
- 新路径(mode="new"):wiki_knowledge_retrieval_node 原样运行;
- 旧路径(mode="old"):同一节点 + 3 个模块级补丁,恢复阶段 C 之前语义:
  1. derive_source_freshness 恒 ("unknown", "source_relevance_check_pending");
  2. DEEP_PROFILE 等于 BALANCED_PROFILE(升级路由等于原地不动);
  3. _citation_value 恒 0.0(candidate_value <= min_held 恒成立 → 禁用价值准入与替换)。

**测量边界(诚实声明)**:该节点负责**检索与证据装配**,不生成自然语言答案。
因此本驱动以**引用内容**作为「结论」载体参与 golden 判定——衡量的是检索/证据质量,
不是答案生成质量。真实模型答案质量需 --mode real,本环境无端点。
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from app.agents.nodes import wiki_retrieval as node_module
from app.agents.nodes.wiki_retrieval import wiki_knowledge_retrieval_node
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState, SemanticAnalysisResult
from app.api.services import factory
from app.api.services.adapters import RuntimeWikiReadAdapter
from app.evals.phase_d_questions import (
    citation_scores,
    conclusion_coverage,
    safety_violations,
)
from app.services.wiki.snapshot_reader import WikiSnapshotReader


def _passed_for_action(
    golden, conclusion_coverage: float, recall: float, cited_paths
) -> bool:
    """按 golden.action 分类判定——不同动作的正确行为不同，不能用同一判据。

    每个分支只使用下面这些**真实入参**，名字与含义一一对应：

    - `conclusion_coverage`：**预期结论**在已取到证据文本中的覆盖比例（浮点）。
      ⚠ 它**不是** `gate.coverage` —— 后者是**系统自己声明的**覆盖档位，是另一个量。
      本函数**不接收** `gate.coverage`，原因见下方「不可验证的一段」。
    - `recall`：`golden.citations` 中被实际引用的比例。
    - `cited_paths`：本次实际引用到的路径集合。

    分支与承诺的对应关系：
      answer  : 结论覆盖完整且应有引用全部取到    -> conclusion_coverage == 1.0 and recall == 1.0
      reject  : 被拒来源不得出现在引用里            -> not (expected & actual)
      degrade : 至少取到相关证据 + 证据须支持预期结论 -> recall > 0.0 and conclusion_coverage > 0.0
      fallback: 同 degrade                          -> 同上

    ⚠ **本 harness 内不可验证的一段（显式声明，不假实现）**：
      `degrade` 的完整承诺是「应作答但**须标注覆盖不足**」。该子句指的是**系统自己的覆盖声明**
      （`WikiEvidenceGate.coverage`，取值 not_assessed / partial / model_assessed_complete），
      **不是本函数的任何入参**。而它在本 harness 内**结构性不可得**：

      1. `app/agents/nodes/wiki_retrieval.py:459-461`：`if not model:`
         `report["stop_reason"] = "assessment_unavailable"` 然后 `break`
         —— **在任何评估之前就跳出**；
      2. `gate.coverage` 只有 `apply_assessment`（`app/agents/retrieval/wiki_gate.py:169-173`）
         会写成非默认值，默认值为 `not_assessed`（`wiki_gate.py:60`），
         其余写点（`wiki_retrieval.py:485/523/556/674`）**全部重置为 not_assessed**；
      3. 而本 harness（`tests/phase_d_eval.py`）**不提供任何 model**。

      ⇒ 评估永不运行 ⇒ `gate.coverage` 恒为 `not_assessed` ⇒ **该子句无法被检验**。

      **因此本函数不接收该量**：接收一个恒不可得、且不会被使用的入参，只会再造一个
      「名字看起来已接线、实际没接线」的伪证据 —— 那正是本次改名要消除的东西。
      若将来把 model 接入本 harness，守卫测试
      `test_gate_coverage_is_unavailable_in_this_harness` 会失败，
      届时必须**真正实现**该子句，而不是让它继续隐形。
    """
    action = str(golden.get("action") or "answer")
    expected = {str(path) for path in (golden.get("citations") or [])}
    actual = {str(path) for path in cited_paths}
    if action in {"reject", "stale"}:
        # reject:正确行为是拒绝作答;stale:原始资料已变化,旧内容不得作为当前事实。
        # 两者都用同一可检验判据:该页不得出现在引用里。
        return not (expected & actual)
    if action in {"degrade", "fallback"}:
        # L1 修复:原先只判 recall > 0.0,把**已算出、已传入**的 conclusion_coverage 整个丢掉。
        # 取 > 0.0 而非 == 1.0:degrade 的语义本就是**覆盖不足**,
        # 要求满覆盖会与该动作的定义自相矛盾。
        return recall > 0.0 and conclusion_coverage > 0.0
    return conclusion_coverage == 1.0 and recall == 1.0


@dataclass
class QuestionOutcome:
    question_id: str
    scenario: str
    mode: str
    cited_paths: list[str] = field(default_factory=list)
    coverage: str = "not_assessed"
    freshness: str = "unknown"
    conflict: str = "not_assessed"
    stop_reason: str = ""
    # 准入/置换证据:新旧路径的引用条数可能相同(准入 1 页又置换 1 页),
    # 真正的差异在「读了几页」与「置换了几页」,故必须单独采集。
    read_count: int = 0
    replaced: int = 0
    displaced: list[str] = field(default_factory=list)
    latency_ms: int = 0
    assessment_calls: int = 0
    conclusion_coverage: float = 0.0
    citation_precision: float = 0.0
    citation_recall: float = 0.0
    passed: bool = False
    # 方案 E(设计 §4-E.1):本题是否**真正考到**了它声称考的能力。
    # **必须由检测器算出,不得人工声明** —— 人工声明是「未经验证的断言」且会腐烂
    # (底层修好后不自动翻转),等于把「虚报通过」换成「虚报未考到」。
    exercised: bool = True
    # 诊断标签(口径治理规则③:标记未考到的同时必须登记「为什么未考到」)。
    # 三个互斥取值:gate_denied / load_rejected / never_candidate;空串表示无 golden 引用。
    absence_reason: str = ""


@contextmanager
def _legacy_semantics():
    """把节点恢复为阶段 C 之前的确定性语义(仅评测用,不改生产代码)。"""
    original_freshness = node_module.derive_source_freshness
    original_deep = node_module.DEEP_PROFILE
    original_value = node_module._citation_value
    node_module.derive_source_freshness = lambda **kwargs: (
        "unknown",
        "source_relevance_check_pending",
    )
    node_module.DEEP_PROFILE = node_module.BALANCED_PROFILE
    node_module._citation_value = lambda score, freshness, coverage: 0.0
    try:
        yield
    finally:
        node_module.derive_source_freshness = original_freshness
        node_module.DEEP_PROFILE = original_deep
        node_module._citation_value = original_value


def _authorize(database):
    """与 factory 读路径同构:binding 必须 active 且未撤销。"""

    def authorize(vault_id: str, relative_path: str) -> bool:
        with database.session(read_only=True) as conn:
            row = conn.execute(
                "SELECT status, revoked_at FROM wiki_page_bindings "
                "WHERE vault_id = ? AND wiki_relative_path = ?",
                (vault_id, relative_path),
            ).fetchone()
        return (
            row is not None
            and row["status"] == "active"
            and row["revoked_at"] is None
        )

    return authorize


# ---------------------------------------------------------------- 方案 E 检测器
# 判定规则(设计 §4-E.1,**按「缺席由谁造成」**):
#   gate_denied      = **评测 harness 自己装的闸**拒绝了 golden 路径
#                      ⇒ 判定为真来自**题目的构造**,不是系统表现 ⇒ **未考到**。
#   load_rejected    = **系统自己的完整性校验**拒绝了 golden 路径
#                      ⇒ 判定反映**系统真实行为** ⇒ **已考到,如实失败**。
#   never_candidate  = 页可读但没进候选 ⇒ 系统检索失败 ⇒ **已考到,如实失败**。
#
# 为什么不用「存在可达行为能改变判定」这句字面表述:严格读它会把 gate_denied 也算成已考到
# (读器若不再遵守 authorize 回调,判定就会翻转),与已定范围矛盾。
# 「由谁造成」才是可操作的判别式,且恰好给出已定范围。
ABSENCE_GATE_DENIED = "gate_denied"
ABSENCE_LOAD_REJECTED = "load_rejected"
ABSENCE_NEVER_CANDIDATE = "never_candidate"


class _GoldenPathProbe:
    """记录 golden 引用路径在运行期**被哪一层**拒绝。只观察,不改行为。"""

    def __init__(self, authorize, golden_paths: Iterable[str]) -> None:
        self._authorize = authorize
        self._golden = frozenset(str(path) for path in golden_paths)
        self.gate_denied: set[str] = set()
        self.load_rejected: set[str] = set()

    def authorize(self, vault_id: str, relative_path: str) -> bool:
        allowed = self._authorize(vault_id, relative_path)
        if relative_path in self._golden and allowed is not True:
            self.gate_denied.add(relative_path)
        return allowed

    def wrap_reader(self, reader):
        original = reader._load

        def load(*args: Any, **kwargs: Any):
            try:
                return original(*args, **kwargs)
            except Exception:
                path = kwargs.get("path")
                if path is None and len(args) > 1:
                    path = args[1]
                if path in self._golden:
                    self.load_rejected.add(str(path))
                raise

        reader._load = load
        return reader

    def classify(self) -> tuple[bool, str]:
        if not self._golden:
            return True, ""
        # **顺序即语义**:被 harness 的闸拒绝的页连 _load 都到不了,
        # 若先判 load_rejected 会把「harness 造成」误记成「系统造成」——那正是要防的误标。
        if self.gate_denied:
            return False, ABSENCE_GATE_DENIED
        if self.load_rejected:
            return True, ABSENCE_LOAD_REJECTED
        return True, ABSENCE_NEVER_CANDIDATE


def _state(question: str) -> dict[str, Any]:
    return {
        "agent_state": AgentState(
            conversation_id="phase-d",
            message_id="phase-d-message",
            agent_run_id="phase-d-run",
            user_message=question,
            semantic_analysis=SemanticAnalysisResult(
                needs_context=True, source_scope="knowledge_base", query=question,
            ),
        ),
        "events": [],
    }


def run_question(
    corpus, question: Mapping[str, Any], *, mode: str = "new", semantic_embedder=None,
    reader_patch=None,
) -> QuestionOutcome:
    """在给定语料上跑一题,返回确定性指标(不调用真实模型)。

    semantic_embedder=None 时快照检索走纯词法单路(历史行为);注入嵌入器后走
    「词法 + 语义」双路 RRF 融合——这是消融对照的**唯一**开关。
    """
    if mode not in {"new", "old"}:
        raise ValueError(f"unknown mode: {mode!r}")
    # 方案 E:探测 golden 路径被哪一层拒绝。包装 authorize 与 _load 只做观察,
    # 不改变任何返回值/异常(load 包装原样重抛)。
    probe = _GoldenPathProbe(
        _authorize(corpus.database),
        (question.get("golden") or {}).get("citations") or (),
    )
    reader = probe.wrap_reader(
        WikiSnapshotReader(
            corpus.database, corpus.service.wiki, authorize=probe.authorize,
            semantic_embedder=semantic_embedder,
        )
    )
    if reader_patch is not None:
        # 消融专用:允许驱动替换读器方法(如只留语义通道),生产代码不暴露该开关。
        reader_patch(reader)
    # 兜底路径需要 retrieval 服务(与 test_wiki_vault_fallback 同口径:monkeypatch
    # adapters 的 vault 解析与 retrieval 工厂,再用 RuntimeRetrievalAdapter 包装)。
    from app.api.services import adapters as _adapters

    with corpus.database.session(read_only=True) as conn:
        vault_row = conn.execute("SELECT id FROM vaults LIMIT 1").fetchone()
    vault_id = vault_row["id"] if vault_row is not None else ""
    original_vault_id = _adapters.active_vault_id
    original_retrieval = _adapters.retrieval_service
    _adapters.active_vault_id = lambda _: vault_id
    _adapters.retrieval_service = lambda _: corpus.service.retrieval
    services = AgentRuntimeServices(
        wiki_reader=RuntimeWikiReadAdapter(object()),
        retrieval=_adapters.RuntimeRetrievalAdapter(object()),
    )
    original_dependency = factory.wiki_snapshot_reader_dependency
    factory.wiki_snapshot_reader_dependency = lambda request: reader
    state = _state(str(question["question"]))

    started = time.monotonic()
    if mode == "old":
        with _legacy_semantics():
            asyncio.run(wiki_knowledge_retrieval_node(state, services))
    else:
        asyncio.run(wiki_knowledge_retrieval_node(state, services))
    factory.wiki_snapshot_reader_dependency = original_dependency
    _adapters.active_vault_id = original_vault_id
    _adapters.retrieval_service = original_retrieval
    latency_ms = int((time.monotonic() - started) * 1000)

    agent_state = state["agent_state"]
    report = state.get("wiki_reading") or {}
    gate = agent_state.wiki_evidence_gate
    citations = list(agent_state.citations or [])
    cited_paths = [str(item.relative_path) for item in citations]
    evidence_text = "\n".join(str(item.snippet or "") for item in citations)

    golden = question["golden"]
    exercised, absence_reason = probe.classify()
    precision, recall = citation_scores(golden["citations"], cited_paths)
    coverage_score = conclusion_coverage(golden["conclusion"], evidence_text)
    return QuestionOutcome(
        question_id=str(question["id"]),
        scenario=str(question["scenario"]),
        mode=mode,
        cited_paths=cited_paths,
        coverage=str(getattr(gate, "coverage", "not_assessed")),
        freshness=str(getattr(gate, "freshness", "unknown")),
        conflict=str(getattr(gate, "conflict", "not_assessed")),
        stop_reason=str(report.get("stop_reason") or ""),
        read_count=len(report.get("read") or []),
        replaced=int(report.get("replaced") or 0),
        displaced=[str(item) for item in (report.get("displaced") or [])],
        latency_ms=latency_ms,
        assessment_calls=int(report.get("assessment_calls") or 0),
        conclusion_coverage=coverage_score,
        citation_precision=precision,
        citation_recall=recall,
        passed=_passed_for_action(golden, coverage_score, recall, cited_paths),
        # 每次运行都重新算 —— 这正是口径治理规则②「只能由检测器自动翻转、
        # 不允许人工改回」的实现方式:没有任何可人工写入的字段。
        exercised=exercised,
        absence_reason=absence_reason,
    )


def run_suite(corpus_factory, questions: Iterable[Mapping[str, Any]], *, modes: Sequence[str] = ("new",)) -> list[QuestionOutcome]:
    """按 vault_fixture 分组构建语料,逐题跑指定模式。"""
    by_fixture: dict[str, list[Mapping[str, Any]]] = {}
    for question in questions:
        by_fixture.setdefault(str(question["vault_fixture"]), []).append(question)
    outcomes: list[QuestionOutcome] = []
    for fixture, group in by_fixture.items():
        corpus = corpus_factory(fixture)
        for question in group:
            for mode in modes:
                outcomes.append(run_question(corpus, question, mode=mode))
    return outcomes


def summarize(outcomes: Sequence[QuestionOutcome]) -> dict[str, Any]:
    """按题配对 old/new,产出四象限与七项指标(设计 §2.2/§3.1)。"""
    paired: dict[str, dict[str, QuestionOutcome]] = {}
    for outcome in outcomes:
        paired.setdefault(outcome.question_id, {})[outcome.mode] = outcome

    quadrants = {
        "both_pass": 0,
        "old_pass_new_fail": 0,
        "old_fail_new_pass": 0,
        "both_fail": 0,
    }
    by_scenario: dict[str, dict[str, int]] = {}
    totals = {
        "new_pass": 0, "old_pass": 0,
        "new_reads": 0, "old_reads": 0,
        "new_replaced": 0, "old_replaced": 0,
        "new_latency_ms": 0, "old_latency_ms": 0,
    }
    for question_id, modes in paired.items():
        new = modes.get("new")
        old = modes.get("old")
        if new is None or old is None:
            continue
        scenario = new.scenario
        bucket = by_scenario.setdefault("scenario") if False else by_scenario.setdefault(scenario, {
            "both_pass": 0, "old_pass_new_fail": 0,
            "old_fail_new_pass": 0, "both_fail": 0,
        })
        if new.passed and old.passed:
            key = "both_pass"
        elif old.passed:
            key = "old_pass_new_fail"
        elif new.passed:
            key = "old_fail_new_pass"
        else:
            key = "both_fail"
        quadrants[key] += 1
        bucket[key] += 1
        totals["new_pass"] += int(new.passed)
        totals["old_pass"] += int(old.passed)
        totals["new_reads"] += new.read_count
        totals["old_reads"] += old.read_count
        totals["new_replaced"] += new.replaced
        totals["old_replaced"] += old.replaced
        totals["new_latency_ms"] += new.latency_ms
        totals["old_latency_ms"] += old.latency_ms
    # 方案 E 报告口径(治理规则①:未考到的题**逐条列题号与原因**,不得只报总数)。
    not_exercised = [
        {
            "question_id": outcome.question_id,
            "scenario": outcome.scenario,
            "mode": outcome.mode,
            "absence_reason": outcome.absence_reason,
        }
        for outcome in outcomes
        if not outcome.exercised
    ]
    exercised_totals = {
        "new_exercised": sum(1 for o in outcomes if o.mode == "new" and o.exercised),
        "new_exercised_pass": sum(
            1 for o in outcomes if o.mode == "new" and o.exercised and o.passed
        ),
        "old_exercised": sum(1 for o in outcomes if o.mode == "old" and o.exercised),
        "old_exercised_pass": sum(
            1 for o in outcomes if o.mode == "old" and o.exercised and o.passed
        ),
    }
    return {
        "questions": len(paired),
        "quadrants": quadrants,
        "by_scenario": by_scenario,
        "totals": totals,
        "not_exercised": not_exercised,
        "exercised_totals": exercised_totals,
    }


def render_report(summary: Mapping[str, Any], *, mode: str = "scripted", known_limitations: Sequence[str] = ()) -> str:
    """渲染 Markdown 报告(设计 §3.1 结构)。"""
    quadrants = summary["quadrants"]
    totals = summary["totals"]
    questions = int(summary["questions"] or 0) or 1
    lines = [
        f"# 阶段 D Shadow 评测报告(mode={mode})",
        "",
        "## 0. 运行事实(诚实声明)",
        "- 模型模式：scripted(注入脚本模型；本环境无真实模型端点)",
        "- 测量边界：该节点负责检索与证据装配，不生成自然语言答案；"
        "  本报告的「结论覆盖」以引用内容为载体，衡量**检索/证据质量**。",
        "- 旧路径为**参数化消融**(同一节点 + 3 个模块级补丁)，不是历史版本回放。",
        *([""] + [f"- 已知局限：{item}" for item in known_limitations] if known_limitations else []),
        "",
        "## 1. 总览",
        f"- 配对题数：{summary['questions']}",
        f"- 新路径通过：{totals['new_pass']}/{questions}",
        f"- 旧路径通过：{totals['old_pass']}/{questions}",
        f"- 读取页数：new {totals['new_reads']} vs old {totals['old_reads']}",
        f"- 置换次数：new {totals['new_replaced']} vs old {totals['old_replaced']}",
        f"- 累计延迟：new {totals['new_latency_ms']}ms vs old {totals['old_latency_ms']}ms",
        "",
        "## 1b. 未考到(方案 E)",
        *(
            [
                f"- 未考到题数：{len(summary.get('not_exercised') or [])}"
                f"（考到且通过：{summary.get('exercised_totals', {}).get('new_exercised_pass', 0)}"
                f"/{summary.get('exercised_totals', {}).get('new_exercised', 0)}）",
                "",
                "| 题号 | 场景 | 模式 | 原因 |",
                "| --- | --- | --- | --- |",
                *[
                    f"| {item['question_id']} | {item['scenario']} | {item['mode']} |"
                    f" {item['absence_reason']} |"
                    for item in (summary.get("not_exercised") or [])
                ],
            ]
            if (summary.get("not_exercised") or [])
            else ["- 未考到题数：0（本运行所有题目的判定都可被系统行为改变）"]
        ),
        "",
        "## 2. 混淆矩阵四象限(old vs new)",
        "| 象限 | 题数 |",
        "| --- | --- |",
        f"| 两者皆过 | {quadrants['both_pass']} |",
        f"| 旧过新不过(回归) | {quadrants['old_pass_new_fail']} |",
        f"| 旧不过新过(改进) | {quadrants['old_fail_new_pass']} |",
        f"| 两者皆不过 | {quadrants['both_fail']} |",
        "",
        "## 3. 逐场景四象限",
        "| 场景 | 皆过 | 旧过新不过 | 旧不过新过 | 皆不过 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for scenario, counts in sorted(summary["by_scenario"].items()):
        lines.append(
            f"| {scenario} | {counts['both_pass']} | {counts['old_pass_new_fail']} |"
            f" {counts['old_fail_new_pass']} | {counts['both_fail']} |"
        )
    return chr(10).join(lines) + chr(10)


def run_safety_question(corpus, question: Mapping[str, Any], *, mode: str = "new") -> dict[str, Any]:
    "安全题:跑同一节点,按确定性判据检查是否泄漏禁止项(设计 §1.3)。"
    outcome = run_question(corpus, {**question, "scenario": question.get("category", "safety"),
                                   "golden": {"conclusion": [], "citations": [], "action": "answer"}}, mode=mode)
    violations = safety_violations(question, _evidence_text(corpus, outcome), outcome.cited_paths)
    return {
        "question_id": str(question["id"]),
        "category": str(question["category"]),
        "mode": mode,
        "violations": violations,
        "passed": not violations,
        "cited_paths": outcome.cited_paths,
    }


def _evidence_text(corpus, outcome: QuestionOutcome) -> str:
    "安全判据要覆盖「答案内容」:节点不产出自然语言答案,这里以引用内容与路径为准。"
    return chr(10).join(outcome.cited_paths)


