from __future__ import annotations

import sqlite3

from apps.backend.tests._schema import migrate_db
from app.models.api import MemoryRecallPermissions, MemorySearchResult
from app.services.memory_activation import MemoryActivationDecision, MemoryActivationItem
from app.services.memory_permissions import (
    MemoryActivationEventRecorder,
    permissions_from_activation_decision,
    split_recall_prompt_sections,
)
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier
from app.utils.public_references import public_memory_reference


def _item(
    *,
    memory_kind: MemoryKind = MemoryKind.PREFERENCE,
    memory_scope: MemoryScope = MemoryScope.GLOBAL,
    text: str = "Ada dislikes preachy answers",
) -> MemoryActivationItem:
    return MemoryActivationItem(
        memory_id="memory-1",
        target_type="fact",
        memory_kind=memory_kind,
        memory_scope=memory_scope,
        lifecycle_status=LifecycleStatus.ACTIVE,
        source_scope="graph_facts",
        text=text,
        confidence=0.9,
        importance=0.8,
        evidence_count=2,
        risk_tier=RiskTier.LOW,
    )


def _decision(item: MemoryActivationItem) -> MemoryActivationDecision:
    return MemoryActivationDecision(
        item=item,
        allowed=True,
        activation_score=0.85,
        score_breakdown={"query_relevance": 0.2},
        can_style_response=True,
        can_answer_context=True,
        can_proactively_mention=True,
        can_suggest_action=True,
    )


def _result(
    *,
    snippet: str,
    permissions: MemoryRecallPermissions,
    memory_kind: str | None = None,
    fact_id: str | None = None,
) -> MemorySearchResult:
    return MemorySearchResult(
        note_id=fact_id or "note-1",
        chunk_id="chunk-1",
        relative_path="MemoryGraph/LongTerm",
        title="Structured Long-Term Memory",
        heading="Profile",
        snippet=snippet,
        score=0.9,
        source_scope="personal_memory",
        retrieval_mode="graph_activation",
        recall_permissions=permissions,
        activation_score=0.82,
        score_breakdown={"query_relevance": 0.2},
        memory_kind=memory_kind,
        fact_id=fact_id,
    )


def test_recent_pressure_memory_is_style_only_when_query_is_unrelated() -> None:
    permissions = permissions_from_activation_decision(
        _decision(
            _item(
                memory_kind=MemoryKind.RECENT_STATE,
                memory_scope=MemoryScope.TEMPORARY,
                text="Ada has been under pressure recently",
            )
        ),
        query="Explain Python decorators",
    )

    assert permissions.can_style_response is True
    assert permissions.can_answer_context is False
    assert permissions.can_proactively_mention is False


def test_project_context_requires_relevant_project_query() -> None:
    decision = _decision(
        _item(
            memory_kind=MemoryKind.PROJECT_CONTEXT,
            memory_scope=MemoryScope.PROJECT,
            text="Ada is working on project Atlas",
        )
    )

    unrelated = permissions_from_activation_decision(decision, query="What is my coding style?")
    related = permissions_from_activation_decision(decision, query="What is the status of project Atlas?")

    assert unrelated.can_answer_context is False
    assert unrelated.can_proactively_mention is False
    assert related.can_answer_context is True
    assert related.can_suggest_action is True


def test_prompt_sections_keep_style_memory_out_of_raw_answer_context() -> None:
    pressure = _result(
        snippet="Ada has been under pressure recently",
        permissions=MemoryRecallPermissions(can_style_response=True, can_answer_context=False),
        memory_kind=MemoryKind.RECENT_STATE.value,
    )
    preference = _result(
        snippet="Ada dislikes preachy answers",
        permissions=MemoryRecallPermissions(can_style_response=True, can_answer_context=True),
        memory_kind=MemoryKind.PREFERENCE.value,
    )

    sections = split_recall_prompt_sections([pressure, preference], query="Explain decorators")

    style_text = "\n".join(sections.style_hints)
    answer_text = "\n".join(sections.answer_context_lines)
    assert "low-pressure tone" in style_text
    assert "Ada has been under pressure recently" not in answer_text
    assert "Ada dislikes preachy answers" in answer_text
    assert sections.usages[0].used_for_style is True
    assert sections.usages[0].used_for_answer_context is False


def test_prompt_context_uses_safe_source_and_opaque_citation_references() -> None:
    raw_fact_id = "internal-fact-id-must-not-enter-prompt"
    citation_ref = public_memory_reference("citation", "Wiki/Projects/Atlas.md")
    result = _result(
        snippet="Ada works on Atlas",
        permissions=MemoryRecallPermissions(can_answer_context=True),
        memory_kind=MemoryKind.PROJECT_CONTEXT.value,
        fact_id=raw_fact_id,
    ).model_copy(
        update={
            "relative_path": "Wiki/Projects/Atlas.md",
            "citation_refs": [citation_ref],
        }
    )

    sections = split_recall_prompt_sections([result], query="What is the status of project Atlas?")

    line = sections.answer_context_lines[0]
    assert "source=Wiki/Projects/Atlas.md" in line
    assert f"citations={citation_ref}" in line
    assert raw_fact_id not in line


def test_prompt_context_rejects_absolute_sources_and_sensitive_memory() -> None:
    absolute_source = _result(
        snippet="safe eligible context",
        permissions=MemoryRecallPermissions(can_answer_context=True),
    ).model_copy(update={"relative_path": r"C:\Users\Alice\Vault\Secret.md"})
    sensitive = _result(
        snippet="private medical detail",
        permissions=MemoryRecallPermissions(
            can_style_response=True,
            can_answer_context=True,
            can_proactively_mention=True,
            can_suggest_action=True,
        ),
    ).model_copy(
        update={
            "memory_scope": MemoryScope.SENSITIVE.value,
            "risk_tier": RiskTier.HIGH.value,
        }
    )

    sections = split_recall_prompt_sections([absolute_source, sensitive], query="safe eligible context")

    assert sections.answer_context_lines == ("- source=(none) / Profile: safe eligible context",)
    assert "Alice" not in "\n".join(sections.answer_context_lines)
    assert "private medical detail" not in "\n".join(
        (*sections.style_hints, *sections.answer_context_lines, *sections.proactive_mention_lines)
    )


def test_activation_recorder_writes_usage_permissions(tmp_path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    recorder = MemoryActivationEventRecorder(db_path)
    result = _result(
        snippet="Ada dislikes preachy answers",
        permissions=MemoryRecallPermissions(can_style_response=True, can_answer_context=True),
    )

    recorder.record_usage(
        result=result,
        conversation_id=None,
        message_id=None,
        agent_run_id=None,
        used_for_style=True,
        used_for_answer_context=True,
        used_for_proactive_mention=False,
        used_for_action_suggestion=False,
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM memory_activation_events").fetchone()

    assert row is not None
    assert row[7] == '{"can_answer_context":true,"can_proactively_mention":false,"can_style_response":true,"can_suggest_action":false}'
    assert row[9] == 1
    assert row[10] == 1
