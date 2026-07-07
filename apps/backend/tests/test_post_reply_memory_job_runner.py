from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.models.config import AutomationSettingsResponse
from app.services.post_reply_memory_job_runner import (
    PostReplyMemoryJobInput,
    PostReplyMemoryJobRunner,
)


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory() as test_client:
        yield test_client


def _state(*, user_message: str = "Remember the Project Atlas checkpoint.") -> AgentState:
    return AgentState(
        conversation_id="conversation-runner",
        message_id="user-message-runner",
        agent_run_id="agent-run-runner",
        user_message=user_message,
    )


def _automation(
    *,
    daily: bool = True,
    structured: bool = True,
    slow: bool = True,
    wiki: bool = True,
) -> AutomationSettingsResponse:
    return AutomationSettingsResponse(
        auto_chat_diary=daily,
        auto_structured_memory=structured,
        auto_long_term_memory=slow,
        auto_wiki_organize=wiki,
    )


def _payload(
    *,
    automation: AutomationSettingsResponse,
    user_message: str = "Remember the Project Atlas checkpoint.",
    assistant_answer: str = "The checkpoint is recorded.",
) -> PostReplyMemoryJobInput:
    return PostReplyMemoryJobInput(
        context=object(),
        state=_state(user_message=user_message),
        assistant_message_id="assistant-message-runner",
        assistant_answer=assistant_answer,
        automation=automation,
    )


def _action(action_id: str, action_type: str, *, status: str = "completed") -> AgentActionEvent:
    return AgentActionEvent(
        agent_run_id="agent-run-runner",
        action_id=action_id,
        action_type=action_type,
        risk_tier="low",
        decision="auto",
        status=status,
        title="Safe test action",
        summary="Safe fixed summary.",
        target_paths=[],
        reversible=False,
    )


def _stage_map(result) -> dict[str, object]:
    return {stage.key: stage for stage in result.stages}


def _daily_result() -> SimpleNamespace:
    return SimpleNamespace(
        entry=SimpleNamespace(
            created_at="2026-07-07T01:02:03+00:00",
            markdown_path="Memories/Daily/2026/07/week/2026-07-07.md",
            memory_date="2026-07-07",
        )
    )


def _assert_safe_result(result) -> None:
    result_json = json.dumps(asdict(result), ensure_ascii=False)
    for forbidden in (
        "RAW_USER_MESSAGE",
        "RAW_ASSISTANT_ANSWER",
        "Authorization",
        "Bearer",
        "raw-token",
        "user-token",
        "source_text",
        "source_excerpt",
        "raw_evidence",
        "evidence_id",
        "C:\\Users",
        "Traceback",
        "token=secret",
    ):
        assert forbidden not in result_json


@pytest.mark.asyncio
async def test_runner_executes_stages_in_order_and_records_safe_action_ids() -> None:
    order: list[str] = []
    daily_result = _daily_result()

    def daily_stage(**_kwargs):
        order.append("daily_diary")
        return daily_result, [_action("daily-action", "chat.daily_archive")]

    async def structured_stage(**kwargs):
        order.append("structured_diary")
        assert kwargs["daily_result"] is daily_result
        return ("diary-object-1",), [_action("structured-action", "diary.structured_memory")]

    def slow_stage(**kwargs):
        order.append("slow_consolidation")
        assert kwargs["diary_object_ids"] == ("diary-object-1",)
        return [_action("slow-action", "memory.consolidation.candidate")]

    def wiki_stage(**kwargs):
        order.append("wiki_summary")
        assert kwargs["daily_result"] is daily_result
        return [_action("wiki-action", "wiki.answer_summary.write")]

    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=daily_stage,
        structured_diary_stage=structured_stage,
        slow_consolidation_stage=slow_stage,
        wiki_summary_stage=wiki_stage,
    )

    run = await runner.run_with_actions(_payload(automation=_automation()))

    assert order == ["daily_diary", "structured_diary", "slow_consolidation", "wiki_summary"]
    assert [stage.key for stage in run.result.stages] == order
    assert [stage.status for stage in run.result.stages] == ["succeeded"] * 4
    assert [stage.action_ids for stage in run.result.stages] == [
        ("daily-action",),
        ("structured-action",),
        ("slow-action",),
        ("wiki-action",),
    ]
    assert [event.action_id for event in run.action_events] == [
        "daily-action",
        "structured-action",
        "slow-action",
        "wiki-action",
    ]
    result_json = json.dumps(asdict(run.result), ensure_ascii=False)
    assert "Safe fixed summary" not in result_json
    assert "Memories/Daily" not in result_json


@pytest.mark.asyncio
async def test_real_daily_stage_failure_is_reported_and_structured_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_pipeline.diary as diary_module

    order: list[str] = []

    def failing_daily_service(_context):
        raise RuntimeError("Authorization: Bearer raw-token from C:\\Users\\Ada\\Vault\\secret.md")

    async def structured_stage(**kwargs):
        order.append("structured_diary")
        assert kwargs["daily_result"] is None
        return ("diary-object-1",), [_action("structured-action", "diary.structured_memory")]

    monkeypatch.setattr(diary_module, "chat_auto_memory_service", failing_daily_service)
    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=diary_module.archive_daily_diary,
        structured_diary_stage=structured_stage,
        slow_consolidation_stage=lambda **_kwargs: pytest.fail("slow stage should be disabled"),
        wiki_summary_stage=lambda **_kwargs: pytest.fail("wiki stage should be disabled"),
    )

    run = await runner.run_with_actions(_payload(automation=_automation(slow=False, wiki=False)))
    stages = _stage_map(run.result)

    assert order == ["structured_diary"]
    assert stages["daily_diary"].status == "failed"
    assert stages["daily_diary"].error_code == "daily_diary_failed"
    assert stages["structured_diary"].status == "succeeded"
    _assert_safe_result(run.result)


@pytest.mark.asyncio
async def test_real_structured_stage_failure_is_reported_and_slow_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_pipeline.diary_memory as diary_memory_module

    order: list[str] = []
    daily_result = _daily_result()

    def daily_stage(**_kwargs):
        return daily_result, [_action("daily-action", "chat.daily_archive")]

    def failing_diary_service(_context):
        raise RuntimeError("source_text raw_evidence evidence_id=e-1")

    def slow_stage(**kwargs):
        order.append("slow_consolidation")
        assert kwargs["diary_object_ids"] == ()
        return [_action("slow-action", "memory.consolidation.candidate")]

    monkeypatch.setattr(diary_memory_module, "diary_memory_service", failing_diary_service)
    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=daily_stage,
        structured_diary_stage=diary_memory_module.archive_structured_diary_memory,
        slow_consolidation_stage=slow_stage,
        wiki_summary_stage=lambda **_kwargs: pytest.fail("wiki stage should be disabled"),
    )

    run = await runner.run_with_actions(_payload(automation=_automation(wiki=False)))
    stages = _stage_map(run.result)

    assert order == ["slow_consolidation"]
    assert stages["structured_diary"].status == "failed"
    assert stages["structured_diary"].error_code == "structured_diary_failed"
    assert stages["slow_consolidation"].status == "succeeded"
    _assert_safe_result(run.result)


@pytest.mark.asyncio
async def test_real_slow_consolidation_failure_is_reported_and_wiki_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_pipeline.consolidation as consolidation_module

    order: list[str] = []
    daily_result = _daily_result()

    def daily_stage(**_kwargs):
        return daily_result, [_action("daily-action", "chat.daily_archive")]

    def failing_consolidation_service(_context):
        raise RuntimeError("source_excerpt token=secret Traceback (most recent call last)")

    def wiki_stage(**kwargs):
        order.append("wiki_summary")
        assert kwargs["daily_result"] is daily_result
        return [_action("wiki-action", "wiki.answer_summary.write")]

    monkeypatch.setattr(consolidation_module, "memory_consolidation_service", failing_consolidation_service)
    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=daily_stage,
        structured_diary_stage=lambda **_kwargs: pytest.fail("structured stage should be disabled"),
        slow_consolidation_stage=consolidation_module.consolidate_slow_memory,
        wiki_summary_stage=wiki_stage,
    )

    run = await runner.run_with_actions(_payload(automation=_automation(structured=False)))
    stages = _stage_map(run.result)

    assert order == ["wiki_summary"]
    assert stages["slow_consolidation"].status == "failed"
    assert stages["slow_consolidation"].error_code == "slow_consolidation_failed"
    assert stages["wiki_summary"].status == "succeeded"
    _assert_safe_result(run.result)


@pytest.mark.asyncio
async def test_real_wiki_stage_failure_is_reported_and_job_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_pipeline.wiki_summary as wiki_summary_module

    daily_result = _daily_result()

    def daily_stage(**_kwargs):
        return daily_result, [_action("daily-action", "chat.daily_archive")]

    def failing_wiki_service(_context):
        raise RuntimeError("C:\\Users\\Ada\\Vault\\secret.md raw_evidence stack trace")

    monkeypatch.setattr(wiki_summary_module, "wiki_service", failing_wiki_service)
    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=daily_stage,
        structured_diary_stage=lambda **_kwargs: ((), []),
        slow_consolidation_stage=lambda **_kwargs: [],
        wiki_summary_stage=wiki_summary_module.archive_wiki_answer_summary,
    )

    run = await runner.run_with_actions(_payload(automation=_automation()))
    stages = _stage_map(run.result)

    assert stages["wiki_summary"].status == "failed"
    assert stages["wiki_summary"].error_code == "wiki_summary_failed"
    assert run.result.completed_at
    _assert_safe_result(run.result)


@pytest.mark.asyncio
async def test_daily_failure_does_not_block_structured_stage() -> None:
    order: list[str] = []

    def daily_stage(**_kwargs):
        order.append("daily_diary")
        raise RuntimeError("Authorization: Bearer raw-token from C:\\Users\\Ada\\Vault\\secret.md")

    async def structured_stage(**kwargs):
        order.append("structured_diary")
        assert kwargs["daily_result"] is None
        return ("diary-object-1",), [_action("structured-action", "diary.structured_memory")]

    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=daily_stage,
        structured_diary_stage=structured_stage,
        slow_consolidation_stage=lambda **_kwargs: pytest.fail("slow stage should be disabled"),
        wiki_summary_stage=lambda **_kwargs: pytest.fail("wiki stage should be disabled"),
    )

    run = await runner.run_with_actions(_payload(automation=_automation(slow=False, wiki=False)))
    stages = _stage_map(run.result)

    assert order == ["daily_diary", "structured_diary"]
    assert stages["daily_diary"].status == "failed"
    assert stages["daily_diary"].error_code == "daily_diary_failed"
    assert stages["structured_diary"].status == "succeeded"
    assert stages["slow_consolidation"].status == "skipped"
    assert stages["wiki_summary"].status == "skipped"
    assert "Authorization" not in stages["daily_diary"].safe_summary
    assert "raw-token" not in stages["daily_diary"].safe_summary
    assert "C:\\Users" not in stages["daily_diary"].safe_summary


@pytest.mark.asyncio
async def test_structured_failure_does_not_block_slow_consolidation() -> None:
    order: list[str] = []
    daily_result = SimpleNamespace(entry=SimpleNamespace(markdown_path=None))

    def daily_stage(**_kwargs):
        order.append("daily_diary")
        return daily_result, [_action("daily-action", "chat.daily_archive")]

    async def structured_stage(**_kwargs):
        order.append("structured_diary")
        raise RuntimeError("raw_evidence source_text Traceback (most recent call last)")

    def slow_stage(**kwargs):
        order.append("slow_consolidation")
        assert kwargs["diary_object_ids"] == ()
        return [_action("slow-action", "memory.consolidation.candidate")]

    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=daily_stage,
        structured_diary_stage=structured_stage,
        slow_consolidation_stage=slow_stage,
        wiki_summary_stage=lambda **_kwargs: pytest.fail("wiki stage should be disabled"),
    )

    run = await runner.run_with_actions(_payload(automation=_automation(wiki=False)))
    stages = _stage_map(run.result)

    assert order == ["daily_diary", "structured_diary", "slow_consolidation"]
    assert stages["structured_diary"].status == "failed"
    assert stages["structured_diary"].error_code == "structured_diary_failed"
    assert stages["slow_consolidation"].status == "succeeded"
    stage_json = json.dumps(asdict(stages["structured_diary"]), ensure_ascii=False)
    assert "raw_evidence" not in stage_json
    assert "source_text" not in stage_json
    assert "Traceback" not in stage_json


@pytest.mark.asyncio
async def test_slow_consolidation_failure_does_not_block_wiki_summary() -> None:
    order: list[str] = []
    daily_result = SimpleNamespace(entry=SimpleNamespace(markdown_path=None))

    def daily_stage(**_kwargs):
        order.append("daily_diary")
        return daily_result, [_action("daily-action", "chat.daily_archive")]

    def slow_stage(**_kwargs):
        order.append("slow_consolidation")
        raise RuntimeError("token=secret source_excerpt stack trace")

    def wiki_stage(**kwargs):
        order.append("wiki_summary")
        assert kwargs["daily_result"] is daily_result
        return [_action("wiki-action", "wiki.answer_summary.write")]

    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=daily_stage,
        structured_diary_stage=lambda **_kwargs: pytest.fail("structured stage should be disabled"),
        slow_consolidation_stage=slow_stage,
        wiki_summary_stage=wiki_stage,
    )

    run = await runner.run_with_actions(_payload(automation=_automation(structured=False)))
    stages = _stage_map(run.result)

    assert order == ["daily_diary", "slow_consolidation", "wiki_summary"]
    assert stages["structured_diary"].status == "skipped"
    assert stages["slow_consolidation"].status == "failed"
    assert stages["slow_consolidation"].error_code == "slow_consolidation_failed"
    assert stages["wiki_summary"].status == "succeeded"


@pytest.mark.asyncio
async def test_disabled_stages_return_skipped_without_calling_stage_functions() -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("disabled stage should not be called")

    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=fail_if_called,
        structured_diary_stage=fail_if_called,
        slow_consolidation_stage=fail_if_called,
        wiki_summary_stage=fail_if_called,
    )

    run = await runner.run_with_actions(
        _payload(automation=_automation(daily=False, structured=False, slow=False, wiki=False))
    )

    assert [(stage.key, stage.status) for stage in run.result.stages] == [
        ("daily_diary", "skipped"),
        ("structured_diary", "skipped"),
        ("slow_consolidation", "skipped"),
        ("wiki_summary", "skipped"),
    ]
    assert run.action_events == ()


@pytest.mark.asyncio
async def test_daily_disabled_structured_enabled_runs_with_empty_daily_result() -> None:
    order: list[str] = []

    async def structured_stage(**kwargs):
        order.append("structured_diary")
        assert kwargs["daily_result"] is None
        return ("diary-object-1",), [_action("structured-action", "diary.structured_memory")]

    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=lambda **_kwargs: pytest.fail("daily stage should be disabled"),
        structured_diary_stage=structured_stage,
        slow_consolidation_stage=lambda **_kwargs: pytest.fail("slow stage should be disabled"),
        wiki_summary_stage=lambda **_kwargs: pytest.fail("wiki stage should be disabled"),
    )

    run = await runner.run_with_actions(
        _payload(automation=_automation(daily=False, structured=True, slow=False, wiki=False))
    )
    stages = _stage_map(run.result)

    assert order == ["structured_diary"]
    assert stages["daily_diary"].status == "skipped"
    assert stages["structured_diary"].status == "succeeded"


@pytest.mark.asyncio
async def test_structured_disabled_does_not_write_sqlite_diary_object(client: TestClient) -> None:
    from app.api.wiring import AppContext

    runner = PostReplyMemoryJobRunner()

    run = await runner.run_with_actions(
        PostReplyMemoryJobInput(
            context=AppContext(app=client.app),
            state=_state(),
            assistant_message_id="assistant-message-runner",
            assistant_answer="The checkpoint is recorded.",
            automation=_automation(daily=False, structured=False, slow=False, wiki=False),
        )
    )

    with sqlite3.connect(client.app.state.database.path) as conn:
        diary_count = conn.execute("SELECT COUNT(*) FROM diary_memory_objects").fetchone()[0]
    stages = _stage_map(run.result)
    assert stages["structured_diary"].status == "skipped"
    assert diary_count == 0


@pytest.mark.asyncio
async def test_automation_settings_failure_returns_safe_failed_result() -> None:
    def failing_automation(_context):
        raise RuntimeError("Authorization: Bearer raw-token source_text C:\\Users\\Ada\\Vault\\secret.md")

    runner = PostReplyMemoryJobRunner(
        automation_provider=failing_automation,
        daily_diary_stage=lambda **_kwargs: pytest.fail("daily stage should not be called"),
        structured_diary_stage=lambda **_kwargs: pytest.fail("structured stage should not be called"),
        slow_consolidation_stage=lambda **_kwargs: pytest.fail("slow stage should not be called"),
        wiki_summary_stage=lambda **_kwargs: pytest.fail("wiki stage should not be called"),
    )

    run = await runner.run_with_actions(
        PostReplyMemoryJobInput(
            context=object(),
            state=_state(),
            assistant_message_id="assistant-message-runner",
            assistant_answer="The checkpoint is recorded.",
        )
    )

    assert run.action_events == ()
    assert [(stage.key, stage.status, stage.error_code) for stage in run.result.stages] == [
        ("daily_diary", "failed", "automation_settings_failed"),
        ("structured_diary", "failed", "automation_settings_failed"),
        ("slow_consolidation", "failed", "automation_settings_failed"),
        ("wiki_summary", "failed", "automation_settings_failed"),
    ]
    _assert_safe_result(run.result)


@pytest.mark.asyncio
async def test_archive_chat_memory_settings_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_pipeline as chat_pipeline

    def failing_automation(_context):
        raise RuntimeError("token=secret source_excerpt Traceback (most recent call last)")

    monkeypatch.setattr(chat_pipeline, "automation_settings", failing_automation)

    actions = await chat_pipeline.archive_chat_memory(
        context=object(),
        state=_state(),
        assistant_message_id="assistant-message-runner",
        assistant_answer="The checkpoint is recorded.",
    )

    assert actions == []


@pytest.mark.asyncio
async def test_result_safe_fields_do_not_include_raw_prompt_or_exception_content() -> None:
    raw_user = "RAW_USER_MESSAGE Authorization Bearer user-token"
    raw_answer = "RAW_ASSISTANT_ANSWER source_text raw_evidence C:\\Users\\Ada\\Vault\\secret.md"

    def failing_daily(**_kwargs):
        raise RuntimeError("Traceback (most recent call last): token=secret raw_evidence evidence_id=e-1")

    runner = PostReplyMemoryJobRunner(
        daily_diary_stage=failing_daily,
        structured_diary_stage=lambda **_kwargs: ((), []),
        slow_consolidation_stage=lambda **_kwargs: [],
        wiki_summary_stage=lambda **_kwargs: [],
    )

    run = await runner.run_with_actions(
        _payload(
            automation=_automation(),
            user_message=raw_user,
            assistant_answer=raw_answer,
        )
    )

    result_json = json.dumps(asdict(run.result), ensure_ascii=False)
    for forbidden in (
        raw_user,
        raw_answer,
        "Authorization",
        "Bearer",
        "user-token",
        "RAW_ASSISTANT_ANSWER",
        "source_text",
        "raw_evidence",
        "C:\\Users",
        "Traceback",
        "token=secret",
        "evidence_id",
    ):
        assert forbidden not in result_json
    assert "daily_diary_failed" in result_json


@pytest.mark.asyncio
async def test_direct_stage_calls_keep_default_swallow_exception_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_pipeline.consolidation as consolidation_module
    import app.services.chat_pipeline.diary as diary_module
    import app.services.chat_pipeline.diary_memory as diary_memory_module
    import app.services.chat_pipeline.wiki_summary as wiki_summary_module

    automation = _automation()

    monkeypatch.setattr(
        diary_module,
        "chat_auto_memory_service",
        lambda _context: (_ for _ in ()).throw(RuntimeError("daily should be swallowed")),
    )
    daily_result, daily_actions = diary_module.archive_daily_diary(
        context=object(),
        state=_state(),
        assistant_message_id="assistant-message-runner",
        assistant_answer="The checkpoint is recorded.",
        automation=automation,
        policy=object(),
    )
    assert daily_result is None
    assert daily_actions == []

    monkeypatch.setattr(
        diary_memory_module,
        "diary_memory_service",
        lambda _context: (_ for _ in ()).throw(RuntimeError("structured should be swallowed")),
    )
    structured_ids, structured_actions = await diary_memory_module.archive_structured_diary_memory(
        context=object(),
        state=_state(),
        assistant_message_id="assistant-message-runner",
        assistant_answer="The checkpoint is recorded.",
        daily_result=None,
        automation=automation,
        policy=object(),
    )
    assert structured_ids == ()
    assert structured_actions == []

    monkeypatch.setattr(
        consolidation_module,
        "memory_consolidation_service",
        lambda _context: (_ for _ in ()).throw(RuntimeError("slow should be swallowed")),
    )
    assert (
        consolidation_module.consolidate_slow_memory(
            context=object(),
            state=_state(),
            assistant_message_id="assistant-message-runner",
            assistant_answer="The checkpoint is recorded.",
            daily_result=None,
            diary_object_ids=(),
            automation=automation,
            policy=object(),
        )
        == []
    )

    monkeypatch.setattr(
        wiki_summary_module,
        "wiki_service",
        lambda _context: (_ for _ in ()).throw(RuntimeError("wiki should be swallowed")),
    )
    assert (
        wiki_summary_module.archive_wiki_answer_summary(
            context=object(),
            state=_state(),
            assistant_message_id="assistant-message-runner",
            assistant_answer="The checkpoint is recorded.",
            daily_result=_daily_result(),
            diary_object_ids=(),
            automation=automation,
            policy=object(),
        )
        == []
    )


@pytest.mark.asyncio
async def test_archive_chat_memory_wrapper_returns_legacy_action_list(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_pipeline as chat_pipeline

    daily_result = SimpleNamespace(entry=SimpleNamespace(markdown_path=None))

    monkeypatch.setattr(chat_pipeline, "automation_settings", lambda _context: _automation())
    monkeypatch.setattr(
        chat_pipeline,
        "archive_daily_diary",
        lambda **_kwargs: (daily_result, [_action("daily-action", "chat.daily_archive")]),
    )

    async def structured_stage(**_kwargs):
        return ("diary-object-1",), [_action("structured-action", "diary.structured_memory")]

    monkeypatch.setattr(chat_pipeline, "archive_structured_diary_memory", structured_stage)
    monkeypatch.setattr(
        chat_pipeline,
        "consolidate_slow_memory",
        lambda **_kwargs: [_action("slow-action", "memory.consolidation.candidate")],
    )
    monkeypatch.setattr(
        chat_pipeline,
        "archive_wiki_answer_summary",
        lambda **_kwargs: [_action("wiki-action", "wiki.answer_summary.write")],
    )

    actions = await chat_pipeline.archive_chat_memory(
        context=object(),
        state=_state(),
        assistant_message_id="assistant-message-runner",
        assistant_answer="The checkpoint is recorded.",
    )

    assert [action.action_id for action in actions] == [
        "daily-action",
        "structured-action",
        "slow-action",
        "wiki-action",
    ]
