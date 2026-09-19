from __future__ import annotations

import asyncio
import json

import pytest

from app.services.memory_candidates import MemoryCandidateStore
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.wiki_reconciler import bind_authoritative_wiki_page
from app.storage.markdown import read_markdown
from app.services.wiki.memory_closure import (
    WikiMemoryClosureError, prepare_wiki_synthesis_authority,
)
from tests.test_wiki_compilation import (
    CompilerModel, apply_preview, compile_preview, service_for,
)


def authority(service, paths):
    with service.database.session() as conn:
        return prepare_wiki_synthesis_authority(
            conn, vault_root=service.wiki.writer.vault_root,
            target_path="Wiki/Syntheses/Combined.md", page_type="synthesis",
            title="Combined", source_paths=paths,
        )


@pytest.fixture
def compiled_sources(tmp_path):
    model = CompilerModel()
    service = service_for(tmp_path, model)
    first = compile_preview(service, model.claim, title="Alpha")
    assert apply_preview(service, first).status == "applied"
    model.claim = "Supplier A operates in region R."
    second = compile_preview(service, model.claim, title="Beta")
    assert apply_preview(service, second).status == "applied"
    return service, [first.page_plans[0].target_path, second.page_plans[0].target_path]


def test_model_compiled_sources_resolve_without_body_hash_marker(compiled_sources):
    service, paths = compiled_sources
    for path in paths:
        assert "- 来源哈希：" not in (service.wiki.writer.vault_root / path).read_text(encoding="utf-8")
    resolved = authority(service, paths)
    assert len(resolved.source_hashes) == 2
    assert len(resolved.source_entity_ids) == 2
    assert resolved.evidence_ids


@pytest.mark.parametrize("status", ["forgotten", "rejected", "archived", "superseded"])
def test_inactive_root_candidate_blocks_synthesis(compiled_sources, status):
    service, paths = compiled_sources
    assert authority(service, paths).evidence_ids
    with service.database.session() as conn:
        candidate = conn.execute(
            "SELECT id FROM memory_candidates WHERE summary = 'Wiki source provenance' LIMIT 1"
        ).fetchone()
        MemoryCandidateStore(conn).transition(candidate_id=candidate["id"], to_status=status)
    with pytest.raises(WikiMemoryClosureError, match="source_candidate_not_activatable"):
        authority(service, paths)


@pytest.mark.parametrize("change", ["raw_body", "source_hash", "foreign_vault", "entity_hash"])
def test_compiled_root_binding_is_revalidated(compiled_sources, change):
    service, paths = compiled_sources
    resolved = authority(service, paths)
    with service.database.session() as conn:
        if change == "raw_body":
            conn.execute("UPDATE wiki_sources SET raw_content = 'tampered'")
        elif change == "source_hash":
            conn.execute(
                "UPDATE wiki_sources SET source_hash = 'tampered' WHERE id = "
                "(SELECT id FROM wiki_sources LIMIT 1)"
            )
        elif change == "foreign_vault":
            conn.execute("UPDATE wiki_sources SET vault_id = NULL")
        else:
            conn.execute(
                "UPDATE memory_entities SET metadata_json = "
                "json_set(metadata_json, '$.source_hash', 'tampered') WHERE id = ?",
                (resolved.source_entity_ids[0],),
            )
    with pytest.raises(WikiMemoryClosureError, match="source_hash_not_authoritative"):
        authority(service, paths)


def test_duplicate_page_paths_do_not_increase_root_count(compiled_sources):
    service, paths = compiled_sources
    with pytest.raises(WikiMemoryClosureError, match="synthesis_sources_not_independent"):
        authority(service, [paths[0], paths[0]])


def test_body_hash_cannot_claim_another_existing_source(compiled_sources):
    service, paths = compiled_sources
    resolved = authority(service, paths)
    path = service.wiki.writer.vault_root / paths[0]
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n- 来源哈希：`{resolved.source_hashes[1]}`\n",
        encoding="utf-8",
    )
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        bind_authoritative_wiki_page(
            graph, vault_id=resolved.vault_id, relative_path=paths[0],
            parsed=read_markdown(path),
        )
    with pytest.raises(WikiMemoryClosureError, match="source_hash_not_authoritative"):
        authority(service, paths)


def test_source_page_with_multiple_bound_roots_fails_closed(compiled_sources):
    service, paths = compiled_sources
    resolved = authority(service, paths)
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        page = graph.get_wiki_binding(
            vault_id=resolved.vault_id, wiki_relative_path=paths[0],
        )
        graph.create_relation(
            relation_type="documented_in", subject_entity_id=resolved.source_entity_ids[1],
            object_entity_id=page["page_entity_id"],
            source_text="Conflicting binding.", source_type="wiki_binding",
            evidence_id="conflicting-source-binding", confidence=1.0,
        )
    with pytest.raises(WikiMemoryClosureError, match="source_identity_ambiguous"):
        authority(service, paths)


def test_same_root_candidate_metadata_cannot_change_source_type(compiled_sources):
    service, paths = compiled_sources
    with service.database.session() as conn:
        conn.execute(
            "UPDATE memory_candidates SET metadata_json = "
            "json_set(metadata_json, '$.source_type', 'assistant_output') "
            "WHERE summary = 'Wiki source provenance'"
        )
    with pytest.raises(WikiMemoryClosureError, match="source_candidate_identity_mismatch"):
        authority(service, paths)


@pytest.mark.parametrize("change,reason", [
    ("forgotten", "source_candidate_not_activatable"),
    ("foreign_vault", "source_hash_not_authoritative"),
    ("derived", "derived_source_requires_verified_roots"),
    ("tampered", "source_hash_not_authoritative"),
])
def test_compiler_rechecks_roots_of_active_pages(compiled_sources, change, reason):
    from app.services.wiki.compiler import CompilerError, read_evidence_snapshot

    service, paths = compiled_sources
    with service.database.session() as conn:
        if change == "forgotten":
            conn.execute(
                "UPDATE memory_candidates SET status = 'forgotten' "
                "WHERE summary = 'Wiki source provenance'"
            )
        elif change == "foreign_vault":
            conn.execute("UPDATE wiki_sources SET vault_id = NULL")
        elif change == "derived":
            conn.execute("UPDATE wiki_sources SET source_type = 'assistant_output'")
        else:
            conn.execute("UPDATE wiki_sources SET raw_content = 'altered after review'")
        assert {row["status"] for row in conn.execute(
            "SELECT status FROM wiki_page_bindings"
        )} == {"active"}
    for path in [paths[0], "Wiki/Concepts/Product-P.md"]:
        with pytest.raises(CompilerError, match=reason):
            read_evidence_snapshot(service.wiki, path, database=service.database)


def test_root_validation_is_read_only(compiled_sources, monkeypatch):
    from app.services.wiki.memory_closure import validate_wiki_page_roots

    service, _ = compiled_sources
    path = "Wiki/Concepts/Product-P.md"
    parsed = read_markdown(service.wiki.writer.vault_root / path)

    def forbidden_constructor(*args, **kwargs):
        raise AssertionError("Root reads must not initialize graph backfill")

    monkeypatch.setattr(MemoryEntityGraphStore, "__init__", forbidden_constructor)
    with service.database.session() as conn:
        vault_id = conn.execute("SELECT id FROM vaults").fetchone()["id"]
        changes = conn.total_changes
        validate_wiki_page_roots(
            conn, vault_root=service.wiki.writer.vault_root, vault_id=vault_id,
            source_path=path, expected_content_hash=parsed.content_hash,
        )
        assert conn.total_changes == changes


@pytest.mark.parametrize("stage", ["compile_pages", "confirm", "apply"])
def test_compilation_rechecks_root_forgotten_after_reading(compiled_sources, stage):
    from app.models.wiki import WikiIngestApplyRequest, WikiIngestConfirmRequest, WikiIngestReviewRequest
    from app.services.wiki.compiler import CompilerError

    service, _ = compiled_sources
    model = service.review_model
    model.claim = "Product P no longer uses supplier A."
    path = service.wiki.writer.vault_root / "Wiki/Concepts/Product-P.md"
    original = path.read_bytes()

    def forget_roots():
        with service.database.session() as conn:
            conn.execute(
                "UPDATE memory_candidates SET status = 'forgotten' "
                "WHERE summary = 'Wiki source provenance'"
            )

    if stage == "compile_pages":
        complete = model.complete

        async def forget_during_call(*, user_message, system_prompt):
            response = await complete(user_message=user_message, system_prompt=system_prompt)
            if json.loads(user_message).get("task") == stage:
                forget_roots()
            return response

        model.complete = forget_during_call
        with pytest.raises(CompilerError, match="source_candidate_not_activatable"):
            compile_preview(service, model.claim)
    else:
        preview = compile_preview(service, model.claim)
        if stage == "confirm":
            forget_roots()
            with pytest.raises(CompilerError, match="source_candidate_not_activatable"):
                apply_preview(service, preview)
        else:
            confirmed = service.confirm_ingest(WikiIngestConfirmRequest(
                preview_token=preview.preview_token, user_confirmed=True,
            ))
            review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
            forget_roots()
            with pytest.raises(CompilerError, match="source_candidate_not_activatable"):
                service.apply_ingest(WikiIngestApplyRequest(
                    run_id=confirmed.run_id, approved_targets=[p.target_path for p in confirmed.page_plans],
                    review_id=review.review_id, review_acknowledged=True,
                ))
    assert path.read_bytes() == original


def test_compiler_rejects_reviewed_provenance_cycle(compiled_sources):
    from app.services.wiki.compiler import CompilerError, read_evidence_snapshot

    service, sources = compiled_sources
    relative = "Wiki/Concepts/Product-P.md"
    path = service.wiki.writer.vault_root / relative
    text = path.read_text(encoding="utf-8")
    for source in sources:
        text = text.replace(source, relative)
    path.write_text(text, encoding="utf-8")
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        try:
            bind_authoritative_wiki_page(
                graph, vault_id=conn.execute("SELECT id FROM vaults").fetchone()["id"],
                relative_path=relative, parsed=read_markdown(path),
            )
        finally:
            graph.close()
    with pytest.raises(CompilerError, match="synthesis_source_cycle"):
        read_evidence_snapshot(service.wiki, relative, database=service.database)


def test_message_trace_alone_cannot_supply_roots(compiled_sources):
    from app.services.wiki.compiler import CompilerError, read_evidence_snapshot

    service, sources = compiled_sources
    relative = "Wiki/Concepts/Product-P.md"
    path = service.wiki.writer.vault_root / relative
    text = path.read_text(encoding="utf-8")
    for source in sources:
        text = text.replace(source, "message:trace-only")
    path.write_text(text, encoding="utf-8")
    with service.database.session() as conn:
        graph = MemoryEntityGraphStore(conn)
        try:
            bind_authoritative_wiki_page(
                graph, vault_id=conn.execute("SELECT id FROM vaults").fetchone()["id"],
                relative_path=relative, parsed=read_markdown(path),
            )
        finally:
            graph.close()
    with pytest.raises(CompilerError, match="synthesis_source_provenance_missing"):
        read_evidence_snapshot(service.wiki, relative, database=service.database)
