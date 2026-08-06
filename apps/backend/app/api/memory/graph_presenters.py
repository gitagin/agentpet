from __future__ import annotations

from ...models.api import (
    MemoryGraphExportItem,
    MemoryGraphFactResponse,
    MemoryGraphProjectionClusterResponse,
    MemoryGraphProjectionEdgeResponse,
    MemoryGraphProjectionNodeResponse,
    MemoryGraphProjectionResponse,
    MemoryGraphProjectionSummaryResponse,
)
from ...services.memory_graph_projection import (
    MemoryGraphProjection,
    MemoryGraphProjectionCluster,
    MemoryGraphProjectionEdge,
    MemoryGraphProjectionNode,
    MemoryGraphProjectionSummary,
)
from .shared import (
    RAW_EVIDENCE_REDACTION_NOTE,
    graph_lifecycle_status,
    safe_export_metadata,
    safe_export_optional,
    safe_export_value,
)


def graph_fact_response(fact) -> MemoryGraphFactResponse:
    return MemoryGraphFactResponse(
        fact_id=fact.id,
        category=fact.category,
        subject=fact.subject,
        predicate=fact.predicate,
        object=fact.object,
        status=fact.status.value,
        lifecycle_status=graph_lifecycle_status(fact.status.value),
        confidence=fact.confidence,
        source_text=fact.source_text,
        source_type=fact.source_type,
        support_count=fact.support_count,
        conflicts_with=fact.conflicts_with,
        superseded_by=fact.superseded_by,
        memory_type=fact.memory_type,
        entity_type=fact.entity_type,
        occurred_at=fact.occurred_at,
        expires_at=fact.expires_at,
        metadata_json=fact.metadata_json,
        importance=fact.importance,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
    )


def memory_graph_projection_response(projection: MemoryGraphProjection) -> MemoryGraphProjectionResponse:
    return MemoryGraphProjectionResponse(
        generated_at=projection.generated_at,
        nodes=[memory_graph_projection_node_response(node) for node in projection.nodes],
        edges=[memory_graph_projection_edge_response(edge) for edge in projection.edges],
        clusters=[memory_graph_projection_cluster_response(cluster) for cluster in projection.clusters],
        summary=memory_graph_projection_summary_response(projection.summary),
        redaction_note=projection.redaction_note,
    )


def memory_graph_projection_node_response(node: MemoryGraphProjectionNode) -> MemoryGraphProjectionNodeResponse:
    return MemoryGraphProjectionNodeResponse(
        id=node.id,
        type=node.type,
        label=node.label,
        subtitle=node.subtitle,
        status=node.status,
        risk_tier=node.risk_tier,
        size=node.size,
        confidence_label=node.confidence_label,
        source_label=node.source_label,
        updated_at=node.updated_at,
        available_actions=node.available_actions,
    )


def memory_graph_projection_edge_response(edge: MemoryGraphProjectionEdge) -> MemoryGraphProjectionEdgeResponse:
    return MemoryGraphProjectionEdgeResponse(
        id=edge.id,
        **{
            "from": edge.from_node,
            "to": edge.to_node,
            "type": edge.type,
            "strength": edge.strength,
        },
    )


def memory_graph_projection_cluster_response(
    cluster: MemoryGraphProjectionCluster,
) -> MemoryGraphProjectionClusterResponse:
    return MemoryGraphProjectionClusterResponse(
        id=cluster.id,
        label=cluster.label,
        node_ids=cluster.node_ids,
    )


def memory_graph_projection_summary_response(
    summary: MemoryGraphProjectionSummary,
) -> MemoryGraphProjectionSummaryResponse:
    return MemoryGraphProjectionSummaryResponse(
        total_nodes=summary.total_nodes,
        pending_count=summary.pending_count,
        cleanup_count=summary.cleanup_count,
        hidden_count=summary.hidden_count,
    )


def graph_export_item(fact) -> MemoryGraphExportItem:
    return MemoryGraphExportItem(
        fact_id=fact.id,
        category=safe_export_value(fact.category),
        subject=safe_export_value(fact.subject),
        predicate=safe_export_value(fact.predicate),
        object=safe_export_value(fact.object),
        status=fact.status.value,
        lifecycle_status=graph_lifecycle_status(fact.status.value),
        confidence=fact.confidence,
        source_type=safe_export_value(fact.source_type),
        support_count=fact.support_count,
        conflicts_with=fact.conflicts_with,
        superseded_by=fact.superseded_by,
        memory_type=safe_export_optional(fact.memory_type),
        entity_type=safe_export_optional(fact.entity_type),
        occurred_at=fact.occurred_at,
        expires_at=fact.expires_at,
        metadata=safe_export_metadata(fact.metadata_json),
        importance=fact.importance,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
    )


def memory_graph_markdown_preview(items: list[MemoryGraphExportItem]) -> str:
    lines = ["# 长期记忆导出预览", "", f"> {RAW_EVIDENCE_REDACTION_NOTE}", ""]
    if not items:
        lines.append("_没有匹配此导出预览的长期记忆事实。_")
        return "\n".join(lines)
    for item in items:
        lines.extend(
            [
                f"## {item.subject} {item.predicate} {item.object}",
                "",
                f"- fact_id: `{item.fact_id}`",
                f"- status: `{item.status}`",
                f"- category: `{item.category}`",
                f"- confidence: {item.confidence:.2f}",
                f"- support_count: {item.support_count}",
                f"- source_type: `{item.source_type}`",
                f"- importance: {item.importance:.2f}",
                f"- updated_at: `{item.updated_at}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
