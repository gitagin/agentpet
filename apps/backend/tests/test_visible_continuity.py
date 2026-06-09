from __future__ import annotations

import sqlite3

from app.services.visible_continuity import VisibleContinuityOptions, VisibleContinuityService
from tests._schema import migrate_db_with_vault


def _snapshot(db_path, *, vault_id: str | None = None, now_iso: str = "2026-06-02T12:30:00Z"):
    service = VisibleContinuityService(
        db_path,
        vault_id=vault_id,
        options=VisibleContinuityOptions(now_iso=now_iso),
    )
    try:
        return service.snapshot()
    finally:
        service.close()


def test_empty_database_returns_friendly_snapshot_without_crash(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")

    snapshot = _snapshot(db_path, now_iso="2026-06-02T12:00:00Z")

    assert snapshot.today_card.source_count == 0
    assert snapshot.today_card.title
    assert snapshot.today_card.suggested_next_steps
    assert snapshot.recent_receipts == []
    assert snapshot.project_cards == []
    assert snapshot.playback_preview.source_count == 0


def test_chat_only_state_returns_visible_recent_activity(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO conversations(id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("conv-chat", "Planning the next small step", "active", "2026-06-02T09:00:00Z", "2026-06-02T09:15:00Z"),
        )
        conn.executemany(
            """
            INSERT INTO messages(id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "msg-chat-user",
                    "conv-chat",
                    "user",
                    "Let's make the visible continuity panel useful.",
                    "completed",
                    "2026-06-02T09:00:00Z",
                    "2026-06-02T09:00:00Z",
                ),
                (
                    "msg-chat-assistant",
                    "conv-chat",
                    "assistant",
                    "I will pull the current thread into today's card.",
                    "completed",
                    "2026-06-02T09:10:00Z",
                    "2026-06-02T09:10:00Z",
                ),
            ],
        )

    snapshot = _snapshot(db_path, now_iso="2026-06-02T12:00:00Z")

    assert snapshot.today_card.source_count >= 2
    assert snapshot.today_card.carry_over_items
    assert "未收尾：" in snapshot.today_card.summary
    assert "1 条活跃对话线索" in snapshot.today_card.summary
    assert snapshot.today_card.continuation_prompts == ["继续这条线索：Planning the next small step"]
    assert snapshot.recent_receipts == []


def test_sensitive_blocked_actions_do_not_leak_raw_sensitive_values(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO agent_actions (
                id, action_type, risk_tier, decision, status, title, summary,
                target_paths_json, before_snapshot_json, after_snapshot_json,
                metadata_json, reversible, created_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', ?, ?, ?, ?)
            """,
            (
                "action-sensitive-1",
                "memory.consolidation.safety_event",
                "high",
                "notify",
                "completed",
                "Skipped token=super-secret-value",
                "Blocked Authorization: Bearer abcdefghijklmnop1234567890 and sk-testsecret123456",
                '["Secrets/token=super-secret-value.md"]',
                0,
                "2026-06-02T12:00:00Z",
                "2026-06-02T12:00:00Z",
                "2026-06-02T12:00:00Z",
            ),
        )

    snapshot = _snapshot(db_path, now_iso="2026-06-02T12:05:00Z")

    receipt = snapshot.recent_receipts[0]
    assert receipt.summary == "Blocked [REDACTED] and [REDACTED]"
    assert receipt.title == "Skipped [REDACTED]"
    assert receipt.target_path is None
    serialized = snapshot.model_dump_json()
    assert "super-secret-value" not in serialized
    assert "abcdefghijklmnop" not in serialized
    assert "sk-testsecret" not in serialized


def test_project_inputs_and_retrospective_assets_build_project_card_and_playback_preview(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3", vault_id="vault-1")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO conversations(id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("conv-1", "Agent Pet planning", "active", "2026-06-02T10:00:00Z", "2026-06-02T10:10:00Z"),
        )
        conn.execute(
            """
            INSERT INTO messages(id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-1",
                "conv-1",
                "user",
                "We are working on project Agent Pet visible continuity.",
                "completed",
                "2026-06-02T10:00:00Z",
                "2026-06-02T10:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO agent_runs(
                id, conversation_id, user_message_id, assistant_message_id, status,
                intent, error_code, error_message, created_at, updated_at
            )
            VALUES (?, ?, ?, NULL, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                "run-1",
                "conv-1",
                "msg-1",
                "success",
                "chat",
                "2026-06-02T10:00:00Z",
                "2026-06-02T10:05:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO companion_retrieval_reports (
                id, agent_run_id, strategy, query_hash, candidate_count, selected_count,
                duplicate_drop_count, per_scope_drop_count, budget_drop_count, item_budget,
                per_scope_limit, char_budget, used_chars, source_counts_json,
                selected_scopes_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 8, 4, 1200, 240, ?, ?, ?)
            """,
            (
                "report-1",
                "run-1",
                "deterministic_v1",
                "hash-only",
                3,
                2,
                '{"diary": 1, "memory": 1}',
                '["diary", "memory"]',
                "2026-06-02T10:06:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO tasks(id, title, description, due_at_utc, status, source_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1",
                "Ship project Agent Pet snapshot contract",
                "Define the visible continuity data contract.",
                "2026-06-03T09:00:00Z",
                "pending",
                "project Agent Pet",
                "2026-06-02T11:00:00Z",
                "2026-06-02T11:10:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO diary_memory_objects (
                id, vault_id, type, summary, topic, emotion, people_json,
                keywords_json, importance, confidence, occurred_at, timezone,
                status, object_hash, extraction_model, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "diary-1",
                "vault-1",
                "event",
                "Defined the first visible continuity contract.",
                "project Agent Pet",
                "focused",
                '["visible continuity","project Agent Pet"]',
                0.9,
                0.9,
                "2026-06-02T11:30:00Z",
                "UTC",
                "active",
                "hash-diary-1",
                "fake",
                "2026-06-02T11:30:00Z",
                "2026-06-02T11:30:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO diary_memory_object_sources (
                object_id, source_type, source_id, conversation_id, user_message_id,
                assistant_message_id, agent_run_id, markdown_path, note_id, chunk_id
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL)
            """,
            (
                "diary-1",
                "chat",
                "msg-1",
                "conv-1",
                "msg-1",
                "run-1",
                "Memories/Daily/2026-06-02.md",
            ),
        )
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at, memory_type, entity_type, occurred_at,
                expires_at, metadata_json, importance
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)
            """,
            (
                "fact-1",
                "project-agent-pet",
                "project-agent-pet",
                "project_context",
                "project Agent Pet",
                "needs",
                "visible continuity snapshot",
                "active",
                0.86,
                "Project Agent Pet needs visible continuity snapshot.",
                "user_message",
                2,
                "2026-06-02T11:40:00Z",
                "2026-06-02T11:40:00Z",
                "project_context",
                "project",
                None,
                None,
                0.8,
            ),
        )
        conn.execute(
            """
            INSERT INTO agent_actions (
                id, action_type, risk_tier, decision, status, title, summary,
                target_paths_json, before_snapshot_json, after_snapshot_json,
                metadata_json, reversible, created_at, updated_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', ?, ?, ?, ?)
            """,
            (
                "action-1",
                "wiki.answer_summary.write",
                "low",
                "auto",
                "completed",
                "Saved visible continuity summary",
                "Saved a reusable project summary.",
                '["Wiki/Companion/Summaries/visible-continuity.md"]',
                1,
                "2026-06-02T12:00:00Z",
                "2026-06-02T12:00:00Z",
                "2026-06-02T12:00:00Z",
            ),
        )

    snapshot = _snapshot(db_path, vault_id="vault-1", now_iso="2026-06-02T12:30:00Z")

    assert snapshot.today_card.source_count >= 7
    assert "未收尾：" in snapshot.today_card.summary
    assert "1 个未完成任务" in snapshot.today_card.summary
    assert snapshot.today_card.continuation_prompts[0] == "帮我继续处理这个任务：Ship project Agent Pet snapshot contract"
    assert snapshot.recent_receipts[0].action_id == "action-1"
    assert snapshot.recent_receipts[0].status == "completed"
    assert snapshot.recent_receipts[0].reverted_by is None
    assert snapshot.recent_receipts[0].reverts_action_id is None
    assert snapshot.recent_receipts[0].target_path == "Wiki/Companion/Summaries/visible-continuity.md"
    assert snapshot.project_cards
    assert snapshot.project_cards[0].sources
    assert snapshot.playback_preview.source_count >= 4
    assert "visible continuity" in snapshot.playback_preview.themes
    assert "project Agent Pet" in " ".join(snapshot.playback_preview.themes + [snapshot.project_cards[0].title])


def test_repeated_project_discussion_produces_project_card(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO conversations(id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("conv-project", "Atlas planning", "active", "2026-06-02T09:00:00Z", "2026-06-02T09:20:00Z"),
        )
        conn.executemany(
            """
            INSERT INTO messages(id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "msg-project-1",
                    "conv-project",
                    "user",
                    "Project Atlas needs a smaller launch checklist.",
                    "completed",
                    "2026-06-02T09:00:00Z",
                    "2026-06-02T09:00:00Z",
                ),
                (
                    "msg-project-2",
                    "conv-project",
                    "assistant",
                    "For project Atlas, the next step is drafting the launch checklist.",
                    "completed",
                    "2026-06-02T09:15:00Z",
                    "2026-06-02T09:15:00Z",
                ),
            ],
        )

    snapshot = _snapshot(db_path, now_iso="2026-06-02T12:00:00Z")

    assert len(snapshot.project_cards) == 1
    card = snapshot.project_cards[0]
    assert card.title == "Atlas"
    assert card.current_state == "待确认主题"
    assert "最近 2 条消息提到" in card.recent_progress
    assert sorted(card.sources) == ["messages:msg-project-1", "messages:msg-project-2"]


def test_one_off_casual_project_mention_does_not_become_project_card(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO conversations(id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("conv-casual", "Casual chat", "active", "2026-06-02T09:00:00Z", "2026-06-02T09:05:00Z"),
        )
        conn.execute(
            """
            INSERT INTO messages(id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-casual-1",
                "conv-casual",
                "user",
                "That joke sounded like a project Moon Waffle incident.",
                "completed",
                "2026-06-02T09:00:00Z",
                "2026-06-02T09:00:00Z",
            ),
        )

    snapshot = _snapshot(db_path, now_iso="2026-06-02T12:00:00Z")

    assert snapshot.project_cards == []


def test_completed_project_candidate_is_historical_not_current(tmp_path) -> None:
    db_path = migrate_db_with_vault(tmp_path / "state.sqlite3")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memory_candidates (
                id, candidate_hash, memory_kind, memory_scope, summary,
                normalized_value, source_text, source_text_hash, source_track,
                risk_tier, confidence, importance, evidence_count, status,
                expires_at, last_confirmed_at, superseded_by, fact_id,
                metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, '{}', ?, ?)
            """,
            (
                "candidate-archived-project",
                "candidate-archived-project-hash",
                "project_context",
                "project",
                "Project Atlas was completed after the launch checklist shipped.",
                "project:atlas",
                "Project Atlas was completed after the launch checklist shipped.",
                "hash-only",
                "explicit_user",
                "low",
                0.9,
                0.8,
                3,
                "archived",
                "2026-06-01T17:00:00Z",
                "2026-06-01T17:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO memory_feedback_events (
                id, candidate_id, fact_id, feedback_type, feedback_text, requested_status,
                replacement_candidate_id, source_conversation_id, source_message_id,
                source_agent_run_id, agent_action_id, metadata_json, created_at
            )
            VALUES (?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, '{}', ?)
            """,
            (
                "feedback-completed-project",
                "candidate-archived-project",
                "mark_completed",
                "Project Atlas is done.",
                "archived",
                "2026-06-01T17:00:00Z",
            ),
        )

    snapshot = _snapshot(db_path, now_iso="2026-06-02T12:00:00Z")

    assert len(snapshot.project_cards) == 1
    card = snapshot.project_cards[0]
    assert card.title == "Atlas"
    assert card.current_state == "历史线索"
    assert card.next_step == "保留给回放即可，当前不需要动作。"
    assert card.sources == ["memory_candidates:candidate-archived-project"]
