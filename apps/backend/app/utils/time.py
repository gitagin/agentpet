from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter, perf_counter_ns


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def elapsed_ms(started: float) -> int:
    """Milliseconds elapsed since a ``perf_counter()`` start (clamped to >= 0)."""
    return max(0, round((perf_counter() - started) * 1000))


def elapsed_ms_ns(started_ns: int) -> float:
    """Milliseconds elapsed since a ``perf_counter_ns()`` start (6-dp float)."""
    return round((perf_counter_ns() - started_ns) / 1_000_000, 6)


def coerce_datetime(value: datetime | str) -> datetime:
    """Parse a datetime or ISO string into a UTC-aware datetime."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
