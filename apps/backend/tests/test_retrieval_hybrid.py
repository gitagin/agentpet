from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.api import MemorySearchRequest
from app.repositories.storage import SearchResult
from app.services.retrieval import InvalidRetrievalModeError, RetrievalService
from app.services.retrieval_query import RetrievalPlan, build_retrieval_plan as real_build_retrieval_plan
from app.services.vector_index import VectorIndexUnavailableError, VectorSyncResult
from app.storage.database import Database
from tests.conftest import auth_headers


class StubVectorIndex:
    def __init__(
        self,
        *,
        results: list[SearchResult] | None = None,
        search_error: Exception | None = None,
        reconcile_status: str = "success",
    ) -> None:
        self.available = True
        self.config = SimpleNamespace(
            unavailable_reason=None,
            privacy_policy_version="privacy-v1",
        )
        self.results = list(results or [])
        self.search_error = search_error
        self.reconcile_status = reconcile_status
        self.search_calls: list[dict[str, object]] = []
        self.reconcile_calls: list[dict[str, object]] = []

    def health(self, vault_id: str | None = None) -> dict[str, object]:
        return {
            "semantic_available": True,
            "vector_available": True,
            "embedding_configured": True,
            "index_version": "vector-index.v1",
            "active_generation": "generation-1",
            "last_sync_status": "ready",
            "unavailability_reason": None,
        }

    def search(
        self,
        *,
        query: str,
        vault_id: str,
        top_k: int,
        local_privacy: bool = False,
    ) -> list[SearchResult]:
        self.search_calls.append(
            {
                "query": query,
                "vault_id": vault_id,
                "top_k": top_k,
                "local_privacy": local_privacy,
            }
        )
        if self.search_error is not None:
            raise self.search_error
        return list(self.results)

    def reconcile(self, *, conn, vault_id: str, local_privacy: bool = False) -> VectorSyncResult:
        chunk_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM note_chunks WHERE vault_id = ?",
                (vault_id,),
            ).fetchone()[0]
        )
        self.reconcile_calls.append(
            {
                "vault_id": vault_id,
                "local_privacy": local_privacy,
                "authoritative_chunk_count": chunk_count,
            }
        )
        return VectorSyncResult(status=self.reconcile_status, previous_generation="previous-generation")


def _indexed_service(tmp_path: Path, *, content: str = "exact-token semantic content") -> tuple[RetrievalService, str]:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text(f"# Memory\n\n{content}", encoding="utf-8")
    service = RetrievalService(Database(tmp_path / "app.db"))
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    result = service.rebuild_index(vault_id)
    assert result.status == "success"
    return service, vault_id


def _authoritative_candidate(service: RetrievalService, vault_id: str) -> SearchResult:
    with service.database.connect() as conn:
        row = conn.execute(
            """
            SELECT id, note_id, relative_path, title, heading, content, content_hash
            FROM note_chunks
            WHERE vault_id = ?
            ORDER BY chunk_index
            LIMIT 1
            """,
            (vault_id,),
        ).fetchone()
        assert row is not None
        with conn:
            conn.execute(
                """
                INSERT INTO vector_chunks (
                    vector_id, chunk_id, note_id, vault_id, relative_path, content_hash,
                    collection_name, embedding_model
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"point-{row['id']}",
                    row["id"],
                    row["note_id"],
                    vault_id,
                    row["relative_path"],
                    row["content_hash"],
                    "collection-generation-1",
                    "fake-embedding",
                ),
            )
    return SearchResult(
        note_id=str(row["note_id"]),
        chunk_id=str(row["id"]),
        relative_path=str(row["relative_path"]),
        title=str(row["title"]),
        heading=str(row["heading"]) if row["heading"] is not None else None,
        snippet=str(row["content"]),
        score=0.91,
        content_hash=str(row["content_hash"]),
        vault_id=vault_id,
        generation="generation-1",
    )


def _set_local_privacy(service: RetrievalService, enabled: bool) -> None:
    with service.database.connect() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO app_state(key, value, updated_at)
                VALUES ('local_privacy_mode', ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (json.dumps(enabled),),
            )


def _assert_safe_metadata(metadata: dict[str, object], *private_values: str) -> None:
    serialized = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    for value in private_values:
        assert value not in serialized
    assert "Memory.md" not in serialized


def test_fts_mode_uses_exact_lexical_query_and_never_calls_vector(tmp_path: Path) -> None:
    service, vault_id = _indexed_service(tmp_path)
    vector = StubVectorIndex(search_error=AssertionError("vector search must not run"))
    service.vector_index = vector

    response = service.search(vault_id=vault_id, query="exact-token", mode="fts")

    assert response.results
    assert response.results[0].retrieval_mode == "fts"
    assert vector.search_calls == []
    assert response.metadata["requested_mode"] == "fts"
    assert response.metadata["effective_mode"] == "fts"
    assert response.metadata["requested_channels"] == ["fts"]
    assert response.metadata["completed_channels"] == ["fts"]
    assert len(response.metadata["plan_telemetry"]["query_hash"]) == 64
    _assert_safe_metadata(response.metadata, "exact-token", str(tmp_path), "private-context-marker")


def test_vector_mode_uses_first_semantic_variant_and_reports_safe_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, vault_id = _indexed_service(tmp_path)
    candidate = _authoritative_candidate(service, vault_id)
    vector = StubVectorIndex(results=[candidate])
    service.vector_index = vector
    plan = RetrievalPlan(
        lexical_query="exact-token",
        semantic_variants=("semantic expansion", "unused expansion"),
        source_scopes=("vault_note",),
        requested_channels=("vector",),
        confidence=0.9,
        planner_source="validated_model",
    )
    monkeypatch.setattr("app.services.retrieval.build_retrieval_plan", lambda query, **kwargs: plan)

    response = service.search(vault_id=vault_id, query="exact-token", mode="vector")

    assert vector.search_calls[0]["query"] == "semantic expansion"
    assert response.results
    assert response.results[0].chunk_id == candidate.chunk_id
    assert response.results[0].retrieval_mode == "vector"
    assert response.metadata["requested_channels"] == ["vector"]
    assert response.metadata["completed_channels"] == ["vector"]
    assert response.metadata["effective_mode"] == "vector"
    assert response.metadata["fallback_reason"] is None
    assert response.metadata["retrieval_policy_version"] == "retrieval-policy.v1"
    assert response.metadata["privacy_policy_version"] == "privacy-v1"
    for key in (
        "semantic_available",
        "vector_available",
        "embedding_configured",
        "index_version",
        "active_generation",
        "last_sync_status",
        "unavailability_reason",
    ):
        assert key in response.metadata
    _assert_safe_metadata(
        response.metadata,
        "exact-token",
        "semantic expansion",
        "unused expansion",
        str(tmp_path),
        "private-context-marker",
    )


def test_hybrid_mode_completes_vector_and_fts_and_maps_knowledge_scope_for_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, vault_id = _indexed_service(tmp_path)
    candidate = _authoritative_candidate(service, vault_id)
    vector = StubVectorIndex(results=[candidate])
    service.vector_index = vector
    planner_calls: list[dict[str, object]] = []

    def capture_plan(query: str, **kwargs):
        planner_calls.append({"query": query, **kwargs})
        return real_build_retrieval_plan(query, **kwargs)

    monkeypatch.setattr("app.services.retrieval.build_retrieval_plan", capture_plan)

    response = service.search(
        vault_id=vault_id,
        query="exact-token",
        mode="hybrid",
        source_scope="knowledge_base",
    )

    assert planner_calls[0]["approved_source_scopes"] == ("wiki", "vault_note")
    assert planner_calls[0]["requested_channels"] == ("fts", "vector")
    assert response.metadata["retrieval_mode"] == "hybrid"
    assert response.metadata["requested_channels"] == ["fts", "vector"]
    assert response.metadata["completed_channels"] == ["vector", "fts"]
    assert response.metadata["effective_mode"] == "hybrid"
    assert response.results
    assert response.results[0].retrieval_mode == "vector"
    _assert_safe_metadata(response.metadata, "exact-token", str(tmp_path), "private-context-marker")


@pytest.mark.parametrize("reason", ["qdrant_unavailable", "embedding_provider_unavailable"])
def test_vector_failure_falls_back_to_exact_fts(tmp_path: Path, reason: str) -> None:
    service, vault_id = _indexed_service(tmp_path)
    vector = StubVectorIndex(search_error=VectorIndexUnavailableError(reason))
    service.vector_index = vector

    response = service.search(vault_id=vault_id, query="exact-token", mode="vector")

    assert response.results
    assert all(result.retrieval_mode == "fts" for result in response.results)
    assert response.metadata["retrieval_mode"] == "vector"
    assert response.metadata["effective_mode"] == "fts"
    assert response.metadata["requested_channels"] == ["vector"]
    assert response.metadata["completed_channels"] == ["fts"]
    assert response.metadata["fallback_reason"] == reason
    assert response.metadata["vector_available"] is False


@pytest.mark.parametrize(
    ("local_privacy", "query", "fallback_reason"),
    [
        (True, "exact-token", "local_privacy_mode"),
        (False, "SENSITIVE_QUERY_SENTINEL exact-token", "sensitive_content_blocked"),
    ],
)
def test_privacy_and_sensitive_queries_make_zero_vector_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_privacy: bool,
    query: str,
    fallback_reason: str,
) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.detect_sensitive_reason",
        lambda value: "sensitive_content" if "SENSITIVE_QUERY_SENTINEL" in value else None,
    )
    service, vault_id = _indexed_service(tmp_path)
    vector = StubVectorIndex(search_error=AssertionError("remote vector search must not run"))
    service.vector_index = vector
    _set_local_privacy(service, local_privacy)

    response = service.search(vault_id=vault_id, query=query, mode="vector")

    assert vector.search_calls == []
    assert response.metadata["completed_channels"] == ["fts"]
    assert response.metadata["effective_mode"] == "fts"
    assert response.metadata["fallback_reason"] == fallback_reason
    assert response.metadata["semantic_available"] is False
    assert response.metadata["vector_available"] is False


def test_invalid_retrieval_mode_is_rejected_without_silent_hybrid_fallback(tmp_path: Path) -> None:
    service, vault_id = _indexed_service(tmp_path)

    with pytest.raises(InvalidRetrievalModeError) as raised:
        service.search(vault_id=vault_id, query="exact-token", mode="automatic")

    assert raised.value.code == "invalid_retrieval_mode"

    with pytest.raises(ValidationError) as model_error:
        MemorySearchRequest(query="exact-token", mode="automatic")
    assert model_error.value.errors()[0]["type"] == "literal_error"


def test_invalid_retrieval_mode_returns_stable_api_validation(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "api-data") as client:
        response = client.post(
            "/api/memory/search",
            headers=auth_headers(),
            json={"query": "exact-token", "mode": "automatic"},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["details"]["errors"][0]["type"] == "literal_error"


def test_vector_candidates_are_rejected_when_not_authoritative_or_current(tmp_path: Path) -> None:
    service, vault_id = _indexed_service(tmp_path)
    candidate = _authoritative_candidate(service, vault_id)
    stale_candidates = [
        replace(candidate, content_hash="stale-content-hash"),
        replace(candidate, vault_id="foreign-vault"),
        replace(candidate, generation="previous-generation"),
        replace(candidate, chunk_id="missing-chunk"),
        replace(candidate, note_id="missing-note"),
        replace(candidate, relative_path="Missing.md"),
    ]
    vector = StubVectorIndex(results=stale_candidates)
    service.vector_index = vector

    response = service.search(vault_id=vault_id, query="exact-token", mode="vector")

    assert response.results
    assert all(result.retrieval_mode == "fts" for result in response.results)
    assert response.metadata["fallback_reason"] == "vector_candidates_rejected"
    assert response.metadata["completed_channels"] == ["vector", "fts"]


def test_vector_display_fields_are_projected_from_authoritative_sqlite(tmp_path: Path) -> None:
    service, vault_id = _indexed_service(tmp_path)
    candidate = replace(
        _authoritative_candidate(service, vault_id),
        title="UNTRUSTED_TITLE",
        heading="UNTRUSTED_HEADING",
        snippet="UNTRUSTED_SNIPPET",
    )
    service.vector_index = StubVectorIndex(results=[candidate])

    response = service.search(vault_id=vault_id, query="exact-token", mode="vector")

    assert response.results[0].title == "Memory"
    assert "exact-token semantic content" in response.results[0].snippet
    assert "UNTRUSTED" not in response.results[0].snippet


def test_rebuild_reconciles_only_after_sqlite_snapshot_and_vector_failure_does_not_break_fts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# Memory\n\nreconcile-token", encoding="utf-8")
    vector = StubVectorIndex(reconcile_status="failed")
    service = RetrievalService(Database(tmp_path / "app.db"), vector_index=vector)
    service.initialize()
    vault_id = service.bind_vault(str(vault))

    rebuild = service.rebuild_index(vault_id)
    response = service.search(vault_id=vault_id, query="reconcile-token", mode="fts")

    assert rebuild.status == "success"
    assert vector.reconcile_calls == [
        {
            "vault_id": vault_id,
            "local_privacy": False,
            "authoritative_chunk_count": 1,
        }
    ]
    assert response.results
    assert response.results[0].retrieval_mode == "fts"

    _set_local_privacy(service, True)
    service.reconcile_vector_index(vault_id)
    assert vector.reconcile_calls[-1]["local_privacy"] is True
