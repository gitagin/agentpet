from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db_with_vault
from app.agents.nodes.chat import _can_use_result_as_answer_context
from app.agents.retrieval.compression import evidence_rejection_reason
from app.models.memory import MemoryRecallPermissions, MemorySearchResult
from app.services.evidence_policy import INACTIVE_EVIDENCE_STATUSES
from app.services.memory_entity_graph import EntityGraphError, MemoryEntityGraphStore
from app.services.prompt_memory_assembler import _prompt_exclusion_reason
from app.services.memory_permissions import split_recall_prompt_sections
from app.services.retrieval import RetrievalService
from app.services.wiki_reconciler import (
    bind_authoritative_wiki_page,
    reconcile_wiki_vault,
)
from app.storage.markdown import read_markdown
from app.storage.database import Database


@pytest.mark.parametrize("status", sorted(INACTIVE_EVIDENCE_STATUSES))
def test_inactive_evidence_is_rejected_on_every_prompt_surface(status):
    result = MemorySearchResult(
        note_id="n", chunk_id="c", relative_path="Wiki/Concepts/Test.md",
        title="Test", snippet="A claim.", score=1, lifecycle_status=status,
        recall_permissions=MemoryRecallPermissions(
            can_style_response=True, can_answer_context=True,
            can_proactively_mention=True, can_suggest_action=True,
        ),
    )
    assert evidence_rejection_reason(result)
    assert not _can_use_result_as_answer_context(result)
    assert _prompt_exclusion_reason(result)
    sections = split_recall_prompt_sections([result], query="claim")
    assert not sections.has_prompt_content


@pytest.mark.parametrize("status,snippet", [
    (" STALE ", "Claim."),
    ("active", "Claim. status=revoked"),
    ("active", "Claim. status=forgotten"),
])
def test_lifecycle_normalization_is_consistent(status, snippet):
    result = MemorySearchResult(
        note_id="n", chunk_id="c", relative_path="Wiki/Concepts/Test.md",
        title="Test", snippet=snippet, score=1, lifecycle_status=status,
    )
    assert evidence_rejection_reason(result)
    assert not _can_use_result_as_answer_context(result)
    assert _prompt_exclusion_reason(result)


def _page(tmp_path: Path):
    db = migrate_db_with_vault(tmp_path / "state.sqlite3")
    root = tmp_path / "Vault"
    path = root / "Wiki" / "Concepts" / "Test.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ntitle: Test\nsources: [forged-source]\n---\nClaim.\n", encoding="utf-8")
    return db, root, path


def test_external_sources_do_not_authorize_page(tmp_path):
    db, root, path = _page(tmp_path)
    report = reconcile_wiki_vault(db, vault_id="vault-1", vault_root=root)
    graph = MemoryEntityGraphStore(db)
    try:
        assert graph.list_wiki_bindings(vault_id="vault-1")[0]["status"] == "quarantined"
    finally:
        graph.close()
    assert report.quarantined == 1


@pytest.mark.parametrize("status", ["active", "stale", "forgotten", "quarantined"])
def test_external_edits_never_promote_or_resurrect(tmp_path, status):
    db, root, path = _page(tmp_path)
    graph = MemoryEntityGraphStore(db)
    try:
        bind_authoritative_wiki_page(graph, vault_id="vault-1",
            relative_path="Wiki/Concepts/Test.md", parsed=read_markdown(path), status=status)
        path.write_text(path.read_text(encoding="utf-8") + "Changed.\n", encoding="utf-8")
        reconcile_wiki_vault(db, vault_id="vault-1", vault_root=root)
        row = graph.list_wiki_bindings(vault_id="vault-1")[0]
        assert row["status"] == ("stale" if status == "active" else status)
    finally:
        graph.close()


def test_missing_wiki_directory_invalidates_bindings(tmp_path):
    db, root, path = _page(tmp_path)
    graph = MemoryEntityGraphStore(db)
    try:
        bind_authoritative_wiki_page(graph, vault_id="vault-1",
            relative_path="Wiki/Concepts/Test.md", parsed=read_markdown(path))
        (root / "Wiki").rename(root / "RemovedWiki")
        report = reconcile_wiki_vault(db, vault_id="vault-1", vault_root=root)
        assert report.deleted == 1
        assert graph.list_wiki_bindings(vault_id="vault-1")[0]["status"] == "stale"
    finally:
        graph.close()


@pytest.mark.parametrize("change", ["external_edit", "forgotten", "stale", "deleted"])
def test_cached_wiki_results_recheck_authority(tmp_path, change):
    db, root, path = _page(tmp_path)
    service = RetrievalService(Database(db))
    service.rebuild_index("vault-1")
    graph = MemoryEntityGraphStore(db)
    try:
        binding_id = bind_authoritative_wiki_page(graph, vault_id="vault-1",
            relative_path="Wiki/Concepts/Test.md", parsed=read_markdown(path))
        assert service.search(vault_id="vault-1", query="Claim").results
        assert service.search(vault_id="vault-1", query="Claim").metadata["cache_status"] == "hit"
        if change == "external_edit":
            path.write_text("# Test\nClaim changed.\n", encoding="utf-8")
        elif change == "deleted":
            path.unlink()
        else:
            row = graph.list_wiki_bindings(vault_id="vault-1")[0]
            graph.update_wiki_binding(binding_id, content_hash=row["content_hash"],
                status=change, revision=int(row["revision"]) + 1)
        assert service.search(vault_id="vault-1", query="Claim").results == []
    finally:
        graph.close()


def test_indexing_unreviewed_wiki_does_not_authorize_retrieval(tmp_path):
    db, root, path = _page(tmp_path)
    service = RetrievalService(Database(db))
    service.rebuild_index("vault-1")
    assert service.search(vault_id="vault-1", query="Claim").results == []


@pytest.mark.parametrize("page_type", ["source", "report"])
def test_assistant_summary_is_not_factual_evidence_even_with_active_binding(tmp_path, page_type):
    db, root, _ = _page(tmp_path)
    relative = "Wiki/Companion/Summaries/answer.md"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\ntitle: Summary\npage_type: {page_type}\nsources: [message:user]\n---\nClaim.\n",
        encoding="utf-8",
    )
    service = RetrievalService(Database(db))
    service.rebuild_index("vault-1")
    graph = MemoryEntityGraphStore(db)
    try:
        bind_authoritative_wiki_page(
            graph, vault_id="vault-1", relative_path=relative, parsed=read_markdown(path),
        )
        assert service.search(vault_id="vault-1", query="Claim").results == []
    finally:
        graph.close()


def test_reviewed_write_cannot_reactivate_forgotten_binding(tmp_path):
    db, root, path = _page(tmp_path)
    graph = MemoryEntityGraphStore(db)
    try:
        bind_authoritative_wiki_page(graph, vault_id="vault-1",
            relative_path="Wiki/Concepts/Test.md", parsed=read_markdown(path), status="forgotten")
        with pytest.raises(EntityGraphError, match="forgotten_wiki_page"):
            bind_authoritative_wiki_page(graph, vault_id="vault-1",
                relative_path="Wiki/Concepts/Test.md", parsed=read_markdown(path))
        binding = graph.list_wiki_bindings(vault_id="vault-1")[0]
        with pytest.raises(EntityGraphError, match="forgotten_wiki_page"):
            graph.update_wiki_binding(binding["id"], content_hash=binding["content_hash"], status="active")
        with pytest.raises(EntityGraphError, match="forgotten_wiki_page"):
            graph.bind_wiki_page(vault_id="vault-1", page_entity_id=binding["page_entity_id"],
                wiki_relative_path="Wiki/Renamed.md", content_hash=binding["content_hash"])
        assert graph.list_wiki_bindings(vault_id="vault-1")[0]["status"] == "forgotten"
    finally:
        graph.close()


def test_statement_authority_two_axis_policy() -> None:
    """陈述权威轴与事实范畴轴正交（设计 source-identity-migration-design.md:198-206）。"""
    from app.services.evidence_policy import (
        ProvenanceKind,
        statement_authority,
        user_statement_overrides_external,
    )

    # 偏好类用户陈述：用户是唯一权威，外部来源不能纠正
    for category in ("preference", "identity", "relationship", "health", "crisis"):
        assert statement_authority(ProvenanceKind.USER_STATEMENT, category) == "user"
        assert user_statement_overrides_external(ProvenanceKind.USER_STATEMENT, category) is True

    # 外部事实类用户陈述：只权威于「用户确实说过这话」，不与外部来源互相覆盖
    for category in ("fact", "event", "rule", "goal"):
        assert statement_authority(ProvenanceKind.USER_STATEMENT, category) == "mixed"
        assert user_statement_overrides_external(ProvenanceKind.USER_STATEMENT, category) is False

    # 外部来源：陈述权威在外部
    for kind in (ProvenanceKind.RAW_SOURCE, ProvenanceKind.COMPILED_WIKI, ProvenanceKind.SYNTHESIS):
        assert statement_authority(kind, "preference") == "external"
        assert user_statement_overrides_external(kind, "preference") is False

    # 类别缺失/未知：保守降为 mixed，且不优先
    assert statement_authority(ProvenanceKind.USER_STATEMENT) == "mixed"
    assert statement_authority(ProvenanceKind.USER_STATEMENT, "unknown_category") == "mixed"
    assert user_statement_overrides_external(ProvenanceKind.USER_STATEMENT, None) is False

    # 大小写与空白归一
    assert statement_authority(ProvenanceKind.USER_STATEMENT, "  Preference  ") == "user"

    # 未知来源性质：不授予用户权威
    assert statement_authority(None, "preference") == "external"
