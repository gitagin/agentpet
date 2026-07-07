from __future__ import annotations

import json
import sqlite3

from apps.backend.tests._schema import migrate_db, migrate_db_with_vault
from app.agents.memory_router import MemoryRoute
from app.models.api import MemorySearchResult
from app.models.enums import MemoryFactStatus
from app.services.companion_retrieval import (
    CompanionRetrievalBudget,
    CompanionRetrievalReportStore,
    CompanionRetrievalService,
    rerank_memory_context,
)
from app.services.diary_memory import DiaryMemoryObjectSource, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryObject
from app.services.memory_graph import MemoryFactCandidate, MemoryGraphStore


def result(
    *,
    scope: str,
    path: str,
    snippet: str,
    score: float,
    chunk_id: str | None = None,
) -> MemorySearchResult:
    return MemorySearchResult(
        note_id=chunk_id or path,
        chunk_id=chunk_id or path,
        relative_path=path,
        title=path,
        snippet=snippet,
        score=score,
        source_scope=scope,
    )


def test_companion_rerank_reports_drop_reasons_and_budget() -> None:
    reranked = rerank_memory_context(
        [
            result(scope="daily_chat", path="Daily.md", snippet="daily context", score=0.8),
            result(scope="personal_memory", path="Profile.md", snippet="preferred style", score=0.9),
            result(scope="personal_memory", path="Profile.md", snippet="preferred style", score=0.7),
            result(scope="personal_memory", path="Extra.md", snippet="extra personal context", score=0.6),
            result(scope="diary_objects", path="Diary/1", snippet="structured diary context", score=1.2),
        ],
        preferred_scopes=("personal_memory", "diary_objects", "daily_chat"),
        limit=3,
        per_scope_limit=1,
        char_budget=64,
    )

    assert [item.source_scope for item in reranked.selected] == [
        "personal_memory",
        "diary_objects",
        "daily_chat",
    ]
    assert reranked.telemetry.candidate_count == 5
    assert reranked.telemetry.selected_count == 3
    assert reranked.telemetry.duplicate_drop_count == 1
    assert reranked.telemetry.per_scope_drop_count == 1
    assert reranked.telemetry.item_budget == 3
    assert reranked.telemetry.per_scope_limit == 1
    assert reranked.telemetry.used_chars > 0
    assert reranked.telemetry.source_counts["personal_memory"] == 3


def test_companion_retrieval_report_store_redacts_query_to_hash(tmp_path) -> None:
    store = CompanionRetrievalReportStore(migrate_db(tmp_path / "state.sqlite3"))
    reranked = rerank_memory_context(
        [result(scope="personal_memory", path="Profile.md", snippet="secret-free context", score=1.0)],
        preferred_scopes=("personal_memory",),
        limit=5,
        per_scope_limit=2,
    )

    report = store.record(
        agent_run_id="run-1",
        query="my private query with token=should-not-appear",
        telemetry=reranked.telemetry,
    )
    listed = store.list_reports(agent_run_id="run-1")
    db_bytes = (tmp_path / "state.sqlite3").read_bytes()
    store.close()

    assert report.strategy == "deterministic_v1"
    assert listed[0].id == report.id
    assert listed[0].source_counts == {"personal_memory": 1}
    assert b"should-not-appear" not in db_bytes
    assert b"my private query" not in db_bytes
    assert listed[0].explainability["candidate_recall_count"] == 1


def test_companion_retrieval_report_store_explains_prompt_usage_without_raw_text(tmp_path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    store = CompanionRetrievalReportStore(db_path)
    reranked = rerank_memory_context(
        [
            result(scope="personal_memory", path="Profile.md", snippet="answer context", score=1.0),
            result(scope="personal_memory", path="Style.md", snippet="style context", score=0.9),
            result(scope="personal_memory", path="Filtered.md", snippet="filtered context", score=0.8),
        ],
        preferred_scopes=("personal_memory",),
        limit=5,
        per_scope_limit=5,
    )
    store.record(agent_run_id="run-explain", query="query text with token=should-not-leak", telemetry=reranked.telemetry)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memory_activation_events (
                id, candidate_id, fact_id, agent_run_id, activation_score,
                permissions_json, score_breakdown_json, used_for_style,
                used_for_answer_context, used_for_proactive_mention,
                used_for_action_suggestion, filtered_reason, created_at
            )
            VALUES
                (?, NULL, ?, ?, ?, ?, ?, 0, 1, 0, 0, NULL, ?),
                (?, ?, NULL, ?, ?, ?, ?, 1, 0, 0, 0, NULL, ?),
                (?, NULL, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?)
            """,
            (
                "activation-answer",
                "fact-answer",
                "run-explain",
                0.91,
                json.dumps({"can_answer_context": True}),
                json.dumps({"query_relevance": 0.25}),
                "2026-06-07T00:00:00Z",
                "activation-style",
                "candidate-style",
                "run-explain",
                0.72,
                json.dumps({"can_style_response": True}),
                json.dumps({"conflict_penalty": -0.16}),
                "2026-06-07T00:00:01Z",
                "activation-filtered",
                "fact-filtered",
                "run-explain",
                0.2,
                json.dumps({}),
                json.dumps({"expired_penalty": -0.22}),
                "sensitive_memory Authorization: Bearer report-secret-token",
                "2026-06-07T00:00:02Z",
            ),
        )

    report = store.list_reports(agent_run_id="run-explain")[0]
    store.close()

    explainability = report.explainability
    assert explainability["candidate_recall_count"] == 3
    assert explainability["prompt_memory_ids"] == ["fact-answer", "candidate-style"]
    assert explainability["permissions_used"] == {
        "style": 1,
        "answer_context": 1,
        "proactive_mention": 0,
        "action_suggestion": 0,
    }
    assert explainability["gates"] == {"expired": 1, "conflict": 1, "sensitive": 1}
    assert explainability["activation_score_breakdowns"][0]["score_breakdown"]["query_relevance"] == 0.25
    filtered = explainability["filtered_item_reasons"][0]
    assert filtered["memory_id"] == "fact-filtered"
    assert "[REDACTED]" in filtered["reason"]
    assert "report-secret-token" not in json.dumps(explainability)
    assert "answer context" not in json.dumps(explainability)


def test_companion_retrieval_applies_activation_to_graph_facts(tmp_path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    graph_store = MemoryGraphStore(db_path)
    service = CompanionRetrievalService(graph_store=graph_store, telemetry_db=graph_store.conn)
    try:
        active = _graph_fact(
            graph_store,
            category="preference",
            subject="coding style",
            predicate="prefers",
            object_value="concise status updates",
        )
        stale_boundary = _graph_fact(
            graph_store,
            category="boundary",
            subject="status updates",
            predicate="must",
            object_value="stay concise",
            confidence=0.95,
            importance=0.9,
        )
        stale_boundary = graph_store.update_status(stale_boundary.id, MemoryFactStatus.STALE, reason="old_boundary")
        forgotten = _graph_fact(
            graph_store,
            category="preference",
            subject="forgotten coding style",
            predicate="prefers",
            object_value="verbose essays",
        )
        rejected = _graph_fact(
            graph_store,
            category="preference",
            subject="rejected coding style",
            predicate="prefers",
            object_value="status noise",
        )
        superseded = _graph_fact(
            graph_store,
            category="preference",
            subject="old coding style",
            predicate="prefers",
            object_value="lengthy updates",
        )
        expired_recent = _graph_fact(
            graph_store,
            category="recent_state",
            subject="project alpha",
            predicate="status",
            object_value="blocked",
            expires_at="2020-01-01T00:00:00+00:00",
        )
        graph_store.update_status(forgotten.id, MemoryFactStatus.FORGOTTEN, reason="user_forget")
        graph_store.update_status(rejected.id, MemoryFactStatus.REJECTED, reason="user_reject")
        graph_store.update_status(
            superseded.id,
            MemoryFactStatus.SUPERSEDED,
            reason="corrected",
            superseded_by=active.id,
        )

        result = service.retrieve(
            vault_id="vault-1",
            query="coding style concise status updates",
            route=MemoryRoute(primary_scopes=("graph_facts",), query="coding style concise status updates"),
            budget=CompanionRetrievalBudget(max_items=8, max_graph_facts=8),
        )
    finally:
        service.close()
        graph_store.close()

    recalled_ids = {item.source_id for item in result.items}
    assert active.id in recalled_ids
    assert stale_boundary.id in recalled_ids
    assert forgotten.id not in recalled_ids
    assert rejected.id not in recalled_ids
    assert superseded.id not in recalled_ids
    assert expired_recent.id not in recalled_ids
    assert all(item.retrieval_mode == "graph_activation" for item in result.items)
    assert result.telemetry.counts["activation_filtered_items"] >= 4
    assert result.telemetry.counts["raw_items_seen"] >= 6


def test_companion_retrieval_finds_typed_diary_qa_and_project_update(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    store = DiaryMemoryStore(db_path)
    service = CompanionRetrievalService(diary_store=store, telemetry_db=store.conn)
    try:
        source = DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-qa")
        store.insert_object(
            vault_id="vault-1",
            extracted=DiaryMemoryObject(
                summary="User asked how to compare parser options.",
                topic="parser choice",
                emotion="calm",
                people=(),
                keywords=("parser", "qa"),
                source_text="User asked how to compare parser options.",
                importance=0.8,
                confidence=0.9,
                status=MemoryFactStatus.ACTIVE,
                type="qa",
            ),
            occurred_at="2026-05-13T10:30:00+08:00",
            timezone="Asia/Shanghai",
            source=source,
        )
        store.insert_object(
            vault_id="vault-1",
            extracted=DiaryMemoryObject(
                summary="Project Atlas decision moved to next week.",
                topic="Project Atlas",
                emotion="focused",
                people=(),
                keywords=("atlas", "decision"),
                source_text="Project Atlas decision moved to next week.",
                importance=0.9,
                confidence=0.92,
                status=MemoryFactStatus.ACTIVE,
                type="project_update",
            ),
            occurred_at="2026-05-13T11:30:00+08:00",
            timezone="Asia/Shanghai",
            source=DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-project"),
        )

        result = service.retrieve(
            vault_id="vault-1",
            query="parser Atlas decision",
            route=MemoryRoute(primary_scopes=("diary_objects",), query="parser Atlas decision"),
            budget=CompanionRetrievalBudget(max_items=4, max_diary_objects=4),
        )
    finally:
        service.close()
        store.close()

    texts = [item.text for item in result.items]
    assert any("parser options" in text for text in texts)
    assert any("Project Atlas decision" in text for text in texts)
    assert all(item.source_scope == "diary_objects" for item in result.items)
    assert all(item.retrieval_mode == "diary_object" for item in result.items)


def _graph_fact(
    store: MemoryGraphStore,
    *,
    category: str,
    subject: str,
    predicate: str,
    object_value: str,
    confidence: float = 0.9,
    importance: float = 0.8,
    expires_at: str | None = None,
):
    return store.upsert_candidate(
        MemoryFactCandidate(
            category=category,
            subject=subject,
            predicate=predicate,
            object=object_value,
            source_text=f"{subject} {predicate} {object_value}",
            confidence=confidence,
            importance=importance,
            expires_at=expires_at,
        )
    ).fact
