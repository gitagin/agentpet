from __future__ import annotations

import sqlite3

from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.retrieval import _graph_fusion_candidates
from tests._schema import migrated_connection


def _seed_entity(conn: sqlite3.Connection, *, entity_id: str, name: str, entity_type: str = "person") -> None:
    conn.execute(
        """
        INSERT INTO memory_entities(
            id, entity_key, lookup_fingerprint, entity_type, canonical_name,
            normalized_name, status, risk_tier, confidence, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', 'low', 0.9, '{}', datetime('now'), datetime('now'))
        """,
        (entity_id, f"{entity_type}:{name}", f"fp-{entity_id}", entity_type, name, name.casefold()),
    )


def _seed_alias(conn: sqlite3.Connection, *, alias_id: str, entity_id: str, alias: str) -> None:
    conn.execute(
        """
        INSERT INTO memory_entity_aliases(id, entity_id, alias, normalized_alias, status, created_at)
        VALUES (?, ?, ?, ?, 'active', datetime('now'))
        """,
        (alias_id, entity_id, alias, alias.casefold()),
    )


def test_find_active_entity_ids_resolves_canonical_names_and_aliases() -> None:
    conn = migrated_connection()
    _seed_entity(conn, entity_id="ent-a", name="Alice Chen")
    _seed_alias(conn, alias_id="alias-a", entity_id="ent-a", alias="小陈")

    store = MemoryEntityGraphStore(conn)
    ids = store.find_active_entity_ids(("小陈",))

    assert ids == ["ent-a"]


def test_find_active_entity_ids_ignores_rejected_aliases() -> None:
    conn = migrated_connection()
    _seed_entity(conn, entity_id="ent-a", name="Alice Chen")
    conn.execute(
        """
        INSERT INTO memory_entity_aliases(id, entity_id, alias, normalized_alias, status, created_at)
        VALUES ('alias-a', 'ent-a', '旧名', '旧名', 'rejected', datetime('now'))
        """
    )

    store = MemoryEntityGraphStore(conn)
    ids = store.find_active_entity_ids(("旧名",))

    assert ids == []


def test_graph_fusion_candidates_returns_empty_without_entities() -> None:
    conn = migrated_connection()

    candidates = _graph_fusion_candidates(
        conn,
        names=("Alice Chen",),
        vault_id="vault-1",
        limit=8,
    )

    assert candidates == []
