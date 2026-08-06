"""记忆维护端点：整理建议（hygiene）与回顾报告（retrospectives）。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status

from ...errors import AppError
from ...models.api import (
    MemoryHygieneActionRequest,
    MemoryHygieneActionResponse,
    MemoryHygienePreviewResponse,
    MemoryHygieneSuggestionResponse,
    RetrospectiveReportRequest,
    RetrospectiveReportResponse,
    RetrospectiveResponse,
)
from ...models.common import new_id
from ...services.agent_actions import AgentActionCreate
from ...services.memory_hygiene_suggestions import (
    MemoryHygieneSuggestion,
    MemoryHygieneSuggestionConfirmationRequired,
    MemoryHygieneSuggestionExpired,
    MemoryHygieneSuggestionService,
)
from ...services.memory_lifecycle import MemoryLifecycleTransitionError
from ...services.retrospectives import RetrospectiveService
from ...utils.time import utc_now_iso
from ..wiring import audit_reason, record_agent_action, record_audit
from .dependencies import (
    memory_hygiene_suggestion_service_dependency,
    retrospective_service_dependency,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/hygiene/preview", response_model=MemoryHygienePreviewResponse)
async def preview_memory_hygiene(
    limit: int = 30,
    service: MemoryHygieneSuggestionService = Depends(memory_hygiene_suggestion_service_dependency),
) -> MemoryHygienePreviewResponse:
    suggestions = service.preview(limit=max(1, min(limit, 100)))
    return MemoryHygienePreviewResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        suggestions=[_memory_hygiene_suggestion_response(item) for item in suggestions],
    )


@router.post("/hygiene/actions", response_model=MemoryHygieneActionResponse)
async def apply_memory_hygiene_action(
    action_request: MemoryHygieneActionRequest,
    request: Request,
    service: MemoryHygieneSuggestionService = Depends(memory_hygiene_suggestion_service_dependency),
) -> MemoryHygieneActionResponse:
    action_id = new_id()
    try:
        result = service.apply(
            action_request.suggestion_id,
            confirmed=action_request.confirmed,
            agent_action_id=action_id,
        )
    except MemoryHygieneSuggestionConfirmationRequired as exc:
        raise AppError(
            code="hygiene_confirmation_required",
            message="Applying a memory hygiene suggestion requires confirmation.",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    except MemoryHygieneSuggestionExpired as exc:
        raise AppError(
            code="hygiene_suggestion_expired",
            message="This memory hygiene suggestion is no longer available.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    except (KeyError, MemoryLifecycleTransitionError, ValueError) as exc:
        raise AppError(
            code="hygiene_suggestion_apply_failed",
            message="The memory hygiene suggestion could not be applied.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc
    action = record_agent_action(
        request,
        AgentActionCreate(
            action_id=action_id,
            action_type="memory.hygiene.apply",
            title="记忆整理建议已应用",
            summary=_memory_hygiene_action_summary(result.type),
            risk_tier="low",
            decision="notify",
            status="completed",
            target_paths=(),
            metadata={
                "suggestion_type": result.type,
                "suggestion_id": result.suggestion_id,
                "result_status": result.status,
                "safe_summary": True,
            },
            reversible=False,
        ),
    )
    record_audit(
        request,
        action="memory.hygiene.apply",
        result="success",
        reason=audit_reason(request, suggestion_type=result.type, status=result.status),
    )
    return MemoryHygieneActionResponse(
        ok=True,
        suggestion_id=result.suggestion_id,
        type=result.type,
        status=result.status,
        action_id=action.action_id,
    )


@router.get("/retrospectives", response_model=RetrospectiveResponse)
async def get_retrospectives(
    request: Request,
    service: RetrospectiveService = Depends(retrospective_service_dependency),
) -> RetrospectiveResponse:
    windows = service.build_windows()
    record_audit(
        request,
        action="memory.retrospective.read",
        result="success",
        reason=audit_reason(request, windows="1,7,30,90"),
    )
    return RetrospectiveResponse(generated_at=utc_now_iso(), windows=windows)


@router.post("/retrospectives/report", response_model=RetrospectiveReportResponse)
async def write_retrospective_report(
    report_request: RetrospectiveReportRequest,
    request: Request,
    service: RetrospectiveService = Depends(retrospective_service_dependency),
) -> RetrospectiveReportResponse:
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


def _memory_hygiene_suggestion_response(item: MemoryHygieneSuggestion) -> MemoryHygieneSuggestionResponse:
    return MemoryHygieneSuggestionResponse(
        id=item.id,
        type=item.type,
        title=item.title,
        summary=item.summary,
        impact=item.impact,
        risk_tier=item.risk_tier,
        destructive=item.destructive,
        requires_confirmation=item.requires_confirmation,
        action_label=item.action_label,
    )


def _memory_hygiene_action_summary(suggestion_type: str) -> str:
    labels = {
        "stale_recent_state": "已归档一条过期的临时状态。",
        "low_confidence_stale": "已忽略一条长期未确认的低置信候选。",
        "sensitive_candidate": "已安全拒绝一条不适合保存的候选记忆。",
    }
    return labels.get(suggestion_type, "已应用一条记忆整理建议。")
