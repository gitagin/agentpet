"""Shared helpers for agent reviewer nodes.

The orchestrator, memory-reviewer and wiki-reviewer nodes used to carry
private copies of ``_extract_text`` and ``_parse_json_response``.  Keeping
them here gives the three nodes one implementation to reuse.
"""
from __future__ import annotations

import json
from typing import Any


def extract_text(raw_result: Any) -> str:
    """Extract plain text from a model result that may be a string or object."""
    if isinstance(raw_result, str):
        return raw_result
    if hasattr(raw_result, "text"):
        return str(raw_result.text)
    if hasattr(raw_result, "content"):
        return str(raw_result.content)
    return str(raw_result)


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse a model JSON reply, tolerating a fenced ```json block."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
    return json.loads(stripped)
