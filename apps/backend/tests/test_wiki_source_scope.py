from __future__ import annotations

import asyncio
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

from app.models.wiki import (
    WikiIngestApplyRequest,
    WikiIngestConfirmRequest,
    WikiIngestPreviewRequest,
    WikiIngestReviewRequest,
)
from app.repositories.storage import VaultRepository
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.wiki.common import WikiWorkflowError
from app.services.wiki.memory_closure import (
    WikiMemoryClosureError,
    prepare_wiki_synthesis_authority,
)
from app.services.wiki_reconciler import bind_authoritative_wiki_page
from app.storage.database import Database, MigrationRunner
from app.storage.markdown import read_markdown
from tests.test_wiki_workflows import _ingest_source_page, _workflow_service


@pytest.fixture
def services(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    return (
        _workflow_service(database, tmp_path / "FirstVault"),
        _workflow_service(database, tmp_path / "OtherVault"),
    )


def ingest_request(text="Private original source."):
    return WikiIngestPreviewRequest(title="Private original", content=text, max_pages=1)


def confirm(service, request=None, **kwargs):
    preview = service.preview_ingest(request or ingest_request())
    return service.confirm_ingest(
        WikiIngestConfirmRequest(preview_token=preview.preview_token, user_confirmed=True),
        **kwargs,
    )


def test_new_source_uses_server_vault_identity(services):
    first, other = services
    confirmed = confirm(first, ingest_request().model_copy(update={
        "source_metadata": {"vault_id": "client-forged-vault"}
    }))
    with first.database.session() as conn:
        row = conn.execute(
            "SELECT vaults.root_path FROM wiki_sources JOIN vaults "
            "ON vaults.id = wiki_sources.vault_id WHERE wiki_sources.id = ?",
            (confirmed.source_id,),
        ).fetchone()
    assert row["root_path"] == str(first.wiki.writer.vault_root.resolve())
    assert other._existing_source_id(confirmed.source_hash) is None


def test_same_hash_in_other_vault_is_not_reused_or_disclosed(services):
    # v2 语义说明:本用例锁定 legacy(source_identity_v2 关闭)行为——跨 vault 同正文
    # 仍被拒绝复用(scope_unverified)。v2 开启后跨 vault 同正文各自新建,由
    # test_source_identity_migration.py::test_same_body_in_different_vaults_is_independent 覆盖。
    first, other = services
    confirmed = confirm(first)
    preview = other.preview_ingest(ingest_request())
    assert preview.source_id != confirmed.source_id
    with pytest.raises(WikiWorkflowError, match="source_scope_unverified"):
        other.confirm_ingest(WikiIngestConfirmRequest(
            preview_token=preview.preview_token, user_confirmed=True
        ))
    with first.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM wiki_workflow_runs").fetchone()[0] == 1


def test_cross_vault_run_cannot_be_reviewed_cached_or_applied(services):
    first, other = services
    confirmed = confirm(first)
    review = asyncio.run(first.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
    for refresh in (False, True):
        with pytest.raises(WikiWorkflowError, match="source_scope_unverified"):
            asyncio.run(other.review_ingest(WikiIngestReviewRequest(
                run_id=confirmed.run_id, force_refresh=refresh
            )))
    with pytest.raises(WikiWorkflowError, match="source_scope_unverified"):
        other.get_ingest_review(review.review_id)
    with pytest.raises(WikiWorkflowError, match="source_scope_unverified"):
        other.apply_ingest(WikiIngestApplyRequest(
            run_id=confirmed.run_id, review_id=review.review_id,
            review_acknowledged=True,
            approved_targets=[p.target_path for p in confirmed.page_plans],
        ))
    assert not other.wiki.writer.vault_root.exists()


def test_foreign_run_id_cannot_be_overwritten_with_a_local_source(services):
    first, other = services
    original = confirm(first)
    with pytest.raises(WikiWorkflowError, match="source_scope_unverified"):
        confirm(other, ingest_request("Other body."), run_id=original.run_id)
    assert first._load_ingest_run(original.run_id).raw_content == ingest_request().content
    with first.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 1


def test_foreign_review_id_cannot_be_overwritten(services):
    first, other = services
    original = confirm(first)
    review = asyncio.run(first.review_ingest(WikiIngestReviewRequest(run_id=original.run_id)))
    local = confirm(other, ingest_request("Other body."))
    with pytest.raises(WikiWorkflowError, match="review_identity_conflict"):
        asyncio.run(other.review_ingest(
            WikiIngestReviewRequest(run_id=local.run_id),
            review_id=review.review_id,
        ))
    assert first.get_ingest_review(review.review_id).run_id == original.run_id


def test_unknown_legacy_scope_is_not_claimed_by_current_vault(services):
    first, _ = services
    confirmed = confirm(first)
    review = asyncio.run(first.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
    with first.database.session() as conn:
        conn.execute("UPDATE wiki_sources SET vault_id = NULL WHERE id = ?", (confirmed.source_id,))
    for read in (
        lambda: first.validate_ingest_run(confirmed.run_id),
        lambda: first.get_ingest_review(review.review_id),
        lambda: confirm(first),
    ):
        with pytest.raises(WikiWorkflowError, match="source_scope_unverified"):
            read()
    with first.database.session() as conn:
        assert conn.execute("SELECT vault_id FROM wiki_sources").fetchone()[0] is None


@pytest.mark.parametrize("kind", ["confirm", "review", "apply"])
def test_receipts_do_not_restore_foreign_or_unscoped_results(services, monkeypatch, kind):
    from app.api.services import adapters

    first, other = services
    key = "b" * 64
    run_id = adapters._stable_effect_id("wiki-ingest", key)
    confirmed = confirm(first, run_id=run_id)
    review_id = adapters._stable_effect_id("wiki-review", key)
    review = asyncio.run(first.review_ingest(
        WikiIngestReviewRequest(run_id=run_id), review_id=review_id
    ))
    result = {"expected_state": {"run_id": run_id, "response": {"run_id": run_id}}}
    if kind == "apply":
        first.apply_ingest(WikiIngestApplyRequest(
            run_id=run_id, review_id=review.review_id,
            review_acknowledged=True,
            approved_targets=[p.target_path for p in confirmed.page_plans],
        ))
    receipt = SimpleNamespace(idempotency_key=key, result=result)
    monkeypatch.setattr(adapters, "database", lambda _: first.database)
    monkeypatch.setattr(adapters, "wiki_service", lambda _: first.wiki)
    reader = getattr(adapters, f"_wiki_ingest_{kind}_reader")(None)
    monkeypatch.setattr(adapters, "wiki_workflow_service", lambda _: first)
    assert reader(receipt) is not None
    monkeypatch.setattr(adapters, "wiki_workflow_service", lambda _: other)
    assert reader(receipt) is None
    monkeypatch.setattr(adapters, "wiki_workflow_service", lambda _: first)
    with first.database.session() as conn:
        conn.execute("UPDATE wiki_sources SET vault_id = NULL WHERE id = ?", (confirmed.source_id,))
    assert reader(receipt) is None


def test_copied_source_page_does_not_acquire_foreign_raw_source(services):
    first, other = services
    path = _ingest_source_page(first, title="Alpha")
    copied = other.wiki.writer.vault_root / path
    copied.parent.mkdir(parents=True)
    shutil.copyfile(first.wiki.writer.vault_root / path, copied)
    with first.database.session() as conn:
        vault_id = VaultRepository(conn).upsert(other.wiki.writer.vault_root)
    graph = MemoryEntityGraphStore(first.database.path)
    try:
        bind_authoritative_wiki_page(
            graph, vault_id=vault_id, relative_path=path,
            parsed=read_markdown(copied), status="active",
        )
    finally:
        graph.close()
    with first.database.session() as conn:
        with pytest.raises(WikiMemoryClosureError, match="source_hash_not_authoritative"):
            prepare_wiki_synthesis_authority(
                conn, vault_root=other.wiki.writer.vault_root,
                target_path="Wiki/Concepts/Copy.md", page_type="concept",
                title="Copy", source_paths=[path],
            )


@pytest.mark.parametrize("foreign", [False, True])
def test_same_text_hash_does_not_import_unrelated_evidence(services, foreign):
    from app.services.memory_candidates import MemoryCandidateCreate, MemoryCandidateStore
    from app.services.memory_taxonomy import MemoryKind, MemoryScope, SourceTrack

    first, other = services
    path = _ingest_source_page(first, title="Alpha")
    unrelated = confirm(other, ingest_request("Other raw document."))
    with first.database.session() as conn:
        source = conn.execute("SELECT raw_content FROM wiki_sources WHERE vault_id = "
            "(SELECT id FROM vaults WHERE root_path = ?)",
            (str(first.wiki.writer.vault_root),)).fetchone()
        store = MemoryCandidateStore(conn)
        try:
            candidate = store.create_candidate(MemoryCandidateCreate(
                memory_kind=MemoryKind.FACT, memory_scope=MemoryScope.TOPIC,
                summary="Unrelated text match", normalized_value="unrelated-match",
                source_text=source["raw_content"], source_track=SourceTrack.MODEL_EXTRACTED,
                metadata={"source_id": unrelated.source_id} if foreign else {},
            ))
            unrelated_evidence = conn.execute(
                "SELECT id FROM memory_evidence WHERE candidate_id = ?", (candidate.id,)
            ).fetchone()["id"]
        finally:
            store.close()
        authority = prepare_wiki_synthesis_authority(
            conn, vault_root=first.wiki.writer.vault_root,
            target_path="Wiki/Concepts/Local.md", page_type="concept",
            title="Local", source_paths=[path],
        )
        assert authority.evidence_ids
        assert unrelated_evidence not in authority.evidence_ids


def test_synthesis_rejects_link_outside_vault_before_reading(services, monkeypatch):
    from app.services.wiki import memory_closure

    first, other = services
    path = _ingest_source_page(first, title="Alpha")
    link = other.wiki.writer.vault_root / "Wiki" / "Sources"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(first.wiki.writer.vault_root / "Wiki" / "Sources", target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this Windows host")
    monkeypatch.setattr(memory_closure, "read_markdown",
        lambda _: pytest.fail("An outside-vault file was read"))
    with first.database.session() as conn:
        with pytest.raises(WikiMemoryClosureError, match="source_path_invalid"):
            prepare_wiki_synthesis_authority(
                conn, vault_root=other.wiki.writer.vault_root,
                target_path="Wiki/Concepts/Outside.md", page_type="concept",
                title="Outside", source_paths=[path],
            )


@pytest.mark.parametrize("kind", ["review", "apply"])
def test_api_cached_result_is_denied_after_switching_vault(client_factory, tmp_path, kind):
    from tests.conftest import auth_headers

    root = tmp_path / "FirstVault"
    other = tmp_path / "OtherVault"
    with client_factory(data_dir=tmp_path / "data") as client:
        headers = auth_headers()
        assert client.post("/api/vaults/init", headers=headers, json={
            "path": str(root), "create_if_missing": True, "confirmed": True
        }).status_code == 200
        service = _workflow_service(client.app.state.database, root)
        confirmed = confirm(service)
        payload = {"run_id": confirmed.run_id}
        response = client.post("/api/wiki/ingest/review", headers=headers, json=payload)
        assert response.status_code == 200, response.text
        if kind == "apply":
            payload.update({
                "review_id": response.json()["review_id"], "review_acknowledged": True,
                "approved_targets": [p.target_path for p in confirmed.page_plans],
            })
            response = client.post("/api/wiki/ingest/apply", headers=headers, json=payload)
            assert response.status_code == 200, response.text
        assert client.post("/api/vaults/init", headers=headers, json={
            "path": str(other), "create_if_missing": True, "confirmed": True
        }).status_code == 200
        rejected = client.post(f"/api/wiki/ingest/{kind}", headers=headers, json=payload)
        assert rejected.status_code == 400, rejected.text
        assert "Private original source." not in rejected.text
        for plan in confirmed.page_plans:
            assert not (other / plan.target_path).exists()


@pytest.mark.parametrize("inject_failure", [False, True])
def test_scope_migration_preserves_legacy_rows_and_foreign_keys(tmp_path, inject_failure):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in MigrationRunner._default_dir().glob("*.sql"):
        if path.name < "030":
            shutil.copyfile(path, migrations / path.name)
    database = Database(tmp_path / "legacy.sqlite3")
    MigrationRunner(database, migrations).apply()
    with database.session() as conn:
        conn.execute(
            "INSERT INTO wiki_sources(id, source_hash, title, source_type, content_preview, raw_content) "
            "VALUES ('source', 'hash', 'Legacy', 'manual', 'body', 'body')"
        )
        conn.execute(
            "INSERT INTO wiki_workflow_runs(id, workflow_type, source_id, status) "
            "VALUES ('run', 'ingest', 'source', 'planned')"
        )
    if inject_failure:
        migration = MigrationRunner._default_dir() / "030_wiki_source_vault_scope.sql"
        (migrations / migration.name).write_text(
            migration.read_text(encoding="utf-8") + "\nINSERT INTO missing_table VALUES ('fail');",
            encoding="utf-8",
        )
        with pytest.raises(sqlite3.OperationalError):
            MigrationRunner(database, migrations).apply()
        with database.session() as conn:
            assert "vault_id" not in {
                row["name"] for row in conn.execute("PRAGMA table_info(wiki_sources)")
            }
            assert conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = '030_wiki_source_vault_scope'"
            ).fetchone() is None
    # legacy 库(001-029)升级后,030-034 应全部执行并记录在 schema_migrations
    MigrationRunner(database).apply()
    with database.session() as conn:
        recorded = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
    assert {
        "030_wiki_source_vault_scope",
        "031_wiki_generations",
        "032_wiki_publication_dependencies",
        "033_wiki_snapshot_projections",
        "034_message_answer_basis",
    } <= recorded
    assert MigrationRunner(database).apply() == []
    with database.session() as conn:
        row = conn.execute("SELECT * FROM wiki_sources WHERE id = 'source'").fetchone()
        assert row["vault_id"] is None and row["raw_content"] == "body"
        assert conn.execute("SELECT source_id FROM wiki_workflow_runs").fetchone()[0] == "source"
        # 030 的 vault 外键与索引已生效:legacy 行保留、外键引用正确、非法 vault 被拒
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        fks = conn.execute("PRAGMA foreign_key_list(wiki_sources)").fetchall()
        assert any(
            fk["table"] == "vaults" and fk["from"] == "vault_id" and fk["to"] == "id"
            for fk in fks
        )
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(wiki_sources)")}
        assert "idx_wiki_sources_vault" in indexes
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE wiki_sources SET vault_id = 'missing' WHERE id = 'source'")
