"""MemorySearchResult 写入侧 source_id/source_version 填充(T14)。

设计 §2.7:检索结果在写入侧按权威数据填充 wiki 来源身份;非 wiki 结果保持 None。
"""

from __future__ import annotations

from app.repositories.storage import VaultRepository
from app.services.retrieval import RetrievalService
from app.storage.database import Database
from tests.test_wiki_workflows import _ingest_source_page, _workflow_service
from tests.wiki_fixtures import indexed_citation


def _vault_id(database, root) -> str:
    with database.session() as conn:
        return VaultRepository(conn).upsert(root)


def test_wiki_source_results_carry_authoritative_source_identity(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    service = _workflow_service(database, tmp_path / "Vault")
    source_path = _ingest_source_page(service, title="Alpha")
    assert source_path.startswith("Wiki/Sources/")

    vault_id = _vault_id(database, service.wiki.writer.vault_root)
    retrieval = RetrievalService(database)
    retrieval.rebuild_index(vault_id)
    response = retrieval.search(
        vault_id=vault_id, query="Verified evidence", top_k=8, mode="fts",
        source_scope="all",
    )

    source_results = [
        item for item in response.results
        if item.relative_path.startswith("Wiki/Sources/")
    ]
    assert source_results, [r.relative_path for r in response.results]
    with database.session() as conn:
        expected = conn.execute(
            "SELECT id, source_version FROM wiki_sources"
        ).fetchone()
    for item in source_results:
        assert item.source_id == expected["id"]
        assert item.source_version == int(expected["source_version"])


def test_non_wiki_results_keep_identity_fields_none(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    _workflow_service(database, vault_root)
    indexed_citation(database, vault_root, "Notes/Plain-note.md")
    vault_id = _vault_id(database, vault_root)

    retrieval = RetrievalService(database)
    response = retrieval.search(
        vault_id=vault_id, query="Relevant snippet", top_k=8, mode="fts",
        source_scope="all",
    )
    assert response.results
    for item in response.results:
        assert item.source_id is None
        assert item.source_version is None


def test_derived_wiki_pages_keep_identity_fields_none(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    service = _workflow_service(database, tmp_path / "Vault")
    _ingest_source_page(service, title="Beta")

    vault_id = _vault_id(database, service.wiki.writer.vault_root)
    retrieval = RetrievalService(database)
    retrieval.rebuild_index(vault_id)
    response = retrieval.search(
        vault_id=vault_id, query="Verified evidence", top_k=8, mode="fts",
        source_scope="all",
    )
    for item in response.results:
        if item.relative_path.startswith("Wiki/") and not item.relative_path.startswith("Wiki/Sources/"):
            assert item.source_id is None
            assert item.source_version is None
