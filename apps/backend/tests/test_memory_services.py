import pytest
from datetime import datetime, timedelta, timezone

from apps.backend.tests._schema import migrated_connection
from app.models.enums import MemoryProposalStatus, MemoryProposalType
from app.services.agent_actions import AgentActionCreate, AgentActionService, AgentActionStore
from app.services.memory import (
    MarkdownWriteHooks,
    MemoryConflictError,
    MemoryProposalStore,
    MemoryService,
    SafeMarkdownWriter,
    content_hash_bytes,
)
from app.services.retrospectives import RetrospectiveService


def build_service(tmp_path, hooks=None, index_refresh=None):
    store = MemoryProposalStore(migrated_connection())
    writer = SafeMarkdownWriter(tmp_path, hooks=hooks)
    return MemoryService(store, writer, index_refresh=index_refresh)


def test_confirm_proposal_appends_markdown_and_marks_confirmed(tmp_path):
    target = tmp_path / "People.md"
    target.write_text("Existing\n", encoding="utf-8")
    service = build_service(tmp_path, index_refresh=lambda path: f"index:{path}")

    proposal = service.create_proposal(
        type=MemoryProposalType.FACT,
        content="- User prefers concise updates.",
        target_path="People.md",
        source_message_id="msg-1",
    )

    result = service.confirm_proposal(proposal.id)

    assert result.status == MemoryProposalStatus.CONFIRMED
    assert result.index_job_id == "index:People.md"
    assert target.read_text(encoding="utf-8") == "Existing\n\n- User prefers concise updates.\n"
    stored = service.store.get(proposal.id)
    assert stored.status == MemoryProposalStatus.CONFIRMED
    assert stored.written_path == str(target)


def test_confirm_rejects_when_target_content_hash_changed(tmp_path):
    target = tmp_path / "Memory.md"
    target.write_text("Initial\n", encoding="utf-8")
    service = build_service(tmp_path)
    proposal = service.create_proposal(
        type=MemoryProposalType.FACT,
        content="- New memory",
        target_path="Memory.md",
    )
    assert proposal.target_content_hash == content_hash_bytes(target.read_bytes())

    target.write_text("Changed\n", encoding="utf-8")

    with pytest.raises(MemoryConflictError):
        service.confirm_proposal(proposal.id)

    stored = service.store.get(proposal.id)
    assert stored.status == MemoryProposalStatus.PENDING
    assert target.read_text(encoding="utf-8") == "Changed\n"


def test_reject_proposal_does_not_write_markdown(tmp_path):
    service = build_service(tmp_path)
    proposal = service.create_proposal(
        type=MemoryProposalType.GOAL,
        content="- Learn Rust",
        target_path="Goals.md",
    )

    rejected = service.reject_proposal(proposal.id, "not useful")

    assert rejected.status == MemoryProposalStatus.REJECTED
    assert rejected.rejected_reason == "not useful"
    assert not (tmp_path / "Goals.md").exists()


def test_safe_markdown_write_hooks_are_called(tmp_path):
    calls = []

    hooks = MarkdownWriteHooks(
        before_write=lambda path, text: calls.append(("before", path.name, text)),
        after_write=lambda path, text: calls.append(("after", path.name, text)),
    )
    writer = SafeMarkdownWriter(tmp_path, hooks=hooks)

    writer.write("Inbox/Pending Memories.md", "- Pending memory\n")

    assert (tmp_path / "Inbox" / "Pending Memories.md").read_text(encoding="utf-8") == "- Pending memory\n"
    assert calls == [
        ("before", "Pending Memories.md", "- Pending memory\n"),
        ("after", "Pending Memories.md", "- Pending memory\n"),
    ]


def test_safe_markdown_write_removes_backup_after_success(tmp_path):
    target = tmp_path / "Memory.md"
    backup = tmp_path / "Memory.md.bak"
    target.write_text("Old\n", encoding="utf-8")
    writer = SafeMarkdownWriter(tmp_path)

    writer.write("Memory.md", "New\n")

    assert target.read_text(encoding="utf-8") == "New\n"
    assert not backup.exists()


def test_safe_markdown_writers_share_lock_for_same_file(tmp_path):
    first = SafeMarkdownWriter(tmp_path)
    second = SafeMarkdownWriter(tmp_path)
    target = first.resolve_markdown_path("Memory.md")

    assert first._lock_for(target) is second._lock_for(target)


def test_safe_markdown_write_restores_backup_when_after_hook_fails(tmp_path):
    target = tmp_path / "Memory.md"
    backup = tmp_path / "Memory.md.bak"
    target.write_text("Old\n", encoding="utf-8")

    def fail_after_write(path, text):
        raise RuntimeError("index refresh failed")

    writer = SafeMarkdownWriter(tmp_path, hooks=MarkdownWriteHooks(after_write=fail_after_write))

    with pytest.raises(RuntimeError, match="index refresh failed"):
        writer.write("Memory.md", "New\n")

    assert target.read_text(encoding="utf-8") == "Old\n"
    assert not backup.exists()


def test_safe_markdown_write_removes_new_file_when_after_hook_fails(tmp_path):
    target = tmp_path / "Memory.md"

    def fail_after_write(path, text):
        raise RuntimeError("index refresh failed")

    writer = SafeMarkdownWriter(tmp_path, hooks=MarkdownWriteHooks(after_write=fail_after_write))

    with pytest.raises(RuntimeError, match="index refresh failed"):
        writer.write("Memory.md", "New\n")

    assert not target.exists()


def test_retrospective_service_builds_local_windows_from_tracked_sources(tmp_path):
    conn = migrated_connection()
    now = "2026-06-02T00:00:00Z"
    conn.execute("INSERT INTO vaults(id, root_path, name) VALUES ('vault-1', ?, 'Vault')", (str(tmp_path),))
    conn.execute(
        """
        INSERT INTO diary_memory_objects (
            id, vault_id, type, summary, topic, emotion, people_json,
            keywords_json, importance, confidence, occurred_at, timezone,
            status, object_hash, extraction_model, created_at, updated_at
        )
        VALUES
            ('diary-1', 'vault-1', 'event', 'Reviewed TASK-03 retrospective UI.', 'product review', 'focused', '[]',
             '["retrospective","focus"]', 0.9, 0.95, '2026-06-01T12:00:00Z', 'UTC', 'active', 'hash-diary-1', 'fake', ?, ?),
            ('diary-2', 'vault-1', 'event', 'Planned another retrospective pass.', 'product review', 'focused', '[]',
             '["retrospective","focus"]', 0.7, 0.9, '2026-05-30T12:00:00Z', 'UTC', 'active', 'hash-diary-2', 'fake', ?, ?)
        """,
        (now, now, now, now),
    )
    conn.execute(
        """
        INSERT INTO diary_memory_object_sources(
            object_id, source_type, source_id, markdown_path, agent_run_id
        )
        VALUES
            ('diary-1', 'chat_exchange', 'run-1', 'Memories/Daily/2026-06-01.md', 'run-1'),
            ('diary-2', 'chat_exchange', 'run-2', 'Memories/Daily/2026-05-30.md', 'run-2')
        """
    )
    conn.execute(
        """
        INSERT INTO memory_graph_facts (
            id, fact_key, conflict_key, category, subject, predicate, object,
            status, confidence, source_text, source_type, support_count,
            created_at, updated_at, memory_type, entity_type, occurred_at,
            expires_at, metadata_json, importance
        )
        VALUES (
            'fact-1', 'fact-key-1', 'conflict-1', 'preference', 'status updates',
            'prefers', 'concise local summaries', 'active', 0.91, 'User prefers concise local summaries.',
            'user_message', 2, '2026-06-01T12:30:00Z', '2026-06-01T12:30:00Z',
            'preference', 'preference', NULL, NULL, '{}', 0.8
        )
        """
    )
    conn.execute(
        """
        INSERT INTO tasks(id, title, description, due_at_utc, status, source_text, created_at, updated_at)
        VALUES
            ('task-1', 'Finish retrospective view', '', '2026-06-01T15:00:00Z', 'done', '', '2026-06-01T10:00:00Z', '2026-06-01T16:00:00Z'),
            ('task-2', 'Review generated report', '', '2026-06-01T15:00:00Z', 'pending', '', '2026-06-01T10:00:00Z', '2026-06-01T11:00:00Z')
        """
    )
    action_service = AgentActionService(AgentActionStore(conn), writer=SafeMarkdownWriter(tmp_path))
    action_service.record(
        AgentActionCreate(
            action_type="wiki.answer_summary.write",
            title="Wiki summary",
            summary="summary",
            target_paths=("Wiki/Companion/Summaries/Task-03.md",),
            reversible=True,
        )
    )
    conn.execute("UPDATE agent_actions SET created_at = ?, updated_at = ?, completed_at = ?", (now, now, now))
    conn.commit()

    service = RetrospectiveService(
        conn,
        vault_id="vault-1",
        now_provider=lambda: datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    windows = service.build_windows()
    seven = next(window for window in windows if window.days == 7)

    assert seven.has_data is True
    assert seven.summary["diary_objects"] == 2
    assert seven.summary["long_term_memories"] == 1
    assert seven.tasks.total == 2
    assert seven.tasks.completed == 1
    assert seven.tasks.pending == 1
    assert seven.tasks.overdue == 1
    topic_names = {topic.name for topic in seven.topics}
    assert {"product review", "retrospective"}.issubset(topic_names)
    retrospective = next(topic for topic in seven.topics if topic.name == "retrospective")
    assert retrospective.sources[0].path == "Memories/Daily/2026-06-01.md"
    assert seven.repeated_preferences[0].name in {"focus", "retrospective", "status updates"}
    assert seven.wiki_updates[0].path == "Wiki/Companion/Summaries/Task-03.md"


def test_retrospective_service_counts_diary_objects_with_offset_timezone_inside_utc_window(tmp_path):
    conn = migrated_connection()
    now = datetime(2026, 6, 2, tzinfo=timezone.utc)
    local_occurred_at = (now - timedelta(days=1)).astimezone(timezone(timedelta(hours=8))).isoformat()
    outside_occurred_at = (now - timedelta(days=8)).astimezone(timezone(timedelta(hours=8))).isoformat()
    conn.execute("INSERT INTO vaults(id, root_path, name) VALUES ('vault-1', ?, 'Vault')", (str(tmp_path),))
    conn.execute(
        """
        INSERT INTO diary_memory_objects (
            id, vault_id, type, summary, topic, emotion, people_json,
            keywords_json, importance, confidence, occurred_at, timezone,
            status, object_hash, extraction_model, created_at, updated_at
        )
        VALUES
            ('diary-offset-1', 'vault-1', 'event', 'Reviewed offset timezone retrospective behavior.',
             'retrospective', 'focused', '[]', '["timezone"]', 0.9, 0.95,
             ?, 'Asia/Shanghai', 'active', 'hash-offset-1', 'fake',
             '2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z'),
            ('diary-offset-archived', 'vault-1', 'event', 'Archived object should stay excluded.',
             'retrospective', 'focused', '[]', '["timezone"]', 0.9, 0.95,
             ?, 'Asia/Shanghai', 'archived', 'hash-offset-archived', 'fake',
             '2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z'),
            ('diary-offset-outside', 'vault-1', 'event', 'Old object should stay outside the 7 day window.',
             'retrospective', 'focused', '[]', '["timezone"]', 0.9, 0.95,
             ?, 'Asia/Shanghai', 'active', 'hash-offset-outside', 'fake',
             '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z')
        """,
        (local_occurred_at, local_occurred_at, outside_occurred_at),
    )
    conn.commit()
    service = RetrospectiveService(
        conn,
        vault_id="vault-1",
        now_provider=lambda: now,
    )

    seven = service.build_window(7)

    assert seven.summary["diary_objects"] == 1
    assert seven.diary_summaries[0].id == "diary-offset-1"


def test_retrospective_report_write_binds_authoritative_markdown_to_action(tmp_path):
    conn = migrated_connection()
    vault = tmp_path / "Vault"
    conn.execute("INSERT INTO vaults(id, root_path, name) VALUES ('vault-1', ?, 'Vault')", (str(vault),))
    conn.execute(
        """
        INSERT INTO diary_memory_objects (
            id, vault_id, type, summary, topic, emotion, people_json,
            keywords_json, importance, confidence, occurred_at, timezone,
            status, object_hash, extraction_model, created_at, updated_at
        )
        VALUES (
            'diary-report-1', 'vault-1', 'event', 'Generated a retrospective report.', 'reporting', 'focused', '[]',
            '["reporting"]', 0.9, 0.95, '2026-06-01T12:00:00Z', 'UTC',
            'active', 'hash-report-1', 'fake', '2026-06-01T12:00:00Z', '2026-06-01T12:00:00Z'
        )
        """
    )
    conn.commit()
    writer = SafeMarkdownWriter(vault)
    service = RetrospectiveService(
        conn,
        vault_id="vault-1",
        writer=writer,
        index_refresh=lambda path: f"indexed:{path}",
        now_provider=lambda: datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    draft = service.prepare_report(days=7)
    response = service.write_report_draft(
        draft,
        action_id="action-retrospective-test",
        action_type="wiki.retrospective_report.write",
    )

    report_path = vault.joinpath(*response.relative_path.split("/"))
    assert response.relative_path.startswith("Wiki/Companion/Reports/")
    assert response.index_job_id == f"indexed:{response.relative_path}"
    assert response.action_type == "wiki.retrospective_report.write"
    assert response.action_id == "action-retrospective-test"
    assert response.title == "7-day 长期回顾"
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "reporting" in report_text
    assert "## 主要主题" in report_text
    assert "## 重要对话和日记摘要" in report_text
    assert "本报告只使用本地 SQLite 与 Vault 中已有的可追踪记录" in report_text
    assert "action_id=action-retrospective-test" in report_text
    effects = service.read_report_effects(
        action_id=response.action_id,
        action_type=response.action_type,
        report_kind=response.report_kind,
        expected_relative_path=response.relative_path,
        expected_content_hash=response.content_hash,
    )
    assert len(effects) == 1
    assert effects[0]["target_path"] == response.relative_path
    assert effects[0]["content_hash"] == response.content_hash


def test_retrospective_service_returns_empty_windows_without_history(tmp_path):
    conn = migrated_connection()
    conn.execute("INSERT INTO vaults(id, root_path, name) VALUES ('vault-1', ?, 'Vault')", (str(tmp_path),))
    service = RetrospectiveService(
        conn,
        vault_id="vault-1",
        now_provider=lambda: datetime(2026, 6, 2, tzinfo=timezone.utc),
    )

    windows = service.build_windows()

    assert [window.days for window in windows] == [1, 7, 30, 90]
    assert all(not window.has_data for window in windows)
    assert all(window.summary["diary_objects"] == 0 for window in windows)
