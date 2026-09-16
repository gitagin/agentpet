"""One-time bigram FTS backfill for existing local data.

Migrations are SQL-only and cannot bigram Chinese text, so rows written
before the bigram change stay unigrammed until this backfill rewrites
them.  It runs once per database at sidecar startup, guarded by an
app_state marker, and rewrites both FTS tables from their authority
tables (note_chunks and diary_memory_objects).
"""

from __future__ import annotations

import json
import logging
import sqlite3

from app.repositories.storage import _bigram_cjk
from app.storage.database import Database

logger = logging.getLogger(__name__)

BACKFILL_MARKER = "fts_bigram_backfill_v2"
# 分批 executemany：SQLite 变量上限内保持批量，同时避免超大 IN 列表。
_BACKFILL_BATCH = 500


def ensure_bigram_fts(db: Database) -> None:
    with db.session() as conn:
        with conn:
            already = conn.execute(
                "SELECT value FROM app_state WHERE key = ?", (BACKFILL_MARKER,)
            ).fetchone()
            if already is not None:
                return
            _backfill_notes(conn)
            _backfill_diary(conn)
            conn.execute(
                """
                INSERT INTO app_state(key, value, updated_at)
                VALUES (?, '1', datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (BACKFILL_MARKER,),
            )
    logger.info("Bigram FTS backfill completed")


def _backfill_notes(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id AS chunk_id, note_id, vault_id, relative_path, title, heading, content
        FROM note_chunks
        """
    ).fetchall()
    for start in range(0, len(rows), _BACKFILL_BATCH):
        batch = rows[start : start + _BACKFILL_BATCH]
        placeholders = ",".join("?" for _ in batch)
        conn.execute(
            f"DELETE FROM note_fts WHERE chunk_id IN ({placeholders})",
            [str(row["chunk_id"]) for row in batch],
        )
        conn.executemany(
            """
            INSERT INTO note_fts(chunk_id, note_id, vault_id, relative_path, title, heading, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(row["chunk_id"]),
                    str(row["note_id"]),
                    str(row["vault_id"]),
                    str(row["relative_path"]),
                    _bigram_cjk(str(row["title"])),
                    _bigram_cjk(str(row["heading"] or "")),
                    _bigram_cjk(str(row["content"])),
                )
                for row in batch
            ],
        )


def _backfill_diary(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM diary_memory_objects").fetchall()
    for start in range(0, len(rows), _BACKFILL_BATCH):
        batch = rows[start : start + _BACKFILL_BATCH]
        placeholders = ",".join("?" for _ in batch)
        conn.execute(
            f"DELETE FROM diary_memory_object_fts WHERE object_id IN ({placeholders})",
            [str(row["id"]) for row in batch],
        )
        conn.executemany(
            """
            INSERT INTO diary_memory_object_fts(
                object_id, type, summary, topic, emotion, people, keywords
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(row["id"]),
                    str(row["type"]),
                    _bigram_cjk(str(row["summary"])),
                    _bigram_cjk(str(row["topic"] or "")),
                    _bigram_cjk(str(row["emotion"] or "")),
                    _bigram_cjk(" ".join(_json_items(str(row["people_json"])))),
                    _bigram_cjk(" ".join(_json_items(str(row["keywords_json"])))),
                )
                for row in batch
            ],
        )


def _json_items(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]
