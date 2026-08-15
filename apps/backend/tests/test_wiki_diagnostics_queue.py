from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.services.wiki_lint import WikiDiagnosticsQueueService


class _TrapWiki:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def ensure_core_files(self) -> None:
        self.calls.append("ensure_core_files")
        raise AssertionError("diagnostics queue must not ensure core Wiki files")

    def append_log(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls.append("append_log")
        raise AssertionError("diagnostics queue must not append the Wiki log")

    def write_page(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls.append("write_page")
        raise AssertionError("diagnostics queue must not write Wiki pages")


class _TrapDiagnosticsQueueService(WikiDiagnosticsQueueService):
    def _write_report(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("diagnostics queue must not write lint reports")


def test_wiki_diagnostics_queue_is_deterministic_and_side_effect_free(tmp_path: Path) -> None:
    vault_root = tmp_path / "Vault"
    wiki_root = vault_root / "Wiki"
    wiki_root.mkdir(parents=True)
    (wiki_root / "Inbox.md").write_text(
        "# Inbox\n\n"
        "This stale claim conflicts with an older note.\n\n"
        "See [[Durable Memory]].\n",
        encoding="utf-8",
    )

    conn = sqlite3.connect(":memory:")
    trap_wiki = _TrapWiki()
    service = _TrapDiagnosticsQueueService(conn, vault_id="vault", vault_root=vault_root, wiki=trap_wiki)
    try:
        first_items = service.list_items()
        second_items = service.list_items()
    finally:
        conn.close()

    first_snapshot = [
        (
            item.diagnostic_type,
            item.issue_code,
            item.severity,
            item.path,
            item.target,
            item.repair_preview.operation if item.repair_preview else None,
            item.repair_preview.target_path if item.repair_preview else None,
        )
        for item in first_items
    ]
    second_snapshot = [
        (
            item.diagnostic_type,
            item.issue_code,
            item.severity,
            item.path,
            item.target,
            item.repair_preview.operation if item.repair_preview else None,
            item.repair_preview.target_path if item.repair_preview else None,
        )
        for item in second_items
    ]

    assert first_snapshot == [
        (
            "contradiction",
            "wiki_contradiction_marker",
            "warning",
            "Wiki/Inbox.md",
            None,
            "review",
            "Wiki/Inbox.md",
        ),
        (
            "stale_claim",
            "wiki_stale_marker",
            "info",
            "Wiki/Inbox.md",
            None,
            "replace_section",
            "Wiki/Inbox.md",
        ),
        (
            "missing_link",
            "missing_wiki_link",
            "warning",
            "Wiki/Inbox.md",
            "Durable Memory",
            "create",
            "Wiki/Concepts/Durable-Memory.md",
        ),
        (
            "missing_concept",
            "missing_concept_page",
            "info",
            "Wiki/Inbox.md",
            "Durable Memory",
            "create",
            "Wiki/Concepts/Durable-Memory.md",
        ),
    ]
    assert second_snapshot == first_snapshot
    assert all(item.repair_preview is not None for item in first_items)
    missing_concept = next(item for item in first_items if item.diagnostic_type == "missing_concept")
    assert "审查概念候选" in missing_concept.repair_preview.markdown_preview
    assert "Wiki/Inbox.md" in missing_concept.repair_preview.markdown_preview
    assert "type: concept" not in missing_concept.repair_preview.markdown_preview
    assert "核心定义" not in missing_concept.repair_preview.markdown_preview

    assert trap_wiki.calls == []
    assert not (wiki_root / "AGENTS.md").exists()
    assert not (wiki_root / "index.md").exists()
    assert not (wiki_root / "log.md").exists()
    assert not (wiki_root / "Reports").exists()
    assert not (wiki_root / "Concepts").exists()
