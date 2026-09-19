from __future__ import annotations

import asyncio
import json

import pytest

from app.models.wiki import WikiIngestPreviewRequest, WikiIngestConfirmRequest, WikiIngestReviewRequest, WikiIngestApplyRequest
from app.services.wiki.compiler import CompilerError, CHUNK_CHARS, read_source
from app.storage.markdown import read_markdown
from tests.test_wiki_workflows import _workflow_service
from app.storage.database import Database


class CompilerModel:
    def __init__(self, claim="Product P uses supplier A.", conflicts=()):
        self.claim = claim
        self.conflicts = list(conflicts)
        self.calls = []

    async def complete(self, *, user_message, system_prompt=None):
        data = json.loads(user_message)
        self.calls.append(data)
        task = data.get("task")
        if task == "read_source":
            return json.dumps({"notes": [{"statement": self.claim, "quote": self.claim,
                "subject": "Product P", "entity_type": "project", "predicate": "supplier",
                "value": self.claim, "related_entity": "Supplier A", "relation": "related_to"}]})
        if task == "select_pages":
            return json.dumps({"paths": [e["path"] for e in data["catalog"] if e["path"] == "Wiki/Concepts/Product-P.md"]})
        if task == "compile_pages":
            source = data["source_path"]
            evidence = [{"path": source, "quote": self.claim}]
            content = self.claim
            for old in data["existing_pages"]:
                if old["path"] == "Wiki/Concepts/Product-P.md":
                    # The scripted model returns an explicit accumulated fixture, testing the
                    # workflow rather than claiming to evaluate a real model's semantic ability.
                    content = "Product P uses supplier A.\n" + self.claim
                    if "Supplier A operates in region R." in old["text"]:
                        content += "\nSupplier A operates in region R."
                    evidence.append({"path": old["path"], "quote": "Product P uses supplier A."})
            return json.dumps({"summary": self.claim, "pages": [
                {"title": data["title"], "page_type": "source", "target_path": source,
                 "content": "## 来源摘要\n\n" + self.claim, "evidence": evidence[:1]},
                {"title": "Product P", "page_type": "concept", "target_path": "Wiki/Concepts/Product-P.md",
                 "content": "## 定义\n\n" + content + "\n\n## 来源\n\n[[" + source + "]]",
                 "evidence": evidence, "conflicts": self.conflicts},
            ]}, ensure_ascii=False)
        return json.dumps({"summary": "Reviewed", "findings": [], "recommended_targets": []})


def service_for(tmp_path, model):
    return _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault", review_model=model)


def compile_preview(service, text, title="Supplier report"):
    return asyncio.run(service.compile_ingest(WikiIngestPreviewRequest(title=title, content=text)))


def apply_preview(service, preview):
    confirmed = service.confirm_ingest(WikiIngestConfirmRequest(preview_token=preview.preview_token, user_confirmed=True))
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
    return service.apply_ingest(WikiIngestApplyRequest(run_id=confirmed.run_id,
        approved_targets=[p.target_path for p in confirmed.page_plans], review_id=review.review_id, review_acknowledged=True))


def test_successive_sources_merge_preserve_provenance_and_mark_conflicts(tmp_path):
    model = CompilerModel()
    service = service_for(tmp_path, model)
    first = compile_preview(service, model.claim)
    assert first.source_metadata["compilation_status"] == "compiled"
    assert not (tmp_path / "Vault/Wiki/Concepts/Product-P.md").exists()
    assert apply_preview(service, first).status == "applied"
    path = tmp_path / "Vault/Wiki/Concepts/Product-P.md"
    text = path.read_text(encoding="utf-8").replace("tags:\n", "aliases:\n  - Product alias\nauthors:\n  - Original author\ntags:\n  - original-tag\n", 1)
    path.write_text(text, encoding="utf-8")
    from app.services.wiki_reconciler import bind_authoritative_wiki_page
    from app.services.memory_entity_graph import MemoryEntityGraphStore
    with service.database.session() as conn:
        vault_id = conn.execute("SELECT id FROM vaults").fetchone()["id"]
        graph = MemoryEntityGraphStore(conn)
        try:
            bind_authoritative_wiki_page(
                graph, vault_id=vault_id, relative_path="Wiki/Concepts/Product-P.md",
                parsed=read_markdown(path),
            )
        finally:
            graph.close()
    model.claim = "Supplier A operates in region R."
    second = compile_preview(service, model.claim)
    assert apply_preview(service, second).status == "applied"
    model.claim = "Product P no longer uses supplier A."
    model.conflicts = ["The supplier changed; the effective date is unknown."]
    third = compile_preview(service, model.claim)
    assert apply_preview(service, third).status == "applied"
    page = read_markdown(tmp_path / "Vault/Wiki/Concepts/Product-P.md")
    assert "Product P uses supplier A." in page.body
    assert "Product P no longer uses supplier A." in page.body
    assert "effective date is unknown" in page.body
    assert page.frontmatter["disputed"] == "true"
    assert page.frontmatter["aliases"] == ["Product alias"]
    assert page.frontmatter["authors"] == ["Original author"]
    assert "original-tag" in page.frontmatter["tags"]
    assert "Supplier A operates in region R." in page.body
    assert page.body.count("## 定义") == 1
    sources = page.frontmatter["sources"]
    assert all(p.page_plans[0].target_path in sources for p in (first, second, third))
    assert len({p.page_plans[0].target_path for p in (first, second, third)}) == 3
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_graph_facts WHERE status = 'candidate'").fetchone()[0] > 0


def test_complete_long_source_is_read_including_tail():
    class Reader:
        def __init__(self): self.texts = []
        async def complete(self, *, user_message, system_prompt):
            text = json.loads(user_message)["text"]
            self.texts.append(text)
            return json.dumps({"notes": [{"statement": text[-20:], "quote": text[-20:]}]})
    model = Reader()
    source = "intro " * (CHUNK_CHARS // 3) + "CRITICAL_TAIL_FACT"
    notes = asyncio.run(read_source(model, source))
    assert len(model.texts) > 1
    assert any("CRITICAL_TAIL_FACT" in note["quote"] for note in notes)
    assert all(any(source[i:i + 100] in text for text in model.texts) for i in range(0, len(source), 100))


@pytest.mark.parametrize("before_confirm", [True, False])
def test_stale_page_rejects_compile_plan_without_overwriting(tmp_path, before_confirm):
    model = CompilerModel()
    service = service_for(tmp_path, model)
    assert apply_preview(service, compile_preview(service, model.claim)).status == "applied"
    model.claim = "Supplier A operates in region R."
    preview = compile_preview(service, model.claim)
    path = tmp_path / "Vault/Wiki/Concepts/Product-P.md"
    if before_confirm:
        path.write_text(path.read_text(encoding="utf-8") + "\nManual correction.\n", encoding="utf-8")
        with pytest.raises(CompilerError, match="stale_context"):
            apply_preview(service, preview)
    else:
        confirmed = service.confirm_ingest(WikiIngestConfirmRequest(preview_token=preview.preview_token, user_confirmed=True))
        review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
        path.write_text(path.read_text(encoding="utf-8") + "\nManual correction.\n", encoding="utf-8")
        with pytest.raises(CompilerError, match="stale_context"):
            service.apply_ingest(WikiIngestApplyRequest(run_id=confirmed.run_id,
                approved_targets=[p.target_path for p in confirmed.page_plans], review_id=review.review_id, review_acknowledged=True))
    assert "Manual correction." in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("response,reason", [("not json", "invalid_json"),
    ('{"notes":[{"statement":"invented","quote":"absent"}]}', "quote_not_in_source")])
def test_invalid_model_does_not_fall_back_to_fake_compilation(tmp_path, response, reason):
    class BrokenModel:
        async def complete(self, **kwargs): return response
    service = service_for(tmp_path, BrokenModel())
    with pytest.raises(CompilerError, match=reason):
        compile_preview(service, "Real source.")
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 0


def test_offline_preview_is_explicitly_uncompiled(tmp_path):
    service = service_for(tmp_path, None)
    preview = compile_preview(service, "Real source.")
    assert preview.source_metadata["compilation_status"] == "model_not_configured"


def test_crlf_page_snapshot_uses_exact_file_hash(tmp_path):
    model = CompilerModel()
    service = service_for(tmp_path, model)
    apply_preview(service, compile_preview(service, model.claim))
    path = tmp_path / "Vault/Wiki/Concepts/Product-P.md"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    model.claim = "Supplier A operates in region R."
    assert apply_preview(service, compile_preview(service, model.claim)).status == "applied"


@pytest.mark.parametrize("status", ["forgotten", "stale", "quarantined"])
def test_compiler_rejects_inactive_existing_page(tmp_path, status):
    from app.services.wiki.compiler import read_evidence_snapshot

    model = CompilerModel()
    service = service_for(tmp_path, model)
    assert apply_preview(service, compile_preview(service, model.claim)).status == "applied"
    with service.database.session() as conn:
        conn.execute("UPDATE wiki_page_bindings SET status = ?", (status,))
    with pytest.raises(CompilerError, match="inactive_wiki_" + status):
        read_evidence_snapshot(service.wiki, "Wiki/Concepts/Product-P.md", database=service.database)


def test_compiler_catalog_never_sends_unreviewed_metadata(tmp_path):
    from app.services.wiki.compiler import related_pages, read_evidence_snapshot

    model = CompilerModel()
    service = service_for(tmp_path, model)
    assert apply_preview(service, compile_preview(service, model.claim)).status == "applied"
    root = service.wiki.writer.vault_root
    path = root / "Wiki/Concepts/Product-P.md"
    path.write_text("---\ntitle: PRIVATE_UNREVIEWED_TITLE\n---\nEdited.", encoding="utf-8")
    (root / "Wiki/Concepts/New.md").write_text("# PRIVATE_NEW_TITLE\nNew.", encoding="utf-8")
    (root / "Wiki/index.md").write_text("# PRIVATE_INDEX_SUMMARY", encoding="utf-8")
    with pytest.raises(CompilerError, match="unverified_wiki_edit"):
        read_evidence_snapshot(service.wiki, "Wiki/Concepts/Product-P.md", database=service.database)
    calls = []

    class CatalogModel:
        async def complete(self, *, user_message, system_prompt):
            calls.append(user_message)
            assert "PRIVATE_" not in user_message
            assert all(entry["path"].startswith("Wiki/Sources/")
                       for entry in json.loads(user_message)["catalog"])
            return '{"paths": []}'

    assert asyncio.run(related_pages(service.wiki, CatalogModel(), [], database=service.database)) == {}
    assert calls


def test_compiler_direct_read_does_not_require_search_index(tmp_path):
    from app.services.wiki.compiler import read_evidence_snapshot
    from app.utils.hash import sha256_bytes_hex

    model = CompilerModel()
    service = service_for(tmp_path, model)
    assert apply_preview(service, compile_preview(service, model.claim)).status == "applied"
    with service.database.session() as conn:
        conn.execute("DELETE FROM notes")
    path = service.wiki.writer.vault_root / "Wiki/Concepts/Product-P.md"
    raw = b"\xef\xbb\xbf" + path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    path.write_bytes(raw)
    snapshot = read_evidence_snapshot(service.wiki, "Wiki/Concepts/Product-P.md", database=service.database)
    assert snapshot.content_hash == sha256_bytes_hex(raw)
    assert snapshot.frontmatter["page_type"] == "concept"


@pytest.mark.parametrize("stage", ["select_pages", "compile_pages", "confirm", "apply"])
def test_compiler_rechecks_revocation_without_a_body_change(tmp_path, stage):
    model = CompilerModel()
    service = service_for(tmp_path, model)
    assert apply_preview(service, compile_preview(service, model.claim)).status == "applied"
    path = service.wiki.writer.vault_root / "Wiki/Concepts/Product-P.md"
    original = path.read_bytes()

    def revoke():
        with service.database.session() as conn:
            conn.execute(
                "UPDATE wiki_page_bindings SET status = 'forgotten' WHERE wiki_relative_path = ?",
                ("Wiki/Concepts/Product-P.md",),
            )

    model.claim = "Supplier A operates in region R."
    if stage in {"select_pages", "compile_pages"}:
        complete = model.complete

        async def revoking_complete(*, user_message, system_prompt):
            response = await complete(user_message=user_message, system_prompt=system_prompt)
            if json.loads(user_message).get("task") == stage:
                revoke()
            return response

        model.complete = revoking_complete
        with pytest.raises(CompilerError, match="inactive_wiki_forgotten"):
            compile_preview(service, model.claim)
    else:
        preview = compile_preview(service, model.claim)
        if stage == "confirm":
            revoke()
            with pytest.raises(CompilerError, match="inactive_wiki_forgotten"):
                apply_preview(service, preview)
        else:
            confirmed = service.confirm_ingest(WikiIngestConfirmRequest(
                preview_token=preview.preview_token, user_confirmed=True,
            ))
            review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
            revoke()
            with pytest.raises(CompilerError, match="inactive_wiki_forgotten"):
                service.apply_ingest(WikiIngestApplyRequest(
                    run_id=confirmed.run_id, approved_targets=[p.target_path for p in confirmed.page_plans],
                    review_id=review.review_id, review_acknowledged=True,
                ))
    assert path.read_bytes() == original


def test_synthesis_reads_sources_and_rejects_stale_evidence(tmp_path):
    from tests.test_wiki_workflows import _ingest_source_page
    from app.models.wiki import WikiSynthesizeRequest

    service = service_for(tmp_path, None)
    sources = [_ingest_source_page(service, title=title) for title in ("Alpha", "Beta")]

    class SynthesisModel:
        async def complete(self, *, user_message, system_prompt):
            data = json.loads(user_message)
            assert data["task"] == "synthesize"
            assert len(data["sources"]) == 2
            return json.dumps({"content": "Alpha and Beta support different scopes.",
                "evidence": [{"path": s["path"], "quote": "Verified evidence from " + title + "."}
                             for s, title in zip(data["sources"], ("Alpha", "Beta"))],
                "conflicts": ["The scopes require clarification."]})

    service.review_model = SynthesisModel()
    request = WikiSynthesizeRequest(title="Comparison", content="Compare scopes", source_paths=sources)
    compiled = asyncio.run(service.compile_synthesis(request))
    assert compiled.content != request.content
    assert compiled.disputed
    response = service.synthesize(compiled)
    page = read_markdown(tmp_path / "Vault" / response.page.relative_path)
    assert "different scopes" in page.body
    path = tmp_path / "Vault" / sources[0]
    path.write_text(path.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")
    with pytest.raises(CompilerError, match="stale_context"):
        service.synthesize(compiled)


def test_synthesis_cannot_rewrite_forgotten_target(tmp_path):
    from tests.test_wiki_workflows import _ingest_source_page
    from app.models.wiki import WikiSynthesizeRequest

    service = service_for(tmp_path, None)
    sources = [_ingest_source_page(service, title=title) for title in ("Alpha", "Beta")]
    request = WikiSynthesizeRequest(title="Comparison", content="Compare scopes", source_paths=sources)
    response = service.synthesize(request)
    relative_path = response.page.relative_path
    path = service.wiki.writer.vault_root / relative_path
    original = path.read_bytes()
    with service.database.session() as conn:
        conn.execute(
            "UPDATE wiki_page_bindings SET status = 'forgotten' WHERE wiki_relative_path = ?",
            (relative_path,),
        )
    with pytest.raises(CompilerError, match="inactive_wiki_forgotten"):
        service.synthesize(request.model_copy(update={"target_path": relative_path}))
    assert path.read_bytes() == original


def test_semantic_lint_detects_conflict_without_marker_words(tmp_path):
    from tests.test_wiki_workflows import _ingest_source_page
    from app.services.wiki.semantic_lint import semantic_issues

    service = service_for(tmp_path, None)
    paths = [_ingest_source_page(service, title=title) for title in ("Alpha", "Beta")]

    class LintModel:
        async def complete(self, *, user_message, system_prompt):
            data = json.loads(user_message)
            assert data["task"] == "semantic_lint"
            assert len(data["pages"]) == 2
            return json.dumps({"findings": [{"kind": "contradiction", "explanation": "Check conflicting scopes.",
                "evidence": [{"path": path, "quote": "Verified evidence from " + title + "."}
                             for path, title in zip(paths, ("Alpha", "Beta"))]}]})

    issues, count = asyncio.run(semantic_issues(service.wiki, LintModel()))
    assert count == 2
    assert issues[0].code == "semantic_contradiction"
    assert issues[0].path == paths[0] and issues[0].target == paths[1]


def test_chat_summary_reads_tail_and_keeps_single_source_status():
    from app.services.chat_answer_wiki_summary import ChatAnswerWikiSummaryService

    answer = "Architecture knowledge and evidence.\n" * 20 + "Tail: preserve independent sources."

    class SummaryModel:
        async def complete(self, *, user_message, system_prompt):
            assert "Tail: preserve independent sources." in json.loads(user_message)["text"]
            return json.dumps({"notes": [{"statement": "Preserve independent sources.",
                "quote": "Tail: preserve independent sources."}]})

    plan = asyncio.run(ChatAnswerWikiSummaryService().plan_with_model(model=SummaryModel(),
        user_question="Explain this architecture and evidence", assistant_answer=answer,
        conversation_id="c", user_message_id="u", assistant_message_id="a", agent_run_id="r",
        diary_markdown_path="Memories/diary.md", memory_date="2026-09-17"))
    assert "Preserve independent sources." in plan.content
    assert "单来源聊天摘要" in plan.content


def test_api_ingest_preview_dispatches_compiler_and_reports_invalid_output(tmp_path, client_factory):
    from app.api.services.factory import wiki_workflow_service_dependency
    from tests.conftest import auth_headers

    model = CompilerModel()
    service = service_for(tmp_path, model)
    with client_factory(sqlite_name="api-state.sqlite3") as client:
        client.app.dependency_overrides[wiki_workflow_service_dependency] = lambda: service
        response = client.post("/api/wiki/ingest/preview", headers=auth_headers(),
            json={"title": "Supplier report", "content": model.claim})
        assert response.status_code == 200
        assert response.json()["source_metadata"]["compilation_status"] == "compiled"
        assert any(call.get("task") == "compile_pages" for call in model.calls)
        assert not (tmp_path / "Vault/Wiki/Concepts/Product-P.md").exists()

        class InvalidModel:
            async def complete(self, **kwargs): return "not-json"
        service.review_model = InvalidModel()
        response = client.post("/api/wiki/ingest/preview", headers=auth_headers(),
            json={"title": "Supplier report", "content": model.claim})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "wiki_compilation_failed"


def test_unquoted_semantic_findings_are_rejected(tmp_path):
    from tests.test_wiki_workflows import _ingest_source_page
    from app.services.wiki.semantic_lint import semantic_issues
    service = service_for(tmp_path, None)
    paths = [_ingest_source_page(service, title=title) for title in ("Alpha", "Beta")]

    class InvalidModel:
        async def complete(self, **kwargs):
            return json.dumps({"findings": [{"kind": "contradiction", "explanation": "Invented",
                "evidence": [{"path": path, "quote": "This quote does not exist."} for path in paths]}]})
    with pytest.raises(CompilerError, match="invalid_citation"):
        asyncio.run(semantic_issues(service.wiki, InvalidModel()))


def test_page_api_accepts_hash_guarded_full_replacement(tmp_path, client_factory):
    from tests.conftest import auth_headers
    from app.utils.hash import sha256_bytes_hex

    vault = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        initialized = client.post("/api/vaults/init", headers=auth_headers(),
            json={"path": str(vault), "create_if_missing": True, "confirmed": True})
        assert initialized.status_code == 200
        payload = {"title": "Replacement", "content": "Original body.",
                   "target_path": "Wiki/Replacement.md", "operation": "create"}
        created = client.post("/api/wiki/pages", headers=auth_headers(), json=payload)
        assert created.status_code == 200
        path = vault / "Wiki/Replacement.md"
        replaced = client.post("/api/wiki/pages", headers=auth_headers(), json={**payload,
            "content": "Replacement body.", "operation": "replace_page",
            "target_content_hash": sha256_bytes_hex(path.read_bytes())})
        assert replaced.status_code == 200, replaced.text
        assert "Replacement body." in path.read_text(encoding="utf-8")
        assert "Original body." not in path.read_text(encoding="utf-8")
