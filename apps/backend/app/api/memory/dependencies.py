from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator

from fastapi import Depends, Request

from ...errors import AppError
from ...services.companion_consolidation import CompanionConsolidationService
from ...services.companion_retrieval import CompanionRetrievalReportStore
from ...services.diary_memory import DiaryMemoryService
from ...services.local_assets import LocalAssetStatsService
from ...services.memory_entity_graph import MemoryEntityGraphStore
from ...services.memory_graph_projection import MemoryGraphProjectionService
from ...services.memory_hygiene_suggestions import MemoryHygieneSuggestionService
from ...services.memory_read import (
    DiaryMemorySourceAdapter,
    GraphMemorySourceAdapter,
    RetrievalMemorySourceAdapter,
    UnifiedMemorySearchService,
)
from ...services.memory_receipts import MemoryReceiptService
from ...services.memory_review import MemoryReviewService
from ...services.retrospectives import RetrospectiveService
from ..wiring import (
    active_vault_id,
    active_vault_root,
    companion_consolidation_service,
    companion_retrieval_report_store,
    database,
    diary_memory_service,
    memory_entity_graph_store,
    retrospective_service,
    retrieval_service,
)


async def database_connection_dependency(request: Request) -> AsyncIterator[sqlite3.Connection]:
    with database(request).session() as conn:
        yield conn


async def diary_memory_service_dependency(request: Request) -> AsyncIterator[DiaryMemoryService]:
    service = diary_memory_service(request)
    try:
        yield service
    finally:
        service.close()


async def memory_entity_graph_store_dependency(request: Request) -> AsyncIterator[MemoryEntityGraphStore]:
    store = memory_entity_graph_store(request)
    try:
        yield store
    finally:
        store.close()


async def memory_graph_projection_service_dependency(
    request: Request,
    conn: sqlite3.Connection = Depends(database_connection_dependency),
) -> AsyncIterator[MemoryGraphProjectionService]:
    try:
        vault_id = active_vault_id(request)
    except AppError as exc:
        if exc.code != "vault_not_configured":
            raise
        vault_id = None
    yield MemoryGraphProjectionService(conn, vault_id=vault_id)


async def memory_receipt_service_dependency(
    conn: sqlite3.Connection = Depends(database_connection_dependency),
) -> AsyncIterator[MemoryReceiptService]:
    yield MemoryReceiptService(conn)


async def local_asset_stats_service_dependency(
    request: Request,
    conn: sqlite3.Connection = Depends(database_connection_dependency),
) -> AsyncIterator[LocalAssetStatsService]:
    vault_id: str | None
    vault_root: str | None
    try:
        vault_id = active_vault_id(request)
        vault_root = active_vault_root(request)
    except AppError as exc:
        if exc.code != "vault_not_configured":
            raise
        vault_id = None
        vault_root = None
    yield LocalAssetStatsService(conn, vault_id=vault_id, vault_root=vault_root)


async def memory_hygiene_suggestion_service_dependency(
    request: Request,
) -> AsyncIterator[MemoryHygieneSuggestionService]:
    service = MemoryHygieneSuggestionService(database(request).path)
    try:
        yield service
    finally:
        service.close()


async def retrospective_service_dependency(request: Request) -> AsyncIterator[RetrospectiveService]:
    service = retrospective_service(request)
    try:
        yield service
    finally:
        service.close()


async def companion_consolidation_service_dependency(
    request: Request,
) -> AsyncIterator[CompanionConsolidationService]:
    service = companion_consolidation_service(request)
    try:
        yield service
    finally:
        service.close()


async def companion_retrieval_report_store_dependency(
    request: Request,
) -> AsyncIterator[CompanionRetrievalReportStore]:
    store = companion_retrieval_report_store(request)
    try:
        yield store
    finally:
        store.close()


def unified_memory_search_service_dependency(request: Request) -> UnifiedMemorySearchService:
    return UnifiedMemorySearchService(
        (
            RetrievalMemorySourceAdapter(
                retrieval_service(request),
                vault_id=active_vault_id(request),
            ),
            GraphMemorySourceAdapter(
                lambda: memory_entity_graph_store(request),
                answerable_only=True,
                vault_id=active_vault_id(request),
            ),
            DiaryMemorySourceAdapter(lambda: diary_memory_service(request)),
        )
    )


async def memory_review_service_dependency(
    request: Request,
) -> AsyncIterator[MemoryReviewService]:
    with database(request).session() as conn:
        yield MemoryReviewService(conn)
