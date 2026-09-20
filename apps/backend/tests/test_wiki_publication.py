from __future__ import annotations

import json

import pytest

from app.services.wiki.generations import WikiGenerationStore
from app.services.wiki.publication import WikiPublicationService
from tests.test_wiki_compilation import CompilerModel, apply_preview, compile_preview, service_for


def publication_record(service, run_id):
    with service.database.session() as conn:
        result = conn.execute("SELECT result_json FROM wiki_workflow_runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(result["result_json"])["publication"]


@pytest.fixture
def published(tmp_path):
    model = CompilerModel()
    service = service_for(tmp_path, model)
    result = apply_preview(service, compile_preview(service, model.claim, title="Alpha"))
    receipt = publication_record(service, result.run_id)
    assert receipt["status"] == "published", receipt
    with service.database.session() as conn:
        vault_id = conn.execute("SELECT id FROM vaults").fetchone()["id"]
    return service, vault_id, result.run_id, receipt["generation"]


def test_ingest_persists_dependency_snapshot_and_idempotent_receipt(published):
    service, vault, run, generation = published
    publisher = WikiPublicationService(service.database, service.wiki)
    assert publisher.publish_ingest(run) == generation
    with service.database.session() as conn:
        rows = conn.execute(
            "SELECT * FROM wiki_generation_dependencies WHERE generation = ?", (generation,),
        ).fetchall()
        assert len(rows) == 2
        concept = next(row for row in rows if row["relative_path"] == "Wiki/Concepts/Product-P.md")
        dependencies = json.loads(concept["dependency_json"])
        assert len(dependencies["pages"]) == 2
        assert dependencies["root_entities"]
        assert conn.execute("SELECT COUNT(*) FROM wiki_generations").fetchone()[0] == 1
    assert publisher.store.active(vault) == generation


def test_second_ingest_publishes_all_pages_together(published, monkeypatch):
    service, vault, _, previous = published
    store = WikiGenerationStore(service.database)
    old = store.read_body(vault, previous, "Wiki/Concepts/Product-P.md")
    promote = WikiGenerationStore.promote

    def observed_promote(self, vault_id, generation, *, validate):
        assert self.active(vault_id) == previous
        assert self.read_body(vault_id, previous, "Wiki/Concepts/Product-P.md") == old
        promote(self, vault_id, generation, validate=validate)

    monkeypatch.setattr(WikiGenerationStore, "promote", observed_promote)
    service.review_model.claim = "Supplier A operates in region R."
    result = apply_preview(service, compile_preview(service, service.review_model.claim, title="Beta"))
    receipt = publication_record(service, result.run_id)
    assert receipt["status"] == "published", receipt
    assert receipt["generation"] != previous
    assert store.active(vault) == receipt["generation"]
    assert store.read_body(vault, previous, "Wiki/Concepts/Product-P.md") == old
    assert b"region R" in store.read_body(vault, receipt["generation"], "Wiki/Concepts/Product-P.md")
    with service.database.session() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM wiki_generation_pages WHERE generation = ?", (receipt["generation"],),
        ).fetchone()[0] == 3


def test_forgotten_source_between_stage_and_promote_blocks_publication(published, monkeypatch):
    service, vault, _, previous = published
    promote = WikiGenerationStore.promote

    def revoked_promote(self, vault_id, generation, *, validate):
        with self.database.session() as conn:
            conn.execute(
                "UPDATE memory_candidates SET status = 'forgotten' WHERE summary = 'Wiki source provenance'"
            )
        promote(self, vault_id, generation, validate=validate)

    monkeypatch.setattr(WikiGenerationStore, "promote", revoked_promote)
    service.review_model.claim = "Supplier A operates in region R."
    result = apply_preview(service, compile_preview(service, service.review_model.claim, title="Beta"))
    receipt = publication_record(service, result.run_id)
    assert receipt["status"] == "blocked", receipt
    assert "root_inactive" in receipt["reason"]
    assert WikiGenerationStore(service.database).active(vault) == previous


def test_failed_publication_can_resume_without_rewriting_working_copy(published):
    service, vault, _, previous = published
    with service.database.session() as conn:
        conn.execute(
            """CREATE TRIGGER interrupt_receipt BEFORE UPDATE OF result_json ON wiki_workflow_runs
               WHEN json_extract(NEW.result_json, '$.publication.status') = 'published'
               BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END"""
        )
    service.review_model.claim = "Supplier A operates in region R."
    result = apply_preview(service, compile_preview(service, service.review_model.claim, title="Beta"))
    assert publication_record(service, result.run_id)["status"] == "failed"
    store = WikiGenerationStore(service.database)
    assert store.active(vault) == previous
    with service.database.session() as conn:
        assert conn.execute(
            "SELECT status FROM wiki_generations WHERE workflow_run_id = ?", (result.run_id,),
        ).fetchone()["status"] == "staged"
        conn.execute("DROP TRIGGER interrupt_receipt")
    path = service.wiki.writer.vault_root / "Wiki/Concepts/Product-P.md"
    before = path.read_bytes()
    generation = WikiPublicationService(service.database, service.wiki).publish_ingest(result.run_id)
    assert store.active(vault) == generation
    receipt = publication_record(service, result.run_id)
    assert receipt["status"] == "published"
    assert receipt["generation"] == generation
    # 登记链(阶段C设计 §1.2):publish 成功即登记 freshness=unknown + 相关性待检查
    assert receipt["freshness"] == "unknown"
    assert receipt["freshness_reason"] == "source_relevance_check_pending"
    assert path.read_bytes() == before


def test_dependency_manifest_cannot_omit_a_required_source(published, monkeypatch):
    service, vault, _, previous = published
    promote = WikiGenerationStore.promote

    def incomplete_promote(self, vault_id, generation, *, validate):
        with self.database.session() as conn:
            conn.execute(
                """DELETE FROM wiki_generation_pages WHERE generation = ? AND relative_path = (
                   SELECT relative_path FROM wiki_generation_pages
                   WHERE generation = ? AND relative_path LIKE 'Wiki/Sources/%' LIMIT 1)""",
                (generation, generation),
            )
        promote(self, vault_id, generation, validate=validate)

    monkeypatch.setattr(WikiGenerationStore, "promote", incomplete_promote)
    service.review_model.claim = "Supplier A operates in region R."
    result = apply_preview(service, compile_preview(service, service.review_model.claim, title="Beta"))
    receipt = publication_record(service, result.run_id)
    assert receipt["status"] == "blocked", receipt
    assert "projection_incomplete" in receipt["reason"]
    assert WikiGenerationStore(service.database).active(vault) == previous
