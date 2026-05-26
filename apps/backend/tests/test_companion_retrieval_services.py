from __future__ import annotations

from apps.backend.tests._schema import migrate_db
from app.models.api import MemorySearchResult
from app.services.companion_retrieval import CompanionRetrievalReportStore, rerank_memory_context


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
