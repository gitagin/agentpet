from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


WIKI_CORE_FILES = {
    "Wiki/AGENTS.md",
    "Wiki/index.md",
    "Wiki/log.md",
}


@dataclass(frozen=True)
class LocalAssetStats:
    vault_configured: bool
    vault_id: str | None
    chat_diary_days: int
    chat_diary_entries: int
    long_term_memory_count: int
    wiki_page_count: int
    task_count: int
    completed_task_count: int
    latest_organization_at: str | None
    reversible_operation_count: int


class LocalAssetStatsService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        vault_id: str | None = None,
        vault_root: str | Path | None = None,
    ) -> None:
        self.conn = conn
        self.vault_id = vault_id
        self.vault_root = Path(vault_root) if vault_root else None

    def summarize(self) -> LocalAssetStats:
        return LocalAssetStats(
            vault_configured=bool(self.vault_id and self.vault_root),
            vault_id=self.vault_id,
            chat_diary_days=self._count_distinct_chat_diary_days(),
            chat_diary_entries=self._count_rows("daily_chat_memory_entries"),
            long_term_memory_count=self._count_active_long_term_memories(),
            wiki_page_count=self._count_wiki_pages(),
            task_count=self._count_rows("tasks"),
            completed_task_count=self._count_completed_tasks(),
            latest_organization_at=self._latest_organization_at(),
            reversible_operation_count=self._count_reversible_operations(),
        )

    def _count_rows(self, table: str) -> int:
        row = self.conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"] or 0)

    def _count_distinct_chat_diary_days(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT memory_date) AS count FROM daily_chat_memory_entries"
        ).fetchone()
        return int(row["count"] or 0)

    def _count_active_long_term_memories(self) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM memory_graph_facts
            WHERE status IN ('active', 'candidate')
            """
        ).fetchone()
        return int(row["count"] or 0)

    def _count_completed_tasks(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM tasks WHERE status = 'done'"
        ).fetchone()
        return int(row["count"] or 0)

    def _latest_organization_at(self) -> str | None:
        row = self.conn.execute(
            """
            SELECT MAX(COALESCE(completed_at, updated_at, created_at)) AS latest
            FROM agent_actions
            WHERE status IN ('completed', 'reverted', 'skipped')
            """
        ).fetchone()
        return str(row["latest"]) if row["latest"] else None

    def _count_reversible_operations(self) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM agent_actions
            WHERE reversible = 1
              AND status = 'completed'
              AND reverted_by IS NULL
              AND reverts_action_id IS NULL
            """
        ).fetchone()
        return int(row["count"] or 0)

    def _count_wiki_pages(self) -> int:
        if self.vault_root is None:
            return 0
        wiki_root = self.vault_root / "Wiki"
        if not wiki_root.exists() or not wiki_root.is_dir():
            return 0

        count = 0
        for path in wiki_root.rglob("*.md"):
            if not path.is_file():
                continue
            relative_path = path.relative_to(self.vault_root).as_posix()
            if relative_path in WIKI_CORE_FILES:
                continue
            count += 1
        return count
