import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, status

from ..errors import AppError
from ..models.api import (
    CompanionConsolidationRunRequest,
    CompanionConsolidationRunResponse,
    CompanionRetrievalExplainabilityResponse,
    CompanionRetrievalReportListResponse,
    CompanionRetrievalReportResponse,
    DiaryMemoryObjectResponse,
    DiaryMemorySearchRequest,
    DiaryMemorySearchResponse,
    DiaryMemorySourceResponse,
    LocalAssetStatsResponse,
    MemoryFeedbackRequest,
    MemoryFeedbackResponse,
    MemoryGraphFactActionResponse,
    MemoryGraphExportItem,
    MemoryGraphExportPreviewResponse,
    MemoryGraphFactListResponse,
    MemoryGraphFactResponse,
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemoryProposalListResponse,
    MemoryProposalResponse,
    MemoryProfileActionRequest,
    MemoryProfileActionResponse,
    MemoryProfileAvailableActionResponse,
    MemoryProfileDetailResponse,
    MemoryProfileProjectionItemResponse,
    MemoryProfileProjectionResponse,
    MemoryProfileSourceSummaryResponse,
    MemoryReviewActionRequest,
    MemoryReviewItemResponse,
    MemoryReviewResponse,
    MemoryReviewSummaryResponse,
    MemoryReceiptItemResponse,
    MemoryReceiptResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    RejectProposalRequest,
    RetrospectiveReportRequest,
    RetrospectiveReportResponse,
    RetrospectiveResponse,
)
from ..models.common import new_id
from ..models.enums import MemoryFactStatus
from ..services.agent_actions import AgentActionCreate
from ..services.diary_memory import (
    DiaryMemoryNotFoundError,
    DiaryMemorySearch,
    diary_records_to_search_results,
)
from ..services.memory import MemoryService
from ..services.memory_lifecycle import MemoryLifecycleTransitionError
from ..services.memory_policy import evaluate_memory_content
from ..services.memory_profile_projection import (
    MemoryProfileProjection,
    MemoryProfileProjectionAction,
    MemoryProfileProjectionDetail,
    MemoryProfileProjectionItem,
    MemoryProfileProjectionSourceSummary,
    MemoryProfileProjectionTarget,
    MemoryProfileProjectionService,
)
from ..services.memory_receipts import MemoryReceipt, MemoryReceiptItem, MemoryReceiptService
from ..services.local_assets import LocalAssetStatsService
from .wiring import (
    active_vault_id,
    active_vault_root,
    audit_reason,
    companion_consolidation_service,
    companion_retrieval_report_store,
    database,
    diary_memory_service,
    map_memory_error,
    memory_service_dependency,
    memory_graph_store,
    memory_lifecycle_service,
    record_audit,
    record_agent_action,
    prepend_graph_memory_results,
    retrieval_service,
    retrospective_service,
)

router = APIRouter(prefix="/memory", tags=["memory"])

RAW_EVIDENCE_REDACTION_NOTE = (
    "原始来源证据已从此预览中省略。文件导出必须通过已确认的安全路径处理。"
)


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


@router.get("/local-assets", response_model=LocalAssetStatsResponse)
async def get_local_asset_stats(request: Request) -> LocalAssetStatsResponse:
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

    with database(request).connect() as conn:
        stats = LocalAssetStatsService(conn, vault_id=vault_id, vault_root=vault_root).summarize()
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


@router.get("/profile-projection", response_model=MemoryProfileProjectionResponse)
async def get_memory_profile_projection(request: Request, limit: int = 120) -> MemoryProfileProjectionResponse:
    capped_limit = max(1, min(limit, 300))
    with database(request).connect() as conn:
        projection = MemoryProfileProjectionService(conn).build(limit=capped_limit)
    return _memory_profile_projection_response(projection)


@router.get("/profile-projection/items/{item_id}", response_model=MemoryProfileDetailResponse)
async def get_memory_profile_projection_item(item_id: str, request: Request) -> MemoryProfileDetailResponse:
    with database(request).connect() as conn:
        detail = MemoryProfileProjectionService(conn).get_detail(item_id)
    if detail is None:
        raise AppError(
            code="memory_profile_item_not_found",
            message="没有找到这条记忆详情，请刷新后重试。",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return _memory_profile_detail_response(detail)


@router.post("/profile-projection/items/{item_id}/actions", response_model=MemoryProfileActionResponse)
async def apply_memory_profile_projection_action(
    item_id: str,
    action_request: MemoryProfileActionRequest,
    request: Request,
) -> MemoryProfileActionResponse:
    if action_request.confirmed is not True:
        raise AppError(
            code="memory_profile_action_confirmation_required",
            message="需要你确认后，才会改动这条记忆。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    with database(request).connect() as conn:
        projection_service = MemoryProfileProjectionService(conn)
        target = projection_service.resolve_target(item_id)
        detail = projection_service.get_detail(item_id)
    if target is None or detail is None or target.target_id is None:
        raise AppError(
            code="memory_profile_item_not_found",
            message="这条记忆已经不可操作，请刷新后重试。",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    available_actions = {action.action for action in detail.available_actions}
    if action_request.action not in available_actions:
        raise AppError(
            code="memory_profile_action_not_available",
            message="这条记忆当前不能执行这个操作。",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    expires_at = _validated_profile_action_expiry(action_request)
    _apply_profile_action_to_target(
        request=request,
        target=target,
        detail=detail,
        action_request=action_request,
        expires_at=expires_at,
    )

    return MemoryProfileActionResponse(
        ok=True,
        message=_profile_action_message(action_request.action),
        item_id=item_id,
    )


@router.get("/receipts", response_model=MemoryReceiptResponse)
async def list_memory_receipts(
    request: Request,
    agent_run_id: str | None = None,
    limit: int = 50,
) -> MemoryReceiptResponse:
    capped_limit = max(1, min(limit, 100))
    with database(request).connect() as conn:
        receipt = MemoryReceiptService(conn).build(agent_run_id=agent_run_id, limit=capped_limit)
    return _memory_receipt_response(receipt)


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


@router.get("/graph/export-preview", response_model=MemoryGraphExportPreviewResponse)
async def export_memory_graph_preview(
    request: Request,
    format: str = "markdown",
    status: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> MemoryGraphExportPreviewResponse:
    preview_format = "json" if format == "json" else "markdown"
    store = memory_graph_store(request)
    try:
        facts = store.list_facts(status=status, query=query, limit=limit)
    finally:
        store.close()
    items = [_graph_export_item(fact) for fact in facts]
    payload = [item.model_dump() for item in items]
    json_preview = json.dumps(payload, ensure_ascii=False, indent=2)
    markdown_preview = _memory_graph_markdown_preview(items)
    record_audit(
        request,
        action="memory.graph.export_preview",
        result="success",
        reason=audit_reason(
            request,
            format=preview_format,
            status=status or "all",
            item_count=str(len(items)),
        ),
    )
    from ..utils.time import utc_now_iso

    return MemoryGraphExportPreviewResponse(
        generated_at=utc_now_iso(),
        format=preview_format,
        item_count=len(items),
        items=items,
        json_preview=json_preview,
        markdown_preview=markdown_preview,
        redaction_note=RAW_EVIDENCE_REDACTION_NOTE,
    )


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


@router.post("/graph/facts/{fact_id}/wrong", response_model=MemoryGraphFactActionResponse)
async def wrong_memory_graph_fact(fact_id: str, request: Request) -> MemoryGraphFactActionResponse:
    store = memory_graph_store(request)
    try:
        fact = store.update_status(fact_id, MemoryFactStatus.WRONG, reason="user_marked_wrong")
    finally:
        store.close()
    record_audit(
        request,
        action="memory.graph.wrong",
        result="success",
        reason=audit_reason(request, fact_id=fact_id),
    )
    return MemoryGraphFactActionResponse(fact_id=fact.id, status=fact.status.value)


@router.post("/graph/facts/{fact_id}/sensitive-block", response_model=MemoryGraphFactActionResponse)
async def sensitive_block_memory_graph_fact(fact_id: str, request: Request) -> MemoryGraphFactActionResponse:
    store = memory_graph_store(request)
    try:
        fact = store.update_status(fact_id, MemoryFactStatus.SENSITIVE_BLOCKED, reason="user_sensitive_blocked")
    finally:
        store.close()
    record_audit(
        request,
        action="memory.graph.sensitive_block",
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


@router.post("/feedback", response_model=MemoryFeedbackResponse)
async def apply_memory_feedback(
    feedback_request: MemoryFeedbackRequest,
    request: Request,
) -> MemoryFeedbackResponse:
    action_id = new_id()
    service = memory_lifecycle_service(request)
    try:
        result = service.apply_feedback(
            target_type=feedback_request.target_type,
            target_id=feedback_request.target_id,
            operation=feedback_request.operation,
            feedback_text=feedback_request.feedback_text,
            replacement_text=feedback_request.replacement_text,
            replacement_subject=feedback_request.replacement_subject,
            replacement_predicate=feedback_request.replacement_predicate,
            replacement_object=feedback_request.replacement_object,
            expires_at=feedback_request.expires_at,
            source_conversation_id=feedback_request.source_conversation_id,
            source_message_id=feedback_request.source_message_id,
            source_agent_run_id=feedback_request.source_agent_run_id,
        )
    except KeyError as exc:
        record_audit(
            request,
            action="memory.feedback.apply",
            result="failed",
            reason=audit_reason(
                request,
                code="memory_feedback_target_not_found",
                target_type=feedback_request.target_type,
                target_id=feedback_request.target_id,
            ),
        )
        raise AppError(
            code="memory_feedback_target_not_found",
            message="Memory feedback target was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"target_type": feedback_request.target_type, "target_id": feedback_request.target_id},
        ) from exc
    except MemoryLifecycleTransitionError as exc:
        error_code = str(exc) or "memory_feedback_invalid"
        record_audit(
            request,
            action="memory.feedback.apply",
            result="failed",
            reason=audit_reason(
                request,
                code=error_code,
                target_type=feedback_request.target_type,
                target_id=feedback_request.target_id,
                operation=feedback_request.operation,
            ),
        )
        raise AppError(
            code=error_code,
            message="Memory feedback could not be applied.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"operation": feedback_request.operation, "target_type": feedback_request.target_type},
        ) from exc
    finally:
        service.close()

    record_audit(
        request,
        action="memory.feedback.apply",
        result="success",
        reason=audit_reason(
            request,
            target_type=result.target_type,
            target_id=result.target_id,
            operation=result.operation,
            feedback_event_id=result.feedback_event_id,
        ),
    )
    action = record_agent_action(
        request,
        AgentActionCreate(
            action_id=action_id,
            action_type="memory.feedback.apply",
            title="Memory feedback applied",
            summary=f"{result.operation} {result.target_type}:{result.target_id} -> {result.status.value}",
            source_agent_run_id=feedback_request.source_agent_run_id,
            source_conversation_id=feedback_request.source_conversation_id,
            source_message_id=feedback_request.source_message_id,
            risk_tier="low",
            decision="auto",
            status="completed",
            target_paths=(),
            metadata=_memory_feedback_action_metadata(feedback_request, result),
            reversible=False,
        ),
    )
    _link_memory_feedback_event_to_action(request, feedback_event_id=result.feedback_event_id, action_id=action.action_id)
    return MemoryFeedbackResponse(
        target_type=result.target_type,
        target_id=result.target_id,
        operation=result.operation,
        status=result.status.value,
        feedback_event_id=result.feedback_event_id,
        replacement_target_id=result.replacement_target_id,
        action_id=action.action_id,
    )


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


@router.get("/reviews/weekly", response_model=MemoryReviewResponse)
async def get_weekly_memory_review(
    request: Request,
    days: int = 7,
    limit: int = 30,
) -> MemoryReviewResponse:
    window_days = max(1, min(days, 31))
    item_limit = max(1, min(limit, 100))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    with database(request).connect() as conn:
        candidate_rows = conn.execute(
            """
            SELECT *
            FROM memory_candidates
            WHERE created_at >= ? OR updated_at >= ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (cutoff, cutoff, item_limit),
        ).fetchall()
        fact_rows = conn.execute(
            """
            SELECT *
            FROM memory_graph_facts
            WHERE created_at >= ? OR updated_at >= ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (cutoff, cutoff, item_limit),
        ).fetchall()
    items = [
        *[_memory_review_candidate_item(row) for row in candidate_rows],
        *[_memory_review_fact_item(row) for row in fact_rows],
    ]
    items.sort(key=lambda item: (item.updated_at, item.review_id), reverse=True)
    items = items[:item_limit]
    summary_counts = {"kept": 0, "temporary": 0, "ignored": 0}
    for item in items:
        summary_counts[item.category] += 1
    record_audit(
        request,
        action="memory.review.read",
        result="success",
        reason=audit_reason(request, days=str(window_days), item_count=str(len(items))),
    )
    return MemoryReviewResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        window_days=window_days,
        summary=MemoryReviewSummaryResponse(**summary_counts),
        items=items,
    )


@router.post("/reviews/weekly/actions", response_model=MemoryFeedbackResponse)
async def apply_weekly_memory_review_action(
    action_request: MemoryReviewActionRequest,
    request: Request,
) -> MemoryFeedbackResponse:
    operation = "make_temporary" if action_request.action == "only_this_week" else action_request.action
    expires_at = None
    if action_request.action == "only_this_week":
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    response = await apply_memory_feedback(
        MemoryFeedbackRequest(
            target_type=action_request.target_type,
            target_id=action_request.target_id,
            operation=operation,
            feedback_text=action_request.feedback_text or f"weekly_review:{action_request.action}",
            replacement_text=action_request.replacement_text,
            replacement_subject=action_request.replacement_subject,
            replacement_predicate=action_request.replacement_predicate,
            replacement_object=action_request.replacement_object,
            expires_at=expires_at,
        ),
        request,
    )
    record_audit(
        request,
        action="memory.review.action",
        result="success",
        reason=audit_reason(
            request,
            target_type=action_request.target_type,
            target_id=action_request.target_id,
            action=action_request.action,
            feedback_event_id=response.feedback_event_id,
        ),
    )
    return response


@router.get("/retrospectives", response_model=RetrospectiveResponse)
async def get_retrospectives(request: Request) -> RetrospectiveResponse:
    service = retrospective_service(request)
    try:
        windows = service.build_windows()
    finally:
        service.close()
        if service.agent_actions is not None:
            service.agent_actions.close()
    record_audit(
        request,
        action="memory.retrospective.read",
        result="success",
        reason=audit_reason(request, windows="1,7,30,90"),
    )
    from ..utils.time import utc_now_iso

    return RetrospectiveResponse(generated_at=utc_now_iso(), windows=windows)


@router.post("/retrospectives/report", response_model=RetrospectiveReportResponse)
async def write_retrospective_report(
    report_request: RetrospectiveReportRequest,
    request: Request,
) -> RetrospectiveReportResponse:
    service = retrospective_service(request)
    try:
        response = (
            service.write_period_report(report_request.period)
            if report_request.period is not None
            else service.write_report(report_request.days)
        )
    except RuntimeError as exc:
        if str(exc) == "retrospective_report_requires_vault":
            raise AppError(
                code="vault_not_configured",
                message="生成 Markdown 回顾报告前需要先配置活动 Vault。",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        raise
    finally:
        service.close()
        if service.agent_actions is not None:
            service.agent_actions.close()
    record_audit(
        request,
        action="memory.retrospective.report.write",
        result="success",
        target_path=response.page.relative_path,
        reason=audit_reason(
            request,
            days=str(report_request.days),
            period=report_request.period or "days",
            action_id=response.action.action_id,
        ),
    )
    return response


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
        lifecycle_status=_graph_lifecycle_status(fact.status.value),
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


def _memory_profile_projection_response(projection: MemoryProfileProjection) -> MemoryProfileProjectionResponse:
    return MemoryProfileProjectionResponse(
        generated_at=projection.generated_at,
        identity=[_memory_profile_projection_item_response(item) for item in projection.identity],
        preferences=[_memory_profile_projection_item_response(item) for item in projection.preferences],
        boundaries=[_memory_profile_projection_item_response(item) for item in projection.boundaries],
        projects=[_memory_profile_projection_item_response(item) for item in projection.projects],
        relationships=[_memory_profile_projection_item_response(item) for item in projection.relationships],
        recent_state=[_memory_profile_projection_item_response(item) for item in projection.recent_state],
        conflicts=[_memory_profile_projection_item_response(item) for item in projection.conflicts],
        needs_confirmation=[_memory_profile_projection_item_response(item) for item in projection.needs_confirmation],
        filtered=[_memory_profile_projection_item_response(item) for item in projection.filtered],
    )


def _memory_profile_projection_item_response(item: MemoryProfileProjectionItem) -> MemoryProfileProjectionItemResponse:
    return MemoryProfileProjectionItemResponse(
        id=item.id,
        category=item.category,
        summary=item.summary,
        confidence=item.confidence,
        importance=item.importance,
        status_label=item.status_label,
        risk_label=item.risk_label,
        source_label=item.source_label,
        updated_at=item.updated_at,
        permissions_summary=item.permissions_summary,
        can_revoke=item.can_revoke,
        available_actions=item.available_actions,
    )


def _memory_profile_detail_response(detail: MemoryProfileProjectionDetail) -> MemoryProfileDetailResponse:
    return MemoryProfileDetailResponse(
        id=detail.id,
        summary=detail.summary,
        category_label=detail.category_label,
        status_label=detail.status_label,
        confidence_label=detail.confidence_label,
        importance_label=detail.importance_label,
        source_label=detail.source_label,
        permissions=detail.permissions,
        safety_note=detail.safety_note,
        updated_at=detail.updated_at,
        source_summary=_memory_profile_source_summary_response(detail.source_summary),
        available_actions=[_memory_profile_action_response(action) for action in detail.available_actions],
    )


def _memory_profile_source_summary_response(
    summary: MemoryProfileProjectionSourceSummary | None,
) -> MemoryProfileSourceSummaryResponse | None:
    if summary is None:
        return None
    return MemoryProfileSourceSummaryResponse(
        label=summary.label,
        description=summary.description,
        evidence_count_label=summary.evidence_count_label,
        last_seen_label=summary.last_seen_label,
        safety_note=summary.safety_note,
    )


def _memory_profile_action_response(action: MemoryProfileProjectionAction) -> MemoryProfileAvailableActionResponse:
    return MemoryProfileAvailableActionResponse(
        action=action.action,  # type: ignore[arg-type]
        label=action.label,
        requires_confirmation=action.requires_confirmation,
    )


def _profile_feedback_operation(action: str) -> str:
    mapping = {
        "forget": "forget",
        "keep": "keep",
        "make_temporary": "make_temporary",
        "mark_stale": "mark_stale",
        "mark_inaccurate": "reject_candidate",
    }
    return mapping[action]


def _validated_profile_action_expiry(action_request: MemoryProfileActionRequest) -> str | None:
    if action_request.action != "make_temporary":
        return None
    value = (action_request.expires_at or "").strip()
    if not value:
        raise AppError(
            code="memory_profile_action_expiry_required",
            message="暂时保留需要设置一个有效的到期时间。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AppError(
            code="memory_profile_action_expiry_invalid",
            message="暂时保留的到期时间格式不正确。",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed <= datetime.now(timezone.utc):
        raise AppError(
            code="memory_profile_action_expiry_in_past",
            message="暂时保留的到期时间需要晚于现在。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return value


def _apply_profile_action_to_target(
    *,
    request: Request,
    target: MemoryProfileProjectionTarget,
    detail: MemoryProfileProjectionDetail,
    action_request: MemoryProfileActionRequest,
    expires_at: str | None,
) -> None:
    action_id = new_id()
    try:
        if target.target_type == "fact" and action_request.action == "mark_inaccurate":
            store = memory_graph_store(request)
            try:
                store.update_status(target.target_id, MemoryFactStatus.WRONG, reason="user_marked_wrong")
            finally:
                store.close()
            feedback_event_id = None
        else:
            operation = _profile_feedback_operation(action_request.action)
            service = memory_lifecycle_service(request)
            try:
                result = service.apply_feedback(
                    target_type=target.target_type,  # type: ignore[arg-type]
                    target_id=target.target_id or "",
                    operation=operation,  # type: ignore[arg-type]
                    feedback_text=_profile_action_feedback_text(action_request.action),
                    expires_at=expires_at,
                )
            finally:
                service.close()
            feedback_event_id = result.feedback_event_id
    except (KeyError, MemoryLifecycleTransitionError, ValueError) as exc:
        record_audit(
            request,
            action="memory.profile.action",
            result="failed",
            reason=audit_reason(request, profile_action=action_request.action, code="memory_profile_action_failed"),
        )
        raise AppError(
            code="memory_profile_action_failed",
            message="这次没有改动记忆，请稍后重试。",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc

    action = record_agent_action(
        request,
        AgentActionCreate(
            action_id=action_id,
            action_type="memory.profile.action",
            title="画像记忆已更新",
            summary=_profile_action_agent_summary(action_request.action),
            risk_tier="low",
            decision="auto",
            status="completed",
            target_paths=(),
            metadata={
                "profile_item_id": target.item.id,
                "profile_action": action_request.action,
                "category_label": detail.category_label,
                "status_label": detail.status_label,
            },
            reversible=False,
        ),
    )
    if feedback_event_id:
        _link_memory_feedback_event_to_action(request, feedback_event_id=feedback_event_id, action_id=action.action_id)
    record_audit(
        request,
        action="memory.profile.action",
        result="success",
        reason=audit_reason(request, profile_action=action_request.action),
    )


def _profile_action_feedback_text(action: str) -> str:
    labels = {
        "forget": "用户从画像详情中撤回",
        "mark_inaccurate": "用户从画像详情中标记不准确",
        "keep": "用户从画像详情中确认记住",
        "make_temporary": "用户从画像详情中设为临时",
        "mark_stale": "用户从画像详情中标记过期",
    }
    return labels.get(action, "用户从画像详情中管理记忆")


def _profile_action_agent_summary(action: str) -> str:
    labels = {
        "forget": "已撤回一条画像记忆",
        "mark_inaccurate": "已标记一条画像记忆不准确",
        "keep": "已确认一条画像记忆",
        "make_temporary": "已将一条画像记忆设为临时",
        "mark_stale": "已标记一条画像记忆可能过期",
    }
    return labels.get(action, "已更新一条画像记忆")


def _profile_action_message(action: str) -> str:
    messages = {
        "forget": "已撤回这条记忆，我不会再把它作为当前画像使用。",
        "mark_inaccurate": "已标记为不准确，我不会再把它作为当前画像使用。",
        "keep": "已确认记住，之后我会在合适时参考它。",
        "make_temporary": "已改为暂时保留，我只会在近期参考它。",
        "mark_stale": "已标记为可能过时，我会减少使用并等待你再次确认。",
    }
    return messages.get(action, "已更新这条记忆。")


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


def _graph_export_item(fact) -> MemoryGraphExportItem:
    return MemoryGraphExportItem(
        fact_id=fact.id,
        category=_safe_export_value(fact.category),
        subject=_safe_export_value(fact.subject),
        predicate=_safe_export_value(fact.predicate),
        object=_safe_export_value(fact.object),
        status=fact.status.value,
        lifecycle_status=_graph_lifecycle_status(fact.status.value),
        confidence=fact.confidence,
        source_type=_safe_export_value(fact.source_type),
        support_count=fact.support_count,
        conflicts_with=fact.conflicts_with,
        superseded_by=fact.superseded_by,
        memory_type=_safe_export_optional(fact.memory_type),
        entity_type=_safe_export_optional(fact.entity_type),
        occurred_at=fact.occurred_at,
        expires_at=fact.expires_at,
        metadata=_safe_export_metadata(fact.metadata_json),
        importance=fact.importance,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
    )


def _memory_graph_markdown_preview(items: list[MemoryGraphExportItem]) -> str:
    lines = [
        "# 长期记忆导出预览",
        "",
        f"> {RAW_EVIDENCE_REDACTION_NOTE}",
        "",
    ]
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


def _safe_export_metadata(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        _safe_export_value(str(key)): _safe_export_object(value)
        for key, value in parsed.items()
    }


def _safe_export_object(value) -> object:
    if isinstance(value, str):
        return _safe_export_value(value)
    if isinstance(value, dict):
        return {
            _safe_export_value(str(key)): _safe_export_object(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_safe_export_object(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_export_value(str(value))


def _safe_export_optional(value: str | None) -> str | None:
    return _safe_export_value(value) if value is not None else None


def _safe_export_value(value: str) -> str:
    policy = evaluate_memory_content(value)
    if not policy.allowed:
        return "[redacted sensitive content]"
    return value


def _graph_lifecycle_status(status: str) -> str | None:
    if status == MemoryFactStatus.QUARANTINED.value:
        return "candidate"
    if status in {MemoryFactStatus.WRONG.value, MemoryFactStatus.SENSITIVE_BLOCKED.value}:
        return "rejected"
    if status in {
        MemoryFactStatus.CANDIDATE.value,
        MemoryFactStatus.ACTIVE.value,
        MemoryFactStatus.STALE.value,
        MemoryFactStatus.ARCHIVED.value,
        MemoryFactStatus.FORGOTTEN.value,
        MemoryFactStatus.REJECTED.value,
        MemoryFactStatus.SUPERSEDED.value,
    }:
        return status
    return None


def _memory_feedback_action_metadata(feedback_request: MemoryFeedbackRequest, result) -> dict[str, object]:
    metadata: dict[str, object] = {
        "operation": result.operation,
        "target_type": result.target_type,
        "target_id": result.target_id,
        "status": result.status.value,
        "feedback_event_id": result.feedback_event_id,
    }
    if result.replacement_target_id:
        metadata["replacement_target_id"] = result.replacement_target_id
    if feedback_request.expires_at:
        metadata["expires_at"] = feedback_request.expires_at
    if feedback_request.replacement_subject:
        metadata["replacement_subject"] = feedback_request.replacement_subject
    if feedback_request.replacement_predicate:
        metadata["replacement_predicate"] = feedback_request.replacement_predicate
    return metadata


def _link_memory_feedback_event_to_action(request: Request, *, feedback_event_id: str, action_id: str) -> None:
    with database(request).connect() as conn:
        with conn:
            conn.execute(
                "UPDATE memory_feedback_events SET agent_action_id = ? WHERE id = ?",
                (action_id, feedback_event_id),
            )


def _memory_review_candidate_item(row) -> MemoryReviewItemResponse:
    category = _memory_review_category(
        status=str(row["status"]),
        memory_kind=str(row["memory_kind"]),
        memory_scope=str(row["memory_scope"]),
        expires_at=row["expires_at"],
        target_type="candidate",
    )
    summary = _safe_review_summary(str(row["summary"]))
    return MemoryReviewItemResponse(
        review_id=f"candidate:{row['id']}",
        target_type="candidate",
        target_id=str(row["id"]),
        category=category,
        summary=summary,
        memory_kind=str(row["memory_kind"]),
        memory_scope=str(row["memory_scope"]),
        lifecycle_status=str(row["status"]),
        risk_tier=str(row["risk_tier"]),
        confidence=float(row["confidence"]),
        importance=float(row["importance"]),
        evidence_count=int(row["evidence_count"]),
        expires_at=row["expires_at"],
        updated_at=str(row["updated_at"]),
        source=str(row["source_track"]),
        allowed_actions=_memory_review_allowed_actions(
            target_type="candidate",
            status=str(row["status"]),
            memory_kind=str(row["memory_kind"]),
        ),
    )


def _memory_review_fact_item(row) -> MemoryReviewItemResponse:
    memory_kind = row["memory_type"] or row["category"]
    lifecycle_status = _graph_lifecycle_status(str(row["status"])) or str(row["status"])
    category = _memory_review_category(
        status=lifecycle_status,
        memory_kind=str(memory_kind or ""),
        memory_scope=None,
        expires_at=row["expires_at"],
        target_type="fact",
    )
    summary = _safe_review_summary(f"{row['subject']} {row['predicate']} {row['object']}")
    return MemoryReviewItemResponse(
        review_id=f"fact:{row['id']}",
        target_type="fact",
        target_id=str(row["id"]),
        category=category,
        summary=summary,
        memory_kind=str(memory_kind) if memory_kind else None,
        memory_scope=None,
        lifecycle_status=lifecycle_status,
        risk_tier=None,
        confidence=float(row["confidence"]),
        importance=float(row["importance"]),
        evidence_count=int(row["support_count"]),
        expires_at=row["expires_at"],
        updated_at=str(row["updated_at"]),
        source=str(row["source_type"]),
        allowed_actions=_memory_review_allowed_actions(
            target_type="fact",
            status=lifecycle_status,
            memory_kind=str(memory_kind or ""),
        ),
    )


def _memory_review_category(
    *,
    status: str,
    memory_kind: str,
    memory_scope: str | None,
    expires_at: str | None,
    target_type: str,
) -> str:
    if expires_at or memory_kind == "recent_state" or memory_scope == "temporary":
        return "temporary"
    if status in {"candidate", "quarantined", "rejected", "wrong", "sensitive_blocked", "forgotten"}:
        return "ignored"
    if target_type == "candidate" and status == "stale":
        return "ignored"
    return "kept"


def _memory_review_allowed_actions(*, target_type: str, status: str, memory_kind: str) -> list[str]:
    actions = ["keep", "edit", "forget", "only_this_week"]
    if target_type == "candidate" and status in {"candidate", "quarantined"}:
        actions.append("forget")
    if memory_kind == "project_context":
        actions.append("mark_completed")
    return list(dict.fromkeys(actions))


def _safe_review_summary(value: str) -> str:
    return _safe_export_value(value)


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
