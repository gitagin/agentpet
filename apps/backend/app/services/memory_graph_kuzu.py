"""Rebuildable, read-only Kuzu acceleration for the LLM Wiki graph.

SQLite owns entities, facts, evidence, lifecycle and permissions.  Kuzu is
written only by a full rebuild from a consistent SQLite snapshot and is read
through a read-only connection.  Query results are always intersected with a
fresh SQLite traversal before they are returned to a caller.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, Sequence

from app.services.memory_entity_graph import (
    RELATION_TYPES,
    EntityGraphError,
    EntityRelation,
    MemoryEntityGraphStore,
    ProjectionGeneration,
    _fact_row_recallable,
    _relation_row_recallable,
)
from app.services.memory_taxonomy import LOW_CONFIDENCE_THRESHOLD
from app.services.wiki_reconciler import reconcile_wiki_vault
from app.storage.database import open_database_connection


logger = logging.getLogger(__name__)

KUZU_SCHEMA_VERSION = "llmwiki-graph-v2"
KUZU_BACKEND = "kuzu"
KUZU_EDGE_TYPES = frozenset(RELATION_TYPES)
_SAFE_RISK_TIERS = frozenset({"low", "medium"})
_INTERNAL_EDGE_TYPES = frozenset({"claims", "evidence", "wiki_binding"})


class KuzuProjectionError(RuntimeError):
    """Raised only for invalid rebuild inputs, never for query degradation."""


ProjectionSource = Literal["kuzu", "sqlite"]


@dataclass(frozen=True, slots=True)
class KuzuRebuildReport:
    generation: ProjectionGeneration
    database_path: str | None
    source_revision: int
    node_count: int
    edge_count: int
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class KuzuTraversalResult:
    relations: tuple[EntityRelation, ...]
    source: ProjectionSource
    generation_id: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _AuthoritySnapshot:
    revision: int
    entities: tuple[Mapping[str, object], ...]
    facts: tuple[Mapping[str, object], ...]
    relations: tuple[Mapping[str, object], ...]
    evidence: tuple[Mapping[str, object], ...]
    wiki_bindings: tuple[Mapping[str, object], ...]


class KuzuGraphService:
    """Build and query a generation-aware Kuzu projection."""

    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        graph_root: str | Path,
        *,
        vault_id: str | None = None,
        vault_root: str | Path | None = None,
    ) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.graph_root = Path(graph_root)
        self.vault_id = vault_id
        self.vault_root = Path(vault_root).resolve(strict=False) if vault_root is not None else None
        self.authority = MemoryEntityGraphStore(self.conn)

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def rebuild(self, *, schema_version: str = KUZU_SCHEMA_VERSION) -> KuzuRebuildReport:
        """Create a complete temporary generation and publish it if unchanged."""
        reconcile_error = self._reconcile_wiki_source()
        generation = self.authority.start_projection_generation(schema_version=schema_version)
        if reconcile_error is not None:
            finished = self.authority.finish_projection_generation(
                generation.id,
                success=False,
                error_code=reconcile_error,
            )
            return KuzuRebuildReport(
                generation=finished,
                database_path=None,
                source_revision=self.authority.source_revision(),
                node_count=0,
                edge_count=0,
                fallback_reason=reconcile_error,
            )
        final_path = self._generation_path(generation.id)
        temporary_path = self._temporary_path(generation.id)
        self._remove_database(temporary_path)
        try:
            snapshot = self._snapshot_authority(generation.source_revision)
            if snapshot.revision != generation.source_revision:
                finished = self.authority.finish_projection_generation(
                    generation.id,
                    success=True,
                    error_code="source_revision_changed_before_build",
                )
                return KuzuRebuildReport(
                    generation=finished,
                    database_path=None,
                    source_revision=snapshot.revision,
                    node_count=0,
                    edge_count=0,
                    fallback_reason="source_revision_changed_before_build",
                )

            node_count, edge_count = self._build_database(temporary_path, snapshot)
            current_revision = self.authority.source_revision()
            if current_revision != generation.source_revision:
                finished = self.authority.finish_projection_generation(
                    generation.id,
                    success=True,
                    error_code="source_revision_changed_during_build",
                )
                self._remove_database(temporary_path)
                return KuzuRebuildReport(
                    generation=finished,
                    database_path=None,
                    source_revision=current_revision,
                    node_count=node_count,
                    edge_count=edge_count,
                    fallback_reason="source_revision_changed_during_build",
                )

            final_path.parent.mkdir(parents=True, exist_ok=True)
            self._remove_database(final_path)
            os.replace(temporary_path, final_path)
            finished = self.authority.finish_projection_generation(generation.id, success=True)
            if finished.status != "active":
                self._remove_database(final_path)
                return KuzuRebuildReport(
                    generation=finished,
                    database_path=None,
                    source_revision=self.authority.source_revision(),
                    node_count=node_count,
                    edge_count=edge_count,
                    fallback_reason="generation_not_active",
                )
            return KuzuRebuildReport(
                generation=finished,
                database_path=str(final_path),
                source_revision=finished.source_revision,
                node_count=node_count,
                edge_count=edge_count,
            )
        except ImportError:
            self._remove_database(temporary_path)
            finished = self.authority.finish_projection_generation(
                generation.id,
                success=False,
                error_code="kuzu_dependency_missing",
            )
            return KuzuRebuildReport(
                generation=finished,
                database_path=None,
                source_revision=self.authority.source_revision(),
                node_count=0,
                edge_count=0,
                fallback_reason="kuzu_dependency_missing",
            )
        except Exception as exc:
            logger.warning("Kuzu graph rebuild failed; SQLite remains authoritative", exc_info=True)
            self._remove_database(temporary_path)
            finished = self.authority.finish_projection_generation(
                generation.id,
                success=False,
                error_code=_error_code(exc),
            )
            return KuzuRebuildReport(
                generation=finished,
                database_path=None,
                source_revision=self.authority.source_revision(),
                node_count=0,
                edge_count=0,
                fallback_reason=finished.error_code,
            )

    def traverse(
        self,
        entity_id: str,
        *,
        max_hops: int = 2,
        limit: int = 100,
    ) -> KuzuTraversalResult:
        """Use Kuzu only when it agrees with a fresh SQLite authorization pass."""
        reconcile_error = self._reconcile_wiki_source()
        sqlite_relations = tuple(
            self.authority.traverse(
                entity_id,
                max_hops=max_hops,
                limit=limit,
                vault_id=self.vault_id,
            )
        )
        if reconcile_error is not None:
            return KuzuTraversalResult(
                relations=sqlite_relations,
                source="sqlite",
                fallback_reason=reconcile_error,
            )
        generation = self._usable_generation()
        if generation is None:
            return KuzuTraversalResult(
                relations=sqlite_relations,
                source="sqlite",
                fallback_reason=self._last_fallback_reason,
            )
        path = self._generation_path(generation.id)
        try:
            relation_ids = self._read_relation_ids(path, entity_id, max_hops=max_hops, limit=limit)
            sqlite_ids = tuple(item.fact.id for item in sqlite_relations)
            if set(relation_ids) != set(sqlite_ids):
                return KuzuTraversalResult(
                    relations=sqlite_relations,
                    source="sqlite",
                    generation_id=generation.id,
                    fallback_reason="kuzu_authorization_mismatch",
                )
            # SQLite supplies stable ordering and the authoritative object
            # payload; Kuzu changes the traversal implementation only.
            return KuzuTraversalResult(
                relations=sqlite_relations,
                source="kuzu",
                generation_id=generation.id,
            )
        except ImportError:
            return KuzuTraversalResult(
                relations=sqlite_relations,
                source="sqlite",
                generation_id=generation.id,
                fallback_reason="kuzu_dependency_missing",
            )
        except Exception:
            logger.warning("Kuzu graph read failed; using SQLite traversal", exc_info=True)
            return KuzuTraversalResult(
                relations=sqlite_relations,
                source="sqlite",
                generation_id=generation.id,
                fallback_reason="kuzu_generation_unreadable",
            )

    @contextmanager
    def open_read_only(self, generation_id: str | None = None) -> Iterator[object]:
        """Yield a Kuzu connection opened with ``read_only=True`` for diagnostics."""
        reconcile_error = self._reconcile_wiki_source()
        if reconcile_error is not None:
            raise KuzuProjectionError(reconcile_error)
        generation = self._usable_generation(generation_id=generation_id)
        if generation is None:
            raise KuzuProjectionError(self._last_fallback_reason or "kuzu_generation_unavailable")
        kuzu = _load_kuzu()
        database = kuzu.Database(str(self._generation_path(generation.id)), read_only=True)
        connection = kuzu.Connection(database)
        try:
            yield connection
        finally:
            _close_kuzu(connection)
            _close_kuzu(database)

    def _reconcile_wiki_source(self) -> str | None:
        if self.vault_id is None or self.vault_root is None:
            return None
        try:
            reconcile_wiki_vault(
                self.conn,
                vault_id=self.vault_id,
                vault_root=self.vault_root,
            )
        except Exception:
            logger.warning("Wiki reconciliation failed; derived graph acceleration is disabled", exc_info=True)
            return "wiki_reconcile_failed"
        return None

    def _snapshot_authority(self, expected_revision: int) -> _AuthoritySnapshot:
        # A savepoint gives a repeatable read without stealing or committing a
        # caller-owned transaction.  Rebuilds are normally autonomous, but
        # tests and maintenance jobs may invoke one while a transaction is
        # already open.
        savepoint = "llmwiki_kuzu_snapshot"
        self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            revision_row = self.conn.execute(
                "SELECT revision FROM graph_source_state WHERE id = 1"
            ).fetchone()
            revision = int(revision_row["revision"]) if revision_row is not None else 0
            entities = self.conn.execute(
                """
                SELECT id, entity_type, canonical_name, normalized_name, status,
                       risk_tier, confidence, updated_at
                FROM memory_entities
                WHERE status = 'active' AND risk_tier IN ('low', 'medium')
                ORDER BY id
                """
            ).fetchall()
            candidate_facts = self.conn.execute(
                f"""
                SELECT f.*
                FROM memory_graph_facts f
                WHERE f.statement_kind IN ('claim', 'relation')
                  AND f.status = 'active'
                  AND f.confidence >= {LOW_CONFIDENCE_THRESHOLD}
                ORDER BY f.id
                """
            ).fetchall()
            facts = tuple(
                row
                for row in candidate_facts
                if _fact_row_recallable(self.conn, str(row["id"]), vault_id=self.vault_id)
            )
            fact_ids = {str(row["id"]) for row in facts}
            relation_rows = []
            for row in facts:
                if str(row["statement_kind"] or "") != "relation":
                    continue
                if str(row["relation_type"] or "").casefold() not in KUZU_EDGE_TYPES:
                    continue
                if not _relation_row_recallable(self.conn, row, vault_id=self.vault_id):
                    continue
                endpoints = (
                    row["subject_entity_id"],
                    row["subject_fact_id"],
                    row["object_entity_id"],
                    row["object_fact_id"],
                )
                if not _typed_endpoints_exist(self.conn, endpoints, fact_ids):
                    continue
                relation_rows.append(row)
            evidence = self.conn.execute(
                """
                SELECT id, fact_id, source_type, source_text_hash, source_excerpt,
                       confidence, created_at
                FROM memory_evidence
                WHERE fact_id IN (SELECT id FROM memory_graph_facts WHERE status = 'active')
                ORDER BY id
                """
            ).fetchall()
            wiki_bindings = self.conn.execute(
                """
                SELECT id, vault_id, page_entity_id, wiki_relative_path,
                       content_hash, revision, status, updated_at
                FROM wiki_page_bindings
                WHERE status = 'active'
                ORDER BY id
                """
            ).fetchall()
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except BaseException:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        return _AuthoritySnapshot(
            revision=revision,
            entities=tuple(_row_dict(row) for row in entities),
            facts=tuple(_row_dict(row) for row in facts),
            relations=tuple(_row_dict(row) for row in relation_rows),
            evidence=tuple(_row_dict(row) for row in evidence if str(row["fact_id"] or "") in fact_ids),
            wiki_bindings=tuple(_row_dict(row) for row in wiki_bindings),
        )

    def _build_database(self, path: Path, snapshot: _AuthoritySnapshot) -> tuple[int, int]:
        kuzu = _load_kuzu()
        path.parent.mkdir(parents=True, exist_ok=True)
        database = kuzu.Database(str(path))
        connection = kuzu.Connection(database)
        try:
            _create_schema(connection)
            nodes: dict[str, dict[str, object]] = {}
            for row in snapshot.entities:
                node_id = _entity_node_id(str(row["id"]))
                nodes[node_id] = {
                    "id": node_id,
                    "kind": "entity",
                    "label": str(row["canonical_name"]),
                    "entity_type": str(row["entity_type"]),
                    "status": str(row["status"]),
                    "risk_tier": str(row["risk_tier"]),
                    "confidence": _float_value(row.get("confidence")),
                }
            fact_by_id = {str(row["id"]): row for row in snapshot.facts}
            for row in snapshot.facts:
                node_id = _fact_node_id(str(row["id"]))
                nodes[node_id] = {
                    "id": node_id,
                    "kind": "fact",
                    "label": _fact_label(row),
                    "entity_type": str(row.get("entity_type") or ""),
                    "status": str(row["status"]),
                    "risk_tier": "low",
                    "confidence": _float_value(row.get("confidence")),
                }
            for row in snapshot.evidence:
                source_id = _source_node_id(str(row["id"]))
                nodes[source_id] = {
                    "id": source_id,
                    "kind": "source",
                    "label": str(row["source_type"] or "source"),
                    "entity_type": "source",
                    "status": "active",
                    "risk_tier": "low",
                    "confidence": _float_value(row.get("confidence")),
                }
            for row in snapshot.wiki_bindings:
                page_id = str(row["page_entity_id"])
                if _entity_node_id(page_id) not in nodes:
                    continue
                wiki_id = _wiki_node_id(str(row["id"]))
                nodes[wiki_id] = {
                    "id": wiki_id,
                    "kind": "wiki_page",
                    "label": str(row["wiki_relative_path"]),
                    "entity_type": "wiki_page",
                    "status": str(row["status"]),
                    "risk_tier": "low",
                    "confidence": 1.0,
                }
            for node in nodes.values():
                _create_node(connection, node)

            edges = 0
            for row in snapshot.facts:
                subject = row.get("subject_entity_id") or row.get("subject_fact_id")
                if subject:
                    source_id = _endpoint_node_id(row.get("subject_entity_id"), row.get("subject_fact_id"))
                    if source_id in nodes:
                        _create_edge(
                            connection,
                            source_id,
                            _fact_node_id(str(row["id"])),
                            relation_id=str(row["id"]),
                            relation_type="claims",
                            confidence=_float_value(row.get("confidence")),
                        )
                        edges += 1
            for row in snapshot.relations:
                source_id = _endpoint_node_id(row.get("subject_entity_id"), row.get("subject_fact_id"))
                target_id = _endpoint_node_id(row.get("object_entity_id"), row.get("object_fact_id"))
                if source_id not in nodes or target_id not in nodes:
                    continue
                _create_edge(
                    connection,
                    source_id,
                    target_id,
                    relation_id=str(row["id"]),
                    relation_type=str(row["relation_type"]),
                    confidence=_float_value(row.get("confidence")),
                )
                edges += 1
            for row in snapshot.evidence:
                fact_id = str(row["fact_id"] or "")
                source_id = _source_node_id(str(row["id"]))
                if fact_id in fact_by_id and source_id in nodes:
                    _create_edge(
                        connection,
                        _fact_node_id(fact_id),
                        source_id,
                        relation_id=f"evidence:{row['id']}",
                        relation_type="evidence",
                        confidence=_float_value(row.get("confidence")),
                    )
            for row in snapshot.wiki_bindings:
                page_id = _entity_node_id(str(row["page_entity_id"]))
                wiki_id = _wiki_node_id(str(row["id"]))
                if page_id in nodes and wiki_id in nodes:
                    _create_edge(
                        connection,
                        page_id,
                        wiki_id,
                        relation_id=f"wiki:{row['id']}",
                        relation_type="wiki_binding",
                        confidence=1.0,
                    )
            return len(nodes), edges
        finally:
            _close_kuzu(connection)
            _close_kuzu(database)

    _last_fallback_reason: str | None = None

    def _usable_generation(self, generation_id: str | None = None) -> ProjectionGeneration | None:
        self._last_fallback_reason = None
        if generation_id is None:
            row = self.conn.execute(
                """
                SELECT id FROM graph_projection_generations
                WHERE backend = 'kuzu' AND status = 'active'
                ORDER BY built_at DESC, id DESC LIMIT 1
                """
            ).fetchone()
            if row is None:
                self._last_fallback_reason = "kuzu_generation_missing"
                return None
            generation_id = str(row["id"])
        try:
            generation = self.authority.get_generation(generation_id)
        except (EntityGraphError, sqlite3.OperationalError):
            self._last_fallback_reason = "kuzu_generation_missing"
            return None
        if generation.backend != KUZU_BACKEND or generation.status != "active":
            self._last_fallback_reason = f"kuzu_generation_{generation.status}"
            return None
        if generation.schema_version not in {KUZU_SCHEMA_VERSION, "llmwiki-graph-v1"}:
            self._last_fallback_reason = "kuzu_schema_version_mismatch"
            return None
        if generation.source_revision != self.authority.source_revision():
            self._last_fallback_reason = "kuzu_generation_revision_mismatch"
            return None
        path = self._generation_path(generation.id)
        # Kuzu databases are commonly directories; accepting only regular
        # files incorrectly forces a healthy projection into SQLite fallback.
        if not path.exists() or not (path.is_dir() or path.is_file()):
            self._last_fallback_reason = "kuzu_generation_missing"
            return None
        return generation

    def _read_relation_ids(self, path: Path, entity_id: str, *, max_hops: int, limit: int) -> tuple[str, ...]:
        kuzu = _load_kuzu()
        database = kuzu.Database(str(path), read_only=True)
        connection = kuzu.Connection(database)
        try:
            connection.execute("MATCH (n:GraphNode) RETURN count(n)").get_all()
            hops = max(1, min(max_hops, 2))
            cap = max(1, min(limit, 1000))
            frontier = {_entity_node_id(entity_id)}
            seen = set(frontier)
            relation_ids: list[str] = []
            for _ in range(hops):
                next_frontier: set[str] = set()
                for current in frontier:
                    rows = connection.execute(
                        """
                        MATCH (a:GraphNode)-[r:GraphEdge]->(b:GraphNode)
                        WHERE a.id = $id OR b.id = $id
                        RETURN a.id, b.id, r.relation_id, r.relation_type
                        """,
                        {"id": current},
                    ).get_all()
                    for source, target, relation_id, relation_type in rows:
                        # Internal projection edges (claims/evidence/wiki
                        # binding) are provenance material, not graph hops.
                        # Expanding them here would make Kuzu's hop count
                        # diverge from the authoritative SQLite traversal.
                        if relation_type not in KUZU_EDGE_TYPES:
                            continue
                        if relation_id not in relation_ids:
                            relation_ids.append(str(relation_id))
                        for endpoint in (str(source), str(target)):
                            if endpoint not in seen:
                                seen.add(endpoint)
                                next_frontier.add(endpoint)
                        if len(relation_ids) >= cap:
                            return tuple(relation_ids[:cap])
                frontier = next_frontier
                if not frontier:
                    break
            return tuple(relation_ids[:cap])
        finally:
            _close_kuzu(connection)
            _close_kuzu(database)

    def _generation_path(self, generation_id: str) -> Path:
        root = self.graph_root
        if root.suffix.casefold() == ".kuzu" and not root.is_dir():
            root = root.parent
        return root / f"memory_graph.{generation_id}.kuzu"

    def _temporary_path(self, generation_id: str) -> Path:
        path = self._generation_path(generation_id)
        return path.with_name(f".{path.name}.building")

    @staticmethod
    def _remove_database(path: Path) -> None:
        for candidate in (
            path,
            path.with_name(f"{path.name}.wal"),
            path.with_name(f"{path.name}.lock"),
            path.with_name(f"{path.name}.tmp"),
        ):
            try:
                if candidate.is_dir():
                    shutil.rmtree(candidate)
                else:
                    candidate.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
            except PermissionError:
                logger.warning("Could not remove stale Kuzu artifact: %s", candidate)


def rebuild_kuzu_projection(
    db: str | Path | sqlite3.Connection,
    graph_root: str | Path,
    *,
    schema_version: str = KUZU_SCHEMA_VERSION,
    vault_id: str | None = None,
    vault_root: str | Path | None = None,
) -> KuzuRebuildReport:
    service = KuzuGraphService(db, graph_root, vault_id=vault_id, vault_root=vault_root)
    try:
        return service.rebuild(schema_version=schema_version)
    finally:
        service.close()


def traverse_with_kuzu_fallback(
    db: str | Path | sqlite3.Connection,
    graph_root: str | Path,
    entity_id: str,
    *,
    max_hops: int = 2,
    limit: int = 100,
    vault_id: str | None = None,
    vault_root: str | Path | None = None,
) -> KuzuTraversalResult:
    service = KuzuGraphService(db, graph_root, vault_id=vault_id, vault_root=vault_root)
    try:
        return service.traverse(entity_id, max_hops=max_hops, limit=limit)
    finally:
        service.close()


def _load_kuzu():
    import kuzu

    return kuzu


def _create_schema(connection: Any) -> None:
    execute = connection.execute
    execute(
        """
        CREATE NODE TABLE GraphNode(
            id STRING,
            kind STRING,
            label STRING,
            entity_type STRING,
            status STRING,
            risk_tier STRING,
            confidence DOUBLE,
            PRIMARY KEY(id)
        )
        """
    )
    execute(
        """
        CREATE REL TABLE GraphEdge(
            FROM GraphNode TO GraphNode,
            relation_id STRING,
            relation_type STRING,
            confidence DOUBLE
        )
        """
    )


def _create_node(connection: Any, node: Mapping[str, object]) -> None:
    connection.execute(
        """
        CREATE (n:GraphNode {
            id: $id,
            kind: $kind,
            label: $label,
            entity_type: $entity_type,
            status: $status,
            risk_tier: $risk_tier,
            confidence: $confidence
        })
        """,
        dict(node),
    )


def _create_edge(
    connection: Any,
    source_id: str,
    target_id: str,
    *,
    relation_id: str,
    relation_type: str,
    confidence: float,
) -> None:
    connection.execute(
        """
        MATCH (a:GraphNode {id: $source_id}), (b:GraphNode {id: $target_id})
        CREATE (a)-[:GraphEdge {
            relation_id: $relation_id,
            relation_type: $relation_type,
            confidence: $confidence
        }]->(b)
        """,
        {
            "source_id": source_id,
            "target_id": target_id,
            "relation_id": relation_id,
            "relation_type": relation_type,
            "confidence": confidence,
        },
    )


def _typed_endpoints_exist(
    conn: sqlite3.Connection,
    endpoints: Sequence[object],
    fact_ids: set[str],
) -> bool:
    subject_entity, subject_fact, object_entity, object_fact = endpoints
    if bool(subject_entity) == bool(subject_fact) or bool(object_entity) == bool(object_fact):
        return False
    for entity_id in (subject_entity, object_entity):
        if entity_id:
            row = conn.execute(
                "SELECT status, risk_tier FROM memory_entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if row is None or row["status"] != "active" or row["risk_tier"] not in _SAFE_RISK_TIERS:
                return False
    for fact_id in (subject_fact, object_fact):
        if fact_id and str(fact_id) not in fact_ids:
            return False
    return True


def _row_dict(row: sqlite3.Row) -> dict[str, object]:
    return {str(key): row[key] for key in row.keys()}


def _fact_label(row: Mapping[str, object]) -> str:
    subject = str(row.get("subject") or "")
    predicate = str(row.get("predicate") or "")
    object_value = str(row.get("object") or "")
    return " ".join(part for part in (subject, predicate, object_value) if part)


def _float_value(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value or "0"))
    except (TypeError, ValueError):
        return 0.0


def _endpoint_node_id(entity_id: object, fact_id: object) -> str:
    if entity_id:
        return _entity_node_id(str(entity_id))
    if fact_id:
        return _fact_node_id(str(fact_id))
    return ""


def _entity_node_id(entity_id: str) -> str:
    return f"entity:{entity_id}"


def _fact_node_id(fact_id: str) -> str:
    return f"fact:{fact_id}"


def _source_node_id(source_id: str) -> str:
    return f"source:{source_id}"


def _wiki_node_id(binding_id: str) -> str:
    return f"wiki:{binding_id}"


def _close_kuzu(value: object) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        close()


def _error_code(exc: Exception) -> str:
    name = type(exc).__name__.casefold()
    if "permission" in str(exc).casefold():
        return "kuzu_permission_denied"
    if "io" in name or "io exception" in str(exc).casefold():
        return "kuzu_io_error"
    return "kuzu_rebuild_failed"
