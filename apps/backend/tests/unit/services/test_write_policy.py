from __future__ import annotations

import pytest

from app.services.write_policy import (
    ContentCategory,
    EvidenceLevel,
    WritePolicyDecision,
    WritePolicyRequest,
    check_content_category,
    check_credential_leak,
    check_crisis_content,
    check_evidence_level,
    check_sensitive_pii,
    check_target_path_safety,
    check_write_frequency,
    evaluate_write_policy,
    reset_write_frequency_state,
)


def _request(
    *,
    content: str = "用户明确说喜欢苹果。",
    source_message: str = "用户明确说喜欢苹果。",
    source_run_id: str = "test-run",
    target_path: str = "Memories/LongTerm/Preferences.md",
    evidence_level: EvidenceLevel = EvidenceLevel.explicit_user_statement,
    content_category: ContentCategory = ContentCategory.preference,
) -> WritePolicyRequest:
    return WritePolicyRequest(
        scope="long_term_memory",
        target_path=target_path,
        content=content,
        source_message=source_message,
        source_run_id=source_run_id,
        evidence_level=evidence_level,
        content_category=content_category,
        metadata={},
    )


def _assert_decision(
    decision: WritePolicyDecision | None,
    *,
    expected: str,
    risk_tier: str,
    reason: str,
    allowed: bool = False,
) -> None:
    assert decision is not None
    assert decision.allowed is allowed
    assert decision.decision == expected
    assert decision.risk_tier == risk_tier
    assert decision.reasons == [reason]


@pytest.mark.parametrize(
    "category",
    [
        ContentCategory.preference,
        ContentCategory.fact,
        ContentCategory.event,
        ContentCategory.goal,
        ContentCategory.rule,
        ContentCategory.health,
        ContentCategory.financial,
        ContentCategory.legal,
        ContentCategory.relationship,
        ContentCategory.identity,
        ContentCategory.crisis,
        ContentCategory.credential,
    ],
)
def test_rejects_api_key_in_any_category(category: ContentCategory) -> None:
    decision = check_credential_leak(
        _request(content="sk-abcdefghijklmnopqrstuvwxyz123456", content_category=category)
    )

    _assert_decision(decision, expected="reject", risk_tier="critical", reason="api_key")
    assert decision.reversible is False


def test_rejects_credential_keyword() -> None:
    decision = check_credential_leak(_request(content="这里保存了密码：correct-horse-battery-staple"))

    _assert_decision(decision, expected="reject", risk_tier="critical", reason="credential")
    assert decision.reversible is False


def test_allows_content_without_credentials() -> None:
    assert check_credential_leak(_request()) is None


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("用户的身份证是示例内容。", "identity"),
        ("用户的手机号是示例内容。", "contact"),
    ],
)
def test_rejects_sensitive_pii(content: str, reason: str) -> None:
    decision = check_sensitive_pii(_request(content=content))

    _assert_decision(decision, expected="reject", risk_tier="high", reason=reason)


def test_rejects_phone_number_in_identity_category() -> None:
    decision = check_sensitive_pii(
        _request(content="用户的手机号是示例内容。", content_category=ContentCategory.identity)
    )

    _assert_decision(decision, expected="reject", risk_tier="high", reason="contact")


def test_allows_content_without_sensitive_pii() -> None:
    assert check_sensitive_pii(_request()) is None


@pytest.mark.parametrize(
    "evidence_level",
    [
        EvidenceLevel.explicit_user_statement,
        EvidenceLevel.derived_from_repeated_behavior,
        EvidenceLevel.assistant_summary,
        EvidenceLevel.uncertain_inference,
        EvidenceLevel.external_source,
    ],
)
def test_rejects_crisis_content_regardless_of_evidence(evidence_level: EvidenceLevel) -> None:
    decision = check_crisis_content(
        _request(content="用户提到了自伤风险。", evidence_level=evidence_level)
    )

    _assert_decision(decision, expected="reject", risk_tier="critical", reason="crisis")
    assert decision.reversible is False


def test_allows_content_without_crisis_terms() -> None:
    assert check_crisis_content(_request()) is None


@pytest.mark.parametrize("category", [ContentCategory.rule, ContentCategory.goal])
def test_reject_for_uncertain_inference_rule(category: ContentCategory) -> None:
    decision = check_evidence_level(
        _request(evidence_level=EvidenceLevel.uncertain_inference, content_category=category)
    )

    _assert_decision(
        decision,
        expected="reject",
        risk_tier="high",
        reason="uncertain_inference_requires_rejection",
    )


def test_review_required_for_uncertain_inference_fact() -> None:
    decision = check_evidence_level(
        _request(evidence_level=EvidenceLevel.uncertain_inference, content_category=ContentCategory.fact)
    )

    _assert_decision(
        decision,
        expected="review",
        risk_tier="medium",
        reason="uncertain_inference_requires_review",
    )


@pytest.mark.parametrize(
    "evidence_level",
    [
        EvidenceLevel.explicit_user_statement,
        EvidenceLevel.derived_from_repeated_behavior,
        EvidenceLevel.assistant_summary,
        EvidenceLevel.external_source,
    ],
)
def test_evidence_check_allows_non_uncertain_evidence(evidence_level: EvidenceLevel) -> None:
    assert check_evidence_level(_request(evidence_level=evidence_level)) is None


@pytest.mark.parametrize("category", [ContentCategory.crisis, ContentCategory.credential])
def test_content_category_rejects_critical_categories(category: ContentCategory) -> None:
    decision = check_content_category(_request(content_category=category))

    _assert_decision(
        decision,
        expected="reject",
        risk_tier="critical",
        reason=f"{category.value}_category",
    )


@pytest.mark.parametrize(
    "category",
    [ContentCategory.health, ContentCategory.financial, ContentCategory.legal, ContentCategory.identity],
)
def test_content_category_reviews_sensitive_categories(category: ContentCategory) -> None:
    decision = check_content_category(_request(content_category=category))

    _assert_decision(
        decision,
        expected="review",
        risk_tier="high",
        reason=f"{category.value}_category_requires_review",
    )


@pytest.mark.parametrize("category", [ContentCategory.rule, ContentCategory.goal])
def test_content_category_reviews_rule_and_goal(category: ContentCategory) -> None:
    decision = check_content_category(_request(content_category=category))

    _assert_decision(
        decision,
        expected="review",
        risk_tier="medium",
        reason=f"{category.value}_category_requires_review",
    )


@pytest.mark.parametrize(
    "evidence_level",
    [
        EvidenceLevel.derived_from_repeated_behavior,
        EvidenceLevel.assistant_summary,
        EvidenceLevel.external_source,
    ],
)
def test_content_category_reviews_non_explicit_evidence(evidence_level: EvidenceLevel) -> None:
    decision = check_content_category(_request(evidence_level=evidence_level))

    _assert_decision(
        decision,
        expected="review",
        risk_tier="medium",
        reason=f"{evidence_level.value}_requires_review",
    )


@pytest.mark.parametrize(
    "category",
    [ContentCategory.preference, ContentCategory.fact, ContentCategory.event, ContentCategory.relationship],
)
def test_auto_approves_explicit_preference_without_sensitive_content(category: ContentCategory) -> None:
    assert check_content_category(_request(content_category=category)) is None


@pytest.mark.parametrize(
    ("target_path", "risk_tier", "reason", "reversible"),
    [
        ("/outside-vault.md", "critical", "target_path_outside_vault", False),
        ("../outside-vault.md", "critical", "target_path_outside_vault", False),
        ("", "high", "unsafe_target_path", True),
        (".hidden.md", "high", "unsafe_target_path", True),
    ],
)
def test_path_outside_vault_is_rejected(
    target_path: str,
    risk_tier: str,
    reason: str,
    reversible: bool,
) -> None:
    decision = check_target_path_safety(_request(target_path=target_path))

    _assert_decision(decision, expected="reject", risk_tier=risk_tier, reason=reason)
    assert decision.reversible is reversible


def test_target_path_check_allows_safe_relative_path() -> None:
    assert check_target_path_safety(_request(target_path="Memories/LongTerm/Preferences.md")) is None


def test_frequency_limit_triggers_review_after_10_writes() -> None:
    reset_write_frequency_state()
    request = _request(source_run_id="frequency-test-run")

    decisions = [check_write_frequency(request) for _ in range(11)]

    assert decisions[:10] == [None] * 10
    _assert_decision(
        decisions[10],
        expected="review",
        risk_tier="medium",
        reason="write_frequency_limit_exceeded",
    )


def test_frequency_check_ignores_missing_run_id() -> None:
    reset_write_frequency_state()

    assert check_write_frequency(_request(source_run_id="")) is None


def test_reasons_list_is_never_empty_on_rejection() -> None:
    decision = evaluate_write_policy(_request(content="sk-abcdefghijklmnopqrstuvwxyz123456"))

    assert decision.decision == "reject"
    assert decision.reasons
