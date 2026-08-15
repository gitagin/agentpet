from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app.evals.llmwiki_graph_eval import (
    DATASET_SCHEMA_VERSION,
    EVALUATOR_VERSION,
    REQUIRED_LIFECYCLE_TAGS,
    GraphEvaluationContractError,
    load_graph_fixture,
    run_graph_evaluation,
)


FIXTURE_PATH = Path(__file__).parent / "evals" / "llmwiki" / "graph-lifecycle-v1.json"


@pytest.fixture(scope="module")
def graph_report(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, object], Path]:
    root = tmp_path_factory.mktemp("llmwiki-graph-eval")
    output = root / "output"
    report = run_graph_evaluation(
        fixture_path=FIXTURE_PATH,
        work_dir=root / "work",
        output_dir=output,
    )
    return report, output


def test_graph_fixture_is_versioned_synthetic_and_covers_required_cases() -> None:
    fixture = load_graph_fixture(FIXTURE_PATH)

    assert fixture["schema_version"] == DATASET_SCHEMA_VERSION
    assert fixture["corpus_version"] == "llmwiki-graph-lifecycle-synthetic-v1.0.0"
    groups = Counter(case["group"] for case in fixture["cases"])
    assert groups["lifecycle"] >= 20
    assert groups["no_evidence"] >= 10
    lifecycle_tags = {
        tag
        for case in fixture["cases"]
        if case["group"] == "lifecycle"
        for tag in case["tags"]
    }
    assert REQUIRED_LIFECYCLE_TAGS <= lifecycle_tags


def test_graph_fixture_rejects_an_unproven_no_evidence_success(tmp_path: Path) -> None:
    fixture = load_graph_fixture(FIXTURE_PATH)
    no_evidence = next(case for case in fixture["cases"] if case["group"] == "no_evidence")
    no_evidence["expected"] = ["claim_active"]
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(GraphEvaluationContractError, match="cannot expect"):
        load_graph_fixture(invalid)


def test_sqlite_kuzu_and_missing_projection_fallback_are_equivalent(
    graph_report: tuple[dict[str, object], Path],
) -> None:
    report, output = graph_report
    channels = report["channels"]

    assert report["evaluator_version"] == EVALUATOR_VERSION
    assert re.fullmatch(r"[0-9a-f]{64}", report["configuration_sha256"])
    assert channels["sqlite_graph"]["status"] == "passed"
    assert channels["sqlite_graph"]["sample_size"] >= 20
    assert channels["sqlite_graph_fallback"]["status"] == "passed"
    assert channels["sqlite_graph_fallback"]["fallback_reasons"] == {
        "kuzu_generation_missing": channels["sqlite_graph_fallback"]["sample_size"]
    }
    assert report["equivalence"]["sqlite_vs_fallback_equal"] is True
    if importlib.util.find_spec("kuzu") is None:
        assert channels["kuzu_acceleration"]["status"] == "not_run"
        assert report["equivalence"]["sqlite_vs_kuzu_equal"] is None
    else:
        assert channels["kuzu_acceleration"]["status"] == "passed"
        assert report["equivalence"]["sqlite_vs_kuzu_equal"] is True

    assert (output / "graph-report.json").is_file()
    assert (output / "graph-report.md").is_file()
    assert (output / "artifact-hashes.json").is_file()


def test_lifecycle_and_no_evidence_metrics_keep_synthetic_boundaries(
    graph_report: tuple[dict[str, object], Path],
) -> None:
    report, _ = graph_report

    assert report["lifecycle"]["status"] == "passed"
    assert report["lifecycle"]["sample_size"] >= 20
    assert report["lifecycle"]["correction_propagation"] == {
        "numerator": 3,
        "denominator": 3,
        "sample_size": 3,
        "value": 1.0,
        "evidence_status": "synthetic_fixture_only",
    }
    assert all(item["passed"] for item in report["lifecycle"]["operation_invariants"])
    assert report["no_evidence"]["numerator"] == 10
    assert report["no_evidence"]["denominator"] == 10
    assert report["no_evidence"]["false_activation_numerator"] == 0

    ablation = report["ablation"]
    assert ablation["status"] == "partial"
    assert ablation["deterministic_sqlite_graph"]["model_call_count"] == 0
    assert ablation["deterministic_sqlite_graph"]["estimated_cost_usd"] == 0.0
    assert ablation["llm_extraction_synthesis"]["status"] == "not_run"
    assert ablation["llm_extraction_synthesis"]["sample_size"] == 0


def test_missing_kuzu_is_insufficient_while_sqlite_fallback_still_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.memory_graph_kuzu as kuzu_module

    def missing_kuzu():
        raise ImportError("synthetic missing dependency")

    monkeypatch.setattr(kuzu_module, "_load_kuzu", missing_kuzu)
    report = run_graph_evaluation(
        fixture_path=FIXTURE_PATH,
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
    )

    assert report["status"] == "insufficient_sample"
    assert report["channels"]["kuzu_acceleration"]["status"] == "not_run"
    assert report["channels"]["sqlite_graph_fallback"]["status"] == "passed"
    assert report["equivalence"]["status"] == "insufficient_sample"
    assert report["equivalence"]["sqlite_vs_kuzu_equal"] is None


def test_graph_report_does_not_emit_fixture_queries_or_source_text(
    graph_report: tuple[dict[str, object], Path],
) -> None:
    report, output = graph_report
    serialized = (output / "graph-report.json").read_text(encoding="utf-8")

    assert "synthetic evidence for" not in serialized
    assert '"source_text"' not in serialized
    assert '"query"' not in serialized
    assert re.search(r"[A-Za-z]:[\\/]", serialized) is None
    assert all("case_id" in case and "actual" in case for case in report["case_results"])
