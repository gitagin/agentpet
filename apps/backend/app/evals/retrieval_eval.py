from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import sqlite3
import stat
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from app.repositories.storage import SearchResult
from app.services.reranking import RerankerResponse
from app.services.retrieval import RetrievalService, _classify_source_scope
from app.services.vector_index import LangChainQdrantVectorIndex, VectorIndexConfig
from app.storage.database import Database


EVALUATOR_VERSION = "retrieval-eval.v1"
REPORT_SCHEMA_VERSION = "retrieval-eval-report.v1"
DATASET_SCHEMA_VERSION = "retrieval-eval-dataset.v1"
DEFAULT_RANDOM_SEED = 1204
TOP_K = 10
PROMPT_TOP_K = 5
WARMUP_QUERY_COUNT = 3
PRIMARY_SLICE_MINIMUMS = {
    "exact_keyword_identifier": 10,
    "no_ascii_keyword_overlap": 15,
    "chinese_conversational": 8,
    "cross_expression_zh_en": 5,
    "temporal_date_entity": 7,
    "contradictory_stale_superseded": 5,
    "permission_inactive_sensitive": 5,
    "empty_adversarial_unanswerable": 5,
}
SEARCHABLE_SCOPES = {"all", "personal_memory", "daily_chat", "knowledge_base"}
EXPECTED_SCOPES = SEARCHABLE_SCOPES | {"none"}
ACCESS_STATES = {"active", "inactive", "sensitive", "superseded", "ignored"}
ANSWER_LABELS = {"answerable", "no_evidence"}
FINAL_GATES = {
    "inaccessible_memory_leakage": ("eq", 0.0),
    "expected_excluded_id_leakage": ("eq", 0.0),
    "cross_vault_leakage": ("eq", 0.0),
    "fabricated_citations": ("eq", 0.0),
    "recall_at_5": ("gte", 0.80),
    "recall_at_10": ("gte", 0.90),
    "precision_at_5": ("gte", 0.80),
    "mrr_at_10": ("gte", 0.75),
    "ndcg_at_10": ("gte", 0.80),
    "no_evidence_accuracy": ("gte", 1.0),
    "fts_p95_ms": ("lte", 200.0),
    "fts_hard_max_ms": ("lte", 500.0),
}
GROUNDING_FINAL_GATES = {
    "citation_precision": ("gte", 0.95),
    "local_fact_citation_coverage": ("gte", 1.0),
    "grounded_answer_faithfulness": ("gte", 0.90),
    "local_fact_claims_with_empty_evidence": ("eq", 0.0),
}
MEANINGFUL_STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "before",
    "can",
    "could",
    "does",
    "for",
    "from",
    "have",
    "how",
    "into",
    "its",
    "may",
    "ought",
    "should",
    "that",
    "the",
    "their",
    "then",
    "there",
    "they",
    "this",
    "was",
    "what",
    "when",
    "whether",
    "which",
    "will",
    "with",
    "would",
}
PROHIBITED_FIXTURE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:ghp_|gho_|ghu_|github_pat_|xoxb-|AKIA)[A-Za-z0-9_-]+\b"),
    re.compile(r"\b(?:password|passwd|pwd|secret|token|api_key)\s*=", re.IGNORECASE),
    re.compile(r"\b[A-Za-z]:[\\/]"),
    re.compile(r"(?<![A-Za-z0-9])/(?:home|root|Users)/", re.IGNORECASE),
    re.compile(r"\\\\[^\\/\s]+[\\/]"),
)
OUTPUT_REPORT_NAMES = (
    "corpus-manifest.md",
    "failure-catalog.md",
    "fts-baseline.json",
    "slice-results.md",
)
OUTPUT_HASH_MANIFEST_NAME = "artifact-hashes.json"
COMPARISON_SCHEMA_VERSION = "retrieval-mode-comparison.v2"
COMPARISON_EVALUATOR_VERSION = "retrieval-eval.v3"
COMPARISON_MODES = (
    "fts",
    "vector",
    "hybrid_rrf",
    "hybrid_rrf_identity_control",
)
COMPARISON_OUTPUT_NAMES = (
    "latency-and-cost.md",
    "mode-comparison.json",
    "per-slice-quality.md",
    "identity-control.md",
)
COMPARISON_HASH_SCHEMA_VERSION = "retrieval-eval-artifact-hashes.v3"
LOCAL_VECTOR_MODEL = "deterministic-local-feature-hash-v1"
LOCAL_VECTOR_DIMENSIONS = 256
LOCAL_VECTOR_SCORE_DECIMALS = 4


class EvaluationContractError(ValueError):
    pass


@dataclass(frozen=True)
class ChunkFixture:
    chunk_id: str
    heading: str
    content: str

    @property
    def citation_id(self) -> str:
        return f"citation:agent-pet-retrieval-v1:{self.chunk_id}"


@dataclass(frozen=True)
class DocumentFixture:
    document_id: str
    vault: str
    relative_path: str
    source_scope: str
    access_state: str
    fixture_source: str
    chunks: tuple[ChunkFixture, ...]


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    primary_slice: str
    fixture_source: str
    query: str
    expected_relevant_chunk_ids: tuple[str, ...]
    expected_excluded_chunk_ids: tuple[str, ...]
    requested_source_scope: str
    expected_source_scope: str
    answer_label: str
    tags: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class RetrievalCorpus:
    corpus_version: str
    schema_version: str
    random_seed: int
    documents: tuple[DocumentFixture, ...]
    cases: tuple[EvaluationCase, ...]

    @property
    def chunks_by_id(self) -> dict[str, tuple[DocumentFixture, ChunkFixture, int]]:
        return {
            chunk.chunk_id: (document, chunk, index)
            for document in self.documents
            for index, chunk in enumerate(document.chunks)
        }


@dataclass(frozen=True)
class IndexedChunk:
    stable_chunk_id: str
    citation_id: str
    document_id: str
    logical_vault: str
    source_scope: str
    access_state: str
    relative_path: str
    chunk_index: int
    content_hash: str


@dataclass(frozen=True)
class _ModeSpec:
    mode_id: str
    service_mode: str
    required_channels: tuple[str, ...]
    reranker_enabled: bool = False


@dataclass(frozen=True)
class _EvaluationIdentityReranker:
    name: str = "deterministic-identity-control"
    enabled: bool = True
    is_remote: bool = False

    def rerank(self, *, query: str, candidates, timeout_seconds: float) -> RerankerResponse:
        del query, timeout_seconds
        return RerankerResponse(ordered_ids=tuple(candidate.stable_id for candidate in candidates))


class _DeterministicLocalEmbeddings:
    def __init__(self, dimensions: int = LOCAL_VECTOR_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.last_query_ms = 0.0
        self.last_query_vector: list[float] = []
        self.document_embedding_ms = 0.0

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        started = time.perf_counter_ns()
        vectors = [_feature_hash_vector(text, dimensions=self.dimensions) for text in texts]
        self.document_embedding_ms += _elapsed_ms(started)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        started = time.perf_counter_ns()
        vector = _feature_hash_vector(text, dimensions=self.dimensions)
        self.last_query_ms = _elapsed_ms(started)
        self.last_query_vector = vector
        return vector


class _TimedQdrantClient:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.last_query_ms = 0.0

    def query_points(self, *args: Any, **kwargs: Any):
        started = time.perf_counter_ns()
        try:
            return self._client.query_points(*args, **kwargs)
        finally:
            self.last_query_ms = _elapsed_ms(started)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _DeterministicVectorResultOrder:
    def __init__(
        self,
        index: LangChainQdrantVectorIndex,
        database: Database,
        embeddings: _DeterministicLocalEmbeddings,
        timed_client: _TimedQdrantClient,
    ) -> None:
        self._index = index
        self._embeddings = embeddings
        self._timed_client = timed_client
        self._document_vectors: dict[str, list[float]] = {}
        with database.session() as conn:
            rows = conn.execute(
                """
                SELECT
                    note_chunks.id,
                    note_chunks.note_id,
                    note_chunks.vault_id,
                    note_chunks.relative_path,
                    note_chunks.chunk_index,
                    note_chunks.title,
                    note_chunks.heading,
                    note_chunks.content,
                    note_chunks.content_hash
                FROM note_chunks
                JOIN notes
                  ON notes.id = note_chunks.note_id
                 AND notes.vault_id = note_chunks.vault_id
                 AND notes.relative_path = note_chunks.relative_path
                JOIN vector_chunks
                  ON vector_chunks.chunk_id = note_chunks.id
                 AND vector_chunks.content_hash = note_chunks.content_hash
                WHERE notes.status = 'indexed'
                """
            ).fetchall()
        self._stable_keys = {
            str(row["id"]): (
                str(row["relative_path"]),
                int(row["chunk_index"]),
                str(row["content_hash"]),
            )
            for row in rows
        }
        self._authoritative_rows: dict[str, list[tuple[SearchResult, int]]] = defaultdict(list)
        for row in rows:
            vault_id = str(row["vault_id"])
            self._authoritative_rows[vault_id].append(
                (
                    SearchResult(
                        note_id=str(row["note_id"]),
                        chunk_id=str(row["id"]),
                        relative_path=str(row["relative_path"]),
                        title=str(row["title"]),
                        heading=str(row["heading"]) if row["heading"] is not None else None,
                        snippet=str(row["content"]),
                        score=0.0,
                        content_hash=str(row["content_hash"]),
                        vault_id=vault_id,
                    ),
                    int(row["chunk_index"]),
                )
            )

    def search(self, **kwargs: Any):
        requested_top_k = int(kwargs.get("top_k", 0))
        expanded = dict(kwargs)
        expanded["top_k"] = max(requested_top_k, len(self._stable_keys))
        qdrant_results = self._index.search(**expanded)
        if not qdrant_results:
            return []
        generation = qdrant_results[0].generation
        vault_id = str(kwargs.get("vault_id", ""))
        rescore_started = time.perf_counter_ns()
        query_vector = self._embeddings.last_query_vector
        rescored: list[tuple[SearchResult, int]] = []
        for result, chunk_index in self._authoritative_rows.get(vault_id, []):
            document_vector = self._document_vectors.get(result.content_hash or "")
            if document_vector is None:
                document_vector = _feature_hash_vector(
                    result.snippet,
                    dimensions=self._embeddings.dimensions,
                )
                if result.content_hash:
                    self._document_vectors[result.content_hash] = document_vector
            score = sum(left * right for left, right in zip(query_vector, document_vector, strict=True))
            rescored.append(
                (
                    replace(
                        result,
                        score=round(score, LOCAL_VECTOR_SCORE_DECIMALS),
                        generation=generation,
                    ),
                    chunk_index,
                )
            )
        self._timed_client.last_query_ms = _rounded(
            self._timed_client.last_query_ms + _elapsed_ms(rescore_started)
        )
        ordered = sorted(
            rescored,
            key=lambda item: (
                -round(float(item[0].score), LOCAL_VECTOR_SCORE_DECIMALS),
                item[0].relative_path,
                item[1],
                item[0].content_hash or "",
            ),
        )
        return [result for result, _ in ordered[:requested_top_k]]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._index, name)


def load_corpus(dataset_path: Path) -> RetrievalCorpus:
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvaluationContractError("dataset root must be an object")
    schema_version = _required_str(raw, "schema_version")
    if schema_version != DATASET_SCHEMA_VERSION:
        raise EvaluationContractError(
            f"unsupported dataset schema: {schema_version!r}; expected {DATASET_SCHEMA_VERSION!r}"
        )
    corpus_version = _required_str(raw, "corpus_version")
    random_seed = raw.get("random_seed", DEFAULT_RANDOM_SEED)
    if not isinstance(random_seed, int):
        raise EvaluationContractError("random_seed must be an integer")

    raw_documents = raw.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise EvaluationContractError("documents must be a non-empty list")
    documents: list[DocumentFixture] = []
    document_ids: set[str] = set()
    chunk_ids: set[str] = set()
    fixture_text_parts: list[str] = []
    for raw_document in raw_documents:
        if not isinstance(raw_document, dict):
            raise EvaluationContractError("every document must be an object")
        document_id = _required_str(raw_document, "document_id")
        if document_id in document_ids:
            raise EvaluationContractError(f"duplicate document_id: {document_id}")
        document_ids.add(document_id)
        vault = _required_str(raw_document, "vault")
        if vault not in {"primary", "foreign"}:
            raise EvaluationContractError(f"invalid logical vault for {document_id}: {vault}")
        relative_path = _required_str(raw_document, "relative_path").replace("\\", "/")
        _validate_relative_markdown_path(relative_path)
        source_scope = _required_str(raw_document, "source_scope")
        if source_scope not in SEARCHABLE_SCOPES - {"all"} | {"pending_memory", "ignored"}:
            raise EvaluationContractError(f"invalid source_scope for {document_id}: {source_scope}")
        classified_scope = _classify_source_scope(relative_path)
        if classified_scope != source_scope:
            raise EvaluationContractError(
                f"source_scope/path mismatch for {document_id}: declared={source_scope}, classified={classified_scope}"
            )
        access_state = _required_str(raw_document, "access_state")
        if access_state not in ACCESS_STATES:
            raise EvaluationContractError(f"invalid access_state for {document_id}: {access_state}")
        fixture_source = _required_str(raw_document, "fixture_source")
        if not fixture_source.startswith("synthetic://"):
            raise EvaluationContractError(f"fixture_source must be synthetic for {document_id}")
        raw_chunks = raw_document.get("chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            raise EvaluationContractError(f"document {document_id} must contain chunks")
        chunks: list[ChunkFixture] = []
        for raw_chunk in raw_chunks:
            if not isinstance(raw_chunk, dict):
                raise EvaluationContractError(f"document {document_id} contains a non-object chunk")
            chunk = ChunkFixture(
                chunk_id=_required_str(raw_chunk, "chunk_id"),
                heading=_required_str(raw_chunk, "heading"),
                content=_required_str(raw_chunk, "content"),
            )
            if chunk.chunk_id in chunk_ids:
                raise EvaluationContractError(f"duplicate chunk_id: {chunk.chunk_id}")
            chunk_ids.add(chunk.chunk_id)
            chunks.append(chunk)
            fixture_text_parts.extend((chunk.heading, chunk.content))
        documents.append(
            DocumentFixture(
                document_id=document_id,
                vault=vault,
                relative_path=relative_path,
                source_scope=source_scope,
                access_state=access_state,
                fixture_source=fixture_source,
                chunks=tuple(chunks),
            )
        )

    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationContractError("cases must be a non-empty list")
    cases: list[EvaluationCase] = []
    case_ids: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise EvaluationContractError("every case must be an object")
        case_id = _required_str(raw_case, "case_id")
        if case_id in case_ids:
            raise EvaluationContractError(f"duplicate case_id: {case_id}")
        case_ids.add(case_id)
        primary_slice = _required_str(raw_case, "primary_slice")
        if primary_slice not in PRIMARY_SLICE_MINIMUMS:
            raise EvaluationContractError(f"unknown primary_slice for {case_id}: {primary_slice}")
        fixture_source = _required_str(raw_case, "fixture_source")
        if not fixture_source.startswith("synthetic://"):
            raise EvaluationContractError(f"fixture_source must be synthetic for {case_id}")
        query = _required_str(raw_case, "query")
        relevant = _required_string_tuple(raw_case, "expected_relevant_chunk_ids")
        excluded = _required_string_tuple(raw_case, "expected_excluded_chunk_ids")
        if set(relevant) & set(excluded):
            raise EvaluationContractError(f"case {case_id} has IDs that are both relevant and excluded")
        unknown_ids = (set(relevant) | set(excluded)) - chunk_ids
        if unknown_ids:
            raise EvaluationContractError(f"case {case_id} references unknown chunks: {sorted(unknown_ids)}")
        requested_scope = _required_str(raw_case, "requested_source_scope")
        if requested_scope not in SEARCHABLE_SCOPES:
            raise EvaluationContractError(f"invalid requested_source_scope for {case_id}: {requested_scope}")
        expected_scope = _required_str(raw_case, "expected_source_scope")
        if expected_scope not in EXPECTED_SCOPES:
            raise EvaluationContractError(f"invalid expected_source_scope for {case_id}: {expected_scope}")
        answer_label = _required_str(raw_case, "answer_label")
        if answer_label not in ANSWER_LABELS:
            raise EvaluationContractError(f"invalid answer_label for {case_id}: {answer_label}")
        if answer_label == "answerable" and not relevant:
            raise EvaluationContractError(f"answerable case {case_id} must have relevant chunks")
        if answer_label == "no_evidence" and relevant:
            raise EvaluationContractError(f"no-evidence case {case_id} cannot have relevant chunks")
        if answer_label == "no_evidence" and expected_scope != "none":
            raise EvaluationContractError(f"no-evidence case {case_id} must expect source scope 'none'")
        tags = _required_string_tuple(raw_case, "tags")
        if not tags:
            raise EvaluationContractError(f"case {case_id} must contain at least one tag")
        rationale = _required_str(raw_case, "rationale")
        fixture_text_parts.extend((query, rationale))
        cases.append(
            EvaluationCase(
                case_id=case_id,
                primary_slice=primary_slice,
                fixture_source=fixture_source,
                query=query,
                expected_relevant_chunk_ids=relevant,
                expected_excluded_chunk_ids=excluded,
                requested_source_scope=requested_scope,
                expected_source_scope=expected_scope,
                answer_label=answer_label,
                tags=tags,
                rationale=rationale,
            )
        )

    corpus = RetrievalCorpus(
        corpus_version=corpus_version,
        schema_version=schema_version,
        random_seed=random_seed,
        documents=tuple(documents),
        cases=tuple(cases),
    )
    _validate_dataset_contract(corpus, fixture_text_parts)
    return corpus


def run_fts_evaluation(
    *,
    dataset_path: Path,
    work_dir: Path,
    output_dir: Path,
    run_count: int = 1,
    require_final_gates: bool = False,
) -> dict[str, Any]:
    if run_count < 1:
        raise EvaluationContractError("run_count must be at least 1")
    dataset_path = dataset_path.resolve()
    corpus = load_corpus(dataset_path)
    random.seed(corpus.random_seed)
    run_id = _new_run_id()
    run_dir = work_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    primary_vault = run_dir / "primary-vault"
    foreign_vault = run_dir / "foreign-vault"
    primary_vault.mkdir()
    foreign_vault.mkdir()
    _materialize_corpus(corpus, primary_vault=primary_vault, foreign_vault=foreign_vault)

    database = Database(run_dir / "retrieval-eval.sqlite3")
    service = RetrievalService(database)
    migration_names = service.initialize()
    primary_vault_id = service.bind_vault(str(primary_vault), name="TASK-1204 synthetic primary")
    foreign_vault_id = service.bind_vault(str(foreign_vault), name="TASK-1204 synthetic foreign")
    index_started = time.perf_counter_ns()
    primary_rebuild = service.rebuild_index(primary_vault_id)
    foreign_rebuild = service.rebuild_index(foreign_vault_id)
    index_build_ms = _elapsed_ms(index_started)
    if primary_rebuild.status != "success" or foreign_rebuild.status != "success":
        raise EvaluationContractError("synthetic index rebuild failed")

    indexed_chunks = _map_indexed_chunks(
        corpus,
        database,
        logical_vault_ids={"primary": primary_vault_id, "foreign": foreign_vault_id},
    )
    warmup_latencies: list[float] = []
    for case in corpus.cases[:WARMUP_QUERY_COUNT]:
        started = time.perf_counter_ns()
        service.search(
            vault_id=primary_vault_id,
            query=case.query,
            top_k=TOP_K,
            source_scope=case.requested_source_scope,
            mode="fts",
        )
        warmup_latencies.append(_elapsed_ms(started))

    case_results: list[dict[str, Any]] = []
    all_measured_latencies: list[float] = []
    for case in corpus.cases:
        run_results: list[dict[str, Any]] = []
        for _ in range(run_count):
            started = time.perf_counter_ns()
            response = service.search(
                vault_id=primary_vault_id,
                query=case.query,
                top_k=TOP_K,
                source_scope=case.requested_source_scope,
                mode="fts",
            )
            if response.metadata.get("retrieval_mode") != "fts" or any(
                result.retrieval_mode != "fts" for result in response.results
            ):
                raise EvaluationContractError(
                    f"case {case.case_id} did not remain on the strict FTS channel"
                )
            latency_ms = _elapsed_ms(started)
            all_measured_latencies.append(latency_ms)
            run_results.append(
                _score_case_run(
                    case,
                    response.results,
                    indexed_chunks=indexed_chunks,
                    latency_ms=latency_ms,
                )
            )
        case_results.append(_aggregate_case_runs(case, run_results))

    metrics = _aggregate_quality_metrics(case_results)
    slice_results = _aggregate_slice_metrics(corpus, case_results)
    grounding_hooks = score_grounding_hooks(corpus, observations=())
    safety = _aggregate_safety(case_results, grounding_hooks)
    latency = {
        "unit": "milliseconds",
        "warmup_query_count": WARMUP_QUERY_COUNT,
        "warmup_query_ms": [_rounded(value) for value in warmup_latencies],
        "cold_index_build_ms": _rounded(index_build_ms),
        "measurement_count": len(all_measured_latencies),
        "p50": _rounded(_nearest_rank_percentile(all_measured_latencies, 0.50)),
        "p95": _rounded(_nearest_rank_percentile(all_measured_latencies, 0.95)),
        "hard_max": _rounded(max(all_measured_latencies, default=0.0)),
    }
    gate_results = _evaluate_final_gates(
        metrics=metrics,
        slice_results=slice_results,
        safety=safety,
        grounding_hooks=grounding_hooks,
        latency=latency,
    )
    failures = _build_failure_catalog(corpus, case_results)
    backend_root = Path(__file__).resolve().parents[2]
    configuration = {
        "mode": "fts",
        "requested_mode": "fts",
        "effective_mode": "fts",
        "completed_channels": ["fts"],
        "fallback_used": False,
        "fallback_reason": None,
        "top_k": TOP_K,
        "prompt_top_k": PROMPT_TOP_K,
        "run_count": run_count,
        "random_seed": corpus.random_seed,
        "temperature": 0.0,
        "warmup_query_count": WARMUP_QUERY_COUNT,
        "measurement_method": "time.perf_counter_ns; nearest-rank p50/p95; three excluded warm-ups",
        "normalizer_query_plan_version": "production-note-repository-current-checkout",
        "chunker_version": "production-markdown-chunker-current-checkout",
        "index_generation": "sqlite-fts5-unicode61-migration-001",
        "feature_flags": {
            "vector": False,
            "reranker": False,
            "answer_generation": False,
            "external_provider": False,
        },
    }
    input_hashes = {
        "corpus_sha256": _sha256_file(dataset_path),
        "evaluator_sha256": _sha256_file(Path(__file__).resolve()),
        "configuration_sha256": _sha256_json(configuration),
        "production_retrieval_sha256": _sha256_file(backend_root / "app/services/retrieval.py"),
        "production_repository_sha256": _sha256_file(backend_root / "app/repositories/storage.py"),
        "production_chunker_sha256": _sha256_file(backend_root / "app/storage/markdown.py"),
        "production_fts_schema_sha256": _sha256_file(backend_root / "migrations/001_initial_storage.sql"),
    }
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "status": "baseline_complete",
        "claim_boundary": "FTS-only L2 synthetic baseline; no vector, reranker, answer judge, provider, or real user data",
        "corpus": {
            "schema_version": corpus.schema_version,
            "corpus_version": corpus.corpus_version,
            "case_count": len(corpus.cases),
            "document_count": len(corpus.documents),
            "chunk_count": len(corpus.chunks_by_id),
            "distinct_answerable_gold_set_count": len(
                {
                    tuple(sorted(case.expected_relevant_chunk_ids))
                    for case in corpus.cases
                    if case.answer_label == "answerable"
                }
            ),
            "query_weighting": "case-macro; query variants sharing a gold set remain separate labelled cases",
            "synthetic_only": True,
            "primary_slice_counts": dict(sorted(Counter(case.primary_slice for case in corpus.cases).items())),
        },
        "configuration": configuration,
        "environment": _environment_metadata(),
        "input_hashes": input_hashes,
        "index": {
            "migrations_applied": migration_names,
            "primary_files_seen": primary_rebuild.files_seen,
            "primary_files_indexed": primary_rebuild.files_indexed,
            "foreign_files_seen": foreign_rebuild.files_seen,
            "foreign_files_indexed": foreign_rebuild.files_indexed,
            "stable_id_mapping": "logical_vault + relative_path + chunk_index + content_hash",
        },
        "metrics": metrics,
        "grounding_hooks": grounding_hooks,
        "safety": safety,
        "latency": latency,
        "slice_results": slice_results,
        "case_results": case_results,
        "failure_count": len(failures),
        "final_gates": {
            "requested": require_final_gates,
            "passed": all(item["passed"] for item in gate_results),
            "results": gate_results,
        },
    }
    _write_report_artifacts(
        output_dir=output_dir.resolve(),
        corpus=corpus,
        report=report,
        failures=failures,
    )
    return report


def run_mode_comparison(
    *,
    dataset_path: Path,
    work_dir: Path,
    output_dir: Path,
    run_count: int = 1,
    require_final_gates: bool = False,
) -> dict[str, Any]:
    if run_count < 1:
        raise EvaluationContractError("run_count must be at least 1")
    dataset_path = dataset_path.resolve()
    corpus = load_corpus(dataset_path)
    run_id = _new_run_id()
    run_dir = work_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    primary_vault = run_dir / "primary-vault"
    foreign_vault = run_dir / "foreign-vault"
    primary_vault.mkdir()
    foreign_vault.mkdir()
    _materialize_corpus(corpus, primary_vault=primary_vault, foreign_vault=foreign_vault)

    database = Database(run_dir / "retrieval-eval.sqlite3")
    bootstrap_service = RetrievalService(database)
    migration_names = bootstrap_service.initialize()
    primary_vault_id = bootstrap_service.bind_vault(str(primary_vault), name="TASK-1206 synthetic primary")
    foreign_vault_id = bootstrap_service.bind_vault(str(foreign_vault), name="TASK-1206 synthetic foreign")
    index_started = time.perf_counter_ns()
    primary_rebuild = bootstrap_service.rebuild_index(primary_vault_id)
    foreign_rebuild = bootstrap_service.rebuild_index(foreign_vault_id)
    sqlite_index_build_ms = _elapsed_ms(index_started)
    if primary_rebuild.status != "success" or foreign_rebuild.status != "success":
        raise EvaluationContractError("synthetic index rebuild failed")
    indexed_chunks = _map_indexed_chunks(
        corpus,
        database,
        logical_vault_ids={"primary": primary_vault_id, "foreign": foreign_vault_id},
    )

    vector_index, embeddings, timed_client, vector_sync = _build_local_vector_generation(
        database=database,
        run_dir=run_dir,
        vault_ids=(primary_vault_id, foreign_vault_id),
    )
    snapshot_sha256 = _logical_snapshot_hash(database)
    mode_specs = (
        _ModeSpec("fts", "fts", ("fts",)),
        _ModeSpec("vector", "vector", ("vector",)),
        _ModeSpec("hybrid_rrf", "hybrid", ("fts", "vector")),
        _ModeSpec(
            "hybrid_rrf_identity_control",
            "hybrid",
            ("fts", "vector"),
            reranker_enabled=True,
        ),
    )
    shared_invariants = {
        "corpus_sha256": _sha256_file(dataset_path),
        "sqlite_snapshot_sha256": snapshot_sha256,
        "vector_model": LOCAL_VECTOR_MODEL,
        "vector_dimensions": LOCAL_VECTOR_DIMENSIONS,
        "vector_score_decimals": LOCAL_VECTOR_SCORE_DECIMALS,
        "vector_generations": {
            vault_id: vector_sync[vault_id]["generation"] for vault_id in sorted(vector_sync)
        },
        "filters": "production lifecycle, permission, source-scope, Vault, generation, and content-hash filters",
        "top_k": TOP_K,
        "run_count": run_count,
        "random_seed": corpus.random_seed,
        "warmup_query_count": WARMUP_QUERY_COUNT,
        "measurement_method": "perf_counter_ns with nearest-rank p50/p95; errors retained",
    }
    shared_invariants_sha256 = _sha256_json(shared_invariants)
    mode_reports: dict[str, dict[str, Any]] = {}
    for spec in mode_specs:
        reranker = _EvaluationIdentityReranker() if spec.reranker_enabled else None
        service = RetrievalService(database, vector_index=vector_index, reranker=reranker)
        warmups = []
        for case in corpus.cases[:WARMUP_QUERY_COUNT]:
            started = time.perf_counter_ns()
            service.search(
                vault_id=primary_vault_id,
                query=case.query,
                top_k=TOP_K,
                source_scope=case.requested_source_scope,
                mode=spec.service_mode,
            )
            warmups.append(_elapsed_ms(started))

        case_results: list[dict[str, Any]] = []
        stage_measurements: dict[str, list[float]] = defaultdict(list)
        strict_failures: list[dict[str, str]] = []
        fallback_count = 0
        for case in corpus.cases:
            per_run = []
            for _ in range(run_count):
                started = time.perf_counter_ns()
                response = service.search(
                    vault_id=primary_vault_id,
                    query=case.query,
                    top_k=TOP_K,
                    source_scope=case.requested_source_scope,
                    mode=spec.service_mode,
                )
                total_ms = _elapsed_ms(started)
                strict_success, strict_reason = _strict_mode_success(response.metadata, spec)
                if not strict_success:
                    strict_failures.append({"case_id": case.case_id, "reason": strict_reason})
                fallback_used = bool(response.metadata.get("fallback_reason")) or not strict_success
                fallback_count += int(fallback_used)
                stage_latency = _comparison_stage_latency(
                    response.metadata,
                    total_ms=total_ms,
                    embedding_ms=embeddings.last_query_ms if "vector" in spec.required_channels else 0.0,
                    vector_local_search_ms=(
                        timed_client.last_query_ms if "vector" in spec.required_channels else 0.0
                    ),
                )
                for stage, value in stage_latency.items():
                    stage_measurements[stage].append(value)
                scored = _score_case_run(
                    case,
                    response.results if strict_success else (),
                    indexed_chunks=indexed_chunks,
                    latency_ms=total_ms,
                )
                scored.update(
                    {
                        "strict_channel_success": strict_success,
                        "strict_failure_reason": strict_reason if not strict_success else None,
                        "requested_mode": spec.mode_id,
                        "effective_mode": response.metadata.get("effective_mode"),
                        "completed_channels": list(response.metadata.get("completed_channels", [])),
                        "fallback_used": fallback_used,
                        "fallback_reason": response.metadata.get("fallback_reason"),
                        "stage_latency_ms": stage_latency,
                    }
                )
                per_run.append(scored)
            aggregated = _aggregate_case_runs(case, per_run)
            aggregated["strict_channel_success"] = all(
                bool(run["strict_channel_success"]) for run in per_run
            )
            aggregated["strict_failure_reasons"] = sorted(
                {str(run["strict_failure_reason"]) for run in per_run if run["strict_failure_reason"]}
            )
            aggregated["requested_mode"] = spec.mode_id
            aggregated["effective_modes"] = sorted({str(run["effective_mode"]) for run in per_run})
            aggregated["completed_channels"] = sorted(
                {channel for run in per_run for channel in run["completed_channels"]}
            )
            aggregated["fallback_count"] = sum(int(run["fallback_used"]) for run in per_run)
            aggregated["stage_latency_ms"] = {
                stage: [_rounded(float(run["stage_latency_ms"][stage])) for run in per_run]
                for stage in per_run[0]["stage_latency_ms"]
            }
            case_results.append(aggregated)

        metrics = _aggregate_quality_metrics(case_results)
        slice_results = _aggregate_slice_metrics(corpus, case_results)
        grounding_hooks = score_grounding_hooks(corpus, observations=())
        safety = _aggregate_safety(case_results, grounding_hooks)
        latency = {
            "unit": "milliseconds",
            "warmup_query_count": WARMUP_QUERY_COUNT,
            "warmup_total_ms": [_rounded(value) for value in warmups],
            "stages": {
                stage: _latency_summary(values) for stage, values in sorted(stage_measurements.items())
            },
        }
        configuration = {
            "mode_id": spec.mode_id,
            "service_mode": spec.service_mode,
            "required_channels": list(spec.required_channels),
            "reranker": "diagnostic_identity_control" if spec.reranker_enabled else "disabled",
            "vector_model": LOCAL_VECTOR_MODEL,
            "vector_dimensions": LOCAL_VECTOR_DIMENSIONS,
            "external_provider": False,
            "top_k": TOP_K,
            "run_count": run_count,
            "random_seed": corpus.random_seed,
        }
        mode_reports[spec.mode_id] = {
            "configuration": configuration,
            "configuration_sha256": _sha256_json(configuration),
            "shared_invariants_sha256": shared_invariants_sha256,
            "metrics": metrics,
            "safety": safety,
            "latency": latency,
            "cost": {
                "external_request_count": 0,
                "transmitted_bytes": 0,
                "external_cost_usd": 0.0,
                "provider_usage": None,
                "provider_unit_price": None,
            },
            "errors": {
                "strict_channel_failure_count": len(strict_failures),
                "strict_channel_failures": strict_failures,
                "provider_error_count": 0,
                "local_error_count": len(strict_failures),
                "timeout_count": 0,
                "fallback_count": fallback_count,
            },
            "slice_results": slice_results,
            "case_results": case_results,
            "failed_case_ids": [
                str(result["case_id"]) for result in case_results if _case_failed(result)
            ],
        }

    comparisons = _build_mode_comparisons(mode_reports)
    identity_control = _identity_control_observation(mode_reports)
    comparison_controls_passed = bool(
        comparisons["hybrid_rrf_vs_fts"]["no_ascii_overlap_gate_passed"]
        and comparisons["hybrid_rrf_vs_fts"]["exact_non_regression_gate_passed"]
    )
    report: dict[str, Any] = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "evaluator_version": COMPARISON_EVALUATOR_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "status": "comparison_complete",
        "claim_boundary": (
            "L2 synthetic local comparison using production SQLite, Qdrant lifecycle, RRF, and a "
            "deterministic feature-hash vector control; no real provider or production-mode promotion"
        ),
        "corpus": {
            "schema_version": corpus.schema_version,
            "corpus_version": corpus.corpus_version,
            "case_count": len(corpus.cases),
            "document_count": len(corpus.documents),
            "chunk_count": len(corpus.chunks_by_id),
            "synthetic_only": True,
        },
        "shared_invariants": shared_invariants,
        "shared_invariants_sha256": shared_invariants_sha256,
        "environment": _environment_metadata(),
        "index": {
            "migrations_applied": migration_names,
            "sqlite_index_build_ms": _rounded(sqlite_index_build_ms),
            "vector_document_embedding_ms": _rounded(embeddings.document_embedding_ms),
            "vector_sync": vector_sync,
        },
        "modes": mode_reports,
        "comparisons": comparisons,
        "identity_control": identity_control,
        "selected_default": {
            "agent_mode": "fts",
            "fallback_mode": "fts",
            "decision": "retain",
            "reasons": [
                "deterministic feature-hash vectors are evaluation controls, not a production semantic model",
                "the identity reranker is a diagnostic control, not an adoption candidate",
                "TASK-1207 evidence and citation gates are not yet evaluated",
            ],
        },
        "final_gates": {
            "requested": require_final_gates,
            "status": "aspirational",
            "passed": False,
            "control_results_passed": comparison_controls_passed,
            "reason": (
                "production promotion requires a real embedding/reranker candidate and TASK-1207 evidence; "
                "deterministic character-hash controls cannot satisfy this aspirational gate"
            ),
        },
    }
    _write_comparison_artifacts(output_dir=output_dir.resolve(), report=report)
    return report


def _build_local_vector_generation(
    *,
    database: Database,
    run_dir: Path,
    vault_ids: Sequence[str],
) -> tuple[
    _DeterministicVectorResultOrder,
    _DeterministicLocalEmbeddings,
    _TimedQdrantClient,
    dict[str, dict[str, Any]],
]:
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise EvaluationContractError("local Qdrant dependency is unavailable") from exc
    embeddings = _DeterministicLocalEmbeddings()
    try:
        raw_client = QdrantClient(location=":memory:")
    except TypeError:
        raw_client = QdrantClient(":memory:")
    timed_client = _TimedQdrantClient(raw_client)
    vector_index = LangChainQdrantVectorIndex(
        VectorIndexConfig(
            enabled=True,
            root_path=run_dir / "vector-index",
            collection_name="task_1206_eval",
            embedding_model=LOCAL_VECTOR_MODEL,
            embeddings=embeddings,
            embedding_provider="deterministic-local",
            embedding_dimensions=LOCAL_VECTOR_DIMENSIONS,
            normalization="l2",
            chunker_version="markdown-chunker.v1",
            index_version="vector-index.v1",
            privacy_policy_version="embedding-privacy.v1",
            transport_class="local",
            embedding_configured=True,
            corpus_version="agent-pet-retrieval-synthetic-v1.0.0",
            qdrant_client=timed_client,
        )
    )
    sync_results: dict[str, dict[str, Any]] = {}
    for vault_id in vault_ids:
        with database.session() as conn:
            sync = vector_index.reconcile(conn=conn, vault_id=vault_id, local_privacy=False)
        if sync.status not in {"success", "unchanged"} or not sync.generation:
            raise EvaluationContractError(
                f"deterministic local vector generation failed: {sync.reason or sync.status}"
            )
        sync_results[vault_id] = asdict(sync)
    return (
        _DeterministicVectorResultOrder(vector_index, database, embeddings, timed_client),
        embeddings,
        timed_client,
        sync_results,
    )


def _feature_hash_vector(text: str, *, dimensions: int) -> list[float]:
    normalized = " ".join(text.casefold().split())
    features: list[tuple[str, float]] = []
    for token in re.findall(r"\w+", normalized, flags=re.UNICODE):
        features.append((f"token:{token}", 2.0))
    compact = normalized.replace(" ", "_")
    for width in (2, 3):
        features.extend(
            (f"char{width}:{compact[index:index + width]}", 1.0)
            for index in range(max(0, len(compact) - width + 1))
        )
    vector = [0.0] * dimensions
    for feature, weight in features:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = -1.0 if digest[4] & 1 else 1.0
        vector[bucket] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _logical_snapshot_hash(database: Database) -> str:
    with database.session() as conn:
        note_rows = conn.execute(
            """
            SELECT vault_id, relative_path, chunk_index, content_hash
            FROM note_chunks
            ORDER BY vault_id, relative_path, chunk_index
            """
        ).fetchall()
        vector_rows = conn.execute(
            """
            SELECT vault_id, relative_path, content_hash, embedding_model
            FROM vector_chunks
            ORDER BY vault_id, relative_path, content_hash
            """
        ).fetchall()
    return _sha256_json(
        {
            "notes": [tuple(row) for row in note_rows],
            "vectors": [tuple(row) for row in vector_rows],
        }
    )


def _strict_mode_success(metadata: Mapping[str, Any], spec: _ModeSpec) -> tuple[bool, str]:
    completed = set(str(value) for value in metadata.get("completed_channels", []))
    required = set(spec.required_channels)
    if not required.issubset(completed):
        return False, "required_channel_missing"
    fallback_reason = metadata.get("fallback_reason")
    if fallback_reason:
        return False, str(fallback_reason)
    expected_effective = "hybrid" if len(required) > 1 else next(iter(required))
    if metadata.get("effective_mode") != expected_effective:
        return False, "effective_mode_mismatch"
    reranker = metadata.get("reranker")
    reranker_status = reranker.get("status") if isinstance(reranker, Mapping) else None
    if spec.reranker_enabled and reranker_status != "applied":
        return False, "reranker_not_applied"
    return True, "ok"


def _comparison_stage_latency(
    metadata: Mapping[str, Any],
    *,
    total_ms: float,
    embedding_ms: float,
    vector_local_search_ms: float,
) -> dict[str, float]:
    raw = metadata.get("retrieval_latency_ms")
    latency = raw if isinstance(raw, Mapping) else {}
    vector_adapter_total = float(latency.get("vector_adapter_total", 0.0) or 0.0)
    return {
        "embedding": _rounded(max(0.0, embedding_ms)),
        "vector_local_search": _rounded(max(0.0, vector_local_search_ms)),
        "vector_adapter_residual": _rounded(
            max(0.0, vector_adapter_total - embedding_ms - vector_local_search_ms)
        ),
        "fts_search": _rounded(max(0.0, float(latency.get("fts_search", 0.0) or 0.0))),
        "filter_fusion_dedupe": _rounded(
            max(0.0, float(latency.get("filter_fusion_dedupe", 0.0) or 0.0))
        ),
        "reranker": _rounded(max(0.0, float(latency.get("reranker", 0.0) or 0.0))),
        "total": _rounded(max(0.0, total_ms)),
    }


def _latency_summary(values: Sequence[float]) -> dict[str, Any]:
    measured = [float(value) for value in values]
    return {
        "measurement_count": len(measured),
        "p50": _rounded(_nearest_rank_percentile(measured, 0.50)),
        "p95": _rounded(_nearest_rank_percentile(measured, 0.95)),
        "hard_max": _rounded(max(measured, default=0.0)),
    }


def _build_mode_comparisons(mode_reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    fts = mode_reports["fts"]
    hybrid = mode_reports["hybrid_rrf"]
    identity_control = mode_reports["hybrid_rrf_identity_control"]
    overlap_delta = _slice_metric(hybrid, "no_ascii_keyword_overlap", "recall_at_10") - _slice_metric(
        fts, "no_ascii_keyword_overlap", "recall_at_10"
    )
    exact_regression = _slice_metric(fts, "exact_keyword_identifier", "recall_at_10") - _slice_metric(
        hybrid, "exact_keyword_identifier", "recall_at_10"
    )
    identity_ndcg_delta = float(identity_control["metrics"]["ndcg_at_10"] or 0.0) - float(
        hybrid["metrics"]["ndcg_at_10"] or 0.0
    )
    identity_recall_regression = float(hybrid["metrics"]["recall_at_10"] or 0.0) - float(
        identity_control["metrics"]["recall_at_10"] or 0.0
    )
    return {
        "hybrid_rrf_vs_fts": {
            "no_ascii_overlap_recall_at_10_delta": _rounded(overlap_delta),
            "no_ascii_overlap_gate_threshold": 0.15,
            "no_ascii_overlap_gate_passed": overlap_delta + 1e-12 >= 0.15,
            "exact_query_recall_at_10_regression": _rounded(exact_regression),
            "exact_non_regression_threshold": 0.02,
            "exact_non_regression_gate_passed": exact_regression - 1e-12 <= 0.02,
        },
        "identity_control_vs_hybrid_rrf": {
            "diagnostic_only": True,
            "ndcg_at_10_delta": _rounded(identity_ndcg_delta),
            "recall_at_10_regression": _rounded(identity_recall_regression),
        },
    }


def _slice_metric(report: Mapping[str, Any], primary_slice: str, metric: str) -> float:
    result = next(
        item for item in report["slice_results"] if item["primary_slice"] == primary_slice
    )
    return float(result[metric] or 0.0)


def _identity_control_observation(
    mode_reports: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    baseline = mode_reports["hybrid_rrf"]
    control = mode_reports["hybrid_rrf_identity_control"]
    return {
        "schema_version": "identity-reranker-control.v1",
        "candidate": "deterministic-identity-control",
        "status": "diagnostic_only",
        "adoption_eligible": False,
        "production_enabled": False,
        "ndcg_delta": _rounded(
            float(control["metrics"]["ndcg_at_10"] or 0.0)
            - float(baseline["metrics"]["ndcg_at_10"] or 0.0)
        ),
        "recall_regression": _rounded(
            float(baseline["metrics"]["recall_at_10"] or 0.0)
            - float(control["metrics"]["recall_at_10"] or 0.0)
        ),
        "reason": "identity control preserves input order and cannot support an adoption conclusion",
        "external_provider": False,
        "external_request_count": 0,
        "transmitted_bytes": 0,
        "external_cost_usd": 0.0,
    }


def score_grounding_hooks(
    corpus: RetrievalCorpus,
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Score later answer/citation observations without invoking a judge or model.

    Each observation may contain rendered_citation_ids, accepted_citation_ids,
    and atomic_claims. An atomic claim is a mapping with citation_ids plus
    boolean supported and faithful fields. TASK-1204 supplies no observations;
    later tasks can use this frozen hook without changing retrieval labels.
    """

    if not observations:
        return {
            "status": "not_evaluated",
            "hook_version": "grounding-hooks.v1",
            "final_gate_eligible": False,
            "observation_case_count": 0,
            "missing_case_ids": [case.case_id for case in corpus.cases],
            "citation_precision": None,
            "local_fact_citation_coverage": None,
            "grounded_answer_faithfulness": None,
            "local_fact_claims_with_empty_evidence": None,
            "fabricated_citations": None,
            "task_failures": [],
            "reason": "FTS retrieval baseline emits candidates but does not generate or judge answers",
        }
    cases_by_id = {case.case_id: case for case in corpus.cases}
    observation_case_ids: list[str] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise EvaluationContractError("every grounding observation must be an object")
        case_id = str(observation.get("case_id", ""))
        if case_id not in cases_by_id:
            raise EvaluationContractError(f"grounding observation references unknown case: {case_id}")
        observation_case_ids.append(case_id)
    duplicate_case_ids = sorted(
        case_id for case_id, count in Counter(observation_case_ids).items() if count > 1
    )
    if duplicate_case_ids:
        raise EvaluationContractError(
            f"grounding observations contain duplicate cases: {duplicate_case_ids}"
        )
    missing_case_ids = sorted(set(cases_by_id) - set(observation_case_ids))
    complete_corpus_coverage = not missing_case_ids and len(observations) == len(corpus.cases)
    known_citation_ids = {
        chunk.citation_id for _, chunk, _ in corpus.chunks_by_id.values()
    }
    citation_precision_cases: list[float] = []
    coverage_cases: list[float] = []
    faithfulness_cases: list[float] = []
    empty_evidence_claims = 0
    fabricated_citations = 0
    task_failures: list[str] = []
    for observation in observations:
        case_id = str(observation.get("case_id", ""))
        case = cases_by_id[case_id]
        rendered = _string_list(observation.get("rendered_citation_ids", []), "rendered_citation_ids")
        accepted = set(_string_list(observation.get("accepted_citation_ids", []), "accepted_citation_ids"))
        relevant_citations = {
            corpus.chunks_by_id[chunk_id][1].citation_id for chunk_id in case.expected_relevant_chunk_ids
        }
        observed_citation_ids = set(rendered) | accepted
        if rendered:
            correct = sum(1 for citation_id in rendered if citation_id in accepted & relevant_citations)
            citation_precision_cases.append(correct / len(rendered))
        raw_claims = observation.get("atomic_claims", [])
        if not isinstance(raw_claims, list):
            raise EvaluationContractError("atomic_claims must be a list")
        claims: list[Mapping[str, Any]] = []
        for raw_claim in raw_claims:
            if not isinstance(raw_claim, Mapping):
                raise EvaluationContractError("every atomic claim must be an object")
            claims.append(raw_claim)
        if case.answer_label == "answerable" and not claims:
            fabricated_citations += len(observed_citation_ids - known_citation_ids)
            coverage_cases.append(0.0)
            faithfulness_cases.append(0.0)
            task_failures.append(case.case_id)
            continue
        if not claims:
            fabricated_citations += len(observed_citation_ids - known_citation_ids)
            continue
        cited_claims = 0
        faithful_claims = 0
        for claim in claims:
            claim_citations = set(_string_list(claim.get("citation_ids", []), "atomic_claims.citation_ids"))
            observed_citation_ids.update(claim_citations)
            has_supporting_citation = bool(claim_citations & accepted & relevant_citations)
            cited_claims += int(has_supporting_citation)
            supported = _required_bool(claim, "supported")
            faithful = _required_bool(claim, "faithful")
            faithful_claims += int(has_supporting_citation and supported and faithful)
            if not accepted:
                empty_evidence_claims += 1
        fabricated_citations += len(observed_citation_ids - known_citation_ids)
        coverage_cases.append(cited_claims / len(claims))
        faithfulness_cases.append(faithful_claims / len(claims))
    return {
        "status": "evaluated_complete" if complete_corpus_coverage else "incomplete",
        "hook_version": "grounding-hooks.v1",
        "final_gate_eligible": complete_corpus_coverage,
        "observation_case_count": len(observations),
        "missing_case_ids": missing_case_ids,
        "citation_precision": _macro_or_none(citation_precision_cases),
        "local_fact_citation_coverage": _macro_or_none(coverage_cases),
        "grounded_answer_faithfulness": _macro_or_none(faithfulness_cases),
        "local_fact_claims_with_empty_evidence": empty_evidence_claims,
        "fabricated_citations": fabricated_citations,
        "task_failures": sorted(set(task_failures)),
    }


def _validate_dataset_contract(corpus: RetrievalCorpus, fixture_text_parts: Sequence[str]) -> None:
    if len(corpus.cases) < sum(PRIMARY_SLICE_MINIMUMS.values()):
        raise EvaluationContractError("dataset must contain at least 60 cases")
    slice_counts = Counter(case.primary_slice for case in corpus.cases)
    for primary_slice, minimum in PRIMARY_SLICE_MINIMUMS.items():
        if slice_counts[primary_slice] < minimum:
            raise EvaluationContractError(
                f"primary slice {primary_slice} has {slice_counts[primary_slice]} cases; requires {minimum}"
            )
    chunks_by_id = corpus.chunks_by_id
    for case in corpus.cases:
        if case.answer_label == "answerable":
            for chunk_id in case.expected_relevant_chunk_ids:
                document, _, _ = chunks_by_id[chunk_id]
                if document.vault != "primary" or document.access_state != "active":
                    raise EvaluationContractError(
                        f"relevant chunk {chunk_id} for {case.case_id} is not active primary evidence"
                    )
                if case.expected_source_scope != document.source_scope:
                    raise EvaluationContractError(
                        f"expected source scope mismatch for {case.case_id} and {chunk_id}"
                    )
        if case.primary_slice == "no_ascii_keyword_overlap":
            query_terms = _meaningful_ascii_terms(case.query)
            evidence_terms: set[str] = set()
            for chunk_id in case.expected_relevant_chunk_ids:
                _, chunk, _ = chunks_by_id[chunk_id]
                evidence_terms.update(_meaningful_ascii_terms(f"{chunk.heading} {chunk.content}"))
            overlap = query_terms & evidence_terms
            if overlap:
                raise EvaluationContractError(
                    f"lexical non-overlap case {case.case_id} has meaningful ASCII term overlap: "
                    f"{sorted(overlap)}"
                )
    fixture_text = "\n".join(fixture_text_parts)
    for pattern in PROHIBITED_FIXTURE_PATTERNS:
        if pattern.search(fixture_text):
            raise EvaluationContractError(f"fixture text matches prohibited credential pattern: {pattern.pattern}")


def _materialize_corpus(
    corpus: RetrievalCorpus,
    *,
    primary_vault: Path,
    foreign_vault: Path,
) -> None:
    roots = {"primary": primary_vault, "foreign": foreign_vault}
    for document in corpus.documents:
        root = roots[document.vault]
        destination = root.joinpath(*PurePosixPath(document.relative_path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        markdown = "\n\n".join(
            f"## {chunk.heading}\n\n{chunk.content}" for chunk in document.chunks
        )
        destination.write_text(f"{markdown}\n", encoding="utf-8")


def _map_indexed_chunks(
    corpus: RetrievalCorpus,
    database: Database,
    *,
    logical_vault_ids: Mapping[str, str],
) -> dict[str, IndexedChunk]:
    documents_by_key = {(document.vault, document.relative_path): document for document in corpus.documents}
    db_to_logical = {db_id: logical for logical, db_id in logical_vault_ids.items()}
    indexed: dict[str, IndexedChunk] = {}
    matched_stable_ids: set[str] = set()
    with database.session() as conn:
        rows = conn.execute(
            """
            SELECT id, vault_id, relative_path, chunk_index, content_hash
            FROM note_chunks
            ORDER BY vault_id, relative_path, chunk_index
            """
        ).fetchall()
    for row in rows:
        logical_vault = db_to_logical.get(str(row["vault_id"]))
        if logical_vault is None:
            raise EvaluationContractError("isolated database contains an unexpected vault")
        relative_path = str(row["relative_path"]).replace("\\", "/")
        document = documents_by_key.get((logical_vault, relative_path))
        if document is None:
            raise EvaluationContractError(f"indexed unexpected document: {logical_vault}/{relative_path}")
        chunk_index = int(row["chunk_index"])
        if chunk_index >= len(document.chunks):
            raise EvaluationContractError(f"indexed unexpected chunk index: {document.document_id}/{chunk_index}")
        chunk = document.chunks[chunk_index]
        expected_content_hash = hashlib.sha256(
            f"## {chunk.heading}\n\n{chunk.content}".encode("utf-8")
        ).hexdigest()
        if str(row["content_hash"]) != expected_content_hash:
            raise EvaluationContractError(
                f"content hash mismatch for {document.document_id}/{chunk_index}"
            )
        if chunk.chunk_id in matched_stable_ids:
            raise EvaluationContractError(f"stable chunk mapped more than once: {chunk.chunk_id}")
        matched_stable_ids.add(chunk.chunk_id)
        indexed[str(row["id"])] = IndexedChunk(
            stable_chunk_id=chunk.chunk_id,
            citation_id=chunk.citation_id,
            document_id=document.document_id,
            logical_vault=logical_vault,
            source_scope=document.source_scope,
            access_state=document.access_state,
            relative_path=relative_path,
            chunk_index=chunk_index,
            content_hash=str(row["content_hash"]),
        )
    expected_stable_ids = set(corpus.chunks_by_id)
    if matched_stable_ids != expected_stable_ids:
        missing = sorted(expected_stable_ids - matched_stable_ids)
        raise EvaluationContractError(f"not every stable chunk was indexed: {missing}")
    return indexed


def _score_case_run(
    case: EvaluationCase,
    response_results: Sequence[Any],
    *,
    indexed_chunks: Mapping[str, IndexedChunk],
    latency_ms: float,
) -> dict[str, Any]:
    retrieved: list[str] = []
    citations: list[str] = []
    result_scopes: list[str] = []
    inaccessible_hits: list[str] = []
    cross_vault_hits: list[str] = []
    unknown_runtime_chunk_ids: list[str] = []
    for result in response_results:
        indexed = indexed_chunks.get(str(result.chunk_id))
        if indexed is None:
            unknown_runtime_chunk_ids.append(str(result.chunk_id))
            citations.append(f"unmapped:{result.chunk_id}")
            continue
        retrieved.append(indexed.stable_chunk_id)
        citations.append(indexed.citation_id)
        result_scopes.append(str(result.source_scope))
        if indexed.access_state != "active":
            inaccessible_hits.append(indexed.stable_chunk_id)
        if indexed.logical_vault != "primary":
            cross_vault_hits.append(indexed.stable_chunk_id)
    relevant = set(case.expected_relevant_chunk_ids)
    excluded = set(case.expected_excluded_chunk_ids)
    scope_mismatches = []
    if case.expected_source_scope != "none":
        scope_mismatches = [scope for scope in result_scopes if scope != case.expected_source_scope]
    return {
        "retrieved_chunk_ids": retrieved,
        "candidate_citation_ids": citations,
        "latency_ms": latency_ms,
        "recall_at_5": _recall_at_k(retrieved, relevant, 5),
        "recall_at_10": _recall_at_k(retrieved, relevant, 10),
        "precision_at_5": _precision_at_k(retrieved, relevant, 5),
        "mrr_at_10": _mrr_at_k(retrieved, relevant, 10),
        "ndcg_at_10": _ndcg_at_k(retrieved, relevant, 10),
        "no_evidence_correct": case.answer_label == "no_evidence" and not retrieved and not unknown_runtime_chunk_ids,
        "excluded_hits": [chunk_id for chunk_id in retrieved if chunk_id in excluded],
        "inaccessible_hits": inaccessible_hits,
        "cross_vault_hits": cross_vault_hits,
        "unknown_runtime_chunk_ids": unknown_runtime_chunk_ids,
        "source_scope_mismatches": scope_mismatches,
    }


def _aggregate_case_runs(case: EvaluationCase, runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    first_ids = list(runs[0]["retrieved_chunk_ids"])
    deterministic = all(list(run["retrieved_chunk_ids"]) == first_ids for run in runs[1:])
    result: dict[str, Any] = {
        "case_id": case.case_id,
        "primary_slice": case.primary_slice,
        "answer_label": case.answer_label,
        "requested_source_scope": case.requested_source_scope,
        "expected_source_scope": case.expected_source_scope,
        "expected_relevant_chunk_ids": list(case.expected_relevant_chunk_ids),
        "expected_excluded_chunk_ids": list(case.expected_excluded_chunk_ids),
        "retrieved_chunk_ids": first_ids,
        "candidate_citation_ids": list(runs[0]["candidate_citation_ids"]),
        "run_count": len(runs),
        "deterministic": deterministic,
        "latency_ms": [_rounded(float(run["latency_ms"])) for run in runs],
        "recall_at_5": _macro_or_none([run["recall_at_5"] for run in runs]),
        "recall_at_10": _macro_or_none([run["recall_at_10"] for run in runs]),
        "precision_at_5": _macro_or_none([run["precision_at_5"] for run in runs]),
        "mrr_at_10": _macro_or_none([run["mrr_at_10"] for run in runs]),
        "ndcg_at_10": _macro_or_none([run["ndcg_at_10"] for run in runs]),
        "no_evidence_correct": all(bool(run["no_evidence_correct"]) for run in runs),
    }
    for key in (
        "excluded_hits",
        "inaccessible_hits",
        "cross_vault_hits",
        "unknown_runtime_chunk_ids",
        "source_scope_mismatches",
    ):
        result[key] = sorted({value for run in runs for value in run[key]})
    return result


def _aggregate_quality_metrics(case_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    answerable = [result for result in case_results if result["answer_label"] == "answerable"]
    no_evidence = [result for result in case_results if result["answer_label"] == "no_evidence"]
    return {
        "averaging": "macro over eligible cases",
        "answerable_case_count": len(answerable),
        "no_evidence_case_count": len(no_evidence),
        "recall_at_5": _macro_or_none(result["recall_at_5"] for result in answerable),
        "recall_at_10": _macro_or_none(result["recall_at_10"] for result in answerable),
        "precision_at_5": _macro_or_none(result["precision_at_5"] for result in answerable),
        "mrr_at_10": _macro_or_none(result["mrr_at_10"] for result in answerable),
        "ndcg_at_10": _macro_or_none(result["ndcg_at_10"] for result in answerable),
        "no_evidence_accuracy": _macro_or_none(
            1.0 if result["no_evidence_correct"] else 0.0 for result in no_evidence
        ),
        "deterministic_case_rate": _macro_or_none(1.0 if result["deterministic"] else 0.0 for result in case_results),
    }


def _aggregate_slice_metrics(
    corpus: RetrievalCorpus,
    case_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    results_by_id = {str(result["case_id"]): result for result in case_results}
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for case in corpus.cases:
        grouped[case.primary_slice].append(results_by_id[case.case_id])
    slice_results: list[dict[str, Any]] = []
    for primary_slice in PRIMARY_SLICE_MINIMUMS:
        results = grouped[primary_slice]
        answerable = [result for result in results if result["answer_label"] == "answerable"]
        no_evidence = [result for result in results if result["answer_label"] == "no_evidence"]
        slice_results.append(
            {
                "primary_slice": primary_slice,
                "case_count": len(results),
                "answerable_case_count": len(answerable),
                "no_evidence_case_count": len(no_evidence),
                "distinct_relevant_set_count": len(
                    {
                        tuple(sorted(result["expected_relevant_chunk_ids"]))
                        for result in answerable
                    }
                ),
                "recall_at_5": _macro_or_none(result["recall_at_5"] for result in answerable),
                "recall_at_10": _macro_or_none(result["recall_at_10"] for result in answerable),
                "precision_at_5": _macro_or_none(result["precision_at_5"] for result in answerable),
                "mrr_at_10": _macro_or_none(result["mrr_at_10"] for result in answerable),
                "ndcg_at_10": _macro_or_none(result["ndcg_at_10"] for result in answerable),
                "no_evidence_accuracy": _macro_or_none(
                    1.0 if result["no_evidence_correct"] else 0.0 for result in no_evidence
                ),
                "failed_case_ids": [
                    str(result["case_id"]) for result in results if _case_failed(result)
                ],
            }
        )
    return slice_results


def _aggregate_safety(
    case_results: Sequence[Mapping[str, Any]],
    grounding_hooks: Mapping[str, Any],
) -> dict[str, Any]:
    retrieval_fabricated = sum(
        len(result["unknown_runtime_chunk_ids"]) for result in case_results
    )
    grounding_fabricated_value = grounding_hooks.get("fabricated_citations")
    grounding_fabricated = (
        int(grounding_fabricated_value)
        if isinstance(grounding_fabricated_value, int)
        else 0
    )
    return {
        "inaccessible_memory_leakage": sum(len(result["inaccessible_hits"]) for result in case_results),
        "expected_excluded_id_leakage": sum(len(result["excluded_hits"]) for result in case_results),
        "cross_vault_leakage": sum(len(result["cross_vault_hits"]) for result in case_results),
        "fabricated_citations": retrieval_fabricated + grounding_fabricated,
        "retrieval_candidate_fabricated_citations": retrieval_fabricated,
        "grounding_fabricated_citations": grounding_hooks.get("fabricated_citations"),
        "source_scope_violations": sum(len(result["source_scope_mismatches"]) for result in case_results),
        "local_fact_claims_with_empty_evidence": grounding_hooks["local_fact_claims_with_empty_evidence"],
        "local_fact_claims_metric_status": grounding_hooks["status"],
        "retrieved_prompt_injection_policy_changes": {
            "status": "not_evaluated",
            "value": None,
            "reason": "retrieval-only baseline does not execute retrieved instructions or route tools",
        },
    }


def _evaluate_final_gates(
    *,
    metrics: Mapping[str, Any],
    slice_results: Sequence[Mapping[str, Any]],
    safety: Mapping[str, Any],
    grounding_hooks: Mapping[str, Any],
    latency: Mapping[str, Any],
) -> list[dict[str, Any]]:
    values = {
        **{name: safety.get(name) for name in FINAL_GATES if name in safety},
        **{name: metrics.get(name) for name in FINAL_GATES if name in metrics},
        "fts_p95_ms": latency["p95"],
        "fts_hard_max_ms": latency["hard_max"],
    }
    gate_results = [
        _gate_result(name, values.get(name), comparator, threshold)
        for name, (comparator, threshold) in FINAL_GATES.items()
    ]
    grounding_gate_eligible = grounding_hooks.get("final_gate_eligible") is True
    for name, (comparator, threshold) in GROUNDING_FINAL_GATES.items():
        value = grounding_hooks.get(name) if grounding_gate_eligible else None
        gate_results.append(_gate_result(name, value, comparator, threshold))
    for slice_result in slice_results:
        if int(slice_result["answerable_case_count"]) == 0:
            continue
        gate_results.append(
            _gate_result(
                f"slice_recall_at_10:{slice_result['primary_slice']}",
                slice_result["recall_at_10"],
                "gte",
                0.80,
            )
        )
    gate_results.extend(
        (
            {
                "name": "retrieved_prompt_injection_policy_changes",
                "value": None,
                "comparator": "eq",
                "threshold": 0.0,
                "passed": False,
                "reason": "retrieval-only baseline does not execute routes, tools, policy, or confirmation",
            },
            {
                "name": "no_ascii_overlap_recall_at_10_delta_vs_fts",
                "value": None,
                "comparator": "gte",
                "threshold": 0.15,
                "passed": False,
                "reason": "requires a later non-FTS candidate on the frozen corpus",
            },
            {
                "name": "exact_query_recall_at_10_regression_vs_fts",
                "value": None,
                "comparator": "lte",
                "threshold": 0.02,
                "passed": False,
                "reason": "requires a later non-FTS candidate on the frozen corpus",
            },
        )
    )
    return gate_results


def _build_failure_catalog(
    corpus: RetrievalCorpus,
    case_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cases_by_id = {case.case_id: case for case in corpus.cases}
    failures: list[dict[str, Any]] = []
    for result in case_results:
        if not _case_failed(result):
            continue
        case = cases_by_id[str(result["case_id"])]
        reasons: list[str] = []
        if case.answer_label == "answerable" and float(result["recall_at_10"] or 0.0) < 1.0:
            reasons.append("missing_expected_relevant_evidence")
        if result["excluded_hits"]:
            reasons.append("expected_excluded_evidence_retrieved")
        if result["inaccessible_hits"]:
            reasons.append("inaccessible_or_superseded_evidence_retrieved")
        if result["cross_vault_hits"]:
            reasons.append("cross_vault_evidence_retrieved")
        if result["unknown_runtime_chunk_ids"]:
            reasons.append("unmapped_runtime_chunk_or_fabricated_citation")
        if result["source_scope_mismatches"]:
            reasons.append("source_scope_mismatch")
        if case.answer_label == "no_evidence" and not result["no_evidence_correct"]:
            reasons.append("no_evidence_case_returned_candidates")
        failures.append(
            {
                "case_id": case.case_id,
                "primary_slice": case.primary_slice,
                "requested_mode": "fts",
                "effective_mode": "fts",
                "fallback_used": False,
                "reasons": reasons,
                "expected_owner_task": _failure_owner(case, reasons),
                "recall_at_10": result["recall_at_10"],
                "expected_relevant_chunk_ids": list(case.expected_relevant_chunk_ids),
                "retrieved_chunk_ids": list(result["retrieved_chunk_ids"]),
                "missing_relevant_chunk_ids": sorted(
                    set(case.expected_relevant_chunk_ids) - set(result["retrieved_chunk_ids"])
                ),
                "excluded_hits": list(result["excluded_hits"]),
            }
        )
    return failures


def _write_comparison_artifacts(*, output_dir: Path, report: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _assert_safe_output_directory(output_dir)
    _validate_existing_comparison_ownership(output_dir)
    paths = {
        "mode-comparison.json": output_dir / "mode-comparison.json",
        "per-slice-quality.md": output_dir / "per-slice-quality.md",
        "latency-and-cost.md": output_dir / "latency-and-cost.md",
        "identity-control.md": output_dir / "identity-control.md",
    }
    _atomic_write_text(
        paths["mode-comparison.json"],
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write_text(paths["per-slice-quality.md"], _render_comparison_slices(report))
    _atomic_write_text(paths["latency-and-cost.md"], _render_latency_and_cost(report))
    _atomic_write_text(paths["identity-control.md"], _render_identity_control(report))
    artifact_hashes = {name: _sha256_file(path) for name, path in sorted(paths.items())}
    _atomic_write_text(
        output_dir / OUTPUT_HASH_MANIFEST_NAME,
        json.dumps(
            {
                "schema_version": COMPARISON_HASH_SCHEMA_VERSION,
                "artifact_profile": "task-1206-mode-comparison",
                "hash_algorithm": "sha256",
                "artifacts": artifact_hashes,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _validate_existing_comparison_ownership(output_dir: Path) -> None:
    target_names = (*COMPARISON_OUTPUT_NAMES, OUTPUT_HASH_MANIFEST_NAME)
    existing = [output_dir / name for name in target_names if _path_entry_exists(output_dir / name)]
    for path in existing:
        _assert_safe_output_file(path)
    if not existing:
        return
    manifest_path = output_dir / OUTPUT_HASH_MANIFEST_NAME
    if not _path_entry_exists(manifest_path):
        raise EvaluationContractError("output directory contains unowned mode-comparison artifacts")
    try:
        ownership = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationContractError("existing comparison ownership manifest is invalid") from exc
    if ownership.get("schema_version") != COMPARISON_HASH_SCHEMA_VERSION:
        raise EvaluationContractError("existing output is not owned by the TASK-1206 evaluator")
    recorded = ownership.get("artifacts")
    if not isinstance(recorded, dict) or set(recorded) != set(COMPARISON_OUTPUT_NAMES):
        raise EvaluationContractError("comparison ownership manifest has an invalid artifact set")
    for name in COMPARISON_OUTPUT_NAMES:
        path = output_dir / name
        if not _path_entry_exists(path):
            raise EvaluationContractError("existing comparison output is incomplete")
        _assert_safe_output_file(path)
        expected_hash = recorded.get(name)
        if not isinstance(expected_hash, str) or _sha256_file(path) != expected_hash.casefold():
            raise EvaluationContractError("existing comparison output failed its ownership hash")


def _render_comparison_slices(report: Mapping[str, Any]) -> str:
    lines = [
        "# TASK-1206 Per-Slice Retrieval Quality",
        "",
        f"- Shared invariants SHA-256: `{report['shared_invariants_sha256']}`",
        "- All modes use one isolated SQLite snapshot, one local Qdrant generation, and identical cases.",
        "",
        "| Mode | Slice | Recall@10 | MRR@10 | nDCG@10 | No-evidence accuracy | Failed cases |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode_id in COMPARISON_MODES:
        for result in report["modes"][mode_id]["slice_results"]:
            lines.append(
                f"| `{mode_id}` | `{result['primary_slice']}` | "
                f"{_display_metric(result['recall_at_10'])} | {_display_metric(result['mrr_at_10'])} | "
                f"{_display_metric(result['ndcg_at_10'])} | "
                f"{_display_metric(result['no_evidence_accuracy'])} | {len(result['failed_case_ids'])} |"
            )
    comparison = report["comparisons"]["hybrid_rrf_vs_fts"]
    lines.extend(
        [
            "",
            "## Fixed promotion checks",
            "",
            f"- No-ASCII-keyword-overlap Recall@10 delta: "
            f"{comparison['no_ascii_overlap_recall_at_10_delta']:.4f} "
            f"(pass: {str(comparison['no_ascii_overlap_gate_passed']).lower()})",
            f"- Exact-query Recall@10 regression: {comparison['exact_query_recall_at_10_regression']:.4f} "
            f"(pass: {str(comparison['exact_non_regression_gate_passed']).lower()})",
            "- Failed cases remain listed in mode-comparison.json; no query was removed from averages.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_latency_and_cost(report: Mapping[str, Any]) -> str:
    lines = [
        "# TASK-1206 Latency and Cost",
        "",
        "| Mode | Stage | Count | p50 ms | p95 ms | hard max ms |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for mode_id in COMPARISON_MODES:
        stages = report["modes"][mode_id]["latency"]["stages"]
        for stage, values in stages.items():
            lines.append(
                f"| `{mode_id}` | `{stage}` | {values['measurement_count']} | "
                f"{values['p50']:.4f} | {values['p95']:.4f} | {values['hard_max']:.4f} |"
            )
    lines.extend(
        [
            "",
            "## External use",
            "",
            "Every mode recorded zero external requests, zero transmitted bytes, USD 0 external cost, "
            "and zero provider errors. The feature-hash embedding and Qdrant instance are local controls.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_identity_control(report: Mapping[str, Any]) -> str:
    control = report["identity_control"]
    lines = [
        "# Identity Reranker Diagnostic Control",
        "",
        f"- Control: `{control['candidate']}`",
        f"- Status: **{str(control['status']).replace('_', ' ').title()}**",
        f"- Adoption eligible: {str(control['adoption_eligible']).lower()}",
        f"- Production enabled: {str(control['production_enabled']).lower()}",
        f"- nDCG@10 delta: {_display_metric(control['ndcg_delta'])}",
        f"- Recall@10 regression: {_display_metric(control['recall_regression'])}",
        "- External requests / bytes / USD: 0 / 0 / 0",
        "",
        f"Reason: {control['reason']}",
    ]
    lines.extend(
        [
            "",
            "The deterministic RRF order remains the fallback. No package, model, endpoint, or paid "
            "reranker was enabled.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report_artifacts(
    *,
    output_dir: Path,
    corpus: RetrievalCorpus,
    report: Mapping[str, Any],
    failures: Sequence[Mapping[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _assert_safe_output_directory(output_dir)
    _validate_existing_output_ownership(output_dir)
    baseline_path = output_dir / "fts-baseline.json"
    manifest_path = output_dir / "corpus-manifest.md"
    slice_path = output_dir / "slice-results.md"
    failure_path = output_dir / "failure-catalog.md"
    _atomic_write_text(
        baseline_path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write_text(manifest_path, _render_corpus_manifest(corpus, report))
    _atomic_write_text(slice_path, _render_slice_results(report))
    _atomic_write_text(failure_path, _render_failure_catalog(failures))
    artifact_hashes = {
        path.name: _sha256_file(path)
        for path in (manifest_path, baseline_path, slice_path, failure_path)
    }
    _atomic_write_text(
        output_dir / OUTPUT_HASH_MANIFEST_NAME,
        json.dumps(
            {
                "schema_version": "retrieval-eval-artifact-hashes.v1",
                "hash_algorithm": "sha256",
                "artifacts": artifact_hashes,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _validate_existing_output_ownership(output_dir: Path) -> None:
    target_paths = [
        *(output_dir / name for name in OUTPUT_REPORT_NAMES),
        output_dir / OUTPUT_HASH_MANIFEST_NAME,
    ]
    existing = [path for path in target_paths if _path_entry_exists(path)]
    for path in existing:
        _assert_safe_output_file(path)
    if not existing:
        return
    hash_manifest_path = output_dir / OUTPUT_HASH_MANIFEST_NAME
    if not _path_entry_exists(hash_manifest_path):
        raise EvaluationContractError(
            "output directory contains unowned retrieval-evaluation report names"
        )
    try:
        ownership = json.loads(hash_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationContractError("existing output ownership manifest is invalid") from exc
    if ownership.get("schema_version") != "retrieval-eval-artifact-hashes.v1":
        raise EvaluationContractError("existing output is not owned by this evaluator contract")
    recorded = ownership.get("artifacts")
    if not isinstance(recorded, dict) or set(recorded) != set(OUTPUT_REPORT_NAMES):
        raise EvaluationContractError("existing output ownership manifest has an invalid artifact set")
    for name in OUTPUT_REPORT_NAMES:
        path = output_dir / name
        if not _path_entry_exists(path):
            raise EvaluationContractError("existing output is incomplete; choose a new output directory")
        _assert_safe_output_file(path)
        expected_hash = recorded.get(name)
        if not isinstance(expected_hash, str) or _sha256_file(path) != expected_hash.casefold():
            raise EvaluationContractError(
                "existing output failed its ownership hash; choose a new output directory"
            )


def _atomic_write_text(path: Path, content: str) -> None:
    _assert_safe_output_target(path)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _assert_safe_output_target(path)
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _assert_safe_output_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise EvaluationContractError("output directory disappeared during evaluation") from exc
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse_metadata(metadata):
        raise EvaluationContractError("output directory must be a regular non-reparse directory")


def _assert_safe_output_target(path: Path) -> None:
    if not _path_entry_exists(path):
        return
    _assert_safe_output_file(path)


def _assert_safe_output_file(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or _is_reparse_metadata(metadata):
        raise EvaluationContractError(
            f"output artifact must be a regular non-reparse file: {path.name}"
        )


def _path_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _is_reparse_metadata(metadata: os.stat_result) -> bool:
    windows_attributes = int(getattr(metadata, "st_file_attributes", 0))
    return stat.S_ISLNK(metadata.st_mode) or bool(windows_attributes & 0x400)


def _render_corpus_manifest(corpus: RetrievalCorpus, report: Mapping[str, Any]) -> str:
    lines = [
        "# TASK-1204 Retrieval Corpus Manifest",
        "",
        f"- Schema: `{corpus.schema_version}`",
        f"- Corpus version: `{corpus.corpus_version}`",
        f"- Cases: {len(corpus.cases)}",
        f"- Documents: {len(corpus.documents)}",
        f"- Stable chunks: {len(corpus.chunks_by_id)}",
        f"- Distinct answerable gold sets: {report['corpus']['distinct_answerable_gold_set_count']}",
        f"- Random seed: {corpus.random_seed}",
        "- Data class: synthetic-only; no diary, chat, credential, or real Vault data",
        "- Citation ID rule: `citation:agent-pet-retrieval-v1:<stable_chunk_id>`",
        "- Runtime mapping: logical vault + relative path + chunk index + content hash",
        "- Weighting: case-macro; labelled query variants may share one gold evidence set",
        "",
        "## Frozen input hashes",
        "",
        "| Input | SHA-256 |",
        "| --- | --- |",
    ]
    for name, digest in report["input_hashes"].items():
        lines.append(f"| `{name}` | `{digest}` |")
    lines.extend(
        [
            "",
            "## Primary slices",
            "",
            "| Primary slice | Cases | Minimum |",
            "| --- | ---: | ---: |",
        ]
    )
    counts = Counter(case.primary_slice for case in corpus.cases)
    for primary_slice, minimum in PRIMARY_SLICE_MINIMUMS.items():
        lines.append(f"| `{primary_slice}` | {counts[primary_slice]} | {minimum} |")
    lines.extend(
        [
            "",
            "The labels are visible and frozen. This is a deterministic design benchmark, not a hidden or unbiased test set.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_slice_results(report: Mapping[str, Any]) -> str:
    lines = [
        "# TASK-1204 FTS Slice Results",
        "",
        "FTS-only baseline. A failed final gate is recorded and is not tuned away.",
        "",
        "| Primary slice | Cases | Recall@5 | Recall@10 | Precision@5 | MRR@10 | nDCG@10 | No-evidence accuracy | Failed cases |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in report["slice_results"]:
        lines.append(
            f"| `{result['primary_slice']}` | {result['case_count']} | "
            f"{_display_metric(result['recall_at_5'])} | {_display_metric(result['recall_at_10'])} | "
            f"{_display_metric(result['precision_at_5'])} | {_display_metric(result['mrr_at_10'])} | "
            f"{_display_metric(result['ndcg_at_10'])} | {_display_metric(result['no_evidence_accuracy'])} | "
            f"{len(result['failed_case_ids'])} |"
        )
    metrics = report["metrics"]
    latency = report["latency"]
    lines.extend(
        [
            "",
            "## Overall",
            "",
            f"- Recall@5: {_display_metric(metrics['recall_at_5'])}",
            f"- Recall@10: {_display_metric(metrics['recall_at_10'])}",
            f"- Precision@5: {_display_metric(metrics['precision_at_5'])}",
            f"- MRR@10: {_display_metric(metrics['mrr_at_10'])}",
            f"- nDCG@10: {_display_metric(metrics['ndcg_at_10'])}",
            f"- No-evidence accuracy: {_display_metric(metrics['no_evidence_accuracy'])}",
            f"- FTS p50/p95/hard max: {latency['p50']} / {latency['p95']} / {latency['hard_max']} ms",
            f"- Final gates passed: {str(report['final_gates']['passed']).lower()}",
            "- Citation precision and grounded-answer faithfulness: not evaluated; frozen hooks exist for TASK-1207.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_failure_catalog(failures: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# TASK-1204 FTS Failure Catalog",
        "",
        f"Recorded failed cases: {len(failures)}",
        "",
        "| Case | Slice | Mode | Fallback | Failure | Expected owner | Recall@10 | Expected relevant IDs | Actual retrieved IDs | Missing relevant IDs | Excluded hits |",
        "| --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for failure in failures:
        lines.append(
            "| `{case_id}` | `{primary_slice}` | `{requested_mode}->{effective_mode}` | `{fallback}` | "
            "{reasons} | `{expected_owner_task}` | {recall_at_10} | {expected} | {actual} | {missing} | {excluded} |".format(
                case_id=failure["case_id"],
                primary_slice=failure["primary_slice"],
                requested_mode=failure["requested_mode"],
                effective_mode=failure["effective_mode"],
                fallback=str(failure["fallback_used"]).lower(),
                reasons=", ".join(failure["reasons"]),
                expected_owner_task=failure["expected_owner_task"],
                recall_at_10=_display_metric(failure["recall_at_10"]),
                expected=", ".join(
                    f"`{value}`" for value in failure["expected_relevant_chunk_ids"]
                ) or "-",
                actual=", ".join(
                    f"`{value}`" for value in failure["retrieved_chunk_ids"]
                ) or "-",
                missing=", ".join(f"`{value}`" for value in failure["missing_relevant_chunk_ids"]) or "-",
                excluded=", ".join(f"`{value}`" for value in failure["excluded_hits"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _failure_owner(case: EvaluationCase, reasons: Sequence[str]) -> str:
    safety_reasons = {
        "expected_excluded_evidence_retrieved",
        "inaccessible_or_superseded_evidence_retrieved",
        "cross_vault_evidence_retrieved",
        "unmapped_runtime_chunk_or_fabricated_citation",
        "source_scope_mismatch",
        "no_evidence_case_returned_candidates",
    }
    if safety_reasons & set(reasons):
        return "TASK-1207"
    if case.primary_slice in {
        "no_ascii_keyword_overlap",
        "chinese_conversational",
        "cross_expression_zh_en",
        "temporal_date_entity",
    }:
        return "TASK-1205"
    if "missing_expected_relevant_evidence" in reasons:
        return "TASK-1206"
    return "TASK-1204"


def _case_failed(result: Mapping[str, Any]) -> bool:
    if result["answer_label"] == "answerable" and float(result["recall_at_10"] or 0.0) < 1.0:
        return True
    if result["answer_label"] == "no_evidence" and not result["no_evidence_correct"]:
        return True
    return any(
        result[key]
        for key in (
            "excluded_hits",
            "inaccessible_hits",
            "cross_vault_hits",
            "unknown_runtime_chunk_ids",
            "source_scope_mismatches",
        )
    )


def _gate_result(name: str, value: Any, comparator: str, threshold: float) -> dict[str, Any]:
    if value is None:
        return {
            "name": name,
            "value": None,
            "comparator": comparator,
            "threshold": threshold,
            "passed": False,
            "reason": "not evaluated",
        }
    numeric_value = float(value)
    passed = {
        "eq": numeric_value == threshold,
        "gte": numeric_value >= threshold,
        "lte": numeric_value <= threshold,
    }[comparator]
    return {
        "name": name,
        "value": _rounded(numeric_value),
        "comparator": comparator,
        "threshold": threshold,
        "passed": passed,
    }


def _recall_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    return len(relevant & set(retrieved[:k])) / len(relevant)


def _precision_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    return len(relevant & set(retrieved[:k])) / k


def _mrr_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved[:k], start=1)
        if chunk_id in relevant
    )
    ideal_count = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal if ideal else 0.0


def _nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _macro_or_none(values: Iterable[Any]) -> float | None:
    eligible = [float(value) for value in values if value is not None]
    if not eligible:
        return None
    return _rounded(sum(eligible) / len(eligible))


def _meaningful_ascii_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9]+", text.casefold()):
        if len(token) <= 2 or token in MEANINGFUL_STOP_WORDS or token.isdigit():
            continue
        terms.add(token)
        if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            terms.add(token[:-1])
    return terms


def _validate_relative_markdown_path(relative_path: str) -> None:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or path.suffix.casefold() != ".md":
        raise EvaluationContractError(f"fixture path must be a relative Markdown path: {relative_path}")
    if not path.parts or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts):
        raise EvaluationContractError(f"unsafe fixture path: {relative_path}")
    if ":" in relative_path:
        raise EvaluationContractError(f"fixture path cannot contain a drive or URI separator: {relative_path}")


def _required_str(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationContractError(f"{key} must be a non-empty string")
    return value.strip()


def _required_string_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key)
    return tuple(_string_list(value, key))


def _required_bool(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if type(value) is not bool:
        raise EvaluationContractError(f"{key} must be a boolean")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise EvaluationContractError(f"{label} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _environment_metadata() -> dict[str, Any]:
    return {
        "operating_system": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "logical_cpu_count": os.cpu_count(),
        "machine_identity_recorded": False,
        "external_provider": None,
        "chat_model": None,
        "embedding_model": None,
        "external_request_count": 0,
        "transmitted_bytes": 0,
        "external_cost_usd": 0.0,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"run-{timestamp}-{uuid.uuid4().hex[:8]}"


def _elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _display_metric(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen retrieval evaluation")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--mode", choices=("fts", "all"), default="fts")
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-count", type=int, default=1)
    parser.add_argument("--require-final-gates", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runner = run_mode_comparison if args.mode == "all" else run_fts_evaluation
        report = runner(
            dataset_path=args.dataset,
            work_dir=args.work_dir,
            output_dir=args.output_dir,
            run_count=args.run_count,
            require_final_gates=args.require_final_gates,
        )
    except (EvaluationContractError, json.JSONDecodeError, OSError) as exc:
        print(f"retrieval evaluation failed: {exc}", file=sys.stderr)
        return 1
    if args.mode == "all":
        summary = {
            "status": report["status"],
            "corpus_version": report["corpus"]["corpus_version"],
            "case_count": report["corpus"]["case_count"],
            "modes": list(report["modes"]),
            "selected_agent_default": report["selected_default"]["agent_mode"],
            "identity_control_status": report["identity_control"]["status"],
            "shared_invariants_sha256": report["shared_invariants_sha256"],
            "final_gates_requested": report["final_gates"]["requested"],
            "final_gates_passed": report["final_gates"]["passed"],
        }
    else:
        summary = {
            "status": report["status"],
            "corpus_version": report["corpus"]["corpus_version"],
            "case_count": report["corpus"]["case_count"],
            "mode": report["configuration"]["effective_mode"],
            "recall_at_10": report["metrics"]["recall_at_10"],
            "mrr_at_10": report["metrics"]["mrr_at_10"],
            "no_evidence_accuracy": report["metrics"]["no_evidence_accuracy"],
            "fts_p95_ms": report["latency"]["p95"],
            "failure_count": report["failure_count"],
            "final_gates_requested": report["final_gates"]["requested"],
            "final_gates_passed": report["final_gates"]["passed"],
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_final_gates and not report["final_gates"]["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
