import sqlite3

import pytest

from app.models.enums import MemoryProposalStatus, MemoryProposalType
from app.services.memory import (
    MarkdownWriteHooks,
    MemoryConflictError,
    MemoryProposalStore,
    MemoryService,
    SafeMarkdownWriter,
    content_hash_bytes,
)


def build_service(tmp_path, hooks=None, index_refresh=None):
    store = MemoryProposalStore(sqlite3.connect(":memory:"))
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
