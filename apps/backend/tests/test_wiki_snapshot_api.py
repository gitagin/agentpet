from __future__ import annotations

import pytest

from app.api.services import factory
from app.repositories.storage import NoteRepository
from app.storage.markdown import read_markdown
from tests.conftest import auth_headers
from tests.test_wiki_publication import published


@pytest.fixture
def api(published, client_factory, monkeypatch):
    service, vault, _, generation = published
    with client_factory(sqlite_name="http-state.sqlite3") as client:
        monkeypatch.setattr(factory, "database", lambda request: service.database)
        monkeypatch.setattr(factory, "wiki_service", lambda request: service.wiki)
        monkeypatch.setattr(factory, "active_vault_id", lambda request: vault)
        yield client, service, generation


def payload(generation, **updates):
    return {"relative_path": "Wiki/Concepts/Product-P.md", "generation": generation, **updates}


def test_snapshot_api_requires_auth_and_returns_versioned_section(api):
    client, _, generation = api
    assert client.post("/api/wiki/pages/read", json=payload(generation)).status_code == 401
    response = client.post(
        "/api/wiki/pages/read", headers=auth_headers(), json=payload(generation, section="定义"),
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["generation"] == generation
    assert page["line_basis"] == "markdown_body"
    assert "Product P uses supplier A." in page["content"]
    assert "## 来源" not in page["content"]
    assert page["start_line"] <= page["end_line"]
    mismatch = client.post(
        "/api/wiki/pages/read", headers=auth_headers(), json=payload(generation, expected_version="wrong"),
    )
    assert mismatch.status_code == 409
    assert "content" not in mismatch.json()


def test_snapshot_api_denies_forgotten_roots_and_arbitrary_paths(api):
    client, service, generation = api
    for path in ("Wiki/../secret.md", "C:/private.md"):
        response = client.post(
            "/api/wiki/pages/read", headers=auth_headers(), json=payload(generation, relative_path=path),
        )
        assert response.status_code == 403
    with service.database.session() as conn:
        conn.execute("UPDATE memory_candidates SET status = 'forgotten' WHERE summary = 'Wiki source provenance'")
    response = client.post("/api/wiki/pages/read", headers=auth_headers(), json=payload(generation))
    assert response.status_code == 403
    assert "Product P uses supplier A." not in response.text


def test_snapshot_api_respects_existing_chunk_filter(api):
    client, service, generation = api
    with service.database.session() as conn:
        vault = conn.execute("SELECT id FROM vaults").fetchone()["id"]
        paths = [row[0] for row in conn.execute("SELECT relative_path FROM wiki_generation_pages")]
        for relative in paths:
            path = service.wiki.writer.vault_root / relative
            NoteRepository(conn).replace_note(
                vault_id=vault, relative_path=relative, markdown=read_markdown(path),
                modified_at=path.stat().st_mtime,
            )
    seen = []
    def policy(candidate):
        seen.append(candidate)
        return candidate.heading != "引用核验"
    client.app.state.retrieval_service.candidate_filter = policy
    response = client.post("/api/wiki/pages/read", headers=auth_headers(), json=payload(generation))
    assert response.status_code == 403
    assert seen
    client.app.state.retrieval_service.candidate_filter = lambda candidate: True
    assert client.post(
        "/api/wiki/pages/read", headers=auth_headers(), json=payload(generation),
    ).status_code == 200


def test_snapshot_api_does_not_leak_foreign_generation(api):
    client, _, _ = api
    response = client.post(
        "/api/wiki/pages/read", headers=auth_headers(), json=payload("unknown-generation"),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "wiki_snapshot_read_unavailable"
