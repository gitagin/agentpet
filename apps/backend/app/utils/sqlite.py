"""Shared SQLite row/JSON coercion helpers for store services.

Every store service used to carry its own private copy of these small
helpers (``_table_exists``, ``_json_object``, ``_json_list``,
``_optional_str``, ``_json_load``).  Keeping one implementation here avoids
the copy-paste drift that previously produced two different ``_json_object``
semantics under the same name (one parsing, one serializing).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any


def table_exists(conn: sqlite3.Connection, name: str, *, include_views: bool = False) -> bool:
    """Return whether a table (or view) named ``name`` exists in the database.

    ``include_views`` matches the historical ``type IN ('table', 'view')``
    variants; the default matches the ``type = 'table'`` variants.
    """
    type_filter = "IN ('table', 'view')" if include_views else "= 'table'"
    row = conn.execute(
        f"SELECT 1 FROM sqlite_master WHERE type {type_filter} AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def json_object(value: Any) -> dict[str, Any]:
    """Parse a JSON-encoded column into a dict; ``{}`` on empty/invalid input."""
    if value is None or value == "":
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value: Any, *, strict: bool = False) -> list[str]:
    """Parse a JSON-encoded array column into a list of strings; ``[]`` otherwise.

    ``strict`` keeps only entries that are already strings (the historical
    ``memory_graph_projection`` behavior); the default stringifies any item,
    matching the majority of the former private copies.
    """
    if value is None or value == "":
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    if strict:
        return [str(item) for item in parsed if isinstance(item, str) and item.strip()]
    return [str(item) for item in parsed if str(item).strip()]


def json_load(value: Any, default: Any) -> Any:
    """Parse a JSON-encoded value, returning ``default`` on failure."""
    if value is None:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def optional_str(value: Any) -> str | None:
    """Coerce a row value into a non-empty string, or ``None``."""
    if value is None:
        return None
    text = str(value)
    return text if text else None


def extract_json_object(text: str, *, error_code: str) -> str:
    """Extract the first balanced JSON object literal from model output.

    Raises ``ValueError(error_code)`` when no ``{...}`` block is present so
    callers keep their domain-specific failure codes.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(error_code)
    return text[start : end + 1]
