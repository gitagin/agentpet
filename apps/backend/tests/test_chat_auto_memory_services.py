from __future__ import annotations

from datetime import datetime, timezone

from apps.backend.tests._schema import migrated_connection
from app.services.chat_auto_memory import ChatAutoMemoryService, ChatAutoMemoryStore
from app.services.chat_answer_wiki_summary import ChatAnswerWikiSummaryService
from app.services.memory import SafeMarkdownWriter


def build_service(tmp_path, now_values, index_jobs=None):
    values = list(now_values)
    jobs = index_jobs if index_jobs is not None else []

    def now_provider():
        return values.pop(0)

    return ChatAutoMemoryService(
        ChatAutoMemoryStore(migrated_connection()),
        SafeMarkdownWriter(tmp_path),
        now_provider=now_provider,
        index_refresh=lambda path: jobs.append(path) or f"index:{path}",
    )


def append_exchange(service, run_id, question="用户问题", answer="桌宠回答"):
    return service.append_chat_exchange(
        conversation_id=f"conversation-{run_id}",
        user_message_id=f"user-{run_id}",
        assistant_message_id=f"assistant-{run_id}",
        agent_run_id=run_id,
        user_question=question,
        assistant_answer=answer,
    )


def daily_file(root, day: str):
    return root / "Memories" / "Daily" / "2026" / "05" / "第1周_05-01至05-07" / day


def test_daily_chat_memory_creates_memories_daily_year_month_week_day_file(tmp_path):
    service = build_service(
        tmp_path,
        [datetime(2026, 5, 3, 13, 40, 12, tzinfo=timezone.utc)],
    )

    result = append_exchange(service, "run-1", "今天做什么？", "先完成核心闭环。")

    target = daily_file(tmp_path, "星期日") / "2026-05-03.md"
    assert result.written is True
    assert (
        result.entry.markdown_path
        == "Memories/Daily/2026/05/第1周_05-01至05-07/星期日/2026-05-03.md"
    )
    assert target.exists()
    assert not (tmp_path / "2026").exists()
    content = target.read_text(encoding="utf-8")
    assert "# 2026-05-03 聊天记忆" in content
    assert "## 21:40:12" in content
    assert "- 用户问题：今天做什么？" in content
    assert "- 桌宠回答：先完成核心闭环。" in content
    assert "- agent_run_id：`run-1`" in content


def test_daily_chat_memory_appends_same_day_without_overwrite(tmp_path):
    service = build_service(
        tmp_path,
        [
            datetime(2026, 5, 3, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 3, 2, 0, 0, tzinfo=timezone.utc),
        ],
    )

    append_exchange(service, "run-1", "第一问", "第一答")
    append_exchange(service, "run-2", "第二问", "第二答")

    target = daily_file(tmp_path, "星期日") / "2026-05-03.md"
    content = target.read_text(encoding="utf-8")
    assert content.count("# 2026-05-03 聊天记忆") == 1
    assert "第一问" in content
    assert "第一答" in content
    assert "第二问" in content
    assert "第二答" in content


def test_daily_chat_memory_uses_local_day_for_cross_day_writes(tmp_path):
    service = build_service(
        tmp_path,
        [
            datetime(2026, 5, 3, 15, 59, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 3, 16, 1, 0, tzinfo=timezone.utc),
        ],
    )

    append_exchange(service, "run-1", "前一天问题", "前一天回答")
    append_exchange(service, "run-2", "新一天问题", "新一天回答")

    first_day = daily_file(tmp_path, "星期日") / "2026-05-03.md"
    second_day = daily_file(tmp_path, "星期一") / "2026-05-04.md"
    assert "前一天问题" in first_day.read_text(encoding="utf-8")
    assert "新一天问题" in second_day.read_text(encoding="utf-8")


def test_daily_chat_memory_is_idempotent_by_agent_run_id(tmp_path):
    service = build_service(
        tmp_path,
        [datetime(2026, 5, 3, 13, 40, 12, tzinfo=timezone.utc)],
    )

    first = append_exchange(service, "run-1", "只写一次", "不会重复")
    second = append_exchange(service, "run-1", "只写一次", "不会重复")

    target = daily_file(tmp_path, "星期日") / "2026-05-03.md"
    content = target.read_text(encoding="utf-8")
    assert first.written is True
    assert second.written is False
    assert content.count("只写一次") == 1


def test_daily_chat_memory_uses_fixed_seven_day_month_weeks(tmp_path):
    service = build_service(
        tmp_path,
        [
            datetime(2026, 5, 7, 13, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 8, 13, 0, 0, tzinfo=timezone.utc),
        ],
    )

    first_week = append_exchange(service, "run-1", "第七天", "仍在第一周")
    second_week = append_exchange(service, "run-2", "第八天", "进入第二周")

    assert (
        first_week.entry.markdown_path
        == "Memories/Daily/2026/05/第1周_05-01至05-07/星期四/2026-05-07.md"
    )
    assert (
        second_week.entry.markdown_path
        == "Memories/Daily/2026/05/第2周_05-08至05-14/星期五/2026-05-08.md"
    )


def test_chat_answer_wiki_summary_skips_low_value_chat(tmp_path):
    service = ChatAnswerWikiSummaryService()

    plan = service.plan(
        user_question="你好",
        assistant_answer="你好，我在。",
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        agent_run_id="run-1",
        diary_markdown_path="Memories/Daily/2026/05/第1周_05-01至05-07/星期日/2026-05-03.md",
        memory_date="2026-05-03",
    )

    assert plan is None
    assert not (tmp_path / "Wiki").exists()


def test_chat_answer_wiki_summary_plans_single_source_page_with_evidence_links(tmp_path):
    service = ChatAnswerWikiSummaryService()

    plan = service.plan(
        user_question="优化桌宠回答后日记和 Wiki 自动整理流程",
        assistant_answer=(
            "- 桌宠应先按意图检索日记、长期记忆和 Wiki。\n"
            "- 回答完成后写入日记，再自我总结。\n"
            "- 有价值的总结要带证据、更新日志和自检清单写入 Wiki。"
        ),
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        agent_run_id="run-1",
        diary_markdown_path="Memories/Daily/2026/05/第1周_05-01至05-07/星期日/2026-05-03.md",
        memory_date="2026-05-03",
        diary_object_ids=("obj-1",),
    )
    assert plan is not None

    text = plan.content
    assert "## 来源摘要" in text
    assert "## 问题" in text
    assert "## 结论" in text
    assert "## 证据状态" in text
    assert "## 来源" in text
    assert "## 更新记录" in text
    assert "经典案例" not in text
    assert "\n## 自检清单\n" not in text
    assert "[[Memories/Daily/2026/05/第1周_05-01至05-07/星期日/2026-05-03.md]]" in text
    assert "agent_run_id：`run-1`" in text
    assert plan.target_path.startswith("Wiki/Companion/Summaries/")
    assert "[[Wiki/index.md]]" in plan.links
    assert "[[Wiki/AGENTS.md]]" in plan.links
    assert not (tmp_path / "Wiki").exists()


def test_chat_answer_wiki_summary_skips_sensitive_content(tmp_path):
    service = ChatAnswerWikiSummaryService()

    plan = service.plan(
        user_question="把接口凭据整理进 wiki",
        assistant_answer="api_key=sk-agent-memory-secret-1234567890 应该写入 Wiki。",
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        agent_run_id="run-1",
        diary_markdown_path="Memories/Daily/2026/05/第1周_05-01至05-07/星期日/2026-05-03.md",
        memory_date="2026-05-03",
    )

    assert plan is None
    assert not (tmp_path / "Wiki").exists()
