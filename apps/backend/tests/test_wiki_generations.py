from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.repositories.storage import VaultRepository
from app.services.wiki.generations import WikiGenerationError, WikiGenerationStore
from app.storage.database import Database, MigrationRunner


@pytest.fixture
def storage(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    MigrationRunner(database).apply()
    with database.session() as conn:
        vault_id = VaultRepository(conn).upsert(tmp_path / "Vault")
    return WikiGenerationStore(database), vault_id


def storage_validator(conn, vault_id, generation, manifest):
    # These tests exercise storage atomicity, not semantic/permission approval.
    assert manifest
    assert conn.in_transaction


def test_staged_pages_are_invisible_and_bodies_are_shared(storage):
    store, vault = storage
    first = store.stage(vault, base_generation=None, changes={
        "Wiki/A.md": b"# Original", "Wiki/B.md": b"# Shared",
    })
    assert store.active(vault) is None
    with pytest.raises(WikiGenerationError, match="unavailable"):
        store.read_body(vault, first, "Wiki/A.md")
    store.promote(vault, first, validate=storage_validator)
    second = store.stage(vault, base_generation=first, changes={"Wiki/A.md": b"# New"})
    assert store.active(vault) == first
    assert store.read_body(vault, first, "Wiki/A.md") == b"# Original"
    store.promote(vault, second, validate=storage_validator)
    assert store.read_body(vault, second, "Wiki/A.md") == b"# New"
    assert store.read_body(vault, second, "Wiki/B.md") == b"# Shared"
    assert store.read_body(vault, first, "Wiki/A.md") == b"# Original"
    with store.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_page_bodies").fetchone()[0] == 3


def test_rejected_validation_and_interrupted_promote_preserve_head(storage):
    store, vault = storage
    first = store.stage(vault, base_generation=None, changes={"Wiki/A.md": b"old"})
    store.promote(vault, first, validate=storage_validator)
    draft = store.stage(vault, base_generation=first, changes={"Wiki/A.md": b"new"})

    def denied(*args):
        raise WikiGenerationError("source_forgotten")

    with pytest.raises(WikiGenerationError, match="source_forgotten"):
        store.promote(vault, draft, validate=denied)
    with store.database.session() as conn:
        conn.execute(
            """CREATE TRIGGER reject_publish BEFORE UPDATE OF status ON wiki_generations
               BEGIN SELECT RAISE(ABORT, 'injected_failure_after_pointer_update'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected_failure"):
        store.promote(vault, draft, validate=storage_validator)
    reopened = WikiGenerationStore(Database(store.database.path))
    assert reopened.active(vault) == first
    assert reopened.read_body(vault, first, "Wiki/A.md") == b"old"
    with store.database.session() as conn:
        assert conn.execute("SELECT status FROM wiki_generations WHERE id = ?", (draft,)).fetchone()[0] == "staged"
        conn.execute("DROP TRIGGER reject_publish")
    reopened.promote(vault, draft, validate=storage_validator)
    assert reopened.active(vault) == draft


def test_concurrent_publish_has_one_winner(storage):
    store, vault = storage
    drafts = [store.stage(vault, base_generation=None, changes={"Wiki/A.md": body})
              for body in (b"one", b"two")]

    def publish(generation):
        try:
            store.promote(vault, generation, validate=storage_validator)
            return generation
        except WikiGenerationError as exc:
            assert str(exc) == "wiki_generation_base_conflict"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, drafts))
    winners = [result for result in results if result]
    assert winners == [store.active(vault)]


def test_versions_cannot_cross_vault_and_paths_cannot_escape(storage, tmp_path):
    store, vault = storage
    draft = store.stage(vault, base_generation=None, changes={"Wiki/A.md": b"private"})
    with store.database.session() as conn:
        other = VaultRepository(conn).upsert(tmp_path / "Other")
    with pytest.raises(WikiGenerationError, match="not_staged"):
        store.promote(other, draft, validate=storage_validator)
    store.promote(vault, draft, validate=storage_validator)
    with pytest.raises(WikiGenerationError, match="unavailable"):
        store.read_body(other, draft, "Wiki/A.md")
    for path in ("Wiki/../secret.md", "Wiki//A.md", "Wiki\\A.md", "Memories/A.md"):
        with pytest.raises(WikiGenerationError, match="invalid_path"):
            store.stage(vault, base_generation=draft, changes={path: b"unsafe"})
    assert store.active(vault) == draft


def test_damaged_body_cannot_publish(storage):
    store, vault = storage
    draft = store.stage(vault, base_generation=None, changes={"Wiki/A.md": b"original"})
    with store.database.session() as conn:
        conn.execute("UPDATE wiki_page_bodies SET body = ?", (b"tampered",))
    with pytest.raises(WikiGenerationError, match="body_integrity"):
        store.promote(vault, draft, validate=storage_validator)
    assert store.active(vault) is None


def test_async_validator_cannot_accidentally_authorize(storage):
    store, vault = storage
    draft = store.stage(vault, base_generation=None, changes={"Wiki/A.md": b"original"})

    async def validate(*args):
        raise AssertionError("must not run")

    with pytest.raises(WikiGenerationError, match="async_validator"):
        store.promote(vault, draft, validate=validate)
    assert store.active(vault) is None
