from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.memory_graph_kuzu import (
    KuzuGraphService,
    KuzuProjectionError,
    rebuild_kuzu_projection,
    traverse_with_kuzu_fallback,
)
from tests._schema import migrate_db


def _graph_fixture(tmp_path: Path) -> tuple[Path, str, str, str]:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        self_entity = store.ensure_self()
        project = store.create_entity(entity_type="project", canonical_name="Atlas")
        concept = store.create_entity(entity_type="concept", canonical_name="Evidence graph")
        first = store.create_relation(
            relation_type="works_on",
            subject_entity_id=self_entity.id,
            object_entity_id=project.id,
            source_text="I work on Atlas.",
            evidence_id="evidence-works-on",
            confidence=0.92,
        )
        store.create_relation(
            relation_type="related_to",
            subject_entity_id=project.id,
            object_entity_id=concept.id,
            source_text="Atlas uses an evidence graph.",
            evidence_id="evidence-related",
            confidence=0.91,
        )
        return db, self_entity.id, project.id, first.id
    finally:
        store.close()


def test_rebuild_publishes_active_generation_and_read_only_connection(tmp_path: Path) -> None:
    pytest.importorskip("kuzu", reason="Kuzu optional dependency is not installed")
    db, self_id, _project_id, relation_id = _graph_fixture(tmp_path)
    service = KuzuGraphService(db, tmp_path / "graph")
    try:
        report = service.rebuild()
        assert report.generation.status == "active"
        assert report.database_path is not None
        assert Path(report.database_path).exists()
        assert report.node_count >= 4
        assert report.edge_count >= 2

        result = service.traverse(self_id)
        assert result.source == "kuzu"
        assert result.fallback_reason is None
        assert relation_id in {item.fact.id for item in result.relations}

        with service.open_read_only() as connection:
            connection = cast(Any, connection)
            with pytest.raises(RuntimeError, match="read-only database"):
                connection.execute(
                    """
                    CREATE (n:GraphNode {
                        id: 'illegal', kind: 'entity', label: 'illegal',
                        entity_type: 'concept', status: 'active',
                        risk_tier: 'low', confidence: 1.0
                    })
                    """
                )
    finally:
        service.close()


def test_generation_revision_changes_force_sqlite_fallback(tmp_path: Path) -> None:
    db, self_id, _project_id, _relation_id = _graph_fixture(tmp_path)
    service = KuzuGraphService(db, tmp_path / "graph")
    try:
        report = service.rebuild()
        assert report.generation.status == "active"
        store = MemoryEntityGraphStore(db)
        try:
            store.add_alias(self_id, "current user")
        finally:
            store.close()

        result = service.traverse(self_id)
        assert result.source == "sqlite"
        assert result.fallback_reason == "kuzu_generation_revision_mismatch"
    finally:
        service.close()


def test_deleted_or_corrupt_generation_falls_back_without_losing_sqlite(tmp_path: Path) -> None:
    db, self_id, _project_id, relation_id = _graph_fixture(tmp_path)
    service = KuzuGraphService(db, tmp_path / "graph")
    try:
        report = service.rebuild()
        assert report.database_path is not None
        path = Path(report.database_path)
        path.unlink()
        result = service.traverse(self_id)
        assert result.source == "sqlite"
        assert result.fallback_reason == "kuzu_generation_missing"
        assert relation_id in {item.fact.id for item in result.relations}

        rebuilt = service.rebuild()
        assert rebuilt.database_path is not None
        Path(rebuilt.database_path).write_bytes(b"not a Kuzu database")
        corrupted = service.traverse(self_id)
        assert corrupted.source == "sqlite"
        assert corrupted.fallback_reason == "kuzu_generation_unreadable"
    finally:
        service.close()


def test_source_change_during_build_is_stale_and_not_published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _self_id, _project_id, _relation_id = _graph_fixture(tmp_path)
    service = KuzuGraphService(db, tmp_path / "graph")
    original = service._build_database

    def build_then_change(path: Path, snapshot):
        result = original(path, snapshot)
        store = MemoryEntityGraphStore(db)
        try:
            store.create_entity(entity_type="event", canonical_name="Changed during rebuild")
        finally:
            store.close()
        return result

    monkeypatch.setattr(service, "_build_database", build_then_change)
    try:
        report = service.rebuild()
        assert report.generation.status == "stale"
        assert report.generation.error_code == "source_revision_changed_during_build"
        assert report.database_path is None
        assert not list((tmp_path / "graph").glob("memory_graph.*.kuzu"))
    finally:
        service.close()


def test_missing_kuzu_dependency_is_a_recorded_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _self_id, _project_id, _relation_id = _graph_fixture(tmp_path)
    import app.services.memory_graph_kuzu as kuzu_service

    monkeypatch.setattr(kuzu_service, "_load_kuzu", lambda: (_ for _ in ()).throw(ImportError("missing")))
    report = rebuild_kuzu_projection(db, tmp_path / "graph")
    assert report.generation.status == "failed"
    assert report.generation.error_code == "kuzu_dependency_missing"
    assert report.fallback_reason == "kuzu_dependency_missing"

    result = traverse_with_kuzu_fallback(db, tmp_path / "graph", _self_id)
    assert result.source == "sqlite"
    assert result.fallback_reason == "kuzu_generation_missing"


def test_entity_authority_does_not_initialize_transactional_kuzu_mirror(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        assert not hasattr(store.graph, "_kuzu")
    finally:
        store.close()


def test_read_only_generation_requires_active_metadata(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    service = KuzuGraphService(db, tmp_path / "graph")
    try:
        with pytest.raises(KuzuProjectionError, match="kuzu_generation_missing"):
            with service.open_read_only():
                pass
    finally:
        service.close()


def test_external_wiki_edit_invalidates_generation_before_traversal(tmp_path: Path) -> None:
    pytest.importorskip("kuzu", reason="Kuzu optional dependency is not installed")
    db, self_id, _project_id, relation_id = _graph_fixture(tmp_path)
    vault_root = tmp_path / "Vault"
    wiki_path = vault_root / "Wiki" / "Atlas.md"
    wiki_path.parent.mkdir(parents=True)
    wiki_path.write_text(
        "---\nsources:\n  - source-atlas\n---\n# Atlas\n\nInitial source-backed page.\n",
        encoding="utf-8",
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO vaults (id, root_path, name, created_at) VALUES (?, ?, ?, ?)",
            ("vault-atlas", str(vault_root), "Atlas Vault", "2026-08-10T00:00:00Z"),
        )
        conn.commit()

    service = KuzuGraphService(
        db,
        tmp_path / "graph",
        vault_id="vault-atlas",
        vault_root=vault_root,
    )
    try:
        report = service.rebuild()
        assert report.generation.status == "active"
        assert service.traverse(self_id).source == "kuzu"

        wiki_path.write_text(
            "---\nsources:\n  - source-atlas\n---\n# Atlas\n\nExternally corrected page.\n",
            encoding="utf-8",
        )

        result = service.traverse(self_id)
        assert result.source == "sqlite"
        assert result.fallback_reason == "kuzu_generation_revision_mismatch"
        assert relation_id in {item.fact.id for item in result.relations}
        binding = service.authority.get_wiki_binding(
            vault_id="vault-atlas",
            wiki_relative_path="Wiki/Atlas.md",
        )
        assert binding is not None
        assert binding["status"] == "stale"
        assert service.authority.source_revision() > report.source_revision
    finally:
        service.close()
