"""长期记忆图谱端点：投影、事实列表、导出预览与事实操作。

事实操作使用一个枚举校验的参数化端点。旧的 5 个 URL 仅作为显式 deprecated
兼容入口注册，并全部委托给同一个 service（backlog #12）。
"""

from __future__ import annotations

import json
from fastapi import APIRouter, Depends, Query, Request

from ...models.api import (
    MemoryGraphExportPreviewResponse,
    MemoryGraphFactActionResponse,
    MemoryGraphFactListResponse,
    MemoryGraphProjectionResponse,
)
from ...services.memory_graph_actions import (
    MemoryGraphFactAction,
    MemoryGraphFactActionService,
)
from ...services.memory_graph_projection import MemoryGraphProjectionService
from ...utils.time import utc_now_iso
from ..wiring import audit_reason, record_audit
from .dependencies import (
    graph_fact_action_service_dependency,
    memory_graph_projection_service_dependency,
    memory_graph_store_dependency,
)
from .graph_presenters import (
    graph_export_item,
    graph_fact_response,
    memory_graph_markdown_preview,
    memory_graph_projection_response,
)
from .shared import RAW_EVIDENCE_REDACTION_NOTE

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/graph-projection", response_model=MemoryGraphProjectionResponse)
async def get_memory_graph_projection(
    max_nodes: int = 40,
    service: MemoryGraphProjectionService = Depends(memory_graph_projection_service_dependency),
) -> MemoryGraphProjectionResponse:
    capped_nodes = max(5, min(max_nodes, 80))
    projection = service.build(max_nodes=capped_nodes)
    return memory_graph_projection_response(projection)


@router.get("/graph/facts", response_model=MemoryGraphFactListResponse)
async def list_memory_graph_facts(
    request: Request,
    # Renamed from `status` to avoid shadowing fastapi.status inside the
    # handler; the query parameter name stays `status` via the alias.
    status_filter: str | None = Query(default=None, alias="status"),
    query: str | None = None,
    limit: int = 50,
    store=Depends(memory_graph_store_dependency),
) -> MemoryGraphFactListResponse:
    capped_limit = max(1, min(limit, 300))
    facts = store.list_facts(status=status_filter, query=query, limit=capped_limit)
    return MemoryGraphFactListResponse(facts=[graph_fact_response(fact) for fact in facts])


@router.get("/graph/export-preview", response_model=MemoryGraphExportPreviewResponse)
async def export_memory_graph_preview(
    request: Request,
    export_format: str = Query(default="markdown", alias="format"),
    status_filter: str | None = Query(default=None, alias="status"),
    query: str | None = None,
    limit: int = 100,
    store=Depends(memory_graph_store_dependency),
) -> MemoryGraphExportPreviewResponse:
    preview_format = "json" if export_format == "json" else "markdown"
    capped_limit = max(1, min(limit, 500))
    facts = store.list_facts(status=status_filter, query=query, limit=capped_limit)
    items = [graph_export_item(fact) for fact in facts]
    payload = [item.model_dump() for item in items]
    json_preview = json.dumps(payload, ensure_ascii=False, indent=2)
    markdown_preview = memory_graph_markdown_preview(items)
    record_audit(
        request,
        action="memory.graph.export_preview",
        result="success",
        reason=audit_reason(
            request,
            format=preview_format,
            status=status_filter or "all",
            item_count=str(len(items)),
        ),
    )
    return MemoryGraphExportPreviewResponse(
        generated_at=utc_now_iso(),
        format=preview_format,
        item_count=len(items),
        items=items,
        json_preview=json_preview,
        markdown_preview=markdown_preview,
        redaction_note=RAW_EVIDENCE_REDACTION_NOTE,
    )


def execute_graph_fact_action(
    request: Request,
    service: MemoryGraphFactActionService,
    fact_id: str,
    action: MemoryGraphFactAction,
) -> MemoryGraphFactActionResponse:
    result = service.apply(fact_id, action)
    record_audit(
        request,
        action=result.audit_action,
        result="success",
        reason=audit_reason(request, fact_id=fact_id),
    )
    return MemoryGraphFactActionResponse(fact_id=result.fact_id, status=result.status.value)


@router.post(
    "/graph/facts/{fact_id}/actions/{action}",
    response_model=MemoryGraphFactActionResponse,
)
async def apply_memory_graph_fact_action(
    fact_id: str,
    action: MemoryGraphFactAction,
    request: Request,
    service: MemoryGraphFactActionService = Depends(graph_fact_action_service_dependency),
) -> MemoryGraphFactActionResponse:
    return execute_graph_fact_action(request, service, fact_id, action)


def legacy_graph_fact_action_endpoint(action: MemoryGraphFactAction):
    async def endpoint(
        fact_id: str,
        request: Request,
        service: MemoryGraphFactActionService = Depends(graph_fact_action_service_dependency),
    ) -> MemoryGraphFactActionResponse:
        return execute_graph_fact_action(request, service, fact_id, action)

    return endpoint


for legacy_action, endpoint_name in (
    (MemoryGraphFactAction.CONFIRM, "confirm_memory_graph_fact"),
    (MemoryGraphFactAction.REJECT, "reject_memory_graph_fact"),
    (MemoryGraphFactAction.WRONG, "wrong_memory_graph_fact"),
    (MemoryGraphFactAction.SENSITIVE_BLOCK, "sensitive_block_memory_graph_fact"),
    (MemoryGraphFactAction.ARCHIVE, "archive_memory_graph_fact"),
):
    legacy_endpoint = legacy_graph_fact_action_endpoint(legacy_action)
    legacy_endpoint.__name__ = endpoint_name
    router.add_api_route(
        f"/graph/facts/{{fact_id}}/{legacy_action.value}",
        legacy_endpoint,
        methods=["POST"],
        response_model=MemoryGraphFactActionResponse,
        deprecated=True,
        name=endpoint_name,
    )
