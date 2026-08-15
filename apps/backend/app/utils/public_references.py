from __future__ import annotations

import re

from .hash import sha256_hex


_REFERENCE_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def public_memory_reference(kind: str, raw_id: object) -> str:
    """Create a stable opaque reference for an API or prompt citation."""
    normalized_kind = str(kind or "").strip().casefold()
    if not _REFERENCE_KIND.fullmatch(normalized_kind):
        raise ValueError("invalid_public_reference_kind")
    value = str(raw_id or "").strip()
    if not value:
        raise ValueError("empty_public_reference_id")
    return f"{normalized_kind}_" + sha256_hex(f"llmwiki:{normalized_kind}:{value}")[:24]


def safe_relative_source_reference(value: object) -> str | None:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or len(raw) > 500 or raw.startswith("/") or ":" in raw.split("/", 1)[0]:
        return None
    parts = tuple(part for part in raw.split("/") if part)
    if not parts or any(
        part in {".", ".."} or any(ord(char) < 32 for char in part)
        for part in parts
    ):
        return None
    return "/".join(parts)
