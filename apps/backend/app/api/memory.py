from fastapi import APIRouter, Depends, Request, status

from ..errors import AppError
from ..models.api import (
    CompanionConsolidationRunRequest,
    CompanionConsolidationRunResponse,
    CompanionRetrievalReportListResponse,
    CompanionRetrievalReportResponse,
    DiaryMemoryObjectResponse,
    DiaryMemorySearchRequest,
    DiaryMemorySearchResponse,
    DiaryMemorySourceResponse,
    MemoryGraphFactActionResponse,
    MemoryGraphFactListResponse,
    MemoryGraphFactResponse,
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemoryProposalListResponse,
    MemoryProposalResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    RejectProposalRequest,
)
from ..services.agent_actions import AgentActionCreate
from ..services.diary_memory import (
    DiaryMemoryNotFoundError,
    DiaryMemorySearch,
    diary_records_to_search_results,
)
from ..services.memory import MemoryService
from ..services.memory_policy import evaluate_memory_content
from .wiring import (
    active_vault_id,
    audit_reason,
    companion_consolidation_service,
    companion_retrieval_report_store,
    diary_memory_service,
    map_memory_error,
    memory_service_dependency,
    memory_graph_store,
    record_audit,
    record_agent_action,
    prepend_graph_memory_results,
    retrieval_service,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/search", response_model=MemorySearchResponse)
async def search_memory(search_request: MemorySearchRequest, request: Request) -> MemorySearchResponse:
    if search_request.source_scope == "diary_objects":
        service = diary_memory_service(request)
        try:
            records = service.search(DiaryMemorySearch(query=search_request.query, top_k=search_request.top_k))
        finally:
            service.close()
        return MemorySearchResponse(
            results=diary_records_to_search_results(records),
            metadata={"semantic_available": False, "retrieval_mode": "diary_object"},
        )
    response = retrieval_service(request).search(
        vault_id=active_vault_id(request),
        query=search_request.query,
        top_k=search_request.top_k,
        source_scope=search_request.source_scope,
        mode=search_request.mode,
    )
    if search_request.source_scope in {"personal_memory", "all"}:
        response = prepend_graph_memory_results(
            request,
            response,
            query=search_request.query,
            top_k=search_request.top_k,
        )
    if search_request.source_scope == "all":
        service = diary_memory_service(request)
        try:
            diary_results = diary_records_to_search_results(
                service.search(DiaryMemorySearch(query=search_request.query, top_k=search_request.top_k))
            )
        finally:
            service.close()
        response = response.model_copy(update={"results": [*diary_results, *response.results][: search_request.top_k]})
    return response


@router.post("/diary/search", response_model=DiaryMemorySearchResponse)
async def search_diary_memory(
    search_request: DiaryMemorySearchRequest,
    request: Request,
) -> DiaryMemorySearchResponse:
    service = diary_memory_service(request)
    try:
        records = service.search(
            DiaryMemorySearch(
                query=search_request.query,
                type=search_request.type,
                topic=search_request.topic,
                emotion=search_request.emotion,
                people=tuple(search_request.people),
                min_importance=search_request.min_importance,
                from_=search_request.from_,
                to=search_request.to,
                top_k=search_request.top_k,
            )
        )
    finally:
        service.close()
    return DiaryMemorySearchResponse(objects=[_diary_memory_response(record) for record in records])


@router.get("/diary/{object_id}", response_model=DiaryMemoryObjectResponse)
async def get_diary_memory_object(object_id: str, request: Request) -> DiaryMemoryObjectResponse:
    service = diary_memory_service(request)
    try:
        record = service.get(object_id)
    except DiaryMemoryNotFoundError as exc:
        raise AppError(
            code="diary_memory_not_found",
            message="未找到结构化聊天日记记忆。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"object_id": object_id},
        ) from exc
    finally:
        service.close()
    return _diary_memory_response(record)


@router.get("/graph/facts", response_model=MemoryGraphFactListResponse)
async def list_memory_graph_facts(
    request: Request,
    status: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> MemoryGraphFactListResponse:
    store = memory_graph_store(request)
    try:
        facts = store.list_facts(status=status, query=query, limit=limit)
    finally:
        store.close()
    return MemoryGraphFactListResponse(facts=[_graph_fact_response(fact) for fact in facts])


@router.post("/graph/facts/{fact_id}/confirm", response_model=MemoryGraphFactActionResponse)
async def confirm_memory_graph_fact(fact_id: str, request: Request) -> MemoryGraphFactActionResponse:
    store = memory_graph_store(request)
    try:
        fact = store.update_status(fact_id, "active", reason="user_confirmed")
    finally:
        store.close()
    record_audit(
        request,
        action="memory.graph.confirm",
        result="success",
        reason=audit_reason(request, fact_id=fact_id),
    )
    return MemoryGraphFactActionResponse(fact_id=fact.id, status=fact.status.value)


@router.post("/graph/facts/{fact_id}/reject", response_model=MemoryGraphFactActionResponse)
async def reject_memory_graph_fact(fact_id: str, request: Request) -> MemoryGraphFactActionResponse:
    store = memory_graph_store(request)
    try:
        fact = store.update_status(fact_id, "rejected", reason="user_rejected")
    finally:
        store.close()
    record_audit(
        request,
        action="memory.graph.reject",
        result="success",
        reason=audit_reason(request, fact_id=fact_id),
    )
    return MemoryGraphFactActionResponse(fact_id=fact.id, status=fact.status.value)


@router.post("/graph/facts/{fact_id}/archive", response_model=MemoryGraphFactActionResponse)
async def archive_memory_graph_fact(fact_id: str, request: Request) -> MemoryGraphFactActionResponse:
    store = memory_graph_store(request)
    try:
        fact = store.update_status(fact_id, "archived", reason="user_archived")
    finally:
        store.close()
    record_audit(
        request,
        action="memory.graph.archive",
        result="success",
        reason=audit_reason(request, fact_id=fact_id),
    )
    return MemoryGraphFactActionResponse(fact_id=fact.id, status=fact.status.value)


@router.post("/companion/consolidation/runs", response_model=CompanionConsolidationRunResponse)
async def run_companion_consolidation(
    run_request: CompanionConsolidationRunRequest,
    request: Request,
) -> CompanionConsolidationRunResponse:
    service = companion_consolidation_service(request)
    try:
        result = service.run_once(from_=run_request.from_, to=run_request.to, limit=run_request.limit)
    finally:
        service.graph_store.close()
        service.close()
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
) -> CompanionRetrievalReportListResponse:
    store = companion_retrieval_report_store(request)
    try:
        reports = store.list_reports(agent_run_id=agent_run_id, limit=limit)
    finally:
        store.close()
    return CompanionRetrievalReportListResponse(
        reports=[_companion_retrieval_report_response(report) for report in reports]
    )


@router.post("/proposals", response_model=MemoryProposalResponse)
async def create_memory_proposal(
    proposal_request: MemoryProposalCreateRequest,
    request: Request,
    service: MemoryService = Depends(memory_service_dependency),
) -> MemoryProposalResponse:
    policy = evaluate_memory_content(proposal_request.content)
    if not policy.allowed:
        record_audit(
            request,
            action="memory.proposal.create",
            result="denied",
            target_path=proposal_request.target_path,
            reason=audit_reason(request, code="sensitive_memory_rejected", policy=policy.reason),
        )
        raise AppError(
            code="sensitive_memory_rejected",
            message="疑似密钥或凭据的敏感内容不能保存为长期记忆。",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"reason": policy.reason or "sensitive_content"},
        )
    try:
        proposal = service.create_proposal(
            type=proposal_request.type,
            content=proposal_request.content,
            target_path=proposal_request.target_path,
            source_message_id=proposal_request.source_message_id,
        )
    except Exception as exc:
        record_audit(
            request,
            action="memory.proposal.create",
            result="failed",
            target_path=proposal_request.target_path,
            reason=audit_reason(request, code=exc.__class__.__name__),
        )
        raise map_memory_error(exc) from exc
    record_audit(
        request,
        action="memory.proposal.create",
        result="success",
        target_path=proposal.target_path,
        reason=audit_reason(request, proposal_id=proposal.id),
    )
    record_agent_action(
        request,
        AgentActionCreate(
            action_type="memory.proposal.ask",
            title="需要确认长期记忆",
            summary=proposal.content[:180],
            source_message_id=proposal.source_message_id,
            risk_tier="medium",
            decision="ask",
            status="pending",
            target_paths=(proposal.target_path,),
            metadata={"proposal_id": proposal.id, "proposal_type": proposal.type.value},
            reversible=False,
        ),
    )
    return MemoryProposalResponse(
        proposal_id=proposal.id,
        status=proposal.status.value,
        preview_markdown=proposal.content,
        target_path=proposal.target_path,
    )


@router.get("/proposals", response_model=MemoryProposalListResponse)
async def list_memory_proposals(
    service: MemoryService = Depends(memory_service_dependency),
) -> MemoryProposalListResponse:
    proposals = service.list_pending()
    return MemoryProposalListResponse(
        proposals=[
            MemoryProposalResponse(
                proposal_id=proposal.id,
                status=proposal.status.value,
                preview_markdown=proposal.content,
                target_path=proposal.target_path,
            )
            for proposal in proposals
        ]
    )


@router.post("/proposals/{proposal_id}/confirm", response_model=MemoryProposalActionResponse)
async def confirm_memory_proposal(
    proposal_id: str,
    request: Request,
    service: MemoryService = Depends(memory_service_dependency),
) -> MemoryProposalActionResponse:
    try:
        result = service.confirm_proposal(proposal_id)
    except Exception as exc:
        record_audit(
            request,
            action="memory.proposal.confirm",
            result="failed",
            reason=audit_reason(request, proposal_id=proposal_id, code=exc.__class__.__name__),
        )
        raise map_memory_error(exc) from exc
    record_audit(
        request,
        action="memory.proposal.confirm",
        result="success",
        target_path=result.written_path,
        reason=audit_reason(request, proposal_id=result.proposal_id, index_job_id=result.index_job_id),
    )
    action = record_agent_action(
        request,
        AgentActionCreate(
            action_type="memory.proposal.confirm",
            title="已写入长期记忆",
            summary=result.written_path or "",
            risk_tier="medium",
            decision="ask",
            status="completed",
            target_paths=tuple([result.written_path] if result.written_path else []),
            metadata={"proposal_id": result.proposal_id, "index_job_id": result.index_job_id},
            reversible=False,
        ),
    )
    return MemoryProposalActionResponse(
        proposal_id=result.proposal_id,
        status=result.status.value,
        written_path=result.written_path,
        index_job_id=result.index_job_id,
        action_id=action.action_id,
    )


@router.post("/proposals/{proposal_id}/reject", response_model=MemoryProposalActionResponse)
async def reject_memory_proposal(
    proposal_id: str,
    reject_request: RejectProposalRequest,
    request: Request,
    service: MemoryService = Depends(memory_service_dependency),
) -> MemoryProposalActionResponse:
    try:
        proposal = service.reject_proposal(proposal_id, reject_request.reason)
    except Exception as exc:
        record_audit(
            request,
            action="memory.proposal.reject",
            result="failed",
            reason=audit_reason(request, proposal_id=proposal_id, code=exc.__class__.__name__),
        )
        raise map_memory_error(exc) from exc
    record_audit(
        request,
        action="memory.proposal.reject",
        result="success",
        target_path=proposal.target_path,
        reason=audit_reason(request, proposal_id=proposal.id),
    )
    action = record_agent_action(
        request,
        AgentActionCreate(
            action_type="memory.proposal.reject",
            title="已取消长期记忆候选",
            summary=proposal.rejected_reason or "",
            risk_tier="low",
            decision="auto",
            status="completed",
            target_paths=(proposal.target_path,),
            metadata={"proposal_id": proposal.id},
            reversible=False,
        ),
    )
    return MemoryProposalActionResponse(
        proposal_id=proposal.id,
        status=proposal.status.value,
        action_id=action.action_id,
    )


def _graph_fact_response(fact) -> MemoryGraphFactResponse:
    return MemoryGraphFactResponse(
        fact_id=fact.id,
        category=fact.category,
        subject=fact.subject,
        predicate=fact.predicate,
        object=fact.object,
        status=fact.status.value,
        confidence=fact.confidence,
        source_text=fact.source_text,
        source_type=fact.source_type,
        support_count=fact.support_count,
        conflicts_with=fact.conflicts_with,
        memory_type=fact.memory_type,
        entity_type=fact.entity_type,
        occurred_at=fact.occurred_at,
        expires_at=fact.expires_at,
        metadata_json=fact.metadata_json,
        importance=fact.importance,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
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
    )


def _diary_memory_response(record) -> DiaryMemoryObjectResponse:
    return DiaryMemoryObjectResponse(
        id=record.id,
        vault_id=record.vault_id,
        type=record.type,
        summary=record.summary,
        topic=record.topic,
        emotion=record.emotion,
        people=list(record.people),
        keywords=list(record.keywords),
        importance=record.importance,
        confidence=record.confidence,
        occurred_at=record.occurred_at,
        timezone=record.timezone,
        status=record.status.value,
        extraction_model=record.extraction_model,
        created_at=record.created_at,
        updated_at=record.updated_at,
        sources=[
            DiaryMemorySourceResponse(
                source_type=source.source_type,
                source_id=source.source_id,
                conversation_id=source.conversation_id,
                user_message_id=source.user_message_id,
                assistant_message_id=source.assistant_message_id,
                agent_run_id=source.agent_run_id,
                markdown_path=source.markdown_path,
                note_id=source.note_id,
                chunk_id=source.chunk_id,
            )
            for source in record.sources
        ],
    )
