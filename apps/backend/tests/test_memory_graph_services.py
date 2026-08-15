import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from apps.backend.tests._schema import migrate_db
from app.models.enums import MemoryFactStatus
from app.services.long_term_memory import LongTermMemoryService
from app.services.memory import SafeMarkdownWriter
from app.services.memory_graph import MemoryFactCandidate, MemoryGraphStore, facts_to_context_lines
from app.storage.database import Database, MigrationRunner


def graph_db(tmp_path: Path) -> Path:
    return migrate_db(tmp_path / "state.sqlite3")


def test_memory_graph_records_active_fact_and_deduplicates_support(tmp_path):
    store = MemoryGraphStore(graph_db(tmp_path))

    first = store.upsert_candidate(
        MemoryFactCandidate(
            category="preference",
            subject="fruit",
            predicate="is",
            object="apple",
            source_text="I like apple",
            confidence=0.9,
        )
    )
    second = store.upsert_candidate(
        MemoryFactCandidate(
            category="preference",
            subject="fruit",
            predicate="is",
            object="apple",
            source_text="I like apple again",
            confidence=0.9,
        )
    )

    assert first.inserted is True
    assert first.fact.status == MemoryFactStatus.ACTIVE
    assert first.fact.memory_type is None
    assert first.fact.entity_type is None
    assert first.fact.occurred_at is None
    assert first.fact.expires_at is None
    assert first.fact.metadata_json == "{}"
    assert first.fact.importance == 0.5
    assert second.inserted is False
    assert second.reason == "already_recorded"
    assert second.fact.id == first.fact.id
    assert second.fact.support_count == 2
    store.close()


def test_legacy_fact_store_groups_conflicts_without_writing_an_authority_pointer(tmp_path):
    store = MemoryGraphStore(graph_db(tmp_path))
    active = store.upsert_candidate(
        MemoryFactCandidate(
            category="preference",
            subject="fruit",
            predicate="is",
            object="apple",
            source_text="I like apple",
            confidence=0.9,
        )
    )

    conflict = store.upsert_candidate(
        MemoryFactCandidate(
            category="preference",
            subject="fruit",
            predicate="is",
            object="banana",
            source_text="I like banana",
            confidence=0.9,
        )
    )

    assert active.fact.status == MemoryFactStatus.ACTIVE
    assert conflict.fact.status == MemoryFactStatus.QUARANTINED
    assert conflict.reason == "conflict_detected"
    assert conflict.fact.conflicts_with is None
    assert [fact.object for fact in store.search_active("fruit")] == ["apple"]

    confirmed = store.update_status(conflict.fact.id, MemoryFactStatus.ACTIVE, reason="user_confirmed")
    assert confirmed.status == MemoryFactStatus.ACTIVE
    store.close()


def test_memory_graph_status_controls_exclude_inactive_facts_from_context(tmp_path):
    store = MemoryGraphStore(graph_db(tmp_path))
    active = store.upsert_candidate(
        MemoryFactCandidate(
            category="preference",
            subject="fruit",
            predicate="is",
            object="apple",
            source_text="I like apple",
            confidence=0.9,
        )
    ).fact
    wrong = store.upsert_candidate(
        MemoryFactCandidate(
            category="preference",
            subject="drink",
            predicate="is",
            object="coffee",
            source_text="I like coffee",
            confidence=0.9,
        )
    ).fact
    archived = store.upsert_candidate(
        MemoryFactCandidate(
            category="preference",
            subject="editor",
            predicate="is",
            object="vim",
            source_text="I like vim",
            confidence=0.9,
        )
    ).fact
    sensitive_blocked = store.upsert_candidate(
        MemoryFactCandidate(
            category="profile",
            subject="account",
            predicate="is",
            object="private",
            source_text="private account fact",
            confidence=0.9,
        )
    ).fact

    store.update_status(wrong.id, MemoryFactStatus.WRONG, reason="user_marked_wrong")
    store.update_status(archived.id, MemoryFactStatus.ARCHIVED, reason="user_archived")
    store.update_status(sensitive_blocked.id, MemoryFactStatus.SENSITIVE_BLOCKED, reason="user_sensitive_blocked")

    assert [fact.id for fact in store.search_active("i")] == [active.id]
    assert facts_to_context_lines(store.list_facts(query="i")) == [
        "fruit is apple (confidence=0.90, support=1)"
    ]
    store.close()


def test_memory_graph_records_optional_expansion_fields_and_searches_them(tmp_path):
    store = MemoryGraphStore(graph_db(tmp_path))

    result = store.upsert_candidate(
        MemoryFactCandidate(
            category="profile",
            subject="Ada",
            predicate="attends",
            object="robotics club",
            source_text="Ada attended robotics club on Wednesday",
            confidence=0.9,
            memory_type="episodic",
            entity_type="person",
            occurred_at="2026-05-13T09:30:00Z",
            expires_at="2026-06-13T09:30:00Z",
            metadata_json='{"tag":"club","source":"test"}',
            importance=0.82,
        )
    )

    assert result.inserted is True
    assert result.fact.memory_type == "episodic"
    assert result.fact.entity_type == "person"
    assert result.fact.occurred_at == "2026-05-13T09:30:00Z"
    assert result.fact.expires_at == "2026-06-13T09:30:00Z"
    assert json.loads(result.fact.metadata_json) == {"source": "test", "tag": "club"}
    assert result.fact.importance == 0.82
    assert [fact.id for fact in store.search_active("episodic")] == [result.fact.id]
    assert [fact.id for fact in store.search_active("person")] == [result.fact.id]
    assert [fact.id for fact in store.search_active("club")] == [result.fact.id]
    assert [fact.id for fact in store.list_facts(query="2026-05-13")] == [result.fact.id]
    store.close()


def test_memory_graph_upgrades_existing_fact_table_with_safe_defaults(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memory_graph_facts (
            id TEXT PRIMARY KEY,
            fact_key TEXT NOT NULL UNIQUE,
            conflict_key TEXT NOT NULL,
            category TEXT NOT NULL,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_text TEXT NOT NULL,
            source_type TEXT NOT NULL,
            conversation_id TEXT,
            user_message_id TEXT,
            agent_run_id TEXT,
            support_count INTEGER NOT NULL DEFAULT 1,
            conflicts_with TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO memory_graph_facts (
            id, fact_key, conflict_key, category, subject, predicate, object,
            status, confidence, source_text, source_type, support_count,
            created_at, updated_at
        )
        VALUES (
            'fact-1', 'fact-key', 'conflict-key', 'preference', 'coffee', 'is',
            'black', 'active', 0.8, 'I like black coffee', 'test', 1,
            '2026-05-13T00:00:00Z', '2026-05-13T00:00:00Z'
        )
        """
    )
    conn.commit()
    conn.close()

    migrate_db(db_path)
    store = MemoryGraphStore(db_path)
    facts = store.search_active("coffee")

    assert len(facts) == 1
    assert facts[0].subject == "coffee"
    assert facts[0].memory_type is None
    assert facts[0].entity_type is None
    assert facts[0].occurred_at is None
    assert facts[0].expires_at is None
    assert facts[0].metadata_json == "{}"
    assert facts[0].importance == 0.5
    store.close()


def test_memory_graph_migration_adds_optional_expansion_columns(tmp_path):
    db = Database(tmp_path / "state.sqlite3")

    applied = MigrationRunner(db).apply()

    assert "010_diary_memory_objects" in applied
    with db.connect() as conn:
        columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(memory_graph_facts)").fetchall()}
    assert columns["memory_type"]["type"] == "TEXT"
    assert columns["entity_type"]["type"] == "TEXT"
    assert columns["occurred_at"]["type"] == "TEXT"
    assert columns["expires_at"]["type"] == "TEXT"
    assert columns["metadata_json"]["type"] == "TEXT"
    assert columns["importance"]["type"] == "REAL"


def test_long_term_memory_writes_structured_graph_fact(tmp_path):
    service = LongTermMemoryService(
        SafeMarkdownWriter(tmp_path),
        now_provider=lambda: datetime(2026, 5, 4, 10, 11, 12, tzinfo=timezone.utc),
        graph_store=MemoryGraphStore(graph_db(tmp_path)),
    )

    result = service.remember_from_user_message(
        "my favorite fruit is apple",
        conversation_id="conversation-1",
        user_message_id="message-1",
        agent_run_id="run-1",
    )

    assert result.written is True
    assert result.graph_fact_id
    assert result.graph_status == "active"
    facts = service.graph_store.search_active("fruit")
    assert len(facts) == 1
    assert facts[0].subject == "fruit"
    assert facts[0].predicate == "is"
    assert facts[0].object == "apple"
    service.close()


def test_memory_graph_write_does_not_create_a_transactional_kuzu_projection(tmp_path):
    store = MemoryGraphStore(graph_db(tmp_path))
    try:
        result = store.upsert_candidate(
            MemoryFactCandidate(
                category="preference",
                subject="fruit",
                predicate="is",
                object="apple",
                source_text="I like apple",
                confidence=0.9,
            )
        )

        assert result.inserted is True
        assert store.search_active("fruit")[0].id == result.fact.id
        assert not (tmp_path / "graph").exists()
    finally:
        store.close()
