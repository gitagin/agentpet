from __future__ import annotations

from app.evals.soak_report import linear_growth_percent, percentile, summarize_soak


def _ready_sample(index: int, *, duplicate_effects: int = 0) -> dict[str, object]:
    return {
        "timestamp": f"2026-08-10T00:{index:02d}:00+00:00",
        "ready": True,
        "memory_bytes": 1000,
        "handle_count": 20,
        "sqlite_snapshot": {
            "unexplained_action_count": 0,
            "failed_recovery_count": 0,
            "post_reply_backlog_count": 0,
            "index_backlog_count": 0,
            "duplicate_business_effect_count": duplicate_effects,
            "automatic_duplicate_dispatch_count": 0,
            "sqlite_error_count": 0,
            "wiki_lint_failed_count": 0,
            "graph_generation_lag_seconds": 0,
            "graph_projection_mode": "kuzu",
        },
    }


def test_percentile_and_linear_growth_are_deterministic() -> None:
    assert percentile([1, 2, 3, 4]) == 4
    assert percentile([]) is None
    samples = [{"rss": value} for value in [100, 100, 100, 101, 102, 103, 104, 105, 106, 107]]
    growth = linear_growth_percent(samples, "rss")
    assert growth is not None
    assert growth > 0


def test_short_window_is_explicitly_debug_evidence() -> None:
    report = summarize_soak(
        [_ready_sample(index) for index in range(5)],
        requested_duration_hours=0.01,
        interval_seconds=1,
        observed_duration_seconds=36,
    )
    assert report["status"] == "debug_passed"
    assert report["evidence_status"] == "debug-short-window"
    assert report["formal_window_observed"] is False


def test_formal_window_cannot_pass_without_sample_count() -> None:
    report = summarize_soak(
        [_ready_sample(index) for index in range(5)],
        requested_duration_hours=24,
        interval_seconds=60,
        observed_duration_seconds=24 * 3600,
    )
    assert report["status"] == "failed"
    assert report["formal_window_observed"] is False
    assert report["required_formal_samples"] == 1_440


def test_duplicate_effect_fails_even_when_health_is_ready() -> None:
    report = summarize_soak(
        [_ready_sample(index, duplicate_effects=1) for index in range(5)],
        requested_duration_hours=0.01,
        interval_seconds=1,
        observed_duration_seconds=36,
    )
    assert report["status"] == "debug_failed"
    assert report["checks"]["duplicate_business_effects"]["passed"] is False
