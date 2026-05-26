from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.services.continuity import ContinuityProposalStateError, ContinuityService


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
        assert "Confirmed continuity context" in service.context_block()
        assert "Companion presence behavior" in service.presence_context_block()
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
