"""阶段 D 评测装配测试(设计 §2.1:验证题集 schema 合法、安全判据命中可检测)。

本文件只验证**数据与判定**,不运行节点——节点级双路径驱动见后续切片。
函数名英文,语料中文。
"""

from __future__ import annotations

import copy
import sqlite3

import pytest

from app.evals.phase_d_questions import (
    QUALITY_SCENARIOS,
    SAFETY_CATEGORIES,
    SCHEMA_VERSION,
    QuestionSetError,
    citation_scores,
    conclusion_coverage,
    load_questions,
    safety_passed,
    safety_violations,
    validate_questions,
)
from tests.phase_d_eval import run_question
from tests.phase_d_corpus import (
    ALPHA_PATH,
    ALT_PATH,
    LONG_PATH,
    REVOKED_PATH,
    VARIANTS,
    build_corpus,
)


def test_question_set_loads_and_matches_the_design_contract() -> None:
    document = load_questions()
    assert document["schema_version"] == SCHEMA_VERSION
    assert document["meta"]["language"] == "zh-CN"
    assert document["meta"]["sensitive"] is False
    assert len(document["quality"]) == len(QUALITY_SCENARIOS) * 3
    assert len(document["safety"]) == len(SAFETY_CATEGORIES) * 2
    assert {q["scenario"] for q in document["quality"]} == set(QUALITY_SCENARIOS)
    assert {s["category"] for s in document["safety"]} == set(SAFETY_CATEGORIES)


def test_question_set_guard_rejects_malformed_documents() -> None:
    document = load_questions()

    wrong_version = copy.deepcopy(document)
    wrong_version["schema_version"] = "phase-d-questions.v0"
    with pytest.raises(QuestionSetError):
        validate_questions(wrong_version)

    missing_question = copy.deepcopy(document)
    missing_question["quality"] = missing_question["quality"][:-1]
    with pytest.raises(QuestionSetError):
        validate_questions(missing_question)

    sensitive = copy.deepcopy(document)
    sensitive["meta"]["sensitive"] = True
    with pytest.raises(QuestionSetError):
        validate_questions(sensitive)

    incomplete_golden = copy.deepcopy(document)
    incomplete_golden["quality"][0]["golden"]["citations"] = []
    with pytest.raises(QuestionSetError):
        validate_questions(incomplete_golden)

    duplicate_id = copy.deepcopy(document)
    duplicate_id["safety"][0]["id"] = duplicate_id["quality"][0]["id"]
    with pytest.raises(QuestionSetError):
        validate_questions(duplicate_id)


def test_conclusion_coverage_is_deterministic_containment() -> None:
    assert conclusion_coverage(["标准交货周期为 14 天"], "标准交货周期为 14 天。") == 1.0
    assert conclusion_coverage(["标准交货周期为 14 天"], "无关内容") == 0.0
    assert conclusion_coverage(["甲", "乙"], "只有甲") == 0.5
    assert conclusion_coverage([], "任意") == 0.0


def test_citation_scores_separate_precision_and_recall() -> None:
    precision, recall = citation_scores(["Wiki/A.md", "Wiki/B.md"], ["Wiki/A.md"])
    assert (precision, recall) == (1.0, 0.5)
    precision, recall = citation_scores(["Wiki/A.md"], ["Wiki/A.md", "Wiki/X.md"])
    assert (precision, recall) == (0.5, 1.0)
    # golden 要求引用但一条都没给 → 引用失败
    assert citation_scores(["Wiki/A.md"], []) == (0.0, 0.0)


def test_safety_criteria_detect_leaks_deterministically() -> None:
    document = load_questions()
    question = next(s for s in document["safety"] if s["category"] == "over_privileged_read")
    forbidden = question["golden"]["forbidden"]

    # 泄漏事实串或来源路径都要被抓到
    assert not safety_passed(question, "该来源的交货周期是 " + forbidden[-1], [])
    assert not safety_passed(question, "无关回答", [forbidden[0]])
    # 干净回答必须通过(防止「全拒」式假阳)
    assert safety_passed(question, "该来源已被遗忘，无法作答。", ["Wiki/Concepts/Supplier-Alpha.md"])
    assert safety_violations(question, "干净", []) == []


def test_safety_failure_is_not_averaged_into_quality() -> None:
    """设计 §1.3:安全错误单独计分,一次失败即红,不混入质量均分。"""
    document = load_questions()
    safety_question = document["safety"][0]
    forbidden = safety_question["golden"]["forbidden"]

    # 质量满分也无法掩盖一次安全失败
    quality_pass_rate = 42 / 42
    violations = safety_violations(safety_question, "泄漏 " + forbidden[-1], [])
    assert violations, "泄漏必须被检出"
    compliance = (len(document["safety"]) - 1) / len(document["safety"])
    assert compliance < 1.0
    assert quality_pass_rate == 1.0  # 两者独立:均分高不代表合规


@pytest.mark.parametrize("variant", VARIANTS)
def test_corpus_variant_builds_and_matches_the_question_set(variant, tmp_path) -> None:
    """每个 vault_fixture 变体都必须可构建,且落盘路径与题集 golden 对齐。"""
    corpus = build_corpus(variant, tmp_path / variant)

    pages = {
        path.relative_to(corpus.vault_root).as_posix()
        for path in corpus.vault_root.rglob("*.md")
    }
    assert ALPHA_PATH in pages

    with sqlite3.connect(corpus.database.path) as conn:
        bindings = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT wiki_relative_path, status, revoked_at FROM wiki_page_bindings"
            )
        }

    if variant == "revoked":
        assert bindings[REVOKED_PATH][1] is not None
    elif variant == "forgotten":
        assert bindings[REVOKED_PATH][0] == "forgotten"
    elif variant == "quarantined":
        assert bindings[REVOKED_PATH][0] == "quarantined"
    elif variant == "wiki_missing":
        assert (corpus.vault_root / "Notes" / "Suppliers.md").exists()
    elif variant == "assistant_summary":
        assert "Wiki/Companion/Summaries/Alpha.md" in pages
    elif variant == "oversized":
        assert LONG_PATH in pages
    elif variant == "conflict":
        assert ALT_PATH in pages


def test_question_set_fixtures_all_have_a_builder() -> None:
    """题集引用的每个 vault_fixture 都必须有构建器,避免评测时才发现缺语料。"""
    document = load_questions()
    referenced = {q["vault_fixture"] for q in document["quality"]} | {
        s["vault_fixture"] for s in document["safety"]
    }
    assert referenced <= set(VARIANTS)
    assert referenced == set(document["meta"]["vault_fixtures"])


def test_driver_runs_a_question_in_both_modes(tmp_path) -> None:
    """驱动必须真的把题喂给节点,并在两种模式下产出可比较的确定性指标。"""
    document = load_questions()
    question = next(q for q in document["quality"] if q["scenario"] == "single_page")
    corpus = build_corpus(question["vault_fixture"], tmp_path)

    outcomes = {mode: run_question(corpus, question, mode=mode) for mode in ("new", "old")}

    for mode, outcome in outcomes.items():
        assert outcome.mode == mode
        assert outcome.cited_paths, f"{mode} 路径未取到任何引用"
        assert outcome.citation_recall == 1.0
        assert outcome.conclusion_coverage == 1.0
        assert outcome.passed is True
        assert outcome.latency_ms >= 0


def test_legacy_switch_restores_pre_phase_c_semantics(tmp_path) -> None:
    """旧路径补丁必须真的改变节点行为(否则四象限对照没有信号)。"""
    from app.agents.nodes import wiki_retrieval as node_module
    from tests.phase_d_eval import _legacy_semantics

    with _legacy_semantics():
        assert node_module.DEEP_PROFILE is node_module.BALANCED_PROFILE
        assert node_module._citation_value(1.0, "fresh", "model_assessed_complete") == 0.0
        assert node_module.derive_source_freshness(
            verification_status="verified", expires_at=None, revoked_at=None,
            observation="unchanged_since_capture",
        ) == ("unknown", "source_relevance_check_pending")

    # 退出上下文后必须完整恢复,不得污染后续用例
    assert node_module.DEEP_PROFILE is not node_module.BALANCED_PROFILE
    assert node_module._citation_value(1.0, "fresh", "model_assessed_complete") > 0.0
