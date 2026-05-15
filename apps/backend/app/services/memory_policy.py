from __future__ import annotations

import re
from dataclasses import dataclass


SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "api_key",
        re.compile(
            r"\b(?:sk|pk|rk|ghp|gho|ghu|github_pat|xox[baprs]|AKIA)[A-Za-z0-9_\-]{12,}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "bearer_token",
        re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
    ),
    (
        "password_assignment",
        re.compile(r"\b(?:password|passwd|pwd|secret|token|api[_ -]?key)\s*[:=]\s*\S{6,}", re.IGNORECASE),
    ),
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class MemoryPolicyDecision:
    allowed: bool
    reason: str | None = None


def evaluate_memory_content(content: str) -> MemoryPolicyDecision:
    for reason, pattern in SENSITIVE_PATTERNS:
        if pattern.search(content):
            return MemoryPolicyDecision(allowed=False, reason=reason)
    return MemoryPolicyDecision(allowed=True)
