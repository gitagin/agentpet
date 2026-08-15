from __future__ import annotations

import re
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
    assert "不创建空定义" in concept.markdown_preview
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
    assert "修复建议" in report_text
    assert "wiki_stale_marker" in report_text


def test_wiki_lint_detects_template_sources_logs_and_format_traps(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    vault_root = tmp_path / "Vault"
    wiki_root = vault_root / "Wiki"
    wiki_root.mkdir(parents=True)
    sources = wiki_root / "Sources"
    sources.mkdir()
    (sources / "Concept.md").write_text(
        "---\n"
        "title: Concept\n"
        "type: source\n"
        "tags: [auto-wiki]\n"
        "---\n"
        "# Concept\n\n"
        "Useful content with TODO and [[External/Bad]].\n",
        encoding="utf-8",
    )

    database = Database(db_path)
    MigrationRunner(database).apply()
    with database.connect() as conn:
        with conn:
            vault_id = VaultRepository(conn).upsert(vault_root)

    service = WikiLintService(db_path, vault_id=vault_id, vault_root=vault_root)
    try:
        report = service.run(WikiLintRequest(write_report=False))
    finally:
        service.close()

    codes = {issue.code for issue in report.issues}
    assert {
        "wiki_page_contract_missing",
        "wiki_source_reference_missing",
        "wiki_trigger_source_missing",
        "wiki_revision_missing",
        "wiki_page_update_log_missing",
        "wiki_inbound_link_count_low",
        "wiki_link_path_outside_known_roots",
        "wiki_placeholder_left",
    }.issubset(codes)
    proposal_codes = {proposal.issue_code for proposal in report.repair_proposals}
    assert "wiki_page_contract_missing" in proposal_codes


def test_wiki_lint_enforces_evidence_decision_inference_and_path_contracts(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    vault_root = tmp_path / "Vault"
    wiki_root = vault_root / "Wiki"

    def write_page(relative_path: str, *, page_type: str, sources: list[str], body: str, inference: bool = False) -> None:
        path = wiki_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        source_lines = "\n".join(f"  - {source}" for source in sources)
        inference_line = "inference: true\n" if inference else ""
        path.write_text(
            "---\n"
            f"wiki_id: wiki-{path.stem}\n"
            f"title: {path.stem}\n"
            f"page_type: {page_type}\n"
            f"type: {page_type}\n"
            "entity_ids: []\n"
            "fact_ids: []\n"
            "revision: 1\n"
            "confidence: medium\n"
            "disputed: false\n"
            f"{inference_line}"
            "sources:\n"
            f"{source_lines}\n"
            "updated_at: 2026-08-10T00:00:00Z\n"
            "---\n\n"
            f"# {path.stem}\n\n{body}\n",
            encoding="utf-8",
        )

    write_page(
        "Syntheses/Single.md",
        page_type="synthesis",
        sources=["Wiki/Sources/Only.md"],
        inference=True,
        body=(
            "## 问题\n\nSingle source\n\n"
            "## 结论\n\nA claim.\n\n"
            "## 支持证据\n\n- [[Wiki/Sources/Only.md]]\n\n"
            "## 来源\n\n- [[Wiki/Sources/Only.md]]"
        ),
    )
    write_page(
        "Decisions/Guessed.md",
        page_type="decision",
        sources=["Wiki/Sources/Choice.md"],
        body="## 背景\n\nA model suggestion.\n\n## 依据\n\n- [[Wiki/Sources/Choice.md]]\n\n## 来源\n\n- [[Wiki/Sources/Choice.md]]",
    )
    write_page(
        "Comparisons/Missing-Inference.md",
        page_type="comparison",
        sources=["Wiki/Sources/A.md", "Wiki/Sources/B.md"],
        body=(
            "## 比较对象\n\nA and B\n\n"
            "## 共同证据\n\n- [[Wiki/Sources/A.md]]\n- [[Wiki/Sources/B.md]]\n\n"
            "## 差异\n\nA differs from B.\n\n"
            "## 来源\n\n- [[Wiki/Sources/A.md]]\n- [[Wiki/Sources/B.md]]"
        ),
    )
    write_page(
        "Concepts/Wrong-Type.md",
        page_type="entity",
        sources=["Wiki/Sources/Entity.md"],
        body="## 实体定义\n\nEntity.\n\n## 已确认事实\n\nA fact.\n\n## 来源\n\n- [[Wiki/Sources/Entity.md]]",
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
        "wiki_evidence_insufficient",
        "wiki_decision_missing_user_decision",
        "wiki_inference_marker_missing",
        "wiki_page_type_path_mismatch",
    }.issubset(codes)
    contract_proposals = [
        proposal
        for proposal in report.repair_proposals
        if proposal.issue_code
        in {
            "wiki_evidence_insufficient",
            "wiki_decision_missing_user_decision",
            "wiki_inference_marker_missing",
            "wiki_page_type_path_mismatch",
        }
    ]
    assert contract_proposals
    assert all(proposal.operation == "review" for proposal in contract_proposals)
    assert all(not re.search(r"\b(?:TODO|TBD)\b|待定|待补", proposal.markdown_preview) for proposal in contract_proposals)
