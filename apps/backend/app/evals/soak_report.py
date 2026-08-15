"""Deterministic aggregation and threshold checks for the local soak runner."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path


SOAK_SCHEMA_VERSION = "llmwiki-soak.v1"
FORMAL_MINIMUM_HOURS = 24.0
FORMAL_MINIMUM_SAMPLES = 1_440
READY_RATIO_MINIMUM = 0.995
RECOVERY_P95_MAX_SECONDS = 60.0
RESOURCE_GROWTH_MAX_PERCENT = 10.0
GENERATION_LAG_MAX_SECONDS = 300.0


def percentile(values: Iterable[float], percentile_value: float = 0.95) -> float | None:
    """Return a nearest-rank percentile without inventing a value for empty data."""
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    bounded = min(1.0, max(0.0, float(percentile_value)))
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * bounded) - 1))
    return ordered[index]


def linear_growth_percent(samples: Sequence[dict[str, object]], field: str) -> float | None:
    """Estimate post-warmup linear growth as a percent of the warmup baseline."""
    values: list[float] = []
    for sample in samples:
        raw = sample.get(field)
        if isinstance(raw, bool) or raw is None or not isinstance(raw, (int, float, str)):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            values.append(value)
    if len(values) < 4:
        return None
    warmup = max(1, math.floor(len(values) * 0.1))
    observed = values[warmup:]
    if len(observed) < 3:
        return None
    baseline_window = max(2, math.floor(len(observed) * 0.1))
    baseline = sum(observed[:baseline_window]) / baseline_window
    if baseline <= 0:
        return None
    x_mean = (len(observed) - 1) / 2
    y_mean = sum(observed) / len(observed)
    denominator = sum((index - x_mean) ** 2 for index in range(len(observed)))
    if denominator <= 0:
        return None
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(observed)) / denominator
    projected_change = slope * (len(observed) - 1)
    return round((projected_change / baseline) * 100, 3)


def _last_snapshot(samples: Sequence[dict[str, object]]) -> dict[str, object]:
    for sample in reversed(samples):
        snapshot = sample.get("sqlite_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
    return {}


def _snapshot_number(snapshot: dict[str, object], key: str, default: int = 0) -> int:
    raw = snapshot.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return default
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return default


def _snapshot_float(snapshot: dict[str, object], key: str) -> float | None:
    raw = snapshot.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def summarize_soak(
    samples: Sequence[dict[str, object]],
    *,
    requested_duration_hours: float,
    interval_seconds: int,
    observed_duration_seconds: float,
) -> dict[str, object]:
    """Build a privacy-safe report and apply the frozen local thresholds."""
    sample_count = len(samples)
    ready_count = sum(1 for sample in samples if sample.get("ready") is True)
    ready_ratio = ready_count / sample_count if sample_count else 0.0
    snapshots = [sample.get("sqlite_snapshot") for sample in samples if isinstance(sample.get("sqlite_snapshot"), dict)]
    final_snapshot = _last_snapshot(samples)

    recovery_durations: list[float] = []
    generation_lags: list[float] = []
    fallback_samples = 0
    for sample in samples:
        raw_recoveries = sample.get("recovery_durations_seconds")
        if isinstance(raw_recoveries, list):
            for raw in raw_recoveries:
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value) and value >= 0:
                    recovery_durations.append(value)
        snapshot = sample.get("sqlite_snapshot")
        if isinstance(snapshot, dict):
            lag = _snapshot_float(snapshot, "graph_generation_lag_seconds")
            if lag is not None:
                generation_lags.append(lag)
            mode = str(snapshot.get("graph_projection_mode") or "")
            if mode in {"sqlite_fallback", "sqlite_only"}:
                fallback_samples += 1

    final_recovery_values = final_snapshot.get("recovery_durations_ms")
    if isinstance(final_recovery_values, list):
        for raw in final_recovery_values:
            try:
                value = float(raw) / 1000.0
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value >= 0:
                recovery_durations.append(value)

    recovery_p95 = percentile(recovery_durations)
    generation_lag_p95 = percentile(generation_lags)
    memory_growth = linear_growth_percent(samples, "memory_bytes")
    handle_growth = linear_growth_percent(samples, "handle_count")
    required_samples = max(
        FORMAL_MINIMUM_SAMPLES,
        math.ceil(max(0.0, requested_duration_hours) * 3600 / max(1, interval_seconds)),
    )
    formal_requested = requested_duration_hours >= FORMAL_MINIMUM_HOURS
    formal_window = (
        formal_requested
        and observed_duration_seconds >= requested_duration_hours * 3600
        and sample_count >= required_samples
    )
    final_unexplained = _snapshot_number(final_snapshot, "unexplained_action_count")
    final_failed_recovery = _snapshot_number(final_snapshot, "failed_recovery_count")
    final_post_reply_backlog = _snapshot_number(final_snapshot, "post_reply_backlog_count")
    final_post_reply_failed = _snapshot_number(final_snapshot, "post_reply_failed_count")
    final_index_backlog = _snapshot_number(final_snapshot, "index_backlog_count")
    final_duplicate_effects = _snapshot_number(final_snapshot, "duplicate_business_effect_count")
    final_duplicate_dispatches = _snapshot_number(final_snapshot, "automatic_duplicate_dispatch_count")
    final_sqlite_errors = _snapshot_number(final_snapshot, "sqlite_error_count")
    final_lint_failures = _snapshot_number(final_snapshot, "wiki_lint_failed_count")

    resource_values_available = memory_growth is not None and handle_growth is not None
    resource_values_within_limit = (
        (memory_growth is None or memory_growth <= RESOURCE_GROWTH_MAX_PERCENT)
        and (handle_growth is None or handle_growth <= RESOURCE_GROWTH_MAX_PERCENT)
    )
    projection_telemetry_present = bool(generation_lags) or fallback_samples > 0
    checks: dict[str, dict[str, object]] = {
        "ready_ratio": {
            "value": round(ready_ratio, 6),
            "minimum": READY_RATIO_MINIMUM,
            "final_ready": bool(samples and samples[-1].get("ready") is True),
            "passed": ready_ratio >= READY_RATIO_MINIMUM
            and sample_count > 0
            and samples[-1].get("ready") is True,
        },
        "duplicate_business_effects": {
            "value": final_duplicate_effects,
            "maximum": 0,
            "passed": final_duplicate_effects == 0 and final_duplicate_dispatches == 0,
        },
        "unexplained_claims": {
            "value": final_unexplained,
            "maximum": 0,
            "passed": final_unexplained == 0,
        },
        "failed_recovery": {
            "value": final_failed_recovery,
            "maximum": 0,
            "passed": final_failed_recovery == 0,
        },
        "backlog": {
            "post_reply": final_post_reply_backlog,
            "post_reply_failed": final_post_reply_failed,
            "index": final_index_backlog,
            "maximum": 0,
            "passed": final_post_reply_backlog == 0
            and final_post_reply_failed == 0
            and final_index_backlog == 0,
        },
        "recovery_p95": {
            "value_seconds": recovery_p95,
            "maximum_seconds": RECOVERY_P95_MAX_SECONDS,
            "passed": recovery_p95 is None or recovery_p95 <= RECOVERY_P95_MAX_SECONDS,
        },
        "resource_growth": {
            "memory_percent": memory_growth,
            "handles_percent": handle_growth,
            "maximum_percent": RESOURCE_GROWTH_MAX_PERCENT,
            "passed": resource_values_available and resource_values_within_limit
            if formal_requested
            else resource_values_within_limit,
            "evidence_status": "measured" if resource_values_available else "debug_insufficient_samples",
        },
        "generation_lag": {
            "p95_seconds": generation_lag_p95,
            "maximum_seconds": GENERATION_LAG_MAX_SECONDS,
            "fallback_samples": fallback_samples,
            "passed": projection_telemetry_present
            and (generation_lag_p95 is None or generation_lag_p95 <= GENERATION_LAG_MAX_SECONDS or fallback_samples > 0),
        },
        "database_and_lint": {
            "sqlite_errors": final_sqlite_errors,
            "wiki_lint_failures": final_lint_failures,
            "passed": final_sqlite_errors == 0 and final_lint_failures == 0,
        },
    }
    mechanism_checks_passed = all(bool(item.get("passed")) for item in checks.values())
    if formal_requested:
        status = "passed" if formal_window and mechanism_checks_passed else "failed"
    else:
        status = "debug_passed" if mechanism_checks_passed and sample_count > 0 else "debug_failed"

    return {
        "schema_version": SOAK_SCHEMA_VERSION,
        "threshold_version": SOAK_SCHEMA_VERSION,
        "status": status,
        "requested_duration_hours": requested_duration_hours,
        "observed_duration_seconds": round(observed_duration_seconds, 2),
        "interval_seconds": interval_seconds,
        "sample_count": sample_count,
        "required_formal_samples": required_samples,
        "ready_sample_count": ready_count,
        "ready_ratio": round(ready_ratio, 6),
        "recovery_durations_seconds": [round(value, 3) for value in recovery_durations],
        "recovery_p95_seconds": recovery_p95,
        "generation_lag_p95_seconds": generation_lag_p95,
        "resource_growth_percent": {
            "memory_bytes": memory_growth,
            "handle_count": handle_growth,
        },
        "final_snapshot": final_snapshot,
        "checks": checks,
        "formal_window_observed": formal_window,
        "evidence_status": "real-time-window" if formal_window else "debug-short-window",
        "snapshot_count": len(snapshots),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate privacy-safe Agent Pet soak samples")
    parser.add_argument("--samples", required=True)
    parser.add_argument("--duration-hours", type=float, required=True)
    parser.add_argument("--interval-seconds", type=int, required=True)
    parser.add_argument("--observed-duration-seconds", type=float, required=True)
    parser.add_argument("--out", required=True)
    return parser


def _load_samples(path: str | Path) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            samples.append(value)
    return samples


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = summarize_soak(
        _load_samples(args.samples),
        requested_duration_hours=args.duration_hours,
        interval_seconds=args.interval_seconds,
        observed_duration_seconds=args.observed_duration_seconds,
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["status"] in {"passed", "debug_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
