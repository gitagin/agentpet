from __future__ import annotations

import pytest

from app.services.wiki.generations import WikiGenerationError, WikiGenerationStore
from app.services.wiki.snapshot_reader import WikiReadPin, WikiSnapshotReader
from tests.test_wiki_publication import published


def reader_for(service, authorize=lambda vault, path: True):
    return WikiSnapshotReader(service.database, service.wiki, authorize=authorize)


def test_pinned_search_read_and_links_ignore_working_copy(published):
    service, vault, _, generation = published
    reader = reader_for(service)
    pin = reader.pin()
    assert pin == WikiReadPin(vault, generation)
    hits = reader.search(pin, "supplier")
    assert hits
    assert all(hit.generation == generation for hit in hits)
    concept = next(hit for hit in hits if hit.relative_path == "Wiki/Concepts/Product-P.md")
    page = reader.read(pin, concept.relative_path, expected_version=concept.content_hash)
    assert "Product P uses supplier A." in page.content
    assert page.links
    source = reader.read(pin, page.links[0])
    assert page.relative_path in source.backlinks
    path = service.wiki.writer.vault_root / page.relative_path
    path.write_text("# UNVERIFIED_EXTERNAL_TEXT", encoding="utf-8")
    assert reader.read(pin, page.relative_path).content == page.content
    assert not reader.search(pin, "UNVERIFIED_EXTERNAL_TEXT")
    with pytest.raises(WikiGenerationError, match="version_mismatch"):
        reader.read(pin, page.relative_path, expected_version="forged")


def test_draft_and_cross_vault_pins_are_not_readable(published):
    service, vault, _, generation = published
    reader = reader_for(service)
    draft = WikiGenerationStore(service.database).stage(
        vault, base_generation=generation, changes={"Wiki/Draft.md": b"# DRAFT_ONLY_SECRET"},
    )
    with pytest.raises(WikiGenerationError, match="unavailable"):
        reader.pin(draft)
    with pytest.raises(WikiGenerationError, match="unavailable"):
        reader.search(WikiReadPin("another-vault", generation), "supplier")
    assert not reader.search(reader.pin(), "DRAFT_ONLY_SECRET")


@pytest.mark.parametrize("revocation", ["candidate", "permission"])
def test_root_revocation_filters_search_and_blocks_read(published, revocation):
    service, _, _, _ = published
    allowed = True
    reader = reader_for(service, lambda vault, path: allowed)
    pin = reader.pin()
    assert reader.search(pin, "supplier")
    if revocation == "candidate":
        with service.database.session() as conn:
            conn.execute(
                "UPDATE memory_candidates SET status = 'forgotten' WHERE summary = 'Wiki source provenance'"
            )
    else:
        allowed = False
    assert reader.search(pin, "supplier") == []
    with pytest.raises(WikiGenerationError):
        reader.read(pin, "Wiki/Concepts/Product-P.md")


def test_sections_report_body_positions_and_never_silently_truncate(published):
    service, _, _, _ = published
    reader = reader_for(service)
    pin = reader.pin()
    page = reader.read(pin, "Wiki/Concepts/Product-P.md")
    section = reader.read(pin, page.relative_path, section="定义")
    lines = page.content.splitlines(keepends=True)
    assert section.content == "".join(lines[section.start_line - 1:section.end_line])
    assert "Product P uses supplier A." in section.content
    assert "## 来源" not in section.content
    with pytest.raises(WikiGenerationError, match="budget_exhausted"):
        reader.read(pin, page.relative_path, max_chars=5)


def test_missing_projection_never_falls_back_to_another_version(published):
    service, vault, _, generation = published
    reader = reader_for(service)
    pin = reader.pin()
    with service.database.session() as conn:
        conn.execute("DELETE FROM wiki_body_fts WHERE vault_id = ?", (vault,))
    with pytest.raises(WikiGenerationError, match="projection_incomplete"):
        reader.search(pin, "supplier")
    assert WikiGenerationStore(service.database).active(vault) == generation


def test_head_switch_does_not_change_existing_query_pin(published):
    from app.services.wiki.publication import WikiPublicationService

    service, vault, _, previous = published
    reader = reader_for(service)
    pin = reader.pin()
    store = WikiGenerationStore(service.database)
    new = store.stage(vault, base_generation=previous, changes={})
    store.promote(
        vault, new, validate=WikiPublicationService(service.database, service.wiki)._validate,
    )
    assert reader.pin().generation == new
    assert reader.read(pin, "Wiki/Concepts/Product-P.md").generation == previous
    assert all(hit.generation == previous for hit in reader.search(pin, "supplier"))
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_body_projection").fetchone()[0] == 2
