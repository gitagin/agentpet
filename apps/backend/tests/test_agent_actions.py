from __future__ import annotations

from pathlib import Path

from apps.backend.tests._schema import migrate_db
from app.models.api import AutomationSettingsRequest
from app.services.agent_actions import (
    AgentActionCreate,
    AgentActionService,
    AgentActionStore,
    AutomationPolicy,
    markdown_snapshot,
)
from app.services.memory import SafeMarkdownWriter


def test_automation_policy_matrix_covers_auto_notify_and_ask() -> None:
    policy = AutomationPolicy()

    auto = policy.decide("wiki.page.write", target_paths=["Wiki/Notes/Ada.md"], reversible=True)
    answer_summary = policy.decide(
        "wiki.answer_summary.write",
        target_paths=["Wiki/Companion/Summaries/2026-05-18-Ada.md"],
        confidence=0.8,
        reversible=True,
    )
    notify = policy.decide("agent.notice")
    medium = policy.decide("continuity.identity", confidence=0.9)
    low_confidence = policy.decide("diary.structured_memory", confidence=0.4, reversible=True)
    high = policy.decide("markdown.delete", target_paths=["Wiki/Old.md"], destructive=True)
    sensitive = policy.decide("memory.long_term.write", sensitive=True)
    unsafe_wiki_path = policy.decide("wiki.page.write", target_paths=["Notes/Ada.md"], reversible=True)

    assert (auto.risk_tier, auto.decision, auto.reversible) == ("low", "auto", True)
    assert (answer_summary.risk_tier, answer_summary.decision, answer_summary.reversible) == ("low", "auto", True)
    assert (notify.risk_tier, notify.decision, notify.reversible) == ("low", "notify", False)
    assert (medium.risk_tier, medium.decision) == ("medium", "ask")
    assert (low_confidence.risk_tier, low_confidence.decision) == ("medium", "ask")
    assert (high.risk_tier, high.decision, high.reversible) == ("high", "ask", False)
    assert (sensitive.risk_tier, sensitive.decision) == ("high", "ask")
    assert (unsafe_wiki_path.risk_tier, unsafe_wiki_path.decision) == ("high", "ask")


def test_agent_action_settings_default_to_opt_in_memory(tmp_path: Path) -> None:
    store = AgentActionStore(migrate_db(tmp_path / "state.sqlite3"))

    defaults = store.get_automation_settings()
    saved = store.set_automation_settings(
        AutomationSettingsRequest(
            auto_chat_diary=False,
            auto_structured_memory=True,
            auto_long_term_memory=False,
            auto_wiki_organize=False,
            use_negotiation=False,
            max_rounds=2,
        )
    )
    loaded = store.get_automation_settings()

    assert defaults.auto_chat_diary is False
    assert defaults.auto_structured_memory is False
    assert defaults.auto_long_term_memory is False
    assert defaults.auto_wiki_organize is False
    assert defaults.use_negotiation is False
    assert defaults.max_rounds == 5
    assert defaults.high_risk_confirmation_required is True
    assert saved.auto_chat_diary is False
    assert saved.auto_structured_memory is True
    assert saved.auto_long_term_memory is False
    assert saved.auto_wiki_organize is False
    assert saved.use_negotiation is False
    assert saved.max_rounds == 2
    assert saved.high_risk_confirmation_required is True
    assert loaded == saved


def test_agent_action_revert_restores_markdown_snapshot(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    writer = SafeMarkdownWriter(vault)
    target_path = "Wiki/Runtime.md"
    writer.write(target_path, "# Runtime\n\nOld content.\n")
    before = markdown_snapshot(writer, [target_path])
    writer.write(target_path, "# Runtime\n\nNew content.\n")
    after = markdown_snapshot(writer, [target_path])

    service = AgentActionService(
        AgentActionStore(migrate_db(tmp_path / "state.sqlite3")),
        writer=writer,
    )
    action = service.record(
        AgentActionCreate(
            action_type="wiki.page.write",
            title="Updated Runtime",
            summary="replace_section -> Wiki/Runtime.md",
            source_agent_run_id="run-1",
            source_message_id="message-1",
            risk_tier="low",
            decision="auto",
            status="completed",
            target_paths=(target_path,),
            before_snapshot=before,
            after_snapshot=after,
            metadata={"source": {"label": "Wiki review", "review_id": "review-1"}},
            reversible=True,
        )
    )

    assert action.source["label"] == "Wiki review"
    assert action.source["review_id"] == "review-1"
    assert action.source["source_agent_run_id"] == "run-1"
    assert action.source["source_message_id"] == "message-1"
    assert action.diff_summary == "更新 1 个文件"

    updated, reverted = service.revert(action.action_id)

    assert writer.resolve_markdown_path(target_path).read_text(encoding="utf-8") == "# Runtime\n\nOld content.\n"
    assert updated.status == "reverted"
    assert updated.reverted_by == reverted.action_id
    assert reverted.action_type == "agent_action.revert"
    assert reverted.metadata["reverted_action_id"] == action.action_id
