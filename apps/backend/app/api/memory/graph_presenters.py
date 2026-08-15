from __future__ import annotations

from ...models.api import (
    MemoryGraphClusterResponse,
    MemoryGraphEdgeResponse,
    MemoryGraphGenerationResponse,
    MemoryGraphNodeResponse,
    MemoryGraphResponse,
    MemoryGraphSummaryResponse,
    MemoryGraphVaultScopeResponse,
)
from ...services.memory_graph_projection import (
    MemoryGraphProjection,
    MemoryGraphProjectionCluster,
    MemoryGraphProjectionEdge,
    MemoryGraphProjectionNode,
    MemoryGraphProjectionSummary,
)


def memory_graph_response(
    projection: MemoryGraphProjection,
    *,
    vault_id: str,
    generation: MemoryGraphGenerationResponse,
) -> MemoryGraphResponse:
    return MemoryGraphResponse(
        generated_at=projection.generated_at,
        nodes=[memory_graph_node_response(node) for node in projection.nodes],
        edges=[
            memory_graph_edge_response(edge)
            for edge in projection.edges
            if edge.type != "belongs_to"
        ],
        clusters=[memory_graph_cluster_response(cluster) for cluster in projection.clusters],
        summary=memory_graph_summary_response(projection.summary),
        vault=MemoryGraphVaultScopeResponse(vault_id=vault_id),
        generation=generation,
        degraded_mode=generation.status == "degraded",
        redaction_note=projection.redaction_note,
    )


def memory_graph_node_response(node: MemoryGraphProjectionNode) -> MemoryGraphNodeResponse:
    return MemoryGraphNodeResponse(
        node_id=node.id,
        type=node.type,
        label=node.label,
        subtitle=node.subtitle,
        status=node.status,
        risk=node.risk_tier,
        size=node.size,
        confidence_label=node.confidence_label,
        source_label=node.source_label,
        updated_at=node.updated_at,
        allowed_actions=node.available_actions,
        confidence=(
            node.confidence
            if node.confidence > 0
            else _confidence_from_label(node.confidence_label)
        ),
        evidence_count=max(0, int(node.evidence_count)),
    )


def _confidence_from_label(value: str) -> float:
    text = str(value or "").casefold()
    if "high" in text or "高" in text:
        return 0.9
    if "low" in text or "低" in text:
        return 0.55
    if "hidden" in text or "隐藏" in text:
        return 0.0
    return 0.75


def memory_graph_edge_response(edge: MemoryGraphProjectionEdge) -> MemoryGraphEdgeResponse:
    return MemoryGraphEdgeResponse(
        edge_id=edge.id,
        source_node_id=edge.from_node,
        target_node_id=edge.to_node,
        relation_type=edge.type,
        risk=edge.risk,
        confidence=max(0.0, min(1.0, float(edge.strength))),
        evidence_count=max(0, int(edge.evidence_count)),
        status=edge.status,
        updated_at=edge.updated_at,
        allowed_actions=edge.available_actions,
    )


def memory_graph_cluster_response(
    cluster: MemoryGraphProjectionCluster,
) -> MemoryGraphClusterResponse:
    return MemoryGraphClusterResponse(
        cluster_id=cluster.id,
        label=cluster.label,
        node_ids=cluster.node_ids,
    )


def memory_graph_summary_response(
    summary: MemoryGraphProjectionSummary,
) -> MemoryGraphSummaryResponse:
    return MemoryGraphSummaryResponse(
        total_nodes=summary.total_nodes,
        pending_count=summary.pending_count,
        cleanup_count=summary.cleanup_count,
        hidden_count=summary.hidden_count,
    )
