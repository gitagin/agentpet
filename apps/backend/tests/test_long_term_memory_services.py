from __future__ import annotations

import logging
from datetime import datetime, timezone

from apps.backend.tests._schema import migrate_db
from app.services.long_term_memory import LongTermMemoryService, extract_long_term_memory_candidate
from app.services.memory import SafeMarkdownWriter
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.memory_graph import MemoryGraphStore


def build_service(tmp_path, index_jobs=None):
    jobs = index_jobs if index_jobs is not None else []
    return LongTermMemoryService(
        SafeMarkdownWriter(tmp_path),
        now_provider=lambda: datetime(2026, 5, 4, 10, 11, 12, tzinfo=timezone.utc),
        index_refresh=lambda path: jobs.append(path) or f"index:{path}",
    )


def test_explicit_preference_writes_long_term_preferences(tmp_path):
    jobs: list[str] = []
    service = build_service(tmp_path, jobs)

    result = service.remember_from_user_message(
        "我喜欢的水果是苹果",
        conversation_id="conversation-1",
        user_message_id="message-1",
        agent_run_id="run-1",
    )

    target = tmp_path / "Memories" / "LongTerm" / "Preferences.md"
    assert result.written is True
    assert result.target_path == "Memories/LongTerm/Preferences.md"
    assert jobs == ["Memories/LongTerm/Preferences.md"]
    content = target.read_text(encoding="utf-8")
    assert "# 长期偏好" in content
    assert "## 2026-05-04 18:11:12" in content
    assert "- 类型：preference" in content
    assert "- 主题：水果" in content
    assert "- 内容：用户的水果是苹果" in content
    assert "- 来源原文：我喜欢的水果是苹果" in content
    assert "- memory_key：`" in content
    assert "- agent_run_id：`run-1`" in content


def test_explicit_profile_fact_writes_profile(tmp_path):
    service = build_service(tmp_path)

    result = service.remember_from_user_message(
        "我的昵称是小明",
        conversation_id="conversation-1",
        user_message_id="message-1",
        agent_run_id="run-1",
    )

    target = tmp_path / "Memories" / "LongTerm" / "Profile.md"
    assert result.written is True
    content = target.read_text(encoding="utf-8")
    assert "- 类型：profile" in content
    assert "- 主题：昵称" in content
    assert "- 内容：用户的昵称是小明" in content


def test_question_does_not_write_long_term_memory(tmp_path):
    service = build_service(tmp_path)

    result = service.remember_from_user_message(
        "我喜欢的水果是什么？",
        conversation_id="conversation-1",
        user_message_id="message-1",
        agent_run_id="run-1",
    )

    assert result.written is False
    assert result.reason == "no_explicit_memory"
    assert not (tmp_path / "Memories" / "LongTerm" / "Preferences.md").exists()


def test_repeated_same_fact_is_idempotent(tmp_path):
    service = build_service(tmp_path)

    first = service.remember_from_user_message(
        "我喜欢的水果是苹果",
        conversation_id="conversation-1",
        user_message_id="message-1",
        agent_run_id="run-1",
    )
    second = service.remember_from_user_message(
        "我喜欢的水果是苹果",
        conversation_id="conversation-2",
        user_message_id="message-2",
        agent_run_id="run-2",
    )

    content = (tmp_path / "Memories" / "LongTerm" / "Preferences.md").read_text(encoding="utf-8")
    assert first.written is True
    assert second.written is False
    assert second.reason == "already_recorded"
    assert content.count("- 内容：用户的水果是苹果") == 1


def test_sensitive_candidate_is_rejected(tmp_path):
    service = build_service(tmp_path)

    result = service.remember_from_user_message(
        "我的api key是sk-secret-agent-memory-1234567890",
        conversation_id="conversation-1",
        user_message_id="message-1",
        agent_run_id="run-1",
    )

    assert result.written is False
    assert result.reason != "no_explicit_memory"
    assert not (tmp_path / "Memories" / "LongTerm" / "Profile.md").exists()


def test_sensitive_life_domain_requires_review_instead_of_auto_write(tmp_path):
    service = build_service(tmp_path)

    result = service.remember_from_user_message(
        "我的健康情况是长期失眠",
        conversation_id="conversation-1",
        user_message_id="message-1",
        agent_run_id="run-1",
    )

    assert result.written is False
    assert result.reason == "sensitive_life_domain"
    assert not (tmp_path / "Memories" / "LongTerm" / "Profile.md").exists()


def test_one_off_emotion_is_not_explicit_long_term_candidate():
    candidate = extract_long_term_memory_candidate("I feel anxious today because the release is close.")

    assert candidate is None


def test_extracts_short_like_statement_as_preference():
    candidate = extract_long_term_memory_candidate("我喜欢苹果")

    assert candidate is not None
    assert candidate.target_path == "Memories/LongTerm/Preferences.md"
    assert candidate.subject == "偏好"
    assert candidate.value == "苹果"


def test_extracts_compound_demo_preference_clause() -> None:
    candidate = extract_long_term_memory_candidate(
        "明天下午三点提醒我给张老师回邮件，并记住我更喜欢下午开会。"
    )

    assert candidate is not None
    assert candidate.target_path == "Memories/LongTerm/Preferences.md"
    assert candidate.subject == "偏好"
    assert candidate.value == "下午开会"


def test_model_extraction_failure_logs_warning_and_skips_candidates(tmp_path, caplog):
    class FailingModel:
        def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            raise RuntimeError("model down")

    service = LongTermMemoryService(
        SafeMarkdownWriter(tmp_path),
        graph_store=MemoryGraphStore(migrate_db(tmp_path / "state.sqlite3")),
        extraction_model=FailingModel(),
        extraction_model_name="test-model",
    )
    try:
        caplog.set_level(logging.WARNING, logger="app.services.long_term_memory")

        result = service.remember_from_user_message(
            "This is a durable work note without explicit preference syntax.",
            conversation_id="conversation-1",
            user_message_id="message-1",
            agent_run_id="run-1",
        )

        assert result.written is False
        assert result.reason == "no_explicit_memory"
        assert "Long-term memory model extraction failed; skipping model candidates" in caplog.text
    finally:
        service.close()


def test_model_candidate_retry_reuses_source_identity_without_answer_activation(tmp_path):
    class Model:
        def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            return (
                '[{"category":"project","subject":"Atlas","predicate":"status",'
                '"object":"in progress","source_text":"Atlas is in progress.",'
                '"confidence":0.9,"entity_type":"project","memory_type":"project"}]'
            )

    database = migrate_db(tmp_path / "state.sqlite3")
    graph = MemoryEntityGraphStore(database)
    service = LongTermMemoryService(
        SafeMarkdownWriter(tmp_path),
        graph_store=graph,
        extraction_model=Model(),
        extraction_model_name="test-model",
    )
    try:
        first = service.remember_from_user_message(
            "Atlas is in progress for this project.",
            conversation_id="conversation-model",
            user_message_id="message-model",
            agent_run_id="run-model-1",
        )
        second = service.remember_from_user_message(
            "Atlas is in progress for this project.",
            conversation_id="conversation-model",
            user_message_id="message-model",
            agent_run_id="run-model-2",
        )

        assert first.graph_fact_id == second.graph_fact_id
        assert first.graph_status == "candidate"
        assert second.graph_status == "candidate"
        assert graph.conn.execute("SELECT COUNT(*) FROM memory_entities").fetchone()[0] == 1
        assert graph.conn.execute(
            "SELECT COUNT(*) FROM memory_graph_facts WHERE statement_kind = 'claim'"
        ).fetchone()[0] == 1
        assert graph.conn.execute("SELECT COUNT(*) FROM memory_entity_evidence").fetchone()[0] == 1
        fact = graph.get(first.graph_fact_id)
        assert fact.support_count == 1
        assert graph.answerable_facts(query="Atlas") == []
    finally:
        service.close()
