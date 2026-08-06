from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from app.storage.database import Database, MigrationRunner


def test_explicit_purge_command_securely_reclaims_deleted_pages(tmp_path: Path) -> None:
    database_path = tmp_path / "maintenance.sqlite3"
    database = Database(database_path)
    MigrationRunner(database).apply()
    with database.session() as conn:
        conn.execute("CREATE TABLE purge_probe (payload BLOB NOT NULL)")
        conn.executemany(
            "INSERT INTO purge_probe(payload) VALUES (?)",
            [(b"x" * 8192,) for _ in range(128)],
        )
    populated_size = database_path.stat().st_size
    with database.session() as conn:
        conn.execute("DELETE FROM purge_probe")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.maintenance",
            "purge-deleted-content",
            "--database",
            str(database_path),
        ],
        cwd=Path(__file__).parents[1],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Purged deleted SQLite content" in result.stdout
    assert database_path.stat().st_size < populated_size
    with sqlite3.connect(database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM purge_probe").fetchone()[0] == 0
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
