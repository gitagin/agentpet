from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.storage.database import Database


RESET_CONFIRMATION_TEXT = "RESET_AGENT_PET"


SQLITE_RESET_TABLES = (
    "note_fts",
    "diary_memory_object_fts",
    "wiki_workflow_page_updates",
    "wiki_ingest_reviews",
    "wiki_query_archives",
    "wiki_sources",
    "wiki_log_events",
    "wiki_workflow_runs",
    "vector_chunks",
    "note_chunks",
    "notes",
    "index_jobs",
    "continuity_events",
    "continuity_state",
    "continuity_proposals",
    "memory_graph_events",
    "memory_graph_facts",
    "diary_memory_object_sources",
    "diary_memory_objects",
    "daily_chat_memory_entries",
    "memory_proposals",
    "agent_runs",
    "messages",
    "conversations",
    "reminders",
    "tasks",
    "app_state",
    "vaults",
    "agent_model_configs",
    "embedding_config",
    "embedding_keys",
    "model_config",
    "model_keys",
    "audit_logs",
)


@dataclass(frozen=True)
class LocalStateResetResult:
    status: str
    cleared_tables: dict[str, int] = field(default_factory=dict)
    removed_paths: list[str] = field(default_factory=list)


class LocalStateResetService:
    def __init__(self, database: Database, data_dir: str | Path) -> None:
        self.database = database
        self.data_dir = Path(data_dir)

    def reset(self) -> LocalStateResetResult:
        cleared_tables = self._clear_sqlite_tables()
        removed_paths = self._remove_runtime_state_paths()
        return LocalStateResetResult(
            status="reset",
            cleared_tables=cleared_tables,
            removed_paths=removed_paths,
        )

    def _clear_sqlite_tables(self) -> dict[str, int]:
        cleared: dict[str, int] = {}
        with self.database.connect() as conn:
            existing = self._existing_tables(conn)
            with conn:
                conn.execute("PRAGMA secure_delete = ON")
                for table in SQLITE_RESET_TABLES:
                    if table not in existing:
                        continue
                    before = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                    conn.execute(f'DELETE FROM "{table}"')
                    cleared[table] = before
            conn.execute("VACUUM")
        return cleared

    def _remove_runtime_state_paths(self) -> list[str]:
        candidates = [self.database.path.with_suffix(f"{self.database.path.suffix}.credentials")]
        for root in self._runtime_state_roots():
            candidates.extend(
                (
                    root / "vector-index",
                    root / "memory-graph",
                    root / "memory_graph.kuzu",
                )
            )
        removed: list[str] = []
        seen: set[Path] = set()
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(path.name)
        return removed

    def _runtime_state_roots(self) -> list[Path]:
        return [self.data_dir, self.database.path.parent]

    @staticmethod
    def _existing_tables(conn: sqlite3.Connection) -> set[str]:
        return {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
