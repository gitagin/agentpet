from __future__ import annotations

import sqlite3

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
    memory_type: str = "event",
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
        type=memory_type,
    )


def test_diary_memory_store_transaction_commits_and_nests_in_a_caller_transaction(tmp_path):
    # 整批写入用 SAVEPOINT 而不是 BEGIN:调用方可能已经开着事务,
    # BEGIN 会直接报 "cannot start a transaction within a transaction"。
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    store = DiaryMemoryStore(db_path)
    source = DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-tx")

    def count_from_fresh_connection() -> int:
        # 只有另开连接才看得出数据是否真的提交:同连接里的未提交写入本来就可见。
        with sqlite3.connect(db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM diary_memory_objects").fetchone()[0]

    with store.transaction():
        store.insert_object(
            vault_id="vault-1",
            extracted=memory_object(summary="User is worried about changing jobs."),
            occurred_at="2026-05-13T10:30:00+08:00",
            timezone="Asia/Shanghai",
            source=source,
            commit=False,
        )
    assert count_from_fresh_connection() == 1

    # 嵌套在外层事务里:不崩,而且外层回滚后这批写入也必须消失。
    store.conn.execute("BEGIN")
    with store.transaction():
        store.insert_object(
            vault_id="vault-1",
            extracted=memory_object(summary="User planned a weekend trip with Alice."),
            occurred_at="2026-05-14T10:30:00+08:00",
            timezone="Asia/Shanghai",
            source=source,
            commit=False,
        )
    assert count_from_fresh_connection() == 1
    store.conn.execute("ROLLBACK")
    assert count_from_fresh_connection() == 1
    store.close()


def test_diary_memory_store_transaction_rolls_back_the_whole_batch_on_failure(tmp_path):
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    store = DiaryMemoryStore(db_path)
    source = DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-rollback")
    calls = 0
    original_insert = store.insert_object

    def failing_insert(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("crash_after_first_object")
        return original_insert(**kwargs)

    store.insert_object = failing_insert

    with pytest.raises(RuntimeError):
        with store.transaction():
            for index in range(2):
                store.insert_object(
                    vault_id="vault-1",
                    extracted=memory_object(summary=f"object {index}", keywords=(f"k{index}",)),
                    occurred_at="2026-05-13T10:30:00+08:00",
                    timezone="Asia/Shanghai",
                    source=source,
                    commit=False,
                )

    with sqlite3.connect(db_path) as conn:
        # 第一条也不能留下:半套记忆正是这套校验要排除的状态。
        assert conn.execute("SELECT COUNT(*) FROM diary_memory_objects").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM diary_memory_object_sources").fetchone()[0] == 0
    store.close()


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
                memory_type="qa",
                topic="parser choice",
                keywords=("parser", "qa"),
            ),
            memory_object(
                summary="Project Atlas decision moved to next week.",
                memory_type="project_update",
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


def test_diary_memory_search_hits_mixed_script_substring(tmp_path):
    store = DiaryMemoryStore(migrate_db_with_vault(tmp_path / "state.sqlite3"))
    store.insert_object(
        vault_id="vault-1",
        extracted=memory_object(
            summary="User studied python教程 and wrote asyncio examples.",
            keywords=("tutorial",),
        ),
        occurred_at="2026-05-12T23:00:00+08:00",
        timezone="Asia/Shanghai",
        source=DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-1"),
    )

    records = store.search(DiaryMemorySearch(query="教程", top_k=5), vault_id="vault-1")

    assert len(records) == 1
    assert records[0].summary == "User studied python教程 and wrote asyncio examples."
    store.close()


def test_diary_memory_search_hits_single_cjk_char_via_like_fallback(tmp_path):
    store = DiaryMemoryStore(migrate_db_with_vault(tmp_path / "state.sqlite3"))
    store.insert_object(
        vault_id="vault-1",
        extracted=memory_object(
            summary="User talked about 奶牛 farms over the weekend.",
            keywords=("cattle",),
        ),
        occurred_at="2026-05-12T23:00:00+08:00",
        timezone="Asia/Shanghai",
        source=DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-1"),
    )

    records = store.search(DiaryMemorySearch(query="牛", top_k=5), vault_id="vault-1")

    assert len(records) == 1
    assert records[0].summary == "User talked about 奶牛 farms over the weekend."
    store.close()


def test_diary_memory_search_tolerates_fts_metacharacters_and_returns_empty(tmp_path):
    store = DiaryMemoryStore(migrate_db_with_vault(tmp_path / "state.sqlite3"))
    store.insert_object(
        vault_id="vault-1",
        extracted=memory_object(summary="User felt pressure at work and considered resigning."),
        occurred_at="2026-05-12T23:00:00+08:00",
        timezone="Asia/Shanghai",
        source=DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-1"),
    )

    for query in ('he said "hi"', "a^2 NEAR (b) -c", "!!!", "教程*mixed"):
        records = store.search(DiaryMemorySearch(query=query, top_k=5), vault_id="vault-1")
        assert isinstance(records, list)
    store.close()


def test_diary_memory_batch_takes_the_write_lock_before_deduping(tmp_path):
    """批次写事务必须先拿写锁,再按内容去重(读),最后才插入。

    一批日记记忆的写入形态是先按内容哈希查重、再逐条插入,所以事务里一定是"先读后写"。
    WAL 下 deferred 事务的读快照在第一次读时固定:期间任何别的连接提交,后面的插入会
    **立即**报 database is locked(SQLITE_BUSY_SNAPSHOT,busy_timeout 按设计不参与),
    整批记忆以一个没有异常码的失败收场。SAVEPOINT 只是加入调用方的事务,挡不住并发写者,
    因此无调用方事务时必须用 BEGIN IMMEDIATE。
    """
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    store = DiaryMemoryStore(db_path)
    other = sqlite3.connect(db_path, timeout=0.2)
    try:
        store.conn.execute(
            "CREATE TABLE IF NOT EXISTS lock_probe(id INTEGER PRIMARY KEY, value TEXT)"
        )
        store.conn.commit()

        with store.transaction():
            # 查重读必须落在真实表上:常量 SELECT 不会开读事务,也就定不下快照,
            # 那样这个测试即使在 SAVEPOINT 实现下也会假绿。
            store.conn.execute("SELECT COUNT(*) FROM lock_probe")
            with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                other.execute("INSERT INTO lock_probe(id, value) VALUES (1, 'concurrent')")
            store.conn.execute("INSERT INTO lock_probe(id, value) VALUES (2, 'within')")
    finally:
        other.close()
        store.close()

    with sqlite3.connect(db_path) as verify:
        assert sorted(row[0] for row in verify.execute("SELECT id FROM lock_probe")) == [2]
