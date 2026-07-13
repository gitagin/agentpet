from __future__ import annotations

import json
from pathlib import Path

from app.demo_seed import _validated_cli_demo_root, seed_demo_environment
from app.services.agent_actions import AgentActionService, AgentActionStore
from app.services.memory import SafeMarkdownWriter
from app.services.retrieval import RetrievalService
from app.storage.database import Database


def test_demo_seed_builds_isolated_golden_path_data(tmp_path) -> None:
    demo_root = tmp_path / "agent-pet-demo"

    manifest = seed_demo_environment(demo_root)

    assert manifest.memory_facts == 5
    assert manifest.tasks == 2
    assert manifest.markdown_files == 5
    assert manifest.indexed_files == 5
    assert (demo_root / "vault" / "Memories" / "LongTerm" / "Preferences.md").is_file()
    assert (demo_root / "vault" / "Wiki" / "Projects" / "Agent-Pet-Demo.md").is_file()

    with Database(manifest.sqlite_path).connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_graph_facts").fetchone()[0] == 5
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM daily_chat_memory_entries").fetchone()[0] == 3
        automation = conn.execute(
            "SELECT use_negotiation, max_rounds, high_risk_confirmation_required FROM automation_settings WHERE id = 1"
        ).fetchone()
        assert tuple(automation) == (1, 2, 1)

    results = RetrievalService(Database(manifest.sqlite_path)).search(
        vault_id=manifest.vault_id,
        query="我之前提过更喜欢上午还是下午开会？顺便告诉我这个结论来自哪条记录。",
        top_k=5,
        source_scope="personal_memory",
        mode="fts",
    )
    assert results.results
    assert any("下午开会" in result.snippet for result in results.results), [
        (result.relative_path, result.snippet)
        for result in results.results
    ]

    daily_results = RetrievalService(Database(manifest.sqlite_path)).search(
        vault_id=manifest.vault_id,
        query="下午开会",
        top_k=5,
        source_scope="daily_chat",
        mode="fts",
    )
    assert daily_results.results
    assert all(result.source_scope == "daily_chat" for result in daily_results.results)
    assert all(
        result.relative_path.startswith("Memories/Daily/")
        and len(result.relative_path.split("/")) == 7
        for result in daily_results.results
    )

    with Database(manifest.sqlite_path).connect() as conn:
        seeded_titles = {
            row[0]
            for row in conn.execute("SELECT title FROM tasks").fetchall()
        }
    assert "给张老师回邮件" not in seeded_titles

    action_store = AgentActionStore(manifest.sqlite_path)
    try:
        action_service = AgentActionService(
            action_store,
            writer=SafeMarkdownWriter(manifest.vault_root),
        )
        reversible = next(
            action
            for action in action_service.list_recent(limit=20)
            if action.action_type == "demo.project_note.write"
        )
        reverted, receipt = action_service.revert(reversible.action_id)
    finally:
        action_store.close()

    assert reverted.status == "reverted"
    assert receipt.action_type == "agent_action.revert"
    assert not (demo_root / "vault" / "Wiki" / "Projects" / "Agent-Pet-Demo.md").exists()

    manifest_payload = json.loads((demo_root / "demo-manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["vault_id"] == manifest.vault_id


def test_demo_seed_refuses_to_overwrite_existing_state(tmp_path) -> None:
    demo_root = tmp_path / "agent-pet-demo"
    demo_root.mkdir()
    (demo_root / "keep.txt").write_text("do not overwrite", encoding="utf-8")

    try:
        seed_demo_environment(demo_root)
    except FileExistsError as error:
        assert "not empty" in str(error)
    else:
        raise AssertionError("seed_demo_environment must refuse non-empty directories")

    assert (demo_root / "keep.txt").read_text(encoding="utf-8") == "do not overwrite"


def test_demo_cli_root_must_resolve_inside_repository_tmp() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    allowed = repository_root / ".tmp" / "demo-cli-validation"

    assert _validated_cli_demo_root(allowed) == allowed.resolve(strict=False)

    try:
        _validated_cli_demo_root(repository_root / "outside-demo")
    except ValueError as error:
        assert "must resolve inside" in str(error)
    else:
        raise AssertionError("CLI demo root must reject paths outside the repository .tmp folder")
