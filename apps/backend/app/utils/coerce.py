from __future__ import annotations

from typing import Any


def coerce_field(value: Any, expected_type: type, default: Any = None) -> Any:
    if isinstance(value, expected_type):
        return value
    try:
        return expected_type(value)
    except (TypeError, ValueError):
        return default


def coerce_model(value: Any, expected_type: type[Any]) -> Any:
    if isinstance(value, expected_type):
        return value
    return expected_type.model_validate(value)


def clamp_unit_interval(value: Any) -> float:
    """Clamp a value into [0.0, 1.0]; non-numeric values become 0.0."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def compact_text(value: str, limit: int) -> str:
    """Collapse whitespace and truncate with an ellipsis at ``limit`` chars."""
    compacted = " ".join(str(value).strip().split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(0, limit - 3)].rstrip() + "..."
