from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.reranking import (
    MAX_RERANK_CANDIDATES,
    DisabledReranker,
    RerankerResponse,
    apply_reranker,
    evaluate_reranker_adoption,
)
from app.services.retrieval_fusion import FusedCandidate, FusionContribution


def _fused(stable_id: str, rank: int) -> FusedCandidate:
    return FusedCandidate(
        stable_id=stable_id,
        content_hash=f"hash-{stable_id}",
        source_scope="vault_note",
        payload={"stable_id": stable_id, "private_excerpt": f"private-{stable_id}"},
        score=1 / (60 + rank),
        best_rank=rank,
        contributions=(FusionContribution(channel="fts", rank=rank, component=1 / (60 + rank)),),
    )


@dataclass
class StubReranker:
    response: RerankerResponse | None = None
    error: Exception | None = None
    name: str = "stub"
    enabled: bool = True
    is_remote: bool = False

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...], float]] = []

    def rerank(self, *, query: str, candidates, timeout_seconds: float):
        self.calls.append((query, tuple(candidate.stable_id for candidate in candidates), timeout_seconds))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def test_disabled_reranker_is_exact_zero_cost_fallback() -> None:
    candidates = tuple(_fused(f"id-{index}", index + 1) for index in range(5))

    outcome = apply_reranker(
        query="private query",
        candidates=candidates,
        reranker=DisabledReranker(),
    )

    assert outcome.candidates == candidates
    assert outcome.status == "disabled"
    assert outcome.reranker_name == "disabled"
    assert outcome.latency_ms == 0.0
    assert outcome.external_request_count == 0
    assert outcome.transmitted_bytes == 0
    assert outcome.external_cost_usd == 0.0
    assert outcome.provider_error_count == 0


def test_remote_reranker_is_blocked_before_private_query_or_candidates_are_sent() -> None:
    candidates = tuple(_fused(f"id-{index}", index + 1) for index in range(3))
    remote = StubReranker(
        response=RerankerResponse(ordered_ids=tuple(reversed([candidate.stable_id for candidate in candidates]))),
        is_remote=True,
    )

    outcome = apply_reranker(
        query="private query marker",
        candidates=candidates,
        reranker=remote,
        remote_provider_approved=False,
    )

    assert remote.calls == []
    assert outcome.candidates == candidates
    assert outcome.status == "privacy_blocked"
    assert outcome.fallback_reason == "remote_reranker_not_approved"
    assert outcome.external_request_count == 0
    assert outcome.transmitted_bytes == 0


def test_reranker_can_only_reorder_first_twenty_and_reports_usage() -> None:
    candidates = tuple(_fused(f"id-{index:02d}", index + 1) for index in range(25))
    head_ids = tuple(candidate.stable_id for candidate in candidates[:MAX_RERANK_CANDIDATES])
    local = StubReranker(
        response=RerankerResponse(
            ordered_ids=tuple(reversed(head_ids)),
            external_request_count=0,
            transmitted_bytes=0,
            external_cost_usd=0.0,
        )
    )

    outcome = apply_reranker(query="query", candidates=candidates, reranker=local)

    assert local.calls == [("query", head_ids, 3.0)]
    assert [candidate.stable_id for candidate in outcome.candidates[:MAX_RERANK_CANDIDATES]] == list(
        reversed(head_ids)
    )
    assert outcome.candidates[MAX_RERANK_CANDIDATES:] == candidates[MAX_RERANK_CANDIDATES:]
    assert outcome.status == "applied"


@pytest.mark.parametrize(
    ("response", "error", "reason"),
    [
        (RerankerResponse(ordered_ids=("id-0",)), None, "reranker_failed"),
        (RerankerResponse(ordered_ids=("id-0", "id-0", "id-2")), None, "reranker_failed"),
        (RerankerResponse(ordered_ids=("id-0", "id-1", "unknown")), None, "reranker_failed"),
        (None, RuntimeError("provider detail must stay private"), "reranker_failed"),
        (None, TimeoutError("late"), "reranker_timeout"),
    ],
)
def test_invalid_error_and_timeout_outputs_fall_back_to_original_rrf_order(
    response: RerankerResponse | None,
    error: Exception | None,
    reason: str,
) -> None:
    candidates = tuple(_fused(f"id-{index}", index + 1) for index in range(3))
    reranker = StubReranker(response=response, error=error)

    outcome = apply_reranker(query="query", candidates=candidates, reranker=reranker)

    assert outcome.candidates == candidates
    assert outcome.status == "failed"
    assert outcome.fallback_reason == reason
    assert "provider detail" not in str(outcome)


def test_local_reranking_is_deterministic_for_identical_inputs() -> None:
    candidates = tuple(_fused(f"id-{index}", index + 1) for index in range(4))
    order = tuple(candidate.stable_id for candidate in (candidates[1], candidates[0], *candidates[2:]))
    reranker = StubReranker(response=RerankerResponse(ordered_ids=order))

    first = apply_reranker(query="query", candidates=candidates, reranker=reranker)
    second = apply_reranker(query="query", candidates=candidates, reranker=reranker)

    assert first.candidates == second.candidates
    assert [candidate.stable_id for candidate in first.candidates] == list(order)


def test_disabled_noop_reranker_is_deferred_by_fixed_adoption_gate() -> None:
    decision = evaluate_reranker_adoption(
        candidate_enabled=False,
        baseline_ndcg=0.8,
        candidate_ndcg=0.8,
        baseline_recall=0.9,
        candidate_recall=0.9,
        paired_ndcg_deltas=(0.0,) * 50,
        safety_violation_count=0,
        reranker_p95_ms=0.0,
        reranker_hard_max_ms=0.0,
        hybrid_total_p95_ms=0.0,
        hybrid_total_hard_max_ms=0.0,
    )

    assert decision.decision == "defer"
    assert decision.bootstrap_ci_lower == 0.0
    assert decision.bootstrap_ci_upper == 0.0
    assert decision.reasons == ("candidate_disabled", "quality_delta_below_threshold")


def test_reranker_adoption_requires_quality_recall_ci_safety_latency_cost_and_gate() -> None:
    passing = evaluate_reranker_adoption(
        candidate_enabled=True,
        baseline_ndcg=0.80,
        candidate_ndcg=0.86,
        baseline_recall=0.92,
        candidate_recall=0.91,
        paired_ndcg_deltas=(0.04, 0.06, 0.08) * 20,
        safety_violation_count=0,
        reranker_p95_ms=100.0,
        reranker_hard_max_ms=200.0,
        hybrid_total_p95_ms=300.0,
        hybrid_total_hard_max_ms=400.0,
        bootstrap_samples=1_000,
    )
    assert passing.decision == "adopt"
    assert passing.reasons == ()
    assert (passing.bootstrap_ci_lower or 0.0) >= 0.0

    blocked_external = evaluate_reranker_adoption(
        candidate_enabled=True,
        baseline_ndcg=0.80,
        candidate_ndcg=0.86,
        baseline_recall=0.92,
        candidate_recall=0.91,
        paired_ndcg_deltas=(0.04, 0.06, 0.08) * 20,
        safety_violation_count=1,
        reranker_p95_ms=1_600.0,
        reranker_hard_max_ms=3_100.0,
        hybrid_total_p95_ms=4_600.0,
        hybrid_total_hard_max_ms=7_100.0,
        is_external=True,
        human_gate_approved=False,
        external_mean_cost_usd=None,
        bootstrap_samples=1_000,
    )
    assert blocked_external.decision == "defer"
    assert set(blocked_external.reasons) >= {
        "safety_gate_failed",
        "latency_gate_failed",
        "hybrid_total_latency_gate_failed",
        "human_gate_not_approved",
        "external_cost_unknown",
    }


def test_cooperative_reranker_timeout_falls_back_without_usage_claims() -> None:
    candidates = tuple(_fused(f"id-{index}", index + 1) for index in range(3))

    class TimeoutReranker(StubReranker):
        def rerank(self, *, query: str, candidates, timeout_seconds: float):
            assert timeout_seconds == 0.01
            raise TimeoutError("bounded adapter timeout")

    outcome = apply_reranker(
        query="query",
        candidates=candidates,
        reranker=TimeoutReranker(),
        timeout_seconds=0.01,
    )

    assert outcome.status == "failed"
    assert outcome.fallback_reason == "reranker_timeout"
    assert outcome.candidates == candidates
    assert outcome.external_request_count == 0
    assert outcome.transmitted_bytes == 0


def test_exact_quality_and_recall_boundaries_are_not_lost_to_float_rounding() -> None:
    decision = evaluate_reranker_adoption(
        candidate_enabled=True,
        baseline_ndcg=0.80,
        candidate_ndcg=0.85,
        baseline_recall=0.92,
        candidate_recall=0.90,
        paired_ndcg_deltas=(0.05,) * 50,
        safety_violation_count=0,
        reranker_p95_ms=100.0,
        reranker_hard_max_ms=100.0,
        hybrid_total_p95_ms=200.0,
        hybrid_total_hard_max_ms=200.0,
        bootstrap_samples=1_000,
    )

    assert decision.decision == "adopt"
    assert decision.reasons == ()


def test_invalid_numeric_gates_and_usage_counters_fail_closed() -> None:
    invalid_gate = evaluate_reranker_adoption(
        candidate_enabled=True,
        baseline_ndcg=float("nan"),
        candidate_ndcg=1.2,
        baseline_recall=0.92,
        candidate_recall=0.90,
        paired_ndcg_deltas=(float("nan"),),
        safety_violation_count=0,
        reranker_p95_ms=200.0,
        reranker_hard_max_ms=100.0,
        hybrid_total_p95_ms=400.0,
        hybrid_total_hard_max_ms=300.0,
    )
    assert invalid_gate.decision == "defer"
    assert set(invalid_gate.reasons) >= {
        "invalid_quality_metric",
        "paired_bootstrap_ci_lower_below_zero",
        "latency_gate_failed",
        "hybrid_total_latency_gate_failed",
    }

    candidates = tuple(_fused(f"id-{index}", index + 1) for index in range(2))
    invalid_usage = StubReranker(
        response=RerankerResponse(
            ordered_ids=tuple(candidate.stable_id for candidate in candidates),
            external_request_count=True,
            external_cost_usd=float("nan"),
        )
    )
    outcome = apply_reranker(query="query", candidates=candidates, reranker=invalid_usage)
    assert outcome.status == "failed"
    assert outcome.fallback_reason == "reranker_failed"
    assert outcome.external_request_count == 0
