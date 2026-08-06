from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from app.services.vector_index import (
    _HNSW_INDEXING_THRESHOLD_KB,
    LangChainQdrantVectorIndex,
    VectorIndexConfig,
    _SnapshotChunk,
    _normalize_vector,
    _snapshot_hash,
)
from app.utils.hash import sha256_hex


SCHEMA_VERSION = "agent-pet-vector-query-scaling.v1"
DEFAULT_COLLECTION_SIZES = (2_048, 32_768)
DEFAULT_DIMENSIONS = 64
DEFAULT_WARMUP_QUERIES = 20
DEFAULT_MEASURED_QUERIES = 80
DEFAULT_MAX_LINEAR_FRACTION = 0.65
_MIN_COLLECTION_SIZE_RATIO = 8.0
_UPSERT_BATCH_SIZE = 512


class VectorScalingContractError(RuntimeError):
    pass


class _DeterministicEmbeddings:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed_query(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        return _deterministic_vector(seed, self.dimensions)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


@dataclass(frozen=True)
class _PreparedCollection:
    index: LangChainQdrantVectorIndex
    collection_name: str
    vault_id: str
    point_count: int
    indexed_vectors_count: int


def _deterministic_vector(seed: int, dimensions: int) -> list[float]:
    state = seed & 0xFFFFFFFF
    values: list[float] = []
    for _ in range(dimensions):
        state = (1_664_525 * state + 1_013_904_223) & 0xFFFFFFFF
        values.append((state / 2**31) - 1.0)
    return _normalize_vector(values, "l2")


def _nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise VectorScalingContractError("latency sample set must not be empty")
    if not 0 < percentile <= 1:
        raise VectorScalingContractError("percentile must be in (0, 1]")
    ordered = sorted(float(value) for value in values)
    return ordered[max(0, math.ceil(len(ordered) * percentile) - 1)]


def evaluate_scaling(
    *,
    small_size: int,
    large_size: int,
    small_p95_ms: float,
    large_p95_ms: float,
    max_linear_fraction: float = DEFAULT_MAX_LINEAR_FRACTION,
) -> dict[str, Any]:
    if small_size <= 0 or large_size <= small_size:
        raise VectorScalingContractError("collection sizes must be positive and strictly increasing")
    if small_p95_ms <= 0 or large_p95_ms <= 0:
        raise VectorScalingContractError("p95 measurements must be positive")
    if not 0 < max_linear_fraction < 1:
        raise VectorScalingContractError("max_linear_fraction must be in (0, 1)")
    size_ratio = large_size / small_size
    if size_ratio < _MIN_COLLECTION_SIZE_RATIO:
        raise VectorScalingContractError(
            f"collection size ratio must be at least {_MIN_COLLECTION_SIZE_RATIO:g}x"
        )
    latency_ratio = large_p95_ms / small_p95_ms
    linear_fraction = latency_ratio / size_ratio
    return {
        "collection_size_ratio": round(size_ratio, 6),
        "p95_latency_ratio": round(latency_ratio, 6),
        "linear_growth_fraction": round(linear_fraction, 6),
        "max_linear_growth_fraction": max_linear_fraction,
        "criterion": "p95_latency_ratio / collection_size_ratio <= max_linear_growth_fraction",
        "passed": linear_fraction <= max_linear_fraction,
    }


def run_vector_query_scaling(
    *,
    qdrant_url: str,
    collection_sizes: Sequence[int] = DEFAULT_COLLECTION_SIZES,
    dimensions: int = DEFAULT_DIMENSIONS,
    warmup_queries: int = DEFAULT_WARMUP_QUERIES,
    measured_queries: int = DEFAULT_MEASURED_QUERIES,
    optimizer_timeout_seconds: float = 180.0,
    max_linear_fraction: float = DEFAULT_MAX_LINEAR_FRACTION,
) -> dict[str, Any]:
    _validate_configuration(
        qdrant_url=qdrant_url,
        collection_sizes=collection_sizes,
        dimensions=dimensions,
        warmup_queries=warmup_queries,
        measured_queries=measured_queries,
        optimizer_timeout_seconds=optimizer_timeout_seconds,
    )
    try:
        from qdrant_client import QdrantClient, models
    except ImportError as exc:
        raise VectorScalingContractError(
            "vector extra is required: install the backend with .[vector]"
        ) from exc

    client = QdrantClient(url=qdrant_url, timeout=max(30, int(optimizer_timeout_seconds)))
    try:
        server = client.info()
    except Exception as exc:
        raise VectorScalingContractError(f"Qdrant Server is not reachable at {qdrant_url}") from exc

    prepared: list[_PreparedCollection] = []
    try:
        for point_count in collection_sizes:
            prepared.append(
                _prepare_collection(
                    client=client,
                    models=models,
                    point_count=int(point_count),
                    dimensions=dimensions,
                    optimizer_timeout_seconds=optimizer_timeout_seconds,
                )
            )

        for item in prepared:
            # The first call performs the generation-wide integrity validation.
            # It is intentionally outside the steady-state query measurements.
            results = item.index.search(
                query="vector scaling integrity warmup",
                vault_id=item.vault_id,
                top_k=5,
            )
            if not results:
                raise VectorScalingContractError("warmup query returned no vector results")
            for query_number in range(warmup_queries):
                item.index.search(
                    query=f"vector scaling warmup {query_number % 17}",
                    vault_id=item.vault_id,
                    top_k=5,
                )

        latency_samples: dict[int, list[float]] = {
            item.point_count: [] for item in prepared
        }
        for query_number in range(measured_queries):
            ordered = prepared if query_number % 2 == 0 else list(reversed(prepared))
            for item in ordered:
                started_ns = time.perf_counter_ns()
                results = item.index.search(
                    query=f"vector scaling measured query {query_number % 23}",
                    vault_id=item.vault_id,
                    top_k=5,
                )
                elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
                if not results:
                    raise VectorScalingContractError("measured query returned no vector results")
                latency_samples[item.point_count].append(elapsed_ms)

        measurements: list[dict[str, Any]] = []
        for item in prepared:
            samples = latency_samples[item.point_count]
            measurements.append(
                {
                    "point_count": item.point_count,
                    "indexed_vectors_count": item.indexed_vectors_count,
                    "sample_count": len(samples),
                    "p50_ms": round(_nearest_rank_percentile(samples, 0.50), 6),
                    "p95_ms": round(_nearest_rank_percentile(samples, 0.95), 6),
                    "max_ms": round(max(samples), 6),
                    "samples_ms": [round(value, 6) for value in samples],
                }
            )
        small = measurements[0]
        large = measurements[-1]
        scaling = evaluate_scaling(
            small_size=int(small["point_count"]),
            large_size=int(large["point_count"]),
            small_p95_ms=float(small["p95_ms"]),
            large_p95_ms=float(large["p95_ms"]),
            max_linear_fraction=max_linear_fraction,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "passed" if scaling["passed"] else "failed",
            "claim_boundary": (
                "steady-state Agent Pet vector search against an actual Qdrant Server over localhost; "
                "one generation-wide validation, collection construction, optimizer time, remote embeddings, "
                "quality, and non-local network latency are excluded"
            ),
            "configuration": {
                "collection_sizes": list(collection_sizes),
                "dimensions": dimensions,
                "warmup_queries_per_collection": warmup_queries,
                "measured_queries_per_collection": measured_queries,
                "hnsw_indexing_threshold_kb": _HNSW_INDEXING_THRESHOLD_KB,
                "max_linear_growth_fraction": max_linear_fraction,
            },
            "environment": {
                "operating_system": platform.system(),
                "os_release": platform.release(),
                "architecture": platform.machine(),
                "python_version": platform.python_version(),
                "qdrant_client_version": importlib.metadata.version("qdrant-client"),
                "qdrant_server_version": str(getattr(server, "version", "unknown")),
                "qdrant_url_recorded": _redacted_qdrant_endpoint(qdrant_url),
            },
            "measurements": measurements,
            "scaling": scaling,
        }
    finally:
        for item in prepared:
            try:
                client.delete_collection(item.collection_name)
            except Exception:
                pass
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _prepare_collection(
    *,
    client: Any,
    models: Any,
    point_count: int,
    dimensions: int,
    optimizer_timeout_seconds: float,
) -> _PreparedCollection:
    run_id = uuid4().hex
    vault_id = f"fix-backlog-16-{point_count}-{run_id}"
    generation = uuid4().hex
    embeddings = _DeterministicEmbeddings(dimensions)
    index = LangChainQdrantVectorIndex(
        VectorIndexConfig(
            enabled=True,
            root_path=Path(".tmp") / "unused-vector-scaling",
            collection_name=f"fix_backlog_16_{run_id}",
            embedding_model="deterministic-vector-scaling-v1",
            embeddings=embeddings,
            embedding_provider="deterministic-local-control",
            embedding_dimensions=dimensions,
            normalization="l2",
            chunker_version="vector-scaling-v1",
            index_version="vector-scaling-v1",
            privacy_policy_version="synthetic-public-v1",
            transport_class="local",
            embedding_configured=True,
            corpus_version="fix-backlog-16-synthetic-v1",
            qdrant_client=client,
        )
    )
    chunks = [_synthetic_chunk(vault_id, point_number) for point_number in range(point_count)]
    collection_name = index._generation_collection(vault_id, generation)
    metadata = index._metadata(
        vault_id=vault_id,
        generation=generation,
        dimensions=dimensions,
        corpus_hash=_snapshot_hash(chunks),
        point_count=point_count,
    )
    building_metadata = dict(metadata)
    building_metadata["lifecycle_status"] = "building"
    index._create_generation(collection_name, dimensions, building_metadata)

    for start in range(0, point_count, _UPSERT_BATCH_SIZE):
        points = []
        for point_number, chunk in enumerate(
            chunks[start : start + _UPSERT_BATCH_SIZE],
            start=start,
        ):
            points.append(
                models.PointStruct(
                    id=chunk.point_id,
                    vector=_deterministic_vector(point_number + 1, dimensions),
                    payload={
                        "page_content": chunk.content,
                        "metadata": {
                            "authoritative_chunk_id": chunk.chunk_id,
                            "content_hash": chunk.content_hash,
                            "vault_id": vault_id,
                            "note_id": chunk.note_id,
                            "relative_path": chunk.relative_path,
                            "title": chunk.title,
                            "heading": "",
                            "generation": generation,
                        },
                    },
                )
            )
        client.upsert(collection_name=collection_name, points=points, wait=True)

    index._update_collection_metadata(collection_name, metadata)
    index._promote_alias(vault_id, collection_name)
    indexed_vectors_count = _wait_for_collection_ready(
        client=client,
        collection_name=collection_name,
        point_count=point_count,
        dimensions=dimensions,
        timeout_seconds=optimizer_timeout_seconds,
    )
    return _PreparedCollection(
        index=index,
        collection_name=collection_name,
        vault_id=vault_id,
        point_count=point_count,
        indexed_vectors_count=indexed_vectors_count,
    )


def _synthetic_chunk(vault_id: str, point_number: int) -> _SnapshotChunk:
    content = f"synthetic vector scaling document {point_number} token {point_number % 997}"
    return _SnapshotChunk(
        chunk_id=f"chunk-{point_number:08d}",
        note_id=f"note-{point_number:08d}",
        vault_id=vault_id,
        relative_path=f"Wiki/Scaling/{point_number:08d}.md",
        title=f"Scaling document {point_number}",
        heading=None,
        content=content,
        content_hash=sha256_hex(content),
    )


def _wait_for_collection_ready(
    *,
    client: Any,
    collection_name: str,
    point_count: int,
    dimensions: int,
    timeout_seconds: float,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    requires_hnsw = point_count * dimensions * 4 > _HNSW_INDEXING_THRESHOLD_KB * 1024
    last_state = "unknown"
    while time.monotonic() < deadline:
        info = client.get_collection(collection_name)
        status = _enum_text(getattr(info, "status", None))
        optimizer_status = _enum_text(getattr(info, "optimizer_status", None))
        actual_count = int(getattr(info, "points_count", 0) or 0)
        indexed_count = int(getattr(info, "indexed_vectors_count", 0) or 0)
        optimizer_ready = optimizer_status == "ok" or optimizer_status.endswith("ok")
        hnsw_ready = not requires_hnsw or indexed_count >= math.floor(point_count * 0.90)
        if status == "green" and optimizer_ready and actual_count == point_count and hnsw_ready:
            return indexed_count
        last_state = (
            f"status={status}, optimizer={optimizer_status}, points={actual_count}, "
            f"indexed={indexed_count}, expected={point_count}"
        )
        time.sleep(0.5)
    raise VectorScalingContractError(
        f"Qdrant collection did not become query-ready within {timeout_seconds:g}s: {last_state}"
    )


def _enum_text(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().casefold()


def _redacted_qdrant_endpoint(qdrant_url: str) -> str:
    from urllib.parse import urlsplit

    parsed = urlsplit(qdrant_url)
    return f"{parsed.scheme}://{parsed.hostname or 'unknown'}:{parsed.port or 6333}"


def _validate_configuration(
    *,
    qdrant_url: str,
    collection_sizes: Sequence[int],
    dimensions: int,
    warmup_queries: int,
    measured_queries: int,
    optimizer_timeout_seconds: float,
) -> None:
    if not qdrant_url.startswith(("http://", "https://")):
        raise VectorScalingContractError("qdrant_url must target an actual Qdrant Server over HTTP(S)")
    if len(collection_sizes) < 2:
        raise VectorScalingContractError("at least two collection sizes are required")
    if any(size <= 0 for size in collection_sizes):
        raise VectorScalingContractError("collection sizes must be positive")
    if list(collection_sizes) != sorted(set(collection_sizes)):
        raise VectorScalingContractError("collection sizes must be unique and strictly increasing")
    if collection_sizes[-1] / collection_sizes[0] < _MIN_COLLECTION_SIZE_RATIO:
        raise VectorScalingContractError(
            f"collection size ratio must be at least {_MIN_COLLECTION_SIZE_RATIO:g}x"
        )
    if dimensions <= 0 or warmup_queries < 0 or measured_queries < 20:
        raise VectorScalingContractError(
            "dimensions must be positive, warmup non-negative, and measured queries at least 20"
        )
    if optimizer_timeout_seconds <= 0:
        raise VectorScalingContractError("optimizer timeout must be positive")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure Agent Pet steady-state vector query scaling against Qdrant Server"
    )
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument(
        "--collection-sizes",
        type=int,
        nargs="+",
        default=list(DEFAULT_COLLECTION_SIZES),
    )
    parser.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    parser.add_argument("--warmup-queries", type=int, default=DEFAULT_WARMUP_QUERIES)
    parser.add_argument("--measured-queries", type=int, default=DEFAULT_MEASURED_QUERIES)
    parser.add_argument("--optimizer-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-linear-fraction", type=float, default=DEFAULT_MAX_LINEAR_FRACTION)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_vector_query_scaling(
            qdrant_url=args.qdrant_url,
            collection_sizes=args.collection_sizes,
            dimensions=args.dimensions,
            warmup_queries=args.warmup_queries,
            measured_queries=args.measured_queries,
            optimizer_timeout_seconds=args.optimizer_timeout_seconds,
            max_linear_fraction=args.max_linear_fraction,
        )
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError, VectorScalingContractError) as exc:
        print(f"vector query scaling failed: {exc}", file=sys.stderr)
        return 1
    summary = {
        "status": report["status"],
        "measurements": [
            {
                "point_count": item["point_count"],
                "indexed_vectors_count": item["indexed_vectors_count"],
                "p95_ms": item["p95_ms"],
            }
            for item in report["measurements"]
        ],
        "scaling": report["scaling"],
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["scaling"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
