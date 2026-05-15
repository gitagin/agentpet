from __future__ import annotations

from pathlib import Path

from app.models.api import WikiLintRequest
from app.repositories.storage import VaultRepository
from app.services.wiki_lint import WikiLintService
from app.storage.database import Database, MigrationRunner


def test_wiki_lint_returns_non_writing_repair_proposals(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    vault_root = tmp_path / "Vault"
    wiki_root = vault_root / "Wiki"
    wiki_root.mkdir(parents=True)
    (wiki_root / "Source.md").write_text(
        "# Source\n\n"
        "This stale claim conflicts with another note.\n\n"
        "See [[Control Panel Drift]] and [[Missing Target]].\n",
        encoding="utf-8",
    )
    (wiki_root / "Orphan.md").write_text("# Orphan\n\nUnlinked page.\n", encoding="utf-8")
    entities = wiki_root / "Entities"
    entities.mkdir()
    (entities / "OpenAI.md").write_text(
        "---\ntitle: OpenAI\ntype: entity\naliases: [Open AI]\n---\n# OpenAI\n",
        encoding="utf-8",
    )
    (entities / "Open-AI.md").write_text(
        "---\ntitle: Open AI\ntype: entity\n---\n# Open AI\n",
        encoding="utf-8",
    )

    database = Database(db_path)
    MigrationRunner(database).apply()
    with database.connect() as conn:
        with conn:
            vault_id = VaultRepository(conn).upsert(vault_root)

    service = WikiLintService(db_path, vault_id=vault_id, vault_root=vault_root)
    try:
        report = service.run()
    finally:
        service.close()

    codes = {issue.code for issue in report.issues}
    assert {
        "wiki_contradiction_marker",
        "wiki_stale_marker",
        "missing_concept_page",
        "missing_wiki_link",
        "orphan_wiki_page",
        "duplicate_entity_candidate",
    }.issubset(codes)
    assert report.report_page is None
    assert not (wiki_root / "Reports").exists()

    proposal_codes = {proposal.issue_code for proposal in report.repair_proposals}
    assert {
        "wiki_contradiction_marker",
        "wiki_stale_marker",
        "missing_concept_page",
        "missing_wiki_link",
        "orphan_wiki_page",
        "duplicate_entity_candidate",
    }.issubset(proposal_codes)
    concept = next(proposal for proposal in report.repair_proposals if proposal.issue_code == "missing_concept_page")
    assert concept.operation == "create"
    assert concept.target_path == "Wiki/Concepts/Control-Panel-Drift.md"
    assert "type: concept" in concept.markdown_preview
    assert report.summary["repair_proposals"] == len(report.repair_proposals)


def test_wiki_lint_report_write_includes_repair_proposals(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    vault_root = tmp_path / "Vault"
    wiki_root = vault_root / "Wiki"
    wiki_root.mkdir(parents=True)
    (wiki_root / "Main.md").write_text("# Main\n\nThis content is outdated.\n", encoding="utf-8")

    database = Database(db_path)
    MigrationRunner(database).apply()
    with database.connect() as conn:
        with conn:
            vault_id = VaultRepository(conn).upsert(vault_root)

    from app.services.memory import SafeMarkdownWriter
    from app.services.wiki import WikiService

    wiki = WikiService(SafeMarkdownWriter(vault_root))
    service = WikiLintService(db_path, vault_id=vault_id, vault_root=vault_root, wiki=wiki)
    try:
        report = service.run()
    finally:
        service.close()

    assert report.report_page is None
    assert not (wiki_root / "Reports").exists()

    service = WikiLintService(db_path, vault_id=vault_id, vault_root=vault_root, wiki=wiki)
    try:
        written = service.run(WikiLintRequest(write_report=True))
    finally:
        service.close()

    assert written.report_page is not None
    report_path = vault_root.joinpath(*written.report_page.relative_path.split("/"))
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "Repair Proposals" in report_text
    assert "wiki_stale_marker" in report_text
