from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.api.services.adapters import _wiki_query_archive_has_partial_effect
from app.services.memory import SafeMarkdownWriter
from app.storage.database import Database, MigrationRunner


def _service(tmp_path: Path):
    database = Database(tmp_path / "state.sqlite3")
    MigrationRunner(database).apply()
    writer = SafeMarkdownWriter(tmp_path / "Vault")
    return database, SimpleNamespace(database=database, wiki=SimpleNamespace(writer=writer))


def test_query_archive_recovery_does_not_replay_clean_failure(tmp_path: Path) -> None:
    database, service = _service(tmp_path)
    try:
        assert (
            _wiki_query_archive_has_partial_effect(
                service,
                archive_id="archive-clean-failure",
                target_path="Wiki/Reports/Answer.md",
                marker="<!-- action:clean-failure -->",
            )
            is False
        )
    finally:
        database.path.unlink(missing_ok=True)


def test_query_archive_recovery_replays_when_target_marker_is_durable(tmp_path: Path) -> None:
    database, service = _service(tmp_path)
    target = service.wiki.writer.resolve_markdown_path("Wiki/Reports/Answer.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("<!-- action:partial -->\n# Answer\n", encoding="utf-8")
    try:
        assert (
            _wiki_query_archive_has_partial_effect(
                service,
                archive_id="archive-marker",
                target_path="Wiki/Reports/Answer.md",
                marker="<!-- action:partial -->",
            )
            is True
        )
    finally:
        database.path.unlink(missing_ok=True)


def test_query_archive_recovery_replays_when_archive_row_is_durable(tmp_path: Path) -> None:
    database, service = _service(tmp_path)
    archive_id = "archive-row"
    with database.session() as conn:
        conn.execute(
            """
            INSERT INTO wiki_query_archives(
                id, question, answer_preview, answer, title, target_path,
                page_title, page_operation, page_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                archive_id,
                "Question?",
                "Answer",
                "Answer",
                "Answer",
                "Wiki/Reports/Answer.md",
                "Answer",
                "replace_section",
                "created",
            ),
        )
    try:
        assert (
            _wiki_query_archive_has_partial_effect(
                service,
                archive_id=archive_id,
                target_path="Wiki/Reports/Answer.md",
                marker="<!-- action:not-on-page -->",
            )
            is True
        )
    finally:
        database.path.unlink(missing_ok=True)
