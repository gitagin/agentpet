from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from app.evals import retrieval_eval
from app.evals.retrieval_eval import (
    EvaluationContractError,
    PRIMARY_SLICE_MINIMUMS,
    _ModeSpec,
    _aggregate_safety,
    _evaluate_final_gates,
    _meaningful_ascii_terms,
    _mrr_at_k,
    _ndcg_at_k,
    _precision_at_k,
    _recall_at_k,
    _strict_mode_success,
    load_corpus,
    run_fts_evaluation,
    run_mode_comparison,
    score_grounding_hooks,
)


DATASET_PATH = Path(__file__).parent / "evals" / "retrieval" / "retrieval-corpus-v1.json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_ARTIFACTS = {
    "artifact-hashes.json",
    "corpus-manifest.md",
    "failure-catalog.md",
    "fts-baseline.json",
    "slice-results.md",
}
VECTOR_EXTRA_UNAVAILABLE = pytest.mark.skipif(
    importlib.util.find_spec("qdrant_client") is None,
    reason="all-mode retrieval evaluation requires the optional vector extra",
)
REQUIRED_COMPARISON_ARTIFACTS = {
    "artifact-hashes.json",
    "latency-and-cost.md",
    "mode-comparison.json",
    "per-slice-quality.md",
    "identity-control.md",
}


def test_frozen_dataset_satisfies_slice_label_and_privacy_contract() -> None:
    corpus = load_corpus(DATASET_PATH)

    assert corpus.schema_version == "retrieval-eval-dataset.v1"
    assert corpus.corpus_version == "agent-pet-retrieval-synthetic-v1.0.0"
    assert corpus.random_seed == 1204
    assert len(corpus.cases) == 60
    assert len({case.case_id for case in corpus.cases}) == 60
    assert Counter(case.primary_slice for case in corpus.cases) == PRIMARY_SLICE_MINIMUMS

    chunks_by_id = corpus.chunks_by_id
    for document in corpus.documents:
        assert document.fixture_source.startswith("synthetic://")
        assert not Path(document.relative_path).is_absolute()
        for chunk in document.chunks:
            assert chunk.chunk_id not in chunk.heading
            assert chunk.chunk_id not in chunk.content
            assert chunk.citation_id not in chunk.heading
            assert chunk.citation_id not in chunk.content

    for case in corpus.cases:
        assert case.fixture_source.startswith("synthetic://")
        assert case.tags
        assert case.rationale
        assert not (set(case.expected_relevant_chunk_ids) & set(case.expected_excluded_chunk_ids))
        assert set(case.expected_relevant_chunk_ids) | set(case.expected_excluded_chunk_ids) <= set(chunks_by_id)
        if case.answer_label == "answerable":
            assert case.expected_relevant_chunk_ids
        else:
            assert not case.expected_relevant_chunk_ids
            assert case.expected_source_scope == "none"


def test_no_ascii_keyword_overlap_slice_has_no_meaningful_ascii_overlap() -> None:
    corpus = load_corpus(DATASET_PATH)
    chunks_by_id = corpus.chunks_by_id

    for case in corpus.cases:
        if case.primary_slice != "no_ascii_keyword_overlap":
            continue
        query_terms = _meaningful_ascii_terms(case.query)
        evidence_terms: set[str] = set()
        for chunk_id in case.expected_relevant_chunk_ids:
            _, chunk, _ = chunks_by_id[chunk_id]
            evidence_terms.update(_meaningful_ascii_terms(f"{chunk.heading} {chunk.content}"))
        assert query_terms.isdisjoint(evidence_terms), (case.case_id, query_terms & evidence_terms)


def test_metric_formulas_use_frozen_denominators_and_binary_relevance() -> None:
    relevant = {"a", "b", "c", "d", "e"}
    retrieved = ["x", "a", "y", "b", "z", "c"]

    assert _recall_at_k(retrieved, relevant, 5) == 2 / 5
    assert _recall_at_k(retrieved, relevant, 10) == 3 / 5
    assert _precision_at_k(retrieved, relevant, 5) == 2 / 5
    assert _mrr_at_k(retrieved, relevant, 10) == 1 / 2
    expected_dcg = (1 / math.log2(3)) + (1 / math.log2(5)) + (1 / math.log2(7))
    ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, 6))
    assert math.isclose(_ndcg_at_k(retrieved, relevant, 10) or 0.0, expected_dcg / ideal_dcg)

    assert _recall_at_k([], set(), 5) is None
    assert _precision_at_k([], set(), 5) is None
    assert _mrr_at_k([], set(), 10) is None
    assert _ndcg_at_k([], set(), 10) is None


def test_grounding_hooks_are_not_evaluated_without_answers_and_score_fixed_observations() -> None:
    corpus = load_corpus(DATASET_PATH)
    empty = score_grounding_hooks(corpus, observations=())
    assert empty["status"] == "not_evaluated"
    assert empty["citation_precision"] is None
    assert empty["local_fact_citation_coverage"] is None
    assert empty["grounded_answer_faithfulness"] is None
    assert empty["final_gate_eligible"] is False

    case = next(case for case in corpus.cases if case.case_id == "EXACT-001")
    relevant_citation = corpus.chunks_by_id[case.expected_relevant_chunk_ids[0]][1].citation_id
    target_observation = {
        "case_id": case.case_id,
        "rendered_citation_ids": [relevant_citation, "citation:unknown"],
        "accepted_citation_ids": [relevant_citation],
        "atomic_claims": [
            {
                "citation_ids": [relevant_citation],
                "supported": True,
                "faithful": True,
            },
            {
                "citation_ids": [],
                "supported": False,
                "faithful": False,
            },
        ],
    }
    partial = score_grounding_hooks(corpus, observations=(target_observation,))
    assert partial["status"] == "incomplete"
    assert partial["final_gate_eligible"] is False
    assert len(partial["missing_case_ids"]) == 59
    assert partial["fabricated_citations"] == 1
    partial_safety = _aggregate_safety([], partial)
    assert partial_safety["fabricated_citations"] == 1
    partial_gates = _evaluate_final_gates(
        metrics={},
        slice_results=(),
        safety=partial_safety,
        grounding_hooks=partial,
        latency={"p95": 0.0, "hard_max": 0.0},
    )
    citation_gate = next(gate for gate in partial_gates if gate["name"] == "citation_precision")
    assert citation_gate["passed"] is False
    assert citation_gate["reason"] == "not evaluated"

    complete_observations = []
    for corpus_case in corpus.cases:
        if corpus_case.case_id == case.case_id:
            complete_observations.append(target_observation)
            continue
        if corpus_case.answer_label == "no_evidence":
            complete_observations.append(
                {
                    "case_id": corpus_case.case_id,
                    "rendered_citation_ids": [],
                    "accepted_citation_ids": [],
                    "atomic_claims": [],
                }
            )
            continue
        citation_id = corpus.chunks_by_id[corpus_case.expected_relevant_chunk_ids[0]][1].citation_id
        complete_observations.append(
            {
                "case_id": corpus_case.case_id,
                "rendered_citation_ids": [citation_id],
                "accepted_citation_ids": [citation_id],
                "atomic_claims": [
                    {
                        "citation_ids": [citation_id],
                        "supported": True,
                        "faithful": True,
                    }
                ],
            }
        )
    scored = score_grounding_hooks(corpus, observations=tuple(complete_observations))

    assert scored["status"] == "evaluated_complete"
    assert scored["final_gate_eligible"] is True
    assert scored["citation_precision"] == 0.99
    assert scored["local_fact_citation_coverage"] == 0.99
    assert scored["grounded_answer_faithfulness"] == 0.99
    assert scored["local_fact_claims_with_empty_evidence"] == 0
    assert scored["fabricated_citations"] == 1

    with pytest.raises(EvaluationContractError, match="duplicate cases"):
        score_grounding_hooks(corpus, observations=(target_observation, target_observation))
    invalid_boolean_observation = {
        **target_observation,
        "atomic_claims": [
            {
                "citation_ids": [relevant_citation],
                "supported": "false",
                "faithful": True,
            }
        ],
    }
    with pytest.raises(EvaluationContractError, match="supported must be a boolean"):
        score_grounding_hooks(corpus, observations=(invalid_boolean_observation,))


def test_fts_baseline_is_isolated_reproducible_and_writes_complete_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trap_database = tmp_path / "must-not-use-default.sqlite3"
    monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(trap_database))
    work_a = tmp_path / "work-a"
    work_b = tmp_path / "work-b"
    output_a = tmp_path / "output-a"
    output_b = tmp_path / "output-b"

    report_a = run_fts_evaluation(
        dataset_path=DATASET_PATH,
        work_dir=work_a,
        output_dir=output_a,
        run_count=1,
        require_final_gates=False,
    )
    report_b = run_fts_evaluation(
        dataset_path=DATASET_PATH,
        work_dir=work_b,
        output_dir=output_b,
        run_count=1,
        require_final_gates=True,
    )

    assert not trap_database.exists()
    assert report_a["configuration"]["requested_mode"] == "fts"
    assert report_a["configuration"]["effective_mode"] == "fts"
    assert report_a["configuration"]["completed_channels"] == ["fts"]
    assert report_a["configuration"]["fallback_used"] is False
    assert report_a["environment"]["external_request_count"] == 0
    assert report_a["environment"]["transmitted_bytes"] == 0
    assert report_a["environment"]["external_cost_usd"] == 0.0
    assert report_a["corpus"]["case_count"] == 60
    assert len(report_a["slice_results"]) == len(PRIMARY_SLICE_MINIMUMS)
    assert report_a["grounding_hooks"]["status"] == "not_evaluated"
    assert report_a["final_gates"]["requested"] is False
    assert report_a["final_gates"]["passed"] is False
    assert report_b["final_gates"]["requested"] is True
    assert report_b["final_gates"]["passed"] is False
    assert report_a["metrics"] == report_b["metrics"]
    assert report_a["safety"] == report_b["safety"]
    assert report_a["input_hashes"] == report_b["input_hashes"]
    assert _quality_signature(report_a) == _quality_signature(report_b)

    slices = {result["primary_slice"]: result for result in report_a["slice_results"]}
    assert slices["exact_keyword_identifier"]["recall_at_10"] == 1.0
    assert (slices["no_ascii_keyword_overlap"]["recall_at_10"] or 0.0) < 0.05
    assert slices["permission_inactive_sensitive"]["no_evidence_accuracy"] == 1.0
    assert report_a["failure_count"] > 0
    assert report_a["latency"]["warmup_query_count"] == 3
    assert report_a["latency"]["measurement_count"] == 60
    assert set(path.name for path in output_a.iterdir()) == REQUIRED_ARTIFACTS

    runtime_ids_a = _runtime_chunk_ids(next(work_a.iterdir()) / "retrieval-eval.sqlite3")
    runtime_ids_b = _runtime_chunk_ids(next(work_b.iterdir()) / "retrieval-eval.sqlite3")
    assert len(runtime_ids_a) == len(runtime_ids_b) == 120
    assert runtime_ids_a.isdisjoint(runtime_ids_b)
    assert all(
        citation_id.startswith("citation:agent-pet-retrieval-v1:chunk-")
        for result in report_a["case_results"]
        for citation_id in result["candidate_citation_ids"]
    )

    artifact_manifest = json.loads((output_a / "artifact-hashes.json").read_text(encoding="utf-8"))
    for filename, expected_hash in artifact_manifest["artifacts"].items():
        actual_hash = hashlib.sha256((output_a / filename).read_bytes()).hexdigest()
        assert actual_hash == expected_hash
    failure_catalog = (output_a / "failure-catalog.md").read_text(encoding="utf-8")
    assert "TASK-1205" in failure_catalog
    assert "TASK-1207" not in failure_catalog

    monkeypatch.setattr(retrieval_eval, "run_fts_evaluation", lambda **_: report_a)
    cli_args = [
        "--dataset",
        str(DATASET_PATH),
        "--work-dir",
        str(tmp_path / "unused-work"),
        "--output-dir",
        str(tmp_path / "unused-output"),
    ]
    assert retrieval_eval.main(cli_args) == 0
    assert retrieval_eval.main([*cli_args, "--require-final-gates"]) == 2


def _quality_signature(report: dict) -> list[tuple]:
    return [
        (
            result["case_id"],
            tuple(result["retrieved_chunk_ids"]),
            result["recall_at_5"],
            result["recall_at_10"],
            result["precision_at_5"],
            result["mrr_at_10"],
            result["ndcg_at_10"],
            result["no_evidence_correct"],
            tuple(result["excluded_hits"]),
        )
        for result in report["case_results"]
    ]


def _runtime_chunk_ids(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("SELECT id FROM note_chunks").fetchall()
    return {str(row[0]) for row in rows}


@VECTOR_EXTRA_UNAVAILABLE
def test_all_mode_comparison_uses_one_snapshot_reports_every_stage_and_defers_reranker(
    tmp_path: Path,
) -> None:
    report = run_mode_comparison(
        dataset_path=DATASET_PATH,
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "output",
        run_count=1,
    )

    assert report["schema_version"] == "retrieval-mode-comparison.v2"
    assert list(report["modes"]) == [
        "fts",
        "vector",
        "hybrid_rrf",
        "hybrid_rrf_identity_control",
    ]
    shared_hash = report["shared_invariants_sha256"]
    expected_case_ids = [case.case_id for case in load_corpus(DATASET_PATH).cases]
    for mode_id, mode in report["modes"].items():
        assert mode["shared_invariants_sha256"] == shared_hash
        assert [result["case_id"] for result in mode["case_results"]] == expected_case_ids
        expected_atom_gate_fallbacks = 0 if mode_id == "fts" else 8
        assert mode["errors"]["strict_channel_failure_count"] == expected_atom_gate_fallbacks
        assert mode["errors"]["fallback_count"] == expected_atom_gate_fallbacks
        assert {
            failure["reason"] for failure in mode["errors"]["strict_channel_failures"]
        } <= {"vector_candidates_rejected"}
        assert mode["safety"]["inaccessible_memory_leakage"] == 0
        assert mode["cost"] == {
            "external_request_count": 0,
            "transmitted_bytes": 0,
            "external_cost_usd": 0.0,
            "provider_usage": None,
            "provider_unit_price": None,
        }
        assert set(mode["latency"]["stages"]) == {
            "embedding",
            "filter_fusion_dedupe",
            "fts_search",
            "reranker",
            "total",
            "vector_adapter_residual",
            "vector_local_search",
        }
        assert all(
            stage["measurement_count"] == 60
            for stage in mode["latency"]["stages"].values()
        )
    assert report["modes"]["hybrid_rrf"]["metrics"] == report["modes"][
        "hybrid_rrf_identity_control"
    ]["metrics"]
    assert report["identity_control"]["status"] == "diagnostic_only"
    assert report["identity_control"]["adoption_eligible"] is False
    assert report["identity_control"]["ndcg_delta"] == 0.0
    assert report["final_gates"]["status"] == "aspirational"
    assert report["selected_default"]["agent_mode"] == "fts"
    assert set(path.name for path in (tmp_path / "output").iterdir()) == REQUIRED_COMPARISON_ARTIFACTS

    manifest = json.loads((tmp_path / "output" / "artifact-hashes.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "retrieval-eval-artifact-hashes.v3"
    for filename, expected_hash in manifest["artifacts"].items():
        assert hashlib.sha256((tmp_path / "output" / filename).read_bytes()).hexdigest() == expected_hash


@VECTOR_EXTRA_UNAVAILABLE
def test_all_mode_vector_fixture_never_receives_gold_ids_or_rationales_and_is_reproducible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_text: list[str] = []
    real_feature_hash = retrieval_eval._feature_hash_vector

    def capture(text: str, *, dimensions: int):
        captured_text.append(text)
        return real_feature_hash(text, dimensions=dimensions)

    monkeypatch.setattr(retrieval_eval, "_feature_hash_vector", capture)
    first = run_mode_comparison(
        dataset_path=DATASET_PATH,
        work_dir=tmp_path / "work-a",
        output_dir=tmp_path / "output-a",
        run_count=1,
    )
    second = run_mode_comparison(
        dataset_path=DATASET_PATH,
        work_dir=tmp_path / "work-b",
        output_dir=tmp_path / "output-b",
        run_count=1,
    )
    corpus = load_corpus(DATASET_PATH)

    assert captured_text
    assert all(case.rationale not in captured_text for case in corpus.cases)
    assert all(chunk_id not in "\n".join(captured_text) for chunk_id in corpus.chunks_by_id)
    for mode_id in first["modes"]:
        assert _quality_signature(first["modes"][mode_id]) == _quality_signature(
            second["modes"][mode_id]
        ), mode_id
    assert first["comparisons"] == second["comparisons"]
    assert first["identity_control"] == second["identity_control"]


def test_strict_mode_contract_rejects_fallback_results() -> None:
    vector = _ModeSpec("vector", "vector", ("vector",))
    success, reason = _strict_mode_success(
        {
            "completed_channels": ["fts"],
            "effective_mode": "fts",
            "fallback_reason": "qdrant_unavailable",
        },
        vector,
    )

    assert success is False
    assert reason == "required_channel_missing"

