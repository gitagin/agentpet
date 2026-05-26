from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.database import Database, MigrationRunner


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def migrate_db(db_path: Path) -> Path:
    MigrationRunner(Database(db_path)).apply()
    return db_path


def migrate_db_with_vault(db_path: Path, *, vault_id: str = "vault-1") -> Path:
    migrate_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR IGNORE INTO vaults(id, root_path, name) VALUES (?, ?, ?)",
            (vault_id, str(db_path.parent / "Vault"), "Vault"),
        )
    return db_path


def migrated_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(migration.read_text(encoding="utf-8"))
    return conn
