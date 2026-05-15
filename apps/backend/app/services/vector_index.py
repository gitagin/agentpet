from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.models.common import new_id
from app.repositories.storage import SearchResult
from app.storage.markdown import ParsedMarkdown


@dataclass(frozen=True)
class VectorIndexConfig:
    enabled: bool
    root_path: Path
    collection_name: str
    embedding_model: str
    embeddings: Any | None = None


class VectorIndexUnavailableError(Exception):
    pass


class VectorChunkRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vector_chunks (
                vector_id TEXT PRIMARY KEY,
                chunk_id TEXT NOT NULL,
                note_id TEXT NOT NULL,
                vault_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_vector_chunks_vault_path
            ON vector_chunks(vault_id, relative_path)
            """
        )

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
            vector_id = _vector_id(vault_id, relative_path, chunk.content_hash, collection_name, embedding_model)
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
                  AND note_chunks.content_hash = ?
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
                    chunk.content_hash,
                ),
            )
        return vector_ids

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
    def __init__(self, config: VectorIndexConfig) -> None:
        self.config = config

    @property
    def available(self) -> bool:
        return self.config.enabled and self.config.embeddings is not None

    def upsert_markdown(
        self,
        *,
        vault_id: str,
        note_id: str,
        relative_path: str,
        markdown: ParsedMarkdown,
    ) -> list[str]:
        if not self.available:
            return []
        ids = [
            _vector_id(vault_id, relative_path, chunk.content_hash, self.config.collection_name, self.config.embedding_model)
            for chunk in markdown.chunks
        ]
        if not ids:
            return []
        store = self._store()
        try:
            store.delete(ids=ids)
        except Exception:
            pass
        documents = []
        for chunk, vector_id in zip(markdown.chunks, ids):
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

    def search(self, *, query: str, vault_id: str, top_k: int) -> list[SearchResult]:
        if not self.available:
            raise VectorIndexUnavailableError("vector index is not configured")
        rows = self._store().similarity_search_with_score(
            query=query,
            k=top_k,
            filter={"must": [{"key": "metadata.vault_id", "match": {"value": vault_id}}]},
        )
        results: list[SearchResult] = []
        for document, score in rows:
            metadata = getattr(document, "metadata", {}) or {}
            results.append(
                SearchResult(
                    note_id=str(metadata.get("note_id") or ""),
                    chunk_id=str(metadata.get("vector_id") or new_id()),
                    relative_path=str(metadata.get("relative_path") or ""),
                    title=str(metadata.get("title") or ""),
                    heading=str(metadata.get("heading") or "") or None,
                    snippet=str(getattr(document, "page_content", "") or "")[:600],
                    score=float(score),
                )
            )
        return [result for result in results if result.relative_path]

    def _store(self) -> Any:
        try:
            from langchain_qdrant import QdrantVectorStore
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise VectorIndexUnavailableError("qdrant dependencies are not installed") from exc

        self.config.root_path.mkdir(parents=True, exist_ok=True)
        client = QdrantClient(path=str(self.config.root_path))
        return QdrantVectorStore(
            client=client,
            collection_name=self.config.collection_name,
            embedding=self.config.embeddings,
        )

    def _document(self, *, page_content: str, metadata: dict[str, Any]) -> Any:
        try:
            from langchain_core.documents import Document
        except ImportError as exc:
            raise VectorIndexUnavailableError("langchain-core is not installed") from exc
        return Document(page_content=page_content, metadata=metadata)


def _vector_id(
    vault_id: str,
    relative_path: str,
    content_hash: str,
    collection_name: str,
    embedding_model: str,
) -> str:
    raw = "\n".join([vault_id, relative_path, content_hash, collection_name, embedding_model])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
