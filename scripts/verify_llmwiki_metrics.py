"""Run the evidence-gated LLM Wiki evaluation from production retrieval code."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evals.retrieval_eval import (  # noqa: E402
    EvaluationContractError,
    run_fts_evaluation,
)
from app.evals.llmwiki_graph_eval import (  # noqa: E402
    GraphEvaluationContractError,
    run_graph_evaluation,
)


EVALUATOR_VERSION = "llmwiki-metrics-eval.v3"
THRESHOLD_VERSION = "llmwiki-gates.v1"
DEFAULT_GRAPH_FIXTURE = (
    BACKEND_ROOT / "tests" / "evals" / "llmwiki" / "graph-lifecycle-v1.json"
)
EXIT_PASSED = 0
EXIT_THRESHOLD_FAILURE = 1
EXIT_INSUFFICIENT_SAMPLE = 2
EXIT_INVALID_INPUT = 3

FROZEN_THRESHOLDS: dict[str, dict[str, object]] = {
    "retrieval_recall_at_5": {
        "comparator": "gte",
        "value": 0.8,
        "minimum_sample": 20,
        "required": True,
    },
    "citation_coverage": {
        "comparator": "gte",
        "value": 0.95,
        "minimum_sample": 20,
        "required": True,
    },
    "no_evidence_accuracy": {
        "comparator": "gte",
        "value": 1.0,
        "minimum_sample": 10,
        "required": True,
    },
    "false_activation": {
        "comparator": "lte",
        "value": 0.0,
        "minimum_sample": 10,
        "required": True,
    },
    "correction_propagation": {
        "comparator": "gte",
        "value": 1.0,
        "minimum_sample": 20,
        "required": True,
    },
}


def _metric(
    numerator: int | float,
    denominator: int,
    *,
    evidence_status: str | None = None,
) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
        "value": numerator / denominator if denominator else None,
        "evidence_status": evidence_status or ("sufficient" if denominator else "insufficient_sample"),
    }


def _empty_metric() -> dict[str, object]:
    return _metric(0, 0, evidence_status="insufficient_sample")


def _apply_threshold(name: str, metric: dict[str, object]) -> None:
    threshold = FROZEN_THRESHOLDS[name]
    minimum_sample = int(threshold["minimum_sample"])
    value = metric.get("value")
    sample_size = int(metric.get("sample_size") or 0)
    metric.update(
        {
            "threshold": threshold["value"],
            "comparator": threshold["comparator"],
            "minimum_sample": minimum_sample,
            "required": bool(threshold["required"]),
        }
    )
    if value is None or sample_size < minimum_sample:
        metric["status"] = "insufficient_sample"
        return
    numeric_value = float(value)
    target = float(threshold["value"])
    comparator = str(threshold["comparator"])
    passed = numeric_value >= target if comparator == "gte" else numeric_value <= target
    metric["status"] = "passed" if passed else "failed"


def _production_fts_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    cases = [item for item in report.get("case_results", []) if isinstance(item, Mapping)]
    answerable = [item for item in cases if item.get("answer_label") == "answerable"]
    no_evidence = [item for item in cases if item.get("answer_label") == "no_evidence"]
    recall_sum = sum(float(item.get("recall_at_5") or 0.0) for item in answerable)
    no_evidence_correct = sum(bool(item.get("no_evidence_correct")) for item in no_evidence)
    false_activations = len(no_evidence) - no_evidence_correct
    grounding = report.get("grounding_hooks")
    citation_value = (
        grounding.get("local_fact_citation_coverage")
        if isinstance(grounding, Mapping)
        else None
    )
    citation_observations = (
        int(grounding.get("observation_case_count") or 0)
        if isinstance(grounding, Mapping)
        else 0
    )
    citation = (
        _metric(float(citation_value) * citation_observations, citation_observations)
        if citation_value is not None and citation_observations
        else _empty_metric()
    )
    baseline = {
        "name": "production_sqlite_fts",
        "retrieval_recall_at_5": _metric(recall_sum, len(answerable)),
        "citation_coverage": citation,
        "no_evidence_accuracy": _metric(no_evidence_correct, len(no_evidence)),
        "false_activation": _metric(false_activations, len(no_evidence)),
        "latency_ms": {
            "p50": report.get("latency", {}).get("p50"),
            "p95": report.get("latency", {}).get("p95"),
            "hard_max": report.get("latency", {}).get("hard_max"),
            "sample_size": report.get("latency", {}).get("measurement_count", 0),
            "evidence_status": "synthetic_fixture_only",
        },
    }
    for name in (
        "retrieval_recall_at_5",
        "citation_coverage",
        "no_evidence_accuracy",
        "false_activation",
    ):
        _apply_threshold(name, baseline[name])
    return {
        "case_count": len(cases),
        "answerable_cases": len(answerable),
        "no_evidence_cases": len(no_evidence),
        "baseline": baseline,
    }


def _evaluate(
    fixture: Path,
    production_output: Path,
    *,
    graph_fixture: Path,
    graph_output: Path,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="llmwiki-metrics-eval-") as temp_name:
        temp_root = Path(temp_name)
        report = run_fts_evaluation(
            dataset_path=fixture,
            work_dir=temp_root / "work",
            output_dir=temp_root / "production-fts",
            run_count=1,
            require_final_gates=True,
        )
        graph_report = run_graph_evaluation(
            fixture_path=graph_fixture,
            work_dir=temp_root / "graph-work",
            output_dir=temp_root / "graph",
        )
        if production_output.exists():
            shutil.rmtree(production_output)
        production_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(temp_root / "production-fts", production_output)
        if graph_output.exists():
            shutil.rmtree(graph_output)
        graph_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(temp_root / "graph", graph_output)

    results = _production_fts_metrics(report)
    graph_correction = graph_report["lifecycle"]["correction_propagation"]
    correction = _metric(
        graph_correction["numerator"],
        graph_correction["denominator"],
        evidence_status=str(graph_correction["evidence_status"]),
    )
    _apply_threshold("correction_propagation", correction)
    results.update(
        {
            "production_evaluator": {
                "module": "app.evals.retrieval_eval",
                "evaluator_version": report.get("evaluator_version"),
                "run_id": report.get("run_id"),
                "configuration_sha256": report.get("input_hashes", {}).get("configuration_sha256"),
                "production_retrieval_sha256": report.get("input_hashes", {}).get(
                    "production_retrieval_sha256"
                ),
                "final_gates_passed": report.get("final_gates", {}).get("passed") is True,
                "failure_count": report.get("failure_count"),
            },
            "graph_evaluator": {
                "module": "app.evals.llmwiki_graph_eval",
                "evaluator_version": graph_report.get("evaluator_version"),
                "configuration_sha256": graph_report.get("configuration_sha256"),
                "evaluator_sha256": graph_report.get("input_hashes", {}).get("evaluator_sha256"),
                "fixture_sha256": graph_report.get("fixture", {}).get("sha256"),
                "status": graph_report.get("status"),
            },
            "channels": {
                "sqlite_fts": {
                    "status": "passed"
                    if report.get("final_gates", {}).get("passed") is True
                    else "failed",
                    "evidence_status": "synthetic_fixture_only",
                    "sample_size": len(report.get("case_results", [])),
                },
                "sqlite_graph": graph_report["channels"]["sqlite_graph"],
                "kuzu_acceleration": graph_report["channels"]["kuzu_acceleration"],
                "sqlite_graph_fallback": graph_report["channels"]["sqlite_graph_fallback"],
            },
            "ablation": {
                "name": "deterministic_vs_llm_extraction_synthesis",
                "status": "partial",
                "evidence_status": "insufficient_sample",
                "deterministic_sqlite_graph": graph_report["ablation"][
                    "deterministic_sqlite_graph"
                ],
                "llm_extraction_synthesis": graph_report["ablation"][
                    "llm_extraction_synthesis"
                ],
            },
            "lifecycle_metrics": {
                "correction_propagation": correction,
                "lookup_duration": _empty_metric(),
                "confirmation_burden": _empty_metric(),
                "wiki_reuse": _empty_metric(),
            },
        }
    )
    return results


def _overall_status(results: Mapping[str, Any]) -> tuple[str, int]:
    metrics = [
        metric
        for metric in results["baseline"].values()
        if isinstance(metric, Mapping) and metric.get("required") is True
    ]
    metrics.append(results["lifecycle_metrics"]["correction_propagation"])
    if any(metric.get("status") == "failed" for metric in metrics):
        return "failed", EXIT_THRESHOLD_FAILURE
    if any(metric.get("status") == "insufficient_sample" for metric in metrics):
        return "insufficient_sample", EXIT_INSUFFICIENT_SAMPLE
    if any(channel.get("status") == "not_run" for channel in results["channels"].values()):
        return "insufficient_sample", EXIT_INSUFFICIENT_SAMPLE
    if results["ablation"].get("status") != "passed":
        return "insufficient_sample", EXIT_INSUFFICIENT_SAMPLE
    return "passed", EXIT_PASSED


def _display_value(value: object) -> str:
    if value is None:
        return "insufficient"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _markdown(report: Mapping[str, Any]) -> str:
    results = report["results"]
    baseline = results["baseline"]
    lines = [
        "# LLM Wiki fixture metrics",
        "",
        f"- status: `{report['status']}`",
        f"- exit_code: `{report['exit_code']}`",
        f"- evaluator: `{report['evaluator_version']}`",
        f"- production evaluator: `{results['production_evaluator']['module']}`",
        f"- production evaluator version: `{results['production_evaluator']['evaluator_version']}`",
        f"- threshold_version: `{report['threshold_version']}`",
        f"- corpus: `{report['corpus_version']}`",
        f"- cases: `{results['case_count']}`",
        "- privacy: the summary contains counts, hashes and fixed labels; source text is not emitted.",
        "",
        "| Metric | Numerator | Denominator | Value | Threshold | Status | Evidence |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for name in (
        "retrieval_recall_at_5",
        "citation_coverage",
        "no_evidence_accuracy",
        "false_activation",
    ):
        metric = baseline[name]
        threshold = metric.get("threshold")
        comparator = metric.get("comparator", "")
        threshold_text = f"{comparator} {_display_value(threshold)}" if threshold is not None else "-"
        lines.append(
            f"| {name} | {_display_value(metric['numerator'])} | {metric['denominator']} | "
            f"{_display_value(metric['value'])} | {threshold_text} | {metric['status']} | "
            f"{metric['evidence_status']} |"
        )
    lines.extend(
        [
            "",
            "## Evidence boundaries",
            "",
            "SQLite graph, Kuzu acceleration and a removed-projection SQLite fallback are measured "
            "on the versioned synthetic graph fixture. LLM extraction/synthesis remains `not_run`; "
            "correction propagation remains below its frozen minimum sample. Synthetic evidence is "
            "not a substitute for a 7-day trial or 24-hour soak.",
        ]
    )
    return "\n".join(lines) + "\n"


def _configuration_hash(
    *,
    fixture_hash: str,
    graph_fixture_hash: str,
    production_hash: object,
    graph_evaluator_hash: object,
) -> str:
    payload = {
        "evaluator_version": EVALUATOR_VERSION,
        "threshold_version": THRESHOLD_VERSION,
        "thresholds": FROZEN_THRESHOLDS,
        "fixture_sha256": fixture_hash,
        "graph_fixture_sha256": graph_fixture_hash,
        "production_retrieval_sha256": production_hash,
        "graph_evaluator_sha256": graph_evaluator_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_report(output: Path, report: Mapping[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(_markdown(report), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--graph-fixture", type=Path, default=DEFAULT_GRAPH_FIXTURE)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        raw = args.fixture.read_bytes()
        fixture_hash = hashlib.sha256(raw).hexdigest()
        graph_raw = args.graph_fixture.read_bytes()
        graph_fixture_hash = hashlib.sha256(graph_raw).hexdigest()
        results = _evaluate(
            args.fixture.resolve(),
            args.out / "production-fts",
            graph_fixture=args.graph_fixture.resolve(),
            graph_output=args.out / "graph-lifecycle",
        )
        status, exit_code = _overall_status(results)
        report = {
            "schema_version": "llmwiki-evaluation-report.v3",
            "evaluator_version": EVALUATOR_VERSION,
            "threshold_version": THRESHOLD_VERSION,
            "thresholds": FROZEN_THRESHOLDS,
            "status": status,
            "exit_code": exit_code,
            "corpus_version": str(
                json.loads(raw.decode("utf-8")).get("corpus_version") or "unknown"
            ),
            "fixture_sha256": fixture_hash,
            "graph_fixture_sha256": graph_fixture_hash,
            "configuration_sha256": _configuration_hash(
                fixture_hash=fixture_hash,
                graph_fixture_hash=graph_fixture_hash,
                production_hash=results["production_evaluator"]["production_retrieval_sha256"],
                graph_evaluator_hash=results["graph_evaluator"]["configuration_sha256"],
            ),
            "results": results,
        }
        _write_report(args.out, report)
        print(
            json.dumps(
                {
                    "status": status,
                    "exit_code": exit_code,
                    "out": str(args.out),
                    "sample_size": results["case_count"],
                    "production_evaluator": results["production_evaluator"]["module"],
                },
                ensure_ascii=True,
            )
        )
        return exit_code
    except (
        EvaluationContractError,
        GraphEvaluationContractError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "invalid_input",
                    "exit_code": EXIT_INVALID_INPUT,
                    "error": type(exc).__name__,
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return EXIT_INVALID_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
