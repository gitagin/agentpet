from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.services.continuity import ContinuityProposalStateError, ContinuityService
from app.utils.time import utc_now_iso


def _seed_open_thread(service: ContinuityService, summary: str) -> str:
    # 直接落一条 pending 的 open_thread 提案,不依赖模型/规则抽取,
    # 保证测试只验证 confirm/reject 的状态机。
    proposal_id = f"proposal-{summary[:8]}"
    now = utc_now_iso()
    service.conn.execute(
        """
        INSERT INTO continuity_proposals (
            id, proposal_hash, kind, summary, evidence, confidence,
            source_conversation_id, source_message_id, agent_run_id,
            status, rejected_reason, error, created_at, updated_at
        ) VALUES (?, ?, 'open_thread', ?, 'seed', 0.9, NULL, NULL, NULL,
                  'pending', NULL, NULL, ?, ?)
        """,
        (proposal_id, f"hash-{summary[:8]}", summary, now, now),
    )
    service.conn.commit()
    return proposal_id


def test_continuity_proposals_are_pending_until_confirmed_and_do_not_write_markdown(tmp_path: Path) -> None:
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        proposals = asyncio.run(
            service.create_proposals_from_exchange(
                user_message="I feel tired today, can we continue this tomorrow?",
                assistant_answer="We can pause and pick it up tomorrow.",
                conversation_id="conversation-1",
                source_message_id="message-1",
                agent_run_id="run-1",
            )
        )

        assert {proposal.kind for proposal in proposals} >= {"mood", "energy", "open_thread"}
        assert service.context_block() == ""
        assert service.presence_context_block() == ""
        assert service.presence_signal() is None
        assert not list(tmp_path.rglob("*.md"))

        confirmed = service.confirm_proposal(proposals[0].id)

        assert confirmed.status == "confirmed"
        assert "已确认的连续性上下文" in service.context_block()
        assert "陪伴在场行为" in service.presence_context_block()
        assert service.get_state_items()
        assert not list(tmp_path.rglob("*.md"))
    finally:
        service.close()


def test_continuity_proposal_creation_is_idempotent_for_same_exchange(tmp_path: Path) -> None:
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        kwargs = {
            "user_message": "I feel stressed and want to continue this later.",
            "assistant_answer": "We can slow down and return later.",
            "conversation_id": "conversation-1",
            "source_message_id": "message-1",
            "agent_run_id": "run-1",
        }

        first = asyncio.run(service.create_proposals_from_exchange(**kwargs))
        second = asyncio.run(service.create_proposals_from_exchange(**kwargs))

        assert first
        assert [proposal.id for proposal in second] == [proposal.id for proposal in first]
        assert len(service.list_pending()) == len(first)
    finally:
        service.close()


def test_rejected_continuity_proposal_stays_queryable_but_not_in_context(tmp_path: Path) -> None:
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        [proposal, *_] = asyncio.run(
            service.create_proposals_from_exchange(
                user_message="I feel lonely tonight.",
                assistant_answer="I can stay with you for a bit.",
                conversation_id="conversation-1",
                source_message_id="message-1",
                agent_run_id="run-1",
            )
        )

        rejected = service.reject_proposal(proposal.id, "not accurate")

        assert rejected.status == "rejected"
        assert service.list_pending() == []
        assert service.context_block() == ""
        assert service.presence_context_block() == ""
        assert service.presence_signal() is None
        with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
            row = conn.execute(
                "SELECT status, rejected_reason FROM continuity_proposals WHERE id = ?",
                (proposal.id,),
            ).fetchone()
        assert row == ("rejected", "not accurate")
    finally:
        service.close()


def test_confirmed_open_thread_creates_runtime_presence_signal_only(tmp_path: Path) -> None:
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        proposals = asyncio.run(
            service.create_proposals_from_exchange(
                user_message="I feel tired today, can we continue this tomorrow?",
                assistant_answer="We can pause and pick it up tomorrow.",
                conversation_id="conversation-1",
                source_message_id="message-1",
                agent_run_id="run-1",
            )
        )
        open_thread = next(proposal for proposal in proposals if proposal.kind == "open_thread")

        assert service.presence_signal() is None

        service.confirm_proposal(open_thread.id)
        signal = service.presence_signal()

        assert signal is not None
        assert signal.kind == "open_thread"
        assert signal.intensity == "high"
        assert signal.source_state_keys == ("unresolved_threads",)
        assert "Vault" in signal.display_hint
        assert not list(tmp_path.rglob("*.md"))
    finally:
        service.close()


def test_confirm_continuity_proposal_is_idempotent_but_reject_after_confirm_fails(tmp_path: Path) -> None:
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        [proposal, *_] = asyncio.run(
            service.create_proposals_from_exchange(
                user_message="Thank you, you helped me feel less stressed.",
                assistant_answer="I am here with you.",
                conversation_id="conversation-1",
                source_message_id="message-1",
                agent_run_id="run-1",
            )
        )

        first = service.confirm_proposal(proposal.id)
        second = service.confirm_proposal(proposal.id)

        assert first.status == "confirmed"
        assert second.status == "confirmed"
        with pytest.raises(ContinuityProposalStateError):
            service.reject_proposal(proposal.id, "changed mind")
    finally:
        service.close()


def test_sensitive_exchange_does_not_create_continuity_proposal(tmp_path: Path) -> None:
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        proposals = asyncio.run(
            service.create_proposals_from_exchange(
                user_message="I feel tired and my api key is sk-continuity-secret-1234567890",
                assistant_answer="I will not save that.",
                conversation_id="conversation-1",
                source_message_id="message-1",
                agent_run_id="run-1",
            )
        )

        assert proposals == []
        assert service.list_pending() == []
    finally:
        service.close()


def test_rejecting_confirmed_open_thread_retracts_presence_state(tmp_path: Path) -> None:
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        first_id = _seed_open_thread(service, "话题甲待续")
        second_id = _seed_open_thread(service, "话题乙待续")
        service.confirm_proposal(first_id)
        service.confirm_proposal(second_id)
        assert "话题甲待续" in service.context_block()
        assert "话题乙待续" in service.context_block()

        # 在场信号带上来源提案 id,前端据此提供「不再继续」入口。
        signal = service.presence_signal()
        assert signal is not None
        assert signal.kind == "open_thread"
        assert signal.source_proposal_id is not None

        rejected = service.reject_proposal(first_id, reason="不再继续这个话题")

        assert rejected.status == "rejected"
        assert "话题甲待续" not in service.context_block()
        assert "话题乙待续" in service.context_block()

        # 第二条也拒绝后,在场状态清空,不再注入任何未完话题。
        service.reject_proposal(second_id, reason="不再继续这个话题")
        assert "unresolved_threads" not in {item.state_key for item in service.get_state_items()}
        assert "未完话题" not in service.context_block()
    finally:
        service.close()


def test_presence_context_caps_unresolved_threads_to_two_most_recent(tmp_path: Path) -> None:
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        for summary in ("最旧话题", "旧话题", "新话题一", "新话题二"):
            proposal_id = _seed_open_thread(service, summary)
            service.confirm_proposal(proposal_id)

        block = service.context_block()

        assert "新话题一" in block
        assert "新话题二" in block
        assert "最旧话题" not in block
        assert "旧话题" not in block
    finally:
        service.close()


def test_rejected_thread_identity_blocks_the_same_topic_on_later_turns(tmp_path: Path) -> None:
    # 身份 = (kind, 归一化摘要),不含每轮 message/run/evidence:
    # 否则同一话题每轮都会变成"新提案",用户拒绝永远不生效、话题必然复发。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        candidate = {
            "kind": "open_thread",
            "summary": "用户想下次继续聊酒馆卡链接的事",
            "evidence": "第一轮的证据文字",
            "confidence": 0.8,
        }
        first = service._insert_candidate(
            candidate,
            conversation_id="conversation-1",
            source_message_id="message-1",
            agent_run_id="run-1",
        )
        assert first is not None
        service.reject_proposal(first.id, reason="不再继续")

        later_turn = service._insert_candidate(
            {**candidate, "evidence": "第二轮完全不同的证据措辞"},
            conversation_id="conversation-2",
            source_message_id="message-2",
            agent_run_id="run-2",
        )
        assert later_turn is None
        assert service.list_pending() == []

        # 换一种措辞但仍是同一个话题(相似度 0.19 ≥ 阈值 0.14)→ 同样被抑制。
        reworded = service._insert_candidate(
            {
                **candidate,
                "summary": "用户似乎在查找那个酒馆卡链接,助手暂时没能给出,需要补充出处",
            },
            conversation_id="conversation-4",
            source_message_id="message-4",
            agent_run_id="run-4",
        )
        assert reworded is None

        other_topic = service._insert_candidate(
            {**candidate, "summary": "另一件完全不同的未完事情"},
            conversation_id="conversation-3",
            source_message_id="message-3",
            agent_run_id="run-3",
        )
        assert other_topic is not None
        assert other_topic.status == "pending"
    finally:
        service.close()


def test_greeting_only_exchange_does_not_create_open_thread(tmp_path: Path) -> None:
    # 纯问候不构成未完话题:否则每发一个 "hi" 都会新增一条噪音话题。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        proposals = asyncio.run(
            service.create_proposals_from_exchange(
                user_message="hi",
                assistant_answer="嗨，我在。",
                conversation_id="conversation-greeting",
                source_message_id="message-greeting",
                agent_run_id="run-greeting",
            )
        )

        assert [proposal.kind for proposal in proposals if proposal.kind == "open_thread"] == []

        # 有实质内容的消息仍然照常生成未完话题。
        with_topic = asyncio.run(
            service.create_proposals_from_exchange(
                user_message="那个酒馆卡的链接我还没找到，下次继续帮我看",
                assistant_answer="好的，下次接着看。",
                conversation_id="conversation-topic",
                source_message_id="message-topic",
                agent_run_id="run-topic",
            )
        )
        assert any(proposal.kind == "open_thread" for proposal in with_topic) or with_topic == []
    finally:
        service.close()


def _state_owner_status(service: ContinuityService) -> tuple[str | None, str | None]:
    row = service.conn.execute(
        "SELECT source_proposal_id FROM continuity_state WHERE state_key = 'unresolved_threads'"
    ).fetchone()
    if row is None or row["source_proposal_id"] is None:
        return None, None
    owner_id = str(row["source_proposal_id"])
    proposal = service.conn.execute(
        "SELECT status FROM continuity_proposals WHERE id = ?", (owner_id,)
    ).fetchone()
    return owner_id, (str(proposal["status"]) if proposal is not None else "<missing>")


def test_presence_signal_names_one_thread_and_targets_that_live_proposal(tmp_path: Path) -> None:
    # 按钮一次只静音一个话题,提示就必须只讲那一个话题:
    # 否则用户看到三条话题、按钮只撤下其中一条,会断定按钮失效。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        first = _seed_open_thread(service, "话题甲待续")
        second = _seed_open_thread(service, "话题乙待续")
        third = _seed_open_thread(service, "话题丙待续")
        for proposal_id in (first, second, third):
            service.confirm_proposal(proposal_id)

        signal = service.presence_signal()
        assert signal is not None
        assert "话题丙待续" in signal.summary
        assert "话题甲待续" not in signal.summary
        assert "另有 2 条待接续话题" in signal.summary
        assert signal.source_proposal_id == third

        # 每拒绝一次,提示就推进到下一条仍存活的话题,落点始终是可拒绝的活提案。
        service.reject_proposal(third, reason="不再继续")
        signal = service.presence_signal()
        assert signal is not None
        assert "话题乙待续" in signal.summary
        assert "话题甲待续" not in signal.summary
        assert signal.source_proposal_id == second

        service.reject_proposal(second, reason="不再继续")
        signal = service.presence_signal()
        assert signal is not None
        assert "话题甲待续" in signal.summary
        assert "另有" not in signal.summary
        assert signal.source_proposal_id == first

        service.reject_proposal(first, reason="不再继续")
        assert "unresolved_threads" not in {item.state_key for item in service.get_state_items()}
    finally:
        service.close()


def test_rejected_owner_pointer_is_derived_back_to_a_live_thread(tmp_path: Path) -> None:
    # 复现线上库的真实形态:continuity_state 只有一个来源列,而未完话题是合并列表。
    # 拒绝一条后该列仍停在刚被拒绝的提案上,前端于是拿一个已拒绝的 id 去调拒绝接口,
    # 服务层按幂等返回成功 —— 按钮从此变成静默空操作。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        first = _seed_open_thread(service, "话题甲待续")
        second = _seed_open_thread(service, "话题乙待续")
        service.confirm_proposal(first)
        service.confirm_proposal(second)
        service.reject_proposal(second, reason="不再继续")

        # 人为把来源列写回已拒绝的那条提案,模拟修复前遗留的状态行。
        service.conn.execute(
            "UPDATE continuity_state SET source_proposal_id = ? WHERE state_key = 'unresolved_threads'",
            (second,),
        )
        service.conn.commit()
        assert _state_owner_status(service) == (second, "rejected")

        signal = service.presence_signal()
        assert signal is not None
        assert signal.source_proposal_id == first
        assert signal.source_proposal_id != second

        # 提示给出的落点必须是可用的:点下去真的能把话题撤下。
        service.reject_proposal(signal.source_proposal_id, reason="不再继续")
        assert "unresolved_threads" not in {item.state_key for item in service.get_state_items()}
        assert service.presence_signal() is None
    finally:
        service.close()


def test_rejecting_an_already_rejected_thread_still_converges(tmp_path: Path) -> None:
    # 重复点击必须收敛而不是假装成功:已拒绝的 open_thread 仍要复查在场状态。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        first = _seed_open_thread(service, "话题甲待续")
        second = _seed_open_thread(service, "话题乙待续")
        service.confirm_proposal(first)
        service.confirm_proposal(second)

        service.reject_proposal(first, reason="不再继续")
        # 把第一条话题以"漏网的措辞"塞回状态,模拟相似度规则未覆盖的残留。
        service.conn.execute(
            "UPDATE continuity_state SET value = ? WHERE state_key = 'unresolved_threads'",
            ("话题甲待续 | 话题乙待续",),
        )
        service.conn.commit()

        again = service.reject_proposal(first, reason="不再继续")

        assert again.status == "rejected"
        value = service.conn.execute(
            "SELECT value FROM continuity_state WHERE state_key = 'unresolved_threads'"
        ).fetchone()["value"]
        assert str(value) == "话题乙待续"
        # 落点必须仍是活提案,否则下一次点击又会掉进静默空操作。
        owner_id, owner_status = _state_owner_status(service)
        assert owner_id == second
        assert owner_status == "confirmed"
    finally:
        service.close()


def test_model_failure_logs_warning_and_uses_deterministic_fallback(tmp_path: Path, caplog) -> None:
    class FailingModel:
        async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            raise RuntimeError("model down")

    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        caplog.set_level(logging.WARNING, logger="app.services.continuity")

        proposals = asyncio.run(
            service.create_proposals_from_exchange(
                user_message="I feel tired today, can we continue this tomorrow?",
                assistant_answer="We can pause and pick it up tomorrow.",
                conversation_id="conversation-1",
                source_message_id="message-1",
                agent_run_id="run-1",
                model_client=FailingModel(),
            )
        )

        assert {proposal.kind for proposal in proposals} >= {"mood", "energy", "open_thread"}
        assert "Continuity model extraction failed; falling back to deterministic candidates" in caplog.text
    finally:
        service.close()


def test_rejecting_one_mood_template_does_not_silence_the_others(tmp_path: Path) -> None:
    # 模板句两两共享 4 个 bigram(公共前缀),整句相似度会把它们判成同一话题:
    # 用户拒绝"难过"之后,"压力/兴奋/孤独"全都不再提案,界面毫无提示。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        first = service._insert_candidate(
            _template_candidate("mood", "用户表达了难过情绪。"),
            conversation_id="conversation-mood-1",
            source_message_id="message-mood-1",
            agent_run_id="run-mood-1",
        )
        assert first is not None
        service.reject_proposal(first.id, reason="不想聊这个")

        other = service._insert_candidate(
            _template_candidate("mood", "用户表达了兴奋。"),
            conversation_id="conversation-mood-2",
            source_message_id="message-mood-2",
            agent_run_id="run-mood-2",
        )

        assert other is not None
        assert other.status == "pending"
    finally:
        service.close()


def test_rejecting_a_template_topic_does_not_silence_free_text(tmp_path: Path) -> None:
    # 模板句与模型自由文本是两种身份:拒绝一个模板话题不该连带压掉同 kind 的自由文本。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        template = service._insert_candidate(
            _template_candidate("mood", "用户表达了压力。"),
            conversation_id="conversation-template",
            source_message_id="message-template",
            agent_run_id="run-template",
        )
        assert template is not None
        service.reject_proposal(template.id, reason="不想聊这个")

        free_text = service._insert_candidate(
            {
                "kind": "mood",
                "summary": "用户刚刚说评审前的准备让他有点睡不着",
                "evidence": "我这两晚都睡不太好",
                "confidence": 0.7,
            },
            conversation_id="conversation-free-text",
            source_message_id="message-free-text",
            agent_run_id="run-free-text",
        )

        assert free_text is not None
    finally:
        service.close()


def test_rejecting_the_name_suggestion_silences_other_names(tmp_path: Path) -> None:
    # 名字是变量,"要不要记录助手名字"是同一个话题:拒绝过一次就不该换个名字再来。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        luna = service._insert_candidate(
            _template_candidate("identity", "陪伴助手的名称线索：Luna。"),
            conversation_id="conversation-name-1",
            source_message_id="message-name-1",
            agent_run_id="run-name-1",
        )
        assert luna is not None
        service.reject_proposal(luna.id, reason="不用记名字")

        aki = service._insert_candidate(
            _template_candidate("identity", "陪伴助手的名称线索：Aki。"),
            conversation_id="conversation-name-2",
            source_message_id="message-name-2",
            agent_run_id="run-name-2",
        )

        assert aki is None
    finally:
        service.close()


def test_retracting_one_thread_keeps_a_similarly_worded_confirmed_thread(tmp_path: Path) -> None:
    # 未完话题是用户确认过的在场状态:按相似度撤销会把"只是措辞相近"的另一条
    # 一起删掉,那是一次静默的状态丢失。撤销只认被拒绝的那一条。
    service = ContinuityService(migrate_db(tmp_path / "state.sqlite3"))
    try:
        keep = service._insert_candidate(
            {
                "kind": "open_thread",
                "summary": "用户想下次继续讨论项目排期",
                "evidence": "下次再对一下排期",
                "confidence": 0.7,
            },
            conversation_id="conversation-keep",
            source_message_id="message-keep",
            agent_run_id="run-keep",
        )
        drop = service._insert_candidate(
            {
                "kind": "open_thread",
                "summary": "用户想下次继续聊酒馆卡链接的事",
                "evidence": "下次继续找那条链接",
                "confidence": 0.7,
            },
            conversation_id="conversation-drop",
            source_message_id="message-drop",
            agent_run_id="run-drop",
        )
        assert keep is not None and drop is not None
        service.confirm_proposal(keep.id)
        service.confirm_proposal(drop.id)

        service.reject_proposal(drop.id, reason="不再继续")

        value = service.conn.execute(
            "SELECT value FROM continuity_state WHERE state_key = 'unresolved_threads'"
        ).fetchone()["value"]
        assert [item.strip() for item in str(value).split(" | ")] == ["用户想下次继续讨论项目排期"]
    finally:
        service.close()


def _template_candidate(kind: str, summary: str) -> dict[str, object]:
    return {
        "kind": kind,
        "summary": summary,
        "evidence": "模板候选的测试证据",
        "confidence": 0.56,
    }
