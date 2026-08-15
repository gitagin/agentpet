from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.state import AgentState
from app.api import chat as chat_api
from app.services.post_reply_memory_jobs import PostReplyMemoryJobStore
from app.storage.database import Database, MigrationRunner


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "state.sqlite3")
    MigrationRunner(database).apply()
    return database


def _app(database: Database) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(database=database))


def _seed_chat(database: Database) -> None:
    now = "2026-08-09T00:00:00Z"
    with database.session() as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, title, status, created_at, updated_at)
            VALUES ('conversation-job', 'job test', 'active', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES ('user-job', 'conversation-job', 'user', 'Remember Project Atlas.', 'completed', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES ('assistant-job', 'conversation-job', 'assistant', 'The answer is durable.', 'completed', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO agent_runs
                (id, conversation_id, user_message_id, assistant_message_id, status, created_at, updated_at)
            VALUES ('run-job', 'conversation-job', 'user-job', 'assistant-job', 'success', ?, ?)
            """,
            (now, now),
        )


def test_expired_job_at_retry_limit_becomes_terminal_failed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_chat(database)
    store = PostReplyMemoryJobStore(database.path)
    store.enqueue(
        job_id="job-expired",
        agent_run_id="run-job",
        conversation_id="conversation-job",
        user_message_id="user-job",
        assistant_message_id="assistant-job",
    )
    try:
        with database.session() as conn:
            conn.execute(
                """
                UPDATE post_reply_memory_jobs
                SET status = 'running', attempts = 3,
                    lease_expires_at = '2000-01-01T00:00:00Z',
                    updated_at = '2026-08-09T00:00:00Z'
                WHERE id = 'job-expired'
                """
            )
        assert store.requeue_expired(max_attempts=3) == 0
        record = store.get("job-expired")
        assert record is not None
        assert record.status == "failed"
        assert record.last_error_code == "post_reply_retry_exhausted"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_startup_recovery_rebuilds_authoritative_messages_and_completes_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    _seed_chat(database)
    store = PostReplyMemoryJobStore(database.path)
    store.enqueue(
        job_id="job-recover",
        agent_run_id="run-job",
        conversation_id="conversation-job",
        user_message_id="user-job",
        assistant_message_id="assistant-job",
    )
    store.close()

    observed: list[tuple[str, str, str]] = []

    async def worker(_context, state: AgentState, assistant_message_id: str, final_text: str) -> None:
        observed.append((state.user_message, assistant_message_id, final_text))

    monkeypatch.setattr(chat_api, "_complete_assistant_message_background", worker)
    app = _app(database)
    chat_api._POST_REPLY_TASKS.clear()

    assert chat_api.recover_post_reply_memory_jobs(app) == 1
    tasks = tuple(chat_api._POST_REPLY_TASKS)
    assert len(tasks) == 1
    await asyncio.gather(*tasks)
    await asyncio.sleep(0)

    assert observed == [("Remember Project Atlas.", "assistant-job", "The answer is durable.")]
    check = PostReplyMemoryJobStore(database.path)
    try:
        record = check.get("job-recover")
        assert record is not None
        assert record.status == "completed"
        assert record.attempts == 1
    finally:
        check.close()
