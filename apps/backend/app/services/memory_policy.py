from __future__ import annotations

from dataclasses import dataclass

from app.services.write_policy import detect_sensitive_reason


@dataclass(frozen=True)
class MemoryPolicyDecision:
    allowed: bool
    reason: str | None = None


def evaluate_memory_content(content: str) -> MemoryPolicyDecision:
    reason = detect_sensitive_reason(content)
    if reason is not None:
        return MemoryPolicyDecision(allowed=False, reason=reason)
    return MemoryPolicyDecision(allowed=True)
