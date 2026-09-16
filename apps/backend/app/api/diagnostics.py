import json
import logging
from collections import Counter
from fastapi import APIRouter, Depends, Request, status

from ..config import get_settings
from ..models.api import DiagnosticsExportResponse, LocalStateResetRequest, LocalStateResetResponse, NegotiationStatsResponse, MemoryGraphRebuildResponse
from ..errors import AppError
from .idempotency import IdempotencyKeyHeader
from ..scheduler import ReminderSchedulerProtocol
from ..services.diagnostics import DiagnosticsExporter
from ..services.memory_maintenance import schedule_memory_maintenance
from ..services.local_state_reset import (
    MEMORY_RESET_CONFIRMATION_TEXT,
    RESET_CONFIRMATION_TEXT,
    LocalStateResetService,
    MemoryStateResetService,
)
from ..services.retrieval_factory import close_vector_index
from .wiring import active_vault_root, cached_active_vault_id, clear_cached_active_vault_id, database, production_action_lifecycle
from .wiring import refresh_retrieval_vector_index, reminder_scheduler, reset_chat_runs

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

logger = logging.getLogger(__name__)


@router.post("/memory-graph/rebuild", response_model=MemoryGraphRebuildResponse)
async def rebuild_memory_graph_projection(
    request: Request,
    idempotency_key: IdempotencyKeyHeader,
) -> MemoryGraphRebuildResponse:
    """Rebuild only the derived Kuzu projection; SQLite remains authoritative."""
    key = idempotency_key
    from ..agents.contracts import ActionProposal
    from ..agents.nodes.policy_guard import evaluate_action_proposal

    proposal = ActionProposal(
        proposal_id=f"proposal:memory.graph.rebuild:{key[:24]}",
        explicit_intent_ref=f"memory-graph-rebuild:{key}",
        action_type="memory.graph.rebuild",
        target_ref="memory-graph-projection",
        parameters={},
        expected_effect="从 SQLite 权威数据重建一个可删除的 Kuzu 图投影。",
        source_message_id=key,
    )
    policy = evaluate_action_proposal(proposal)
    if policy.decision != "approved":
        raise AppError("graph_rebuild_not_allowed", "图谱重建未通过本机安全策略。", 422)
    policy = policy.model_copy(update={"idempotency_key": key})
    outcome = await production_action_lifecycle(request).execute(
        proposal,
        policy,
        source_run_id=str(
            getattr(getattr(request, "state", None), "request_id", None)
            or f"memory-graph-rebuild:{key[:24]}"
        ),
    )
    receipt = outcome.receipt
    if receipt.status != "verified":
        raise AppError(
            "graph_rebuild_recovery_required",
            "图谱重建结果无法安全确认，SQLite 查询仍可用，请查看本地恢复记录。",
            409,
        )
    result = dict(receipt.result)
    return MemoryGraphRebuildResponse(
        operation_id=outcome.action.action_id,
        status=str(result.get("status") or "failed_recovery"),
        backend=str(result.get("backend") or "kuzu"),
        generation_id=str(result["generation_id"]) if result.get("generation_id") else None,
        source_revision=int(result.get("source_revision") or 0),
        node_count=int(result.get("node_count") or 0),
        edge_count=int(result.get("edge_count") or 0),
        degraded=bool(result.get("degraded")),
        fallback_code=str(result["fallback_code"]) if result.get("fallback_code") else None,
        replayed=outcome.duplicate,
    )

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
        # 先释放本地 Qdrant 客户端持有的 vector-index 锁，否则 Windows 上
        # 删除运行时目录会因 .lock 被占用而失败。
        _close_active_vector_index(request)
        service = LocalStateResetService(database(request), get_settings().data_dir)
        result = service.reset()
        clear_cached_active_vault_id(request)
        reset_chat_runs(request)
        if scheduler_available:
            scheduler.clear()
            # scheduler.clear() 会连任务清单一起清空（APScheduler jobstore），
            # 必须重新注册周期维护任务，否则重置后直到重启都没有自动衰减。
            schedule_memory_maintenance(scheduler, database(request).path)
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
            message=f"请输入确认词 {MEMORY_RESET_CONFIRMATION_TEXT} 后再重置记忆状态。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        vault_root = active_vault_root(request)
    except AppError:
        vault_root = None
    # 与 reset-local-state 对齐：先释放 Qdrant 本地锁，再删除 vector-index 目录，
    # 最后重建一个干净的向量索引实例，避免"重置记忆"后残留旧向量/旧缓存。
    _close_active_vector_index(request)
    service = MemoryStateResetService(database(request), get_settings().data_dir, vault_root=vault_root)
    result = service.reset()
    reset_chat_runs(request)
    refresh_retrieval_vector_index(request)
    return LocalStateResetResponse(
        status=result.status,
        cleared_tables=result.cleared_tables,
        removed_paths=result.removed_paths,
    )


def _close_active_vector_index(request: Request) -> None:
    retrieval = getattr(request.app.state, "retrieval_service", None)
    close_vector_index(getattr(retrieval, "vector_index", None))


def _load_metadata(value: object) -> dict[str, object]:
    try:
        metadata = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _canonical_agent_name(agent_id: str) -> str:
    return LEGACY_AGENT_ALIASES.get(agent_id, agent_id)
