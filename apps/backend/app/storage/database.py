from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn


class MigrationRunner:
    def __init__(self, database: Database, migrations_dir: str | Path | None = None) -> None:
        self.database = database
        self.migrations_dir = Path(migrations_dir) if migrations_dir else self._default_dir()

    def apply(self) -> list[str]:
        applied: list[str] = []
        with self.database.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            seen = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for migration in sorted(self.migrations_dir.glob("*.sql")):
                version = migration.stem
                if version in seen:
                    continue
                with conn:
                    conn.executescript(migration.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations(version) VALUES (?)",
                        (version,),
                    )
                applied.append(version)
        return applied

    @staticmethod
    def _default_dir() -> Path:
        return Path(__file__).resolve().parents[2] / "migrations"
