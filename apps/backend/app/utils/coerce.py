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
