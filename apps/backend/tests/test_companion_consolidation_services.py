from __future__ import annotations

from apps.backend.tests._schema import migrate_db_with_vault
from app.models.enums import MemoryFactStatus
from app.services.companion_consolidation import CompanionConsolidationService
from app.services.diary_memory import DiaryMemoryObjectSource, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryObject
from app.services.memory_graph import MemoryGraphStore


def diary_object(summary: str, *, confidence: float = 0.95) -> DiaryMemoryObject:
    return DiaryMemoryObject(
        summary=summary,
        topic="coding style",
        emotion="focused",
        people=("Ada",),
        keywords=("style",),
        source_text=summary,
        importance=0.8,
        confidence=confidence,
        status=MemoryFactStatus.ACTIVE,
    )


def test_companion_consolidation_creates_candidate_graph_facts_without_markdown(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    diary_store = DiaryMemoryStore(db_path)
    inserted = diary_store.insert_object(
        vault_id="vault-1",
        extracted=diary_object("Ada prefers concise status updates."),
        occurred_at="2026-05-15T10:00:00+08:00",
        timezone="Asia/Shanghai",
        source=DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-1"),
        extraction_model="fake",
    )
    assert inserted is not None
    diary_store.close()

    graph_store = MemoryGraphStore(db_path)
    service = CompanionConsolidationService(db_path, vault_id="vault-1", graph_store=graph_store)

    result = service.run_once(
        from_="2026-05-15T00:00:00+08:00",
        to="2026-05-16T00:00:00+08:00",
    )
    second = service.run_once(
        from_="2026-05-15T00:00:00+08:00",
        to="2026-05-16T00:00:00+08:00",
    )
    facts = graph_store.list_facts(status=MemoryFactStatus.CANDIDATE)
    service.close()
    graph_store.close()

    assert result.status == "completed"
    assert result.source_count == 1
    assert result.output_count == 1
    assert result.fact_ids == second.fact_ids
    assert len(facts) == 1
    assert facts[0].status == MemoryFactStatus.CANDIDATE
    assert facts[0].source_type == "diary_memory_object"
    assert facts[0].memory_type == "event"
    assert not list(tmp_path.rglob("*.md"))


def test_companion_consolidation_records_empty_window(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    diary_store = DiaryMemoryStore(db_path)
    diary_store.close()
    graph_store = MemoryGraphStore(db_path)
    service = CompanionConsolidationService(db_path, vault_id="vault-1", graph_store=graph_store)

    result = service.run_once(from_="2026-05-01T00:00:00+08:00", to="2026-05-02T00:00:00+08:00")
    service.close()
    graph_store.close()

    assert result.status == "completed"
    assert result.source_count == 0
    assert result.output_count == 0
    assert result.reason == "no_active_diary_objects"
