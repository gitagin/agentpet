"""统一检索、本地资产统计、回执与陪伴整合相关端点。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...models.api import (
    CompanionConsolidationRunRequest,
    CompanionConsolidationRunResponse,
    CompanionRetrievalExplainabilityResponse,
    CompanionRetrievalReportListResponse,
    CompanionRetrievalReportResponse,
    LocalAssetStatsResponse,
    MemoryReceiptItemResponse,
    MemoryReceiptResponse,
    MemorySearchRequest,
    MemorySearchResponse,
)
from ...services.companion_consolidation import CompanionConsolidationService
from ...services.companion_retrieval import CompanionRetrievalReportStore
from ...services.local_assets import LocalAssetStatsService
from ...services.memory_read import UnifiedMemorySearchService
from ...services.memory_receipts import MemoryReceipt, MemoryReceiptItem, MemoryReceiptService
from ..wiring import audit_reason, record_audit
from .dependencies import (
    companion_consolidation_service_dependency,
    companion_retrieval_report_store_dependency,
    local_asset_stats_service_dependency,
    memory_receipt_service_dependency,
    unified_memory_search_service_dependency,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/search", response_model=MemorySearchResponse)
async def search_memory(
    search_request: MemorySearchRequest,
    service: UnifiedMemorySearchService = Depends(unified_memory_search_service_dependency),
) -> MemorySearchResponse:
    return service.search(
        query=search_request.query,
        top_k=search_request.top_k,
        mode=search_request.mode,
        source_scope=search_request.source_scope,
    )


@router.get("/local-assets", response_model=LocalAssetStatsResponse)
async def get_local_asset_stats(
    service: LocalAssetStatsService = Depends(local_asset_stats_service_dependency),
) -> LocalAssetStatsResponse:
    stats = service.summarize()
    return LocalAssetStatsResponse(
        vault_configured=stats.vault_configured,
        vault_id=stats.vault_id,
        chat_diary_days=stats.chat_diary_days,
        chat_diary_entries=stats.chat_diary_entries,
        long_term_memory_count=stats.long_term_memory_count,
        wiki_page_count=stats.wiki_page_count,
        task_count=stats.task_count,
        completed_task_count=stats.completed_task_count,
        latest_organization_at=stats.latest_organization_at,
        reversible_operation_count=stats.reversible_operation_count,
    )


@router.get("/receipts", response_model=MemoryReceiptResponse)
async def list_memory_receipts(
    request: Request,
    agent_run_id: str | None = None,
    limit: int = 50,
    service: MemoryReceiptService = Depends(memory_receipt_service_dependency),
) -> MemoryReceiptResponse:
    capped_limit = max(1, min(limit, 100))
    receipt = service.build(agent_run_id=agent_run_id, limit=capped_limit)
    return _memory_receipt_response(receipt)


@router.post("/companion/consolidation/runs", response_model=CompanionConsolidationRunResponse)
async def run_companion_consolidation(
    run_request: CompanionConsolidationRunRequest,
    request: Request,
    service: CompanionConsolidationService = Depends(companion_consolidation_service_dependency),
) -> CompanionConsolidationRunResponse:
    result = service.run_once(from_=run_request.from_, to=run_request.to, limit=run_request.limit)
    record_audit(
        request,
        action="memory.companion.consolidation.run",
        result="success",
        reason=audit_reason(
            request,
            run_id=result.run_id,
            source_count=str(result.source_count),
            output_count=str(result.output_count),
        ),
    )
    return _companion_consolidation_response(result)


@router.get("/companion/context-reports", response_model=CompanionRetrievalReportListResponse)
async def list_companion_context_reports(
    request: Request,
    agent_run_id: str | None = None,
    limit: int = 20,
    store: CompanionRetrievalReportStore = Depends(companion_retrieval_report_store_dependency),
) -> CompanionRetrievalReportListResponse:
    capped_limit = max(1, min(limit, 100))
    reports = store.list_reports(agent_run_id=agent_run_id, limit=capped_limit)
    return CompanionRetrievalReportListResponse(
        reports=[_companion_retrieval_report_response(report) for report in reports]
    )


def _memory_receipt_response(receipt: MemoryReceipt) -> MemoryReceiptResponse:
    return MemoryReceiptResponse(
        generated_at=receipt.generated_at,
        items=[_memory_receipt_item_response(item) for item in receipt.items],
    )


def _memory_receipt_item_response(item: MemoryReceiptItem) -> MemoryReceiptItemResponse:
    return MemoryReceiptItemResponse(
        id=item.id,
        kind=item.kind,
        title=item.title,
        detail=item.detail,
        safety_note=item.safety_note,
        action_label=item.action_label,
        related_memory_id=item.related_memory_id,
        created_at=item.created_at,
    )


def _companion_consolidation_response(result) -> CompanionConsolidationRunResponse:
    return CompanionConsolidationRunResponse(
        run_id=result.run_id,
        status=result.status,
        source_count=result.source_count,
        output_count=result.output_count,
        skipped_count=result.skipped_count,
        reason=result.reason,
        fact_ids=list(result.fact_ids),
        started_at=result.started_at,
        completed_at=result.completed_at,
    )


def _companion_retrieval_report_response(report) -> CompanionRetrievalReportResponse:
    return CompanionRetrievalReportResponse(
        id=report.id,
        agent_run_id=report.agent_run_id,
        strategy=report.strategy,
        candidate_count=report.candidate_count,
        selected_count=report.selected_count,
        duplicate_drop_count=report.duplicate_drop_count,
        per_scope_drop_count=report.per_scope_drop_count,
        budget_drop_count=report.budget_drop_count,
        item_budget=report.item_budget,
        per_scope_limit=report.per_scope_limit,
        char_budget=report.char_budget,
        used_chars=report.used_chars,
        source_counts=report.source_counts,
        selected_scopes=list(report.selected_scopes),
        created_at=report.created_at,
        explainability=CompanionRetrievalExplainabilityResponse.model_validate(report.explainability),
    )
