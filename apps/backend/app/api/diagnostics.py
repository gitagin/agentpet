import json
from collections import Counter

from fastapi import APIRouter, Depends, Request, status

from ..config import get_settings
from ..errors import AppError
from ..models.api import DiagnosticsExportResponse, LocalStateResetRequest, LocalStateResetResponse, NegotiationStatsResponse
from ..scheduler import ReminderSchedulerProtocol
from ..services.diagnostics import DiagnosticsExporter
from ..services.local_state_reset import (
    MEMORY_RESET_CONFIRMATION_TEXT,
    RESET_CONFIRMATION_TEXT,
    LocalStateResetService,
    MemoryStateResetService,
)
from .wiring import cached_active_vault_id, clear_cached_active_vault_id, database
from .wiring import refresh_retrieval_vector_index, reminder_scheduler, reset_chat_runs

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

AGENT_OUTCOME_LABELS = {
    "retrieval_agent": "cited answer",
    "action_agent": "local action",
    "reflection_agent": "memory review",
    "chat_agent": "chat answer",
    "semantic_analysis_agent": "chat answer",
}

LEGACY_AGENT_ALIASES = {
    "memory_retrieval_agent": "retrieval_agent",
    "knowledge_retrieval_agent": "retrieval_agent",
    "context_retrieval_agent": "retrieval_agent",
    "knowledge_agent": "retrieval_agent",
    "wiki_manager_agent": "action_agent",
    "memory_proposal_agent": "action_agent",
    "task_agent": "action_agent",
    "diary_memory_extractor_agent": "reflection_agent",
    "continuity_agent": "reflection_agent",
}


@router.get("/export", response_model=DiagnosticsExportResponse)
async def export_diagnostics(
    request: Request,
    active_vault_id: str | None = Depends(cached_active_vault_id),
) -> DiagnosticsExportResponse:
    exporter = DiagnosticsExporter(database(request), get_settings())
    return exporter.export(active_vault_id=active_vault_id)


@router.get("/negotiation-stats", response_model=NegotiationStatsResponse)
async def negotiation_stats(request: Request) -> NegotiationStatsResponse:
    with database(request).session() as conn:
        rows = conn.execute(
            """
            SELECT negotiation_rounds, total_latency_ms, metadata_json
            FROM agent_actions
            WHERE action_type = 'agent.negotiation'
              AND negotiation_rounds > 0
            """
        ).fetchall()
    if not rows:
        return NegotiationStatsResponse()

    total = len(rows)
    fallback_count = 0
    agent_counter: Counter[str] = Counter()
    outcome_counter: Counter[str] = Counter()
    total_rounds = 0
    total_latency_ms = 0
    for row in rows:
        total_rounds += int(row["negotiation_rounds"] or 0)
        total_latency_ms += int(row["total_latency_ms"] or 0)
        metadata = _load_metadata(row["metadata_json"])
        if metadata.get("fallback") is True:
            fallback_count += 1
        agents_invoked = metadata.get("agents_invoked")
        if isinstance(agents_invoked, list):
            agents = [_canonical_agent_name(str(agent)) for agent in agents_invoked if isinstance(agent, str)]
            agent_counter.update(agents)
            outcome_counter.update(AGENT_OUTCOME_LABELS.get(agent, "chat answer") for agent in agents)

    return NegotiationStatsResponse(
        avg_rounds=total_rounds / total,
        avg_latency_ms=total_latency_ms / total,
        fallback_rate=fallback_count / total,
        top_agents_invoked=[agent for agent, _count in agent_counter.most_common(3)],
        top_outcomes_supported=[outcome for outcome, _count in outcome_counter.most_common(3)],
        outcome_support_counts=dict(outcome_counter),
    )


@router.post("/reset-local-state", response_model=LocalStateResetResponse)
async def reset_local_state(
    request: Request,
    reset_request: LocalStateResetRequest,
    scheduler=Depends(reminder_scheduler),
) -> LocalStateResetResponse:
    if reset_request.confirmation != RESET_CONFIRMATION_TEXT:
        raise AppError(
            code="reset_confirmation_required",
            message=f"请输入确认词 {RESET_CONFIRMATION_TEXT} 后再重置本地状态。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    scheduler_available = isinstance(scheduler, ReminderSchedulerProtocol)
    if scheduler_available:
        scheduler.pause()
    try:
        service = LocalStateResetService(database(request), get_settings().data_dir)
        result = service.reset()
        clear_cached_active_vault_id(request)
        reset_chat_runs(request)
        if scheduler_available:
            scheduler.clear()
        refresh_retrieval_vector_index(request)
    finally:
        if scheduler_available:
            scheduler.resume()
    return LocalStateResetResponse(
        status=result.status,
        cleared_tables=result.cleared_tables,
        removed_paths=result.removed_paths,
    )


@router.post("/reset-memory-state", response_model=LocalStateResetResponse)
async def reset_memory_state(request: Request, reset_request: LocalStateResetRequest) -> LocalStateResetResponse:
    if reset_request.confirmation != MEMORY_RESET_CONFIRMATION_TEXT:
        raise AppError(
            code="memory_reset_confirmation_required",
            message=f"璇疯緭鍏ョ‘璁よ瘝 {MEMORY_RESET_CONFIRMATION_TEXT} 鍚庡啀閲嶇疆璁板繂鐘舵€併€?",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    service = MemoryStateResetService(database(request), get_settings().data_dir)
    result = service.reset()
    reset_chat_runs(request)
    return LocalStateResetResponse(
        status=result.status,
        cleared_tables=result.cleared_tables,
        removed_paths=result.removed_paths,
    )


def _load_metadata(value: object) -> dict[str, object]:
    try:
        metadata = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _canonical_agent_name(agent_id: str) -> str:
    return LEGACY_AGENT_ALIASES.get(agent_id, agent_id)
