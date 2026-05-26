from __future__ import annotations

from app.services.write_policy import (
    ContentCategory,
    EvidenceLevel,
    MarkdownWritePolicyRequest,
    WritePolicyRequest,
    evaluate_markdown_write,
    evaluate_write_policy,
    reset_write_frequency_state,
)


def _request(
    *,
    content: str = "用户明确说喜欢苹果。",
    evidence_level: EvidenceLevel = EvidenceLevel.explicit_user_statement,
    content_category: ContentCategory = ContentCategory.preference,
) -> WritePolicyRequest:
    return WritePolicyRequest(
        scope="long_term_memory",
        target_path="Memories/LongTerm/Preferences.md",
        content=content,
        source_message="用户明确说喜欢苹果。",
        source_run_id="test-run",
        evidence_level=evidence_level,
        content_category=content_category,
        metadata={},
    )


def test_markdown_write_policy_allows_low_risk_content():
    reset_write_frequency_state()

    decision = evaluate_markdown_write(
        MarkdownWritePolicyRequest(
            scope="long_term_memory",
            target_path="Memories/LongTerm/Preferences.md",
            title="水果",
            content="- 内容：用户的水果是苹果",
        )
    )

    assert decision.allowed is True
    assert decision.risk_tier == "low"
    assert decision.decision == "auto"
    assert decision.reversible is True


def test_markdown_write_policy_rejects_sensitive_content():
    reset_write_frequency_state()

    decision = evaluate_markdown_write(
        MarkdownWritePolicyRequest(
            scope="wiki",
            target_path="Wiki/Secrets.md",
            title="Secrets",
            content="api_key = sk-secret-agent-memory-1234567890",
        )
    )

    assert decision.allowed is False
    assert decision.reason == "api_key"
    assert decision.risk_tier == "critical"
    assert decision.decision == "ask"


def test_write_policy_rejects_plaintext_api_key():
    reset_write_frequency_state()

    decision = evaluate_write_policy(
        _request(content="明文 API Key: sk-abcdefghijklmnopqrstuvwxyz123456")
    )

    assert decision.allowed is False
    assert decision.decision == "reject"
    assert decision.risk_tier == "critical"
    assert decision.reasons == ["api_key"]


def test_write_policy_rejects_uncertain_inference_rule():
    reset_write_frequency_state()

    decision = evaluate_write_policy(
        _request(
            content="用户可能要求以后都自动写入资料库。",
            evidence_level=EvidenceLevel.uncertain_inference,
            content_category=ContentCategory.rule,
        )
    )

    assert decision.allowed is False
    assert decision.decision == "reject"
    assert decision.reasons == ["uncertain_inference_requires_rejection"]


def test_write_policy_auto_approves_explicit_preference_without_sensitive_content():
    reset_write_frequency_state()

    decision = evaluate_write_policy(
        _request(
            content="用户明确说喜欢苹果。",
            evidence_level=EvidenceLevel.explicit_user_statement,
            content_category=ContentCategory.preference,
        )
    )

    assert decision.allowed is True
    assert decision.decision == "auto"
    assert decision.risk_tier == "low"
