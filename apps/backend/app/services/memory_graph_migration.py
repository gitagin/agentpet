"""Non-destructive migration and integrity checks for the LLM Wiki graph.

SQLite remains the authority.  This module deliberately keeps migration
backups and validation outside the API handlers so a sidecar/bootstrap caller
can prove what changed before any derived graph projection is rebuilt.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from app.storage.database import Database, MigrationRunner, open_database_connection


REQUIRED_GRAPH_TABLES = frozenset(
    {
        "graph_source_state",
        "memory_entities",
        "memory_entity_aliases",
        "memory_entity_evidence",
        "wiki_page_bindings",
        "memory_fact_artifact_bindings",
        "graph_projection_generations",
    }
)
REQUIRED_FACT_COLUMNS = frozenset(
    {
        "statement_kind",
        "subject_entity_id",
        "subject_fact_id",
        "object_entity_id",
        "object_fact_id",
        "relation_type",
    }
)
COUNT_TABLES = (
    "memory_graph_facts",
    "memory_graph_events",
    "memory_candidates",
    "memory_evidence",
    "diary_memory_objects",
    "memory_entities",
    "memory_entity_aliases",
    "memory_entity_evidence",
    "wiki_page_bindings",
    "memory_fact_artifact_bindings",
)


class MemoryGraphMigrationError(RuntimeError):
    """Raised when migration validation fails and the backup was restored."""


@dataclass(frozen=True, slots=True)
class GraphDatabaseSnapshot:
    tables: frozenset[str]
    columns: Mapping[str, frozenset[str]]
    row_counts: Mapping[str, int]
    foreign_key_violations: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class GraphMigrationReport:
    backup_path: str
    applied_versions: tuple[str, ...]
    repeated_apply_versions: tuple[str, ...]
    before: GraphDatabaseSnapshot
    after: GraphDatabaseSnapshot
    repeat_snapshot: GraphDatabaseSnapshot


@contextmanager
def _connection_scope(db: str | Path | sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    owns = not isinstance(db, sqlite3.Connection)
    conn = open_database_connection(db)
    try:
        yield conn
    finally:
        if owns:
            conn.close()


def snapshot_graph_database(db: str | Path | sqlite3.Connection) -> GraphDatabaseSnapshot:
    """Capture schema, row counts and foreign-key violations consistently."""
    with _connection_scope(db) as conn:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        tables = frozenset(str(row["name"]) for row in table_rows)
        columns: dict[str, frozenset[str]] = {}
        for table in tables:
            # Table names come from sqlite_master, never caller input.
            info = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
            columns[table] = frozenset(str(row["name"]) for row in info)
        row_counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])
            for table in COUNT_TABLES
            if table in tables
        }
        violations = tuple(
            tuple(str(value) for value in row)
            for row in conn.execute("PRAGMA foreign_key_check").fetchall()
        )
    return GraphDatabaseSnapshot(
        tables=tables,
        columns=columns,
        row_counts=row_counts,
        foreign_key_violations=violations,
    )


def validate_graph_snapshot(
    snapshot: GraphDatabaseSnapshot,
    *,
    previous: GraphDatabaseSnapshot | None = None,
) -> tuple[str, ...]:
    """Return deterministic validation errors; an empty tuple means valid."""
    errors: list[str] = []
    missing_tables = sorted(REQUIRED_GRAPH_TABLES - snapshot.tables)
    if missing_tables:
        errors.append(f"missing_tables:{','.join(missing_tables)}")
    fact_columns = snapshot.columns.get("memory_graph_facts", frozenset())
    missing_columns = sorted(REQUIRED_FACT_COLUMNS - fact_columns)
    if missing_columns:
        errors.append(f"missing_fact_columns:{','.join(missing_columns)}")
    if snapshot.foreign_key_violations:
        errors.append(f"foreign_key_violations:{len(snapshot.foreign_key_violations)}")
    if previous is not None:
        for table, before_count in previous.row_counts.items():
            after_count = snapshot.row_counts.get(table)
            if after_count is not None and after_count < before_count:
                errors.append(f"row_count_decreased:{table}:{before_count}->{after_count}")
    return tuple(errors)


def backup_sqlite_database(db_path: str | Path, backup_path: str | Path) -> Path:
    """Create a consistent SQLite backup using the SQLite backup API."""
    source_path = Path(db_path)
    target_path = Path(backup_path)
    if not source_path.exists():
        raise MemoryGraphMigrationError(f"database_not_found:{source_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_name(f".{target_path.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    source = open_database_connection(source_path)
    target = open_database_connection(temporary)
    try:
        source.backup(target)
        target.commit()
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        target.close()
        source.close()
    try:
        os.replace(temporary, target_path)
    except PermissionError:
        # Windows can keep an already-existing backup open while the atomic
        # rename is attempted.  Copying through SQLite preserves the backup
        # contents without deleting a file that another process owns.
        if not target_path.exists():
            raise
        _backup_into_existing(temporary, target_path)
        temporary.unlink(missing_ok=True)
    return target_path


def restore_sqlite_database(backup_path: str | Path, db_path: str | Path) -> None:
    """Restore a backup through a temporary file, preserving atomic replacement."""
    source_path = Path(backup_path)
    target_path = Path(db_path)
    if not source_path.exists():
        raise MemoryGraphMigrationError(f"backup_not_found:{source_path}")
    temporary = target_path.with_name(f".{target_path.name}.restore.tmp")
    if temporary.exists():
        temporary.unlink()
    source = open_database_connection(source_path)
    target = open_database_connection(temporary)
    try:
        source.backup(target)
        target.commit()
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        target.close()
        source.close()
    if target_path.exists():
        _backup_into_existing(temporary, target_path)
        temporary.unlink(missing_ok=True)
    else:
        os.replace(temporary, target_path)


def _backup_into_existing(source_path: Path, target_path: Path) -> None:
    """Copy one SQLite database into an existing path when rename is locked."""
    source = open_database_connection(source_path)
    target = open_database_connection(target_path)
    try:
        source.backup(target)
        target.commit()
        # The authority may be in WAL mode.  Checkpoint while this connection
        # is still open so the restored bytes are durable in the main file.
        try:
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            # DELETE-journal databases and read-only handles do not support a
            # truncate checkpoint; the committed backup is still valid.
            pass
    finally:
        target.close()
        source.close()


def apply_llmwiki_migrations(
    db_path: str | Path,
    *,
    backup_path: str | Path | None = None,
) -> GraphMigrationReport:
    """Apply migrations with backup, validation and an idempotence pass.

    A validation failure restores the pre-migration backup before raising.  A
    successful second runner pass is part of the returned evidence rather than
    an assumption about ``schema_migrations``.
    """
    database_path = Path(db_path)
    chosen_backup = Path(backup_path) if backup_path is not None else database_path.with_name(
        f"{database_path.name}.pre-llmwiki.bak"
    )
    backup_sqlite_database(database_path, chosen_backup)
    before = snapshot_graph_database(database_path)
    runner = MigrationRunner(Database(database_path))
    try:
        applied = tuple(runner.apply())
        # Schema migration and conservative legacy typing are one bootstrap
        # contract.  The entity store only promotes rows with a durable,
        # low-risk explicit-user candidate; every other legacy fact remains
        # untyped and audit-only.
        from app.services.memory_entity_graph import MemoryEntityGraphStore

        entity_store = MemoryEntityGraphStore(database_path)
        try:
            entity_store.backfill_explicit_legacy_candidates()
        finally:
            entity_store.close()
        after = snapshot_graph_database(database_path)
        errors = validate_graph_snapshot(after, previous=before)
        if errors:
            raise MemoryGraphMigrationError(";".join(errors))
        repeated = tuple(runner.apply())
        repeat_snapshot = snapshot_graph_database(database_path)
        repeat_errors = validate_graph_snapshot(repeat_snapshot, previous=after)
        if repeat_errors:
            raise MemoryGraphMigrationError(";".join(repeat_errors))
    except BaseException as exc:
        restore_sqlite_database(chosen_backup, database_path)
        if isinstance(exc, MemoryGraphMigrationError):
            raise
        raise MemoryGraphMigrationError(f"migration_failed:{type(exc).__name__}:{exc}") from exc
    return GraphMigrationReport(
        backup_path=str(chosen_backup),
        applied_versions=applied,
        repeated_apply_versions=repeated,
        before=before,
        after=after,
        repeat_snapshot=repeat_snapshot,
    )
