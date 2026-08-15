from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.storage.database import Database


RESET_CONFIRMATION_TEXT = "RESET_AGENT_PET"
MEMORY_RESET_CONFIRMATION_TEXT = "RESET_AGENT_PET_MEMORY"
FULL_MEMORY_RESET_CONFIRMATION_TEXT = "RESET_AGENT_PET_ALL"


MEMORY_RESET_TABLES = (
    "product_metric_events",
    "post_reply_memory_jobs",
    "agent_checkpoint_decisions",
    "agent_checkpoints",
    "companion_retrieval_reports",
    "companion_retrieval_events",
    "companion_consolidation_run_outputs",
    "companion_consolidation_run_sources",
    "companion_consolidation_runs",
    "memory_feedback_events",
    "memory_activation_events",
    "memory_lifecycle_events",
    "memory_evidence",
    "memory_candidates",
    "memory_graph_events",
    "memory_graph_facts",
    "memory_fact_artifact_bindings",
    "memory_entity_evidence",
    "memory_entity_aliases",
    "wiki_page_bindings",
    "memory_entities",
    "graph_source_state",
    "graph_projection_generations",
    "diary_memory_object_fts",
    "diary_memory_object_sources",
    "diary_memory_objects",
    "daily_chat_memory_entries",
    "continuity_events",
    "continuity_proposals",
    "continuity_state",
    "memory_proposals",
    "agent_actions",
    "agent_runs",
    "messages",
    "conversations",
)


SQLITE_RESET_TABLES = (
    "product_metric_events",
    "post_reply_memory_jobs",
    "apscheduler_jobs",
    "note_fts",
    "diary_memory_object_fts",
    "agent_actions",
    "automation_settings",
    "companion_retrieval_reports",
    "companion_consolidation_run_outputs",
    "companion_consolidation_run_sources",
    "companion_consolidation_runs",
    "memory_feedback_events",
    "memory_activation_events",
    "memory_lifecycle_events",
    "memory_evidence",
    "memory_candidates",
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
    "memory_fact_artifact_bindings",
    "memory_entity_evidence",
    "memory_entity_aliases",
    "wiki_page_bindings",
    "memory_entities",
    "graph_source_state",
    "graph_projection_generations",
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
        cleared_tables = self._clear_sqlite_tables(SQLITE_RESET_TABLES)
        removed_paths = self._remove_runtime_state_paths()
        return LocalStateResetResult(
            status="reset",
            cleared_tables=cleared_tables,
            removed_paths=removed_paths,
        )

    def _clear_sqlite_tables(self, tables: tuple[str, ...]) -> dict[str, int]:
        cleared: dict[str, int] = {}
        with self.database.session() as conn:
            existing = self._existing_tables(conn)
            with conn:
                conn.execute("PRAGMA secure_delete = ON")
                for table in tables:
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


class MemoryStateResetService(LocalStateResetService):
    """Clear personal memory state without touching model credentials or Vault files."""

    def reset(self) -> LocalStateResetResult:
        cleared_tables = self._clear_sqlite_tables(MEMORY_RESET_TABLES)
        removed_paths = self._remove_memory_runtime_paths()
        return LocalStateResetResult(
            status="memory_reset",
            cleared_tables=cleared_tables,
            removed_paths=removed_paths,
        )

    def _remove_memory_runtime_paths(self) -> list[str]:
        removed: list[str] = []
        seen: set[Path] = set()
        for root in self._runtime_state_roots():
            for path in (root / "memory-graph", root / "memory_graph.kuzu"):
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


class FullMemoryResetService(MemoryStateResetService):
    """彻底重置：清空 SQLite 记忆，并删除 Vault 里软件生成的记忆目录。

    Vault 的 Wiki/ 和 Memories/ 是软件自动生成的记忆产物（资料页 + 聊天日记），
    可安全删除。用户的原始资料在 import_root（Vault 之外），Vault 根目录下
    用户自己的其他文件与目录会被保留。
    """

    def __init__(
        self,
        database: Database,
        data_dir: str | Path,
        *,
        vault_root: str | Path | None = None,
    ) -> None:
        super().__init__(database, data_dir)
        self.vault_root = Path(vault_root).resolve() if vault_root else None

    def reset(self) -> LocalStateResetResult:
        result = super().reset()
        removed = list(result.removed_paths)
        removed.extend(self._remove_vault_memory_dirs())
        return LocalStateResetResult(
            status="full_memory_reset",
            cleared_tables=result.cleared_tables,
            removed_paths=removed,
        )

    def _remove_vault_memory_dirs(self) -> list[str]:
        removed: list[str] = []
        if self.vault_root is None or not self.vault_root.exists():
            return removed
        # 安全护栏：绝不删除文件系统根或用户主目录本身
        root = self.vault_root.resolve()
        if root.parent == root:
            return removed
        for name in ("Wiki", "Memories"):
            path = root / name
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(f"{name}/")
        return removed
