from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.services.retrieval_query import (
    ApprovedRetrievalContext,
    MAX_SEMANTIC_VARIANTS,
    RetrievalQueryPlanner,
    build_retrieval_plan,
    build_retrieval_plan_telemetry,
)


def test_deterministic_plan_normalizes_query_and_preserves_exact_atoms() -> None:
    query = '  Find   Alice Chen\nfrom 2026-07-01 to 2026-07-12 about "Project Night" and TASK-1205.  '

    plan = build_retrieval_plan(query)

    assert plan.lexical_query == 'Find Alice Chen from 2026-07-01 to 2026-07-12 about "Project Night" and TASK-1205.'
    assert plan.exact_terms == ("Project Night",)
    assert "TASK-1205" in plan.identifiers
    assert "Alice Chen" in plan.entities
    assert "Project Night" in plan.entities
    assert plan.date_range is not None
    assert plan.date_range.start == date(2026, 7, 1)
    assert plan.date_range.end == date(2026, 7, 12)
    assert plan.date_range.expressions == ("2026-07-01", "2026-07-12")
    assert plan.requested_channels == ("fts",)
    assert plan.planner_source == "deterministic"
    assert plan.fallback_reason == "model_output_unavailable"


def test_validated_model_output_is_bounded_by_caller_approved_scopes_and_channels() -> None:
    query = 'What did Alice Chen decide about "Project Night" in TASK-1205?'
    model_output = {
        "lexical_query": query,
        "semantic_variants": [
            'Alice Chen decision for "Project Night" in TASK-1205',
            'TASK-1205 outcome involving Alice Chen and "Project Night"',
        ],
        "exact_terms": ["Project Night"],
        "identifiers": ["TASK-1205"],
        "entities": ["Alice Chen", "Project Night"],
        "source_scopes": ["wiki", "graph"],
        "filters": {"status": "active"},
        "requested_channels": ["vector", "fts"],
        "confidence": 0.86,
    }

    plan = build_retrieval_plan(
        query,
        model_output=model_output,
        approved_source_scopes=("wiki", "vault_note"),
        requested_channels=("fts", "vector"),
        filters={"language": "en"},
    )

    assert plan.planner_source == "validated_model"
    assert plan.fallback_reason is None
    assert plan.source_scopes == ("wiki",)
    assert plan.requested_channels == ("vector", "fts")
    assert plan.filters == {"status": "active", "language": "en"}
    assert plan.confidence == pytest.approx(0.86)
    assert len(plan.semantic_variants) == 2
    assert all("Alice Chen" in variant for variant in plan.semantic_variants)
    assert all('"Project Night"' in variant for variant in plan.semantic_variants)
    assert all("TASK-1205" in variant for variant in plan.semantic_variants)


@pytest.mark.parametrize(
    "model_output",
    [
        "not-json",
        {"semantic_variants": ["a", "b", "c", "d"]},
        {"unknown_field": "not allowed"},
    ],
)
def test_invalid_model_output_falls_back_deterministically(model_output) -> None:
    plan = build_retrieval_plan("find the offline preference", model_output=model_output)

    assert plan.planner_source == "deterministic"
    assert plan.fallback_reason == "model_output_invalid"
    assert plan.semantic_variants == ()


def test_model_cannot_replace_identifier_name_date_or_quoted_term() -> None:
    query = 'Alice Chen recorded "Project Night" for TASK-1205 on 2026-07-12'
    model_output = {
        "lexical_query": 'Bob recorded "Other Project" for TASK-9999 on 2025-01-01',
        "semantic_variants": ["Bob project record"],
        "confidence": 0.99,
    }

    plan = build_retrieval_plan(query, model_output=model_output)

    assert plan.planner_source == "deterministic"
    assert plan.fallback_reason == "model_output_invalid"
    assert plan.lexical_query == query
    assert plan.exact_terms == ("Project Night",)
    assert "TASK-1205" in plan.identifiers
    assert "Alice Chen" in plan.entities
    assert plan.date_range is not None
    assert plan.date_range.start == date(2026, 7, 12)


def test_identifier_preservation_rejects_prefix_impersonation() -> None:
    plan = build_retrieval_plan(
        "find TASK-1205",
        model_output={"semantic_variants": ["find TASK-12050"]},
    )

    assert plan.identifiers == ("TASK-1205",)
    assert plan.planner_source == "deterministic"
    assert plan.fallback_reason == "model_output_invalid"
    assert plan.semantic_variants == ()


def test_mixed_case_entity_is_preserved_verbatim() -> None:
    replaced = build_retrieval_plan(
        "What did OpenAI decide about roadmap?",
        model_output={"semantic_variants": ["Open Anthropic roadmap decision"]},
    )
    preserved = build_retrieval_plan(
        "What did OpenAI decide about roadmap?",
        model_output={"semantic_variants": ["OpenAI roadmap decision"]},
    )

    assert "OpenAI" in replaced.entities
    assert replaced.planner_source == "deterministic"
    assert replaced.semantic_variants == ()
    assert preserved.planner_source == "validated_model"
    assert preserved.semantic_variants == ("OpenAI roadmap decision",)


def test_chinese_name_is_preserved_in_entities_and_model_variants() -> None:
    query = '张三提到 "离线模式" 属于 TASK-1205'
    model_output = {
        "semantic_variants": ['TASK-1205 中张三讨论 "离线模式"'],
        "entities": ["张三", "离线模式"],
    }

    plan = build_retrieval_plan(query, model_output=model_output)

    assert "张三" in plan.entities
    assert plan.semantic_variants == ('TASK-1205 中张三讨论 "离线模式"',)


def test_approved_context_only_resolves_pronoun_and_relative_date() -> None:
    context = ApprovedRetrievalContext(referent="Alice Chen", reference_date=date(2026, 7, 12))
    query = '昨天她提到 TASK-1205 的 "Index Plan"'

    plan = build_retrieval_plan(query, approved_context=context)

    assert plan.lexical_query == query
    assert plan.date_range is not None
    assert plan.date_range.start == date(2026, 7, 11)
    assert plan.date_range.end == date(2026, 7, 11)
    assert plan.context_resolution_count == 2
    assert len(plan.semantic_variants) == 2
    assert "Alice Chen" in plan.entities
    assert any("Alice Chen" in variant for variant in plan.semantic_variants)
    assert any("2026-07-11" in variant for variant in plan.semantic_variants)
    assert all("TASK-1205" in variant for variant in plan.semantic_variants)
    assert all("Index Plan" in variant for variant in plan.semantic_variants)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("前天", date(2026, 8, 4)),
        ("昨天", date(2026, 8, 5)),
        ("今天", date(2026, 8, 6)),
        ("后天", date(2026, 8, 8)),
    ],
)
def test_relative_date_uses_asia_shanghai_calendar_day(expression: str, expected: date) -> None:
    utc_time_after_shanghai_midnight = datetime(2026, 8, 5, 17, 0, tzinfo=timezone.utc)

    plan = build_retrieval_plan(
        f"我{expression}和你聊了什么",
        now=utc_time_after_shanghai_midnight,
    )

    assert plan.date_range is not None
    assert plan.date_range.start == expected
    assert plan.date_range.end == expected


def test_approved_context_is_narrow_and_rejects_raw_conversation_fields() -> None:
    with pytest.raises(ValidationError):
        ApprovedRetrievalContext.model_validate(
            {
                "referent": "Alice",
                "reference_date": "2026-07-12",
                "raw_conversation": "private raw context",
            }
        )


def test_context_is_not_used_when_query_has_no_pronoun_or_relative_time() -> None:
    context = ApprovedRetrievalContext(referent="DO_NOT_APPEND", reference_date=date(2026, 7, 12))

    plan = build_retrieval_plan("find TASK-1205", approved_context=context)

    assert plan.context_resolution_count == 0
    assert plan.semantic_variants == ()
    assert "DO_NOT_APPEND" not in plan.lexical_query
    assert "DO_NOT_APPEND" not in plan.entities


@pytest.mark.parametrize("privacy_flag", ["local_privacy", "sensitive"])
def test_privacy_policy_removes_vector_and_preserves_fts_fallback(privacy_flag: str) -> None:
    kwargs = {privacy_flag: True}

    plan = build_retrieval_plan(
        "semantic preference lookup",
        requested_channels=("vector", "active_memory"),
        **kwargs,
    )

    assert "vector" not in plan.requested_channels
    assert plan.requested_channels[0] == "fts"
    assert plan.requested_channels == ("fts", "active_memory")
    assert plan.privacy_filtered_channel_count == 1


def test_model_cannot_add_unapproved_vector_channel() -> None:
    plan = build_retrieval_plan(
        "find my preference",
        requested_channels=("fts",),
        model_output={"requested_channels": ["vector"], "confidence": 0.8},
    )

    assert plan.planner_source == "validated_model"
    assert plan.requested_channels == ("fts",)


def test_semantic_variants_never_exceed_contract_limit() -> None:
    context = ApprovedRetrievalContext(referent="Alice Chen", reference_date=date(2026, 7, 12))
    query = '昨天 she mentioned "Index Plan" in TASK-1205'
    model_output = {
        "semantic_variants": [
            '昨天 Alice Chen mentioned "Index Plan" in TASK-1205',
            'Alice Chen yesterday discussed "Index Plan" in TASK-1205',
            'TASK-1205 had Alice Chen mention "Index Plan" 昨天',
        ]
    }

    plan = RetrievalQueryPlanner().plan(query, approved_context=context, model_output=model_output)

    assert len(plan.semantic_variants) <= MAX_SEMANTIC_VARIANTS


def test_telemetry_contains_only_hashes_counts_and_no_raw_query_or_context() -> None:
    query = 'QUERY_SENTINEL find "PRIVATE_TERM" in TASK-1205'
    context = ApprovedRetrievalContext(referent="CONTEXT_SENTINEL", reference_date=date(2026, 7, 12))
    plan = build_retrieval_plan(query, approved_context=context)

    telemetry = build_retrieval_plan_telemetry(
        plan,
        original_query=query,
        approved_context=context,
    )
    payload = telemetry.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert len(telemetry.query_hash) == 64
    assert telemetry.approved_context_hash is not None
    assert len(telemetry.approved_context_hash) == 64
    assert "QUERY_SENTINEL" not in serialized
    assert "PRIVATE_TERM" not in serialized
    assert "TASK-1205" not in serialized
    assert "CONTEXT_SENTINEL" not in serialized
    assert all(
        key.endswith("_hash")
        or key.endswith("_count")
        or key == "schema_version"
        for key in payload
    )


def test_filters_are_bounded_and_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="retrieval_filter_key_invalid"):
        build_retrieval_plan("find note", filters={"raw_query": "must not be stored"})
