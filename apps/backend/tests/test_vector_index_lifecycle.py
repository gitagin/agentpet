from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from langchain_core.embeddings import Embeddings

qdrant_client = pytest.importorskip("qdrant_client")
QdrantClient = qdrant_client.QdrantClient
models = qdrant_client.models

from app.repositories.storage import NoteRepository, VaultRepository
import app.services.vector_index as vector_index_module
from app.services.vector_index import (
    LangChainQdrantVectorIndex,
    VectorIndexConfig,
    VectorIndexUnavailableError,
)
from app.storage.database import Database, MigrationRunner
from app.storage.markdown import parse_markdown


class FakeEmbeddings(Embeddings):
    def __init__(self, dimensions: int = 8) -> None:
        self.dimensions = dimensions
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        data = text.encode("utf-8") or b"\0"
        values = [float((data[index % len(data)] + index * 17) % 251 + 1) for index in range(self.dimensions)]
        return values


class PromotionFailingIndex(LangChainQdrantVectorIndex):
    fail_promotion = False

    def _promote_alias(self, vault_id: str, collection_name: str) -> None:
        if self.fail_promotion:
            raise VectorIndexUnavailableError("qdrant_unavailable")
        super()._promote_alias(vault_id, collection_name)


class PostCommitFailingIndex(LangChainQdrantVectorIndex):
    fail_after_promotion = False

    def _promote_alias(self, vault_id: str, collection_name: str) -> None:
        super()._promote_alias(vault_id, collection_name)
        if self.fail_after_promotion:
            raise VectorIndexUnavailableError("qdrant_unavailable")


def _database(tmp_path: Path) -> tuple[Database, object, str]:
    database = Database(tmp_path / "agent-pet.sqlite3")
    MigrationRunner(database).apply()
    conn = database.connect()
    vault_root = tmp_path / "Vault"
    vault_root.mkdir()
    with conn:
        vault_id = VaultRepository(conn).upsert(vault_root)
    return database, conn, vault_id


def _replace_note(conn, vault_id: str, relative_path: str, content: str) -> None:
    NoteRepository(conn).replace_note(
        vault_id=vault_id,
        relative_path=relative_path,
        markdown=parse_markdown(content, fallback_title=Path(relative_path).stem),
        modified_at=1.0,
    )


def _index(
    tmp_path: Path,
    client: QdrantClient,
    embeddings: FakeEmbeddings,
    *,
    model: str = "fake-embedding-v1",
    dimensions: int | None = None,
    chunker_version: str = "markdown-chunker.v1",
    cls=LangChainQdrantVectorIndex,
) -> LangChainQdrantVectorIndex:
    return cls(
        VectorIndexConfig(
            enabled=True,
            root_path=tmp_path / "unused-qdrant-path",
            collection_name="agent_pet_test_vectors",
            embedding_model=model,
            embeddings=embeddings,
            embedding_provider="deterministic-fake",
            embedding_dimensions=dimensions or embeddings.dimensions,
            normalization="l2",
            chunker_version=chunker_version,
            index_version="vector-index.v1",
            privacy_policy_version="embedding-privacy.v1",
            transport_class="remote-approved",
            embedding_configured=True,
            qdrant_client=client,
        )
    )


def _active_collection(client: QdrantClient) -> str:
    aliases = client.get_aliases().aliases
    assert len(aliases) == 1
    return str(aliases[0].collection_name)


def _records(client: QdrantClient, collection_name: str):
    records, offset = client.scroll(
        collection_name=collection_name,
        limit=100,
        with_payload=True,
        with_vectors=False,
    )
    assert offset is None
    return records


def test_server_generation_enables_hnsw_threshold_and_vault_payload_index(tmp_path: Path) -> None:
    class RecordingServerClient:
        def __init__(self) -> None:
            self.create_kwargs = None
            self.payload_index_kwargs = None

        def collection_exists(self, collection_name: str) -> bool:
            return False

        def create_collection(self, **kwargs) -> bool:
            self.create_kwargs = kwargs
            return True

        def create_payload_index(self, **kwargs):
            self.payload_index_kwargs = kwargs

    client = RecordingServerClient()
    index = _index(tmp_path, client, FakeEmbeddings())

    index._create_generation("server-generation", 8, {"lifecycle_status": "building"})

    assert client.create_kwargs["optimizers_config"].indexing_threshold == 1024
    assert client.payload_index_kwargs == {
        "collection_name": "server-generation",
        "field_name": "metadata.vault_id",
        "field_schema": models.PayloadSchemaType.KEYWORD,
        "wait": True,
    }


def test_reconcile_creates_validated_generation_and_is_unchanged_for_same_corpus(tmp_path: Path) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Alpha.md", "# Alpha\n\nsemantic lifecycle contract")
        assert conn.execute("SELECT COUNT(*) AS count FROM vector_chunks").fetchone()["count"] == 0
        client = QdrantClient(location=":memory:")
        embeddings = FakeEmbeddings()
        index = _index(tmp_path, client, embeddings)

        first = index.reconcile(conn, vault_id)

        assert first.status == "success"
        assert first.indexed_count == 1
        assert first.generation
        assert index.active_generation(vault_id) == first.generation
        physical = _active_collection(client)
        info = client.get_collection(physical)
        metadata = dict(info.config.metadata or {})
        assert metadata["lifecycle_status"] == "validated"
        assert metadata["embedding_provider"] == "deterministic-fake"
        assert metadata["embedding_dimensions"] == embeddings.dimensions
        assert metadata["normalization"] == "l2"
        assert metadata["chunker_version"] == "markdown-chunker.v1"
        assert metadata["index_version"] == "vector-index.v1"
        assert metadata["privacy_policy_version"] == "embedding-privacy.v1"
        assert metadata["transport_class"] == "remote-approved"
        assert metadata["corpus_version"] == "sqlite-note-chunks-v1"
        assert metadata["vault_identity"] != vault_id
        assert metadata["fingerprint"]

        record = _records(client, physical)[0]
        UUID(str(record.id))
        payload = record.payload["metadata"]
        authoritative_id = conn.execute(
            "SELECT id FROM note_chunks WHERE vault_id = ?",
            (vault_id,),
        ).fetchone()["id"]
        assert payload["authoritative_chunk_id"] == authoritative_id
        assert payload["content_hash"]
        assert payload["vault_id"] == vault_id
        assert payload["generation"] == first.generation
        mapping = conn.execute(
            "SELECT vector_id, chunk_id, collection_name FROM vector_chunks WHERE vault_id = ?",
            (vault_id,),
        ).fetchone()
        assert mapping["vector_id"] == str(record.id)
        assert mapping["chunk_id"] == authoritative_id
        assert mapping["collection_name"] == physical

        search = index.search(query="lifecycle", vault_id=vault_id, top_k=3)
        assert search[0].chunk_id == authoritative_id
        assert search[0].content_hash == payload["content_hash"]
        assert search[0].vault_id == vault_id
        assert search[0].generation == first.generation

        embed_call_count = len(embeddings.document_calls)
        second = index.reconcile(conn, vault_id)
        assert second.status == "unchanged"
        assert second.generation == first.generation
        assert index.active_generation(vault_id) == first.generation
        assert len(embeddings.document_calls) == embed_call_count

        health = index.health(vault_id)
        assert set(health) == {
            "semantic_available",
            "vector_available",
            "embedding_configured",
            "index_version",
            "active_generation",
            "last_sync_status",
            "unavailability_reason",
        }
        assert health["vector_available"] is True
        assert health["active_generation"] == first.generation
        assert health["unavailability_reason"] is None
    finally:
        conn.close()


def test_repeated_queries_do_not_repeat_full_generation_scroll_or_hash(tmp_path: Path, monkeypatch) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Alpha.md", "# Alpha\n\nrepeated validation contract")
        client = QdrantClient(location=":memory:")
        index = _index(tmp_path, client, FakeEmbeddings())
        assert index.reconcile(conn, vault_id).status == "success"

        scroll_calls = 0
        hash_calls = 0
        original_scroll = index._scroll_records
        original_records_hash = vector_index_module._records_hash

        def recording_scroll(collection_name):
            nonlocal scroll_calls
            scroll_calls += 1
            return original_scroll(collection_name)

        def recording_records_hash(records):
            nonlocal hash_calls
            hash_calls += 1
            return original_records_hash(records)

        monkeypatch.setattr(index, "_scroll_records", recording_scroll)
        monkeypatch.setattr(vector_index_module, "_records_hash", recording_records_hash)

        assert index.search(query="validation", vault_id=vault_id, top_k=3)
        first_scroll_calls = scroll_calls
        first_hash_calls = hash_calls
        assert first_scroll_calls == 1
        assert first_hash_calls == 1

        for _ in range(5):
            assert index.search(query="validation", vault_id=vault_id, top_k=3)

        assert scroll_calls == first_scroll_calls
        assert hash_calls == first_hash_calls
    finally:
        conn.close()


def test_first_reconcile_backfills_all_fts_chunks_and_keeps_duplicate_content_ids_distinct(tmp_path: Path) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        duplicate = "# Shared\n\nidentical duplicate body"
        _replace_note(conn, vault_id, "Wiki/First.md", duplicate)
        _replace_note(conn, vault_id, "Wiki/Second.md", duplicate)
        authoritative_ids = {
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM note_chunks WHERE vault_id = ?",
                (vault_id,),
            ).fetchall()
        }
        assert len(authoritative_ids) == 2
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM vector_chunks WHERE vault_id = ?",
            (vault_id,),
        ).fetchone()["count"] == 0

        client = QdrantClient(location=":memory:")
        embeddings = FakeEmbeddings()
        index = _index(tmp_path, client, embeddings)
        result = index.reconcile(conn, vault_id)

        assert result.status == "success"
        assert result.indexed_count == 2
        records = _records(client, _active_collection(client))
        point_ids = {str(record.id) for record in records}
        payload_chunk_ids = {
            str(record.payload["metadata"]["authoritative_chunk_id"])
            for record in records
        }
        assert len(point_ids) == 2
        assert payload_chunk_ids == authoritative_ids
        assert {
            str(row["chunk_id"])
            for row in conn.execute(
                "SELECT chunk_id FROM vector_chunks WHERE vault_id = ?",
                (vault_id,),
            ).fetchall()
        } == authoritative_ids
        assert len([text for call in embeddings.document_calls for text in call]) == 2
    finally:
        conn.close()


def test_reconcile_update_delete_and_prune_never_serve_stale_active_points(tmp_path: Path) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Changing.md", "# Old\n\nobsolete-vector-content")
        client = QdrantClient(location=":memory:")
        index = _index(tmp_path, client, FakeEmbeddings())
        first = index.reconcile(conn, vault_id)
        old_collection = _active_collection(client)
        old_point_ids = {str(record.id) for record in _records(client, old_collection)}

        _replace_note(conn, vault_id, "Wiki/Changing.md", "# New\n\nfresh-vector-content")
        updated = index.reconcile(conn, vault_id)
        new_collection = _active_collection(client)
        new_records = _records(client, new_collection)

        assert updated.status == "success"
        assert updated.generation != first.generation
        assert new_collection != old_collection
        assert client.collection_exists(old_collection)
        assert old_point_ids.isdisjoint({str(record.id) for record in new_records})
        assert all("obsolete-vector-content" not in record.payload["page_content"] for record in new_records)
        assert any("fresh-vector-content" in record.payload["page_content"] for record in new_records)

        NoteRepository(conn).mark_deleted(vault_id=vault_id, relative_path="Wiki/Changing.md")
        deleted = index.reconcile(conn, vault_id)
        empty_collection = _active_collection(client)
        assert deleted.status == "success"
        assert deleted.indexed_count == 0
        assert empty_collection != new_collection
        assert client.count(empty_collection, exact=True).count == 0
        assert index.search(query="obsolete-vector-content", vault_id=vault_id, top_k=3) == []
        assert conn.execute(
            "SELECT COUNT(*) AS count FROM vector_chunks WHERE vault_id = ?",
            (vault_id,),
        ).fetchone()["count"] == 0
        assert not client.collection_exists(old_collection)
        assert client.collection_exists(new_collection)

        removed = index.prune(vault_id, keep=0)
        assert new_collection in removed
        assert client.collection_exists(empty_collection)
    finally:
        conn.close()


def test_failed_generation_promotion_preserves_previous_active_and_fails_closed(tmp_path: Path) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Stable.md", "# Stable\n\nprevious-valid-generation")
        client = QdrantClient(location=":memory:")
        index = _index(tmp_path, client, FakeEmbeddings(), cls=PromotionFailingIndex)
        first = index.reconcile(conn, vault_id)
        previous_collection = _active_collection(client)

        _replace_note(conn, vault_id, "Wiki/Stable.md", "# Changed\n\nnew-generation-that-must-fail")
        index.fail_promotion = True
        failed = index.reconcile(conn, vault_id)

        assert failed.status == "failed"
        assert failed.previous_generation == first.generation
        assert index.active_generation(vault_id) == first.generation
        assert _active_collection(client) == previous_collection
        assert client.collection_exists(previous_collection)
        assert len(client.get_collections().collections) == 1
        with pytest.raises(VectorIndexUnavailableError):
            index.search(query="previous", vault_id=vault_id, top_k=3)

        index.fail_promotion = False
        recovered = index.reconcile(conn, vault_id)
        assert recovered.status == "success"
        assert recovered.generation != first.generation
        assert index.health(vault_id)["vector_available"] is True
    finally:
        conn.close()


def test_post_commit_alias_error_restores_previous_generation(tmp_path: Path) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Stable.md", "# Stable\n\nprevious-generation")
        client = QdrantClient(location=":memory:")
        index = _index(tmp_path, client, FakeEmbeddings(), cls=PostCommitFailingIndex)
        first = index.reconcile(conn, vault_id)
        previous_collection = _active_collection(client)

        _replace_note(conn, vault_id, "Wiki/Stable.md", "# Changed\n\nambiguous-promotion")
        index.fail_after_promotion = True
        failed = index.reconcile(conn, vault_id)

        assert failed.status == "failed"
        assert index.active_generation(vault_id) == first.generation
        assert _active_collection(client) == previous_collection
        assert [str(item.name) for item in client.get_collections().collections] == [previous_collection]
    finally:
        conn.close()


def test_generation_cleanup_protects_true_previous_active_over_newer_orphan(tmp_path: Path) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Stable.md", "# Stable\n\nfirst-generation")
        client = QdrantClient(location=":memory:")
        index = _index(tmp_path, client, FakeEmbeddings())
        index.reconcile(conn, vault_id)
        previous_collection = _active_collection(client)
        orphan_collection = index._generation_collection(vault_id, "f" * 32)
        client.create_collection(
            collection_name=orphan_collection,
            vectors_config=models.VectorParams(size=8, distance=models.Distance.COSINE),
            metadata={"created_at": "9999-01-01T00:00:00+00:00", "lifecycle_status": "building"},
        )

        _replace_note(conn, vault_id, "Wiki/Stable.md", "# Stable\n\nsecond-generation")
        result = index.reconcile(conn, vault_id)

        assert result.status == "success"
        assert client.collection_exists(previous_collection)
        assert not client.collection_exists(orphan_collection)
    finally:
        conn.close()


@pytest.mark.parametrize("drift_kind", ["model", "dimensions", "chunker"])
def test_config_fingerprint_drift_fails_closed_then_rebuilds(tmp_path: Path, drift_kind: str) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Drift.md", "# Drift\n\nmodel fingerprint and corruption")
        client = QdrantClient(location=":memory:")
        first_index = _index(tmp_path, client, FakeEmbeddings(), model="fake-model-a")
        first = first_index.reconcile(conn, vault_id)

        model = "fake-model-b" if drift_kind == "model" else "fake-model-a"
        dimensions = 12 if drift_kind == "dimensions" else 8
        chunker_version = "markdown-chunker.v2" if drift_kind == "chunker" else "markdown-chunker.v1"
        drift_embeddings = FakeEmbeddings(dimensions=dimensions)
        drifted = _index(
            tmp_path,
            client,
            drift_embeddings,
            model=model,
            dimensions=dimensions,
            chunker_version=chunker_version,
        )
        drift_health = drifted.health(vault_id)
        assert drift_health["vector_available"] is False
        assert drift_health["unavailability_reason"] == "index_drift"
        query_calls = len(drift_embeddings.query_calls)
        with pytest.raises(VectorIndexUnavailableError, match="index_drift"):
            drifted.search(query="fingerprint", vault_id=vault_id, top_k=3)
        assert len(drift_embeddings.query_calls) == query_calls

        rebuilt = drifted.reconcile(conn, vault_id)
        assert rebuilt.status == "success"
        assert rebuilt.generation != first.generation
        assert drifted.health(vault_id)["vector_available"] is True
    finally:
        conn.close()


def test_payload_tamper_fails_closed_then_recovers_with_new_generation(tmp_path: Path) -> None:
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Corrupt.md", "# Corrupt\n\npoint count corruption")
        client = QdrantClient(location=":memory:")
        index = _index(tmp_path, client, FakeEmbeddings())
        built = index.reconcile(conn, vault_id)
        physical = _active_collection(client)
        point_id = _records(client, physical)[0].id
        client.set_payload(
            collection_name=physical,
            payload={"page_content": "tampered-content"},
            points=[point_id],
            wait=True,
        )

        corrupt_health = index.health(vault_id)
        assert corrupt_health["vector_available"] is False
        assert corrupt_health["unavailability_reason"] == "index_corrupt"
        with pytest.raises(VectorIndexUnavailableError, match="index_corrupt"):
            index.search(query="corruption", vault_id=vault_id, top_k=3)

        recovered = index.reconcile(conn, vault_id)
        assert recovered.status == "success"
        assert recovered.generation != built.generation
        assert index.health(vault_id)["vector_available"] is True
    finally:
        conn.close()


def test_qdrant_health_failure_is_not_reported_as_unbuilt(tmp_path: Path) -> None:
    class BrokenQdrantClient:
        def get_aliases(self):
            raise OSError("unavailable")

    index = _index(tmp_path, BrokenQdrantClient(), FakeEmbeddings())

    health = index.health("vault-1")

    assert health["vector_available"] is False
    assert health["last_sync_status"] == "failed"
    assert health["unavailability_reason"] == "qdrant_unavailable"


def test_remote_privacy_filters_content_and_blocks_queries_before_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.vector_index.evaluate_memory_content",
        lambda text: SimpleNamespace(allowed="SENSITIVE_SENTINEL" not in text),
    )
    _, conn, vault_id = _database(tmp_path)
    try:
        _replace_note(conn, vault_id, "Wiki/Safe.md", "# Safe\n\nordinary searchable knowledge")
        _replace_note(conn, vault_id, "Inbox/Pending.md", "# Pending\n\npending-private-text")
        _replace_note(conn, vault_id, ".hidden/Private.md", "# Hidden\n\nhidden-private-text")
        _replace_note(conn, vault_id, "2026/05/第1周/星期一/2026-05-04.md", "# Legacy\n\nlegacy-private-text")
        _replace_note(conn, vault_id, "Wiki/Secret.md", "# Secret\n\nSENSITIVE_SENTINEL document")
        client = QdrantClient(location=":memory:")
        embeddings = FakeEmbeddings()
        index = _index(tmp_path, client, embeddings)

        result = index.reconcile(conn, vault_id)

        assert result.status == "success"
        assert result.indexed_count == 1
        assert result.excluded_count == 4
        embedded_text = "\n".join(text for call in embeddings.document_calls for text in call)
        assert "ordinary searchable knowledge" in embedded_text
        assert "pending-private-text" not in embedded_text
        assert "hidden-private-text" not in embedded_text
        assert "legacy-private-text" not in embedded_text
        assert "SENSITIVE_SENTINEL" not in embedded_text

        query_calls = len(embeddings.query_calls)
        with pytest.raises(VectorIndexUnavailableError, match="sensitive_content_blocked"):
            index.search(query="SENSITIVE_SENTINEL query", vault_id=vault_id, top_k=3)
        assert len(embeddings.query_calls) == query_calls
        with pytest.raises(VectorIndexUnavailableError, match="local_privacy_mode"):
            index.search(query="ordinary query", vault_id=vault_id, top_k=3, local_privacy=True)
        assert len(embeddings.query_calls) == query_calls

        document_calls = len(embeddings.document_calls)
        blocked = index.reconcile(conn, vault_id, local_privacy=True)
        assert blocked.status == "blocked"
        assert blocked.reason == "local_privacy_mode"
        assert len(embeddings.document_calls) == document_calls
    finally:
        conn.close()
