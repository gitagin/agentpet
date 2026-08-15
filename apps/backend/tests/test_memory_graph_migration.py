from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.services.memory_graph_migration import (
    MemoryGraphMigrationError,
    apply_llmwiki_migrations,
    backup_sqlite_database,
    restore_sqlite_database,
    snapshot_graph_database,
    validate_graph_snapshot,
)
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.storage.database import Database, MigrationRunner
from app.evals.llmwiki_migration_smoke import run as run_migration_smoke


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _empty_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.close()


def _apply_until_019(path: Path, migration_dir: Path) -> None:
    migration_dir.mkdir()
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        if migration.stem.startswith(("020_", "021_")):
            continue
        shutil.copyfile(migration, migration_dir / migration.name)
    MigrationRunner(Database(path), migration_dir).apply()


def _insert_legacy_fact(
    database: Path,
    *,
    fact_id: str,
    category: str = "preference",
    subject: str = "writing style",
    source_text: str = "I prefer concise answers.",
    candidate_id: str | None = None,
    candidate_status: str = "active",
    risk_tier: str = "low",
) -> None:
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0.9, ?, 'user_message', 1, ?, ?)
            """,
            (
                fact_id,
                f"legacy-key-{fact_id}",
                f"legacy-conflict-{fact_id}",
                category,
                subject,
                "prefers",
                "concise answers",
                source_text,
                "2026-08-10T00:00:00Z",
                "2026-08-10T00:00:00Z",
            ),
        )
        if candidate_id is not None:
            conn.execute(
                """
                INSERT INTO memory_candidates (
                    id, candidate_hash, memory_kind, memory_scope, summary,
                    normalized_value, source_text, source_text_hash, source_track,
                    risk_tier, confidence, importance, evidence_count, status,
                    fact_id, metadata_json, created_at, updated_at
                ) VALUES (?, ?, 'preference', 'global', ?, ?, ?, ?, 'explicit_user',
                    ?, 0.9, 0.8, 1, ?, ?, '{}', ?, ?)
                """,
                (
                    candidate_id,
                    f"candidate-hash-{candidate_id}",
                    source_text,
                    "concise answers",
                    source_text,
                    f"source-hash-{candidate_id}",
                    risk_tier,
                    candidate_status,
                    fact_id,
                    "2026-08-10T00:00:00Z",
                    "2026-08-10T00:00:00Z",
                ),
            )
        conn.commit()


def test_empty_database_migration_is_valid_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite3"
    backup = tmp_path / "backups" / "empty.pre.bak"
    _empty_database(database)

    report = apply_llmwiki_migrations(database, backup_path=backup)

    required_versions = (
        "020_action_execution_idempotency",
        "021_llm_wiki_memory_graph",
        "022_resident_runtime_delivery",
        "023_product_metrics",
        "024_post_reply_jobs_and_evidence_idempotency",
    )
    positions = tuple(report.applied_versions.index(version) for version in required_versions)
    assert positions == tuple(sorted(positions))
    assert report.repeated_apply_versions == ()
    assert report.backup_path == str(backup)
    assert backup.exists()
    assert validate_graph_snapshot(report.after) == ()
    assert report.after.foreign_key_violations == ()


def test_019_database_upgrade_preserves_rows_and_repeated_runner_pass(tmp_path: Path) -> None:
    database = tmp_path / "legacy-019.sqlite3"
    backup = tmp_path / "legacy-019.pre.bak"
    _empty_database(database)
    _apply_until_019(database, tmp_path / "migrations-019")
    with sqlite3.connect(database) as conn:
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at
            ) VALUES ('legacy-fact', 'legacy-key', 'legacy-conflict', 'preference',
                'style', 'prefers', 'concise', 'active', 0.9, 'legacy source',
                'user_message', 1, '2026-08-08T00:00:00Z', '2026-08-08T00:00:00Z')
            """
        )
        conn.commit()

    report = apply_llmwiki_migrations(database, backup_path=backup)

    assert report.applied_versions[:2] == (
        "020_action_execution_idempotency",
        "021_llm_wiki_memory_graph",
    )
    assert report.repeated_apply_versions == ()
    assert report.before.row_counts["memory_graph_facts"] == 1
    assert report.after.row_counts["memory_graph_facts"] == 1
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_graph_facts)")}
        assert {"statement_kind", "subject_entity_id", "relation_type"}.issubset(columns)


def test_migration_bootstrap_types_only_durable_explicit_legacy_rows(tmp_path: Path) -> None:
    database = tmp_path / "legacy-explicit-upgrade.sqlite3"
    backup = tmp_path / "legacy-explicit-upgrade.pre.bak"
    _empty_database(database)
    _apply_until_019(database, tmp_path / "migrations-019-explicit")
    _insert_legacy_fact(
        database,
        fact_id="legacy-upgrade-fact",
        candidate_id="legacy-upgrade-candidate",
    )

    report = apply_llmwiki_migrations(database, backup_path=backup)

    assert report.repeated_apply_versions == ()
    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT statement_kind, subject_entity_id FROM memory_graph_facts WHERE id = ?",
            ("legacy-upgrade-fact",),
        ).fetchone()
        assert row[0] == "claim"
        assert row[1]
        assert conn.execute("SELECT COUNT(*) FROM memory_entity_evidence").fetchone()[0] == 1


def test_backup_and_restore_round_trip_uses_authoritative_rows(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    backup = tmp_path / "state.bak"
    _empty_database(database)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker(value) VALUES ('before')")
        conn.commit()

    backup_sqlite_database(database, backup)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE marker SET value = 'after'")
        conn.commit()
    restore_sqlite_database(backup, database)

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT value FROM marker").fetchone()[0] == "before"


def test_failed_validation_restores_pre_migration_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "state.sqlite3"
    backup = tmp_path / "state.pre.bak"
    _empty_database(database)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker(value) VALUES ('before')")
        conn.commit()

    monkeypatch.setattr(
        "app.services.memory_graph_migration.validate_graph_snapshot",
        lambda *_args, **_kwargs: ("forced_validation_failure",),
    )
    with pytest.raises(MemoryGraphMigrationError, match="forced_validation_failure"):
        apply_llmwiki_migrations(database, backup_path=backup)

    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT value FROM marker").fetchone()[0] == "before"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'graph_source_state'").fetchone() is None


def test_021_schema_can_be_reapplied_when_its_marker_is_missing(tmp_path: Path) -> None:
    database = tmp_path / "marker-missing.sqlite3"
    _empty_database(database)
    MigrationRunner(Database(database)).apply()
    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM schema_migrations WHERE version = '021_llm_wiki_memory_graph'")
        conn.commit()

    applied = MigrationRunner(Database(database)).apply()

    assert applied == ["021_llm_wiki_memory_graph"]
    assert validate_graph_snapshot(snapshot_graph_database(database)) == ()


def test_migration_smoke_uses_populated_legacy_fixture(tmp_path: Path) -> None:
    report = run_migration_smoke(tmp_path / "evidence")
    legacy = report["modes"]["legacy_database"]

    assert legacy["before"]["row_counts"]["memory_graph_facts"] == 1
    assert legacy["before"]["row_counts"]["memory_candidates"] == 1
    assert legacy["after"]["row_counts"]["memory_graph_facts"] == 1
    assert legacy["after"]["row_counts"]["memory_candidates"] == 1
    assert legacy["preserved_row_counts"] is True


def test_explicit_legacy_fact_is_typed_once_and_stays_recallable(tmp_path: Path) -> None:
    database = tmp_path / "legacy-explicit.sqlite3"
    _empty_database(database)
    MigrationRunner(Database(database)).apply()
    _insert_legacy_fact(
        database,
        fact_id="legacy-explicit-fact",
        candidate_id="legacy-explicit-candidate",
    )

    first = MemoryEntityGraphStore(database)
    try:
        fact = first.graph.get("legacy-explicit-fact")
        assert fact.statement_kind == "claim"
        assert fact.subject_entity_id is not None
        entity = first.get_entity(fact.subject_entity_id)
        assert entity.entity_type == "preference"
        assert entity.status == "active"
        assert [item.id for item in first.answerable_facts(query="concise")] == [fact.id]
        assert first.backfill_explicit_legacy_candidates() == ()
        counts = {
            table: first.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("memory_entities", "memory_evidence", "memory_entity_evidence")
        }
    finally:
        first.close()

    second = MemoryEntityGraphStore(database)
    try:
        repeated_counts = {
            table: second.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("memory_entities", "memory_evidence", "memory_entity_evidence")
        }
        assert repeated_counts == counts
        assert second.graph.get("legacy-explicit-fact").subject_entity_id == fact.subject_entity_id
    finally:
        second.close()


def test_legacy_fact_without_durable_candidate_link_remains_audit_only(tmp_path: Path) -> None:
    database = tmp_path / "legacy-unlinked.sqlite3"
    _empty_database(database)
    MigrationRunner(Database(database)).apply()
    _insert_legacy_fact(database, fact_id="legacy-unlinked-fact")

    store = MemoryEntityGraphStore(database)
    try:
        fact = store.graph.get("legacy-unlinked-fact")
        assert fact.statement_kind is None
        assert fact.subject_entity_id is None
        assert store.conn.execute("SELECT COUNT(*) FROM memory_entities").fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 0
        assert store.answerable_facts(query="concise") == []
    finally:
        store.close()


def test_sensitive_explicit_legacy_source_is_not_backfilled(tmp_path: Path) -> None:
    database = tmp_path / "legacy-sensitive.sqlite3"
    _empty_database(database)
    MigrationRunner(Database(database)).apply()
    _insert_legacy_fact(
        database,
        fact_id="legacy-sensitive-fact",
        source_text="password: super-secret-value",
        candidate_id="legacy-sensitive-candidate",
    )

    store = MemoryEntityGraphStore(database)
    try:
        fact = store.graph.get("legacy-sensitive-fact")
        assert fact.statement_kind is None
        assert fact.subject_entity_id is None
        candidate = store.conn.execute(
            "SELECT status, risk_tier FROM memory_candidates WHERE id = ?",
            ("legacy-sensitive-candidate",),
        ).fetchone()
        assert tuple(candidate) == ("active", "low")
        assert store.conn.execute("SELECT COUNT(*) FROM memory_entities").fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 0
    finally:
        store.close()


def test_unconfirmed_legacy_self_candidate_stays_non_answerable(tmp_path: Path) -> None:
    database = tmp_path / "legacy-self-candidate.sqlite3"
    _empty_database(database)
    MigrationRunner(Database(database)).apply()
    _insert_legacy_fact(
        database,
        fact_id="legacy-self-fact",
        category="profile",
        subject="我",
        candidate_id="legacy-self-candidate",
        candidate_status="candidate",
    )

    store = MemoryEntityGraphStore(database)
    try:
        fact = store.graph.get("legacy-self-fact")
        assert fact.statement_kind == "claim"
        assert fact.status.value == "candidate"
        assert fact.subject_entity_id is not None
        assert store.get_entity(fact.subject_entity_id).status == "candidate"
        assert store.answerable_facts(query="concise") == []
    finally:
        store.close()
