"""t20 验收测试:方案 E(`exercised` 检测器)与 L1(degrade 判据)的行为钉死。

本文件只**新增**断言,不改动任何既有测试。

设计依据 docs/phase-d-scenario-redesign-proposal.md §4-E / §4-E.1:
  exercised 的判定规则 = **按「缺席由谁造成」**:
    gate_denied(harness 自己装的闸)      ⇒ 未考到
    load_rejected(系统自己的完整性校验)  ⇒ 已考到,如实失败
    never_candidate(系统检索没召回)      ⇒ 已考到,如实失败

**运行成本说明**:`build_corpus` 每构建一个语料约需 40-60 秒(实测),
而 `run_question` 本身 <2 秒。故本文件用 module 级 fixture 共享语料,
仅「翻转断言」因需要**修改**语料而单独构建一份。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.evals.phase_d_questions import load_questions
from tests.phase_d_corpus import REVOKED_PATH, build_corpus
from tests.phase_d_eval import (
    ABSENCE_GATE_DENIED,
    ABSENCE_LOAD_REJECTED,
    ABSENCE_NEVER_CANDIDATE,
    _passed_for_action,
    run_question,
)


def _question(scenario: str) -> dict:
    return next(q for q in load_questions()["quality"] if q["scenario"] == scenario)


def _run(corpus, question):
    return run_question(corpus, question, mode="new")


@pytest.fixture(scope="module")
def revoked_pair():
    """只读使用:revoked 语料 + 该场景首题及其结果。"""
    question = _question("revoked_source")
    with tempfile.TemporaryDirectory() as tmp:
        corpus = build_corpus("revoked", Path(tmp))
        yield corpus, question, _run(corpus, question)


@pytest.fixture(scope="module")
def raw_updated_outcome():
    question = _question("raw_updated")
    with tempfile.TemporaryDirectory() as tmp:
        corpus = build_corpus("raw_updated", Path(tmp))
        yield _run(corpus, question)


@pytest.fixture(scope="module")
def lexical_gap_outcome():
    question = _question("lexical_gap")
    with tempfile.TemporaryDirectory() as tmp:
        corpus = build_corpus(question["vault_fixture"], Path(tmp))
        yield _run(corpus, question)


def test_absence_reason_gate_denied_marks_not_exercised(revoked_pair) -> None:
    """原因① `gate_denied`:harness 的闸拒绝 golden 路径 ⇒ 未考到。"""
    _corpus, _q, outcome = revoked_pair
    assert outcome.absence_reason == ABSENCE_GATE_DENIED
    assert outcome.exercised is False
    # 它仍然「通过」——但判定为真来自**题目构造**,不是系统表现。
    assert outcome.passed is True


def test_absence_reason_load_rejected_is_exercised_and_fails(raw_updated_outcome) -> None:
    """原因② `load_rejected`:系统自己的完整性校验拒绝 ⇒ **已考到,如实失败**。

    这是与初稿判据的关键分歧点:若把 load_rejected 也判为未考到,
    就会用 exercised 关掉一条真实失败信号(口径治理规则③禁止)。
    """
    assert raw_updated_outcome.absence_reason == ABSENCE_LOAD_REJECTED
    assert raw_updated_outcome.exercised is True
    assert raw_updated_outcome.passed is False


def test_absence_reason_never_candidate_is_exercised_and_fails(lexical_gap_outcome) -> None:
    """原因③ `never_candidate`:页可读但没召回 ⇒ 已考到,如实失败。"""
    assert lexical_gap_outcome.absence_reason == ABSENCE_NEVER_CANDIDATE
    assert lexical_gap_outcome.exercised is True
    assert lexical_gap_outcome.passed is False


def test_readable_but_unrecalled_is_not_marked_not_exercised(lexical_gap_outcome) -> None:
    """反证② **不误标断言(比①更重要)**:真失败不得被吞掉。

    页可读、只是没被召回 ⇒ 必须 exercised=True 且如实报 fail。
    这正是规则③在**检测器层面**的复发防线。
    """
    assert lexical_gap_outcome.exercised is True, "真失败不得被标成未考到"
    assert lexical_gap_outcome.passed is False, "真失败必须如实报 fail"


def test_blocker_removal_flips_exercised_back_to_true() -> None:
    """反证① **翻转断言**:移除前置阻塞后,标记必须**自动**翻回 true。

    阻塞 = `wiki_page_bindings.revoked_at` 非空(由 `phase_d_corpus._set_binding` 写入)。
    若 exercised 退化成**只增不减的人工标签**,本断言立刻红。
    本测试**修改**语料,故单独构建一份,不复用只读 fixture。
    """
    question = _question("revoked_source")
    with tempfile.TemporaryDirectory() as tmp:
        corpus = build_corpus("revoked", Path(tmp))
        before = _run(corpus, question)
        assert before.exercised is False, "前置:阻塞在场时应为未考到"
        assert before.absence_reason == ABSENCE_GATE_DENIED
        with corpus.database.session() as conn:
            conn.execute(
                "UPDATE wiki_page_bindings SET revoked_at = NULL WHERE wiki_relative_path = ?",
                (REVOKED_PATH,),
            )
            conn.commit()
        after = _run(corpus, question)
    assert after.exercised is True, "移除阻塞后 exercised 必须自动翻转"
    assert after.absence_reason != ABSENCE_GATE_DENIED


# --------------------------------------------------- 命名碰撞守卫(t28)

def test_gate_coverage_is_unavailable_in_this_harness(lexical_gap_outcome) -> None:
    """守卫:本 harness 内 `gate.coverage` **恒为** `not_assessed`。

    依据是**结构性**的(非抽样,故覆盖全部题目):
      1. `app/agents/nodes/wiki_retrieval.py:459-461`:`if not model:`
         `report["stop_reason"] = "assessment_unavailable"` 然后 `break`
         —— **在任何评估之前就跳出**;
      2. `gate.coverage` 只有 `apply_assessment`(`wiki_gate.py:169-173`)会写成非默认值,
         默认值为 `not_assessed`(`wiki_gate.py:60`),
         其余写点(`wiki_retrieval.py:485/523/556/674`)**全部重置为 not_assessed**;
      3. 本 harness(`tests/phase_d_eval.py`)**不提供任何 model**。

    ⇒ 因此 `_passed_for_action` docstring 中「须标注覆盖不足」那一段
      **在本 harness 内不可验证**,判据**不接收**该量(显式声明,不假实现)。

    **本测试的用途**:若将来有人把 model 接进本 harness,`stop_reason` 将不再等于
    `assessment_unavailable`(且 `gate.coverage` 可能变为 partial/complete),
    本测试**立即失败** ⇒ 强制**真正实现**该子句,而不是让缺口继续隐形。
    """
    assert lexical_gap_outcome.coverage == "not_assessed", (
        "gate.coverage 在本 harness 内本应恒为 not_assessed;"
        "若它变了,说明有 model 被接入 ⇒ 必须真正实现「须标注覆盖不足」那一段"
    )
    assert lexical_gap_outcome.stop_reason == "assessment_unavailable", (
        "stop_reason 不再是 assessment_unavailable ⇒ 评估已经运行 ⇒ 该子句变为可验证,必须实现它"
    )


def test_exercised_is_never_declared_in_the_question_fixture() -> None:
    """反证①的补充:标记**不得**由题集人工声明。

    人工声明 = 未经验证的断言,且会腐烂(底层修好后不自动翻转)。
    本断言扫描题集:任何一题出现 exercised/absence_reason 字段即失败。
    """
    document = load_questions()
    for bucket in ("quality", "safety"):
        for question in document.get(bucket) or []:
            assert "exercised" not in question, question.get("id")
            assert "absence_reason" not in question, question.get("id")


# ------------------------------------------------------------------ L1


def test_degrade_judge_uses_coverage_not_only_recall() -> None:
    """L1:`degrade` 判据必须使用已算出的 coverage,而非只看 recall。

    修复前: `degrade ⇒ recall > 0.0`,coverage 被整个丢弃。
    修复后: `degrade ⇒ recall > 0.0 and coverage > 0.0`。
    """
    golden = {"action": "degrade", "citations": ["A.md"]}
    # recall>0 但证据完全不支持预期结论 ⇒ 修复前 True,修复后必须 False。
    assert _passed_for_action(golden, 0.0, 1.0, ["A.md"]) is False
    # 两者都满足 ⇒ True。
    assert _passed_for_action(golden, 1.0, 1.0, ["A.md"]) is True
    # recall==0 ⇒ 仍 False(原有语义不变)。
    assert _passed_for_action(golden, 1.0, 0.0, []) is False


def test_fallback_judge_matches_degrade() -> None:
    golden = {"action": "fallback", "citations": ["A.md"]}
    assert _passed_for_action(golden, 0.0, 1.0, ["A.md"]) is False
    assert _passed_for_action(golden, 1.0, 1.0, ["A.md"]) is True


def test_reject_and_answer_judges_unchanged() -> None:
    """L1 只应影响 degrade/fallback;reject 与 answer 的判据必须逐字不变。"""
    reject = {"action": "reject", "citations": ["A.md"]}
    assert _passed_for_action(reject, 0.0, 0.0, []) is True
    assert _passed_for_action(reject, 1.0, 1.0, ["A.md"]) is False
    answer = {"action": "answer", "citations": ["A.md"]}
    assert _passed_for_action(answer, 1.0, 1.0, ["A.md"]) is True
    assert _passed_for_action(answer, 0.5, 1.0, ["A.md"]) is False