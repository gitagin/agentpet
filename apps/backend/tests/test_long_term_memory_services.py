from __future__ import annotations

import logging
from datetime import datetime, timezone

from apps.backend.tests._schema import migrate_db
from app.services.long_term_memory import LongTermMemoryService, extract_long_term_memory_candidate
from app.services.memory import SafeMarkdownWriter
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
    assert "# Long-Term Preferences" in content
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


def test_extracts_short_like_statement_as_preference():
    candidate = extract_long_term_memory_candidate("我喜欢苹果")

    assert candidate is not None
    assert candidate.target_path == "Memories/LongTerm/Preferences.md"
    assert candidate.subject == "偏好"
    assert candidate.value == "苹果"


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
