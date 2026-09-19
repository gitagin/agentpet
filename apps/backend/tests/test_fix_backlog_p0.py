"""Focused regression coverage for fix-backlog items 1-5."""

from __future__ import annotations

import asyncio
import ctypes
import gc
import logging
import multiprocessing
import os
import sqlite3
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.agents.state import AgentState
from app.api import chat as chat_api
from app.models.enums import AgentRunStatus, MessageStatus
from app.services.settings import InMemoryCredentialStore, SettingsStore
from app.storage.database import (
    BUSY_TIMEOUT_MILLISECONDS,
    Database,
    MigrationRunner,
)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "state.sqlite3")
    MigrationRunner(database).apply()
    return database


def _process_handle_count() -> int:
    if os.name == "nt":
        count = ctypes.c_ulong()
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessHandleCount.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        kernel32.GetProcessHandleCount.restype = ctypes.c_int
        process = kernel32.GetCurrentProcess()
        if not kernel32.GetProcessHandleCount(process, ctypes.byref(count)):
            raise ctypes.WinError()
        return int(count.value)
    proc_fds = Path("/proc/self/fd")
    if proc_fds.is_dir():
        return len(tuple(proc_fds.iterdir()))
    pytest.skip("This platform does not expose a process handle count.")


def _request_for(database: Database) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(database=database)),
        state=SimpleNamespace(request_id="p0-test"),
    )


def _insert_stream_message(database: Database, *, message_id: str = "assistant-1") -> None:
    now = "2026-08-04T00:00:00Z"
    with database.session() as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, title, status, created_at, updated_at)
            VALUES ('conversation-1', 'test', 'active', ?, ?)
            """,
            (now, now),
        )
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, 'conversation-1', 'assistant', '', 'partial', ?, ?)
            """,
            (message_id, now, now),
        )


def _seed_interrupted_process(database_path: str, ready) -> None:
    database = Database(database_path)
    MigrationRunner(database).apply()
    now = "2026-08-04T00:00:00Z"
    with database.session() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, status, created_at, updated_at) VALUES ('killed-c', 'c', 'active', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at) VALUES ('killed-u', 'killed-c', 'user', 'u', 'completed', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at) VALUES ('killed-a', 'killed-c', 'assistant', 'partial', 'partial', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO agent_runs (id, conversation_id, user_message_id, assistant_message_id, status, created_at, updated_at) VALUES ('killed-run', 'killed-c', 'killed-u', 'killed-a', 'running', ?, ?)",
            (now, now),
        )
    ready.set()
    while True:
        time.sleep(1)


def test_database_session_sets_contention_pragmas_and_closes(tmp_path: Path) -> None:
    database = _database(tmp_path)

    with database.session() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MILLISECONDS
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_repeated_database_sessions_do_not_leak_process_handles(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.session() as conn:
        conn.execute("SELECT 1").fetchone()
    gc.collect()
    baseline = _process_handle_count()

    for _ in range(250):
        with database.session() as conn:
            conn.execute("SELECT 1").fetchone()

    gc.collect()
    assert _process_handle_count() <= baseline + 2


def test_production_sqlite_connections_are_centralized() -> None:
    app_root = Path(__file__).parents[1] / "app"
    offenders = []
    for path in app_root.rglob("*.py"):
        if path == app_root / "storage" / "database.py":
            continue
        if "sqlite3.connect(" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(app_root).as_posix())
    assert offenders == []


def test_settings_store_uses_database_and_runs_data_migration_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    from app.services import settings as settings_module

    settings_module._DATA_MIGRATIONS_DONE.clear()
    calls: list[int] = []
    original = SettingsStore._run_data_migrations

    def tracked(store: SettingsStore) -> None:
        calls.append(1)
        original(store)

    monkeypatch.setattr(SettingsStore, "_run_data_migrations", tracked)
    first = SettingsStore(database, credential_store=InMemoryCredentialStore())
    assert first.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    first.close()
    second = SettingsStore(database, credential_store=InMemoryCredentialStore())
    second.close()

    assert calls == [1]


def test_settings_store_session_enforces_foreign_keys_and_skips_schema_probe_after_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    from app.services import settings as settings_module

    settings_module._DATA_MIGRATIONS_DONE.clear()
    settings_module.initialize_settings_store(database)
    statements: list[str] = []
    original_connect = database.connect

    def traced_connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(database, "connect", traced_connect)
    store = SettingsStore(database, credential_store=InMemoryCredentialStore())
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
                VALUES ('orphan', 'missing-conversation', 'assistant', '', 'partial', 'now', 'now')
                """
            )
        store.conn.rollback()
    finally:
        store.close()

    assert not any("sqlite_master" in statement.lower() for statement in statements)


def test_stream_partial_persistence_reuses_one_connection_and_stays_under_twenty_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    _insert_stream_message(database)
    request = _request_for(database)
    persister = chat_api._StreamPartialPersister(request, "assistant-1")
    writes: list[str] = []
    connections: list[sqlite3.Connection] = []
    original_write = persister._write_sync
    original_connect = database.connect

    def tracked_write(content: str, status_value: str, answer_basis="not_assessed") -> None:
        writes.append(status_value)
        original_write(content, status_value, answer_basis)

    def tracked_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(persister, "_write_sync", tracked_write)
    monkeypatch.setattr(database, "connect", tracked_connect)

    async def run_real() -> None:
        chunks: list[str] = []
        for _ in range(800):
            chunks.append("x")
            await persister.note_token(chunks)
        await persister.persist_terminal("".join(chunks), MessageStatus.COMPLETED.value)
        await persister.close()

    asyncio.run(run_real())

    partial_writes = writes.count(MessageStatus.PARTIAL.value)
    assert partial_writes <= 18
    # INSERT + partial UPDATEs + one terminal UPDATE.
    assert 1 + len(writes) <= 20
    assert len(connections) == 1

    with database.session() as conn:
        row = conn.execute(
            "SELECT content, status FROM messages WHERE id = 'assistant-1'"
        ).fetchone()
    assert row["content"] == "x" * 800
    assert row["status"] == MessageStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_stream_partial_write_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    _insert_stream_message(database)
    persister = chat_api._StreamPartialPersister(_request_for(database), "assistant-1")
    started = threading.Event()
    release = threading.Event()
    original_write = persister._write_sync

    def blocked_write(content: str, status_value: str, answer_basis="not_assessed") -> None:
        started.set()
        while not release.is_set():
            time.sleep(0.005)
        original_write(content, status_value, answer_basis)

    monkeypatch.setattr(persister, "_write_sync", blocked_write)
    pending: asyncio.Task[None] | None = None
    try:
        for _ in range(49):
            await persister.note_token(["x"])
        pending = asyncio.create_task(persister.note_token(["x"]))
        await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=1)

        ticks = 0
        deadline = asyncio.get_running_loop().time() + 0.05
        while asyncio.get_running_loop().time() < deadline:
            ticks += 1
            await asyncio.sleep(0)
        assert ticks > 0
    finally:
        release.set()
        if pending is not None:
            await pending
        await persister.close()


@pytest.mark.asyncio
async def test_two_concurrent_stream_persisters_do_not_block_each_other(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    _insert_stream_message(database, message_id="assistant-1")
    with database.session() as conn:
        now = "2026-08-04T00:00:00Z"
        conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES ('assistant-2', 'conversation-1', 'assistant', '', 'partial', ?, ?)
            """,
            (now, now),
        )

    first = chat_api._StreamPartialPersister(_request_for(database), "assistant-1")
    second = chat_api._StreamPartialPersister(_request_for(database), "assistant-2")
    first_write_started = threading.Event()
    release_first_write = threading.Event()
    original_first_write = first._write_sync

    def blocked_first_write(content: str, status_value: str, answer_basis="not_assessed") -> None:
        first_write_started.set()
        while not release_first_write.is_set():
            time.sleep(0.005)
        original_first_write(content, status_value, answer_basis)

    monkeypatch.setattr(first, "_write_sync", blocked_first_write)
    blocked_task: asyncio.Task[None] | None = None
    try:
        first_chunks: list[str] = []
        for _ in range(49):
            first_chunks.append("a")
            await first.note_token(first_chunks)
        first_chunks.append("a")
        blocked_task = asyncio.create_task(first.note_token(first_chunks))
        assert await asyncio.wait_for(asyncio.to_thread(first_write_started.wait), timeout=1)

        second_chunks: list[str] = []
        for _ in range(50):
            second_chunks.append("b")
            await asyncio.wait_for(second.note_token(second_chunks), timeout=1)
        await asyncio.wait_for(
            second.persist_terminal("".join(second_chunks), MessageStatus.COMPLETED.value),
            timeout=1,
        )
    finally:
        release_first_write.set()
        if blocked_task is not None:
            await blocked_task
        await first.close()
        await second.close()

    with database.session() as conn:
        row = conn.execute("SELECT content, status FROM messages WHERE id = 'assistant-2'").fetchone()
    assert tuple(row) == ("b" * 50, MessageStatus.COMPLETED.value)


def test_recover_interrupted_chat_runs_closes_running_and_partial_rows(tmp_path: Path) -> None:
    database = _database(tmp_path)
    now = "2026-08-04T00:00:00Z"
    with database.session() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, status, created_at, updated_at) VALUES ('c', 'c', 'active', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at) VALUES ('u', 'c', 'user', 'u', 'completed', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at) VALUES ('a', 'c', 'assistant', 'partial text', 'partial', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO agent_runs (id, conversation_id, user_message_id, assistant_message_id, status, created_at, updated_at) VALUES ('run', 'c', 'u', 'a', 'running', ?, ?)",
            (now, now),
        )

    recovered = chat_api.recover_interrupted_chat_runs(database)
    assert recovered >= 2
    with database.session() as conn:
        run = conn.execute("SELECT status, error_code FROM agent_runs WHERE id = 'run'").fetchone()
        message = conn.execute("SELECT status, content FROM messages WHERE id = 'a'").fetchone()
    assert tuple(run) == (AgentRunStatus.CANCELLED.value, "process_interrupted")
    assert tuple(message) == (MessageStatus.CANCELLED.value, "partial text")


def test_app_startup_recovers_persisted_chat_rows(client_factory) -> None:
    sqlite_name = "restart-recovery.sqlite3"
    now = "2026-08-04T00:00:00Z"
    with client_factory(sqlite_name=sqlite_name) as first_client:
        database = first_client.app.state.database
        with database.session() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, status, created_at, updated_at) VALUES ('restart-c', 'c', 'active', ?, ?)",
                (now, now),
            )
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at) VALUES ('restart-u', 'restart-c', 'user', 'u', 'completed', ?, ?)",
                (now, now),
            )
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at) VALUES ('restart-a', 'restart-c', 'assistant', 'partial', 'partial', ?, ?)",
                (now, now),
            )
            conn.execute(
                "INSERT INTO agent_runs (id, conversation_id, user_message_id, assistant_message_id, status, created_at, updated_at) VALUES ('restart-run', 'restart-c', 'restart-u', 'restart-a', 'running', ?, ?)",
                (now, now),
            )

    with client_factory(sqlite_name=sqlite_name) as restarted_client:
        with restarted_client.app.state.database.session() as conn:
            run = conn.execute(
                "SELECT status, error_code FROM agent_runs WHERE id = 'restart-run'"
            ).fetchone()
            message = conn.execute(
                "SELECT status FROM messages WHERE id = 'restart-a'"
            ).fetchone()
    assert tuple(run) == (AgentRunStatus.CANCELLED.value, "process_interrupted")
    assert tuple(message) == (MessageStatus.CANCELLED.value,)


def test_forcibly_terminated_process_is_recovered_on_real_app_restart(
    client_factory,
    tmp_path: Path,
) -> None:
    sqlite_name = "killed-process-recovery.sqlite3"
    database_path = tmp_path / sqlite_name
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=_seed_interrupted_process, args=(str(database_path), ready))
    process.start()
    try:
        assert ready.wait(timeout=10)
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)

    with client_factory(sqlite_name=sqlite_name) as restarted_client:
        with restarted_client.app.state.database.session() as conn:
            run = conn.execute(
                "SELECT status, error_code FROM agent_runs WHERE id = 'killed-run'"
            ).fetchone()
            message = conn.execute(
                "SELECT status FROM messages WHERE id = 'killed-a'"
            ).fetchone()
    assert tuple(run) == (AgentRunStatus.CANCELLED.value, "process_interrupted")
    assert tuple(message) == (MessageStatus.CANCELLED.value,)


@pytest.mark.asyncio
async def test_post_reply_tasks_are_strongly_referenced_and_log_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = SimpleNamespace()
    request = SimpleNamespace(app=app, state=SimpleNamespace(request_id="p0-task"))
    state = AgentState(
        conversation_id="c",
        message_id="m",
        agent_run_id="run",
        user_message="hello",
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def worker(context, worker_state, message_id, final_text):
        started.set()
        await release.wait()

    monkeypatch.setattr(chat_api, "_complete_assistant_message_background", worker)
    chat_api._POST_REPLY_TASKS.clear()
    chat_api._schedule_post_reply_work(request, state, "assistant", "reply")
    await started.wait()
    assert len(chat_api._POST_REPLY_TASKS) == 1
    task = next(iter(chat_api._POST_REPLY_TASKS))
    release.set()
    await task
    await asyncio.sleep(0)
    assert not chat_api._POST_REPLY_TASKS


@pytest.mark.asyncio
async def test_post_reply_task_pressure_completes_every_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SimpleNamespace()
    request = SimpleNamespace(app=app, state=SimpleNamespace(request_id="p0-pressure"))
    state = AgentState(
        conversation_id="c",
        message_id="m",
        agent_run_id="run",
        user_message="hello",
    )
    completed: set[str] = set()

    async def worker(context, worker_state, message_id, final_text):
        await asyncio.sleep(0)
        completed.add(message_id)

    monkeypatch.setattr(chat_api, "_complete_assistant_message_background", worker)
    chat_api._POST_REPLY_TASKS.clear()
    expected = {f"assistant-{index}" for index in range(100)}
    for message_id in expected:
        chat_api._schedule_post_reply_work(request, state, message_id, "reply")
    tasks = tuple(chat_api._POST_REPLY_TASKS)
    assert len(tasks) == len(expected)
    await asyncio.gather(*tasks)
    await asyncio.sleep(0)

    assert completed == expected
    assert not chat_api._POST_REPLY_TASKS


@pytest.mark.asyncio
async def test_continuity_failures_keep_proposals_visible_and_log_tracebacks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = AgentState(
        conversation_id="c",
        message_id="m",
        agent_run_id="run",
        user_message="hello",
    )
    proposal = SimpleNamespace(
        id="proposal-1",
        kind="identity",
        summary="summary",
        evidence="evidence",
        confidence=0.95,
        source_conversation_id="c",
        source_message_id="m",
        status="pending",
    )

    class FailingConfirmService:
        closed = False

        async def create_proposals_from_exchange(self, **kwargs):
            return [proposal]

        def confirm_proposal(self, proposal_id: str):
            raise RuntimeError("injected confirm failure")

        def close(self) -> None:
            self.closed = True

    service = FailingConfirmService()
    request = SimpleNamespace(app=SimpleNamespace(), state=SimpleNamespace(request_id="p0-continuity"))
    monkeypatch.setattr(chat_api, "continuity_service", lambda _request: service)
    monkeypatch.setattr(chat_api, "chat_model_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        chat_api,
        "automation_settings",
        lambda _request: SimpleNamespace(auto_structured_memory=True),
    )

    class AllowPolicy:
        def decide(self, *args, **kwargs):
            return SimpleNamespace(decision="allow", risk_tier="low", reason="test")

    monkeypatch.setattr(chat_api, "AutomationPolicy", AllowPolicy)
    caplog.set_level(logging.WARNING, logger=chat_api.__name__)
    events = [
        event
        async for event in chat_api._create_continuity_proposals(
            request,
            state,
            assistant_answer="answer",
        )
    ]

    assert len(events) == 1
    assert events[0].proposal_id == proposal.id
    assert service.closed is True
    record = next(record for record in caplog.records if "auto-confirm failed" in record.message)
    assert record.exc_info is not None

    async def failing_worker(context, worker_state, message_id, final_text):
        raise RuntimeError("injected post-reply failure")

    monkeypatch.setattr(chat_api, "_complete_assistant_message_background", failing_worker)
    caplog.set_level(logging.WARNING, logger=chat_api.__name__)
    chat_api._schedule_post_reply_work(request, state, "assistant-2", "reply")
    failing_task = next(iter(chat_api._POST_REPLY_TASKS))
    with pytest.raises(RuntimeError, match="injected post-reply failure"):
        await failing_task
    await asyncio.sleep(0)
    record = next(record for record in caplog.records if "Post-reply chat memory task failed" in record.message)
    assert record.exc_info is not None
    assert not chat_api._POST_REPLY_TASKS
