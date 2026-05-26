from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Callable, Literal, Mapping


class _StrEnum(str, Enum):
    pass


class EvidenceLevel(_StrEnum):
    explicit_user_statement = "explicit_user_statement"
    derived_from_repeated_behavior = "derived_from_repeated_behavior"
    assistant_summary = "assistant_summary"
    uncertain_inference = "uncertain_inference"
    external_source = "external_source"


class ContentCategory(_StrEnum):
    preference = "preference"
    fact = "fact"
    event = "event"
    goal = "goal"
    rule = "rule"
    health = "health"
    financial = "financial"
    legal = "legal"
    relationship = "relationship"
    identity = "identity"
    crisis = "crisis"
    credential = "credential"


@dataclass(frozen=True)
class WritePolicyRequest:
    scope: str
    target_path: str
    content: str
    source_message: str
    source_run_id: str
    evidence_level: EvidenceLevel
    content_category: ContentCategory
    metadata: dict


@dataclass(frozen=True)
class WritePolicyDecision:
    allowed: bool
    decision: Literal["auto", "review", "reject"]
    risk_tier: Literal["low", "medium", "high", "critical"]
    reasons: list[str]
    reversible: bool


@dataclass(frozen=True)
class MarkdownWritePolicyDecision:
    allowed: bool
    reason: str | None = None
    risk_tier: str = "low"
    decision: str = "auto"
    reversible: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MarkdownWritePolicyRequest:
    scope: str
    target_path: str
    title: str
    content: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    reversible: bool = True


SENSITIVE_PATTERNS: dict[str, list[str]] = {
    "identity": ["身份证", "护照号", "社保号", "驾照"],
    "contact": ["手机号", "家庭住址", "工作单位"],
    "health": ["疾病", "用药", "就诊", "心理"],
    "financial": ["收入", "银行账户", "投资", "负债"],
    "crisis": ["自伤", "自杀", "暴力"],
    "credential": [r"sk-[a-zA-Z0-9]{20,}", r"Bearer\s+[a-zA-Z0-9\-._]{20,}", "密码", "私钥"],
}

LEGACY_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
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

_REVIEW_CATEGORIES = {
    ContentCategory.health,
    ContentCategory.financial,
    ContentCategory.legal,
    ContentCategory.identity,
}
_REJECT_CATEGORIES = {ContentCategory.crisis, ContentCategory.credential}
_WRITE_TIMESTAMPS: dict[str, list[float]] = {}
_WRITE_TIMESTAMPS_LOCK = threading.Lock()
_WRITE_LIMIT_WINDOW_SECONDS = 300
_WRITE_LIMIT_COUNT = 10
Checker = Callable[[WritePolicyRequest], WritePolicyDecision | None]


def _combined_policy_text(request: WritePolicyRequest) -> str:
    return "\n".join(
        [
            request.scope,
            request.target_path,
            request.content,
            request.source_message,
            request.source_run_id,
            *[f"{key}: {value}" for key, value in request.metadata.items()],
        ]
    )


def _decision(
    decision: Literal["auto", "review", "reject"],
    risk_tier: Literal["low", "medium", "high", "critical"],
    reason: str,
    *,
    reversible: bool = True,
) -> WritePolicyDecision:
    return WritePolicyDecision(
        allowed=decision == "auto",
        decision=decision,
        risk_tier=risk_tier,
        reasons=[reason],
        reversible=reversible,
    )


def _keyword_or_regex_matches(text: str, pattern: str) -> bool:
    if any(token in pattern for token in "\\[]{}()+*?|^$"):
        return re.search(pattern, text, re.IGNORECASE) is not None
    return pattern.lower() in text.lower()


def detect_sensitive_reason(content: str) -> str | None:
    for reason, pattern in LEGACY_CREDENTIAL_PATTERNS:
        if pattern.search(content):
            return reason
    for category, patterns in SENSITIVE_PATTERNS.items():
        for pattern in patterns:
            if _keyword_or_regex_matches(content, pattern):
                return category
    return None


def check_credential_leak(request: WritePolicyRequest) -> WritePolicyDecision | None:
    text = _combined_policy_text(request)
    for reason, pattern in LEGACY_CREDENTIAL_PATTERNS:
        if pattern.search(text):
            return _decision("reject", "critical", reason, reversible=False)
    for pattern in SENSITIVE_PATTERNS["credential"]:
        if _keyword_or_regex_matches(text, pattern):
            return _decision("reject", "critical", "credential", reversible=False)
    return None


def check_sensitive_pii(request: WritePolicyRequest) -> WritePolicyDecision | None:
    text = _combined_policy_text(request)
    for category in ("identity", "contact"):
        for pattern in SENSITIVE_PATTERNS[category]:
            if _keyword_or_regex_matches(text, pattern):
                return _decision("reject", "high", category)
    return None


def check_crisis_content(request: WritePolicyRequest) -> WritePolicyDecision | None:
    text = _combined_policy_text(request)
    for pattern in SENSITIVE_PATTERNS["crisis"]:
        if _keyword_or_regex_matches(text, pattern):
            return _decision("reject", "critical", "crisis", reversible=False)
    return None


def check_evidence_level(request: WritePolicyRequest) -> WritePolicyDecision | None:
    if request.evidence_level is EvidenceLevel.uncertain_inference:
        if request.content_category in {ContentCategory.rule, ContentCategory.goal}:
            return _decision("reject", "high", "uncertain_inference_requires_rejection")
        return _decision("review", "medium", "uncertain_inference_requires_review")
    return None


def check_content_category(request: WritePolicyRequest) -> WritePolicyDecision | None:
    if request.content_category in _REJECT_CATEGORIES:
        return _decision("reject", "critical", f"{request.content_category.value}_category")
    if request.content_category in _REVIEW_CATEGORIES:
        return _decision("review", "high", f"{request.content_category.value}_category_requires_review")
    if request.content_category in {ContentCategory.rule, ContentCategory.goal}:
        return _decision("review", "medium", f"{request.content_category.value}_category_requires_review")
    if request.evidence_level is not EvidenceLevel.explicit_user_statement:
        return _decision("review", "medium", f"{request.evidence_level.value}_requires_review")
    return None


def check_target_path_safety(request: WritePolicyRequest) -> WritePolicyDecision | None:
    target_path = request.target_path.replace("\\", "/")
    path = PurePosixPath(target_path)
    if path.is_absolute() or ".." in path.parts:
        return _decision("reject", "critical", "target_path_outside_vault", reversible=False)
    if not target_path.strip() or target_path.startswith("."):
        return _decision("reject", "high", "unsafe_target_path")
    return None


def check_write_frequency(request: WritePolicyRequest) -> WritePolicyDecision | None:
    if not request.source_run_id:
        return None
    now = time.monotonic()
    key = request.source_run_id
    with _WRITE_TIMESTAMPS_LOCK:
        timestamps = [
            timestamp
            for timestamp in _WRITE_TIMESTAMPS.get(key, [])
            if now - timestamp < _WRITE_LIMIT_WINDOW_SECONDS
        ]
        timestamps.append(now)
        _WRITE_TIMESTAMPS[key] = timestamps
        limit_exceeded = len(timestamps) > _WRITE_LIMIT_COUNT
    if limit_exceeded:
        return _decision("review", "medium", "write_frequency_limit_exceeded")
    return None


CHECKS: tuple[Checker, ...] = (
    check_credential_leak,
    check_sensitive_pii,
    check_crisis_content,
    check_evidence_level,
    check_content_category,
    check_target_path_safety,
    check_write_frequency,
)


def reset_write_frequency_state() -> None:
    with _WRITE_TIMESTAMPS_LOCK:
        _WRITE_TIMESTAMPS.clear()


def evaluate_write_policy(request: WritePolicyRequest) -> WritePolicyDecision:
    for check in CHECKS:
        decision = check(request)
        if decision is not None:
            return decision
    return WritePolicyDecision(
        allowed=True,
        decision="auto",
        risk_tier="low",
        reasons=[],
        reversible=True,
    )


def _metadata_enum_value(
    metadata: Mapping[str, str],
    key: str,
    default: EvidenceLevel | ContentCategory,
) -> str:
    value = metadata.get(key) or metadata.get(key.replace("_", ""))
    if value is None and key == "content_category":
        value = metadata.get("category")
    return str(value or default.value)


def _coerce_content_category(raw_value: str) -> ContentCategory:
    alias_map = {
        "profile": ContentCategory.preference,
        "preference": ContentCategory.preference,
        "fact": ContentCategory.fact,
        "event": ContentCategory.event,
        "goal": ContentCategory.goal,
        "rule": ContentCategory.rule,
        "medical": ContentCategory.health,
        "health": ContentCategory.health,
        "finance": ContentCategory.financial,
        "financial": ContentCategory.financial,
        "legal": ContentCategory.legal,
        "identity": ContentCategory.identity,
        "crisis": ContentCategory.crisis,
        "credential": ContentCategory.credential,
        "companion_memory": ContentCategory.preference,
        "model_fact": ContentCategory.fact,
    }
    try:
        return ContentCategory(raw_value)
    except ValueError:
        return alias_map.get(raw_value, ContentCategory.preference)


def _legacy_write_request(request: MarkdownWritePolicyRequest) -> WritePolicyRequest:
    evidence_level = EvidenceLevel(
        _metadata_enum_value(request.metadata, "evidence_level", EvidenceLevel.explicit_user_statement)
    )
    content_category = _coerce_content_category(
        _metadata_enum_value(request.metadata, "content_category", ContentCategory.preference)
    )
    return WritePolicyRequest(
        scope=request.scope,
        target_path=request.target_path,
        content="\n".join([request.title, request.content]),
        source_message=str(request.metadata.get("source_message", "")),
        source_run_id=str(request.metadata.get("source_run_id", "")),
        evidence_level=evidence_level,
        content_category=content_category,
        metadata=dict(request.metadata),
    )


def evaluate_markdown_write(request: MarkdownWritePolicyRequest) -> MarkdownWritePolicyDecision:
    try:
        core_request = _legacy_write_request(request)
    except ValueError as exc:
        return MarkdownWritePolicyDecision(
            allowed=False,
            reason="invalid_policy_metadata",
            risk_tier="high",
            decision="ask",
            reversible=request.reversible,
            metadata={**request.metadata, "error": str(exc)},
        )

    core_decision = evaluate_write_policy(core_request)
    if core_decision.decision == "reject":
        return MarkdownWritePolicyDecision(
            allowed=False,
            reason=core_decision.reasons[0] if core_decision.reasons else "rejected",
            risk_tier=core_decision.risk_tier,
            decision="ask",
            reversible=request.reversible and core_decision.reversible,
            metadata=request.metadata,
        )
    if core_decision.decision == "review":
        return MarkdownWritePolicyDecision(
            allowed=False,
            reason=core_decision.reasons[0] if core_decision.reasons else "review_required",
            risk_tier=core_decision.risk_tier,
            decision="ask",
            reversible=request.reversible and core_decision.reversible,
            metadata=request.metadata,
        )
    return MarkdownWritePolicyDecision(
        allowed=True,
        risk_tier=core_decision.risk_tier,
        decision="auto",
        reversible=request.reversible and core_decision.reversible,
        metadata=request.metadata,
    )
