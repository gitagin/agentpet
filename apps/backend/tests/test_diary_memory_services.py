from __future__ import annotations

import pytest

from apps.backend.tests._schema import migrate_db_with_vault
from app.models.enums import MemoryFactStatus
from app.services.diary_memory import (
    DiaryMemoryObjectSource,
    DiaryMemorySearch,
    DiaryMemoryService,
    DiaryMemoryStore,
    diary_records_to_search_results,
)
from app.services.diary_memory_extractor import DiaryMemoryObject


class FakeDiaryExtractor:
    def __init__(self, objects: list[DiaryMemoryObject]) -> None:
        self.objects = objects
        self.calls = []

    async def extract(self, diary_text: str, *, memory_date: str | None = None, source_path: str | None = None):
        self.calls.append((diary_text, memory_date, source_path))
        return self.objects


def memory_object(
    *,
    summary: str,
    type: str = "event",
    topic: str = "work",
    emotion: str = "anxious",
    people: tuple[str, ...] = ("manager",),
    keywords: tuple[str, ...] = ("resign", "pressure"),
    importance: float = 0.82,
    confidence: float = 0.9,
    status: MemoryFactStatus = MemoryFactStatus.ACTIVE,
) -> DiaryMemoryObject:
    return DiaryMemoryObject(
        summary=summary,
        topic=topic,
        emotion=emotion,
        people=people,
        keywords=keywords,
        source_text=summary,
        importance=importance,
        confidence=confidence,
        status=status,
        type=type,
    )


@pytest.mark.asyncio
async def test_diary_memory_service_archives_objects_sources_and_searches_fts(tmp_path):
    extractor = FakeDiaryExtractor(
        [
            memory_object(summary="User felt pressure at work and considered resigning."),
            memory_object(
                summary="User mentioned the manager conflict but confidence is lower.",
                confidence=0.55,
                status=MemoryFactStatus.QUARANTINED,
            ),
        ]
    )
    service = DiaryMemoryService(
        DiaryMemoryStore(migrate_db_with_vault(tmp_path / "state.sqlite3")),
        vault_id="vault-1",
        extractor=extractor,
        extraction_model="reflection_agent",
    )

    result = await service.archive_chat_exchange(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        agent_run_id="run-1",
        user_question="I argued with my manager and want to resign.",
        assistant_answer="That sounds stressful.",
        occurred_at="2026-05-13T10:30:00+08:00",
        markdown_path="Memories/Daily/2026/05/week/2026-05-13.md",
    )

    assert result.objects_seen == 2
    assert result.objects_written == 2
    assert extractor.calls[0][1] == "2026-05-13"
    records = service.search(DiaryMemorySearch(query="resign manager", top_k=5))
    assert [record.status for record in records] == [
        MemoryFactStatus.ACTIVE,
        MemoryFactStatus.QUARANTINED,
    ]
    assert records[0].extraction_model == "reflection_agent"
    assert records[0].type == "event"
    assert records[0].occurred_at == "2026-05-13T10:30:00+08:00"
    detail = service.get(records[0].id)
    assert detail.sources[0].conversation_id == "conversation-1"
    assert detail.sources[0].user_message_id == "user-1"
    assert detail.sources[0].assistant_message_id == "assistant-1"
    assert detail.sources[0].agent_run_id == "run-1"
    assert detail.sources[0].markdown_path == "Memories/Daily/2026/05/week/2026-05-13.md"
    service.close()


@pytest.mark.asyncio
async def test_diary_memory_service_uses_extracted_type_without_writing_vault_files(tmp_path):
    extractor = FakeDiaryExtractor(
        [
            memory_object(
                summary="User asked how to compare two parser options.",
                type="qa",
                topic="parser choice",
                keywords=("parser", "qa"),
            ),
            memory_object(
                summary="Project Atlas decision moved to next week.",
                type="project_update",
                topic="Project Atlas",
                emotion="focused",
                keywords=("atlas", "decision"),
            ),
        ]
    )
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    service = DiaryMemoryService(
        DiaryMemoryStore(db_path),
        vault_id="vault-1",
        extractor=extractor,
        extraction_model="reflection_agent",
    )

    result = await service.archive_chat_exchange(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        agent_run_id="run-typed",
        user_question="Compare parser options.",
        assistant_answer="We decided to revisit Project Atlas next week.",
        occurred_at="2026-05-13T10:30:00+08:00",
        markdown_path="Memories/Daily/2026/05/week/2026-05-13.md",
    )

    assert result.objects_seen == 2
    qa_records = service.search(DiaryMemorySearch(query="parser", type="qa", top_k=5))
    project_records = service.search(DiaryMemorySearch(query="Atlas", type="project_update", top_k=5))
    assert [record.type for record in qa_records] == ["qa"]
    assert [record.type for record in project_records] == ["project_update"]
    assert not (tmp_path / "Vault").exists()
    service.close()


def test_diary_memory_store_is_idempotent_per_source_and_hash(tmp_path):
    store = DiaryMemoryStore(migrate_db_with_vault(tmp_path / "state.sqlite3"))
    source = DiaryMemoryObjectSource(
        object_id="",
        source_type="chat_exchange",
        source_id="run-1",
        conversation_id="conversation-1",
    )
    extracted = memory_object(summary="User is worried about changing jobs.")

    first = store.insert_object(
        vault_id="vault-1",
        extracted=extracted,
        occurred_at="2026-05-13T10:30:00+08:00",
        timezone="Asia/Shanghai",
        source=source,
        extraction_model="fake-model",
    )
    second = store.insert_object(
        vault_id="vault-1",
        extracted=extracted,
        occurred_at="2026-05-13T10:30:00+08:00",
        timezone="Asia/Shanghai",
        source=source,
        extraction_model="fake-model",
    )

    assert first is not None
    assert second is None
    records = store.search(DiaryMemorySearch(query="changing jobs", top_k=5), vault_id="vault-1")
    assert len(records) == 1
    assert store.get(first.id).sources[0].source_id == "run-1"
    store.close()


def test_diary_memory_search_filters_and_returns_synthetic_memory_results(tmp_path):
    store = DiaryMemoryStore(migrate_db_with_vault(tmp_path / "state.sqlite3"))
    source = DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-1")
    store.insert_object(
        vault_id="vault-1",
        extracted=memory_object(
            summary="User felt angry after a meeting with Bob.",
            topic="work pressure",
            emotion="angry",
            people=("Bob",),
            keywords=("meeting", "pressure"),
            importance=0.7,
        ),
        occurred_at="2026-05-12T23:00:00+08:00",
        timezone="Asia/Shanghai",
        source=source,
    )
    store.insert_object(
        vault_id="vault-1",
        extracted=memory_object(
            summary="User planned a weekend trip with Alice.",
            topic="travel",
            emotion="happy",
            people=("Alice",),
            keywords=("weekend",),
            importance=0.4,
        ),
        occurred_at="2026-05-13T08:00:00+08:00",
        timezone="Asia/Shanghai",
        source=DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-2"),
    )

    records = store.search(
        DiaryMemorySearch(
            query="meeting",
            topic="work",
            emotion="angry",
            people=("Bob",),
            min_importance=0.6,
            from_="2026-05-12T00:00:00+08:00",
            to="2026-05-13T00:00:00+08:00",
            top_k=5,
        ),
        vault_id="vault-1",
    )
    results = diary_records_to_search_results(records)

    assert len(records) == 1
    assert records[0].summary == "User felt angry after a meeting with Bob."
    assert results[0].relative_path == f"DiaryMemory/{records[0].id}"
    assert results[0].source_scope == "diary_objects"
    assert results[0].retrieval_mode == "diary_object"
    store.close()
