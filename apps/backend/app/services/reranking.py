from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from random import Random
from time import perf_counter_ns
from typing import Protocol, runtime_checkable

from app.services.retrieval_fusion import FusedCandidate


RERANKER_POLICY_VERSION = "reranker-policy.v1"
MAX_RERANK_CANDIDATES = 20
RERANKER_QUALITY_DELTA = 0.05
MAX_RECALL_REGRESSION = 0.02
RERANKER_P95_LIMIT_MS = 1_500.0
RERANKER_HARD_LIMIT_MS = 3_000.0
RERANKER_EXTERNAL_MEAN_COST_LIMIT_USD = 0.01
HYBRID_RERANKER_P95_LIMIT_MS = 4_500.0
HYBRID_RERANKER_HARD_LIMIT_MS = 7_000.0


@dataclass(frozen=True, slots=True)
class RerankerResponse:
    ordered_ids: tuple[str, ...]
    external_request_count: int = 0
    transmitted_bytes: int = 0
    external_cost_usd: float = 0.0
    provider_error_count: int = 0


@runtime_checkable
class Reranker(Protocol):
    name: str
    enabled: bool
    is_remote: bool

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[FusedCandidate],
        timeout_seconds: float,
    ) -> RerankerResponse: ...


@dataclass(frozen=True, slots=True)
class DisabledReranker:
    name: str = "disabled"
    enabled: bool = False
    is_remote: bool = False

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[FusedCandidate],
        timeout_seconds: float,
    ) -> RerankerResponse:
        del query, timeout_seconds
        return RerankerResponse(ordered_ids=tuple(candidate.stable_id for candidate in candidates))


@dataclass(frozen=True, slots=True)
class RerankOutcome:
    candidates: tuple[FusedCandidate, ...]
    status: str
    reranker_name: str
    latency_ms: float
    external_request_count: int
    transmitted_bytes: int
    external_cost_usd: float
    provider_error_count: int
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RerankerAdoptionDecision:
    decision: str
    reasons: tuple[str, ...]
    ndcg_delta: float | None
    citation_precision_delta: float | None
    recall_regression: float | None
    bootstrap_ci_lower: float | None
    bootstrap_ci_upper: float | None


def apply_reranker(
    *,
    query: str,
    candidates: Sequence[FusedCandidate],
    reranker: Reranker | None,
    remote_provider_approved: bool = False,
    timeout_seconds: float = RERANKER_HARD_LIMIT_MS / 1_000,
) -> RerankOutcome:
    original = tuple(candidates)
    selected = reranker or DisabledReranker()
    if not selected.enabled:
        return _fallback_outcome(original, selected.name, status="disabled")
    if selected.is_remote and not remote_provider_approved:
        return _fallback_outcome(
            original,
            selected.name,
            status="privacy_blocked",
            fallback_reason="remote_reranker_not_approved",
        )

    head = original[:MAX_RERANK_CANDIDATES]
    started = perf_counter_ns()
    try:
        response = selected.rerank(
            query=query,
            candidates=head,
            timeout_seconds=max(0.0, timeout_seconds),
        )
        if not isinstance(response, RerankerResponse):
            raise ValueError("reranker returned an invalid response type")
        _validate_response(response, expected_ids=tuple(candidate.stable_id for candidate in head))
    except TimeoutError:
        return _fallback_outcome(
            original,
            selected.name,
            status="failed",
            latency_ms=_elapsed_ms(started),
            fallback_reason="reranker_timeout",
            provider_error_count=1 if selected.is_remote else 0,
        )
    except Exception:
        return _fallback_outcome(
            original,
            selected.name,
            status="failed",
            latency_ms=_elapsed_ms(started),
            fallback_reason="reranker_failed",
            provider_error_count=1 if selected.is_remote else 0,
        )

    by_id = {candidate.stable_id: candidate for candidate in head}
    reranked_head = tuple(by_id[stable_id] for stable_id in response.ordered_ids)
    return RerankOutcome(
        candidates=(*reranked_head, *original[MAX_RERANK_CANDIDATES:]),
        status="applied",
        reranker_name=selected.name,
        latency_ms=_elapsed_ms(started),
        external_request_count=response.external_request_count,
        transmitted_bytes=response.transmitted_bytes,
        external_cost_usd=response.external_cost_usd,
        provider_error_count=response.provider_error_count,
    )


def evaluate_reranker_adoption(
    *,
    candidate_enabled: bool,
    baseline_ndcg: float,
    candidate_ndcg: float,
    baseline_recall: float,
    candidate_recall: float,
    paired_ndcg_deltas: Sequence[float],
    safety_violation_count: int,
    reranker_p95_ms: float,
    reranker_hard_max_ms: float,
    baseline_citation_precision: float | None = None,
    candidate_citation_precision: float | None = None,
    is_external: bool = False,
    human_gate_approved: bool = False,
    external_mean_cost_usd: float | None = None,
    hybrid_total_p95_ms: float | None = None,
    hybrid_total_hard_max_ms: float | None = None,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 1206,
) -> RerankerAdoptionDecision:
    metric_values = (baseline_ndcg, candidate_ndcg, baseline_recall, candidate_recall)
    valid_metrics = all(isfinite(value) and 0.0 <= value <= 1.0 for value in metric_values)
    ndcg_delta = candidate_ndcg - baseline_ndcg if valid_metrics else float("nan")
    citation_delta = None
    if baseline_citation_precision is not None and candidate_citation_precision is not None:
        if all(
            isfinite(value) and 0.0 <= value <= 1.0
            for value in (baseline_citation_precision, candidate_citation_precision)
        ):
            citation_delta = candidate_citation_precision - baseline_citation_precision
    recall_regression = baseline_recall - candidate_recall if valid_metrics else float("nan")
    ci_lower, ci_upper = _paired_bootstrap_mean_interval(
        paired_ndcg_deltas,
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    reasons: list[str] = []
    if not valid_metrics:
        reasons.append("invalid_quality_metric")
    if not candidate_enabled:
        reasons.append("candidate_disabled")
    quality_deltas = [ndcg_delta] if isfinite(ndcg_delta) else []
    if citation_delta is not None:
        quality_deltas.append(citation_delta)
    if not quality_deltas or max(quality_deltas) + 1e-12 < RERANKER_QUALITY_DELTA:
        reasons.append("quality_delta_below_threshold")
    if not isfinite(recall_regression) or recall_regression - MAX_RECALL_REGRESSION > 1e-12:
        reasons.append("recall_regression_exceeds_threshold")
    if ci_lower is None or ci_lower < 0:
        reasons.append("paired_bootstrap_ci_lower_below_zero")
    if not isinstance(safety_violation_count, int) or safety_violation_count != 0:
        reasons.append("safety_gate_failed")
    reranker_latencies = (reranker_p95_ms, reranker_hard_max_ms)
    if (
        any(not isfinite(value) or value < 0 for value in reranker_latencies)
        or reranker_p95_ms > reranker_hard_max_ms
        or reranker_p95_ms > RERANKER_P95_LIMIT_MS
        or reranker_hard_max_ms > RERANKER_HARD_LIMIT_MS
    ):
        reasons.append("latency_gate_failed")
    if hybrid_total_p95_ms is None or hybrid_total_hard_max_ms is None:
        reasons.append("hybrid_total_latency_unknown")
    elif (
        not isfinite(hybrid_total_p95_ms)
        or not isfinite(hybrid_total_hard_max_ms)
        or hybrid_total_p95_ms < 0
        or hybrid_total_hard_max_ms < 0
        or hybrid_total_p95_ms > hybrid_total_hard_max_ms
        or hybrid_total_p95_ms > HYBRID_RERANKER_P95_LIMIT_MS
        or hybrid_total_hard_max_ms > HYBRID_RERANKER_HARD_LIMIT_MS
    ):
        reasons.append("hybrid_total_latency_gate_failed")
    if is_external:
        if not human_gate_approved:
            reasons.append("human_gate_not_approved")
        if external_mean_cost_usd is None:
            reasons.append("external_cost_unknown")
        elif (
            not isfinite(external_mean_cost_usd)
            or external_mean_cost_usd < 0
            or external_mean_cost_usd > RERANKER_EXTERNAL_MEAN_COST_LIMIT_USD
        ):
            reasons.append("external_cost_gate_failed")
    return RerankerAdoptionDecision(
        decision="adopt" if not reasons else "defer",
        reasons=tuple(reasons),
        ndcg_delta=round(ndcg_delta, 6) if isfinite(ndcg_delta) else None,
        citation_precision_delta=round(citation_delta, 6) if citation_delta is not None else None,
        recall_regression=round(recall_regression, 6) if isfinite(recall_regression) else None,
        bootstrap_ci_lower=ci_lower,
        bootstrap_ci_upper=ci_upper,
    )


def _validate_response(response: RerankerResponse, *, expected_ids: tuple[str, ...]) -> None:
    if len(response.ordered_ids) != len(expected_ids):
        raise ValueError("reranker changed candidate count")
    if len(set(response.ordered_ids)) != len(response.ordered_ids):
        raise ValueError("reranker returned duplicate identities")
    if set(response.ordered_ids) != set(expected_ids):
        raise ValueError("reranker changed candidate identities")
    if (
        type(response.external_request_count) is not int
        or type(response.transmitted_bytes) is not int
        or response.external_request_count < 0
        or response.transmitted_bytes < 0
    ):
        raise ValueError("reranker usage counters must be non-negative")
    if type(response.provider_error_count) is not int or response.provider_error_count < 0:
        raise ValueError("reranker provider error count must be non-negative")
    if not isfinite(response.external_cost_usd) or response.external_cost_usd < 0:
        raise ValueError("reranker cost must be a finite non-negative value")


def _fallback_outcome(
    candidates: tuple[FusedCandidate, ...],
    reranker_name: str,
    *,
    status: str,
    latency_ms: float = 0.0,
    fallback_reason: str | None = None,
    provider_error_count: int = 0,
) -> RerankOutcome:
    return RerankOutcome(
        candidates=candidates,
        status=status,
        reranker_name=reranker_name,
        latency_ms=latency_ms,
        external_request_count=0,
        transmitted_bytes=0,
        external_cost_usd=0.0,
        provider_error_count=provider_error_count,
        fallback_reason=fallback_reason,
    )


def _elapsed_ms(started_ns: int) -> float:
    return round((perf_counter_ns() - started_ns) / 1_000_000, 6)


def _paired_bootstrap_mean_interval(
    deltas: Sequence[float],
    *,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    values = tuple(float(value) for value in deltas)
    if not values or samples <= 0 or any(not isfinite(value) for value in values):
        return None, None
    generator = Random(seed)
    sample_size = len(values)
    means = []
    for _ in range(samples):
        means.append(sum(values[generator.randrange(sample_size)] for _ in range(sample_size)) / sample_size)
    means.sort()
    lower_index = max(0, int(samples * 0.025) - 1)
    upper_index = min(samples - 1, int(samples * 0.975) - 1)
    return round(means[lower_index], 6), round(means[upper_index], 6)
