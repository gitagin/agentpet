"""Validation shared by local write endpoints."""

from __future__ import annotations

import re


IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def is_valid_idempotency_key(value: str | None) -> bool:
    return bool(value and IDEMPOTENCY_KEY_PATTERN.fullmatch(value))
