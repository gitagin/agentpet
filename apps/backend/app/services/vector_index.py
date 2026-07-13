from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.repositories.storage import SearchResult
from app.services.memory_policy import evaluate_memory_content
from app.storage.markdown import ParsedMarkdown
from app.utils.hash import sha256_hex


logger = logging.getLogger(__name__)

_INDEX_VERSION = "qdrant-generation-v1"
_CORPUS_VERSION = "sqlite-note-chunks-v1"
_CHUNKER_VERSION = "markdown-chunker-v1"
_NORMALIZATION = "l2-v1"
_ALIAS_PREFIX = "agent_pet_vector"
_POINT_NAMESPACE = uuid5(NAMESPACE_URL, "agent-pet/vector-points/v1")
_BATCH_SIZE = 64
_SAFE_REASONS = {
    "active_generation_missing",
    "credential_store_unavailable",
    "embedding_api_key_missing",
    "embedding_configuration_unavailable",
    "embedding_dimension_mismatch",
    "embedding_dimensions_unknown",
    "embedding_initialization_failed",
    "embedding_not_configured",
    "embedding_provider_unavailable",
    "embedding_provider_unsupported",
    "index_corrupt",
    "index_drift",
    "index_not_built",
    "local_privacy_mode",
    "local_privacy_remote_blocked",
    "qdrant_unavailable",
    "sensitive_content_blocked",
    "sync_failed",
    "vector_disabled",
}


@dataclass(frozen=True)
class VectorIndexConfig:
    enabled: bool
    root_path: Path
    collection_name: str
    embedding_model: str
    embeddings: Any | None = None
    unavailable_reason: str | None = None
    embedding_provider: str = "openai-compatible"
    embedding_dimensions: int | None = None
    normalization: str = _NORMALIZATION
    chunker_version: str = _CHUNKER_VERSION
    index_version: str = _INDEX_VERSION
    privacy_policy_version: str = "privacy-v1"
    transport_class: str = "remote"
    embedding_configured: bool | None = None
    corpus_version: str = _CORPUS_VERSION
    qdrant_client: Any | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class VectorSyncResult:
    status: str
    generation: str | None = None
    previous_generation: str | None = None
    indexed_count: int = 0
    excluded_count: int = 0
    corpus_hash: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _SnapshotChunk:
    chunk_id: str
    note_id: str
    vault_id: str
    relative_path: str
    title: str
    heading: str | None
    content: str
    content_hash: str

    @property
    def point_id(self) -> str:
        return str(uuid5(_POINT_NAMESPACE, self.chunk_id))


class VectorIndexUnavailableError(Exception):
    def __init__(self, reason: str = "qdrant_unavailable") -> None:
        self.reason = _safe_reason(reason)
        super().__init__(self.reason)


class VectorChunkRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def replace_note_vectors(
        self,
        *,
        vault_id: str,
        relative_path: str,
        note_id: str,
        chunks: ParsedMarkdown,
        collection_name: str,
        embedding_model: str,
    ) -> list[str]:
        self.conn.execute(
            "DELETE FROM vector_chunks WHERE vault_id = ? AND relative_path = ?",
            (vault_id, relative_path),
        )
        vector_ids: list[str] = []
        for chunk in chunks.chunks:
            vector_id = _vector_id(
                vault_id,
                relative_path,
                chunk.content_hash,
                collection_name,
                embedding_model,
            )
            vector_ids.append(vector_id)
            self.conn.execute(
                """
                INSERT INTO vector_chunks (
                    vector_id, chunk_id, note_id, vault_id, relative_path, content_hash,
                    collection_name, embedding_model, created_at, updated_at
                )
                SELECT ?, note_chunks.id, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now')
                FROM note_chunks
                WHERE note_chunks.note_id = ?
                  AND note_chunks.vault_id = ?
                  AND note_chunks.relative_path = ?
                  AND note_chunks.chunk_index = ?
                LIMIT 1
                """,
                (
                    vector_id,
                    note_id,
                    vault_id,
                    relative_path,
                    chunk.content_hash,
                    collection_name,
                    embedding_model,
                    note_id,
                    vault_id,
                    relative_path,
                    chunk.index,
                ),
            )
        return vector_ids

    def replace_vault_vectors(
        self,
        *,
        vault_id: str,
        chunks: Sequence[_SnapshotChunk],
        collection_name: str,
        embedding_model: str,
    ) -> list[str]:
        point_ids = [chunk.point_id for chunk in chunks]
        with self.conn:
            self.conn.execute("DELETE FROM vector_chunks WHERE vault_id = ?", (vault_id,))
            self.conn.executemany(
                """
                INSERT INTO vector_chunks (
                    vector_id, chunk_id, note_id, vault_id, relative_path, content_hash,
                    collection_name, embedding_model, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                [
                    (
                        chunk.point_id,
                        chunk.chunk_id,
                        chunk.note_id,
                        vault_id,
                        chunk.relative_path,
                        chunk.content_hash,
                        collection_name,
                        embedding_model,
                    )
                    for chunk in chunks
                ],
            )
        return point_ids

    def delete_note_vectors(self, *, vault_id: str, relative_path: str) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT vector_id
            FROM vector_chunks
            WHERE vault_id = ? AND relative_path = ?
            """,
            (vault_id, relative_path),
        ).fetchall()
        self.conn.execute(
            "DELETE FROM vector_chunks WHERE vault_id = ? AND relative_path = ?",
            (vault_id, relative_path),
        )
        return [str(row["vector_id"]) for row in rows]


class LangChainQdrantVectorIndex:
    def __init__(self, config: VectorIndexConfig, *, client: Any | None = None) -> None:
        self.config = config
        self._client = client or config.qdrant_client
        self._owns_client = self._client is None
        self._lock = threading.RLock()
        self._last_sync: dict[str, VectorSyncResult] = {}
        self._blocked_vaults: dict[str, str] = {}

    @property
    def available(self) -> bool:
        configured = self.config.embedding_configured
        return (
            self.config.enabled
            and self.config.embeddings is not None
            and configured is not False
        )

    def reconcile(
        self,
        conn: sqlite3.Connection,
        vault_id: str,
        *,
        local_privacy: bool = False,
    ) -> VectorSyncResult:
        with self._lock:
            if not self.available:
                return self._record_sync(
                    vault_id,
                    VectorSyncResult(status="unavailable", reason=self._configuration_reason()),
                )
            if local_privacy and self._uses_remote_embeddings:
                return self._record_sync(
                    vault_id,
                    VectorSyncResult(status="blocked", reason="local_privacy_mode"),
                )

            all_chunks = self._snapshot(conn, vault_id)
            chunks = [chunk for chunk in all_chunks if self._eligible_for_remote_embedding(chunk)]
            excluded_count = len(all_chunks) - len(chunks)
            corpus_hash = _snapshot_hash(chunks)
            previous_collection: str | None = None
            previous_generation: str | None = None

            try:
                previous_collection = self._active_collection(vault_id)
                previous_generation = self._generation_for_collection(previous_collection)
                active_metadata = self._collection_metadata(previous_collection)
                candidate_dimensions = self._configured_dimensions()
                if candidate_dimensions is None and active_metadata is not None:
                    candidate_dimensions = _positive_int(active_metadata.get("embedding_dimensions"))
                if previous_collection and candidate_dimensions:
                    expected = self._metadata(
                        vault_id=vault_id,
                        generation=str(active_metadata.get("generation") or "") if active_metadata else "",
                        dimensions=candidate_dimensions,
                        corpus_hash=corpus_hash,
                        point_count=len(chunks),
                    )
                    if active_metadata and self._validate_collection(previous_collection, expected, chunks):
                        VectorChunkRepository(conn).replace_vault_vectors(
                            vault_id=vault_id,
                            chunks=chunks,
                            collection_name=previous_collection,
                            embedding_model=self.config.embedding_model,
                        )
                        self._blocked_vaults.pop(vault_id, None)
                        return self._record_sync(
                            vault_id,
                            VectorSyncResult(
                                status="unchanged",
                                generation=previous_generation,
                                previous_generation=previous_generation,
                                indexed_count=len(chunks),
                                excluded_count=excluded_count,
                                corpus_hash=corpus_hash,
                            ),
                        )

                vectors, dimensions = self._embed_snapshot(chunks, candidate_dimensions)
                generation = uuid4().hex
                collection_name = self._generation_collection(vault_id, generation)
                metadata = self._metadata(
                    vault_id=vault_id,
                    generation=generation,
                    dimensions=dimensions,
                    corpus_hash=corpus_hash,
                    point_count=len(chunks),
                )
                building_metadata = dict(metadata)
                building_metadata["lifecycle_status"] = "building"
                self._create_generation(collection_name, dimensions, building_metadata)
                try:
                    self._upsert_generation(collection_name, chunks, vectors, generation)
                    if not self._validate_collection(collection_name, building_metadata, chunks):
                        raise VectorIndexUnavailableError("index_corrupt")
                    self._update_collection_metadata(collection_name, metadata)
                    if not self._validate_collection(collection_name, metadata, chunks):
                        raise VectorIndexUnavailableError("index_corrupt")
                    self._promote_alias(vault_id, collection_name)
                    try:
                        VectorChunkRepository(conn).replace_vault_vectors(
                            vault_id=vault_id,
                            chunks=chunks,
                            collection_name=collection_name,
                            embedding_model=self.config.embedding_model,
                        )
                    except Exception:
                        self._restore_alias(vault_id, previous_collection)
                        raise
                except Exception:
                    self._rollback_failed_candidate(
                        vault_id=vault_id,
                        candidate_collection=collection_name,
                        previous_collection=previous_collection,
                    )
                    raise

                self._blocked_vaults.pop(vault_id, None)
                try:
                    self.prune(
                        vault_id,
                        keep=0,
                        protected_collections=(previous_collection,) if previous_collection else (),
                    )
                except Exception:
                    logger.warning(
                        "Old vector generation cleanup deferred",
                        extra={"vault_id": vault_id},
                    )
                return self._record_sync(
                    vault_id,
                    VectorSyncResult(
                        status="success",
                        generation=generation,
                        previous_generation=previous_generation,
                        indexed_count=len(chunks),
                        excluded_count=excluded_count,
                        corpus_hash=corpus_hash,
                    ),
                )
            except Exception as exc:
                reason = exc.reason if isinstance(exc, VectorIndexUnavailableError) else "sync_failed"
                self._blocked_vaults[vault_id] = _safe_reason(reason)
                logger.warning(
                    "Vector generation reconcile failed",
                    extra={"vault_id": vault_id, "reason": _safe_reason(reason), "error_type": type(exc).__name__},
                )
                return self._record_sync(
                    vault_id,
                    VectorSyncResult(
                        status="failed",
                        previous_generation=previous_generation,
                        indexed_count=0,
                        excluded_count=excluded_count,
                        corpus_hash=corpus_hash,
                        reason=_safe_reason(reason),
                    ),
                )

    def search(
        self,
        *,
        query: str,
        vault_id: str,
        top_k: int,
        local_privacy: bool = False,
    ) -> list[SearchResult]:
        if not self.available:
            raise VectorIndexUnavailableError(self._configuration_reason())
        if self._uses_remote_embeddings and local_privacy:
            raise VectorIndexUnavailableError("local_privacy_mode")
        if self._uses_remote_embeddings and not evaluate_memory_content(query).allowed:
            raise VectorIndexUnavailableError("sensitive_content_blocked")
        if vault_id in self._blocked_vaults:
            raise VectorIndexUnavailableError(self._blocked_vaults[vault_id])

        with self._lock:
            collection_name = self._active_alias(vault_id)
            physical = self._active_collection(vault_id)
            if physical is None:
                raise VectorIndexUnavailableError("index_not_built")
            metadata = self._collection_metadata(physical)
            if metadata is None or not self._metadata_matches_config(metadata, vault_id):
                self._blocked_vaults[vault_id] = "index_drift"
                raise VectorIndexUnavailableError("index_drift")
            if not self._validate_collection_from_metadata(physical, metadata):
                self._blocked_vaults[vault_id] = "index_corrupt"
                raise VectorIndexUnavailableError("index_corrupt")

            vector = self._embed_query(query)
            dimensions = _positive_int(metadata.get("embedding_dimensions"))
            if dimensions is None or len(vector) != dimensions:
                raise VectorIndexUnavailableError("embedding_dimension_mismatch")
            vector = _normalize_vector(vector, self.config.normalization)
            try:
                from qdrant_client import models

                response = self._client_instance().query_points(
                    collection_name=collection_name,
                    query=vector,
                    query_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="metadata.vault_id",
                                match=models.MatchValue(value=vault_id),
                            )
                        ]
                    ),
                    limit=max(0, top_k),
                    with_payload=True,
                    with_vectors=False,
                )
            except VectorIndexUnavailableError:
                raise
            except Exception as exc:
                logger.warning(
                    "Vector query failed",
                    extra={"vault_id": vault_id, "error_type": type(exc).__name__},
                )
                raise VectorIndexUnavailableError("qdrant_unavailable") from exc

            results: list[SearchResult] = []
            for point in response.points:
                payload = point.payload or {}
                metadata_payload = payload.get("metadata") or {}
                if metadata_payload.get("vault_id") != vault_id:
                    continue
                authoritative_chunk_id = str(metadata_payload.get("authoritative_chunk_id") or "")
                content_hash = str(metadata_payload.get("content_hash") or "")
                generation = str(metadata_payload.get("generation") or "")
                if (
                    not authoritative_chunk_id
                    or not content_hash
                    or not generation
                    or generation != str(metadata.get("generation") or "")
                ):
                    continue
                results.append(
                    SearchResult(
                        note_id=str(metadata_payload.get("note_id") or ""),
                        chunk_id=authoritative_chunk_id,
                        relative_path=str(metadata_payload.get("relative_path") or ""),
                        title=str(metadata_payload.get("title") or ""),
                        heading=str(metadata_payload.get("heading") or "") or None,
                        snippet=str(payload.get("page_content") or "")[:600],
                        score=float(point.score),
                        content_hash=content_hash,
                        vault_id=vault_id,
                        generation=generation,
                    )
                )
            return [result for result in results if result.relative_path]

    def health(self, vault_id: str | None = None, *, deep: bool = True) -> dict[str, object]:
        embedding_configured = (
            self.config.embedding_configured
            if self.config.embedding_configured is not None
            else bool(self.config.enabled and self.config.embeddings is not None)
        )
        reason: str | None = None
        generation: str | None = None
        vector_available = False
        status = "not_built"

        if not self.config.enabled:
            reason = self._configuration_reason()
            status = "unavailable"
        elif not embedding_configured:
            reason = self._configuration_reason()
            status = "unavailable"
        elif self.config.embeddings is None:
            reason = "embedding_initialization_failed"
            status = "unavailable"
        else:
            try:
                collections = self._active_collections(vault_id)
                valid: list[tuple[str, dict[str, object]]] = []
                for physical in collections:
                    metadata = self._collection_metadata(physical)
                    metadata_matches = (
                        metadata is not None
                        and self._metadata_matches_config(metadata, vault_id)
                        if vault_id is not None
                        else metadata is not None and self._metadata_matches_config_fields(metadata)
                    )
                    if not metadata_matches:
                        reason = "index_drift"
                        continue
                    valid_collection = (
                        self._validate_collection_from_metadata(physical, metadata)
                        if deep
                        else self._validate_collection_count(physical, metadata)
                    )
                    if metadata is None or not valid_collection:
                        if reason is None:
                            reason = "index_corrupt"
                        continue
                    valid.append((physical, metadata))
                if collections and len(valid) != len(collections):
                    reason = reason or "index_corrupt"
                    status = "failed"
                elif valid:
                    vector_available = True
                    status = "ready"
                    if len(valid) == 1:
                        generation = str(valid[0][1].get("generation") or "") or None
                else:
                    reason = "index_not_built"
            except Exception:
                reason = "qdrant_unavailable"
                status = "failed"

        if vault_id and vault_id in self._blocked_vaults:
            vector_available = False
            reason = self._blocked_vaults[vault_id]
            status = "failed"
        if vault_id and vault_id in self._last_sync and status not in {"failed", "unavailable"}:
            status = self._last_sync[vault_id].status

        return {
            "semantic_available": bool(vector_available and embedding_configured),
            "vector_available": vector_available,
            "embedding_configured": embedding_configured,
            "index_version": self.config.index_version,
            "active_generation": generation,
            "last_sync_status": status,
            "unavailability_reason": _safe_reason(reason) if reason else None,
        }

    def active_generation(self, vault_id: str | None = None) -> str | None:
        collections = self._active_collections(vault_id)
        if len(collections) != 1:
            return None
        return self._generation_for_collection(collections[0])

    def prune(
        self,
        vault_id: str,
        *,
        keep: int = 1,
        protected_collections: Iterable[str] = (),
    ) -> list[str]:
        with self._lock:
            client = self._client_instance()
            active = self._active_collection(vault_id)
            prefix = self._generation_prefix(vault_id)
            protected = {name for name in protected_collections if name}
            candidates: list[tuple[str, str]] = []
            for collection in client.get_collections().collections:
                name = str(collection.name)
                if name == active or name in protected or not name.startswith(prefix):
                    continue
                metadata = self._collection_metadata(name) or {}
                candidates.append((str(metadata.get("created_at") or ""), name))
            candidates.sort(reverse=True)
            removed: list[str] = []
            for _, name in candidates[max(0, keep) :]:
                if self._delete_collection(name):
                    removed.append(name)
            return removed

    def upsert_markdown(
        self,
        *,
        vault_id: str,
        note_id: str,
        relative_path: str,
        markdown: ParsedMarkdown,
    ) -> list[str]:
        """Compatibility path; generation-safe callers should use ``reconcile``."""
        if not self.available:
            return []
        eligible = [
            chunk
            for chunk in markdown.chunks
            if _path_allowed(relative_path)
            and (not self._uses_remote_embeddings or evaluate_memory_content(chunk.content).allowed)
        ]
        ids = [
            _vector_id(
                vault_id,
                relative_path,
                chunk.content_hash,
                self.config.collection_name,
                self.config.embedding_model,
            )
            for chunk in eligible
        ]
        if not ids:
            return []
        store = self._store()
        try:
            store.delete(ids=ids)
        except Exception:
            logger.exception(
                "Vector index delete failed before upsert",
                extra={"vault_id": vault_id, "relative_path": relative_path, "vector_count": len(ids)},
            )
            raise
        documents = []
        for chunk, vector_id in zip(eligible, ids):
            documents.append(
                self._document(
                    page_content=chunk.content,
                    metadata={
                        "vault_id": vault_id,
                        "note_id": note_id,
                        "relative_path": relative_path,
                        "title": markdown.title,
                        "heading": chunk.heading or "",
                        "chunk_hash": chunk.content_hash,
                        "vector_id": vector_id,
                    },
                )
            )
        store.add_documents(documents=documents, ids=ids)
        return ids

    def delete(self, ids: Iterable[str]) -> None:
        id_list = [item for item in ids if item]
        if not self.available or not id_list:
            return
        self._store().delete(ids=id_list)

    def close(self) -> None:
        with self._lock:
            client = self._client
            if self._owns_client and client is not None and hasattr(client, "close"):
                client.close()
            self._client = None

    def _snapshot(self, conn: sqlite3.Connection, vault_id: str) -> list[_SnapshotChunk]:
        rows = conn.execute(
            """
            SELECT
                note_chunks.id AS chunk_id,
                note_chunks.note_id,
                note_chunks.vault_id,
                note_chunks.relative_path,
                note_chunks.title,
                note_chunks.heading,
                note_chunks.content,
                note_chunks.content_hash
            FROM note_chunks
            JOIN notes ON notes.id = note_chunks.note_id
            WHERE note_chunks.vault_id = ?
              AND notes.vault_id = note_chunks.vault_id
              AND notes.status = 'indexed'
            ORDER BY note_chunks.relative_path, note_chunks.chunk_index, note_chunks.id
            """,
            (vault_id,),
        ).fetchall()
        return [
            _SnapshotChunk(
                chunk_id=str(row["chunk_id"]),
                note_id=str(row["note_id"]),
                vault_id=str(row["vault_id"]),
                relative_path=str(row["relative_path"]),
                title=str(row["title"]),
                heading=str(row["heading"]) if row["heading"] is not None else None,
                content=str(row["content"]),
                content_hash=str(row["content_hash"]),
            )
            for row in rows
        ]

    def _eligible_for_remote_embedding(self, chunk: _SnapshotChunk) -> bool:
        if not _path_allowed(chunk.relative_path):
            return False
        return not self._uses_remote_embeddings or evaluate_memory_content(chunk.content).allowed

    def _embed_snapshot(
        self,
        chunks: Sequence[_SnapshotChunk],
        expected_dimensions: int | None,
    ) -> tuple[list[list[float]], int]:
        if not chunks:
            if expected_dimensions is None:
                raise VectorIndexUnavailableError("embedding_dimensions_unknown")
            return [], expected_dimensions
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[start : start + _BATCH_SIZE]
            try:
                raw = self.config.embeddings.embed_documents([chunk.content for chunk in batch])
            except Exception as exc:
                raise VectorIndexUnavailableError("embedding_provider_unavailable") from exc
            vectors.extend([_normalize_vector(vector, self.config.normalization) for vector in raw])
        dimensions = len(vectors[0]) if vectors else 0
        if dimensions <= 0 or any(len(vector) != dimensions for vector in vectors):
            raise VectorIndexUnavailableError("embedding_dimension_mismatch")
        if expected_dimensions is not None and dimensions != expected_dimensions:
            raise VectorIndexUnavailableError("embedding_dimension_mismatch")
        return vectors, dimensions

    def _embed_query(self, query: str) -> list[float]:
        try:
            return [float(value) for value in self.config.embeddings.embed_query(query)]
        except Exception as exc:
            raise VectorIndexUnavailableError("embedding_provider_unavailable") from exc

    def _create_generation(self, collection_name: str, dimensions: int, metadata: dict[str, object]) -> None:
        try:
            from qdrant_client import models

            client = self._client_instance()
            if client.collection_exists(collection_name):
                client.delete_collection(collection_name)
            created = client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
                metadata=metadata,
            )
            if not created:
                raise VectorIndexUnavailableError("qdrant_unavailable")
        except VectorIndexUnavailableError:
            raise
        except Exception as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc

    def _upsert_generation(
        self,
        collection_name: str,
        chunks: Sequence[_SnapshotChunk],
        vectors: Sequence[Sequence[float]],
        generation: str,
    ) -> None:
        if len(chunks) != len(vectors):
            raise VectorIndexUnavailableError("embedding_dimension_mismatch")
        try:
            from qdrant_client import models

            client = self._client_instance()
            for start in range(0, len(chunks), _BATCH_SIZE):
                points = []
                for chunk, vector in zip(
                    chunks[start : start + _BATCH_SIZE],
                    vectors[start : start + _BATCH_SIZE],
                ):
                    points.append(
                        models.PointStruct(
                            id=chunk.point_id,
                            vector=list(vector),
                            payload={
                                "page_content": chunk.content,
                                "metadata": {
                                    "authoritative_chunk_id": chunk.chunk_id,
                                    "content_hash": chunk.content_hash,
                                    "vault_id": chunk.vault_id,
                                    "note_id": chunk.note_id,
                                    "relative_path": chunk.relative_path,
                                    "title": chunk.title,
                                    "heading": chunk.heading or "",
                                    "generation": generation,
                                },
                            },
                        )
                    )
                if points:
                    client.upsert(collection_name=collection_name, points=points, wait=True)
        except Exception as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc

    def _validate_collection(
        self,
        collection_name: str,
        expected_metadata: dict[str, object],
        chunks: Sequence[_SnapshotChunk],
    ) -> bool:
        metadata = self._collection_metadata(collection_name)
        compared_keys = set(expected_metadata) - {"created_at"}
        if metadata is None or any(metadata.get(key) != expected_metadata[key] for key in compared_keys):
            return False
        if not self._validate_collection_from_metadata(collection_name, metadata):
            return False
        records = self._scroll_records(collection_name)
        expected = {
            chunk.point_id: (chunk.chunk_id, chunk.content_hash, chunk.vault_id)
            for chunk in chunks
        }
        actual: dict[str, tuple[str, str, str]] = {}
        generation = str(expected_metadata["generation"])
        for record in records:
            payload = record.payload or {}
            item = payload.get("metadata") or {}
            if str(item.get("generation") or "") != generation:
                return False
            actual[str(record.id)] = (
                str(item.get("authoritative_chunk_id") or ""),
                str(item.get("content_hash") or ""),
                str(item.get("vault_id") or ""),
            )
        return actual == expected

    def _validate_collection_from_metadata(
        self,
        collection_name: str,
        metadata: dict[str, object],
    ) -> bool:
        try:
            if not metadata.get("fingerprint") or not metadata.get("generation"):
                return False
            expected_count = _nonnegative_int(metadata.get("point_count"))
            if expected_count is None:
                return False
            client = self._client_instance()
            if client.count(collection_name=collection_name, exact=True).count != expected_count:
                return False
            records = self._scroll_records(collection_name)
            if len(records) != expected_count:
                return False
            expected_generation = str(metadata.get("generation") or "")
            expected_vault_identity = str(metadata.get("vault_identity") or "")
            for record in records:
                payload = record.payload or {}
                item = payload.get("metadata") or {}
                chunk_id = str(item.get("authoritative_chunk_id") or "")
                content_hash = str(item.get("content_hash") or "")
                vault_id = str(item.get("vault_id") or "")
                page_content = payload.get("page_content")
                if not chunk_id or not content_hash or not vault_id or not isinstance(page_content, str):
                    return False
                if str(record.id) != str(uuid5(_POINT_NAMESPACE, chunk_id)):
                    return False
                if sha256_hex(page_content) != content_hash:
                    return False
                if str(item.get("generation") or "") != expected_generation:
                    return False
                if sha256_hex(vault_id) != expected_vault_identity:
                    return False
            return _records_hash(records) == str(metadata.get("corpus_hash") or "")
        except Exception:
            return False

    def _validate_collection_count(
        self,
        collection_name: str,
        metadata: dict[str, object],
    ) -> bool:
        try:
            expected_count = _nonnegative_int(metadata.get("point_count"))
            return (
                expected_count is not None
                and self._client_instance().count(collection_name=collection_name, exact=True).count
                == expected_count
            )
        except Exception:
            return False

    def _scroll_records(self, collection_name: str) -> list[Any]:
        client = self._client_instance()
        records: list[Any] = []
        offset = None
        while True:
            page, next_offset = client.scroll(
                collection_name=collection_name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            records.extend(page)
            if next_offset is None:
                return records
            offset = next_offset

    def _metadata(
        self,
        *,
        vault_id: str,
        generation: str,
        dimensions: int,
        corpus_hash: str,
        point_count: int,
    ) -> dict[str, object]:
        base: dict[str, object] = {
            "index_version": self.config.index_version,
            "embedding_provider": self.config.embedding_provider,
            "embedding_model": self.config.embedding_model,
            "embedding_dimensions": dimensions,
            "normalization": self.config.normalization,
            "chunker_version": self.config.chunker_version,
            "privacy_policy_version": self.config.privacy_policy_version,
            "transport_class": self.config.transport_class,
            "privacy_eligibility": "exclude-pending-hidden-legacy-and-sensitive-remote-v1",
            "corpus_version": self.config.corpus_version,
            "vault_identity": sha256_hex(vault_id),
            "collection_family": self.config.collection_name,
        }
        base["fingerprint"] = sha256_hex(json.dumps(base, ensure_ascii=True, sort_keys=True))
        base.update(
            {
                "generation": generation,
                "corpus_hash": corpus_hash,
                "point_count": point_count,
                "lifecycle_status": "validated",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return base

    def _metadata_matches_config(self, metadata: dict[str, object], vault_id: str) -> bool:
        dimensions = _positive_int(metadata.get("embedding_dimensions"))
        if dimensions is None:
            return False
        expected = self._metadata(
            vault_id=vault_id,
            generation=str(metadata.get("generation") or ""),
            dimensions=dimensions,
            corpus_hash=str(metadata.get("corpus_hash") or ""),
            point_count=_nonnegative_int(metadata.get("point_count")) or 0,
        )
        keys = {
            "index_version",
            "embedding_provider",
            "embedding_model",
            "embedding_dimensions",
            "normalization",
            "chunker_version",
            "privacy_policy_version",
            "transport_class",
            "privacy_eligibility",
            "corpus_version",
            "vault_identity",
            "collection_family",
            "fingerprint",
            "lifecycle_status",
        }
        if self.config.embedding_dimensions is not None and dimensions != self.config.embedding_dimensions:
            return False
        return all(metadata.get(key) == expected.get(key) for key in keys)

    def _metadata_matches_config_fields(self, metadata: dict[str, object]) -> bool:
        dimensions = _positive_int(metadata.get("embedding_dimensions"))
        if dimensions is None:
            return False
        vault_identity = str(metadata.get("vault_identity") or "")
        if not vault_identity:
            return False
        base: dict[str, object] = {
            "index_version": self.config.index_version,
            "embedding_provider": self.config.embedding_provider,
            "embedding_model": self.config.embedding_model,
            "embedding_dimensions": dimensions,
            "normalization": self.config.normalization,
            "chunker_version": self.config.chunker_version,
            "privacy_policy_version": self.config.privacy_policy_version,
            "transport_class": self.config.transport_class,
            "privacy_eligibility": "exclude-pending-hidden-legacy-and-sensitive-remote-v1",
            "corpus_version": self.config.corpus_version,
            "vault_identity": vault_identity,
            "collection_family": self.config.collection_name,
        }
        if self.config.embedding_dimensions is not None and dimensions != self.config.embedding_dimensions:
            return False
        fingerprint = sha256_hex(json.dumps(base, ensure_ascii=True, sort_keys=True))
        return (
            all(metadata.get(key) == value for key, value in base.items())
            and metadata.get("fingerprint") == fingerprint
            and metadata.get("lifecycle_status") == "validated"
        )

    def _update_collection_metadata(
        self,
        collection_name: str,
        metadata: dict[str, object],
    ) -> None:
        try:
            updated = self._client_instance().update_collection(
                collection_name=collection_name,
                metadata=metadata,
            )
            if not updated:
                raise VectorIndexUnavailableError("qdrant_unavailable")
        except VectorIndexUnavailableError:
            raise
        except Exception as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc

    def _collection_metadata(self, collection_name: str | None) -> dict[str, object] | None:
        if not collection_name:
            return None
        try:
            client = self._client_instance()
            if not client.collection_exists(collection_name):
                return None
            return dict(client.get_collection(collection_name).config.metadata or {})
        except VectorIndexUnavailableError:
            raise
        except Exception as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc

    def _promote_alias(self, vault_id: str, collection_name: str) -> None:
        try:
            from qdrant_client import models

            client = self._client_instance()
            alias = self._active_alias(vault_id)
            operations: list[Any] = []
            if self._active_collection(vault_id) is not None:
                operations.append(
                    models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
                )
            operations.append(
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(collection_name=collection_name, alias_name=alias)
                )
            )
            client.update_collection_aliases(change_aliases_operations=operations)
        except Exception as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc

    def _restore_alias(self, vault_id: str, previous_collection: str | None) -> None:
        try:
            from qdrant_client import models

            client = self._client_instance()
            alias = self._active_alias(vault_id)
            operations: list[Any] = []
            if self._active_collection(vault_id) is not None:
                operations.append(
                    models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
                )
            if previous_collection is not None and client.collection_exists(previous_collection):
                operations.append(
                    models.CreateAliasOperation(
                        create_alias=models.CreateAlias(
                            collection_name=previous_collection,
                            alias_name=alias,
                        )
                    )
                )
            if operations:
                client.update_collection_aliases(change_aliases_operations=operations)
        except Exception:
            logger.warning("Vector alias rollback failed", extra={"vault_id": vault_id})

    def _rollback_failed_candidate(
        self,
        *,
        vault_id: str,
        candidate_collection: str,
        previous_collection: str | None,
    ) -> None:
        try:
            active_collection = self._active_collection(vault_id)
        except VectorIndexUnavailableError:
            return
        if active_collection == candidate_collection:
            self._restore_alias(vault_id, previous_collection)
            try:
                active_collection = self._active_collection(vault_id)
            except VectorIndexUnavailableError:
                return
        if active_collection != candidate_collection:
            self._delete_collection(candidate_collection)

    def _active_collection(self, vault_id: str) -> str | None:
        alias = self._active_alias(vault_id)
        try:
            for item in self._client_instance().get_aliases().aliases:
                if item.alias_name == alias:
                    return str(item.collection_name)
        except VectorIndexUnavailableError:
            raise
        except Exception as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc
        return None

    def _active_collections(self, vault_id: str | None) -> list[str]:
        if vault_id is not None:
            collection = self._active_collection(vault_id)
            return [collection] if collection else []
        try:
            return sorted(
                {
                    str(item.collection_name)
                    for item in self._client_instance().get_aliases().aliases
                    if str(item.alias_name).startswith(f"{_ALIAS_PREFIX}_")
                    and str(item.alias_name).endswith("_active")
                }
            )
        except VectorIndexUnavailableError:
            raise
        except Exception as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc

    def _active_alias(self, vault_id: str) -> str:
        return f"{_ALIAS_PREFIX}_{sha256_hex(vault_id)[:16]}_active"

    def _generation_prefix(self, vault_id: str) -> str:
        return f"{_ALIAS_PREFIX}_{sha256_hex(vault_id)[:16]}_g_"

    def _generation_collection(self, vault_id: str, generation: str) -> str:
        return f"{self._generation_prefix(vault_id)}{generation[:20]}"

    def _generation_for_collection(self, collection_name: str | None) -> str | None:
        metadata = self._collection_metadata(collection_name)
        if metadata is None:
            return None
        return str(metadata.get("generation") or "") or None

    def _delete_collection(self, collection_name: str) -> bool:
        try:
            client = self._client_instance()
            if not client.collection_exists(collection_name):
                return False
            return bool(client.delete_collection(collection_name))
        except Exception:
            return False

    def _configured_dimensions(self) -> int | None:
        if self.config.embedding_dimensions is not None:
            return self.config.embedding_dimensions
        return _positive_int(getattr(self.config.embeddings, "dimensions", None))

    @property
    def _uses_remote_embeddings(self) -> bool:
        return self.config.transport_class.strip().casefold() not in {"local", "on-device", "on_device"}

    def _configuration_reason(self) -> str:
        if self.config.unavailable_reason:
            return _safe_reason(self.config.unavailable_reason)
        if not self.config.enabled:
            return "vector_disabled"
        if self.config.embedding_configured is False:
            return "embedding_not_configured"
        if self.config.embeddings is None:
            return "embedding_not_configured"
        return "index_not_built"

    def _record_sync(self, vault_id: str, result: VectorSyncResult) -> VectorSyncResult:
        self._last_sync[vault_id] = result
        if result.reason:
            self._blocked_vaults[vault_id] = _safe_reason(result.reason)
        return result

    def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import QdrantClient

            self.config.root_path.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(self.config.root_path))
            return self._client
        except Exception as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc

    def _store(self) -> Any:
        try:
            from langchain_qdrant import QdrantVectorStore
            from qdrant_client import models
        except ImportError as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc

        dimensions = self._configured_dimensions()
        if dimensions is None:
            raise VectorIndexUnavailableError("embedding_dimensions_unknown")
        client = self._client_instance()
        if not client.collection_exists(self.config.collection_name):
            client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
            )
        return QdrantVectorStore(
            client=client,
            collection_name=self.config.collection_name,
            embedding=self.config.embeddings,
            validate_collection_config=False,
        )

    def _document(self, *, page_content: str, metadata: dict[str, Any]) -> Any:
        try:
            from langchain_core.documents import Document
        except ImportError as exc:
            raise VectorIndexUnavailableError("qdrant_unavailable") from exc
        return Document(page_content=page_content, metadata=metadata)


def _legacy_chunk_allowed(relative_path: str, content: str) -> bool:
    return _path_allowed(relative_path) and evaluate_memory_content(content).allowed


def _path_allowed(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").strip("/")
    parts = normalized.split("/") if normalized else []
    if not parts or parts[0] == "Inbox" or any(part.startswith(".") for part in parts):
        return False
    if _looks_like_ignored_legacy_daily_path(parts):
        return False
    return True


def _looks_like_ignored_legacy_daily_path(parts: Sequence[str]) -> bool:
    if len(parts) < 5 or not re.fullmatch(r"\d{4}", parts[0]) or not re.fullmatch(r"\d{2}", parts[1]):
        return False
    return parts[4].startswith(f"{parts[0]}-{parts[1]}-") and parts[4].endswith(".md")


def _snapshot_hash(chunks: Sequence[_SnapshotChunk]) -> str:
    rows = [f"{chunk.point_id}\0{chunk.chunk_id}\0{chunk.content_hash}" for chunk in chunks]
    return sha256_hex("\n".join(sorted(rows)))


def _records_hash(records: Sequence[Any]) -> str:
    rows: list[str] = []
    for record in records:
        payload = record.payload or {}
        metadata = payload.get("metadata") or {}
        rows.append(
            "\0".join(
                [
                    str(record.id),
                    str(metadata.get("authoritative_chunk_id") or ""),
                    str(metadata.get("content_hash") or ""),
                ]
            )
        )
    return sha256_hex("\n".join(sorted(rows)))


def _normalize_vector(vector: Sequence[float], normalization: str) -> list[float]:
    values = [float(value) for value in vector]
    if normalization.strip().casefold() not in {"l2", "l2-v1", "cosine", "cosine-v1"}:
        return values
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude <= 0:
        return values
    return [value / magnitude for value in values]


def _safe_reason(reason: object) -> str:
    value = str(reason or "").strip().casefold()
    if value in _SAFE_REASONS:
        return value
    if "missing" in value and ("key" in value or "credential" in value):
        return "embedding_api_key_missing"
    if "provider" in value and "unsupported" in value:
        return "embedding_provider_unsupported"
    return "embedding_initialization_failed"


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _nonnegative_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _vector_id(
    vault_id: str,
    relative_path: str,
    content_hash: str,
    collection_name: str,
    embedding_model: str,
) -> str:
    raw = "\n".join([vault_id, relative_path, content_hash, collection_name, embedding_model])
    return str(uuid5(_POINT_NAMESPACE, raw))


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (TypeError, ValueError):
        return False
