from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from time import perf_counter_ns

from app.models.api import MemorySearchResponse, MemorySearchResult
from app.models.enums import IndexJobStatus, IndexJobType, NoteStatus
from app.repositories.storage import IndexJobRepository, NoteRepository, SearchResult, VaultRepository
from app.storage.database import Database, MigrationRunner
from app.storage.markdown import read_markdown
from app.storage.vault import VaultStorage
from app.services.retrieval_query import build_retrieval_plan, build_retrieval_plan_telemetry
from app.services.reranking import DisabledReranker, Reranker, apply_reranker
from app.services.retrieval_fusion import (
    FUSION_POLICY_VERSION,
    RRF_K,
    FusionCandidate,
    primary_channel,
    reciprocal_rank_fusion,
)
from app.services.vector_index import (
    LangChainQdrantVectorIndex,
    VectorIndexUnavailableError,
)
from app.services.write_policy import detect_sensitive_reason


logger = logging.getLogger(__name__)

# Over-fetch factor for retrieval channels: pull a wider candidate pool than
# top_k so fusion/rerank has material to work with, bounded to keep per-query
# cost predictable.
_CANDIDATE_POOL_MULTIPLIER = 4
_CANDIDATE_POOL_MIN = 8
_CANDIDATE_POOL_MAX = 40


def candidate_pool_size(top_k: int) -> int:
    return min(max(top_k * _CANDIDATE_POOL_MULTIPLIER, _CANDIDATE_POOL_MIN), _CANDIDATE_POOL_MAX)


_VALID_RETRIEVAL_MODES = ("fts", "vector", "hybrid")
_VALID_SOURCE_SCOPES = ("all", "personal_memory", "daily_chat", "knowledge_base")
_LOCAL_PRIVACY_STATE_KEY = "local_privacy_mode"
_DEFAULT_PRIVACY_POLICY_VERSION = "privacy-v1"
_RETRIEVAL_POLICY_VERSION = "retrieval-policy.v1"


class InvalidRetrievalModeError(ValueError):
    code = "invalid_retrieval_mode"

    def __init__(self) -> None:
        super().__init__("retrieval mode must be one of: fts, vector, hybrid")


class InvalidRetrievalSourceScopeError(ValueError):
    code = "invalid_retrieval_source_scope"

    def __init__(self) -> None:
        super().__init__(
            "retrieval source_scope must be one of: all, personal_memory, daily_chat, "
            "knowledge_base"
        )


@dataclass(frozen=True)
class RebuildIndexResult:
    index_job_id: str
    files_seen: int
    files_indexed: int
    status: str


class RetrievalService:
    def __init__(
        self,
        database: Database,
        vector_index: LangChainQdrantVectorIndex | None = None,
        reranker: Reranker | None = None,
        candidate_filter: Callable[[SearchResult], bool] | None = None,
    ) -> None:
        self.database = database
        self.vector_index = vector_index
        self.reranker = reranker or DisabledReranker()
        self.candidate_filter = candidate_filter

    def initialize(self) -> list[str]:
        return MigrationRunner(self.database).apply()

    def bind_vault(self, root_path: str, *, name: str | None = None) -> str:
        with self.database.session() as conn:
            with conn:
                return VaultRepository(conn).upsert(root_path, name=name)

    def rebuild_index(self, vault_id: str) -> RebuildIndexResult:
        with self.database.session() as conn:
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
                    note_repo.replace_note(
                        vault_id=vault_id,
                        relative_path=vault_path.relative_path,
                        markdown=parsed,
                        modified_at=vault_path.absolute_path.stat().st_mtime,
                    )
                    files_indexed += 1
                except Exception as exc:
                    errors.append(f"{vault_path.relative_path}: {exc}")

            for relative_path in note_repo.list_active_paths(vault_id=vault_id) - seen_paths:
                note_repo.mark_deleted(vault_id=vault_id, relative_path=relative_path)

            status = IndexJobStatus.SUCCESS if not errors else IndexJobStatus.FAILED
            if status == IndexJobStatus.SUCCESS:
                self._reconcile_vector_index_with_conn(conn, vault_id=vault_id)
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
        # Documented production default. hybrid/vector remain explicit opt-in:
        # they never passed the retrieval quality gate (see docs/portfolio/
        # claim-evidence-index.md, TASK-1215 Defer).
        mode: str = "fts",
        now: date | datetime | None = None,
    ) -> MemorySearchResponse:
        if mode not in _VALID_RETRIEVAL_MODES:
            raise InvalidRetrievalModeError()
        if source_scope not in _VALID_SOURCE_SCOPES:
            raise InvalidRetrievalSourceScopeError()

        total_started = perf_counter_ns()
        with self.database.session() as conn:
            local_privacy = _local_privacy_enabled(conn)
            sensitive_reason = detect_sensitive_reason(query)
            requested_channels = _channels_for_mode(mode)
            plan = build_retrieval_plan(
                query,
                approved_source_scopes=_plan_source_scopes(source_scope),
                requested_channels=requested_channels,
                local_privacy=local_privacy,
                sensitive=sensitive_reason is not None,
                now=now,
            )
            plan_telemetry = build_retrieval_plan_telemetry(plan, original_query=query)
            vector_health = self._vector_health(vault_id)
            fallback_reason: str | None = None
            if "vector" in requested_channels and local_privacy:
                fallback_reason = "local_privacy_mode"
                vector_health.update(
                    semantic_available=False,
                    vector_available=False,
                    unavailability_reason="local_privacy_mode",
                )
            elif "vector" in requested_channels and sensitive_reason is not None:
                fallback_reason = "sensitive_content_blocked"
                vector_health.update(
                    semantic_available=False,
                    vector_available=False,
                    unavailability_reason="sensitive_content_blocked",
                )

            completed_channels: list[str] = []
            vector_results = []
            fts_results = []
            vector_adapter_ms = 0.0
            fts_search_ms = 0.0
            vector_requested = "vector" in requested_channels
            daily_date_range = plan.date_range if source_scope == "daily_chat" else None
            date_constrained_daily = daily_date_range is not None
            # Date filtering needs a broad candidate pool, while the public result
            # count remains bounded by the caller's top_k contract.
            candidate_limit = (
                _CANDIDATE_POOL_MAX if date_constrained_daily else candidate_pool_size(top_k)
            )
            result_limit = top_k
            note_repository = NoteRepository(conn)
            daily_date_results = None
            daily_date_search_ms = 0.0
            daily_chunk_ids = None
            if daily_date_range is not None:
                daily_date_started = perf_counter_ns()
                daily_date_results = _authoritative_fts_results(
                    conn,
                    note_repository.search_daily_chat_by_date_range(
                        vault_id=vault_id,
                        start_date=daily_date_range.start,
                        end_date=daily_date_range.end,
                        top_k=candidate_limit,
                    ),
                    vault_id=vault_id,
                )
                daily_date_search_ms = _elapsed_ms(daily_date_started)
                daily_chunk_ids = tuple(result.chunk_id for result in daily_date_results)

            vector_allowed = "vector" in plan.requested_channels
            if vector_requested and vector_allowed:
                if self.vector_index is None:
                    fallback_reason = "embedding_not_configured"
                else:
                    semantic_query = plan.semantic_variants[0] if plan.semantic_variants else plan.lexical_query
                    vector_started = perf_counter_ns()
                    try:
                        vector_search_kwargs: dict[str, object] = {
                            "query": semantic_query,
                            "vault_id": vault_id,
                            "top_k": candidate_limit,
                            "local_privacy": local_privacy,
                        }
                        if daily_chunk_ids is not None:
                            vector_search_kwargs["chunk_ids"] = daily_chunk_ids
                        candidates = self.vector_index.search(**vector_search_kwargs)
                        completed_channels.append("vector")
                        authoritative_vector_results = _authoritative_vector_results(
                            conn,
                            candidates,
                            vault_id=vault_id,
                            active_generation=_optional_text(vector_health.get("active_generation")),
                        )
                        if daily_chunk_ids is None:
                            vector_results = authoritative_vector_results
                        else:
                            allowed_chunk_ids = set(daily_chunk_ids)
                            vector_results = [
                                result
                                for result in authoritative_vector_results
                                if result.chunk_id in allowed_chunk_ids
                            ]
                        if candidates and not authoritative_vector_results:
                            fallback_reason = "vector_candidates_rejected"
                        elif not candidates and (daily_chunk_ids is None or daily_chunk_ids):
                            fallback_reason = "vector_no_results"
                        elif daily_chunk_ids and not vector_results:
                            fallback_reason = "vector_no_results"
                    except VectorIndexUnavailableError as exc:
                        fallback_reason = exc.reason
                        vector_health.update(
                            semantic_available=False,
                            vector_available=False,
                            unavailability_reason=exc.reason,
                        )
                    except Exception:
                        fallback_reason = "qdrant_unavailable"
                        vector_health.update(
                            semantic_available=False,
                            vector_available=False,
                            unavailability_reason="qdrant_unavailable",
                        )
                    finally:
                        vector_adapter_ms = _elapsed_ms(vector_started)

            valid_empty_vector_scope = (
                daily_chunk_ids == ()
                and "vector" in completed_channels
                and fallback_reason is None
            )
            fts_required = (
                "fts" in requested_channels
                or (not vector_results and not valid_empty_vector_scope)
            )
            if fts_required:
                if daily_date_results is not None:
                    fts_results = daily_date_results
                    fts_search_ms = daily_date_search_ms
                else:
                    fts_started = perf_counter_ns()
                    search_results = note_repository.search(
                        vault_id=vault_id,
                        query=plan.lexical_query,
                        top_k=candidate_limit,
                    )
                    fts_results = _authoritative_fts_results(
                        conn,
                        search_results,
                        vault_id=vault_id,
                    )
                    fts_search_ms = _elapsed_ms(fts_started)
                completed_channels.append("fts")

            fusion_channels = {}
            if fts_results:
                fusion_channels["fts"] = [
                    _fusion_candidate(result, candidate_filter=self.candidate_filter)
                    for result in fts_results
                ]
            if vector_results:
                fusion_channels["vector"] = [
                    _fusion_candidate(result, candidate_filter=self.candidate_filter)
                    for result in vector_results
                ]
            fusion_started = perf_counter_ns()
            reranker_enabled = bool(getattr(self.reranker, "enabled", False))
            fusion_limit = min(
                _CANDIDATE_POOL_MAX,
                max(result_limit, 20 if reranker_enabled else result_limit),
            )
            fusion = reciprocal_rank_fusion(
                fusion_channels,
                approved_scopes=plan.source_scopes,
                top_k=fusion_limit,
                required_vault_id=vault_id,
            )
            fusion_ms = round(
                _elapsed_ms(fusion_started)
                + (daily_date_search_ms if daily_date_results is not None and not fts_required else 0.0),
                6,
            )
            rerank_outcome = apply_reranker(
                query=plan.lexical_query,
                candidates=fusion.candidates,
                reranker=self.reranker,
                remote_provider_approved=False,
            )
            results = rerank_outcome.candidates[:result_limit]
            effective_mode = _effective_mode(
                requested_mode=mode,
                completed_channels=completed_channels,
                vector_results=vector_results,
            )
            metadata: dict[str, object] = {
                **vector_health,
                "retrieval_mode": mode,
                "requested_mode": mode,
                "effective_mode": effective_mode,
                "requested_channels": list(requested_channels),
                "completed_channels": completed_channels,
                "fallback_reason": fallback_reason,
                "retrieval_policy_version": _RETRIEVAL_POLICY_VERSION,
                "privacy_policy_version": _privacy_policy_version(self.vector_index),
                "plan_telemetry": plan_telemetry.model_dump(mode="json"),
                "fusion": {
                    "policy_version": FUSION_POLICY_VERSION,
                    "algorithm": "reciprocal_rank_fusion",
                    "rrf_k": RRF_K,
                    "channel_weights": {channel: 1.0 for channel in sorted(fusion_channels)},
                    "input_counts": fusion.diagnostics.input_counts,
                    "eligible_counts": fusion.diagnostics.eligible_counts,
                    "filtered_count": fusion.diagnostics.filtered_count,
                    "within_channel_duplicate_count": fusion.diagnostics.within_channel_duplicate_count,
                    "conflicting_identity_count": fusion.diagnostics.conflicting_identity_count,
                    "fused_count": fusion.diagnostics.fused_count,
                    "selected_count": len(results),
                },
                "reranker": {
                    "status": rerank_outcome.status,
                    "name": rerank_outcome.reranker_name,
                    "policy_version": "reranker-policy.v1",
                    "fallback_reason": rerank_outcome.fallback_reason,
                    "external_request_count": rerank_outcome.external_request_count,
                    "transmitted_bytes": rerank_outcome.transmitted_bytes,
                    "external_cost_usd": rerank_outcome.external_cost_usd,
                    "provider_error_count": rerank_outcome.provider_error_count,
                },
                "retrieval_latency_ms": {
                    "vector_adapter_total": vector_adapter_ms,
                    "fts_search": fts_search_ms,
                    "filter_fusion_dedupe": fusion_ms,
                    "reranker": rerank_outcome.latency_ms,
                    "total": _elapsed_ms(total_started),
                },
            }
            unavailable_reason = vector_health.get("unavailability_reason")
            if unavailable_reason:
                metadata["vector_unavailable_reason"] = unavailable_reason
        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    note_id=fused.payload.note_id,
                    chunk_id=fused.payload.chunk_id,
                    relative_path=fused.payload.relative_path,
                    title=fused.payload.title,
                    heading=fused.payload.heading,
                    snippet=_sanitize_snippet(fused.payload.snippet),
                    score=fused.score,
                    content_hash=fused.content_hash,
                    source_scope=_classify_source_scope(fused.payload.relative_path),
                    retrieval_mode=primary_channel(fused),
                    retrieval_channels=list(fused.channels),
                    channel_ranks=fused.channel_ranks,
                    retrieval_contributions=[
                        {
                            "channel": contribution.channel,
                            "rank": contribution.rank,
                            "rrf_component": contribution.component,
                        }
                        for contribution in fused.contributions
                    ],
                    score_breakdown={
                        "rrf_total": fused.score,
                        **{
                            f"rrf_{channel}": component
                            for channel, component in fused.score_components.items()
                        },
                    },
                )
                for fused in results
            ],
            metadata=metadata,
        )

    def reconcile_vector_index(self, vault_id: str):
        with self.database.session() as conn:
            return self._reconcile_vector_index_with_conn(conn, vault_id=vault_id)

    def _reconcile_vector_index_with_conn(self, conn, *, vault_id: str):
        if self.vector_index is None:
            return None
        reconcile = getattr(self.vector_index, "reconcile", None)
        if not callable(reconcile):
            return None
        try:
            return reconcile(
                conn=conn,
                vault_id=vault_id,
                local_privacy=_local_privacy_enabled(conn),
            )
        except Exception:
            logger.warning(
                "Vector reconcile failed after authoritative SQLite rebuild; preserving FTS and prior generation",
                extra={"vault_id": vault_id},
            )
            return None

    def _vector_health(self, vault_id: str) -> dict[str, object]:
        health = _default_vector_health()
        if self.vector_index is None:
            return health
        health_method = getattr(self.vector_index, "health", None)
        if callable(health_method):
            try:
                try:
                    reported = health_method(vault_id, deep=False)
                except TypeError:
                    reported = health_method(vault_id)
            except Exception:
                health["last_sync_status"] = "failed"
                health["unavailability_reason"] = "vector_health_unavailable"
                return health
            if isinstance(reported, dict):
                for key in health:
                    if key in reported:
                        health[key] = reported[key]
                return health
        available = bool(getattr(self.vector_index, "available", False))
        health["semantic_available"] = available
        health["vector_available"] = available
        health["embedding_configured"] = available
        config = getattr(self.vector_index, "config", None)
        reason = getattr(config, "unavailable_reason", None)
        health["unavailability_reason"] = str(reason) if reason else None
        return health


def _channels_for_mode(mode: str) -> tuple[str, ...]:
    if mode == "fts":
        return ("fts",)
    if mode == "vector":
        return ("vector",)
    return ("fts", "vector")


def _plan_source_scopes(source_scope: str) -> tuple[str, ...]:
    if source_scope == "personal_memory":
        return ("personal_memory",)
    if source_scope == "daily_chat":
        return ("daily_chat",)
    if source_scope == "knowledge_base":
        return ("wiki", "vault_note")
    return ("personal_memory", "diary", "daily_chat", "wiki", "vault_note", "graph")


def _local_privacy_enabled(conn) -> bool:
    row = conn.execute(
        "SELECT value FROM app_state WHERE key = ?",
        (_LOCAL_PRIVACY_STATE_KEY,),
    ).fetchone()
    if row is None:
        return False
    raw_value = row["value"]
    try:
        value = json.loads(str(raw_value))
    except (TypeError, ValueError):
        value = str(raw_value).strip().casefold()
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value in {"1", "true", "yes", "on"}
    return False


def _default_vector_health() -> dict[str, object]:
    return {
        "semantic_available": False,
        "vector_available": False,
        "embedding_configured": False,
        "index_version": None,
        "active_generation": None,
        "last_sync_status": "unavailable",
        "unavailability_reason": "embedding_not_configured",
    }


def _privacy_policy_version(vector_index) -> str:
    config = getattr(vector_index, "config", None)
    value = getattr(config, "privacy_policy_version", None)
    return str(value or _DEFAULT_PRIVACY_POLICY_VERSION)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _authoritative_vector_results(conn, candidates, *, vault_id: str, active_generation: str | None):
    if active_generation is None:
        return []
    accepted = []
    for candidate in candidates:
        candidate_vault_id = _optional_text(getattr(candidate, "vault_id", None))
        content_hash = _optional_text(getattr(candidate, "content_hash", None))
        generation = _optional_text(getattr(candidate, "generation", None))
        note_id = _optional_text(getattr(candidate, "note_id", None))
        chunk_id = _optional_text(getattr(candidate, "chunk_id", None))
        relative_path = _optional_text(getattr(candidate, "relative_path", None))
        if None in {
            candidate_vault_id,
            content_hash,
            generation,
            note_id,
            chunk_id,
            relative_path,
        }:
            continue
        if candidate_vault_id != vault_id or generation != active_generation:
            continue
        row = conn.execute(
            """
            SELECT
                note_chunks.content_hash,
                note_chunks.title,
                note_chunks.heading,
                note_chunks.content
            FROM note_chunks
            JOIN notes
              ON notes.id = note_chunks.note_id
             AND notes.vault_id = note_chunks.vault_id
             AND notes.relative_path = note_chunks.relative_path
            JOIN vector_chunks
              ON vector_chunks.chunk_id = note_chunks.id
             AND vector_chunks.note_id = note_chunks.note_id
             AND vector_chunks.vault_id = note_chunks.vault_id
             AND vector_chunks.relative_path = note_chunks.relative_path
             AND vector_chunks.content_hash = note_chunks.content_hash
            WHERE note_chunks.id = ?
              AND note_chunks.note_id = ?
              AND note_chunks.vault_id = ?
              AND note_chunks.relative_path = ?
              AND note_chunks.content_hash = ?
              AND notes.status = ?
            LIMIT 1
            """,
            (
                chunk_id,
                note_id,
                vault_id,
                relative_path,
                content_hash,
                NoteStatus.INDEXED.value,
            ),
        ).fetchone()
        if row is None or str(row["content_hash"]) != content_hash:
            continue
        accepted.append(
            replace(
                candidate,
                title=str(row["title"]),
                heading=str(row["heading"]) if row["heading"] is not None else None,
                snippet=str(row["content"])[:600],
            )
        )
    return accepted


def _authoritative_fts_results(conn, candidates, *, vault_id: str) -> list[SearchResult]:
    accepted: list[SearchResult] = []
    for candidate in candidates:
        row = conn.execute(
            """
            SELECT note_chunks.content_hash
            FROM note_chunks
            JOIN notes
              ON notes.id = note_chunks.note_id
             AND notes.vault_id = note_chunks.vault_id
             AND notes.relative_path = note_chunks.relative_path
            WHERE note_chunks.id = ?
              AND note_chunks.note_id = ?
              AND note_chunks.vault_id = ?
              AND note_chunks.relative_path = ?
              AND notes.status = ?
            LIMIT 1
            """,
            (
                candidate.chunk_id,
                candidate.note_id,
                vault_id,
                candidate.relative_path,
                NoteStatus.INDEXED.value,
            ),
        ).fetchone()
        if row is None:
            continue
        content_hash = _optional_text(row["content_hash"])
        if content_hash is None:
            continue
        accepted.append(
            replace(
                candidate,
                content_hash=content_hash,
                vault_id=vault_id,
            )
        )
    return accepted


def _fusion_candidate(
    result: SearchResult,
    *,
    candidate_filter: Callable[[SearchResult], bool] | None = None,
) -> FusionCandidate:
    return FusionCandidate(
        stable_id=result.chunk_id,
        content_hash=result.content_hash or "",
        source_scope=_fusion_source_scope(result.relative_path),
        payload=result,
        stable_order_key=(
            f"{result.relative_path.replace(chr(92), '/')}\0{result.content_hash or ''}"
        ),
        permission_allowed=True,
        lifecycle_status=_note_lifecycle_status(result.relative_path),
        metadata_filter_passed=(
            _classify_source_scope(result.relative_path) not in {"pending_memory", "ignored"}
            and _candidate_policy_allows(result, candidate_filter)
        ),
        vault_id=result.vault_id,
        generation_valid=True,
    )


def _candidate_policy_allows(
    result: SearchResult,
    candidate_filter: Callable[[SearchResult], bool] | None,
) -> bool:
    if candidate_filter is None:
        return True
    try:
        return bool(candidate_filter(result))
    except Exception:
        # Fail closed, but never silently: a broken filter previously made
        # every candidate disappear with no trace in the logs.
        logger.warning(
            "candidate_filter raised while evaluating note_id=%s; treating candidate as disallowed.",
            getattr(result, "note_id", "<unknown>"),
            exc_info=True,
        )
        return False


def _effective_mode(*, requested_mode: str, completed_channels: list[str], vector_results) -> str:
    if requested_mode == "hybrid" and {"fts", "vector"}.issubset(completed_channels):
        return "hybrid"
    if vector_results:
        return "vector"
    if "fts" in completed_channels:
        return "fts"
    return "vector"


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


def _fusion_source_scope(relative_path: str) -> str:
    source_scope = _classify_source_scope(relative_path)
    if source_scope != "knowledge_base":
        return source_scope
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("Wiki/"):
        return "wiki"
    return "vault_note"


def _note_lifecycle_status(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").casefold()
    lifecycle_prefixes = {
        "memories/longterm/superseded/": "superseded",
        "memories/longterm/quarantined/": "quarantined",
        "memories/longterm/candidates/": "candidate",
        "memories/longterm/archived/": "archived",
    }
    for prefix, status in lifecycle_prefixes.items():
        if normalized.startswith(prefix):
            return status
    return "indexed"


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


def _elapsed_ms(started_ns: int) -> float:
    return round((perf_counter_ns() - started_ns) / 1_000_000, 6)
