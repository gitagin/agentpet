"""Stable, evidence-first API for the local LLM Wiki memory graph.

SQLite and the Markdown vault are authoritative.  The graph response is a
safe projection; Kuzu generation metadata is reported as an optional
acceleration state and never changes authorization decisions.
"""

from __future__ import annotations

import logging
import json
import re
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from ...errors import AppError
from ...models.api import (
    MemoryGraphActionRequest,
    MemoryGraphActionResponse,
    MemoryGraphClaimDetailResponse,
    MemoryGraphEdgeDetailResponse,
    MemoryGraphEvidenceResponse,
    MemoryGraphGenerationResponse,
    MemoryGraphLifecycleResponse,
    MemoryGraphNodeDetailResponse,
    MemoryGraphResponse,
    MemoryGraphVersionResponse,
    MemoryGraphWikiBindingResponse,
)
from ...models.enums import MemoryFactStatus
from ...services.memory_entity_graph import (
    ENTITY_TYPES,
    EntityRelation,
    RELATION_TYPES,
    MemoryEntityGraphStore,
)
from ...services.memory_graph_projection import MemoryGraphProjectionService
from ...services.memory_lifecycle import MemoryLifecycleService
from ...services.wiki_reconciler import reconcile_wiki_vault
from ...utils.hash import sha256_hex
from ...utils.public_references import public_memory_reference, safe_relative_source_reference
from ..wiring import active_vault_id, active_vault_root, database, memory_entity_graph_store
from ..idempotency import IdempotencyKeyHeader
from .dependencies import (
    memory_entity_graph_store_dependency,
    memory_graph_projection_service_dependency,
)
from .graph_presenters import memory_graph_response

router = APIRouter(prefix="/memory", tags=["memory"])
logger = logging.getLogger(__name__)

_PUBLIC_ID = re.compile(r"^(?:mg|mge|claim|relation|evidence|wiki)_[0-9a-f]{24,64}$")
_STATUS_FILTERS = frozenset({"active", "pending", "candidate", "quarantined", "archived", "hidden", "forgotten", "stale"})
_ACTIONS = frozenset({"confirm", "correct", "forget", "archive"})


@router.get("/graph", response_model=MemoryGraphResponse)
async def get_memory_graph(
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    entity_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=200, ge=5, le=1000),
    service: MemoryGraphProjectionService = Depends(memory_graph_projection_service_dependency),
) -> MemoryGraphResponse:
    vault_id = _require_bound_vault(request)
    _validate_filters(status_filter, entity_type)
    projection = service.build(max_nodes=limit)
    backend, generation_id, fallback_code, source_revision = _projection_state(request)
    generation = MemoryGraphGenerationResponse(
        generation_id=generation_id,
        backend=backend,
        source_revision=source_revision,
        status="active" if backend == "kuzu" and fallback_code is None else "degraded",
        fallback_code=fallback_code,
    )
    response = memory_graph_response(
        projection,
        vault_id=vault_id,
        generation=generation,
    )
    return _filter_projection(response, query=query, status_filter=status_filter, entity_type=entity_type, limit=limit)


@router.get("/graph/nodes/{node_id}", response_model=MemoryGraphNodeDetailResponse)
async def get_memory_graph_node(
    node_id: str,
    request: Request,
    service: MemoryGraphProjectionService = Depends(memory_graph_projection_service_dependency),
    store: MemoryEntityGraphStore = Depends(memory_entity_graph_store_dependency),
) -> MemoryGraphNodeDetailResponse:
    vault_id = _require_bound_vault(request)
    projection = service.build(max_nodes=1000)
    node = next((item for item in projection.nodes if item.id == node_id), None)
    if node is None:
        raise _not_found("memory_graph_node_not_found")
    entity_id = _resolve_entity_id(node_id, store)
    if entity_id is not None:
        return _entity_detail(store, entity_id, node, request, vault_id=vault_id)
    fact_id = _resolve_fact_node_id(node_id, store)
    if fact_id is not None:
        if not store.fact_visible_in_vault(fact_id, vault_id=vault_id):
            raise _not_found("memory_graph_node_not_found")
        return _claim_node_detail(store, fact_id, node, vault_id=vault_id)
    return MemoryGraphNodeDetailResponse(
        node_id=node.id,
        kind="projection",
        type=node.type,
        label=_safe_text(node.label),
        subtitle=_safe_text(node.subtitle),
        status=node.status,
        risk=node.risk_tier,
        confidence=_confidence(node.confidence_label),
        updated_at=node.updated_at,
        allowed_actions=[],
        evidence_count=node.evidence_count,
    )


@router.post("/graph/nodes/{node_id}/actions", response_model=MemoryGraphActionResponse)
async def act_on_memory_graph_node(
    node_id: str,
    action_request: MemoryGraphActionRequest,
    request: Request,
    idempotency_key: IdempotencyKeyHeader,
    store: MemoryEntityGraphStore = Depends(memory_entity_graph_store_dependency),
) -> MemoryGraphActionResponse:
    _require_bound_vault(request)
    entity_id = _resolve_entity_id(node_id, store)
    if entity_id is None:
        raise _not_found("memory_graph_node_not_found")
    _validate_action(action_request, target="node")
    return await _execute_entity_action(request, node_id, entity_id, action_request, idempotency_key, store)


@router.get("/graph/edges/{edge_id}", response_model=MemoryGraphEdgeDetailResponse)
async def get_memory_graph_edge(
    edge_id: str,
    request: Request,
    service: MemoryGraphProjectionService = Depends(memory_graph_projection_service_dependency),
    store: MemoryEntityGraphStore = Depends(memory_entity_graph_store_dependency),
) -> MemoryGraphEdgeDetailResponse:
    vault_id = _require_bound_vault(request)
    projection = service.build(max_nodes=1000)
    edge = next((item for item in projection.edges if item.id == edge_id), None)
    relation = _resolve_relation(edge, store) if edge is not None else _resolve_relation_any_status(edge_id, store)
    if relation is None:
        raise _not_found("memory_graph_edge_not_found")
    if not store.fact_visible_in_vault(relation.fact.id, vault_id=vault_id):
        raise _not_found("memory_graph_edge_not_found")
    fact = relation.fact
    evidence = _fact_evidence(store, fact.id, vault_id=vault_id)
    return MemoryGraphEdgeDetailResponse(
        edge_id=edge.id if edge is not None else _relation_edge_id(relation),
        source_node_id=_endpoint_public_id(relation.subject_entity_id, relation.subject_fact_id),
        target_node_id=_endpoint_public_id(relation.object_entity_id, relation.object_fact_id),
        relation_type=relation.relation_type,
        status=fact.status.value,
        risk=_fact_risk(fact),
        lifecycle=_fact_lifecycle(store, fact, vault_id=vault_id),
        evidence=evidence,
        wiki_pages=_fact_wiki_bindings(store, fact.id, vault_id=vault_id),
        version_chain=_version_chain(store, fact.id, target_kind="edge", vault_id=vault_id),
        confidence=fact.confidence,
        evidence_count=len(evidence),
        updated_at=fact.updated_at,
        allowed_actions=_edge_actions(fact.status),
    )


@router.post("/graph/edges/{edge_id}/actions", response_model=MemoryGraphActionResponse)
async def act_on_memory_graph_edge(
    edge_id: str,
    action_request: MemoryGraphActionRequest,
    request: Request,
    idempotency_key: IdempotencyKeyHeader,
    service: MemoryGraphProjectionService = Depends(memory_graph_projection_service_dependency),
    store: MemoryEntityGraphStore = Depends(memory_entity_graph_store_dependency),
) -> MemoryGraphActionResponse:
    vault_id = _require_bound_vault(request)
    projection = service.build(max_nodes=1000)
    edge = next((item for item in projection.edges if item.id == edge_id), None)
    # Resolve from authoritative SQLite even when a prior successful action
    # removed the edge from the active projection. This lets the lifecycle
    # coordinator replay the original receipt after an ambiguous response.
    relation = _resolve_relation(edge, store) if edge is not None else _resolve_relation_any_status(edge_id, store)
    if relation is None:
        raise _not_found("memory_graph_edge_not_found")
    if not store.fact_visible_in_vault(relation.fact.id, vault_id=vault_id):
        raise _not_found("memory_graph_edge_not_found")
    _validate_action(action_request, target="edge")
    if relation.fact.status is not MemoryFactStatus.ACTIVE:
        if not _execution_key_exists(request, idempotency_key):
            raise AppError("memory_graph_edge_not_active", "该关系已不在活动图谱中，不能创建新的操作。", status.HTTP_409_CONFLICT)
    return await _execute_relation_action(request, edge_id, relation, action_request, idempotency_key, store)


@router.get("/graph/claims/{claim_id}", response_model=MemoryGraphClaimDetailResponse)
async def get_memory_graph_claim(
    claim_id: str,
    request: Request,
    store: MemoryEntityGraphStore = Depends(memory_entity_graph_store_dependency),
) -> MemoryGraphClaimDetailResponse:
    vault_id = _require_bound_vault(request)
    fact_id = _resolve_claim_id(claim_id, store)
    if fact_id is None:
        raise _not_found("memory_graph_claim_not_found")
    if not store.fact_visible_in_vault(fact_id, vault_id=vault_id):
        raise _not_found("memory_graph_claim_not_found")
    return _claim_detail(store, fact_id, vault_id=vault_id)


@router.post("/graph/claims/{claim_id}/actions", response_model=MemoryGraphActionResponse)
async def act_on_memory_graph_claim(
    claim_id: str,
    action_request: MemoryGraphActionRequest,
    request: Request,
    idempotency_key: IdempotencyKeyHeader,
    store: MemoryEntityGraphStore = Depends(memory_entity_graph_store_dependency),
) -> MemoryGraphActionResponse:
    vault_id = _require_bound_vault(request)
    fact_id = _resolve_claim_id(claim_id, store)
    if fact_id is None:
        raise _not_found("memory_graph_claim_not_found")
    fact = store.get(fact_id)
    if fact.statement_kind not in {None, "claim"}:
        raise _not_found("memory_graph_claim_not_found")
    if not store.fact_visible_in_vault(fact_id, vault_id=vault_id):
        raise _not_found("memory_graph_claim_not_found")
    _validate_action(action_request, target="claim")
    return await _execute_fact_action(request, claim_id, fact_id, action_request, idempotency_key, store)


def _require_bound_vault(request: Request) -> str:
    try:
        vault_id = active_vault_id(request)
    except AppError as exc:
        if exc.code == "vault_not_configured":
            raise AppError("vault_not_bound", "请先绑定一个本地 Wiki 知识库。", status.HTTP_409_CONFLICT) from exc
        raise
    try:
        reconcile_wiki_vault(
            database(request).path,
            vault_id=vault_id,
            vault_root=active_vault_root(request),
        )
    except Exception:
        logger.warning("Wiki reconciliation failed before graph API access", exc_info=True)
        request.state.memory_graph_reconcile_error = "wiki_reconcile_failed"
    else:
        request.state.memory_graph_reconcile_error = None
    return vault_id


def _not_found(code: str) -> AppError:
    return AppError(code, "未找到可访问的图谱对象。", status.HTTP_404_NOT_FOUND)


def _validate_filters(status_filter: str | None, entity_type: str | None) -> None:
    if status_filter and status_filter not in _STATUS_FILTERS:
        raise AppError("invalid_graph_status", "图谱状态筛选值无效。", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if entity_type and entity_type not in ENTITY_TYPES:
        raise AppError("invalid_graph_entity_type", "图谱实体类型无效。", status.HTTP_422_UNPROCESSABLE_CONTENT)


def _validate_action(request: MemoryGraphActionRequest, *, target: str) -> None:
    if request.action not in _ACTIONS:
        raise AppError("graph_action_not_supported", "该图谱操作不受支持。", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if request.action in {"forget", "archive"} and not request.confirmed:
        raise AppError("confirmation_required", "破坏性操作需要 confirmed=true。", status.HTTP_409_CONFLICT)
    if request.action == "correct":
        replacement = request.replacement or {}
        if target == "node":
            allowed = {"canonical_name", "entity_type", "aliases"}
            if set(replacement) - allowed or not isinstance(replacement.get("canonical_name"), str):
                raise AppError("invalid_entity_replacement", "实体纠正必须提供 canonical_name、entity_type 和 aliases。", status.HTTP_422_UNPROCESSABLE_CONTENT)
            if "entity_type" in replacement and replacement["entity_type"] not in ENTITY_TYPES:
                raise AppError("invalid_graph_entity_type", "图谱实体类型无效。", status.HTTP_422_UNPROCESSABLE_CONTENT)
            if "aliases" in replacement and (not isinstance(replacement["aliases"], list) or not all(isinstance(item, str) for item in replacement["aliases"])):
                raise AppError("invalid_entity_aliases", "实体 aliases 必须是字符串数组。", status.HTTP_422_UNPROCESSABLE_CONTENT)
        elif target == "claim":
            if set(replacement) - {"value", "fact_type"} or not isinstance(replacement.get("value"), str) or not replacement.get("value", "").strip():
                raise AppError("invalid_claim_replacement", "事实纠正必须提供非空 value。", status.HTTP_422_UNPROCESSABLE_CONTENT)
        else:
            if set(replacement) - {"relation_type", "subject_node_id", "object_node_id"}:
                raise AppError("invalid_relation_replacement", "关系纠正字段无效。", status.HTTP_422_UNPROCESSABLE_CONTENT)
            if replacement.get("relation_type") not in RELATION_TYPES or not replacement.get("subject_node_id") or not replacement.get("object_node_id"):
                raise AppError("invalid_relation_type", "关系类型不受支持。", status.HTTP_422_UNPROCESSABLE_CONTENT)


def _filter_projection(response: MemoryGraphResponse, *, query: str | None, status_filter: str | None, entity_type: str | None, limit: int) -> MemoryGraphResponse:
    q = " ".join((query or "").casefold().split())
    filtered_nodes = [
        node
        for node in response.nodes
        if (not q or q in f"{node.label} {node.subtitle}".casefold())
        and (not status_filter or node.status == status_filter)
        and (not entity_type or _projection_entity_type(node.type) == entity_type)
    ]
    nodes = filtered_nodes[:limit]
    node_ids = {node.node_id for node in nodes}
    edges = [
        edge
        for edge in response.edges
        if edge.source_node_id in node_ids and edge.target_node_id in node_ids
    ][: limit * 2]
    clusters = [
        cluster.model_copy(update={"node_ids": [item for item in cluster.node_ids if item in node_ids]})
        for cluster in response.clusters
        if any(item in node_ids for item in cluster.node_ids)
    ]
    summary = response.summary.model_copy(
        update={
            "total_nodes": len(nodes),
            "pending_count": sum(node.status == "pending" for node in nodes),
            "cleanup_count": sum(node.type == "cleanup" for node in nodes),
            "hidden_count": sum(
                node.status == "hidden" or node.risk == "hidden"
                for node in nodes
            ),
        }
    )
    return response.model_copy(
        update={
            "nodes": nodes,
            "edges": edges,
            "clusters": clusters,
            "summary": summary,
        }
    )


def _projection_entity_type(node_type: str) -> str | None:
    return {"user": "self", "preference": "preference", "boundary": "boundary", "project": "project", "episode": "event"}.get(node_type, node_type if node_type in ENTITY_TYPES else None)


def _projection_state(request: Request) -> tuple[str, str | None, str | None, int]:
    from ...config import get_settings

    with database(request).session() as conn:
        revision_row = conn.execute("SELECT revision FROM graph_source_state WHERE id = 1").fetchone()
        source_revision = int(revision_row[0]) if revision_row is not None else 0
        row = conn.execute("SELECT id, source_revision FROM graph_projection_generations WHERE backend = 'kuzu' AND status = 'active' ORDER BY built_at DESC, id DESC LIMIT 1").fetchone()
    reconcile_error = getattr(request.state, "memory_graph_reconcile_error", None)
    if reconcile_error:
        return "sqlite", str(row[0]) if row is not None else None, str(reconcile_error), source_revision
    if row is None:
        return "sqlite", None, "kuzu_generation_missing", source_revision
    generation_id = str(row[0])
    if int(row[1]) != source_revision:
        return "sqlite", generation_id, "kuzu_generation_revision_mismatch", source_revision
    try:
        import kuzu  # noqa: F401
    except ImportError:
        return "sqlite", generation_id, "kuzu_dependency_missing", source_revision
    root = get_settings().data_dir / "memory-graph"
    path = root / f"memory_graph.{generation_id}.kuzu"
    if not path.exists():
        return "sqlite", generation_id, "kuzu_generation_missing", source_revision
    return "kuzu", generation_id, None, source_revision


def _opaque_node_id(kind: str, raw_id: str) -> str:
    return "mg_" + sha256_hex("\x1f".join(("memory_graph_projection_v1", "node", kind, raw_id)))[:32]


def _opaque_edge_id(from_node: str, to_node: str, relation_type: str, fact_id: str) -> str:
    return "mge_" + sha256_hex("\x1f".join(("memory_graph_projection_v1", "edge", from_node, to_node, relation_type, fact_id)))[:32]


def _public_id(prefix: str, raw_id: object) -> str:
    return public_memory_reference(prefix, raw_id)


def _validate_public_id(value: str) -> bool:
    return bool(_PUBLIC_ID.fullmatch(value or ""))


def _resolve_entity_id(public_id: str, store: MemoryEntityGraphStore) -> str | None:
    if not _validate_public_id(public_id) or not public_id.startswith("mg_"):
        return None
    rows = store.conn.execute("SELECT id FROM memory_entities WHERE status IN ('active','archived','forgotten','stale') ORDER BY id").fetchall()
    for row in rows:
        raw = str(row[0])
        if public_id == _opaque_node_id("entity", raw):
            return raw
    return None


def _resolve_fact_node_id(public_id: str, store: MemoryEntityGraphStore) -> str | None:
    if not _validate_public_id(public_id) or not public_id.startswith("mg_"):
        return None
    rows = store.conn.execute("SELECT id FROM memory_graph_facts ORDER BY id").fetchall()
    for row in rows:
        raw = str(row[0])
        if public_id == _opaque_node_id("fact", raw):
            return raw
    return None


def _resolve_claim_id(public_id: str, store: MemoryEntityGraphStore) -> str | None:
    if not _validate_public_id(public_id) or not public_id.startswith("claim_"):
        return None
    rows = store.conn.execute("SELECT id FROM memory_graph_facts ORDER BY id").fetchall()
    for row in rows:
        raw = str(row[0])
        if public_id == _public_id("claim", raw):
            return raw
    return None


def _resolve_relation(edge: Any, store: MemoryEntityGraphStore):
    if edge is None or edge.type == "belongs_to" or not _validate_public_id(edge.id):
        return None
    for relation in store.list_relations(status="active", limit=1000):
        subject = relation.subject_entity_id or relation.subject_fact_id
        target = relation.object_entity_id or relation.object_fact_id
        if not subject or not target:
            continue
        source = _opaque_node_id("entity" if relation.subject_entity_id else "fact", str(subject))
        destination = _opaque_node_id("entity" if relation.object_entity_id else "fact", str(target))
        if edge.id == _opaque_edge_id(source, destination, relation.relation_type, relation.fact.id):
            return relation
    return None


def _resolve_relation_any_status(public_id: str, store: MemoryEntityGraphStore) -> EntityRelation | None:
    if not _validate_public_id(public_id) or not public_id.startswith("mge_"):
        return None
    rows = store.conn.execute(
        """
        SELECT id, relation_type, subject_entity_id, subject_fact_id,
               object_entity_id, object_fact_id
        FROM memory_graph_facts
        WHERE statement_kind = 'relation'
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        subject = row["subject_entity_id"] or row["subject_fact_id"]
        target = row["object_entity_id"] or row["object_fact_id"]
        if not subject or not target:
            continue
        source = _opaque_node_id("entity" if row["subject_entity_id"] else "fact", str(subject))
        destination = _opaque_node_id("entity" if row["object_entity_id"] else "fact", str(target))
        if public_id == _opaque_edge_id(source, destination, str(row["relation_type"]), str(row["id"])):
            return EntityRelation(
                fact=store.get(str(row["id"])),
                relation_type=str(row["relation_type"]),
                subject_entity_id=str(row["subject_entity_id"]) if row["subject_entity_id"] else None,
                subject_fact_id=str(row["subject_fact_id"]) if row["subject_fact_id"] else None,
                object_entity_id=str(row["object_entity_id"]) if row["object_entity_id"] else None,
                object_fact_id=str(row["object_fact_id"]) if row["object_fact_id"] else None,
            )
    return None


def _execution_key_exists(request: Request, key: str) -> bool:
    from ...services.agent_actions import ScopedAgentActionLedger
    from ..wiring import agent_action_service

    ledger = ScopedAgentActionLedger(lambda: agent_action_service(request))
    return ledger.find_execution(key) is not None


def _endpoint_public_id(entity_id: str | None, fact_id: str | None) -> str:
    if entity_id:
        return _opaque_node_id("entity", entity_id)
    if fact_id:
        return _opaque_node_id("fact", fact_id)
    return "mg_" + "0" * 32


def _relation_edge_id(relation: EntityRelation) -> str:
    source = _endpoint_public_id(relation.subject_entity_id, relation.subject_fact_id)
    target = _endpoint_public_id(relation.object_entity_id, relation.object_fact_id)
    return _opaque_edge_id(source, target, relation.relation_type, relation.fact.id)


def _entity_detail(
    store: MemoryEntityGraphStore,
    entity_id: str,
    node: Any,
    request: Request,
    *,
    vault_id: str | None = None,
) -> MemoryGraphNodeDetailResponse:
    scope = vault_id
    if scope is None:
        try:
            scope = active_vault_id(request)
        except AppError:
            scope = None
    entity = store.get_entity(entity_id)
    rows = store.conn.execute(
        """
        SELECT id
        FROM memory_graph_facts
        WHERE subject_entity_id = ?
          AND (statement_kind IS NULL OR statement_kind = 'claim')
        ORDER BY updated_at DESC, id
        """,
        (entity_id,),
    ).fetchall()
    rows = [row for row in rows if store.fact_visible_in_vault(str(row["id"]), vault_id=scope)]
    claim_ids = [_public_id("claim", row[0]) for row in rows]
    relation_ids = _entity_relation_ids(store, entity_id, vault_id=scope)
    evidence = _entity_evidence(store, entity_id, vault_id=scope)
    return MemoryGraphNodeDetailResponse(
        node_id=node.id,
        kind="entity",
        type=entity.entity_type,
        label=_safe_text(entity.canonical_name),
        subtitle=_safe_text(node.subtitle),
        status=entity.status,
        risk=_entity_risk(entity.risk_tier),
        confidence=entity.confidence,
        updated_at=entity.updated_at,
        lifecycle=MemoryGraphLifecycleResponse(
            status=entity.status,
            active_for_recall=entity.status == "active" and entity.risk_tier not in {"high", "hidden"},
            confidence=entity.confidence,
            updated_at=entity.updated_at,
        ),
        evidence=evidence,
        wiki_pages=_entity_wiki_bindings(store, entity_id, vault_id=scope),
        edge_ids=relation_ids,
        claim_ids=claim_ids,
        evidence_count=len(evidence) + sum(len(_fact_evidence(store, row[0], vault_id=scope)) for row in rows),
        allowed_actions=[] if entity.entity_type == "self" else ["correct", "forget", "archive"],
    )


def _claim_node_detail(
    store: MemoryEntityGraphStore,
    fact_id: str,
    node: Any,
    *,
    vault_id: str | None = None,
) -> MemoryGraphNodeDetailResponse:
    fact = store.get(fact_id)
    evidence = _fact_evidence(store, fact.id, vault_id=vault_id)
    return MemoryGraphNodeDetailResponse(node_id=node.id, kind="claim", type=node.type, label=_safe_text(node.label), subtitle=_safe_text(node.subtitle), status=fact.status.value, risk=_fact_risk(fact), confidence=fact.confidence, updated_at=fact.updated_at, lifecycle=_fact_lifecycle(store, fact, vault_id=vault_id), evidence=evidence, wiki_pages=_fact_wiki_bindings(store, fact.id, vault_id=vault_id), version_chain=_version_chain(store, fact.id, target_kind="claim", vault_id=vault_id), claim_ids=[_public_id("claim", fact.id)], evidence_count=len(evidence), allowed_actions=_statement_actions(fact.status))


def _claim_detail(
    store: MemoryEntityGraphStore,
    fact_id: str,
    *,
    vault_id: str | None = None,
) -> MemoryGraphClaimDetailResponse:
    fact = store.get(fact_id)
    if fact.statement_kind not in {None, "claim"}:
        raise _not_found("memory_graph_claim_not_found")
    subject_id = _opaque_node_id("entity", fact.subject_entity_id) if fact.subject_entity_id else None
    evidence = _fact_evidence(store, fact.id, vault_id=vault_id)
    subject_label = fact.subject
    if fact.subject_entity_id:
        try:
            subject_label = store.get_entity(fact.subject_entity_id).canonical_name
        except Exception:
            subject_label = fact.subject
    return MemoryGraphClaimDetailResponse(claim_id=_public_id("claim", fact.id), subject_label=_safe_text(subject_label), predicate=_safe_text(fact.predicate), literal_value=_safe_text(fact.object), fact_type=_safe_text(fact.category), status=fact.status.value, risk=_fact_risk(fact), confidence=fact.confidence, source_type=_safe_source_label(fact.source_type), subject_node_id=subject_id, lifecycle=_fact_lifecycle(store, fact, vault_id=vault_id), evidence=evidence, wiki_pages=_fact_wiki_bindings(store, fact.id, vault_id=vault_id), version_chain=_version_chain(store, fact.id, target_kind="claim", vault_id=vault_id), evidence_count=len(evidence), superseded_by_claim_id=_public_id("claim", fact.superseded_by) if fact.superseded_by else None, allowed_actions=_statement_actions(fact.status), updated_at=fact.updated_at)


def _fact_lifecycle(
    store: MemoryEntityGraphStore,
    fact: Any,
    *,
    vault_id: str | None = None,
) -> MemoryGraphLifecycleResponse:
    row = store.conn.execute("SELECT reason FROM memory_lifecycle_events WHERE fact_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (fact.id,)).fetchone()
    active = store.statement_recallable(fact.id, vault_id=vault_id)
    return MemoryGraphLifecycleResponse(status=fact.status.value, active_for_recall=active, confidence=fact.confidence, updated_at=fact.updated_at, expires_at=fact.expires_at, reason=str(row[0]) if row and row[0] else None)


def _fact_evidence(
    store: MemoryEntityGraphStore,
    fact_id: str,
    *,
    vault_id: str | None = None,
) -> list[MemoryGraphEvidenceResponse]:
    if not store.fact_visible_in_vault(fact_id, vault_id=vault_id):
        return []
    rows = store.conn.execute("SELECT id, source_type, source_excerpt, confidence, created_at, metadata_json FROM memory_evidence WHERE fact_id = ? ORDER BY created_at, id", (fact_id,)).fetchall()
    artifact_paths = _fact_artifact_paths(store, fact_id, vault_id=vault_id)
    result = []
    for row in rows:
        excerpt = _safe_text(row[2] or "")[:500]
        if any(marker in excerpt.casefold() for marker in ("token", "password", "secret", "api_key")):
            excerpt = "敏感来源已隐藏"
        relative_path = artifact_paths[0] if len(artifact_paths) == 1 else None
        result.append(MemoryGraphEvidenceResponse(evidence_id=_public_id("evidence", row[0]), source_type=str(row[1] or "source"), label=_safe_source_label(str(row[1] or "source")), excerpt=excerpt, confidence=max(0.0, min(1.0, float(row[3] or 0.0))), created_at=str(row[4]), relative_path=relative_path))
    return result


def _json_object(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_relative_path(value: object) -> str | None:
    return safe_relative_source_reference(value)


def _first_safe_relative_path(*values: object) -> str | None:
    for value in values:
        if (path := _safe_relative_path(value)) is not None:
            return path
    return None


def _fact_artifact_paths(store: MemoryEntityGraphStore, fact_id: str, *, vault_id: str | None) -> list[str]:
    if not _table_exists(store, "memory_fact_artifact_bindings"):
        return []
    clauses = [
        "fact_id = ?",
        "status = 'active'",
        "artifact_type IN ('source', 'wiki_page')",
    ]
    params: list[object] = [fact_id]
    if vault_id is None:
        clauses.append("vault_id IS NULL")
    else:
        clauses.append("(vault_id IS NULL OR vault_id = ?)")
        params.append(vault_id)
    rows = store.conn.execute(
        f"SELECT artifact_ref FROM memory_fact_artifact_bindings WHERE {' AND '.join(clauses)} ORDER BY artifact_type, artifact_ref",
        tuple(params),
    ).fetchall()
    return list(dict.fromkeys(path for row in rows if (path := _safe_relative_path(row[0])) is not None))


def _binding_response(row: Any, *, binding_id: object | None = None, status: object | None = None) -> MemoryGraphWikiBindingResponse | None:
    relative_path = _safe_relative_path(row["wiki_relative_path"] if "wiki_relative_path" in row.keys() else row.get("artifact_ref"))
    if relative_path is None:
        return None
    title = PurePosixPath(relative_path).stem or "Wiki 页面"
    raw_binding_id = binding_id if binding_id is not None else row["id"]
    raw_status = status if status is not None else row["status"]
    return MemoryGraphWikiBindingResponse(
        binding_id=_public_id("wiki", raw_binding_id),
        title=_safe_text(title),
        relative_path=relative_path,
        status=str(raw_status or "active"),
        revision=max(0, int(row["revision"] or 0)) if "revision" in row.keys() else 0,
        content_hash=str(row["content_hash"]) if "content_hash" in row.keys() and row["content_hash"] else None,
        updated_at=str(row["updated_at"] if "updated_at" in row.keys() else ""),
    )


def _fact_wiki_bindings(store: MemoryEntityGraphStore, fact_id: str, *, vault_id: str | None) -> list[MemoryGraphWikiBindingResponse]:
    if not _table_exists(store, "memory_fact_artifact_bindings"):
        return []
    clauses = [
        "a.fact_id = ?",
        "a.status = 'active'",
        "a.artifact_type = 'wiki_page'",
    ]
    params: list[object] = [fact_id]
    if vault_id is None:
        clauses.append("a.vault_id IS NULL")
    else:
        clauses.append("(a.vault_id IS NULL OR a.vault_id = ?)")
        params.append(vault_id)
    rows = store.conn.execute(
        f"""
        SELECT a.id, a.artifact_ref, a.status, a.updated_at,
               w.id AS wiki_id, w.wiki_relative_path, w.content_hash,
               w.revision, w.status AS wiki_status, w.updated_at AS wiki_updated_at
        FROM memory_fact_artifact_bindings a
        LEFT JOIN wiki_page_bindings w
          ON w.vault_id IS a.vault_id AND w.wiki_relative_path = a.artifact_ref
        WHERE {' AND '.join(clauses)}
        ORDER BY a.updated_at, a.id
        """,
        tuple(params),
    ).fetchall()
    result: list[MemoryGraphWikiBindingResponse] = []
    seen: set[str] = set()
    for row in rows:
        source = row if row["wiki_relative_path"] else {"artifact_ref": row["artifact_ref"], "status": row["status"], "updated_at": row["updated_at"]}
        binding = _binding_response(source, binding_id=row["wiki_id"] or row["id"], status=row["wiki_status"] or row["status"])
        if binding is not None and binding.relative_path not in seen:
            seen.add(binding.relative_path)
            result.append(binding)
    return result


def _entity_wiki_bindings(store: MemoryEntityGraphStore, entity_id: str, *, vault_id: str | None) -> list[MemoryGraphWikiBindingResponse]:
    if not _table_exists(store, "wiki_page_bindings") or vault_id is None:
        return []
    rows = store.conn.execute(
        """
        SELECT w.*
        FROM wiki_page_bindings w
        WHERE w.vault_id = ? AND w.status != 'forgotten'
          AND w.page_entity_id = ?
        UNION
        SELECT w.*
        FROM memory_graph_facts r
        JOIN wiki_page_bindings w ON w.page_entity_id = r.object_entity_id AND w.vault_id = ?
        WHERE r.statement_kind = 'relation'
          AND r.relation_type = 'documented_in'
          AND r.subject_entity_id = ?
          AND r.status IN ('active', 'candidate', 'quarantined', 'stale', 'superseded', 'archived')
          AND w.status != 'forgotten'
        ORDER BY wiki_relative_path
        """,
        (vault_id, entity_id, vault_id, entity_id),
    ).fetchall()
    result: list[MemoryGraphWikiBindingResponse] = []
    seen: set[str] = set()
    for row in rows:
        binding = _binding_response(row)
        if binding is not None and binding.relative_path not in seen:
            seen.add(binding.relative_path)
            result.append(binding)
    return result


def _entity_evidence(store: MemoryEntityGraphStore, entity_id: str, *, vault_id: str | None) -> list[MemoryGraphEvidenceResponse]:
    if not _table_exists(store, "memory_entity_evidence"):
        return []
    scope_clause = ""
    scope_params: tuple[object, ...] = ()
    if vault_id is not None and _table_exists(store, "memory_fact_artifact_bindings"):
        scope_clause = """
          AND (
              e.fact_id IS NULL
              OR NOT EXISTS (
                  SELECT 1
                  FROM memory_fact_artifact_bindings b
                  WHERE b.fact_id = e.fact_id AND b.status = 'active'
              )
              OR EXISTS (
                  SELECT 1
                  FROM memory_fact_artifact_bindings b
                  WHERE b.fact_id = e.fact_id
                    AND b.status = 'active'
                    AND (b.vault_id IS NULL OR b.vault_id = ?)
              )
          )
        """
        scope_params = (vault_id,)
    rows = store.conn.execute(
        f"""
        SELECT e.id, e.source_type, e.source_excerpt, e.confidence, e.created_at,
               e.metadata_json
        FROM memory_entity_evidence ee
        JOIN memory_evidence e ON e.id = ee.evidence_id
        WHERE ee.entity_id = ?
        {scope_clause}
        ORDER BY e.created_at, e.id
        """,
        (entity_id, *scope_params),
    ).fetchall()
    result: list[MemoryGraphEvidenceResponse] = []
    for row in rows:
        excerpt = _safe_text(row["source_excerpt"] or "")[:500]
        if any(marker in excerpt.casefold() for marker in ("token", "password", "secret", "api_key")):
            excerpt = "敏感来源已隐藏"
        metadata = _json_object(row["metadata_json"])
        result.append(
            MemoryGraphEvidenceResponse(
                evidence_id=_public_id("evidence", row["id"]),
                source_type=str(row["source_type"] or "source"),
                label=_safe_source_label(str(row["source_type"] or "source")),
                excerpt=excerpt,
                confidence=max(0.0, min(1.0, float(row["confidence"] or 0.0))),
                created_at=str(row["created_at"]),
                relative_path=_first_safe_relative_path(
                    metadata.get("wiki_relative_path"), metadata.get("relative_path"), metadata.get("source_path")
                ),
            )
        )
    return result


def _entity_relation_ids(store: MemoryEntityGraphStore, entity_id: str, *, vault_id: str | None) -> list[str]:
    rows = store.conn.execute(
        """
        SELECT * FROM memory_graph_facts
        WHERE statement_kind = 'relation'
          AND (subject_entity_id = ? OR object_entity_id = ?)
        ORDER BY updated_at DESC, id
        """,
        (entity_id, entity_id),
    ).fetchall()
    result: list[str] = []
    for row in rows:
        fact = store.get(str(row["id"]))
        if not store.fact_visible_in_vault(fact.id, vault_id=vault_id):
            continue
        relation = EntityRelation(
            fact=fact,
            relation_type=str(row["relation_type"] or "related_to"),
            subject_entity_id=str(row["subject_entity_id"]) if row["subject_entity_id"] else None,
            subject_fact_id=str(row["subject_fact_id"]) if row["subject_fact_id"] else None,
            object_entity_id=str(row["object_entity_id"]) if row["object_entity_id"] else None,
            object_fact_id=str(row["object_fact_id"]) if row["object_fact_id"] else None,
        )
        result.append(_relation_edge_id(relation))
    return list(dict.fromkeys(result))


def _version_chain(
    store: MemoryEntityGraphStore,
    fact_id: str,
    *,
    target_kind: str,
    vault_id: str | None = None,
) -> list[MemoryGraphVersionResponse]:
    if not _table_exists(store, "memory_graph_facts"):
        return []
    pending = [fact_id]
    seen: set[str] = set()
    while pending and len(seen) < 200:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        rows = store.conn.execute(
            """
            SELECT subject_fact_id, object_fact_id
            FROM memory_graph_facts
            WHERE statement_kind = 'relation'
              AND relation_type = 'supersedes'
              AND (subject_fact_id = ? OR object_fact_id = ?)
            """,
            (current, current),
        ).fetchall()
        for row in rows:
            for endpoint in (row["subject_fact_id"], row["object_fact_id"]):
                if endpoint and str(endpoint) not in seen:
                    pending.append(str(endpoint))
    facts = [
        store.get(item)
        for item in seen
        if store.fact_visible_in_vault(item, vault_id=vault_id)
    ]
    if target_kind == "claim":
        facts = [fact for fact in facts if fact.statement_kind in {None, "claim"}]
    else:
        facts = [fact for fact in facts if fact.statement_kind == "relation" and fact.relation_type != "supersedes"]
    facts.sort(key=lambda fact: (fact.created_at, fact.id))
    return [
        MemoryGraphVersionResponse(
            object_id=_version_object_id(fact, target_kind=target_kind),
            status=fact.status.value,
            updated_at=fact.updated_at,
            current=fact.id == fact_id,
        )
        for fact in facts
    ]


def _version_object_id(fact: Any, *, target_kind: str) -> str:
    if target_kind == "claim":
        return _public_id("claim", fact.id)
    relation = EntityRelation(
        fact=fact,
        relation_type=str(fact.relation_type or "related_to"),
        subject_entity_id=fact.subject_entity_id,
        subject_fact_id=fact.subject_fact_id,
        object_entity_id=fact.object_entity_id,
        object_fact_id=fact.object_fact_id,
    )
    if relation.subject_entity_id or relation.subject_fact_id:
        return _relation_edge_id(relation)
    return _public_id("relation", fact.id)


def _table_exists(store: MemoryEntityGraphStore, table: str) -> bool:
    row = store.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _entity_risk(value: object) -> str:
    normalized = str(value or "low").casefold()
    return normalized if normalized in {"low", "medium", "high", "hidden"} else "low"


def _fact_risk(fact: Any) -> str:
    metadata = _json_object(getattr(fact, "metadata_json", None))
    return _entity_risk(metadata.get("risk_tier") or metadata.get("risk"))


def _edge_actions(value: MemoryFactStatus) -> list[str]:
    if value is MemoryFactStatus.ACTIVE:
        return ["correct", "forget", "archive"]
    return []


def _statement_actions(value: MemoryFactStatus) -> list[str]:
    if value in {MemoryFactStatus.CANDIDATE, MemoryFactStatus.QUARANTINED}:
        return ["confirm", "correct", "forget", "archive"]
    if value is MemoryFactStatus.ACTIVE:
        return ["correct", "forget", "archive"]
    return ["forget"]


async def _execute_entity_action(request: Request, target_id: str, entity_id: str, action_request: MemoryGraphActionRequest, key: str | None, store: MemoryEntityGraphStore) -> MemoryGraphActionResponse:
    return await _execute_graph_action_via_lifecycle(
        request,
        target_id=target_id,
        raw_target_id=entity_id,
        target_kind="entity",
        action_request=action_request,
        key=key,
    )


async def _execute_fact_action(request: Request, target_id: str, fact_id: str, action_request: MemoryGraphActionRequest, key: str | None, store: MemoryEntityGraphStore) -> MemoryGraphActionResponse:
    return await _execute_graph_action_via_lifecycle(
        request,
        target_id=target_id,
        raw_target_id=fact_id,
        target_kind="statement",
        action_request=action_request,
        key=key,
    )


async def _execute_relation_action(request: Request, target_id: str, relation: Any, action_request: MemoryGraphActionRequest, key: str | None, store: MemoryEntityGraphStore) -> MemoryGraphActionResponse:
    return await _execute_graph_action_via_lifecycle(
        request,
        target_id=target_id,
        raw_target_id=str(relation.fact.id),
        target_kind="relation",
        action_request=action_request,
        key=key,
    )


async def _execute_graph_action_via_lifecycle(
    request: Request,
    *,
    target_id: str,
    raw_target_id: str,
    target_kind: str,
    action_request: MemoryGraphActionRequest,
    key: str | None,
) -> MemoryGraphActionResponse:
    """Run graph mutations through the production claim/receipt coordinator."""
    from ...agents.contracts import ActionProposal
    from ...agents.nodes.policy_guard import evaluate_action_proposal
    from ..services.adapters import production_action_lifecycle

    action_type = f"memory.graph.{target_kind}"
    parameters = {
        "target_kind": target_kind,
        "target_id": raw_target_id,
        "public_target_id": target_id,
        **action_request.model_dump(mode="json", exclude_none=True),
    }
    proposal = ActionProposal(
        proposal_id=f"proposal:{action_type}:{key[:24]}",
        explicit_intent_ref=f"memory-graph:{target_id}:{key}",
        action_type=action_type,
        target_ref=f"intent:memory-graph/{target_id}",
        parameters=parameters,
        expected_effect=f"Update one local memory graph {target_kind} lifecycle state.",
        reversible=True,
        idempotency_key=None,
        requested_confirmation=bool(action_request.confirmed),
    )
    policy = evaluate_action_proposal(proposal)
    if policy.decision == "pending_confirmation" and action_request.confirmed:
        policy = policy.model_copy(update={"decision": "approved", "requires_confirmation": False, "confirmed_by_user": True})
    if policy.decision != "approved":
        raise AppError("graph_action_not_allowed", "图谱操作未通过本机安全策略。", status.HTTP_422_UNPROCESSABLE_CONTENT)
    # The HTTP idempotency key is the caller's stable operation identity.  The
    # policy payload is still canonicalized and validated before this binding.
    policy = policy.model_copy(update={"idempotency_key": key})
    lifecycle = production_action_lifecycle(request)
    outcome = await lifecycle.execute(
        proposal,
        policy,
        source_run_id=str(getattr(getattr(request, "state", None), "request_id", None) or f"memory-graph:{key[:24]}"),
    )
    receipt = outcome.receipt
    if receipt.status != "verified":
        if receipt.safe_error_code == "idempotency_key_conflict":
            raise AppError(
                "idempotency_key_conflict",
                "该幂等键已用于不同操作，请生成新的操作标识后重试。",
                status.HTTP_409_CONFLICT,
            )
        raise AppError("graph_action_recovery_required", "操作结果无法安全确认，请查看本地恢复记录。", status.HTTP_409_CONFLICT)
    raw_response = receipt.result.get("graph_response")
    if not isinstance(raw_response, dict):
        raise AppError("graph_action_response_missing", "图谱操作已写入但权威回执缺少结果。", status.HTTP_409_CONFLICT)
    return MemoryGraphActionResponse.model_validate({**raw_response, "replayed": outcome.duplicate})


def execute_graph_action_effect(request: Request, proposal: Any, claim: Any) -> dict[str, object]:
    """Apply one graph action for the lifecycle adapter registry."""
    parameters = dict(proposal.parameters)
    target_kind = str(parameters.get("target_kind") or "")
    raw_target_id = str(parameters.get("target_id") or "")
    public_target_id = str(parameters.get("public_target_id") or "")
    action_request = _graph_action_request(parameters)
    lifecycle = MemoryLifecycleService(database(request).path)
    store = lifecycle.entity_graph
    try:
        before = _graph_target_snapshot(store, target_kind, raw_target_id)
        if target_kind == "entity":
            result = _apply_entity_action(store, raw_target_id, action_request)
        elif target_kind == "statement":
            result = _apply_fact_action(
                lifecycle,
                raw_target_id,
                action_request,
                agent_action_id=str(claim.claim_id),
            )
        elif target_kind == "relation":
            relation = next((item for item in store.list_relations(status="active", limit=1000) if item.fact.id == raw_target_id), None)
            if relation is None:
                raise _not_found("memory_graph_edge_not_found")
            result = _apply_relation_action(
                lifecycle,
                relation,
                action_request,
                agent_action_id=str(claim.claim_id),
            )
        else:
            raise AppError("graph_action_target_invalid", "图谱操作目标无效。", status.HTTP_422_UNPROCESSABLE_CONTENT)
        after = _authoritative_graph_action_state(store, target_kind, raw_target_id, action_request)
        if after is None:
            raise AppError(
                "graph_action_effect_incomplete",
                "图谱操作未形成可验证的权威状态。",
                status.HTTP_409_CONFLICT,
            )
    finally:
        lifecycle.close()
    response = _response_for(public_target_id, action_request, str(claim.claim_id), after)
    return {
        "result": {
            "graph_response": response.model_dump(mode="json"),
            "graph_parameters": parameters,
            "expected_state": after,
            "state_ref": f"memory-graph:{target_kind}:{raw_target_id}",
            "observed_effect": str(after.get("status") or result.get("status") or "updated"),
        },
        "before_snapshot": before,
        "after_snapshot": after,
    }


def read_graph_action_state(request: Request, receipt: Any) -> dict[str, object] | None:
    """Read the authoritative graph state for claim recovery and verification."""
    raw_parameters = receipt.result.get("graph_parameters") or receipt.result.get("canonical_parameters")
    if not isinstance(raw_parameters, dict):
        return None
    parameters = dict(raw_parameters)
    target_kind = str(parameters.get("target_kind") or "")
    raw_target_id = str(parameters.get("target_id") or "")
    public_target_id = str(parameters.get("public_target_id") or "")
    action_request = _graph_action_request(parameters)
    store = memory_entity_graph_store(request)
    try:
        observed = _authoritative_graph_action_state(store, target_kind, raw_target_id, action_request)
    finally:
        store.close()
    if observed is None:
        return None
    response = _response_for(public_target_id, action_request, str(receipt.claim_id), observed)
    return {
        **observed,
        "graph_response": response.model_dump(mode="json"),
        "state_ref": f"memory-graph:{target_kind}:{raw_target_id}",
        "observed_effect": str(observed.get("status") or "updated"),
    }


def _graph_action_request(parameters: dict[str, object]) -> MemoryGraphActionRequest:
    payload = {
        key: value
        for key, value in parameters.items()
        if key in {"action", "confirmed", "replacement"}
    }
    return MemoryGraphActionRequest.model_validate(payload)


def _graph_target_snapshot(store: MemoryEntityGraphStore, target_kind: str, target_id: str) -> dict[str, object]:
    if target_kind == "entity":
        entity = store.get_entity(target_id)
        return {"state_ref": f"memory-graph:entity:{target_id}", "status": entity.status, "canonical_name": entity.canonical_name, "entity_type": entity.entity_type}
    fact = store.get(target_id)
    return {"state_ref": f"memory-graph:{target_kind}:{target_id}", "status": fact.status.value, "fact_id": fact.id, "object": fact.object, "predicate": fact.predicate}


def _response_for(target_id: str, action: MemoryGraphActionRequest, operation_id: str, result: Any) -> MemoryGraphActionResponse:
    status_value = str(result.get("status") if isinstance(result, dict) else "completed")
    replacement_id = None
    if action.action == "correct" and isinstance(result, dict):
        replacement_id = result.get("replacement_id") or result.get("claim_id")
    return MemoryGraphActionResponse(operation_id=operation_id, target_id=target_id, action=action.action, status=status_value, replacement_id=replacement_id, message="图谱生命周期已更新。")


def _apply_entity_action(store: MemoryEntityGraphStore, entity_id: str, request: MemoryGraphActionRequest) -> dict[str, object]:
    entity = store.get_entity(entity_id)
    if request.action == "confirm":
        updated = store.update_entity_status(entity_id, "active", reason="user_confirmed")
    elif request.action in {"forget", "archive"}:
        updated = store.update_entity_status(entity_id, "forgotten" if request.action == "forget" else "archived", reason=f"user_{request.action}")
    else:
        replacement = request.replacement or {}
        aliases = tuple(str(item).strip() for item in replacement.get("aliases", []) if str(item).strip())
        updated = store.update_entity(entity_id, canonical_name=str(replacement["canonical_name"]), entity_type=str(replacement.get("entity_type") or entity.entity_type), aliases=aliases)
    return {"status": updated.status, "entity_id": updated.id}


def _apply_fact_action(
    lifecycle: MemoryLifecycleService,
    fact_id: str,
    request: MemoryGraphActionRequest,
    *,
    agent_action_id: str | None = None,
) -> dict[str, object]:
    store = lifecycle.entity_graph
    fact = store.get(fact_id)
    if request.action == "confirm":
        lifecycle.transition_fact(
            fact_id,
            MemoryFactStatus.ACTIVE,
            reason="user_confirmed",
            agent_action_id=agent_action_id,
        )
        updated = store.get(fact_id)
        return {"status": updated.status.value, "claim_id": _public_id("claim", updated.id)}
    if request.action in {"forget", "archive"}:
        lifecycle.transition_fact(
            fact_id,
            MemoryFactStatus.FORGOTTEN if request.action == "forget" else MemoryFactStatus.ARCHIVED,
            reason=f"user_{request.action}",
            agent_action_id=agent_action_id,
        )
        updated = store.get(fact_id)
        return {"status": updated.status.value, "claim_id": _public_id("claim", updated.id)}
    replacement = request.replacement or {}
    # The UI's fact_type/category is descriptive metadata, not the semantic
    # predicate.  Preserve the existing predicate unless a future, validated
    # predicate field is explicitly added to this action contract.
    correction = lifecycle.apply_feedback(
        target_type="fact",
        target_id=fact_id,
        operation="edit",
        feedback_text=str(replacement["value"]),
        replacement_predicate=fact.predicate,
        replacement_object=str(replacement["value"]),
        agent_action_id=agent_action_id,
    )
    if correction.replacement_target_id is None:
        raise AppError(
            "graph_action_replacement_missing",
            "事实纠正未生成可验证的替代事实。",
            status.HTTP_409_CONFLICT,
        )
    old = store.get(fact_id)
    new = store.get(correction.replacement_target_id)
    return {"status": new.status.value, "claim_id": _public_id("claim", new.id), "superseded_claim_id": _public_id("claim", old.id)}


def _apply_relation_action(
    lifecycle: MemoryLifecycleService,
    relation: Any,
    request: MemoryGraphActionRequest,
    *,
    agent_action_id: str | None = None,
) -> dict[str, object]:
    store = lifecycle.entity_graph
    if request.action != "correct":
        return _apply_fact_action(
            lifecycle,
            relation.fact.id,
            request,
            agent_action_id=agent_action_id,
        )
    replacement = request.replacement or {}
    subject_entity_id, subject_fact_id = _resolve_endpoint_ids(store, replacement.get("subject_node_id"))
    object_entity_id, object_fact_id = _resolve_endpoint_ids(store, replacement.get("object_node_id"))
    old, new = store.correct_relation(
        relation.fact.id,
        relation_type=str(replacement.get("relation_type")),
        subject_entity_id=subject_entity_id,
        subject_fact_id=subject_fact_id,
        object_entity_id=object_entity_id,
        object_fact_id=object_fact_id,
    )
    return {"status": new.status.value, "claim_id": _public_id("relation", new.id), "superseded_claim_id": _public_id("relation", old.id)}


def _resolve_endpoint_ids(store: MemoryEntityGraphStore, public_id: object) -> tuple[str | None, str | None]:
    value = str(public_id or "")
    entity_id = _resolve_entity_id(value, store)
    if entity_id is not None:
        return entity_id, None
    fact_id = _resolve_fact_node_id(value, store)
    if fact_id is not None:
        return None, fact_id
    raise AppError("invalid_relation_endpoint", "关系端点不是可访问的图谱节点。", status.HTTP_422_UNPROCESSABLE_CONTENT)


def _authoritative_graph_action_state(
    store: MemoryEntityGraphStore,
    target_kind: str,
    target_id: str,
    request: MemoryGraphActionRequest,
) -> dict[str, object] | None:
    if target_kind == "entity":
        return _authoritative_entity_action_state(store, target_id, request)
    if target_kind == "statement":
        return _authoritative_claim_action_state(store, target_id, request)
    if target_kind == "relation":
        return _authoritative_relation_action_state(store, target_id, request)
    return None


def _authoritative_entity_action_state(store: MemoryEntityGraphStore, entity_id: str, request: MemoryGraphActionRequest) -> dict[str, object] | None:
    entity = store.get_entity(entity_id)
    aliases = tuple(
        str(row[0])
        for row in store.conn.execute(
            "SELECT alias FROM memory_entity_aliases WHERE entity_id = ? AND status = 'active' ORDER BY normalized_alias, id",
            (entity_id,),
        ).fetchall()
    )
    observed: dict[str, object] = {
        "state_ref": f"memory-graph:entity:{entity.id}",
        "status": entity.status,
        "entity_id": entity.id,
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type,
        "aliases": list(aliases),
    }
    if request.action == "correct":
        replacement = request.replacement or {}
        expected_name = " ".join(str(replacement.get("canonical_name") or "").split()).strip()
        expected_type = str(replacement.get("entity_type") or entity.entity_type)
        if entity.canonical_name != expected_name or entity.entity_type != expected_type:
            return None
        if "aliases" in replacement:
            expected_aliases = tuple(
                sorted(
                    {
                        " ".join(str(item).split()).strip()
                        for item in replacement.get("aliases", [])
                        if " ".join(str(item).split()).strip()
                        and " ".join(str(item).split()).strip().casefold() != expected_name.casefold()
                    },
                    key=str.casefold,
                )
            )
            if tuple(sorted(aliases, key=str.casefold)) != expected_aliases:
                return None
        return observed
    expected = "active" if request.action == "confirm" else ("forgotten" if request.action == "forget" else "archived")
    return observed if entity.status == expected else None


def _authoritative_claim_action_state(store: MemoryEntityGraphStore, fact_id: str, request: MemoryGraphActionRequest) -> dict[str, object] | None:
    fact = store.get(fact_id)
    observed: dict[str, object] = {
        "state_ref": f"memory-graph:statement:{fact.id}",
        "status": fact.status.value,
        "fact_id": fact.id,
        "object": fact.object,
        "predicate": fact.predicate,
    }
    if request.action == "correct":
        replacement_id = _unique_superseding_fact_id(store, fact_id)
        if replacement_id is None:
            return None
        replacement = store.get(replacement_id)
        expected_value = " ".join(str((request.replacement or {}).get("value") or "").split())
        if (
            replacement.statement_kind not in {None, "claim"}
            or replacement.status is not MemoryFactStatus.ACTIVE
            or replacement.object != expected_value
            or replacement.predicate != fact.predicate
        ):
            return None
        public_replacement_id = _public_id("claim", replacement.id)
        return {
            **observed,
            "status": replacement.status.value,
            "fact_id": replacement.id,
            "object": replacement.object,
            "predicate": replacement.predicate,
            "claim_id": public_replacement_id,
            "replacement_id": public_replacement_id,
            "superseded_claim_id": _public_id("claim", fact_id),
        }
    expected = MemoryFactStatus.ACTIVE if request.action == "confirm" else (MemoryFactStatus.FORGOTTEN if request.action == "forget" else MemoryFactStatus.ARCHIVED)
    if fact.status is not expected:
        return None
    return {**observed, "claim_id": _public_id("claim", fact.id)}


def _authoritative_relation_action_state(store: MemoryEntityGraphStore, fact_id: str, request: MemoryGraphActionRequest) -> dict[str, object] | None:
    relation = store._relation_by_id(fact_id)
    if request.action != "correct":
        expected = MemoryFactStatus.ACTIVE if request.action == "confirm" else (MemoryFactStatus.FORGOTTEN if request.action == "forget" else MemoryFactStatus.ARCHIVED)
        if relation.fact.status is not expected:
            return None
        return _relation_action_state(relation, original_fact_id=fact_id)

    replacement_id = _unique_superseding_fact_id(store, fact_id)
    if replacement_id is None:
        return None
    replacement = store._relation_by_id(replacement_id)
    expected_payload = request.replacement or {}
    expected_subject_entity_id, expected_subject_fact_id = _resolve_endpoint_ids(store, expected_payload.get("subject_node_id"))
    expected_object_entity_id, expected_object_fact_id = _resolve_endpoint_ids(store, expected_payload.get("object_node_id"))
    if (
        replacement.fact.status is not MemoryFactStatus.ACTIVE
        or replacement.relation_type != str(expected_payload.get("relation_type") or "")
        or replacement.subject_entity_id != expected_subject_entity_id
        or replacement.subject_fact_id != expected_subject_fact_id
        or replacement.object_entity_id != expected_object_entity_id
        or replacement.object_fact_id != expected_object_fact_id
    ):
        return None
    return _relation_action_state(replacement, original_fact_id=fact_id)


def _relation_action_state(relation: EntityRelation, *, original_fact_id: str) -> dict[str, object]:
    replacement_id = _relation_edge_id(relation)
    return {
        "state_ref": f"memory-graph:relation:{original_fact_id}",
        "status": relation.fact.status.value,
        "fact_id": relation.fact.id,
        "relation_type": relation.relation_type,
        "subject_entity_id": relation.subject_entity_id,
        "subject_fact_id": relation.subject_fact_id,
        "object_entity_id": relation.object_entity_id,
        "object_fact_id": relation.object_fact_id,
        "subject_node_id": _endpoint_public_id(relation.subject_entity_id, relation.subject_fact_id),
        "object_node_id": _endpoint_public_id(relation.object_entity_id, relation.object_fact_id),
        "claim_id": _public_id("relation", relation.fact.id),
        "replacement_id": replacement_id,
        "superseded_claim_id": _public_id("relation", original_fact_id),
    }


def _unique_superseding_fact_id(store: MemoryEntityGraphStore, fact_id: str) -> str | None:
    rows = store.conn.execute(
        """
        SELECT subject_fact_id
        FROM memory_graph_facts
        WHERE statement_kind = 'relation'
          AND relation_type = 'supersedes'
          AND object_fact_id = ?
          AND status = 'active'
        ORDER BY id
        """,
        (fact_id,),
    ).fetchall()
    replacement_ids = tuple(dict.fromkeys(str(row[0]) for row in rows if row[0]))
    return replacement_ids[0] if len(replacement_ids) == 1 else None


def _safe_text(value: object) -> str:
    text = " ".join(str(value or "").split())
    if not text or ":\\" in text or text.startswith("/"):
        return "本地内容" if text else "未命名"
    return text[:500]


def _safe_source_label(value: str) -> str:
    lowered = value.casefold()
    return "本地来源" if any(marker in lowered for marker in ("path", "file", "token", "secret")) else value[:80] or "本地来源"


def _confidence(label: str) -> float:
    lowered = str(label or "").casefold()
    if "高" in lowered or "high" in lowered:
        return 0.9
    if "低" in lowered or "low" in lowered:
        return 0.55
    return 0.75
