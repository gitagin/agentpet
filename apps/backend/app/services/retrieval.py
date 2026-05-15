from __future__ import annotations

from dataclasses import dataclass

from app.models.api import MemorySearchResponse, MemorySearchResult
from app.models.enums import IndexJobStatus, IndexJobType
from app.repositories.storage import IndexJobRepository, NoteRepository, VaultRepository
from app.storage.database import Database, MigrationRunner
from app.storage.markdown import read_markdown
from app.storage.vault import VaultStorage
from app.services.vector_index import (
    LangChainQdrantVectorIndex,
    VectorChunkRepository,
    VectorIndexUnavailableError,
)


@dataclass(frozen=True)
class RebuildIndexResult:
    index_job_id: str
    files_seen: int
    files_indexed: int
    status: str


class RetrievalService:
    def __init__(self, database: Database, vector_index: LangChainQdrantVectorIndex | None = None) -> None:
        self.database = database
        self.vector_index = vector_index

    def initialize(self) -> list[str]:
        return MigrationRunner(self.database).apply()

    def bind_vault(self, root_path: str, *, name: str | None = None) -> str:
        with self.database.connect() as conn:
            with conn:
                return VaultRepository(conn).upsert(root_path, name=name)

    def rebuild_index(self, vault_id: str) -> RebuildIndexResult:
        with self.database.connect() as conn:
            vault = VaultRepository(conn).get(vault_id)
            job_repo = IndexJobRepository(conn)
            note_repo = NoteRepository(conn)
            storage = VaultStorage(vault["root_path"])
            with conn:
                job_id = job_repo.create(vault_id=vault_id, job_type=IndexJobType.FULL)

            files_seen = 0
            files_indexed = 0
            errors: list[str] = []
            seen_paths: set[str] = set()
            for vault_path in storage.iter_markdown_files():
                files_seen += 1
                seen_paths.add(vault_path.relative_path)
                try:
                    parsed = read_markdown(vault_path.absolute_path)
                    note_id = note_repo.replace_note(
                        vault_id=vault_id,
                        relative_path=vault_path.relative_path,
                        markdown=parsed,
                        modified_at=vault_path.absolute_path.stat().st_mtime,
                    )
                    self._replace_vector_note(
                        conn=conn,
                        vault_id=vault_id,
                        note_id=note_id,
                        relative_path=vault_path.relative_path,
                        markdown=parsed,
                    )
                    files_indexed += 1
                except Exception as exc:
                    errors.append(f"{vault_path.relative_path}: {exc}")

            for relative_path in note_repo.list_active_paths(vault_id=vault_id) - seen_paths:
                self._delete_vector_note(conn=conn, vault_id=vault_id, relative_path=relative_path)
                note_repo.mark_deleted(vault_id=vault_id, relative_path=relative_path)

            status = IndexJobStatus.SUCCESS if not errors else IndexJobStatus.FAILED
            with conn:
                job_repo.finish(
                    job_id=job_id,
                    status=status,
                    files_seen=files_seen,
                    files_indexed=files_indexed,
                    error="\n".join(errors) or None,
                )
            return RebuildIndexResult(job_id, files_seen, files_indexed, status.value)

    def search(
        self,
        *,
        vault_id: str,
        query: str,
        top_k: int = 8,
        source_scope: str = "all",
        mode: str = "hybrid",
    ) -> MemorySearchResponse:
        with self.database.connect() as conn:
            search_mode = mode if mode in {"hybrid", "vector", "fts"} else "hybrid"
            metadata: dict[str, object] = {
                "semantic_available": False,
                "retrieval_mode": search_mode,
                "vector_available": bool(self.vector_index and self.vector_index.available),
            }
            raw_results = []
            vector_results = []
            fts_results = []
            if search_mode in {"hybrid", "vector"}:
                try:
                    vector_results = self._search_vector(
                        vault_id=vault_id,
                        query=query,
                        top_k=min(max(top_k * 4, 8), 40),
                    )
                except VectorIndexUnavailableError:
                    metadata["vector_available"] = False
                except Exception as exc:
                    metadata["vector_error"] = exc.__class__.__name__
                raw_results.extend(("vector", result) for result in vector_results)
            if search_mode in {"hybrid", "fts"} or (search_mode == "vector" and not vector_results):
                fts_results = NoteRepository(conn).search(vault_id=vault_id, query=query, top_k=min(max(top_k * 4, 8), 40))
                raw_results.extend(("fts", result) for result in fts_results)
            if source_scope == "daily_chat":
                date_results = _merge_daily_date_results(
                    raw_results,
                    [
                        ("fts", result)
                        for result in NoteRepository(conn).search_daily_chat_by_date(
                            vault_id=vault_id,
                            query=query,
                            top_k=min(max(top_k * 4, 8), 40),
                        )
                    ],
                )
                raw_results = date_results
            results = _rank_scoped_results(raw_results, source_scope=source_scope, top_k=top_k)
        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    note_id=result.note_id,
                    chunk_id=result.chunk_id,
                    relative_path=result.relative_path,
                    title=result.title,
                    heading=result.heading,
                    snippet=_sanitize_snippet(result.snippet),
                    score=result.score,
                    source_scope=_classify_source_scope(result.relative_path),
                    retrieval_mode=result_mode,
                )
                for result_mode, result in results
            ],
            metadata=metadata,
        )

    def _replace_vector_note(self, *, conn, vault_id: str, note_id: str, relative_path: str, markdown) -> None:
        if self.vector_index is None or not self.vector_index.available:
            return
        ids = self.vector_index.upsert_markdown(
            vault_id=vault_id,
            note_id=note_id,
            relative_path=relative_path,
            markdown=markdown,
        )
        repo = VectorChunkRepository(conn)
        repo.replace_note_vectors(
            vault_id=vault_id,
            relative_path=relative_path,
            note_id=note_id,
            chunks=markdown,
            collection_name=self.vector_index.config.collection_name,
            embedding_model=self.vector_index.config.embedding_model,
        )

    def _delete_vector_note(self, *, conn, vault_id: str, relative_path: str) -> None:
        repo = VectorChunkRepository(conn)
        ids = repo.delete_note_vectors(vault_id=vault_id, relative_path=relative_path)
        if self.vector_index is not None:
            self.vector_index.delete(ids)

    def _search_vector(self, *, vault_id: str, query: str, top_k: int):
        if self.vector_index is None:
            raise VectorIndexUnavailableError("vector index is not configured")
        return self.vector_index.search(vault_id=vault_id, query=query, top_k=top_k)


def _rank_scoped_results(results, *, source_scope: str, top_k: int):
    normalized_scope = source_scope if source_scope in {"personal_memory", "daily_chat", "knowledge_base", "all"} else "all"
    weighted = []
    seen: set[tuple[str, str, str]] = set()
    for result_mode, result in results:
        result_scope = _classify_source_scope(result.relative_path)
        if result_scope in {"pending_memory", "ignored"}:
            continue
        if normalized_scope != "all" and result_scope != normalized_scope:
            continue
        key = (result.relative_path, result.heading or "", _sanitize_snippet(result.snippet).casefold())
        if key in seen:
            continue
        seen.add(key)
        weighted.append((_source_weight(result_scope), _mode_weight(result_mode), result_mode, result))
    weighted.sort(key=lambda item: (-item[0], -item[1], -item[3].score, item[3].relative_path))
    return [(result_mode, result) for _, _, result_mode, result in weighted[:top_k]]


def _classify_source_scope(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    if normalized == "Inbox/Pending Memories.md" or normalized.startswith("Inbox/"):
        return "pending_memory"
    if _looks_like_legacy_root_daily_chat_path(parts):
        return "ignored"
    if _looks_like_daily_chat_path(parts):
        return "daily_chat"
    if _looks_like_personal_memory_path(normalized):
        return "personal_memory"
    return "knowledge_base"


def _looks_like_daily_chat_path(parts: list[str]) -> bool:
    if len(parts) < 7:
        return False
    memories, daily, year, month, week, weekday, filename = parts[-7:]
    return (
        memories == "Memories"
        and daily == "Daily"
        and year.isdigit()
        and len(year) == 4
        and month.isdigit()
        and len(month) == 2
        and week.startswith("第")
        and "周_" in week
        and weekday.startswith("星期")
        and filename.startswith(f"{year}-{month}-")
        and filename.endswith(".md")
    )


def _looks_like_legacy_root_daily_chat_path(parts: list[str]) -> bool:
    if len(parts) < 5:
        return False
    year, month, week, weekday, filename = parts[:5]
    return (
        year.isdigit()
        and len(year) == 4
        and month.isdigit()
        and len(month) == 2
        and week.startswith("第")
        and "周_" in week
        and weekday.startswith("星期")
        and filename.startswith(f"{year}-{month}-")
        and filename.endswith(".md")
    )


def _looks_like_personal_memory_path(normalized: str) -> bool:
    if normalized.startswith("Memory/") or normalized.startswith("Profile/"):
        return True
    if normalized.startswith("Memories/Daily/"):
        return False
    if normalized.startswith("Memories/LongTerm/"):
        return True
    if normalized.startswith("Memories/Profile/"):
        return True
    if normalized.startswith("Memories/Preferences/"):
        return True
    parts = normalized.split("/")
    return len(parts) == 2 and parts[0] == "Memories" and parts[1].endswith(".md")


def _source_weight(source_scope: str) -> int:
    return {"personal_memory": 3, "knowledge_base": 2, "daily_chat": 1}.get(source_scope, 0)


def _mode_weight(mode: str) -> int:
    return {"vector": 2, "fts": 1}.get(mode, 0)


def _sanitize_snippet(snippet: str) -> str:
    lines = []
    for line in snippet.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(
            marker in stripped
            for marker in (
                "conversation_id",
                "user_message_id",
                "assistant_message_id",
                "agent_run_id",
            )
        ):
            continue
        lines.append(stripped)
    return " ".join(lines)


def _merge_daily_date_results(primary, date_results):
    merged = list(primary)
    seen = {result.chunk_id for _, result in merged}
    for result_mode, result in date_results:
        if result.chunk_id in seen:
            continue
        seen.add(result.chunk_id)
        merged.append((result_mode, result))
    return merged
