import asyncio
import shutil

from app.api import chat
from app.storage.database import Database, MigrationRunner
from tests.test_fix_backlog_p0 import _insert_stream_message, _request_for


def test_legacy_migration_retains_content_and_defaults_to_unassessed(tmp_path):
    database = Database(tmp_path / "db.sqlite")
    runner = MigrationRunner(database)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for path in runner.migrations_dir.glob("*.sql"):
        if path.name < "034":
            shutil.copyfile(path, legacy / path.name)
    MigrationRunner(database, legacy).apply()
    _insert_stream_message(database)
    with database.session() as conn:
        conn.execute("UPDATE messages SET content = 'Old answer', status = 'completed'")
    runner.apply()
    assert runner.apply() == []
    with database.session() as conn:
        row = conn.execute("SELECT content, answer_basis FROM messages").fetchone()
        assert tuple(row) == ("Old answer", "not_assessed")


def test_terminal_write_and_daily_history_roundtrip(tmp_path):
    database = Database(tmp_path / "db.sqlite")
    MigrationRunner(database).apply()
    _insert_stream_message(database)
    request = _request_for(database)
    persister = chat._StreamPartialPersister(request, "assistant-1")

    async def save():
        try:
            await persister.persist_terminal("Grounded answer", "completed", "local_evidence_context")
        finally:
            await persister.close()

    asyncio.run(save())
    result = asyncio.run(chat.get_daily_chat_history(
        request, date="2026-08-04", timezone_name="UTC", limit=10,
    ))
    assert result.messages[0].content == "Grounded answer"
    assert result.messages[0].answer_basis == "local_evidence_context"


def test_failed_and_unknown_values_never_restore_as_grounded(tmp_path):
    database = Database(tmp_path / "db.sqlite")
    MigrationRunner(database).apply()
    _insert_stream_message(database)
    request = _request_for(database)
    persister = chat._StreamPartialPersister(request, "assistant-1")

    async def save():
        try:
            await persister.persist_terminal("Failed", "failed", "local_evidence_context")
        finally:
            await persister.close()

    asyncio.run(save())
    with database.session() as conn:
        assert conn.execute("SELECT answer_basis FROM messages").fetchone()[0] == "not_assessed"
        conn.execute("UPDATE messages SET status = 'completed', answer_basis = 'verified'")
    result = asyncio.run(chat.get_daily_chat_history(
        request, date="2026-08-04", timezone_name="UTC", limit=10,
    ))
    assert result.messages[0].answer_basis == "not_assessed"
