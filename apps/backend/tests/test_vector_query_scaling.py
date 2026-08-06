from __future__ import annotations

import pytest

from app.evals.vector_query_scaling import (
    VectorScalingContractError,
    _nearest_rank_percentile,
    _validate_configuration,
    evaluate_scaling,
)


def test_nearest_rank_percentile_is_deterministic() -> None:
    assert _nearest_rank_percentile([4.0, 1.0, 3.0, 2.0], 0.50) == 2.0
    assert _nearest_rank_percentile([4.0, 1.0, 3.0, 2.0], 0.95) == 4.0


def test_scaling_gate_compares_latency_growth_to_linear_growth() -> None:
    passed = evaluate_scaling(
        small_size=2_048,
        large_size=32_768,
        small_p95_ms=4.0,
        large_p95_ms=20.0,
    )
    failed = evaluate_scaling(
        small_size=2_048,
        large_size=32_768,
        small_p95_ms=4.0,
        large_p95_ms=60.0,
    )

    assert passed["collection_size_ratio"] == 16.0
    assert passed["linear_growth_fraction"] == 0.3125
    assert passed["passed"] is True
    assert failed["linear_growth_fraction"] == 0.9375
    assert failed["passed"] is False


def test_scaling_configuration_rejects_embedded_or_too_narrow_runs() -> None:
    with pytest.raises(VectorScalingContractError, match="actual Qdrant Server"):
        _validate_configuration(
            qdrant_url=":memory:",
            collection_sizes=[2_048, 32_768],
            dimensions=64,
            warmup_queries=20,
            measured_queries=80,
            optimizer_timeout_seconds=180.0,
        )
    with pytest.raises(VectorScalingContractError, match="at least 8x"):
        _validate_configuration(
            qdrant_url="http://127.0.0.1:6333",
            collection_sizes=[2_048, 4_096],
            dimensions=64,
            warmup_queries=20,
            measured_queries=80,
            optimizer_timeout_seconds=180.0,
        )
